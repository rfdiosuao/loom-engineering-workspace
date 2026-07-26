package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridEvidencePolicyTest {
    @Test
    fun tree_preferred_semantic_uses_tree_read() {
        assertEquals(
            FreshnessRequirement.TreeRead,
            HybridEvidencePolicy.preResolution(treePreferredSemanticStep(), true, 200L)
        )
    }

    @Test
    fun direct_resolution_requires_full_frame_even_when_tree_is_authorized() {
        assertEquals(
            FreshnessRequirement.AuthorizeAfter(200L),
            HybridEvidencePolicy.preResolution(directStep(), true, 200L)
        )
    }

    @Test
    fun visual_and_perceptual_verification_require_full_frames() {
        assertEquals(
            EvidenceCaptureMode.FULL_FRAME,
            HybridEvidencePolicy.postVerification(visualPayload(), 200L, true).initial.captureMode
        )
        assertEquals(
            EvidenceCaptureMode.FULL_FRAME,
            HybridEvidencePolicy.postVerification(semanticPayload(perceptualCheckpoint()), 200L, true).initial.captureMode
        )
        assertEquals(
            EvidenceCaptureMode.FULL_FRAME,
            HybridEvidencePolicy.postVerification(semanticPayload(displayTransformCheckpoint()), 200L, true).initial.captureMode
        )
    }

    @Test
    fun semantic_postcondition_uses_tree_then_allows_one_escalation() {
        val plan = HybridEvidencePolicy.postVerification(semanticPayload(selectorCheckpoint()), 200L, true)

        assertEquals(FreshnessRequirement.TreeAfter(200L), plan.initial)
        assertTrue(plan.allowFrameEscalation)
    }

    @Test
    fun tree_only_requirements_are_rejected_by_screenshot_freshness_policy() {
        val evidence = evidence(frameSource = "fresh", frameCapturedAt = 201L)

        assertFalse(ScreenshotFreshnessPolicy.accepts(evidence, FreshnessRequirement.TreeRead))
        assertFalse(ScreenshotFreshnessPolicy.accepts(evidence, FreshnessRequirement.TreeAfter(200L)))
    }

    private fun treePreferredSemanticStep() = RpaStep(
        id = "step-tree",
        action = "tap",
        resolverPolicy = ResolverPolicy.TREE_PREFERRED,
        preCheckpoint = selectorCheckpoint()
    )

    private fun directStep() = RpaStep(
        id = "step-direct",
        action = "back",
        resolverPolicy = ResolverPolicy.DIRECT
    )

    private fun visualPayload(): VisualDispatchPayload {
        val current = evidence()
        return VisualDispatchPayload(
            bounds = IntRect(0, 0, 10, 10),
            tapOffsetX = 0.5f,
            tapOffsetY = 0.5f,
            action = VisualPlatformAction.TAP,
            durationMs = 100L,
            evidence = current,
            postCheckpoint = selectorCheckpoint()
        )
    }

    private fun semanticPayload(postCheckpoint: StepCheckpoint): SemanticDispatchPayload {
        val current = evidence()
        return SemanticDispatchPayload(
            resolution = SemanticResolution.Unique(
                node = CompactNode(
                    ref = "node-1",
                    resourceId = "demo:id/target",
                    className = "android.widget.Button",
                    packageName = "demo.app",
                    bounds = IntRect(10, 20, 110, 70)
                ),
                matchedBy = ResolverKind.RESOURCE_ID,
                generation = current.uiGeneration,
                serviceGeneration = current.serviceGeneration
            ),
            bounds = IntRect(10, 20, 110, 70),
            evidence = current,
            postCheckpoint = postCheckpoint
        )
    }

    private fun selectorCheckpoint() = StepCheckpoint(
        expectedPackage = "demo.app",
        requiredSelector = SemanticSelector(resourceId = "demo:id/target")
    )

    private fun perceptualCheckpoint() = StepCheckpoint(
        expectedPackage = "demo.app",
        perceptualHash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        maximumHammingDistance = 0
    )

    private fun displayTransformCheckpoint() = StepCheckpoint(
        expectedPackage = "demo.app",
        expectedDisplayTransform = DisplayTransformCheckpoint(
            displayId = 0,
            widthPx = 1080,
            heightPx = 2400,
            screenshotWidthPx = 1080,
            screenshotHeightPx = 2400,
            rotation = 0,
            densityDpi = 420,
            insetLeft = 0,
            insetTop = 0,
            insetRight = 0,
            insetBottom = 0
        )
    )

    private fun evidence(
        frameSource: String? = null,
        frameCapturedAt: Long? = null
    ) = UiEvidence(
        uiGeneration = 7L,
        serviceGeneration = "service-1",
        packageName = "demo.app",
        windowId = 3,
        capturedAt = 200L,
        transform = DisplayTransform(0, 1080, 2400, 1080, 2400, 0, 420, 0, 0, 0, 0),
        compactTree = null,
        frameId = frameSource?.let { "fresh-frame" },
        frameSource = frameSource,
        frameCapturedAt = frameCapturedAt,
        frameAgeMs = frameCapturedAt?.let { 200L - it }
    )
}
