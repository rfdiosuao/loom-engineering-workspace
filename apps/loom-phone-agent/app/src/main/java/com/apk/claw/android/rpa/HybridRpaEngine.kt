package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import java.security.MessageDigest

fun interface HybridEvidenceSource {
    fun capture(requirement: FreshnessRequirement): UiEvidence
}

data class HybridCompletedStepEvidence(
    val stepIndex: Int,
    val stepId: String,
    val action: String,
    val resolverUsed: String,
    val uiGeneration: Long,
    val attempts: Int,
    val outcomeState: String = "verified",
    val ledgerProof: HybridLedgerProof
)

data class HybridLedgerProof(
    val runKey: String,
    val stepKey: String,
    val attempt: Int
)

data class VerifiedResumeEvidence(
    val runKey: String,
    val stepKey: String,
    val attempt: Int,
    val resolverUsed: ResolverKind,
    val uiGeneration: Long
)

fun interface ResumeProofVerifier {
    fun verify(proof: HybridLedgerProof): VerifiedResumeEvidence?

    companion object {
        fun denyAll(): ResumeProofVerifier = ResumeProofVerifier { null }
    }
}

class ActionLedgerResumeProofVerifier(
    private val store: ActionLedgerStore
) : ResumeProofVerifier {
    override fun verify(proof: HybridLedgerProof): VerifiedResumeEvidence? {
        if (!OPAQUE_PROOF_PATTERN.matches(proof.runKey) ||
            !OPAQUE_PROOF_PATTERN.matches(proof.stepKey) ||
            proof.attempt !in 1..MAX_HYBRID_ATTEMPTS
        ) return null
        val entry = runCatching {
            store.load(OpaqueLedgerKey(proof.runKey, proof.stepKey, proof.attempt))
        }.getOrNull() ?: return null
        if (entry.state != ActionLedgerState.VERIFIED || entry.errorCode != ActionLedgerErrors.VERIFIED) return null
        return VerifiedResumeEvidence(
            runKey = entry.runId,
            stepKey = entry.stepId,
            attempt = entry.attempt,
            resolverUsed = entry.resolverUsed,
            uiGeneration = entry.uiGeneration
        )
    }
}

data class HybridFailedStepContext(
    val stepIndex: Int,
    val stepId: String,
    val action: String,
    val errorCode: String,
    val outcomeState: String
)

data class AgentHandoffContext(
    val templateId: String,
    val templateRevision: Int,
    val targetProfileId: String,
    val workflowDigest: String,
    val opaqueRunKey: String,
    val completedSteps: List<HybridCompletedStepEvidence>,
    val failedStep: HybridFailedStepContext,
    val replayForbiddenUntilProof: Boolean
)

interface HybridWorkflowExecutor {
    fun run(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext? = null,
        cancelled: () -> Boolean = { false },
        deadlineAt: Long = safeDeadline(System.currentTimeMillis(), workflow.maxDurationMs)
    ): HybridRunResult

    fun runValidation(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext? = null,
        cancelled: () -> Boolean = { false },
        deadlineAt: Long = safeDeadline(System.currentTimeMillis(), workflow.maxDurationMs)
    ): HybridRunResult = run(workflow, runId, resumeFrom, cancelled, deadlineAt)
}

data class HybridRunResult(
    val success: Boolean,
    val steps: List<RpaStepRecord>,
    val errorCode: String = "",
    val outcomeState: String,
    val dispatchCount: Int,
    val rounds: Int,
    val mode: String = HYBRID_EXECUTION_MODE,
    val agentHandoffRequired: Boolean = false,
    val handoffContext: AgentHandoffContext? = null,
    val stoppedStepIndex: Int = 0,
    val templateAuthorized: Boolean = false
)

private data class EngineStop(
    val errorCode: String,
    val outcomeState: String,
    val handoff: Boolean,
    val replayForbidden: Boolean = false
)

