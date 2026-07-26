package com.apk.claw.android.workflow

enum class MatchDecision { MATCH, PROFILE_MISMATCH, NOT_ACTIVE }

data class ValidationResult(
    val profileId: String,
    val resetId: String,
    val success: Boolean,
    val coveredResolvers: Set<ResolverKind>,
    val allOutcomesVerified: Boolean,
    val usedStaleFrame: Boolean,
    val serviceRebound: Boolean,
    val retriedAfterDispatch: Boolean,
    val unresolvedWindows: Boolean = false,
    val templateRevision: Int = 0
)

class TemplatePromotionCoordinator(
    private val clock: () -> Long = System::currentTimeMillis,
    private val liveProfileProvider: () -> String = DeviceProfileProvider::current,
    private val profileVerifier: (String) -> Boolean = DeviceProfileProvider::isTrustedProfileId
) {
    fun recordValidation(template: WorkflowTemplate, result: ValidationResult): WorkflowTemplate {
        if (template.status !in VALIDATABLE_STATUSES) return template
        val profileId = template.boundProfileId()
        if (!hasTrustedLiveProfile(template, result.profileId)) return template
        if (result.templateRevision <= 0 || result.templateRevision != template.revision) return template

        val requiredResolvers = template.steps.flatMap { it.allowedResolvers }.toSet()
        val valid = result.success &&
            result.resetId.isNotBlank() &&
            result.allOutcomesVerified &&
            !result.usedStaleFrame &&
            !result.serviceRebound &&
            !result.retriedAfterDispatch &&
            !result.unresolvedWindows
        val baseState = if (template.status == TemplateStatus.DEGRADED) {
            ValidationState(
                profileId = profileId,
                failures = template.validationState.failures,
                validatedRevision = template.revision
            )
        } else {
            template.validationState.forRevision(template.revision, profileId)
        }
        val nextState = TemplateLifecyclePolicy.recordValidation(
            state = baseState,
            profileId = profileId,
            resetId = result.resetId.ifBlank { INVALID_RESET_ID },
            success = valid,
            covered = if (valid) result.coveredResolvers.intersect(requiredResolvers) else emptySet(),
            now = clock()
        )
        val nextStatus = if (TemplateLifecyclePolicy.canActivate(nextState, requiredResolvers)) {
            TemplateStatus.ACTIVE
        } else {
            TemplateStatus.VALIDATING
        }
        val nextSteps = template.steps.map { step ->
            step.copy(validatedResolvers = step.allowedResolvers.intersect(nextState.validatedResolvers))
        }
        return template.copy(
            status = nextStatus,
            steps = nextSteps,
            validationState = nextState,
            targetProfileId = template.targetProfileId.ifBlank { profileId },
            activatedAt = if (nextStatus == TemplateStatus.ACTIVE) clock() else template.activatedAt
        )
    }

    fun match(template: WorkflowTemplate, profileId: String): MatchDecision {
        if (template.status != TemplateStatus.ACTIVE ||
            template.validationState.validatedRevision != template.revision
        ) return MatchDecision.NOT_ACTIVE
        val boundProfile = template.boundProfileId()
        if (boundProfile.isBlank() || template.validationState.profileId != boundProfile) {
            return MatchDecision.NOT_ACTIVE
        }
        return if (profileId == boundProfile) MatchDecision.MATCH else MatchDecision.PROFILE_MISMATCH
    }

    fun recordRuntimeFailure(
        template: WorkflowTemplate,
        reportedProfileId: String,
        templateRevision: Int,
        errorCode: String
    ): WorkflowTemplate {
        if (template.status != TemplateStatus.ACTIVE || errorCode !in DEGRADING_ERRORS) return template
        if (templateRevision <= 0 || templateRevision != template.revision) return template
        if (!hasTrustedLiveProfile(template, reportedProfileId)) return template
        return template.copy(
            status = TemplateStatus.DEGRADED,
            degradedReason = errorCode,
            degradedAt = clock()
        )
    }

    internal fun hasTrustedLiveProfile(
        template: WorkflowTemplate,
        reportedProfileId: String
    ): Boolean {
        if (template.targetPackage.isBlank()) return false
        val boundProfileId = template.boundProfileId()
        if (!profileVerifier(boundProfileId) || !profileVerifier(reportedProfileId)) return false
        val liveProfileId = runCatching { liveProfileProvider() }.getOrDefault("")
        return profileVerifier(liveProfileId) &&
            liveProfileId == boundProfileId &&
            liveProfileId == reportedProfileId
    }

    private fun ValidationState.forRevision(revision: Int, profileId: String): ValidationState {
        if (validatedRevision == revision && this.profileId == profileId) return this
        return ValidationState(
            profileId = profileId,
            failures = failures,
            validatedRevision = revision
        )
    }

    private fun WorkflowTemplate.boundProfileId(): String =
        targetProfileId.ifBlank { validationState.profileId }

    companion object {
        private const val INVALID_RESET_ID = "reset-invalid"
        private val VALIDATABLE_STATUSES = setOf(
            TemplateStatus.DRAFT,
            TemplateStatus.VALIDATING,
            TemplateStatus.DEGRADED
        )
        private val DEGRADING_ERRORS = setOf(
            "structural_mismatch",
            "target_unresolved",
            "target_ambiguous",
            "resolver_disagreement",
            "freshness_violation",
            "stale_resolution_evidence",
            "visual_evidence_not_fresh",
            "service_generation_changed",
            "app_version_mismatch"
        )
    }
}
