package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind

interface DispatchPayload

enum class ClaimedPreDispatchFailure(val code: String) {
    GENERATION_CHANGED(ActionLedgerErrors.PRE_DISPATCH_GENERATION_CHANGED),
    CANCELLED(ActionLedgerErrors.PRE_DISPATCH_CANCELLED),
    DEADLINE_EXCEEDED(ActionLedgerErrors.PRE_DISPATCH_DEADLINE_EXCEEDED),
    RESULT_MISSING(ActionLedgerErrors.PRE_DISPATCH_GUARD_RESULT_MISSING),
    EXCEPTION(ActionLedgerErrors.PRE_DISPATCH_GUARD_EXCEPTION);

    companion object {
        fun fromCode(code: String): ClaimedPreDispatchFailure? = entries.firstOrNull { it.code == code }
    }
}

sealed interface ClaimedPreDispatchDecision {
    data object Allow : ClaimedPreDispatchDecision
    data class Reject(val failure: ClaimedPreDispatchFailure) : ClaimedPreDispatchDecision
}

fun interface ClaimedPreDispatchGuard {
    fun check(): ClaimedPreDispatchDecision?

    companion object {
        fun allow(): ClaimedPreDispatchGuard = ClaimedPreDispatchGuard {
            ClaimedPreDispatchDecision.Allow
        }
    }
}

data class PreparedAction(
    val runId: String,
    val stepId: String,
    val attempt: Int,
    val uiGeneration: Long,
    val serviceGeneration: String,
    val resolverUsed: ResolverKind,
    val payload: DispatchPayload,
    // Runtime-only gate. It is deliberately excluded from durable ledger material.
    val preDispatchGuard: ClaimedPreDispatchGuard = ClaimedPreDispatchGuard.allow()
) {
    val identity: ActionIdentity
        get() = ActionIdentity(runId, stepId, attempt)

    fun toLedgerEntry(preparedAt: Long): ActionLedgerEntry {
        require(RAW_GENERATION_PATTERN.matches(serviceGeneration)) { "ledger_service_generation_invalid" }
        val key = identity.toOpaqueLedgerKey()
        return ActionLedgerEntry(
            runId = key.runKey,
            stepId = key.stepKey,
            attempt = attempt,
            state = ActionLedgerState.PREPARED,
            preparedAt = preparedAt.coerceAtLeast(0L),
            uiGeneration = uiGeneration,
            serviceGeneration = opaqueLedgerValue("service", serviceGeneration),
            resolverUsed = resolverUsed
        ).also(ActionLedgerEntry::validateLedgerEntry)
    }
}

data class DispatchReceipt(
    val outcome: DispatchOutcome,
    val dispatchedAt: Long,
    val errorCode: String = ""
) {
    constructor(accepted: Boolean, dispatchedAt: Long, errorCode: String = "") : this(
        if (accepted) DispatchOutcome.ACCEPTED else DispatchOutcome.REJECTED,
        dispatchedAt,
        errorCode
    )

    val accepted: Boolean
        get() = outcome == DispatchOutcome.ACCEPTED

    companion object {
        fun accepted(dispatchedAt: Long): DispatchReceipt =
            DispatchReceipt(DispatchOutcome.ACCEPTED, dispatchedAt)

        fun rejected(dispatchedAt: Long, errorCode: String = ActionLedgerErrors.DISPATCH_REJECTED): DispatchReceipt =
            DispatchReceipt(DispatchOutcome.REJECTED, dispatchedAt, errorCode)

        fun outcomeUnknown(
            dispatchedAt: Long,
            errorCode: String = AccessibilitySemanticDispatcher.ERROR_ACTION_OUTCOME_UNKNOWN
        ): DispatchReceipt = DispatchReceipt(DispatchOutcome.UNCERTAIN, dispatchedAt, errorCode)
    }
}

fun DispatchResult.toDispatchReceipt(): DispatchReceipt = DispatchReceipt(outcome, dispatchedAt, errorCode)

fun interface ActionDispatcher {
    fun dispatch(action: PreparedAction): DispatchReceipt
}

fun interface OutcomeVerifier {
    fun verify(action: PreparedAction, dispatchedAt: Long): VerificationResult
}

