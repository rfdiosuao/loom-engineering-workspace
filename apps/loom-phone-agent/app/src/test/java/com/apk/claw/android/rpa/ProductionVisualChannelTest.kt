package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.VisualAnchorSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ProductionVisualChannelTest {
    @get:Rule
    val temporary = TemporaryFolder()

    @Test
    fun constructor_requires_exact_safe_template_namespace_and_positive_revision() {
        val reader = VisualAssetReader { _, _, _ -> null }
        val decoder = VisualAssetDecoder { null }

        assertThrows(IllegalArgumentException::class.java) {
            ProductionVisualChannel("../template", 1, 30, reader, decoder)
        }
        assertThrows(IllegalArgumentException::class.java) {
            ProductionVisualChannel("template", 0, 30, reader, decoder)
        }
    }

    @Test
    fun exact_match_reads_only_the_run_template_revision_and_keeps_declared_offsets() {
        val reads = mutableListOf<Triple<String, Int, String>>()
        val identity = Any()
        val frame = frameWithAnchor()
        val channel = ProductionVisualChannel(
            templateId = "template-a",
            revision = 4,
            apiLevel = 30,
            assetReader = VisualAssetReader { templateId, revision, assetName ->
                reads += Triple(templateId, revision, assetName)
                byteArrayOf(1, 2, 3)
            },
            decoder = VisualAssetDecoder { anchor() }
        )

        val result = channel.resolve(ResolverKind.VISUAL_ANCHOR, visualStep(), evidence(frame, identity))
            as Resolution.Ready
        val payload = result.payload as VisualDispatchPayload

        assertEquals(listOf(Triple("template-a", 4, "anchor.webp")), reads)
        assertEquals(IntRect(7, 8, 10, 11), payload.bounds)
        assertEquals(0.25f, payload.tapOffsetX)
        assertEquals(0.75f, payload.tapOffsetY)
        assertEquals(VisualPlatformAction.TAP, payload.action)
        assertTrue(payload.sameServiceIdentity(evidence(frame, identity)))
        assertFalse(payload.sameServiceIdentity(evidence(frame, Any())))
        assertEquals("demo.app", result.evidence.packageName)
        assertEquals(3, result.evidence.windowId)
        assertTrue(result.evidence.matches(evidence(frame, identity)))
        assertFalse(result.evidence.matches(evidence(frame, Any())))
        assertFalse(result.evidence.matches(evidence(frame, identity, packageName = "other.app")))
        assertFalse(result.evidence.matches(evidence(frame, identity, windowId = 4)))
    }

    @Test
    fun store_reader_has_no_cross_template_or_revision_fallback_and_detects_corruption() {
        val root = temporary.newFolder("assets")
        val store = VisualAssetStore(root)
        val bytes = webp(7)
        store.writeAsset("template-a", 1, "anchor.webp", bytes, TemplateStatus.ACTIVE)
        val decoder = VisualAssetDecoder { anchor() }

        fun result(templateId: String, revision: Int): Resolution = ProductionVisualChannel(
            templateId,
            revision,
            30,
            StoreVisualAssetReader(store),
            decoder
        ).resolve(ResolverKind.VISUAL_ANCHOR, visualStep(), evidence(frameWithAnchor()))

        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_ASSET_MISSING,
            (result("template-b", 1) as Resolution.Handoff).errorCode
        )
        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_ASSET_MISSING,
            (result("template-a", 2) as Resolution.Handoff).errorCode
        )

        java.io.File(root, "assets/template-a/r1/anchor.webp").writeBytes(webp(9))
        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_ASSET_MISSING,
            (result("template-a", 1) as Resolution.Handoff).errorCode
        )
    }

    @Test
    fun oversized_or_undecodable_asset_fails_closed_before_matching() {
        var decodeCalls = 0
        val oversized = ProductionVisualChannel(
            "template-a",
            1,
            30,
            VisualAssetReader { _, _, _ -> ByteArray(ProductionVisualChannel.MAX_RUNTIME_ASSET_BYTES + 1) },
            VisualAssetDecoder { decodeCalls++; anchor() }
        )
        val undecodable = ProductionVisualChannel(
            "template-a",
            1,
            30,
            VisualAssetReader { _, _, _ -> byteArrayOf(1) },
            VisualAssetDecoder { null }
        )

        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_ASSET_OVERSIZED,
            (oversized.resolve(ResolverKind.VISUAL_ANCHOR, visualStep(), evidence(frameWithAnchor())) as Resolution.Handoff).errorCode
        )
        assertEquals(0, decodeCalls)
        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_ASSET_DECODE_FAILED,
            (undecodable.resolve(ResolverKind.VISUAL_ANCHOR, visualStep(), evidence(frameWithAnchor())) as Resolution.Handoff).errorCode
        )
    }

    @Test
    fun api24_cached_stale_missing_plane_and_below_threshold_never_return_targets() {
        var reads = 0
        fun channel(api: Int = 30) = ProductionVisualChannel(
            "template-a",
            1,
            api,
            VisualAssetReader { _, _, _ -> reads++; byteArrayOf(1) },
            VisualAssetDecoder { anchor() }
        )

        val api24 = channel(24).resolve(ResolverKind.VISUAL_ANCHOR, visualStep(), evidence(frameWithAnchor()))
        assertEquals("visual_capture_unsupported", (api24 as Resolution.Handoff).errorCode)
        listOf("cache", "stale_fallback").forEach { source ->
            val result = channel().resolve(
                ResolverKind.VISUAL_ANCHOR,
                visualStep(),
                evidence(frameWithAnchor(), frameSource = source)
            )
            assertEquals(ProductionVisualChannel.ERROR_VISUAL_EVIDENCE_UNAVAILABLE, (result as Resolution.Handoff).errorCode)
        }
        val missing = channel().resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep(),
            evidence(null)
        )
        assertEquals(ProductionVisualChannel.ERROR_VISUAL_EVIDENCE_UNAVAILABLE, (missing as Resolution.Handoff).errorCode)
        val futureFrame = channel().resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep(),
            evidence(frameWithAnchor(), frameCapturedAt = 1_101L)
        )
        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_EVIDENCE_UNAVAILABLE,
            (futureFrame as Resolution.Handoff).errorCode
        )
        val wrongDimensions = channel().resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep(),
            evidence(
                frameWithAnchor(),
                transform = DisplayTransform(0, 21, 20, 20, 20, 0, 420, 0, 0, 0, 0)
            )
        )
        assertEquals(
            ProductionVisualChannel.ERROR_VISUAL_EVIDENCE_UNAVAILABLE,
            (wrongDimensions as Resolution.Handoff).errorCode
        )

        val below = channel().resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep().copy(visualAnchor = visualStep().visualAnchor!!.copy(minimumConfidence = 1f)),
            evidence(LumaPlane(20, 20, IntArray(400) { 255 }))
        )
        assertTrue(below is Resolution.Missing)
        assertTrue(reads > 0)
    }

    @Test
    fun normalized_swipe_and_drag_are_explicit_handoffs_without_asset_reads() {
        var reads = 0
        val channel = ProductionVisualChannel(
            "template-a",
            1,
            30,
            VisualAssetReader { _, _, _ -> reads++; byteArrayOf(1) },
            VisualAssetDecoder { anchor() }
        )
        val normalized = channel.resolve(ResolverKind.NORMALIZED_COORDINATE, visualStep(), evidence(frameWithAnchor()))
        val swipe = channel.resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep().copy(action = "swipe_normalized"),
            evidence(frameWithAnchor())
        )
        val drag = channel.resolve(
            ResolverKind.VISUAL_ANCHOR,
            visualStep().copy(action = "drag_normalized"),
            evidence(frameWithAnchor())
        )

        assertEquals(ProductionVisualChannel.ERROR_NORMALIZED_COORDINATE_UNPROVED, (normalized as Resolution.Handoff).errorCode)
        assertEquals(ProductionVisualChannel.ERROR_ACTION_ADAPTER_UNAVAILABLE, (swipe as Resolution.Handoff).errorCode)
        assertEquals(ProductionVisualChannel.ERROR_ACTION_ADAPTER_UNAVAILABLE, (drag as Resolution.Handoff).errorCode)
        assertEquals(0, reads)
    }

    private fun visualStep() = RpaStep(
        id = "step-1",
        action = "tap_anchor",
        resolverPolicy = ResolverPolicy.VISION_REQUIRED,
        allowedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        validatedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        visualAnchor = VisualAnchorSpec(
            "anchor.webp",
            NormalizedRect(0f, 0f, 1f, 1f),
            0.25f,
            0.75f,
            minimumConfidence = 0.99f,
            scaleVariants = listOf(1f)
        )
    )

    private fun evidence(
        plane: LumaPlane?,
        identity: Any = Any(),
        frameSource: String = "fresh",
        frameCapturedAt: Long = 1_050L,
        transform: DisplayTransform = DisplayTransform(0, 20, 20, 20, 20, 0, 420, 0, 0, 0, 0),
        packageName: String = "demo.app",
        windowId: Int = 3
    ) = UiEvidence(
        uiGeneration = 7L,
        serviceGeneration = "service-1",
        packageName = packageName,
        windowId = windowId,
        capturedAt = 1_100L,
        transform = transform,
        compactTree = null,
        frameId = "frame-1",
        frameSource = frameSource,
        frameCapturedAt = frameCapturedAt,
        frameAgeMs = 50L,
        lumaPlane = plane,
        runtimeServiceIdentity = identity
    )

    private fun anchor() = LumaPlane(3, 3, intArrayOf(10, 20, 30, 40, 50, 60, 70, 80, 90))

    private fun frameWithAnchor(): LumaPlane {
        val pixels = IntArray(20 * 20)
        val anchor = anchor().toIntArray()
        for (y in 0 until 3) for (x in 0 until 3) pixels[(8 + y) * 20 + 7 + x] = anchor[y * 3 + x]
        return LumaPlane(20, 20, pixels)
    }

    private fun webp(payload: Int): ByteArray {
        val raster = byteArrayOf(0x2f, 0, 0, 0, 0, payload.toByte())
        val padding = if (raster.size and 1 == 1) byteArrayOf(0) else byteArrayOf()
        val chunk = ascii("VP8L") + littleEndian(raster.size) + raster + padding
        val body = ascii("WEBP") + chunk
        return ascii("RIFF") + littleEndian(body.size) + body
    }

    private fun ascii(value: String) = value.map { it.code.toByte() }.toByteArray()
    private fun littleEndian(value: Int) = byteArrayOf(
        value.toByte(), (value ushr 8).toByte(), (value ushr 16).toByte(), (value ushr 24).toByte()
    )
}
