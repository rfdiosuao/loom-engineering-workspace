package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import java.security.MessageDigest

enum class ActionLedgerState {
    PREPARED,
    DISPATCHING,
    VERIFIED,
    FAILED_NO_DISPATCH,
    FAILED_NO_EFFECT,
    UNCERTAIN;

    val terminal: Boolean
        get() = this == VERIFIED || this == FAILED_NO_DISPATCH ||
            this == FAILED_NO_EFFECT || this == UNCERTAIN
}

data class ActionIdentity(
    val runId: String,
    val stepId: String,
    val attempt: Int
)

internal data class OpaqueLedgerKey(
    val runKey: String,
    val stepKey: String,
    val attempt: Int
)

data class ActionLedgerEntry(
    val runId: String,
    val stepId: String,
    val attempt: Int,
    val state: ActionLedgerState,
    val preparedAt: Long,
    val dispatchedAt: Long = 0L,
    val dispatchInvoked: Boolean = false,
    val finishedAt: Long = 0L,
    val uiGeneration: Long,
    val serviceGeneration: String,
    val resolverUsed: ResolverKind,
    val errorCode: String = ""
) {
    internal val key: OpaqueLedgerKey
        get() = OpaqueLedgerKey(runId, stepId, attempt)
}

enum class ActionLedgerTransition { UPDATED, UNCHANGED, EXPECTATION_MISMATCH }

data class ActionLedgerTransitionResult(
    val status: ActionLedgerTransition,
    val entry: ActionLedgerEntry
)

data class ActionLedgerPruneResult(
    val retained: List<ActionLedgerEntry>,
    val deleted: List<ActionLedgerEntry>,
    val bytesBefore: Long,
    val bytesAfter: Long,
    val capMet: Boolean,
    val reason: String = "",
    val quarantineReasons: Set<String> = emptySet()
)

object ActionLedgerErrors {
    const val VERIFIED = "verified"
    const val NO_EFFECT = "no_effect"
    const val DISPATCH_REJECTED = "dispatch_rejected"
    const val DISPATCH_EXCEPTION = "dispatcher_exception"
    const val VERIFIER_EXCEPTION = "verifier_exception"
    const val VERIFICATION_UNKNOWN = "verification_unknown"
    const val PROCESS_DEATH_DURING_DISPATCH = "process_death_during_dispatch"
    const val SERVICE_GENERATION_CHANGED = "service_generation_changed"
    const val PREPARE_DURABILITY_FAILURE = "ledger_prepare_durability_failure"
    const val CLAIM_DURABILITY_FAILURE = "ledger_claim_durability_failure"
    const val TERMINAL_DURABILITY_FAILURE = "ledger_terminal_durability_failure"
    const val DURABILITY_UNAVAILABLE = "ledger_durability_unavailable"
    const val CALLBACK_RESULT_MISSING = "callback_result_missing"
    const val UI_GENERATION_CHANGED = "ui_generation_changed"
    const val ATTEMPT_SEQUENCE_REJECTED = "attempt_sequence_rejected"
    const val REENTRANT_EXECUTE = "reentrant_execute"
    const val ACTION_OUTCOME_UNKNOWN = "action_outcome_unknown"
    const val PRE_DISPATCH_CANCELLED = "pre_dispatch_cancelled"
    const val PRE_DISPATCH_DEADLINE_EXCEEDED = "pre_dispatch_deadline_exceeded"
    const val PRE_DISPATCH_GENERATION_CHANGED = "pre_dispatch_generation_changed"
    const val PRE_DISPATCH_GUARD_RESULT_MISSING = "pre_dispatch_guard_result_missing"
    const val PRE_DISPATCH_GUARD_EXCEPTION = "pre_dispatch_guard_exception"

    internal val persistent = setOf(
        VERIFIED,
        NO_EFFECT,
        DISPATCH_REJECTED,
        DISPATCH_EXCEPTION,
        VERIFIER_EXCEPTION,
        VERIFICATION_UNKNOWN,
        PROCESS_DEATH_DURING_DISPATCH,
        SERVICE_GENERATION_CHANGED,
        PREPARE_DURABILITY_FAILURE,
        CLAIM_DURABILITY_FAILURE,
        TERMINAL_DURABILITY_FAILURE,
        DURABILITY_UNAVAILABLE,
        CALLBACK_RESULT_MISSING,
        UI_GENERATION_CHANGED,
        ATTEMPT_SEQUENCE_REJECTED,
        REENTRANT_EXECUTE,
        ACTION_OUTCOME_UNKNOWN,
        PRE_DISPATCH_CANCELLED,
        PRE_DISPATCH_DEADLINE_EXCEEDED,
        PRE_DISPATCH_GENERATION_CHANGED,
        PRE_DISPATCH_GUARD_RESULT_MISSING,
        PRE_DISPATCH_GUARD_EXCEPTION,
        AccessibilitySemanticDispatcher.ERROR_ACTION_CLICK_REJECTED
    )
}