sealed interface VerificationResult {
    data object EffectVerified : VerificationResult
    data object NoEffectVerified : VerificationResult
    data class EffectVerifiedAt(val observed: GenerationSnapshot) : VerificationResult
    data class NoEffectVerifiedAt(val observed: GenerationSnapshot) : VerificationResult
    data class Unknown(val errorCode: String = ActionLedgerErrors.VERIFICATION_UNKNOWN) : VerificationResult
}

enum class ActionOutcomeState { VERIFIED, FAILED_NO_DISPATCH, FAILED_NO_EFFECT, UNCERTAIN }

data class ActionOutcome(
    val state: ActionOutcomeState,
    val errorCode: String,
    val entry: ActionLedgerEntry,
    val durable: Boolean = true,
    val preDispatchFailure: ClaimedPreDispatchFailure? = null,
    val dispatchInvoked: Boolean = entry.dispatchInvoked
)

class SingleDispatchExecutor(
    private val store: ActionLedgerStore,
    private val dispatcher: ActionDispatcher,
    private val verifier: OutcomeVerifier,
    private val clock: () -> Long = System::currentTimeMillis,
    private val generation: () -> GenerationSnapshot?,
    private val postDispatchGenerationPolicy: PostDispatchGenerationPolicy = ExactPostDispatchGenerationPolicy
) {
    fun execute(action: PreparedAction): ActionOutcome {
        val preparedAt = safeNow()
        val requested = action.toLedgerEntry(preparedAt)
        var noDispatchCode = ActionLedgerErrors.PREPARE_DURABILITY_FAILURE
        var dispatchOwned = false
        return try {
            val prepared = store.prepareForExecution(requested)
            if (prepared.state.terminal) return prepared.toOutcome()
            noDispatchCode = ActionLedgerErrors.CLAIM_DURABILITY_FAILURE
            when (val result = store.claimDispatch(prepared.key, monotonicTime(prepared)) { claim ->
                dispatchOwned = true
                executeClaimed(action, claim) { code -> noDispatchCode = code }
            }) {
                is DispatchClaimResult.Claimed -> result.value
                is DispatchClaimResult.Existing -> result.entry.toOutcome()
                is DispatchClaimResult.Reentrant -> reentrantOutcome(result.entry ?: prepared)
            }
        } catch (error: Throwable) {
            if (error.message?.startsWith("ledger_attempt_") == true) {
                noDispatchCode = ActionLedgerErrors.ATTEMPT_SEQUENCE_REJECTED
            }
            reconcileFailure(
                requested,
                noDispatchCode,
                if (dispatchOwned) ActionLedgerErrors.TERMINAL_DURABILITY_FAILURE
                else ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH
            )
        }
    }

    private fun executeClaimed(
        action: PreparedAction,
        claim: DispatchClaimScope,
        selectNoDispatchCode: (String) -> Unit
    ): ActionOutcome {
        val guardDecision = try {
            action.preDispatchGuard.check()
                ?: ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.RESULT_MISSING)
        } catch (_: Throwable) {
            ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.EXCEPTION)
        }
        if (guardDecision is ClaimedPreDispatchDecision.Reject) {
            selectNoDispatchCode(guardDecision.failure.code)
            return finish(
                claim,
                ActionLedgerState.FAILED_NO_DISPATCH,
                guardDecision.failure.code
            )
        }
        claim.markDispatchInvoked(monotonicTime(claim.entry))
        val receipt: DispatchReceipt? = try {
            dispatcher.dispatch(action)
        } catch (_: Throwable) {
            return finish(claim, ActionLedgerState.UNCERTAIN, ActionLedgerErrors.DISPATCH_EXCEPTION)
        }
        if (receipt == null) {
            return finish(claim, ActionLedgerState.UNCERTAIN, ActionLedgerErrors.CALLBACK_RESULT_MISSING)
        }
        if (receipt.dispatchedAt < 0L) {
            return finish(claim, ActionLedgerState.UNCERTAIN, AccessibilitySemanticDispatcher.ERROR_ACTION_OUTCOME_UNKNOWN)
        }
        return when (receipt.outcome) {
            DispatchOutcome.REJECTED -> finish(
                claim,
                ActionLedgerState.FAILED_NO_DISPATCH,
                dispatchError(receipt.errorCode)
            )
            DispatchOutcome.UNCERTAIN -> finish(
                claim,
                ActionLedgerState.UNCERTAIN,
                ActionLedgerErrors.ACTION_OUTCOME_UNKNOWN
            )
            DispatchOutcome.ACCEPTED -> verifyAccepted(
                action,
                claim,
                maxOf(receipt.dispatchedAt, claim.entry.dispatchedAt)
            )
        }
    }

    private fun verifyAccepted(
        action: PreparedAction,
        claim: DispatchClaimScope,
        dispatchedAt: Long
    ): ActionOutcome {
        preVerificationGenerationError(action)?.let {
            return finish(claim, ActionLedgerState.UNCERTAIN, it)
        }
        val verification: VerificationResult? = try {
            verifier.verify(action, dispatchedAt)
        } catch (_: Throwable) {
            return finish(claim, ActionLedgerState.UNCERTAIN, ActionLedgerErrors.VERIFIER_EXCEPTION)
        }
        if (verification == null) {
            return finish(claim, ActionLedgerState.UNCERTAIN, ActionLedgerErrors.CALLBACK_RESULT_MISSING)
        }
        postVerificationGenerationError(action, verification)?.let {
            return finish(claim, ActionLedgerState.UNCERTAIN, it)
        }
        return when (verification) {
            VerificationResult.EffectVerified -> finish(
                claim,
                ActionLedgerState.VERIFIED,
                ActionLedgerErrors.VERIFIED
            )
            VerificationResult.NoEffectVerified -> finish(
                claim,
                ActionLedgerState.FAILED_NO_EFFECT,
                ActionLedgerErrors.NO_EFFECT
            )
            is VerificationResult.EffectVerifiedAt -> finish(
                claim,
                ActionLedgerState.VERIFIED,
                ActionLedgerErrors.VERIFIED
            )
            is VerificationResult.NoEffectVerifiedAt -> finish(
                claim,
                ActionLedgerState.FAILED_NO_EFFECT,
                ActionLedgerErrors.NO_EFFECT
            )
            is VerificationResult.Unknown -> finish(
                claim,
                ActionLedgerState.UNCERTAIN,
                ActionLedgerErrors.VERIFICATION_UNKNOWN
            )
        }
    }

    private fun preVerificationGenerationError(action: PreparedAction): String? {
        val current = currentGeneration() ?: return ActionLedgerErrors.VERIFICATION_UNKNOWN
        if (current.serviceGeneration != action.serviceGeneration) {
            return ActionLedgerErrors.SERVICE_GENERATION_CHANGED
        }
        val accepted = try {
            postDispatchGenerationPolicy.accepts(action, current)
        } catch (_: Throwable) {
            return ActionLedgerErrors.VERIFICATION_UNKNOWN
        }
        return if (accepted) null else ActionLedgerErrors.UI_GENERATION_CHANGED
    }

    private fun postVerificationGenerationError(
        action: PreparedAction,
        verification: VerificationResult
    ): String? {
        val current = currentGeneration() ?: return ActionLedgerErrors.VERIFICATION_UNKNOWN
        return try {
            postDispatchGenerationPolicy.verificationError(action, verification, current)
        } catch (_: Throwable) {
            ActionLedgerErrors.VERIFICATION_UNKNOWN
        }
    }

    private fun currentGeneration(): GenerationSnapshot? = try {
        generation()
    } catch (_: Throwable) {
        null
    }

    private fun finish(
        claim: DispatchClaimScope,
        state: ActionLedgerState,
        errorCode: String
    ): ActionOutcome {
        return claim.finish(state, monotonicTime(claim.entry), persistentError(errorCode, state)).toOutcome()
    }

    private fun reconcileFailure(
        requested: ActionLedgerEntry,
        noDispatchCode: String,
        uncertainCode: String
    ): ActionOutcome = try {
        when (val resolution = store.reconcileAfterFailure(
            requested.key,
            safeNow(),
            noDispatchCode,
            uncertainCode
        )) {
            LedgerFailureResolution.Absent -> absentOutcome(requested, noDispatchCode)
            is LedgerFailureResolution.Reentrant -> reentrantOutcome(resolution.entry ?: requested)
            is LedgerFailureResolution.Entry -> when {
                resolution.entry.state.terminal -> resolution.entry.toOutcome()
                resolution.entry.state == ActionLedgerState.PREPARED ->
                    noDispatchOutcome(resolution.entry, noDispatchCode)
                else -> durabilityUnavailable(resolution.entry)
            }
        }
    } catch (_: Throwable) {
        try {
            when (val resolution = store.reconcileAfterOwnershipFailure(
                requested.key,
                safeNow(),
                noDispatchCode,
                uncertainCode
            )) {
                LedgerFailureResolution.Absent -> absentOutcome(requested, noDispatchCode)
                is LedgerFailureResolution.Reentrant ->
                    reentrantOutcome(resolution.entry ?: requested)
                is LedgerFailureResolution.Entry -> when {
                    resolution.entry.state.terminal -> resolution.entry.toOutcome()
                    resolution.entry.state == ActionLedgerState.PREPARED ->
                        noDispatchOutcome(resolution.entry, noDispatchCode)
                    else -> durabilityUnavailable(resolution.entry)
                }
            }
        } catch (_: Throwable) {
            durabilityUnavailable(requested)
        }
    }

    private fun absentOutcome(entry: ActionLedgerEntry, noDispatchCode: String): ActionOutcome =
        if (noDispatchCode == ActionLedgerErrors.ATTEMPT_SEQUENCE_REJECTED) {
            noDispatchOutcome(entry, noDispatchCode).copy(durable = false)
        } else {
            durabilityUnavailable(entry)
        }

    private fun noDispatchOutcome(entry: ActionLedgerEntry, errorCode: String) = ActionOutcome(
        ActionOutcomeState.FAILED_NO_DISPATCH,
        errorCode,
        entry
    )

    private fun reentrantOutcome(entry: ActionLedgerEntry): ActionOutcome = ActionOutcome(
        ActionOutcomeState.UNCERTAIN,
        ActionLedgerErrors.REENTRANT_EXECUTE,
        entry
    )

    private fun durabilityUnavailable(entry: ActionLedgerEntry): ActionOutcome = ActionOutcome(
        ActionOutcomeState.UNCERTAIN,
        ActionLedgerErrors.DURABILITY_UNAVAILABLE,
        entry,
        durable = false
    )

    private fun ActionLedgerEntry.toOutcome(): ActionOutcome = when (state) {
        ActionLedgerState.VERIFIED -> ActionOutcome(ActionOutcomeState.VERIFIED, errorCode, this)
        ActionLedgerState.FAILED_NO_DISPATCH -> ActionOutcome(
            ActionOutcomeState.FAILED_NO_DISPATCH,
            errorCode,
            this,
            preDispatchFailure = ClaimedPreDispatchFailure.fromCode(errorCode)
        )
        ActionLedgerState.FAILED_NO_EFFECT -> ActionOutcome(ActionOutcomeState.FAILED_NO_EFFECT, errorCode, this)
        ActionLedgerState.UNCERTAIN -> ActionOutcome(ActionOutcomeState.UNCERTAIN, errorCode, this)
        ActionLedgerState.PREPARED -> ActionOutcome(
            ActionOutcomeState.FAILED_NO_DISPATCH,
            ActionLedgerErrors.CLAIM_DURABILITY_FAILURE,
            this
        )
        ActionLedgerState.DISPATCHING -> ActionOutcome(
            ActionOutcomeState.UNCERTAIN,
            ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH,
            this
        )
    }

    private fun safeNow(): Long = runCatching { clock() }.getOrDefault(0L).coerceAtLeast(0L)

    private fun monotonicTime(entry: ActionLedgerEntry): Long =
        maxOf(safeNow(), entry.preparedAt, entry.dispatchedAt)

    private fun dispatchError(value: String): String = when (value) {
        AccessibilitySemanticDispatcher.ERROR_ACTION_CLICK_REJECTED -> value
        else -> ActionLedgerErrors.DISPATCH_REJECTED
    }

    private fun persistentError(value: String, state: ActionLedgerState): String =
        value.takeIf { it in ActionLedgerErrors.persistent } ?: defaultErrorFor(state)

    private fun defaultErrorFor(state: ActionLedgerState): String = when (state) {
        ActionLedgerState.VERIFIED -> ActionLedgerErrors.VERIFIED
        ActionLedgerState.FAILED_NO_DISPATCH -> ActionLedgerErrors.DISPATCH_REJECTED
        ActionLedgerState.FAILED_NO_EFFECT -> ActionLedgerErrors.NO_EFFECT
        ActionLedgerState.UNCERTAIN -> ActionLedgerErrors.VERIFICATION_UNKNOWN
        else -> ActionLedgerErrors.DURABILITY_UNAVAILABLE
    }
}

private val RAW_GENERATION_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
