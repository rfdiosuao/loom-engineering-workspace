package com.apk.claw.android.rpa

import android.content.Context
import android.graphics.Bitmap
import android.view.Display
import android.view.Surface
import android.view.WindowManager
import com.apk.claw.android.agent.ScreenObservationBuilder
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.service.ScreenshotFrame
import com.google.gson.JsonObject

internal data class GenerationCaptureCandidate<F : AutoCloseable, V>(
    val frame: F?,
    val value: V
)

internal class DetachedFrameOwnership<F : AutoCloseable, B, P>(
    private val detach: (F) -> B?,
    private val convert: (B) -> P,
    private val dispose: (B) -> Unit
) {
    fun <V> capture(frame: F?, build: (P?) -> V): GenerationCaptureCandidate<F, V> {
        try {
            val converted = frame?.let { ownedFrame ->
                detach(ownedFrame)?.let { detached ->
                    try {
                        convert(detached)
                    } finally {
                        dispose(detached)
                    }
                }
            }
            return GenerationCaptureCandidate(frame, build(converted))
        } catch (error: Throwable) {
            frame?.close()
            throw error
        }
    }
}

internal class GenerationBracketedCapture<F : AutoCloseable, V>(
    private val maxAttempts: Int,
    private val snapshot: () -> GenerationSnapshot,
    private val attempt: (GenerationSnapshot) -> GenerationCaptureCandidate<F, V>
) {
    init {
        require(maxAttempts > 0) { "maxAttempts must be positive" }
    }

    fun capture(): V {
        repeat(maxAttempts) {
            val start = snapshot()
            val candidate = attempt(start)
            try {
                if (snapshot() == start) {
                    return candidate.value
                }
            } finally {
                candidate.frame?.close()
            }
        }
        throw IllegalStateException("UI generation changed during every evidence capture attempt")
    }
}

internal fun frameAgeMs(evidenceCapturedAt: Long, frameCapturedAt: Long): Long {
    return (evidenceCapturedAt - frameCapturedAt).coerceAtLeast(0L)
}

class UiEvidenceProvider(
    private val service: ClawAccessibilityService,
    private val screenshotTimeoutMs: Long = 5_000L
) {
    private val frameOwnership = DetachedFrameOwnership<ScreenshotFrame, Bitmap, LumaPlane>(
        detach = ScreenshotFrame::detachBitmap,
        convert = BitmapLumaAdapter::fromBitmap,
        dispose = { bitmap -> if (!bitmap.isRecycled) bitmap.recycle() }
    )

    fun capture(requirement: FreshnessRequirement): UiEvidence {
        return GenerationBracketedCapture<ScreenshotFrame, UiEvidence>(
            maxAttempts = MAX_EVIDENCE_CAPTURE_ATTEMPTS,
            snapshot = service::getGenerationSnapshot,
            attempt = { generation -> captureAttempt(requirement, generation) }
        ).capture()
    }

    private fun captureAttempt(
        requirement: FreshnessRequirement,
        generation: GenerationSnapshot
    ): GenerationCaptureCandidate<ScreenshotFrame, UiEvidence> {
        val frame = captureFrame(requirement)
        return frameOwnership.capture(frame) { lumaPlane ->
            val treeStartedAt = System.nanoTime()
            val tree = service.screenTreeJson?.deepCopy()
            val packageName = tree?.getAsJsonObject("screen")
                ?.get("currentPackage")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                .orEmpty()
                .ifBlank { service.currentPackageName.orEmpty() }
            val windowId = service.currentWindowId
            val transform = displayTransform(frame)
            val capturedAt = System.currentTimeMillis()
            val ageMs = frame?.let { frameAgeMs(capturedAt, it.capturedAt) }
            val compactTree = tree?.let {
                ScreenObservationBuilder.build(
                    tree = it,
                    capturedAt = capturedAt,
                    uiGeneration = generation.uiGeneration,
                    serviceGeneration = generation.serviceGeneration,
                    frameSource = frame?.source,
                    frameId = frame?.frameId,
                    frameAgeMs = ageMs
                )
            }
            val detachedCompactTree = compactTree?.deepCopy()
            val treeSnapshotMs = elapsedNanosAsMs(treeStartedAt)
            UiEvidence(
                uiGeneration = generation.uiGeneration,
                serviceGeneration = generation.serviceGeneration,
                packageName = packageName,
                windowId = windowId,
                capturedAt = capturedAt,
                transform = transform,
                compactTree = detachedCompactTree,
                frameId = frame?.frameId,
                frameSource = frame?.source,
                frameCapturedAt = frame?.capturedAt,
                frameAgeMs = ageMs,
                treeSnapshotMs = treeSnapshotMs,
                lumaPlane = lumaPlane,
                runtimeServiceIdentity = service
            )
        }
    }

    private fun captureFrame(requirement: FreshnessRequirement): ScreenshotFrame? {
        return when (requirement) {
            FreshnessRequirement.TreeRead,
            is FreshnessRequirement.TreeAfter -> null
            FreshnessRequirement.ReadOnly ->
                service.takeScreenshotFrame(screenshotTimeoutMs, 0L, true)
            is FreshnessRequirement.AuthorizeAfter ->
                service.takeScreenshotFrame(screenshotTimeoutMs, requirement.capturedAfter, false)
        }
    }

    @Suppress("DEPRECATION")
    private fun displayTransform(frame: ScreenshotFrame?): DisplayTransform {
        val metrics = service.resources.displayMetrics
        val display = (service.getSystemService(Context.WINDOW_SERVICE) as? WindowManager)?.defaultDisplay
        return DisplayTransform(
            displayId = display?.displayId ?: Display.DEFAULT_DISPLAY,
            widthPx = metrics.widthPixels,
            heightPx = metrics.heightPixels,
            screenshotWidthPx = frame?.width ?: metrics.widthPixels,
            screenshotHeightPx = frame?.height ?: metrics.heightPixels,
            rotation = display?.rotation ?: Surface.ROTATION_0,
            densityDpi = metrics.densityDpi,
            insetLeft = 0,
            insetTop = 0,
            insetRight = 0,
            insetBottom = 0
        )
    }

    private companion object {
        const val MAX_EVIDENCE_CAPTURE_ATTEMPTS = 3

        fun elapsedNanosAsMs(startedAt: Long): Long {
            val elapsed = (System.nanoTime() - startedAt).coerceAtLeast(0L)
            return if (elapsed == 0L) 0L else ((elapsed - 1L) / 1_000_000L) + 1L
        }
    }
}