internal fun ActionIdentity.validateLedgerIdentity() {
    require(LEDGER_ID_PATTERN.matches(runId) && runId != "." && runId != "..") { "ledger_run_id_invalid" }
    require(LEDGER_ID_PATTERN.matches(stepId) && stepId != "." && stepId != "..") { "ledger_step_id_invalid" }
    require(attempt in 1..MAX_LEDGER_ATTEMPT) { "ledger_attempt_invalid" }
}

internal fun OpaqueLedgerKey.validateLedgerKey() {
    require(OPAQUE_KEY_PATTERN.matches(runKey)) { "ledger_run_key_invalid" }
    require(OPAQUE_KEY_PATTERN.matches(stepKey)) { "ledger_step_key_invalid" }
    require(attempt in 1..MAX_LEDGER_ATTEMPT) { "ledger_attempt_invalid" }
}

internal fun ActionLedgerEntry.validateLedgerEntry() {
    require(OPAQUE_KEY_PATTERN.matches(runId)) { "ledger_run_key_invalid" }
    require(OPAQUE_KEY_PATTERN.matches(stepId)) { "ledger_step_key_invalid" }
    require(attempt in 1..MAX_LEDGER_ATTEMPT) { "ledger_attempt_invalid" }
    require(preparedAt >= 0L) { "ledger_prepared_at_invalid" }
    require(dispatchedAt >= 0L) { "ledger_dispatched_at_invalid" }
    require(finishedAt >= 0L) { "ledger_finished_at_invalid" }
    require(uiGeneration >= 0L) { "ledger_ui_generation_invalid" }
    require(OPAQUE_KEY_PATTERN.matches(serviceGeneration)) { "ledger_service_generation_invalid" }
    require(errorCode.isEmpty() || errorCode in ActionLedgerErrors.persistent) { "ledger_error_code_invalid" }
    when (state) {
        ActionLedgerState.PREPARED -> require(
            dispatchedAt == 0L && !dispatchInvoked && finishedAt == 0L && errorCode.isEmpty()
        ) {
            "ledger_prepared_fields_invalid"
        }
        ActionLedgerState.DISPATCHING -> require(dispatchedAt >= preparedAt && finishedAt == 0L && errorCode.isEmpty()) {
            "ledger_dispatching_fields_invalid"
        }
        else -> {
            require(finishedAt >= preparedAt && finishedAt >= dispatchedAt) { "ledger_terminal_time_invalid" }
            require(errorCode.isNotEmpty()) { "ledger_terminal_error_code_required" }
        }
    }
}

internal fun ActionLedgerEntry.samePreparedMetadata(other: ActionLedgerEntry): Boolean =
    key == other.key &&
        uiGeneration == other.uiGeneration &&
        serviceGeneration == other.serviceGeneration &&
        resolverUsed == other.resolverUsed

internal fun isAllowedLedgerTransition(from: ActionLedgerState, to: ActionLedgerState): Boolean = when (from) {
    ActionLedgerState.PREPARED -> to == ActionLedgerState.DISPATCHING || to == ActionLedgerState.FAILED_NO_DISPATCH
    ActionLedgerState.DISPATCHING -> to.terminal
    else -> false
}

private const val MAX_LEDGER_ATTEMPT = 1_000_000
private val LEDGER_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
internal val OPAQUE_KEY_PATTERN = Regex("^[0-9a-f]{64}$")

internal fun ActionIdentity.toOpaqueLedgerKey(): OpaqueLedgerKey {
    validateLedgerIdentity()
    return OpaqueLedgerKey(
        runKey = opaqueLedgerValue("run", runId),
        stepKey = opaqueLedgerValue("step", "$runId\u0000$stepId"),
        attempt = attempt
    )
}

internal fun opaqueLedgerValue(domain: String, value: String): String {
    val digest = MessageDigest.getInstance("SHA-256")
        .digest("$domain\u0000$value".toByteArray(Charsets.UTF_8))
    val result = CharArray(digest.size * 2)
    for (index in digest.indices) {
        val byte = digest[index].toInt() and 0xff
        result[index * 2] = HEX_DIGITS[byte ushr 4]
        result[index * 2 + 1] = HEX_DIGITS[byte and 0x0f]
    }
    return String(result)
}

internal fun OpaqueLedgerKey.claimShardName(): String {
    validateLedgerKey()
    val digest = opaqueLedgerValue("claim-shard", "$runKey:$stepKey:$attempt")
    val shard = digest.substring(0, 2).toInt(16) % CLAIM_SHARD_COUNT
    return "claim-shard-${shard.toString().padStart(2, '0')}.lock"
}

internal const val CLAIM_SHARD_COUNT = 64

private val HEX_DIGITS = "0123456789abcdef".toCharArray()