class HybridRpaEngine private constructor(
    private val evidenceSource: HybridEvidenceSource,
    private val arbiter: HybridResolutionArbiter,
    private val generation: () -> GenerationSnapshot?,
    private val clock: () -> Long = System::currentTimeMillis,
    private val resumeProofVerifier: ResumeProofVerifier = ResumeProofVerifier.denyAll(),
    private val executorCall: (PreparedAction) -> ActionOutcome
) : HybridWorkflowExecutor {
    constructor(
        evidenceSource: HybridEvidenceSource,
        arbiter: HybridResolutionArbiter,
        executor: SingleDispatchExecutor,
        generation: () -> GenerationSnapshot?,
        clock: () -> Long = System::currentTimeMillis,
        resumeProofVerifier: ResumeProofVerifier = ResumeProofVerifier.denyAll()
    ) : this(
        evidenceSource = evidenceSource,
        arbiter = arbiter,
        generation = generation,
        clock = clock,
        resumeProofVerifier = resumeProofVerifier,
        executorCall = executor::execute
    )

    override fun run(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext?,
        cancelled: () -> Boolean,
        deadlineAt: Long
    ): HybridRunResult {
        if (workflow.executionMode != HYBRID_EXECUTION_MODE) {
            return terminalResult(
                errorCode = "hybrid_mode_required",
                outcomeState = "blocked",
                stoppedStepIndex = 0
            )
        }
        if (RpaWorkflowParser.validate(workflow).isNotEmpty()) {
            return terminalResult(
                errorCode = "invalid_workflow",
                outcomeState = "blocked",
                stoppedStepIndex = 0
            )
        }

        val digest = workflowDigest(workflow)
        val opaqueRunKey = runCatching {
            ActionIdentity(runId, workflow.steps.first().id, 1).toOpaqueLedgerKey().runKey
        }.getOrElse {
            return terminalResult("run_identity_invalid", "blocked", 0)
        }
        val resumedPrefix = validateResumePrefix(workflow, runId, resumeFrom, digest, opaqueRunKey)
            ?: if (resumeFrom != null) {
                return terminalResult("resume_proof_invalid", "blocked", 0)
            } else {
                emptyList()
            }

        val records = mutableListOf<RpaStepRecord>()
        val completed = mutableListOf<HybridCompletedStepEvidence>()
        var dispatchCount = 0
        var rounds = 0

        for ((index, step) in workflow.steps.withIndex()) {
            val resumed = resumedPrefix.getOrNull(index)
            if (resumed != null) {
                completed += resumed
                records += resumed.toRecord(index, step)
                continue
            }

            controlStop(cancelled, deadlineAt)?.let { stop ->
                return stopResult(stop, workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
            }

            val safety = RpaSafetyPolicy.inspect(step)
            if (!safety.allowed) {
                val startedAt = safeNow()
                records += failedRecord(
                    index = index,
                    step = step,
                    startedAt = startedAt,
                    attempts = 0,
                    errorCode = safety.errorCode,
                    outcomeState = "unsafe",
                    dispatchCount = 0,
                    rounds = 0,
                    ready = null,
                    captureMs = 0L,
                    verifyMs = 0L
                )
                return failureResult(
                    workflow = workflow,
                    digest = digest,
                    opaqueRunKey = opaqueRunKey,
                    records = records,
                    completed = completed,
                    step = step,
                    index = index,
                    errorCode = safety.errorCode,
                    outcomeState = "unsafe",
                    dispatchCount = dispatchCount,
                    rounds = rounds,
                    handoff = true,
                    replayForbidden = true
                )
            }

            val stepStartedAt = safeNow()
            val stepState = StepExecutionState()
            var lastReady: Resolution.Ready? = null
            var lastOutcome: ActionOutcome? = null
            var attempts = 0

            while (attempts < MAX_DISPATCH_ATTEMPTS) {
                val resolution = resolveForClaim(
                    step = step,
                    cancelled = cancelled,
                    deadlineAt = deadlineAt,
                    state = stepState
                )
                rounds += resolution.rounds
                stepState.captureMs = saturatedAdd(stepState.captureMs, resolution.captureMs)

                resolution.stop?.let { stop ->
                    val record = failedRecord(
                        index = index,
                        step = step,
                        startedAt = stepStartedAt,
                        attempts = attempts,
                        errorCode = stop.errorCode,
                        outcomeState = stop.outcomeState,
                        dispatchCount = stepState.dispatchCount,
                        rounds = stepState.rounds,
                        ready = resolution.ready,
                        captureMs = stepState.captureMs,
                        verifyMs = stepState.verifyMs,
                        treeSnapshotMs = stepState.treeSnapshotMs,
                        treeLookupMs = stepState.treeLookupMs
                    )
                    records += record
                    return failureResult(
                        workflow = workflow,
                        digest = digest,
                        opaqueRunKey = opaqueRunKey,
                        records = records,
                        completed = completed,
                        step = step,
                        index = index,
                        errorCode = stop.errorCode,
                        outcomeState = stop.outcomeState,
                        dispatchCount = dispatchCount,
                        rounds = rounds,
                        handoff = stop.handoff,
                        replayForbidden = stop.replayForbidden
                    )
                }

                val ready = resolution.ready ?: error("resolution must be ready or stopped")
                lastReady = ready
                controlStop(cancelled, deadlineAt)?.let { stop ->
                    return stopResult(stop, workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
                }

                val currentGeneration = runCatching { generation() }.getOrNull()
                if (!ready.matches(currentGeneration)) {
                    if (!stepState.reresolutionUsed) {
                        stepState.reresolutionUsed = true
                        continue
                    }
                    val record = failedRecord(
                        index,
                        step,
                        stepStartedAt,
                        attempts,
                        HybridResolutionArbiter.ERROR_STALE_RESOLUTION_EVIDENCE,
                        "blocked",
                        stepState.dispatchCount,
                        stepState.rounds,
                        ready,
                        stepState.captureMs,
                        stepState.verifyMs
                    )
                    records += record
                    return failureResult(
                        workflow,
                        digest,
                        opaqueRunKey,
                        records,
                        completed,
                        step,
                        index,
                        HybridResolutionArbiter.ERROR_STALE_RESOLUTION_EVIDENCE,
                        "blocked",
                        dispatchCount,
                        rounds,
                        handoff = true,
                        replayForbidden = false
                    )
                }
                if (!SERVICE_GENERATION_PATTERN.matches(ready.evidence.serviceGeneration)) {
                    records += failedRecord(
                        index, step, stepStartedAt, attempts,
                        "service_generation_invalid", "blocked",
                        stepState.dispatchCount, stepState.rounds, ready,
                        stepState.captureMs, stepState.verifyMs
                    )
                    return failureResult(
                        workflow, digest, opaqueRunKey, records, completed, step, index,
                        "service_generation_invalid", "blocked", dispatchCount, rounds,
                        handoff = true, replayForbidden = false
                    )
                }

                attempts += 1
                val verifyStartedAt = safeNow()
                val prepared = PreparedAction(
                    runId = runId,
                    stepId = step.id,
                    attempt = attempts,
                    uiGeneration = ready.evidence.uiGeneration,
                    serviceGeneration = ready.evidence.serviceGeneration,
                    resolverUsed = ready.resolverUsed,
                    payload = ready.payload,
                    preDispatchGuard = claimedGuard(ready, cancelled, deadlineAt)
                )
                val toolCallStartedAt = safeNow()
                val outcome = try {
                    executorCall(prepared)
                } catch (_: Throwable) {
                    stepState.toolCallMs = saturatedAdd(
                        stepState.toolCallMs,
                        elapsed(toolCallStartedAt, safeNow())
                    )
                    val uncertain = failedRecord(
                        index, step, stepStartedAt, attempts,
                        "executor_outcome_unknown", "uncertain",
                        stepState.dispatchCount, stepState.rounds, ready,
                        stepState.captureMs, stepState.verifyMs, stepState.toolCallMs
                    )
                    records += uncertain
                    return failureResult(
                        workflow, digest, opaqueRunKey, records, completed, step, index,
                        "executor_outcome_unknown", "uncertain", dispatchCount, rounds,
                        handoff = true, replayForbidden = true
                    )
                }
                stepState.toolCallMs = saturatedAdd(
                    stepState.toolCallMs,
                    elapsed(toolCallStartedAt, safeNow())
                )
                val verifyMs = elapsed(verifyStartedAt, safeNow())
                stepState.verifyMs = saturatedAdd(stepState.verifyMs, verifyMs)
                lastOutcome = outcome
                if (outcome.dispatchInvoked) {
                    dispatchCount += 1
                    stepState.dispatchCount += 1
                }

                when (outcome.state) {
                    ActionOutcomeState.UNCERTAIN -> {
                        val record = outcomeRecord(
                            index,
                            step,
                            stepStartedAt,
                            attempts,
                            outcome,
                            ready,
                            stepState
                        )
                        records += record
                        return failureResult(
                            workflow, digest, opaqueRunKey,
                            records,
                            completed,
                            step,
                            index,
                            outcome.errorCode,
                            "uncertain",
                            dispatchCount,
                            rounds,
                            handoff = true,
                            replayForbidden = true
                        )
                    }
                    ActionOutcomeState.VERIFIED -> {
                        val record = outcomeRecord(
                            index,
                            step,
                            stepStartedAt,
                            attempts,
                            outcome,
                            ready,
                            stepState
                        )
                        records += record
                        completed += outcome.toCompletedEvidence(index, step, ready)
                        controlStop(cancelled, deadlineAt)?.let { stop ->
                            return stopResult(stop, workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
                        }
                        break
                    }
                    ActionOutcomeState.FAILED_NO_DISPATCH,
                    ActionOutcomeState.FAILED_NO_EFFECT -> {
                        if (!outcome.durable) {
                            val uncertain = outcome.copy(
                                state = ActionOutcomeState.UNCERTAIN,
                                errorCode = ActionLedgerErrors.DURABILITY_UNAVAILABLE
                            )
                            records += outcomeRecord(
                                index,
                                step,
                                stepStartedAt,
                                attempts,
                                uncertain,
                                ready,
                                stepState
                            )
                            return failureResult(
                                workflow, digest, opaqueRunKey,
                                records,
                                completed,
                                step,
                                index,
                                uncertain.errorCode,
                                "uncertain",
                                dispatchCount,
                                rounds,
                                handoff = true,
                                replayForbidden = true
                            )
                        }
                        when (outcome.preDispatchFailure) {
                            ClaimedPreDispatchFailure.CANCELLED ->
                                return stopResult(EngineStop("cancelled", "cancelled", false), workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
                            ClaimedPreDispatchFailure.DEADLINE_EXCEEDED ->
                                return stopResult(EngineStop("hybrid_timeout", "timeout", false), workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
                            ClaimedPreDispatchFailure.GENERATION_CHANGED -> {
                                if (!stepState.reresolutionUsed) {
                                    stepState.reresolutionUsed = true
                                    continue
                                }
                                records += outcomeRecord(index, step, stepStartedAt, attempts, outcome, ready, stepState)
                                return failureResult(
                                    workflow, digest, opaqueRunKey, records, completed, step, index,
                                    HybridResolutionArbiter.ERROR_STALE_RESOLUTION_EVIDENCE,
                                    "blocked", dispatchCount, rounds,
                                    handoff = true, replayForbidden = false
                                )
                            }
                            ClaimedPreDispatchFailure.RESULT_MISSING,
                            ClaimedPreDispatchFailure.EXCEPTION -> {
                                records += outcomeRecord(index, step, stepStartedAt, attempts, outcome, ready, stepState)
                                return failureResult(
                                    workflow, digest, opaqueRunKey, records, completed, step, index,
                                    outcome.errorCode, "blocked", dispatchCount, rounds,
                                    handoff = true, replayForbidden = false
                                )
                            }
                            null -> Unit
                        }
                        controlStop(cancelled, deadlineAt)?.let { stop ->
                            records += outcomeRecord(
                                index,
                                step,
                                stepStartedAt,
                                attempts,
                                outcome,
                                ready,
                                stepState
                            )
                            return stopResult(stop, workflow, digest, opaqueRunKey, records, completed, dispatchCount, rounds, index, step)
                        }
                        if (attempts >= MAX_DISPATCH_ATTEMPTS) {
                            records += outcomeRecord(
                                index,
                                step,
                                stepStartedAt,
                                attempts,
                                outcome,
                                ready,
                                stepState
                            )
                            return failureResult(
                                workflow, digest, opaqueRunKey,
                                records,
                                completed,
                                step,
                                index,
                                outcome.errorCode,
                                outcome.state.wireName(),
                                dispatchCount,
                                rounds,
                                handoff = true,
                                replayForbidden = false
                            )
                        }
                    }
                }
            }

            if (lastOutcome?.state != ActionOutcomeState.VERIFIED) {
                val errorCode = lastOutcome?.errorCode ?: "target_unresolved"
                records += failedRecord(
                    index,
                    step,
                    stepStartedAt,
                    attempts,
                    errorCode,
                    lastOutcome?.state?.wireName() ?: "blocked",
                    stepState.dispatchCount,
                    stepState.rounds,
                    lastReady,
                    stepState.captureMs,
                    stepState.verifyMs
                )
                return failureResult(
                    workflow, digest, opaqueRunKey,
                    records,
                    completed,
                    step,
                    index,
                    errorCode,
                    lastOutcome?.state?.wireName() ?: "blocked",
                    dispatchCount,
                    rounds,
                    handoff = true,
                    replayForbidden = false
                )
            }
        }

        return HybridRunResult(
            success = true,
            steps = records.toList(),
            outcomeState = "verified",
            dispatchCount = dispatchCount.coerceAtLeast(0),
            rounds = rounds.coerceAtLeast(0)
        )
    }

    private fun resolveForClaim(
        step: RpaStep,
        cancelled: () -> Boolean,
        deadlineAt: Long,
        state: StepExecutionState
    ): ClaimResolution {
        var localRounds = 0
        var captureTotal = 0L
        while (true) {
            controlStop(cancelled, deadlineAt)?.let { stop ->
                return ClaimResolution(stop = stop, rounds = localRounds, captureMs = captureTotal)
            }
            val initialRequirement = when (step.resolverPolicy) {
                ResolverPolicy.VISION_REQUIRED,
                ResolverPolicy.DUAL_CONFIRM -> FreshnessRequirement.AuthorizeAfter(safeNow())
                ResolverPolicy.DIRECT,
                ResolverPolicy.TREE_PREFERRED -> FreshnessRequirement.ReadOnly
            }
            val initial = capture(initialRequirement, cancelled, deadlineAt)
            captureTotal = saturatedAdd(captureTotal, initial.captureMs)
            if (initial.counted) {
                localRounds++
                state.rounds++
            }
            initial.stop?.let {
                return ClaimResolution(stop = it, rounds = localRounds, captureMs = captureTotal)
            }
            val evidence = initial.evidence ?: return ClaimResolution(
                stop = EngineStop("evidence_capture_failed", "blocked", true),
                rounds = localRounds,
                captureMs = captureTotal
            )
            state.treeSnapshotMs = saturatedAdd(state.treeSnapshotMs, evidence.treeSnapshotMs)

            var authorizationEvidence = evidence
            var authorizationRequirement = initialRequirement
            val treeLookupStartedAt = if (step.resolverPolicy == ResolverPolicy.TREE_PREFERRED) safeNow() else 0L
            var resolved = try {
                if (step.resolverPolicy == ResolverPolicy.TREE_PREFERRED) {
                    arbiter.resolveTreeSemantic(step, evidence)
                } else {
                    arbiter.resolve(step, evidence)
                }
            } catch (_: Throwable) {
                Resolution.Handoff("resolver_failed")
            }
            if (step.resolverPolicy == ResolverPolicy.TREE_PREFERRED) {
                state.treeLookupMs = saturatedAdd(
                    state.treeLookupMs,
                    elapsed(treeLookupStartedAt, safeNow())
                )
            }

            if (step.resolverPolicy == ResolverPolicy.TREE_PREFERRED &&
                resolved is Resolution.Missing && step.hasVisualFallback()
            ) {
                controlStop(cancelled, deadlineAt)?.let { stop ->
                    return ClaimResolution(stop = stop, rounds = localRounds, captureMs = captureTotal)
                }
                val visualRequirement = FreshnessRequirement.AuthorizeAfter(safeNow())
                val visual = capture(visualRequirement, cancelled, deadlineAt)
                captureTotal = saturatedAdd(captureTotal, visual.captureMs)
                if (visual.counted) {
                    localRounds++
                    state.rounds++
                }
                visual.stop?.let {
                    return ClaimResolution(stop = it, rounds = localRounds, captureMs = captureTotal)
                }
                authorizationEvidence = visual.evidence ?: return ClaimResolution(
                    stop = EngineStop("evidence_capture_failed", "blocked", true),
                    rounds = localRounds,
                    captureMs = captureTotal
                )
                state.treeSnapshotMs = saturatedAdd(
                    state.treeSnapshotMs,
                    authorizationEvidence.treeSnapshotMs
                )
                authorizationRequirement = visualRequirement
                resolved = try {
                    arbiter.resolveTreeVisualFallback(step, authorizationEvidence)
                } catch (_: Throwable) {
                    Resolution.Handoff("resolver_failed")
                }
            }

            if (resolved is Resolution.Ready &&
                authorizationRequirement is FreshnessRequirement.AuthorizeAfter &&
                !ScreenshotFreshnessPolicy.accepts(authorizationEvidence, authorizationRequirement)
            ) {
                resolved = Resolution.Blocked("visual_evidence_not_fresh")
            }
            if (resolved is Resolution.Ready) {
                return ClaimResolution(
                    ready = resolved.copy(
                        metrics = resolved.metrics.copy(
                            treeSnapshotMs = state.treeSnapshotMs,
                            treeLookupMs = if (step.resolverPolicy == ResolverPolicy.TREE_PREFERRED) {
                                state.treeLookupMs
                            } else {
                                saturatedAdd(state.treeLookupMs, resolved.metrics.treeLookupMs)
                            },
                            captureMs = saturatedAdd(resolved.metrics.captureMs, captureTotal)
                        ).nonnegative()
                    ),
                    rounds = localRounds,
                    captureMs = captureTotal
                )
            }
            if (resolved.canReresolve() && !state.reresolutionUsed) {
                state.reresolutionUsed = true
                continue
            }
            return ClaimResolution(
                stop = resolved.toStop(),
                rounds = localRounds,
                captureMs = captureTotal
            )
        }
    }

    private fun capture(
        requirement: FreshnessRequirement,
        cancelled: () -> Boolean,
        deadlineAt: Long
    ): EvidenceCapture {
        controlStop(cancelled, deadlineAt)?.let { return EvidenceCapture(stop = it) }
        val startedAt = safeNow()
        val evidence = try {
            evidenceSource.capture(requirement)
        } catch (_: Throwable) {
            return EvidenceCapture(
                stop = EngineStop("evidence_capture_failed", "blocked", handoff = true),
                captureMs = elapsed(startedAt, safeNow()),
                counted = true
            )
        }
        val captureMs = elapsed(startedAt, safeNow())
        controlStop(cancelled, deadlineAt)?.let {
            return EvidenceCapture(stop = it, captureMs = captureMs, counted = true)
        }
        return EvidenceCapture(evidence = evidence, captureMs = captureMs, counted = true)
    }

    private fun claimedGuard(
        ready: Resolution.Ready,
        cancelled: () -> Boolean,
        deadlineAt: Long
    ): ClaimedPreDispatchGuard = ClaimedPreDispatchGuard {
        if (runCatching { cancelled() }.getOrDefault(true)) {
            ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.CANCELLED)
        } else if (safeNow() >= deadlineAt) {
            ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.DEADLINE_EXCEEDED)
        } else {
            val current = runCatching { generation() }.getOrNull()
            if (!ready.matches(current)) {
                ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.GENERATION_CHANGED)
            } else {
                ClaimedPreDispatchDecision.Allow
            }
        }
    }

    private fun validateResumePrefix(
        workflow: RpaWorkflow,
        runId: String,
        context: AgentHandoffContext?,
        digest: String,
        opaqueRunKey: String
    ): List<HybridCompletedStepEvidence>? {
        if (context == null) return emptyList()
        if (context.templateId != workflow.templateId ||
            context.templateRevision != workflow.templateRevision ||
            context.targetProfileId != workflow.targetProfileId ||
            context.workflowDigest != digest ||
            context.opaqueRunKey != opaqueRunKey ||
            context.completedSteps.isEmpty() ||
            context.completedSteps.size >= workflow.steps.size ||
            safeError(context.failedStep.errorCode) != context.failedStep.errorCode ||
            safeOutcome(context.failedStep.outcomeState) != context.failedStep.outcomeState
        ) return null

        val reconstructed = ArrayList<HybridCompletedStepEvidence>(context.completedSteps.size)
        context.completedSteps.forEachIndexed { index, supplied ->
            val step = workflow.steps[index]
            if (supplied.stepIndex != index + 1 ||
                supplied.stepId != step.id ||
                supplied.action != safeAction(step.action) ||
                supplied.outcomeState != "verified" ||
                !isResolverName(supplied.resolverUsed)
            ) return null
            val expectedKey = runCatching {
                ActionIdentity(runId, step.id, supplied.ledgerProof.attempt).toOpaqueLedgerKey()
            }.getOrNull() ?: return null
            if (supplied.ledgerProof.runKey != opaqueRunKey ||
                supplied.ledgerProof.runKey != expectedKey.runKey ||
                supplied.ledgerProof.stepKey != expectedKey.stepKey ||
                supplied.ledgerProof.attempt !in 1..MAX_HYBRID_ATTEMPTS
            ) return null
            val verified = resumeProofVerifier.verify(supplied.ledgerProof) ?: return null
            if (verified.runKey != expectedKey.runKey ||
                verified.stepKey != expectedKey.stepKey ||
                verified.attempt != supplied.ledgerProof.attempt ||
                verified.resolverUsed.name != supplied.resolverUsed
            ) return null
            reconstructed += HybridCompletedStepEvidence(
                stepIndex = index + 1,
                stepId = safeIdentifier(step.id),
                action = safeAction(step.action),
                resolverUsed = verified.resolverUsed.name,
                uiGeneration = verified.uiGeneration.coerceAtLeast(0L),
                attempts = verified.attempt.coerceIn(1, MAX_HYBRID_ATTEMPTS),
                outcomeState = "verified",
                ledgerProof = HybridLedgerProof(
                    runKey = verified.runKey,
                    stepKey = verified.stepKey,
                    attempt = verified.attempt
                )
            )
        }
        val failedIndex = reconstructed.size
        val expectedFailed = workflow.steps.getOrNull(failedIndex) ?: return null
        if (context.failedStep.stepIndex != failedIndex + 1 ||
            context.failedStep.stepId != expectedFailed.id ||
            context.failedStep.action != safeAction(expectedFailed.action)
        ) return null
        return reconstructed
    }

    private fun failureResult(
        workflow: RpaWorkflow,
        digest: String,
        opaqueRunKey: String,
        records: List<RpaStepRecord>,
        completed: List<HybridCompletedStepEvidence>,
        step: RpaStep,
        index: Int,
        errorCode: String,
        outcomeState: String,
        dispatchCount: Int,
        rounds: Int,
        handoff: Boolean,
        replayForbidden: Boolean
    ): HybridRunResult {
        val context = if (handoff) {
            AgentHandoffContext(
                templateId = safeIdentifier(workflow.templateId),
                templateRevision = workflow.templateRevision.coerceAtLeast(1),
                targetProfileId = safeIdentifier(workflow.targetProfileId),
                workflowDigest = digest.takeIf { OPAQUE_PROOF_PATTERN.matches(it) }.orEmpty(),
                opaqueRunKey = opaqueRunKey.takeIf { OPAQUE_PROOF_PATTERN.matches(it) }.orEmpty(),
                completedSteps = completed.map { item ->
                    HybridCompletedStepEvidence(
                        stepIndex = item.stepIndex,
                        stepId = safeIdentifier(item.stepId),
                        action = safeAction(item.action),
                        resolverUsed = item.resolverUsed.takeIf(::isResolverName).orEmpty(),
                        uiGeneration = item.uiGeneration.coerceAtLeast(0L),
                        attempts = item.attempts.coerceIn(1, MAX_HYBRID_ATTEMPTS),
                        outcomeState = "verified",
                        ledgerProof = HybridLedgerProof(
                            runKey = item.ledgerProof.runKey.takeIf { OPAQUE_PROOF_PATTERN.matches(it) }.orEmpty(),
                            stepKey = item.ledgerProof.stepKey.takeIf { OPAQUE_PROOF_PATTERN.matches(it) }.orEmpty(),
                            attempt = item.ledgerProof.attempt.coerceIn(1, MAX_HYBRID_ATTEMPTS)
                        )
                    )
                },
                failedStep = HybridFailedStepContext(
                    stepIndex = index + 1,
                    stepId = safeIdentifier(step.id),
                    action = safeAction(step.action),
                    errorCode = safeError(errorCode),
                    outcomeState = safeOutcome(outcomeState)
                ),
                replayForbiddenUntilProof = replayForbidden
            )
        } else {
            null
        }
        return HybridRunResult(
            success = false,
            steps = records.toList(),
            errorCode = safeError(errorCode),
            outcomeState = safeOutcome(outcomeState),
            dispatchCount = dispatchCount.coerceAtLeast(0),
            rounds = rounds.coerceAtLeast(0),
            agentHandoffRequired = handoff,
            handoffContext = context,
            stoppedStepIndex = index + 1
        )
    }

    private fun stopResult(
        stop: EngineStop,
        workflow: RpaWorkflow,
        digest: String,
        opaqueRunKey: String,
        records: List<RpaStepRecord>,
        completed: List<HybridCompletedStepEvidence>,
        dispatchCount: Int,
        rounds: Int,
        index: Int,
        step: RpaStep
    ): HybridRunResult = failureResult(
        workflow = workflow,
        digest = digest,
        opaqueRunKey = opaqueRunKey,
        records = records,
        completed = completed,
        step = step,
        index = index,
        errorCode = stop.errorCode,
        outcomeState = stop.outcomeState,
        dispatchCount = dispatchCount,
        rounds = rounds,
        handoff = stop.handoff,
        replayForbidden = stop.replayForbidden
    )

    private fun terminalResult(
        errorCode: String,
        outcomeState: String,
        stoppedStepIndex: Int
    ) = HybridRunResult(
        success = false,
        steps = emptyList(),
        errorCode = errorCode,
        outcomeState = outcomeState,
        dispatchCount = 0,
        rounds = 0,
        stoppedStepIndex = stoppedStepIndex
    )

    private fun outcomeRecord(
        index: Int,
        step: RpaStep,
        startedAt: Long,
        attempts: Int,
        outcome: ActionOutcome,
        ready: Resolution.Ready,
        state: StepExecutionState
    ): RpaStepRecord {
        val succeeded = outcome.state == ActionOutcomeState.VERIFIED
        return RpaStepRecord(
            index = index + 1,
            stepId = step.id,
            action = safeAction(step.action),
            status = if (succeeded) "succeeded" else "failed",
            attempts = attempts.coerceAtLeast(0),
            actionMs = elapsed(startedAt, safeNow()),
            message = outcome.state.wireName(),
            errorCode = if (succeeded) "" else safeError(outcome.errorCode),
            retryable = outcome.durable && outcome.state in RETRYABLE_OUTCOMES,
            startedAt = startedAt.coerceAtLeast(0L),
            finishedAt = safeNow(),
            resolverPolicy = step.resolverPolicy.name,
            resolverUsed = ready.resolverUsed.name,
            treeSnapshotMs = ready.metrics.treeSnapshotMs.coerceAtLeast(0L),
            treeLookupMs = ready.metrics.treeLookupMs.coerceAtLeast(0L),
            nodesVisited = ready.metrics.nodesVisited.coerceAtLeast(0),
            captureMs = maxOf(state.captureMs, ready.metrics.captureMs).coerceAtLeast(0L),
            matchMs = ready.metrics.matchMs.coerceAtLeast(0L),
            verifyMs = state.verifyMs.coerceAtLeast(0L),
            frameId = ready.evidence.frameId.orEmpty().take(128),
            frameSource = ready.evidence.frameSource.orEmpty().take(32),
            frameAgeMs = ready.evidence.frameAgeMs?.coerceAtLeast(0L) ?: 0L,
            uiGeneration = ready.evidence.uiGeneration.coerceAtLeast(0L),
            outcomeState = outcome.state.wireName(),
            dispatchCount = state.dispatchCount.coerceAtLeast(0),
            rounds = state.rounds.coerceAtLeast(0),
            compactTreeReads = 1,
            fullTreeReads = 0,
            toolCallMs = state.toolCallMs.coerceAtLeast(0L),
            mode = HYBRID_EXECUTION_MODE
        )
    }

    private fun failedRecord(
        index: Int,
        step: RpaStep,
        startedAt: Long,
        attempts: Int,
        errorCode: String,
        outcomeState: String,
        dispatchCount: Int,
        rounds: Int,
        ready: Resolution.Ready?,
        captureMs: Long,
        verifyMs: Long,
        toolCallMs: Long = 0L,
        treeSnapshotMs: Long = ready?.metrics?.treeSnapshotMs ?: 0L,
        treeLookupMs: Long = ready?.metrics?.treeLookupMs ?: 0L
    ) = RpaStepRecord(
        index = index + 1,
        stepId = step.id,
        action = safeAction(step.action),
        status = "failed",
        attempts = attempts.coerceAtLeast(0),
        actionMs = elapsed(startedAt, safeNow()),
        message = safeError(errorCode),
        errorCode = safeError(errorCode),
        retryable = false,
        startedAt = startedAt.coerceAtLeast(0L),
        finishedAt = safeNow(),
        resolverPolicy = step.resolverPolicy.name,
        resolverUsed = ready?.resolverUsed?.name.orEmpty(),
        treeSnapshotMs = treeSnapshotMs.coerceAtLeast(0L),
        treeLookupMs = treeLookupMs.coerceAtLeast(0L),
        nodesVisited = ready?.metrics?.nodesVisited?.coerceAtLeast(0) ?: 0,
        captureMs = captureMs.coerceAtLeast(0L),
        matchMs = ready?.metrics?.matchMs?.coerceAtLeast(0L) ?: 0L,
        verifyMs = verifyMs.coerceAtLeast(0L),
        frameId = ready?.evidence?.frameId.orEmpty().take(128),
        frameSource = ready?.evidence?.frameSource.orEmpty().take(32),
        frameAgeMs = ready?.evidence?.frameAgeMs?.coerceAtLeast(0L) ?: 0L,
        uiGeneration = ready?.evidence?.uiGeneration?.coerceAtLeast(0L) ?: 0L,
        outcomeState = safeOutcome(outcomeState),
        dispatchCount = dispatchCount.coerceAtLeast(0),
        rounds = rounds.coerceAtLeast(0),
        compactTreeReads = if (ready != null) 1 else 0,
        fullTreeReads = 0,
        toolCallMs = toolCallMs.coerceAtLeast(0L),
        mode = HYBRID_EXECUTION_MODE
    )

    private fun controlStop(cancelled: () -> Boolean, deadlineAt: Long): EngineStop? {
        if (runCatching { cancelled() }.getOrDefault(true)) {
            return EngineStop("cancelled", "cancelled", handoff = false)
        }
        if (safeNow() >= deadlineAt) {
            return EngineStop("hybrid_timeout", "timeout", handoff = false)
        }
        return null
    }

    private fun safeNow(): Long = runCatching { clock() }.getOrDefault(0L).coerceAtLeast(0L)

    private data class StepExecutionState(
        var reresolutionUsed: Boolean = false,
        var captureMs: Long = 0L,
        var verifyMs: Long = 0L,
        var toolCallMs: Long = 0L,
        var treeSnapshotMs: Long = 0L,
        var treeLookupMs: Long = 0L,
        var dispatchCount: Int = 0,
        var rounds: Int = 0
    )

    private data class ClaimResolution(
        val ready: Resolution.Ready? = null,
        val stop: EngineStop? = null,
        val rounds: Int,
        val captureMs: Long
    )

    private data class EvidenceCapture(
        val evidence: UiEvidence? = null,
        val stop: EngineStop? = null,
        val captureMs: Long = 0L,
        val counted: Boolean = false
    )

    companion object {
        private const val MAX_DISPATCH_ATTEMPTS = MAX_HYBRID_ATTEMPTS
        private val RETRYABLE_OUTCOMES = setOf(
            ActionOutcomeState.FAILED_NO_DISPATCH,
            ActionOutcomeState.FAILED_NO_EFFECT
        )

        internal fun forTesting(
            evidenceSource: HybridEvidenceSource,
            arbiter: HybridResolutionArbiter,
            generation: () -> GenerationSnapshot?,
            clock: () -> Long,
            resumeProofVerifier: ResumeProofVerifier,
            executorCall: (PreparedAction) -> ActionOutcome
        ): HybridRpaEngine = HybridRpaEngine(
            evidenceSource = evidenceSource,
            arbiter = arbiter,
            generation = generation,
            clock = clock,
            resumeProofVerifier = resumeProofVerifier,
            executorCall = executorCall
        )
    }
}

private fun Resolution.canReresolve(): Boolean = when (this) {
    is Resolution.Missing,
    is Resolution.Ambiguous -> true
    is Resolution.Blocked -> errorCode in setOf(
        HybridResolutionArbiter.ERROR_STALE_RESOLUTION_EVIDENCE,
        "visual_evidence_not_fresh"
    )
    else -> false
}

private fun Resolution.toStop(): EngineStop = when (this) {
    is Resolution.Missing -> EngineStop("target_unresolved", "missing", handoff = true)
    is Resolution.Ambiguous -> EngineStop("target_ambiguous", "ambiguous", handoff = true)
    is Resolution.Blocked -> EngineStop(errorCode, "blocked", handoff = true)
    is Resolution.Unsafe -> EngineStop(errorCode, "unsafe", handoff = true, replayForbidden = true)
    is Resolution.Handoff -> EngineStop(errorCode, "handoff", handoff = true)
    is Resolution.Ready -> error("ready resolution cannot become a stop")
}

private fun Resolution.Ready.matches(current: GenerationSnapshot?): Boolean =
    current != null &&
        current.uiGeneration == evidence.uiGeneration &&
        current.serviceGeneration == evidence.serviceGeneration

private fun RpaStep.hasVisualFallback(): Boolean =
    allowedResolvers.any { it == ResolverKind.VISUAL_ANCHOR || it == ResolverKind.NORMALIZED_COORDINATE }

private fun ActionOutcomeState.wireName(): String = name.lowercase()

private fun ActionOutcome.toCompletedEvidence(
    index: Int,
    step: RpaStep,
    ready: Resolution.Ready
) = HybridCompletedStepEvidence(
    stepIndex = index + 1,
    stepId = safeIdentifier(step.id),
    action = safeAction(step.action),
    resolverUsed = ready.resolverUsed.name,
    uiGeneration = entry.uiGeneration.coerceAtLeast(0L),
    attempts = entry.attempt.coerceIn(1, MAX_HYBRID_ATTEMPTS),
    ledgerProof = HybridLedgerProof(
        runKey = entry.runId,
        stepKey = entry.stepId,
        attempt = entry.attempt
    )
)

private fun HybridCompletedStepEvidence.toRecord(index: Int, step: RpaStep): RpaStepRecord {
    val now = 0L
    return RpaStepRecord(
        index = index + 1,
        stepId = safeIdentifier(step.id),
        action = safeAction(step.action),
        status = "succeeded",
        attempts = attempts.coerceIn(1, MAX_HYBRID_ATTEMPTS),
        actionMs = 0L,
        message = "verified_resume",
        startedAt = now,
        finishedAt = now,
        resolverPolicy = step.resolverPolicy.name,
        resolverUsed = resolverUsed.takeIf { it in ResolverKind.entries.map(ResolverKind::name) }.orEmpty(),
        uiGeneration = uiGeneration.coerceAtLeast(0L),
        outcomeState = "verified",
        dispatchCount = 0,
        rounds = 0,
        compactTreeReads = 0,
        fullTreeReads = 0,
        mode = HYBRID_EXECUTION_MODE
    )
}

private fun safeDeadline(startedAt: Long, durationMs: Long): Long =
    if (durationMs <= 0L || startedAt > Long.MAX_VALUE - durationMs) Long.MAX_VALUE else startedAt + durationMs

private fun elapsed(startedAt: Long, finishedAt: Long): Long = when {
    startedAt < 0L || finishedAt <= startedAt -> 0L
    finishedAt - startedAt < 0L -> Long.MAX_VALUE
    else -> finishedAt - startedAt
}

private fun saturatedAdd(first: Long, second: Long): Long = when {
    first < 0L || second < 0L -> 0L
    first > Long.MAX_VALUE - second -> Long.MAX_VALUE
    else -> first + second
}

private val SAFE_HANDOFF_ID = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
private val OPAQUE_PROOF_PATTERN = Regex("^[0-9a-f]{64}$")
private val SERVICE_GENERATION_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
private val SAFE_HYBRID_ACTIONS = setOf(
    "open_app",
    "wait_stable",
    "assert_package",
    "assert_semantic",
    "assert_frame",
    "tap_semantic",
    "tap_anchor",
    "tap_normalized",
    "swipe_normalized",
    "drag_normalized",
    "long_press_anchor",
    "back",
    "home",
    "wait",
    "finish"
)

private fun safeIdentifier(value: String): String = value.takeIf { SAFE_HANDOFF_ID.matches(it) } ?: "redacted"
private fun safeAction(value: String): String = value.takeIf { it in SAFE_HYBRID_ACTIONS } ?: "unsupported"
private fun safeError(value: String): String = value.takeIf { it in SAFE_HYBRID_ERRORS } ?: "hybrid_error"
private fun safeOutcome(value: String): String = value.takeIf { it in SAFE_HYBRID_OUTCOMES } ?: "blocked"
private fun isResolverName(value: String): Boolean = ResolverKind.entries.any { it.name == value }

private val SAFE_HYBRID_OUTCOMES = setOf(
    "verified", "failed_no_dispatch", "failed_no_effect", "uncertain", "blocked",
    "unsafe", "missing", "ambiguous", "handoff", "cancelled", "timeout"
)

private val SAFE_HYBRID_ERRORS = setOf(
    "hybrid_error", "hybrid_mode_required", "invalid_workflow", "run_identity_invalid",
    "resume_proof_invalid", "cancelled", "hybrid_timeout", "safety_blocked",
    "evidence_capture_failed", "resolver_failed", "target_unresolved", "target_ambiguous",
    "fallback_not_validated", "stale_resolution_evidence", "visual_evidence_not_fresh",
    "visual_capture_unsupported", "resolver_disagreement", "resolver_kind_mismatch",
    "resolver_bounds_invalid", "coordinate_checkpoint_unproved", "resolver_confidence_invalid",
    "ephemeral_ref_not_production_safe", "direct_action_unsupported", "dual_confirmation_not_declared",
    "dual_confirmation_missing", "tree_semantic_policy_mismatch", "tree_visual_policy_mismatch",
    "service_generation_invalid", "executor_outcome_unknown",
    ActionLedgerErrors.VERIFIED, ActionLedgerErrors.NO_EFFECT, ActionLedgerErrors.DISPATCH_REJECTED,
    ActionLedgerErrors.DISPATCH_EXCEPTION, ActionLedgerErrors.VERIFIER_EXCEPTION,
    ActionLedgerErrors.VERIFICATION_UNKNOWN, ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH,
    ActionLedgerErrors.SERVICE_GENERATION_CHANGED, ActionLedgerErrors.PREPARE_DURABILITY_FAILURE,
    ActionLedgerErrors.CLAIM_DURABILITY_FAILURE, ActionLedgerErrors.TERMINAL_DURABILITY_FAILURE,
    ActionLedgerErrors.DURABILITY_UNAVAILABLE, ActionLedgerErrors.CALLBACK_RESULT_MISSING,
    ActionLedgerErrors.UI_GENERATION_CHANGED, ActionLedgerErrors.ATTEMPT_SEQUENCE_REJECTED,
    ActionLedgerErrors.REENTRANT_EXECUTE, ActionLedgerErrors.ACTION_OUTCOME_UNKNOWN,
    AccessibilitySemanticDispatcher.ERROR_ACTION_CLICK_REJECTED,
    ClaimedPreDispatchFailure.GENERATION_CHANGED.code,
    ClaimedPreDispatchFailure.CANCELLED.code,
    ClaimedPreDispatchFailure.DEADLINE_EXCEEDED.code,
    ClaimedPreDispatchFailure.RESULT_MISSING.code,
    ClaimedPreDispatchFailure.EXCEPTION.code
)

private fun workflowDigest(workflow: RpaWorkflow): String {
    val canonical = StringBuilder()
    fun atom(value: Any?) {
        val (type, text) = when (value) {
            null -> "N" to ""
            is String -> "S" to value
            is Boolean -> "B" to value.toString()
            is Int -> "I" to value.toString()
            is Long -> "J" to value.toString()
            is Float -> "F" to value.toRawBits().toString()
            is Double -> "D" to value.toRawBits().toString()
            else -> "O" to value.toString()
        }
        canonical.append(type).append(text.length).append(':').append(text).append('|')
    }
    fun any(value: Any?) {
        when (value) {
            is Map<*, *> -> {
                canonical.append("M").append(value.size).append('{')
                value.entries.sortedBy { it.key.toString() }.forEach { atom(it.key); any(it.value) }
                canonical.append('}')
            }
            is Iterable<*> -> {
                val items = value.toList()
                canonical.append("L").append(items.size).append('[')
                items.forEach(::any)
                canonical.append(']')
            }
            else -> atom(value)
        }
    }
    canonical.append("WORKFLOW{")
    atom(workflow.id); atom(workflow.name); atom(workflow.version); atom(workflow.maxDurationMs)
    atom(workflow.schemaVersion); atom(workflow.executionMode); atom(workflow.templateId)
    atom(workflow.templateRevision); atom(workflow.targetProfileId); any(workflow.params)
    canonical.append("STEPS").append(workflow.steps.size).append('[')
    workflow.steps.forEach { step ->
        canonical.append("STEP{")
        atom(step.id); atom(step.action); any(step.params); atom(step.description); atom(step.waitAfterMs)
        atom(step.timeoutMs); atom(step.maxRetries); atom(step.retryDelayMs)
        atom(step.guard.expectedPackage); any(step.guard.requireText); any(step.guard.forbidText)
        atom(step.resolverPolicy.name); any(step.allowedResolvers.map { it.name }.sorted())
        any(step.validatedResolvers.map { it.name }.sorted()); atom(step.resolverPolicyExplicit)
        listOf(step.semanticSelector, step.preCheckpoint?.requiredSelector, step.preCheckpoint?.forbiddenSelector,
            step.postCheckpoint?.requiredSelector, step.postCheckpoint?.forbiddenSelector).forEach { selector ->
            canonical.append("SELECTOR{")
            atom(selector?.resourceId); atom(selector?.contentDescription); atom(selector?.text)
            atom(selector?.className); atom(selector?.packageName); any(selector?.structuralPath.orEmpty())
            canonical.append('}')
        }
        step.visualAnchor?.let { anchor ->
            canonical.append("VISUAL{")
            atom(anchor.assetName); atom(anchor.searchRegion.left); atom(anchor.searchRegion.top)
            atom(anchor.searchRegion.right); atom(anchor.searchRegion.bottom); atom(anchor.tapOffsetX)
            atom(anchor.tapOffsetY); atom(anchor.minimumConfidence); any(anchor.scaleVariants)
            canonical.append('}')
        } ?: canonical.append("VISUAL_NULL")
        listOf(step.preCheckpoint, step.postCheckpoint).forEach { checkpoint ->
            canonical.append("CHECKPOINT{")
            atom(checkpoint?.expectedPackage); atom(checkpoint?.perceptualHash)
            atom(checkpoint?.maximumHammingDistance); atom(checkpoint?.expectedWindowId)
            checkpoint?.expectedDisplayTransform?.let { transform ->
                canonical.append("DISPLAY{")
                atom(transform.displayId); atom(transform.widthPx); atom(transform.heightPx)
                atom(transform.screenshotWidthPx); atom(transform.screenshotHeightPx)
                atom(transform.rotation); atom(transform.densityDpi); atom(transform.insetLeft)
                atom(transform.insetTop); atom(transform.insetRight); atom(transform.insetBottom)
                canonical.append('}')
            } ?: canonical.append("DISPLAY_NULL")
            canonical.append('}')
        }
        canonical.append('}')
    }
    canonical.append("]}")
    val bytes = MessageDigest.getInstance("SHA-256").digest(canonical.toString().toByteArray(Charsets.UTF_8))
    return bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }
}

private const val MAX_HYBRID_ATTEMPTS = 2

const val HYBRID_EXECUTION_MODE = "hybrid_rpa"
