package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.VisualAnchorSpec
import com.apk.claw.android.workflow.StepCheckpoint
import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.atomic.AtomicInteger

class HybridRpaEngineTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun generation_race_allows_exactly_one_fresh_reresolution_before_dispatch() {
        val captures = AtomicInteger()
        val dispatches = AtomicInteger()
        val source = HybridEvidenceSource {
            val generation = captures.incrementAndGet().toLong()
            evidence(uiGeneration = generation)
        }
        val engine = engine(
            evidenceSource = source,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = { GenerationSnapshot(2L, "service-1") }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "generation-race")

        assertTrue(result.success)
        assertEquals(2, captures.get())
        assertEquals(1, dispatches.get())
        assertEquals(1, result.dispatchCount)
        assertEquals(2, result.rounds)
    }

    @Test
    fun runtime_metrics_measure_dispatch_and_accumulate_tree_snapshot_work() {
        var now = 1_000L
        val result = engine(
            evidenceSource = HybridEvidenceSource { evidence(treeSnapshotMs = 3L) },
            dispatcher = ActionDispatcher {
                now += 5L
                DispatchReceipt.accepted(now)
            },
            verifier = OutcomeVerifier { _, _ ->
                now += 7L
                VerificationResult.EffectVerified
            },
            clock = { now }
        ).run(workflow(directStep("measured-step")), runId = "measured-run")

        assertTrue(result.success)
        assertEquals(3L, result.steps.single().treeSnapshotMs)
        assertTrue(result.steps.single().toolCallMs >= 12L)
        val metrics = RpaRunJson.snapshot(
            RpaRunSnapshot(
                runId = "measured-run",
                workflowId = "workflow-1",
                workflowName = "Hybrid workflow",
                status = RpaRunStatus.SUCCEEDED,
                currentStep = 1,
                totalSteps = 1,
                startedAt = 1_000L,
                updatedAt = now,
                mode = HYBRID_EXECUTION_MODE,
                steps = result.steps,
                dispatchCount = result.dispatchCount
            )
        ).getAsJsonObject("metrics")
        assertEquals(3L, metrics.get("screenTreeMs").asLong)
        assertTrue(metrics.get("toolCallMs").asLong >= 12L)
        assertTrue(metrics.get("toolCallMeasured").asBoolean)
    }

    @Test
    fun dual_confirm_preserves_semantic_tree_lookup_metrics() {
        val currentEvidence = evidence(
            frameId = "dual-frame",
            frameSource = "fresh",
            frameAgeMs = 1L,
            treeSnapshotMs = 3L
        )
        val bounds = IntRect(100, 100, 300, 300)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, evidence ->
                Resolution.Ready(
                    payload = SecretPayload("semantic", bounds),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(evidence),
                    metrics = ResolutionMetrics(treeLookupMs = 4L, nodesVisited = 8)
                )
            },
            visual = VisualChannel { kind, _, evidence ->
                Resolution.Ready(
                    payload = SecretPayload("visual", bounds),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(evidence),
                    metrics = ResolutionMetrics(matchMs = 5L)
                )
            },
            apiLevel = 30
        )
        val step = RpaStep(
            id = "dual-step",
            action = "tap_semantic",
            resolverPolicy = ResolverPolicy.DUAL_CONFIRM,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            semanticSelector = SemanticSelector(resourceId = "com.example:id/target"),
            visualAnchor = visualAnchor()
        )

        val result = engine(
            evidenceSource = HybridEvidenceSource { currentEvidence },
            arbiter = arbiter
        ).run(workflow(step), runId = "dual-metrics")

        assertTrue(result.success)
        assertEquals(3L, result.steps.single().treeSnapshotMs)
        assertEquals(4L, result.steps.single().treeLookupMs)
    }

    @Test
    fun cancellation_after_dispatch_keeps_measured_step_in_terminal_result() {
        var now = 1_000L
        var cancelled = false
        val result = engine(
            dispatcher = ActionDispatcher {
                now += 5L
                DispatchReceipt.accepted(now)
            },
            verifier = OutcomeVerifier { _, _ ->
                now += 7L
                cancelled = true
                VerificationResult.NoEffectVerified
            },
            clock = { now }
        ).run(
            workflow(directStep("cancel-after-dispatch")),
            runId = "cancel-after-dispatch",
            cancelled = { cancelled }
        )

        assertEquals("cancelled", result.errorCode)
        assertEquals(1, result.dispatchCount)
        assertEquals(1, result.steps.size)
        assertTrue(result.steps.single().toolCallMs >= 12L)
        val metrics = RpaRunJson.snapshot(
            RpaRunSnapshot(
                runId = "cancel-after-dispatch",
                workflowId = "workflow-1",
                workflowName = "Hybrid workflow",
                status = RpaRunStatus.CANCELLED,
                currentStep = 1,
                totalSteps = 1,
                startedAt = 1_000L,
                updatedAt = now,
                mode = HYBRID_EXECUTION_MODE,
                steps = result.steps,
                dispatchCount = result.dispatchCount
            )
        ).getAsJsonObject("metrics")
        assertTrue(metrics.get("toolCallMeasured").asBoolean)
        assertEquals(result.steps.single().toolCallMs, metrics.get("toolCallMs").asLong)
    }

    @Test
    fun second_generation_race_stops_without_dispatch() {
        val captures = AtomicInteger()
        val dispatches = AtomicInteger()
        val engine = engine(
            evidenceSource = HybridEvidenceSource {
                captures.incrementAndGet()
                evidence(uiGeneration = 1L)
            },
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = { GenerationSnapshot(2L, "service-1") }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "double-race")

        assertFalse(result.success)
        assertEquals("stale_resolution_evidence", result.errorCode)
        assertEquals(2, captures.get())
        assertEquals(0, dispatches.get())
    }

    @Test
    fun generation_flip_after_engine_check_is_rejected_inside_claim_with_zero_dispatch() {
        val generationCalls = AtomicInteger()
        val dispatches = AtomicInteger()
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = {
                val uiGeneration = if (generationCalls.incrementAndGet() == 1) 1L else 2L
                GenerationSnapshot(uiGeneration, "service-1")
            }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "claim-generation-flip")

        assertFalse(result.success)
        assertEquals("stale_resolution_evidence", result.errorCode)
        assertEquals(0, dispatches.get())
        assertEquals(0, result.dispatchCount)
    }

    @Test
    fun generation_guard_rejection_after_missing_used_reresolution_stops_without_attempt_two() {
        val captures = AtomicInteger()
        val semanticCalls = AtomicInteger()
        val generationCalls = AtomicInteger()
        val dispatches = AtomicInteger()
        val currentEvidence = evidence()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ ->
                if (semanticCalls.incrementAndGet() == 1) Resolution.Missing(kind)
                else Resolution.Ready(
                    SecretPayload("semantic", IntRect(1, 1, 10, 10)),
                    kind,
                    ResolutionEvidence.from(currentEvidence)
                )
            },
            visual = VisualChannel { kind, _, _ -> Resolution.Missing(kind) },
            apiLevel = 30
        )
        val step = RpaStep(
            id = "missing-then-generation",
            action = "tap_semantic",
            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
            semanticSelector = SemanticSelector(resourceId = "com.example:id/target")
        )
        val result = engine(
            evidenceSource = HybridEvidenceSource {
                captures.incrementAndGet()
                currentEvidence
            },
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = {
                GenerationSnapshot(if (generationCalls.incrementAndGet() == 1) 1L else 2L, "service-1")
            }
        ).run(workflow(step), runId = "missing-before-guard-race")

        assertEquals("stale_resolution_evidence", result.errorCode)
        assertEquals(2, captures.get())
        assertEquals(0, dispatches.get())
        assertEquals(0, result.dispatchCount)
    }

    @Test
    fun release_fault_after_one_shot_cancel_guard_is_terminal_with_zero_dispatch_count() {
        val root = temporaryFolder.newFolder("engine-guard-release-fault")
        val failOnce = java.util.concurrent.atomic.AtomicBoolean(true)
        val cancelOnce = java.util.concurrent.atomic.AtomicBoolean(false)
        val dispatches = AtomicInteger()
        val store = ActionLedgerStore(
            root,
            claimLockRelease = { lock ->
                lock.release()
                if (failOnce.compareAndSet(true, false)) throw IllegalStateException("release fault")
            }
        )
        val result = engine(
            ledgerStore = store,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = {
                cancelOnce.set(true)
                GenerationSnapshot(1L, "service-1")
            }
        ).run(
            workflow(directStep("step-1")),
            runId = "cancel-release-fault",
            cancelled = { cancelOnce.compareAndSet(true, false) }
        )

        assertEquals("cancelled", result.errorCode)
        assertEquals("cancelled", result.outcomeState)
        assertEquals(0, dispatches.get())
        assertEquals(0, result.dispatchCount)
        assertEquals(1, store.loadAll().size)
        assertEquals(ActionLedgerErrors.PRE_DISPATCH_CANCELLED, store.loadAll().single().errorCode)
        assertFalse(store.loadAll().single().dispatchInvoked)
    }

    @Test
    fun cancellation_and_deadline_flips_during_claim_authorize_zero_dispatches() {
        val dispatches = AtomicInteger()
        var cancelled = false
        val cancellationEngine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = {
                cancelled = true
                GenerationSnapshot(1L, "service-1")
            }
        )
        val cancelledResult = cancellationEngine.run(
            workflow(directStep("step-1")),
            runId = "claim-cancelled",
            cancelled = { cancelled }
        )

        var now = 1_000L
        val deadlineEngine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            generation = {
                now = 2_000L
                GenerationSnapshot(1L, "service-1")
            },
            clock = { now }
        )
        val deadlineResult = deadlineEngine.run(
            workflow(directStep("step-1")),
            runId = "claim-deadline",
            deadlineAt = 1_500L
        )

        assertEquals("cancelled", cancelledResult.errorCode)
        assertEquals("hybrid_timeout", deadlineResult.errorCode)
        assertEquals(0, dispatches.get())
        assertEquals(0, cancelledResult.dispatchCount)
        assertEquals(0, deadlineResult.dispatchCount)
    }

    @Test
    fun durable_failed_no_dispatch_allows_attempt_two_and_no_more() {
        val dispatches = AtomicInteger()
        val receipts = ArrayDeque(
            listOf(
                DispatchReceipt.rejected(2_000L),
                DispatchReceipt.rejected(2_100L),
                DispatchReceipt.accepted(2_200L)
            )
        )
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                receipts.removeFirst()
            }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "bounded-retry")

        assertFalse(result.success)
        assertEquals(2, dispatches.get())
        assertEquals(2, result.dispatchCount)
        assertEquals("failed_no_dispatch", result.outcomeState)
        assertTrue(result.agentHandoffRequired)
    }

    @Test
    fun durable_failed_no_effect_allows_attempt_two() {
        val dispatches = AtomicInteger()
        val verifications = ArrayDeque<VerificationResult>(
            listOf(VerificationResult.NoEffectVerified, VerificationResult.EffectVerified)
        )
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L + dispatches.get())
            },
            verifier = OutcomeVerifier { _, _ -> verifications.removeFirst() }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "no-effect-retry")

        assertTrue(result.success)
        assertEquals(2, dispatches.get())
        assertEquals(2, result.dispatchCount)
        assertEquals("verified", result.outcomeState)
        assertEquals(2, result.steps.single().attempts)
    }

    @Test
    fun uncertain_stops_immediately_and_never_executes_second_step() {
        val dispatches = AtomicInteger()
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.outcomeUnknown(2_000L)
            }
        )

        val result = engine.run(
            workflow(directStep("step-1"), directStep("step-2")),
            runId = "uncertain-stop"
        )

        assertFalse(result.success)
        assertEquals(1, dispatches.get())
        assertEquals(1, result.steps.size)
        assertEquals("uncertain", result.outcomeState)
        assertTrue(result.agentHandoffRequired)
        assertTrue(result.handoffContext!!.replayForbiddenUntilProof)
        assertEquals("step-1", result.handoffContext!!.failedStep.stepId)
    }

    @Test
    fun non_durable_executor_result_is_uncertain_and_never_retried() {
        val unavailableRoot = temporaryFolder.newFile("not-a-ledger-directory")
        val dispatches = AtomicInteger()
        val engine = engine(
            ledgerRoot = unavailableRoot,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.rejected(2_000L)
            }
        )

        val result = engine.run(workflow(directStep("step-1")), runId = "non-durable")

        assertFalse(result.success)
        assertEquals(0, dispatches.get())
        assertEquals(0, result.dispatchCount)
        assertEquals("uncertain", result.outcomeState)
        assertTrue(result.handoffContext!!.replayForbiddenUntilProof)
    }

    @Test
    fun cancellation_and_deadline_are_checked_before_evidence() {
        val captures = AtomicInteger()
        val engine = engine(
            evidenceSource = HybridEvidenceSource {
                captures.incrementAndGet()
                evidence()
            },
            clock = { 10L }
        )

        val cancelled = engine.run(
            workflow(directStep("step-1")),
            runId = "cancelled",
            cancelled = { true }
        )
        val timedOut = engine.run(
            workflow(directStep("step-1")),
            runId = "timed-out",
            deadlineAt = 9L
        )

        assertEquals("cancelled", cancelled.errorCode)
        assertEquals("hybrid_timeout", timedOut.errorCode)
        assertEquals(0, captures.get())
        assertEquals(0, cancelled.dispatchCount)
        assertEquals(0, timedOut.dispatchCount)
    }

    @Test
    fun cancellation_after_verified_step_preserves_completed_ledger_and_stops_next_step() {
        val dispatches = AtomicInteger()
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        )

        val result = engine.run(
            workflow(directStep("step-1"), directStep("step-2")),
            runId = "cancel-after-verify",
            cancelled = { dispatches.get() > 0 }
        )

        assertEquals("cancelled", result.errorCode)
        assertEquals(1, dispatches.get())
        assertEquals(1, result.steps.size)
        assertEquals("verified", result.steps.single().outcomeState)
    }

    @Test
    fun deadline_after_verification_preserves_verified_step_and_stops_next_step() {
        var now = 1_000L
        val dispatches = AtomicInteger()
        val engine = engine(
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                now = 2_000L
                DispatchReceipt.accepted(now)
            },
            clock = { now }
        )

        val result = engine.run(
            workflow(directStep("step-1"), directStep("step-2")),
            runId = "timeout-after-verify",
            deadlineAt = 1_500L
        )

        assertEquals("hybrid_timeout", result.errorCode)
        assertEquals(1, dispatches.get())
        assertEquals(1, result.steps.size)
        assertEquals("verified", result.steps.single().outcomeState)
    }

    @Test
    fun safety_policy_block_stops_before_evidence_and_forbids_replay() {
        val captures = AtomicInteger()
        val dispatches = AtomicInteger()
        val unsafe = directStep("unsafe").copy(description = "delete account")
        val result = engine(
            evidenceSource = HybridEvidenceSource {
                captures.incrementAndGet()
                evidence()
            },
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        ).run(workflow(unsafe), runId = "policy-block")

        assertEquals("safety_blocked", result.errorCode)
        assertEquals(0, captures.get())
        assertEquals(0, dispatches.get())
        assertTrue(result.handoffContext!!.replayForbiddenUntilProof)
    }

    @Test
    fun unvalidated_fallback_hands_off_without_dispatch_and_context_is_sanitized() {
        val dispatches = AtomicInteger()
        val ledgerStore = ActionLedgerStore(temporaryFolder.newFolder("resume-ledger"))
        val evidence = evidence(frameId = "frame-1", frameSource = "fresh", frameAgeMs = 1L)
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ ->
                Resolution.Ready(
                    payload = SecretPayload("raw-image-and-selector-secret", IntRect(1, 1, 20, 20)),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(evidence)
                )
            },
            apiLevel = 30
        )
        val engine = engine(
            evidenceSource = HybridEvidenceSource { evidence },
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            },
            ledgerStore = ledgerStore,
            resumeProofVerifier = ActionLedgerResumeProofVerifier(ledgerStore)
        )
        val unsafeStep = RpaStep(
            id = "failed-step",
            action = "tap_semantic",
            params = mapOf("raw" to "raw-param-secret"),
            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
            semanticSelector = SemanticSelector(resourceId = "selector-secret"),
            visualAnchor = visualAnchor()
        )

        val result = engine.run(
            workflow(directStep("completed-step"), unsafeStep),
            runId = "sanitized-handoff"
        )

        assertEquals("fallback_not_validated", result.errorCode)
        assertEquals(1, dispatches.get())
        assertEquals(1, result.dispatchCount)
        val handoff = assertNotNull(result.handoffContext).let { result.handoffContext!! }
        assertEquals(listOf("completed-step"), handoff.completedSteps.map { it.stepId })
        assertEquals("failed-step", handoff.failedStep.stepId)
        assertFalse(handoff.toString().contains("raw-param-secret"))
        assertFalse(handoff.toString().contains("selector-secret"))
        assertFalse(handoff.toString().contains("raw-image-and-selector-secret"))

        val resumedDispatches = AtomicInteger()
        val resumedEngine = engine(
            evidenceSource = HybridEvidenceSource { evidence },
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                resumedDispatches.incrementAndGet()
                DispatchReceipt.accepted(3_000L)
            },
            ledgerStore = ledgerStore,
            resumeProofVerifier = ActionLedgerResumeProofVerifier(ledgerStore)
        )
        val resumed = resumedEngine.run(
            workflow(directStep("completed-step"), unsafeStep),
            runId = "sanitized-handoff",
            resumeFrom = handoff
        )
        assertEquals("fallback_not_validated", resumed.errorCode)
        assertEquals(0, resumedDispatches.get())

        val forgedStepTwo = handoff.copy(
            completedSteps = listOf(
                handoff.completedSteps.single().copy(
                    stepIndex = 2,
                    stepId = "failed-step",
                    action = "tap_semantic"
                )
            )
        )
        val forged = resumedEngine.run(
            workflow(directStep("completed-step"), unsafeStep),
            runId = "sanitized-handoff",
            resumeFrom = forgedStepTwo
        )
        assertEquals("resume_proof_invalid", forged.errorCode)

        val rawFields = handoff.copy(
            completedSteps = listOf(handoff.completedSteps.single().copy(resolverUsed = "raw selector text")),
            failedStep = handoff.failedStep.copy(errorCode = "raw error detail")
        )
        val rejectedRaw = resumedEngine.run(
            workflow(directStep("completed-step"), unsafeStep),
            runId = "sanitized-handoff",
            resumeFrom = rawFields
        )
        assertEquals("resume_proof_invalid", rejectedRaw.errorCode)
        assertFalse(rejectedRaw.toString().contains("raw selector text"))
        assertFalse(rejectedRaw.toString().contains("raw error detail"))

        val noVerifier = engine(
            ledgerStore = ledgerStore,
            dispatcher = ActionDispatcher {
                resumedDispatches.incrementAndGet()
                DispatchReceipt.accepted(3_000L)
            }
        ).run(
            workflow(directStep("completed-step"), unsafeStep),
            runId = "sanitized-handoff",
            resumeFrom = handoff
        )
        assertEquals("resume_proof_invalid", noVerifier.errorCode)
        assertFalse(noVerifier.agentHandoffRequired)
        assertEquals(0, resumedDispatches.get())
    }

    @Test
    fun vision_required_on_api_29_hands_off_without_dispatch() {
        val dispatches = AtomicInteger()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, evidence ->
                Resolution.Ready(
                    SecretPayload("not-exposed", IntRect(1, 1, 10, 10)),
                    kind,
                    ResolutionEvidence.from(evidence)
                )
            },
            apiLevel = 29
        )
        val step = RpaStep(
            id = "visual",
            action = "tap_anchor",
            resolverPolicy = ResolverPolicy.VISION_REQUIRED,
            allowedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
            validatedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
            visualAnchor = visualAnchor()
        )
        val result = engine(
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        ).run(workflow(step), runId = "api-29")

        assertEquals("visual_capture_unsupported", result.errorCode)
        assertEquals(0, dispatches.get())
    }

    @Test
    fun tree_semantic_success_on_api_29_never_requests_visual_evidence() {
        val requirements = mutableListOf<FreshnessRequirement>()
        val visualCalls = AtomicInteger()
        val dispatches = AtomicInteger()
        val semanticEvidence = evidence()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ ->
                Resolution.Ready(
                    SecretPayload("semantic", IntRect(1, 1, 10, 10)),
                    kind,
                    ResolutionEvidence.from(semanticEvidence)
                )
            },
            visual = VisualChannel { kind, _, _ ->
                visualCalls.incrementAndGet()
                Resolution.Missing(kind)
            },
            apiLevel = 29
        )
        val step = RpaStep(
            id = "semantic-first",
            action = "tap_semantic",
            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            semanticSelector = SemanticSelector(resourceId = "com.example:id/target"),
            visualAnchor = visualAnchor()
        )

        val result = engine(
            evidenceSource = HybridEvidenceSource { requirement ->
                requirements += requirement
                semanticEvidence
            },
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        ).run(workflow(step), runId = "api29-semantic")

        assertTrue(result.success)
        assertEquals(listOf(FreshnessRequirement.ReadOnly), requirements)
        assertEquals(0, visualCalls.get())
        assertEquals(1, dispatches.get())
    }

    @Test
    fun coordinate_context_mismatch_authorizes_zero_dispatches() {
        val dispatches = AtomicInteger()
        val fresh = evidence(frameId = "frame-coordinate", frameSource = "fresh", frameAgeMs = 1L)
        val fingerprint = validFingerprint()
        val arbiter = HybridResolutionArbiter(
            semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
            visual = VisualChannel { kind, _, _ ->
                Resolution.Ready(
                    payload = SecretPayload("coordinate", IntRect(1, 1, 10, 10)),
                    resolverUsed = kind,
                    evidence = ResolutionEvidence.from(fresh),
                    coordinateProof = CoordinateCheckpointProof(
                        uiGeneration = fresh.uiGeneration,
                        serviceGeneration = fresh.serviceGeneration,
                        frameId = fresh.frameId!!,
                        frameSource = "fresh",
                        frameAgeMs = fresh.frameAgeMs!!,
                        packageName = "com.forged",
                        windowId = fresh.windowId,
                        transform = fresh.transform,
                        expectedFingerprint = fingerprint,
                        actualFingerprint = fingerprint
                    )
                )
            },
            apiLevel = 30
        )
        val step = RpaStep(
            id = "coordinate",
            action = "tap_normalized",
            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
            allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
            semanticSelector = SemanticSelector(resourceId = "com.example:id/missing"),
            preCheckpoint = StepCheckpoint(
                expectedPackage = fresh.packageName,
                perceptualHash = fingerprint,
                maximumHammingDistance = 0,
                expectedWindowId = fresh.windowId,
                expectedDisplayTransform = fresh.transform.toCheckpoint()
            )
        )

        val result = engine(
            evidenceSource = HybridEvidenceSource { fresh },
            arbiter = arbiter,
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        ).run(workflow(step), runId = "coordinate-mismatch")

        assertEquals("coordinate_checkpoint_unproved", result.errorCode)
        assertEquals(0, dispatches.get())
        assertEquals(0, result.dispatchCount)
    }

    @Test
    fun malformed_service_generation_and_throwing_executor_stop_before_later_steps() {
        val dispatches = AtomicInteger()
        val invalidGeneration = engine(
            evidenceSource = HybridEvidenceSource { evidence(serviceGeneration = "raw invalid generation") },
            generation = { GenerationSnapshot(1L, "raw invalid generation") },
            dispatcher = ActionDispatcher {
                dispatches.incrementAndGet()
                DispatchReceipt.accepted(2_000L)
            }
        ).run(workflow(directStep("step-1")), runId = "invalid-service-generation")

        val throwing = engine(
            executorCall = { throw IllegalStateException("raw executor detail") }
        ).run(
            workflow(directStep("step-1"), directStep("step-2")),
            runId = "throwing-executor"
        )

        assertEquals("service_generation_invalid", invalidGeneration.errorCode)
        assertEquals(0, dispatches.get())
        assertEquals("executor_outcome_unknown", throwing.errorCode)
        assertEquals("uncertain", throwing.outcomeState)
        assertEquals(1, throwing.steps.size)
        assertTrue(throwing.handoffContext!!.replayForbiddenUntilProof)
        assertFalse(throwing.toString().contains("raw executor detail"))
    }

    @Test
    fun runner_routes_only_exact_hybrid_mode_and_never_falls_back_when_engine_is_missing() {
        RpaWorkflowRunner.installHybridEngine(null)
        val hybrid = RpaWorkflowRunner.start(workflow(directStep("step-1")))
        val legacy = RpaWorkflowRunner.start(
            RpaWorkflow(
                id = "legacy",
                name = "Legacy",
                steps = listOf(RpaStep(id = "back", action = "back"))
            )
        )

        assertFalse(hybrid.accepted)
        assertEquals("hybrid_engine_unavailable", hybrid.errorCode)
        assertFalse(legacy.accepted)
        assertEquals("accessibility_reenable_required", legacy.errorCode)
    }

    @Test
    fun runner_terminalizes_running_snapshot_when_hybrid_engine_throws() {
        val snapshot = RpaWorkflowRunner.executeHybridForTest(
            workflow(directStep("step-1")),
            object : HybridWorkflowExecutor {
                override fun run(
                    workflow: RpaWorkflow,
                    runId: String,
                    resumeFrom: AgentHandoffContext?,
                    cancelled: () -> Boolean,
                    deadlineAt: Long
                ): HybridRunResult {
                    throw IllegalStateException("raw engine failure")
                }
            }
        )

        assertEquals(RpaRunStatus.FAILED, snapshot.status)
        assertEquals("hybrid_engine_failure", snapshot.errorCode)
        assertEquals("blocked", snapshot.outcomeState)
        assertTrue(snapshot.finishedAt > 0L)
        assertFalse(snapshot.toString().contains("raw engine failure"))
    }

    @Test
    fun runner_publishes_template_lifecycle_only_after_explicit_production_authorization() {
        val claimed = workflow(directStep("step-1")).copy(
            templateStatus = "active",
            templateRevision = 7,
            validationProgress = "3/3",
            promotionEligible = true,
            promotionIneligibleReason = "client_claim"
        )
        val rejected = RpaWorkflowRunner.executeHybridForTest(
            claimed,
            object : HybridWorkflowExecutor {
                override fun run(
                    workflow: RpaWorkflow,
                    runId: String,
                    resumeFrom: AgentHandoffContext?,
                    cancelled: () -> Boolean,
                    deadlineAt: Long
                ) = HybridRunResult(
                    success = false,
                    steps = emptyList(),
                    errorCode = "template_not_authorized",
                    outcomeState = "blocked",
                    dispatchCount = 0,
                    rounds = 0
                )
            }
        )
        val authorized = RpaWorkflowRunner.executeHybridForTest(
            claimed,
            object : HybridWorkflowExecutor {
                override fun run(
                    workflow: RpaWorkflow,
                    runId: String,
                    resumeFrom: AgentHandoffContext?,
                    cancelled: () -> Boolean,
                    deadlineAt: Long
                ) = HybridRunResult(
                    success = true,
                    steps = emptyList(),
                    outcomeState = "verified",
                    dispatchCount = 0,
                    rounds = 0,
                    templateAuthorized = true
                )
            }
        )

        assertEquals("", rejected.templateStatus)
        assertEquals(0, rejected.templateRevision)
        assertEquals("", rejected.validationProgress)
        assertFalse(rejected.promotionEligible)
        assertEquals("", rejected.promotionIneligibleReason)
        assertEquals("active", authorized.templateStatus)
        assertEquals(7, authorized.templateRevision)
        assertEquals("3/3", authorized.validationProgress)
        assertTrue(authorized.promotionEligible)
        assertEquals("client_claim", authorized.promotionIneligibleReason)
    }

    @Test
    fun legacy_run_json_shape_stays_unchanged_while_hybrid_metrics_are_additive() {
        val legacyRecord = RpaStepRecord(
            index = 1,
            stepId = "back",
            action = "back",
            status = "succeeded",
            attempts = 1,
            actionMs = 4L,
            startedAt = 10L,
            finishedAt = 14L
        )
        val legacyJson = RpaRunJson.stepRecord(legacyRecord)
        assertEquals(
            setOf(
                "index", "stepId", "action", "status", "attempts", "actionMs", "message",
                "errorCode", "retryable", "startedAt", "finishedAt"
            ),
            legacyJson.keySet()
        )

        val hybridJson = RpaRunJson.stepRecord(
            legacyRecord.copy(
                index = Int.MIN_VALUE,
                attempts = Int.MIN_VALUE,
                actionMs = Long.MIN_VALUE,
                resolverUsed = "DIRECT",
                treeSnapshotMs = Long.MIN_VALUE,
                treeLookupMs = -2L,
                nodesVisited = -3,
                captureMs = -4L,
                matchMs = -5L,
                verifyMs = -6L,
                frameSource = "fresh",
                frameAgeMs = -7L,
                uiGeneration = -8L,
                outcomeState = "verified",
                dispatchCount = -9,
                rounds = -10,
                toolCallMs = Long.MIN_VALUE,
                mode = "hybrid_rpa"
            )
        )
        assertEquals("DIRECT", hybridJson.get("resolverUsed").asString)
        listOf(
            "index", "attempts", "actionMs",
            "treeSnapshotMs", "treeLookupMs", "nodesVisited", "captureMs", "matchMs", "verifyMs",
            "frameAgeMs", "uiGeneration", "dispatchCount", "rounds", "toolCallMs"
        ).forEach { key -> assertTrue("$key must be nonnegative", hybridJson.get(key).asLong >= 0L) }
        assertFalse(hybridJson.toString().contains("selector"))
        assertFalse(hybridJson.toString().contains("payload"))

        val snapshotJson = RpaRunJson.snapshot(
            RpaRunSnapshot(
                runId = "run",
                workflowId = "workflow",
                workflowName = "Hybrid",
                status = RpaRunStatus.FAILED,
                currentStep = Int.MIN_VALUE,
                totalSteps = Int.MIN_VALUE,
                startedAt = 0L,
                updatedAt = 0L,
                totalMs = Long.MIN_VALUE,
                mode = HYBRID_EXECUTION_MODE,
                dispatchCount = Int.MIN_VALUE,
                rounds = Int.MIN_VALUE
            )
        )
        listOf("currentStep", "totalSteps", "totalMs", "dispatchCount", "rounds").forEach { key ->
            assertTrue("$key must be nonnegative", snapshotJson.get(key).asLong >= 0L)
        }
        val metrics = snapshotJson.getAsJsonObject("metrics")
        assertTrue(metrics.get("totalMs").asLong >= 0L)
        assertEquals(0, metrics.get("rounds").asInt)
        assertEquals(0L, metrics.get("llmRoundMs").asLong)
        assertTrue(metrics.get("resolverRounds").asInt >= 0)

        val saturatedMetrics = RpaRunJson.snapshot(
            RpaRunSnapshot(
                runId = "overflow-run",
                workflowId = "workflow",
                workflowName = "Hybrid",
                status = RpaRunStatus.SUCCEEDED,
                currentStep = 2,
                totalSteps = 2,
                startedAt = 0L,
                updatedAt = 1L,
                mode = HYBRID_EXECUTION_MODE,
                dispatchCount = 2,
                steps = listOf(
                    legacyRecord.copy(
                        mode = HYBRID_EXECUTION_MODE,
                        actionMs = Long.MAX_VALUE,
                        treeSnapshotMs = Long.MAX_VALUE,
                        treeLookupMs = Long.MAX_VALUE,
                        toolCallMs = Long.MAX_VALUE
                    ),
                    legacyRecord.copy(
                        mode = HYBRID_EXECUTION_MODE,
                        actionMs = 1L,
                        treeSnapshotMs = 1L,
                        treeLookupMs = 1L,
                        toolCallMs = 1L
                    )
                )
            )
        ).getAsJsonObject("metrics")
        assertEquals(Long.MAX_VALUE, saturatedMetrics.get("screenTreeMs").asLong)
        assertEquals(Long.MAX_VALUE, saturatedMetrics.get("stepMs").asLong)
        assertEquals(Long.MAX_VALUE, saturatedMetrics.get("toolCallMs").asLong)
        assertTrue(saturatedMetrics.get("toolCallMeasured").asBoolean)
    }

    private fun engine(
        evidenceSource: HybridEvidenceSource = HybridEvidenceSource { evidence() },
        arbiter: HybridResolutionArbiter = directArbiter(),
        dispatcher: ActionDispatcher = ActionDispatcher { DispatchReceipt.accepted(2_000L) },
        verifier: OutcomeVerifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerified },
        generation: () -> GenerationSnapshot? = { GenerationSnapshot(1L, "service-1") },
        clock: () -> Long = { 1_000L },
        ledgerRoot: File = temporaryFolder.newFolder(),
        ledgerStore: ActionLedgerStore = ActionLedgerStore(ledgerRoot),
        resumeProofVerifier: ResumeProofVerifier = ResumeProofVerifier.denyAll(),
        executorCall: ((PreparedAction) -> ActionOutcome)? = null
    ): HybridRpaEngine {
        if (executorCall != null) {
            return HybridRpaEngine.forTesting(
                evidenceSource = evidenceSource,
                arbiter = arbiter,
                generation = generation,
                clock = clock,
                resumeProofVerifier = resumeProofVerifier,
                executorCall = executorCall
            )
        }
        return HybridRpaEngine(
            evidenceSource = evidenceSource,
            arbiter = arbiter,
            executor = SingleDispatchExecutor(
                store = ledgerStore,
                dispatcher = dispatcher,
                verifier = verifier,
                clock = clock,
                generation = generation
            ),
            generation = generation,
            clock = clock,
            resumeProofVerifier = resumeProofVerifier
        )
    }

    private fun workflow(vararg steps: RpaStep) = RpaWorkflow(
        id = "workflow-1",
        name = "Hybrid workflow",
        steps = steps.toList(),
        schemaVersion = 2,
        executionMode = "hybrid_rpa",
        templateId = "template-1",
        templateRevision = 1,
        targetProfileId = "profile-1"
    )

    private fun directStep(id: String) = RpaStep(
        id = id,
        action = "back",
        resolverPolicy = ResolverPolicy.DIRECT,
        allowedResolvers = setOf(ResolverKind.DIRECT),
        validatedResolvers = setOf(ResolverKind.DIRECT)
    )

    private fun directArbiter() = HybridResolutionArbiter(
        semantic = SemanticChannel { kind, _, _ -> Resolution.Missing(kind) },
        visual = VisualChannel { kind, _, _ -> Resolution.Missing(kind) },
        apiLevel = 30
    )

    private fun visualAnchor() = VisualAnchorSpec(
        assetName = "step-anchor.webp",
        searchRegion = NormalizedRect(0f, 0f, 1f, 1f),
        tapOffsetX = 0.5f,
        tapOffsetY = 0.5f
    )

    private fun evidence(
        uiGeneration: Long = 1L,
        serviceGeneration: String = "service-1",
        frameId: String? = null,
        frameSource: String? = null,
        frameAgeMs: Long? = null,
        treeSnapshotMs: Long = 0L,
        runtimeServiceIdentity: Any? = stableServiceIdentity
    ) = UiEvidence(
        uiGeneration = uiGeneration,
        serviceGeneration = serviceGeneration,
        packageName = "com.example",
        windowId = 1,
        capturedAt = if (frameId == null) 1_000L else 1_002L,
        transform = DisplayTransform(0, 1080, 1920, 1080, 1920, 0, 420, 0, 0, 0, 0),
        compactTree = null,
        frameId = frameId,
        frameSource = frameSource,
        frameCapturedAt = frameId?.let { 1_001L },
        frameAgeMs = frameAgeMs,
        treeSnapshotMs = treeSnapshotMs,
        runtimeServiceIdentity = runtimeServiceIdentity
    )

    private val stableServiceIdentity = Any()

    private data class SecretPayload(
        val secret: String,
        override val bounds: IntRect
    ) : BoundedDispatchPayload

    private fun validFingerprint(): String =
        "pf2:${"0".repeat(64)}:80:10:0000000000000000"

    private fun DisplayTransform.toCheckpoint() = DisplayTransformCheckpoint(
        displayId, widthPx, heightPx, screenshotWidthPx, screenshotHeightPx,
        rotation, densityDpi, insetLeft, insetTop, insetRight, insetBottom
    )
}
