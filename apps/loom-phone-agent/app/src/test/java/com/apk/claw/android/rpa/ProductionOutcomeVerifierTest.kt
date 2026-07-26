package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProductionOutcomeVerifierTest {
    @Test
    fun fresh_declared_package_and_selector_postcondition_is_verified_at_observed_generation() {
        var requirement: FreshnessRequirement? = null
        val identity = Any()
        val verifier = ProductionOutcomeVerifier(HybridEvidenceSource { requested ->
            requirement = requested
            evidence(identity = identity, packageName = "done.app", capturedAt = 201L)
        })
        val post = StepCheckpoint(
            expectedPackage = "done.app",
            requiredSelector = SemanticSelector(resourceId = "demo:id/target", packageName = "done.app")
        )

        val result = verifier.verify(prepared(payload(identity, postCheckpoint = post)), 200L)

        assertEquals(
            VerificationResult.EffectVerifiedAt(GenerationSnapshot(8L, "service-1")),
            result
        )
        assertEquals(FreshnessRequirement.AuthorizeAfter(200L), requirement)
    }

    @Test
    fun failed_postcondition_with_complete_precondition_is_verified_no_effect_at_snapshot() {
        val identity = Any()
        val verifier = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, packageName = "before.app", capturedAt = 301L)
        })
        val pre = StepCheckpoint(expectedPackage = "before.app", expectedWindowId = 3)
        val post = StepCheckpoint(expectedPackage = "after.app")

        val result = verifier.verify(
            prepared(payload(identity, preCheckpoint = pre, postCheckpoint = post)),
            300L
        )

        assertEquals(
            VerificationResult.NoEffectVerifiedAt(GenerationSnapshot(8L, "service-1")),
            result
        )
    }

    @Test
    fun failed_postcondition_without_fully_proven_precondition_is_unknown() {
        val identity = Any()
        val noPre = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, packageName = "before.app", capturedAt = 401L)
        }).verify(
            prepared(payload(identity, postCheckpoint = StepCheckpoint(expectedPackage = "after.app"))),
            400L
        )
        val unprovedPre = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, packageName = "before.app", capturedAt = 401L, treeJson = "{}")
        }).verify(
            prepared(
                payload(
                    identity,
                    preCheckpoint = StepCheckpoint(
                        expectedPackage = "before.app",
                        requiredSelector = SemanticSelector(resourceId = "demo:id/target")
                    ),
                    postCheckpoint = StepCheckpoint(expectedPackage = "after.app")
                )
            ),
            400L
        )

        assertTrue(noPre is VerificationResult.Unknown)
        assertTrue(unprovedPre is VerificationResult.Unknown)
    }

    @Test
    fun absent_side_effect_checkpoint_stale_capture_service_replacement_and_exceptions_are_unknown() {
        val identity = Any()
        val noPost = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, capturedAt = 501L)
        }).verify(prepared(payload(identity)), 500L)
        val stale = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, capturedAt = 500L)
        }).verify(prepared(payload(identity, postCheckpoint = StepCheckpoint(expectedPackage = "demo.app"))), 500L)
        val rebound = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = Any(), capturedAt = 501L)
        }).verify(prepared(payload(identity, postCheckpoint = StepCheckpoint(expectedPackage = "demo.app"))), 500L)
        val failed = ProductionOutcomeVerifier(HybridEvidenceSource { throw IllegalStateException("capture") })
            .verify(prepared(payload(identity, postCheckpoint = StepCheckpoint(expectedPackage = "demo.app"))), 500L)

        listOf(noPost, stale, rebound, failed).forEach { result ->
            assertTrue(result is VerificationResult.Unknown)
        }
    }

    @Test
    fun changed_service_generation_or_regressed_ui_generation_is_unknown() {
        val identity = Any()
        val checkpoint = StepCheckpoint(expectedPackage = "demo.app")
        val serviceChanged = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(
                identity = identity,
                capturedAt = 551L,
                serviceGeneration = "service-2"
            )
        }).verify(prepared(payload(identity, postCheckpoint = checkpoint)), 550L)
        val regressed = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, capturedAt = 551L, uiGeneration = 6L)
        }).verify(prepared(payload(identity, postCheckpoint = checkpoint)), 550L)

        assertTrue(serviceChanged is VerificationResult.Unknown)
        assertTrue(regressed is VerificationResult.Unknown)
    }

    @Test
    fun complete_window_display_and_perceptual_postcondition_requires_fresh_matching_plane() {
        val identity = Any()
        val plane = patternedPlane()
        val fingerprint = PerceptualFingerprint.compute(plane)!!
        val transform = DisplayTransform(0, 16, 16, 16, 16, 0, 420, 0, 0, 0, 0)
        val post = StepCheckpoint(
            expectedPackage = "demo.app",
            expectedWindowId = 3,
            expectedDisplayTransform = transform.toCheckpoint(),
            perceptualHash = fingerprint,
            maximumHammingDistance = 0
        )
        val verified = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(
                identity = identity,
                capturedAt = 601L,
                plane = plane,
                frameCapturedAt = 600L,
                transform = transform
            )
        }).verify(prepared(payload(identity, postCheckpoint = post)), 599L)
        val missingPlane = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(
                identity = identity,
                capturedAt = 601L,
                plane = null,
                frameCapturedAt = 600L,
                transform = transform
            )
        }).verify(prepared(payload(identity, postCheckpoint = post)), 599L)

        assertEquals(
            VerificationResult.EffectVerifiedAt(GenerationSnapshot(8L, "service-1")),
            verified
        )
        assertTrue(missingPlane is VerificationResult.Unknown)
    }

    @Test
    fun read_only_wait_and_explicit_open_app_package_have_conservative_proofs() {
        val identity = Any()
        val verifier = ProductionOutcomeVerifier(HybridEvidenceSource {
            evidence(identity = identity, packageName = "demo.app", capturedAt = 701L)
        })
        val wait = prepared(
            DirectPayload(DirectAction.WAIT, waitMs = 10L, evidence = evidence(identity, capturedAt = 1L)),
            resolver = ResolverKind.DIRECT
        )
        val open = prepared(
            DirectPayload(
                DirectAction.OPEN_APP,
                packageName = "demo.app",
                evidence = evidence(identity, capturedAt = 1L)
            ),
            resolver = ResolverKind.DIRECT
        )

        val observed = VerificationResult.EffectVerifiedAt(GenerationSnapshot(8L, "service-1"))
        assertEquals(observed, verifier.verify(wait, 700L))
        assertEquals(observed, verifier.verify(open, 700L))
    }

    private fun prepared(
        payload: DispatchPayload,
        resolver: ResolverKind = ResolverKind.VISUAL_ANCHOR
    ) = PreparedAction("run-1", "step-1", 1, 7L, "service-1", resolver, payload)

    private fun payload(
        identity: Any,
        preCheckpoint: StepCheckpoint? = null,
        postCheckpoint: StepCheckpoint? = null
    ): VisualDispatchPayload {
        val evidence = evidence(identity = identity, capturedAt = 1L)
        return VisualDispatchPayload(
            IntRect(1, 1, 5, 5),
            0.5f,
            0.5f,
            VisualPlatformAction.TAP,
            100L,
            evidence,
            preCheckpoint,
            postCheckpoint
        )
    }

    private fun evidence(
        identity: Any,
        packageName: String = "demo.app",
        capturedAt: Long,
        plane: LumaPlane? = null,
        frameCapturedAt: Long? = null,
        treeJson: String? = null,
        transform: DisplayTransform = displayTransform(),
        uiGeneration: Long = 8L,
        serviceGeneration: String = "service-1"
    ): UiEvidence {
        val tree = treeJson ?: """{
          "currentPackage":"$packageName",
          "metrics":{"uiGeneration":$uiGeneration,"serviceGeneration":"$serviceGeneration"},
          "keyNodes":[{
            "ref":"node-1","resourceId":"demo:id/target","description":"","text":"Target",
            "className":"android.widget.Button","packageName":"$packageName","visible":true,
            "enabled":true,"clickable":true,"bounds":{"left":10,"top":20,"right":110,"bottom":70}
          }]
        }"""
        return UiEvidence(
            uiGeneration = uiGeneration,
            serviceGeneration = serviceGeneration,
            packageName = packageName,
            windowId = 3,
            capturedAt = capturedAt,
            transform = transform,
            compactTree = JsonParser.parseString(tree).asJsonObject,
            frameId = frameCapturedAt?.let { "fresh-frame" },
            frameSource = frameCapturedAt?.let { "fresh" },
            frameCapturedAt = frameCapturedAt,
            frameAgeMs = frameCapturedAt?.let { capturedAt - it },
            lumaPlane = plane,
            runtimeServiceIdentity = identity
        )
    }

    private fun displayTransform() = DisplayTransform(0, 200, 300, 200, 300, 0, 420, 0, 0, 0, 0)

    private fun DisplayTransform.toCheckpoint() = DisplayTransformCheckpoint(
        displayId,
        widthPx,
        heightPx,
        screenshotWidthPx,
        screenshotHeightPx,
        rotation,
        densityDpi,
        insetLeft,
        insetTop,
        insetRight,
        insetBottom
    )

    private fun patternedPlane(): LumaPlane = LumaPlane(
        16,
        16,
        IntArray(256) { index -> if ((index + index / 16) % 2 == 0) 20 else 220 }
    )
}
