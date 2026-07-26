package com.apk.claw.android.rpa

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.apk.claw.android.workflow.ResolverKind

fun interface VisualAssetReader {
    fun read(templateId: String, revision: Int, assetName: String): ByteArray?
}

class StoreVisualAssetReader(
    private val store: VisualAssetStore
) : VisualAssetReader {
    override fun read(templateId: String, revision: Int, assetName: String): ByteArray? =
        runCatching { store.readAsset(templateId, revision, assetName) }.getOrNull()
}

fun interface VisualAssetDecoder {
    fun decode(webpBytes: ByteArray): LumaPlane?
}

object AndroidVisualAssetDecoder : VisualAssetDecoder {
    override fun decode(webpBytes: ByteArray): LumaPlane? {
        if (webpBytes.size !in 1..ProductionVisualChannel.MAX_RUNTIME_ASSET_BYTES) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        runCatching { BitmapFactory.decodeByteArray(webpBytes, 0, webpBytes.size, bounds) }
            .getOrNull()
        val width = bounds.outWidth
        val height = bounds.outHeight
        if (!isBoundedAnchor(width, height)) return null

        val options = BitmapFactory.Options().apply {
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val bitmap = runCatching {
            BitmapFactory.decodeByteArray(webpBytes, 0, webpBytes.size, options)
        }.getOrNull() ?: return null
        return try {
            if (bitmap.width != width || bitmap.height != height || !isBoundedAnchor(bitmap.width, bitmap.height)) {
                null
            } else {
                BitmapLumaAdapter.fromBitmap(bitmap)
            }
        } finally {
            if (!bitmap.isRecycled) bitmap.recycle()
        }
    }

    private fun isBoundedAnchor(width: Int, height: Int): Boolean =
        width > 0 && height > 0 &&
            width.toLong() * height.toLong() <= ProductionVisualChannel.MAX_RUNTIME_ANCHOR_PIXELS
}

class ProductionVisualChannel(
    private val templateId: String,
    private val revision: Int,
    private val apiLevel: Int,
    private val assetReader: VisualAssetReader,
    private val decoder: VisualAssetDecoder,
    private val clock: () -> Long = System::currentTimeMillis
) : VisualChannel {
    init {
        require(TEMPLATE_ID_PATTERN.matches(templateId) && templateId != "." && templateId != "..") {
            "visual_template_id_invalid"
        }
        require(revision > 0) { "visual_template_revision_invalid" }
    }

    override fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution {
        if (kind == ResolverKind.NORMALIZED_COORDINATE) {
            return Resolution.Handoff(ERROR_NORMALIZED_COORDINATE_UNPROVED)
        }
        if (kind != ResolverKind.VISUAL_ANCHOR) {
            return Resolution.Handoff(ERROR_VISUAL_RESOLVER_UNAVAILABLE)
        }
        val platformAction = when (step.action) {
            "tap_anchor" -> VisualPlatformAction.TAP
            "long_press_anchor" -> VisualPlatformAction.LONG_PRESS
            else -> return Resolution.Handoff(ERROR_ACTION_ADAPTER_UNAVAILABLE)
        }
        if (apiLevel < 30) return Resolution.Handoff("visual_capture_unsupported")
        val frame = evidence.validFreshPlane()
            ?: return Resolution.Handoff(ERROR_VISUAL_EVIDENCE_UNAVAILABLE)
        val spec = step.visualAnchor ?: return Resolution.Handoff(ERROR_VISUAL_SPEC_MISSING)
        val bytes = runCatching { assetReader.read(templateId, revision, spec.assetName) }.getOrNull()
            ?: return Resolution.Handoff(ERROR_VISUAL_ASSET_MISSING)
        if (bytes.size > MAX_RUNTIME_ASSET_BYTES) {
            return Resolution.Handoff(ERROR_VISUAL_ASSET_OVERSIZED)
        }
        if (bytes.isEmpty()) return Resolution.Handoff(ERROR_VISUAL_ASSET_DECODE_FAILED)
        val anchor = runCatching { decoder.decode(bytes) }.getOrNull()
            ?: return Resolution.Handoff(ERROR_VISUAL_ASSET_DECODE_FAILED)
        if (anchor.width.toLong() * anchor.height.toLong() > MAX_RUNTIME_ANCHOR_PIXELS) {
            return Resolution.Handoff(ERROR_VISUAL_ASSET_OVERSIZED)
        }

        val startedAt = safeNow()
        val match = runCatching { VisualAnchorMatcher.match(frame, anchor, spec) }
            .getOrElse { VisualMatch.Invalid("matcher_exception") }
        val measuredMs = elapsed(startedAt, safeNow())
        return when (match) {
            is VisualMatch.Found -> {
                val bounds = IntRect(
                    match.left,
                    match.top,
                    match.left + match.width,
                    match.top + match.height
                )
                if (!isBounded(bounds, evidence.transform)) {
                    Resolution.Handoff(ERROR_VISUAL_MATCH_BOUNDS_INVALID)
                } else {
                    Resolution.Ready(
                        payload = VisualDispatchPayload(
                            bounds = bounds,
                            tapOffsetX = spec.tapOffsetX,
                            tapOffsetY = spec.tapOffsetY,
                            action = platformAction,
                            durationMs = step.longPressDurationMs(),
                            evidence = evidence,
                            preCheckpoint = step.preCheckpoint,
                            postCheckpoint = step.postCheckpoint
                        ),
                        resolverUsed = ResolverKind.VISUAL_ANCHOR,
                        evidence = ResolutionEvidence.from(evidence),
                        confidence = match.confidence,
                        metrics = ResolutionMetrics(matchMs = maxOf(measuredMs, match.matchMs))
                    )
                }
            }
            is VisualMatch.BelowThreshold -> Resolution.Missing(ResolverKind.VISUAL_ANCHOR)
            is VisualMatch.Invalid -> Resolution.Handoff(ERROR_VISUAL_MATCH_INVALID)
        }
    }

    private fun UiEvidence.validFreshPlane(): LumaPlane? {
        val plane = runtimeLumaPlane() ?: return null
        val frameTime = frameCapturedAt ?: return null
        val age = frameAgeMs ?: return null
        if (frameSource != "fresh" || frameId.isNullOrBlank() || frameTime > capturedAt || age < 0L) return null
        if (age != (capturedAt - frameTime).coerceAtLeast(0L)) return null
        if (!hasRuntimeServiceIdentity()) return null
        if (transform.screenshotWidthPx != plane.width || transform.screenshotHeightPx != plane.height) return null
        if (transform.widthPx != plane.width || transform.heightPx != plane.height) return null
        return plane
    }

    private fun RpaStep.longPressDurationMs(): Long {
        if (action != "long_press_anchor") return DEFAULT_TAP_DURATION_MS
        val value = params["duration_ms"] ?: params["durationMs"] ?: return DEFAULT_LONG_PRESS_DURATION_MS
        val duration = (value as? Number)?.toLong() ?: return DEFAULT_LONG_PRESS_DURATION_MS
        return duration.coerceIn(MIN_LONG_PRESS_DURATION_MS, MAX_LONG_PRESS_DURATION_MS)
    }

    private fun isBounded(bounds: IntRect, transform: DisplayTransform): Boolean =
        bounds.left >= 0 && bounds.top >= 0 &&
            bounds.right > bounds.left && bounds.bottom > bounds.top &&
            bounds.right <= transform.widthPx && bounds.bottom <= transform.heightPx

    private fun safeNow(): Long = runCatching(clock).getOrDefault(0L).coerceAtLeast(0L)

    private fun elapsed(startedAt: Long, finishedAt: Long): Long = when {
        finishedAt <= startedAt -> 0L
        finishedAt - startedAt < 0L -> Long.MAX_VALUE
        else -> finishedAt - startedAt
    }

    companion object {
        const val MAX_RUNTIME_ASSET_BYTES = VisualAssetStore.MAX_ASSET_BYTES
        const val MAX_RUNTIME_ANCHOR_PIXELS = 1_048_576L
        const val ERROR_VISUAL_EVIDENCE_UNAVAILABLE = "visual_evidence_unavailable"
        const val ERROR_VISUAL_ASSET_MISSING = "visual_asset_missing"
        const val ERROR_VISUAL_ASSET_OVERSIZED = "visual_asset_oversized"
        const val ERROR_VISUAL_ASSET_DECODE_FAILED = "visual_asset_decode_failed"
        const val ERROR_VISUAL_BELOW_THRESHOLD = "visual_below_threshold"
        const val ERROR_VISUAL_MATCH_INVALID = "visual_match_invalid"
        const val ERROR_VISUAL_MATCH_BOUNDS_INVALID = "visual_match_bounds_invalid"
        const val ERROR_VISUAL_SPEC_MISSING = "visual_spec_missing"
        const val ERROR_VISUAL_RESOLVER_UNAVAILABLE = "visual_resolver_unavailable"
        const val ERROR_NORMALIZED_COORDINATE_UNPROVED = "normalized_coordinate_unproved"
        const val ERROR_ACTION_ADAPTER_UNAVAILABLE = "action_adapter_unavailable"

        private const val DEFAULT_TAP_DURATION_MS = 100L
        private const val DEFAULT_LONG_PRESS_DURATION_MS = 800L
        private const val MIN_LONG_PRESS_DURATION_MS = 500L
        private const val MAX_LONG_PRESS_DURATION_MS = 5_000L
        private val TEMPLATE_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    }
}
