package com.apk.claw.android.workflow

import com.apk.claw.android.rpa.RpaWorkflowRunner

data class ValidationReadiness(
    val taskQueueIdle: Boolean,
    val deviceUnlocked: Boolean,
    val accessibilityHealthy: Boolean,
    val expectedPackageRestorable: Boolean,
    val resetRestorable: Boolean,
    val profileId: String
)

data class ValidationResetResult(
    val resetId: String,
    val restored: Boolean
)

enum class ValidationSkipReason {
    TEMPLATE_NOT_VALIDATABLE,
    TASK_QUEUE_BUSY,
    RPA_BUSY,
    DEVICE_LOCKED,
    ACCESSIBILITY_UNHEALTHY,
    PACKAGE_NOT_RESTORABLE,
    RESET_NOT_RESTORABLE,
    RISK_NOT_ALLOWED,
    PROFILE_MISMATCH,
    VALIDATION_ALREADY_ACTIVE
}

sealed interface ValidationScheduleResult {
    data class Skipped(val reason: ValidationSkipReason) : ValidationScheduleResult

    data class Completed(
        val template: WorkflowTemplate,
        val resetSucceeded: Boolean,
        val stepsExecuted: Boolean
    ) : ValidationScheduleResult
}

/**
 * Runs one validation attempt while holding the same exclusive lease as normal RPA execution.
 * The [execute] callback must invoke the validation engine directly and must not re-enter
 * [RpaWorkflowRunner.start], which is intentionally busy for the lifetime of the callback.
 */
class TemplateValidationScheduler(
    private val readiness: (WorkflowTemplate) -> ValidationReadiness,
    private val reset: (WorkflowTemplate) -> ValidationResetResult,
    private val execute: (WorkflowTemplate, String) -> ValidationResult,
    private val persist: (WorkflowTemplate) -> Unit,
    private val coordinator: TemplatePromotionCoordinator = TemplatePromotionCoordinator()
) {
    fun enqueue(template: WorkflowTemplate): ValidationScheduleResult {
        val initialState = readiness(template)
        preflight(template, initialState)?.let { return ValidationScheduleResult.Skipped(it) }
        val lease = RpaWorkflowRunner.tryAcquireValidationLease()
            ?: return ValidationScheduleResult.Skipped(ValidationSkipReason.RPA_BUSY)

        return try {
            val state = readiness(template)
            preflight(template, state)?.let { return ValidationScheduleResult.Skipped(it) }
            val resetResult = runCatching { reset(template) }
                .getOrElse { ValidationResetResult(RESET_FAILURE_ID, restored = false) }
            if (!resetResult.restored || resetResult.resetId.isBlank()) {
                completeFailure(template, state.profileId, resetResult.resetId, stepsExecuted = false)
            } else {
                val result = runCatching { execute(template, resetResult.resetId) }
                    .getOrElse {
                        failedResult(template, state.profileId, resetResult.resetId)
                    }
                val consistentResult = if (result.resetId == resetResult.resetId) {
                    result
                } else {
                    failedResult(template, state.profileId, resetResult.resetId)
                }
                val updated = coordinator.recordValidation(template, consistentResult)
                if (updated != template) persist(updated)
                ValidationScheduleResult.Completed(
                    template = updated,
                    resetSucceeded = true,
                    stepsExecuted = true
                )
            }
        } finally {
            lease.close()
        }
    }

    private fun preflight(
        template: WorkflowTemplate,
        state: ValidationReadiness
    ): ValidationSkipReason? = when {
        template.status !in VALIDATABLE_STATUSES -> ValidationSkipReason.TEMPLATE_NOT_VALIDATABLE
        !state.taskQueueIdle -> ValidationSkipReason.TASK_QUEUE_BUSY
        !state.deviceUnlocked -> ValidationSkipReason.DEVICE_LOCKED
        !state.accessibilityHealthy -> ValidationSkipReason.ACCESSIBILITY_UNHEALTHY
        !state.expectedPackageRestorable -> ValidationSkipReason.PACKAGE_NOT_RESTORABLE
        !state.resetRestorable -> ValidationSkipReason.RESET_NOT_RESTORABLE
        template.riskLevel !in AUTO_VALIDATION_RISKS -> ValidationSkipReason.RISK_NOT_ALLOWED
        !coordinator.hasTrustedLiveProfile(template, state.profileId) ->
            ValidationSkipReason.PROFILE_MISMATCH
        else -> null
    }

    private fun completeFailure(
        template: WorkflowTemplate,
        profileId: String,
        resetId: String,
        stepsExecuted: Boolean
    ): ValidationScheduleResult.Completed {
        val updated = coordinator.recordValidation(
            template,
            failedResult(template, profileId, resetId.ifBlank { RESET_FAILURE_ID })
        )
        if (updated != template) persist(updated)
        return ValidationScheduleResult.Completed(
            template = updated,
            resetSucceeded = false,
            stepsExecuted = stepsExecuted
        )
    }

    private fun failedResult(
        template: WorkflowTemplate,
        profileId: String,
        resetId: String
    ) = ValidationResult(
        profileId = profileId,
        resetId = resetId,
        success = false,
        coveredResolvers = emptySet(),
        allOutcomesVerified = false,
        usedStaleFrame = false,
        serviceRebound = false,
        retriedAfterDispatch = false,
        unresolvedWindows = false,
        templateRevision = template.revision
    )

    companion object {
        private const val RESET_FAILURE_ID = "reset-failure"
        private val VALIDATABLE_STATUSES = setOf(
            TemplateStatus.DRAFT,
            TemplateStatus.VALIDATING,
            TemplateStatus.DEGRADED
        )
        private val AUTO_VALIDATION_RISKS = setOf(
            TemplateRiskLevel.READ_ONLY,
            TemplateRiskLevel.REVERSIBLE
        )
    }
}
