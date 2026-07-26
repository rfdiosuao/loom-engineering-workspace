package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.StepCheckpoint
import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridResolutionArbiterTest {
    @Test
    fun tree_preferred_uses_fixed_semantic_order_then_validated_visual() {
        val calls = mutableListOf<ResolverKind>()
        val evidence = evidence()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ ->
                calls += kind
                Resolution.Missing(kind)
            },
            visual = VisualChannel { kind, _, _ ->
                calls += kind
                ready(kind, evidence)
            },
            apiLevel = 30
        )

        val result = arbiter.resolve(
            step(
                allowed = setOf(
                    ResolverKind.VISUAL_ANCHOR,
                    ResolverKind.TEXT_CLASS,
                    ResolverKind.RESOURCE_ID
                ),
                validated = setOf(ResolverKind.VISUAL_ANCHOR)
            ),
            evidence
        )

        assertEquals(ResolverKind.VISUAL_ANCHOR, (result as Resolution.Ready).resolverUsed)
        assertEquals(
            listOf(ResolverKind.RESOURCE_ID, ResolverKind.TEXT_CLASS, ResolverKind.VISUAL_ANCHOR),
            calls
        )
    }

    @Test
    fun ambiguity_at_higher_priority_stops_without_visual_fallback() {
        var visualCalls = 0
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Ambiguous(kind, 2) },
            visual = VisualChannel { kind, _, evidence ->
                visualCalls += 1
                ready(kind, evidence)
            },
            apiLevel = 30
        )

        val result = arbiter.resolve(
            step(
                allowed = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
                validated = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
            ),
            evidence()
        )

        assertTrue(result is Resolution.Ambiguous)
        assertEquals(0, visualCalls)
    }

    @Test
    fun unvalidated_ready_fallback_is_blocked() {
        val evidence = evidence()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ -> ready(kind, evidence) },
            apiLevel = 30
        )

        val result = arbiter.resolve(
            step(
                allowed = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
                validated = setOf(ResolverKind.RESOURCE_ID)
            ),
            evidence
        )

        assertEquals("fallback_not_validated", (result as Resolution.Blocked).errorCode)
    }

    @Test
    fun cached_or_stale_visual_evidence_authorizes_zero_actions() {
        listOf("cache", "stale_fallback").forEach { source ->
            val evidence = evidence(frameSource = source)
            val arbiter = HybridResolutionArbiter(
                semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
                visual = VisualChannel { kind, _, _ -> ready(kind, evidence) },
                apiLevel = 30
            )

            val result = arbiter.resolve(
                step(
                    policy = ResolverPolicy.VISION_REQUIRED,
                    allowed = setOf(ResolverKind.VISUAL_ANCHOR),
                    validated = setOf(ResolverKind.VISUAL_ANCHOR)
                ),
                evidence
            )

            assertEquals("visual_evidence_not_fresh", (result as Resolution.Blocked).errorCode)
        }
    }

    @Test
    fun visual_resolution_on_api_29_returns_structured_handoff_before_channel_call() {
        var visualCalls = 0
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, evidence ->
                visualCalls += 1
                ready(kind, evidence)
            },
            apiLevel = 29
        )

        val result = arbiter.resolve(
            step(
                policy = ResolverPolicy.VISION_REQUIRED,
                allowed = setOf(ResolverKind.VISUAL_ANCHOR),
                validated = setOf(ResolverKind.VISUAL_ANCHOR)
            ),
            evidence()
        )

        assertEquals("visual_capture_unsupported", (result as Resolution.Handoff).errorCode)
        assertEquals(0, visualCalls)
    }

    @Test
    fun dual_confirmation_disagreement_is_unsafe_and_overflow_safe_overlap_is_accepted() {
        val evidence = evidence()
        var visualBounds = IntRect(100, 100, 200, 200)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ ->
                ready(kind, evidence, IntRect(0, 0, 100, 100))
            },
            visual = VisualChannel { kind, _, _ -> ready(kind, evidence, visualBounds) },
            apiLevel = 30
        )
        val dualStep = step(
            policy = ResolverPolicy.DUAL_CONFIRM,
            allowed = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            validated = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
        )

        val disagreement = arbiter.resolve(dualStep, evidence)
        assertEquals("resolver_disagreement", (disagreement as Resolution.Unsafe).errorCode)

        visualBounds = IntRect(Int.MAX_VALUE / 2, 0, Int.MAX_VALUE, Int.MAX_VALUE)
        val overflowArbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ ->
                ready(kind, evidence, IntRect(0, 0, Int.MAX_VALUE, Int.MAX_VALUE))
            },
            visual = VisualChannel { kind, _, _ -> ready(kind, evidence, visualBounds) },
            apiLevel = 30
        )
        assertTrue(overflowArbiter.resolve(dualStep, evidence) is Resolution.Ready)
    }

    @Test
    fun dual_confirmation_requires_matching_generation_and_fresh_frame() {
        val evidence = evidence()
        val staleVisualEvidence = evidence(uiGeneration = 8L)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> ready(kind, evidence) },
            visual = VisualChannel { kind, _, _ -> ready(kind, staleVisualEvidence) },
            apiLevel = 30
        )

        val result = arbiter.resolve(
            step(
                policy = ResolverPolicy.DUAL_CONFIRM,
                allowed = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
                validated = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
            ),
            evidence
        )

        assertEquals("stale_resolution_evidence", (result as Resolution.Blocked).errorCode)
    }

    @Test
    fun ready_resolution_is_stale_when_package_window_or_exact_service_identity_changes() {
        val service = Any()
        val resolvedEvidence = evidence(runtimeServiceIdentity = service)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> ready(kind, resolvedEvidence) },
            visual = VisualChannel { kind, _, _ -> Resolution.Missing(kind) },
            apiLevel = 30
        )
        val semanticStep = step(
            allowed = setOf(ResolverKind.RESOURCE_ID),
            validated = setOf(ResolverKind.RESOURCE_ID)
        )
        val changedContexts = listOf(
            evidence(packageName = "com.other", runtimeServiceIdentity = service),
            evidence(windowId = 9, runtimeServiceIdentity = service),
            evidence(runtimeServiceIdentity = Any())
        )

        changedContexts.forEach { current ->
            val result = arbiter.resolve(semanticStep, current)
            assertEquals(
                HybridResolutionArbiter.ERROR_STALE_RESOLUTION_EVIDENCE,
                (result as Resolution.Blocked).errorCode
            )
        }
    }

    @Test
    fun ephemeral_ref_and_unproved_normalized_coordinate_cannot_authorize_production() {
        val evidence = evidence()
        val ephemeral = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> ready(kind, evidence) },
            visual = VisualChannel { kind, _, _ -> ready(kind, evidence) },
            apiLevel = 30
        ).resolve(
            step(
                allowed = setOf(ResolverKind.EPHEMERAL_REF),
                validated = setOf(ResolverKind.EPHEMERAL_REF)
            ),
            evidence
        )
        assertEquals("ephemeral_ref_not_production_safe", (ephemeral as Resolution.Blocked).errorCode)

        val coordinate = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ -> ready(kind, evidence) },
            apiLevel = 30
        ).resolve(
            step(
                allowed = setOf(ResolverKind.NORMALIZED_COORDINATE),
                validated = setOf(ResolverKind.NORMALIZED_COORDINATE)
            ),
            evidence
        )
        assertEquals("coordinate_checkpoint_unproved", (coordinate as Resolution.Blocked).errorCode)
    }

    @Test
    fun normalized_coordinate_accepts_only_matching_fresh_checkpoint_proof() {
        val evidence = evidence()
        val expected = validFingerprint()
        val proof = CoordinateCheckpointProof(
            uiGeneration = evidence.uiGeneration,
            serviceGeneration = evidence.serviceGeneration,
            frameId = evidence.frameId!!,
            frameSource = "fresh",
            frameAgeMs = evidence.frameAgeMs!!,
            packageName = evidence.packageName,
            windowId = evidence.windowId,
            transform = evidence.transform,
            expectedFingerprint = expected,
            actualFingerprint = expected
        )
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ ->
                Resolution.Ready(
                    payload = BoxPayload(IntRect(10, 10, 20, 20)),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(evidence),
                    coordinateProof = proof
                )
            },
            apiLevel = 30
        )

        val result = arbiter.resolve(
            step(
                allowed = setOf(ResolverKind.NORMALIZED_COORDINATE),
                validated = setOf(ResolverKind.NORMALIZED_COORDINATE)
            ).copy(preCheckpoint = coordinateCheckpoint(evidence, expected, 1)),
            evidence
        )

        assertTrue(result is Resolution.Ready)
    }

    @Test
    fun normalized_coordinate_rejects_invalid_distant_or_context_mismatched_pf2_proof() {
        val evidence = evidence()
        val expected = validFingerprint()
        val baseProof = CoordinateCheckpointProof(
            uiGeneration = evidence.uiGeneration,
            serviceGeneration = evidence.serviceGeneration,
            frameId = evidence.frameId!!,
            frameSource = "fresh",
            frameAgeMs = evidence.frameAgeMs!!,
            packageName = evidence.packageName,
            windowId = evidence.windowId,
            transform = evidence.transform,
            expectedFingerprint = expected,
            actualFingerprint = expected
        )
        var proof = baseProof
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ ->
                Resolution.Ready(
                    payload = BoxPayload(IntRect(10, 10, 20, 20)),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(evidence),
                    coordinateProof = proof
                )
            },
            apiLevel = 30
        )
        val coordinateStep = step(
            allowed = setOf(ResolverKind.NORMALIZED_COORDINATE),
            validated = setOf(ResolverKind.NORMALIZED_COORDINATE)
        ).copy(preCheckpoint = coordinateCheckpoint(evidence, expected, 0))

        proof = baseProof.copy(actualFingerprint = "not-pf2")
        assertEquals("coordinate_checkpoint_unproved", (arbiter.resolve(coordinateStep, evidence) as Resolution.Blocked).errorCode)

        proof = baseProof.copy(actualFingerprint = validFingerprint(bits = "0000000000000001"))
        assertEquals("coordinate_checkpoint_unproved", (arbiter.resolve(coordinateStep, evidence) as Resolution.Blocked).errorCode)

        proof = baseProof.copy(windowId = evidence.windowId + 1)
        assertEquals("coordinate_checkpoint_unproved", (arbiter.resolve(coordinateStep, evidence) as Resolution.Blocked).errorCode)

        proof = baseProof.copy(packageName = "recorded.other")
        assertEquals("coordinate_checkpoint_unproved", (arbiter.resolve(coordinateStep, evidence) as Resolution.Blocked).errorCode)

        proof = baseProof.copy(transform = evidence.transform.copy(rotation = 1))
        assertEquals("coordinate_checkpoint_unproved", (arbiter.resolve(coordinateStep, evidence) as Resolution.Blocked).errorCode)
    }

    @Test
    fun direct_resolution_uses_fixed_action_enum_and_rejects_arbitrary_text() {
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ -> Resolution.Missing(kind) },
            apiLevel = 30
        )
        val evidence = evidence(frameId = null, frameSource = null, frameAgeMs = null)
        val allowed = setOf(ResolverKind.DIRECT)

        val ready = arbiter.resolve(
            step(action = "back", policy = ResolverPolicy.DIRECT, allowed = allowed, validated = allowed),
            evidence
        ) as Resolution.Ready
        assertEquals(DirectAction.BACK, (ready.payload as DirectPayload).action)

        val unsafe = arbiter.resolve(
            step(action = "run arbitrary payload", policy = ResolverPolicy.DIRECT, allowed = allowed, validated = allowed),
            evidence
        )
        assertEquals("direct_action_unsupported", (unsafe as Resolution.Unsafe).errorCode)

        listOf(
            "input_text",
            "system_key",
            "delete",
            "swipe_normalized",
            "drag_normalized"
        ).forEach { dangerous ->
            val blocked = arbiter.resolve(
                step(action = dangerous, policy = ResolverPolicy.DIRECT, allowed = allowed, validated = allowed),
                evidence
            )
            assertEquals("direct_action_unsupported", (blocked as Resolution.Unsafe).errorCode)
        }
    }

    @Test
    fun direct_resolution_retains_only_bounded_sanitized_parameters() {
        val evidence = evidence()
        val allowed = setOf(ResolverKind.DIRECT)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ -> Resolution.Missing(kind) },
            apiLevel = 30
        )
        val open = arbiter.resolve(
            step(
                action = "open_app",
                policy = ResolverPolicy.DIRECT,
                allowed = allowed,
                validated = allowed
            ).copy(params = mapOf("package_name" to "demo.app", "ignored_secret" to "do-not-retain")),
            evidence
        ) as Resolution.Ready
        val invalidWait = arbiter.resolve(
            step(
                action = "wait",
                policy = ResolverPolicy.DIRECT,
                allowed = allowed,
                validated = allowed
            ).copy(params = mapOf("duration_ms" to DirectPayload.MAX_WAIT_MS + 1L)),
            evidence
        )

        val payload = open.payload as DirectPayload
        assertEquals("demo.app", payload.packageName)
        assertEquals(0L, payload.waitMs)
        assertEquals("direct_params_invalid", (invalidWait as Resolution.Handoff).errorCode)
    }

    private fun step(
        action: String = "tap_semantic",
        policy: ResolverPolicy = ResolverPolicy.TREE_PREFERRED,
        allowed: Set<ResolverKind>,
        validated: Set<ResolverKind>
    ) = RpaStep(
        id = "step-1",
        action = action,
        resolverPolicy = policy,
        allowedResolvers = allowed,
        validatedResolvers = validated
    )

    private fun evidence(
        uiGeneration: Long = 7L,
        frameId: String? = "frame-7",
        frameSource: String? = "fresh",
        frameAgeMs: Long? = 5L,
        packageName: String = "com.example",
        windowId: Int = 2,
        runtimeServiceIdentity: Any? = Any()
    ) = UiEvidence(
        uiGeneration = uiGeneration,
        serviceGeneration = "service-1",
        packageName = packageName,
        windowId = windowId,
        capturedAt = 1_000L,
        transform = DisplayTransform(0, 1080, 1920, 1080, 1920, 0, 420, 0, 0, 0, 0),
        compactTree = null,
        frameId = frameId,
        frameSource = frameSource,
        frameCapturedAt = frameId?.let { 995L },
        frameAgeMs = frameAgeMs,
        runtimeServiceIdentity = runtimeServiceIdentity
    )

    private fun ready(
        kind: ResolverKind,
        evidence: UiEvidence,
        bounds: IntRect = IntRect(10, 10, 110, 110)
    ) = Resolution.Ready(
        payload = BoxPayload(bounds),
        resolverUsed = kind,
        evidence = ResolutionEvidence.from(evidence)
    )

    private data class BoxPayload(override val bounds: IntRect) : BoundedDispatchPayload

    private fun validFingerprint(bits: String = "0000000000000000"): String =
        "pf2:${"0".repeat(64)}:80:10:$bits"

    private fun coordinateCheckpoint(
        evidence: UiEvidence,
        fingerprint: String,
        maximumDistance: Int
    ) = StepCheckpoint(
        expectedPackage = evidence.packageName,
        perceptualHash = fingerprint,
        maximumHammingDistance = maximumDistance,
        expectedWindowId = evidence.windowId,
        expectedDisplayTransform = evidence.transform.toCheckpoint()
    )

    private fun DisplayTransform.toCheckpoint() = DisplayTransformCheckpoint(
        displayId, widthPx, heightPx, screenshotWidthPx, screenshotHeightPx,
        rotation, densityDpi, insetLeft, insetTop, insetRight, insetBottom
    )
}
