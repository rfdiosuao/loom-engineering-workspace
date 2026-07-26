package com.apk.claw.android.workflow

enum class TemplateStatus { DRAFT, VALIDATING, ACTIVE, DEGRADED, DISABLED }

enum class TemplateRiskLevel { READ_ONLY, REVERSIBLE, SIDE_EFFECT, DANGEROUS, UNKNOWN }

enum class ResolverPolicy { DIRECT, TREE_PREFERRED, VISION_REQUIRED, DUAL_CONFIRM }

enum class ResolverKind {
    DIRECT,
    EPHEMERAL_REF,
    RESOURCE_ID,
    CONTENT_DESCRIPTION,
    TEXT_CLASS,
    STRUCTURAL,
    VISUAL_ANCHOR,
    NORMALIZED_COORDINATE
}

data class ValidationState(
    val target: Int = 3,
    val profileId: String = "",
    val consecutiveSuccesses: Int = 0,
    val failures: Int = 0,
    val validatedResolvers: Set<ResolverKind> = emptySet(),
    val validatedResetIds: Set<String> = emptySet(),
    val lastValidationAt: Long = 0L,
    val validatedRevision: Int = 1
)

object TemplateLifecyclePolicy {
    const val REQUIRED_CONSECUTIVE_SUCCESSES = 3

    fun recordValidation(
        state: ValidationState,
        profileId: String,
        resetId: String,
        success: Boolean,
        covered: Set<ResolverKind>,
        now: Long = System.currentTimeMillis()
    ): ValidationState {
        require(profileId.isNotBlank())
        require(resetId.isNotBlank())
        val sameProfile = state.profileId.isBlank() || state.profileId == profileId
        if (!sameProfile) {
            return ValidationState(
                profileId = profileId,
                failures = if (success) 0 else 1,
                consecutiveSuccesses = if (success) 1 else 0,
                validatedResolvers = if (success) covered else emptySet(),
                validatedResetIds = if (success) setOf(resetId) else emptySet(),
                lastValidationAt = now,
                validatedRevision = state.validatedRevision
            )
        }
        return state.copy(
            profileId = profileId,
            target = REQUIRED_CONSECUTIVE_SUCCESSES,
            consecutiveSuccesses = if (success) {
                (state.consecutiveSuccesses + 1).coerceAtMost(REQUIRED_CONSECUTIVE_SUCCESSES)
            } else {
                0
            },
            failures = state.failures + if (success) 0 else 1,
            validatedResolvers = if (success) state.validatedResolvers + covered else emptySet(),
            validatedResetIds = if (success) state.validatedResetIds + resetId else emptySet(),
            lastValidationAt = now
        )
    }

    fun canActivate(state: ValidationState, required: Set<ResolverKind>): Boolean =
        state.consecutiveSuccesses >= REQUIRED_CONSECUTIVE_SUCCESSES &&
            state.validatedResetIds.size >= 2 &&
            state.validatedResolvers.containsAll(required)

    fun matchesProfile(state: ValidationState, profileId: String): Boolean = state.profileId == profileId
}
