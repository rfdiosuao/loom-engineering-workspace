package com.apk.claw.android.rpa

fun interface PostDispatchGenerationPolicy {
    fun accepts(action: PreparedAction, current: GenerationSnapshot): Boolean

    fun verificationError(
        action: PreparedAction,
        verification: VerificationResult,
        current: GenerationSnapshot
    ): String? = ExactPostDispatchGenerationPolicy.verificationError(action, verification, current)
}

internal object ExactPostDispatchGenerationPolicy : PostDispatchGenerationPolicy {
    override fun accepts(action: PreparedAction, current: GenerationSnapshot): Boolean =
        current.uiGeneration == action.uiGeneration &&
            current.serviceGeneration == action.serviceGeneration

    override fun verificationError(
        action: PreparedAction,
        verification: VerificationResult,
        current: GenerationSnapshot
    ): String? {
        val observed = verification.observedSnapshot()
        return if (observed == null) exactGenerationError(action, current)
        else exactStampedGenerationError(action, observed, current)
    }
}

internal object ProductionPostDispatchGenerationPolicy : PostDispatchGenerationPolicy {
    override fun accepts(action: PreparedAction, current: GenerationSnapshot): Boolean =
        current.serviceGeneration == action.serviceGeneration &&
            current.uiGeneration >= action.uiGeneration

    override fun verificationError(
        action: PreparedAction,
        verification: VerificationResult,
        current: GenerationSnapshot
    ): String? {
        val observed = verification.observedSnapshot()
            ?: return ActionLedgerErrors.VERIFICATION_UNKNOWN
        return stampedGenerationError(action, observed, current)
    }
}

private fun VerificationResult.observedSnapshot(): GenerationSnapshot? = when (this) {
    is VerificationResult.EffectVerifiedAt -> observed
    is VerificationResult.NoEffectVerifiedAt -> observed
    VerificationResult.EffectVerified,
    VerificationResult.NoEffectVerified,
    is VerificationResult.Unknown -> null
}

private fun exactStampedGenerationError(
    action: PreparedAction,
    observed: GenerationSnapshot,
    current: GenerationSnapshot
): String? {
    if (observed.serviceGeneration != action.serviceGeneration ||
        current.serviceGeneration != action.serviceGeneration
    ) return ActionLedgerErrors.SERVICE_GENERATION_CHANGED
    if (observed.uiGeneration != action.uiGeneration || current.uiGeneration != action.uiGeneration) {
        return ActionLedgerErrors.UI_GENERATION_CHANGED
    }
    return null
}

private fun stampedGenerationError(
    action: PreparedAction,
    observed: GenerationSnapshot,
    current: GenerationSnapshot
): String? {
    if (observed.serviceGeneration != action.serviceGeneration ||
        current.serviceGeneration != observed.serviceGeneration
    ) return ActionLedgerErrors.SERVICE_GENERATION_CHANGED
    if (observed.uiGeneration < action.uiGeneration || current.uiGeneration != observed.uiGeneration) {
        return ActionLedgerErrors.UI_GENERATION_CHANGED
    }
    return null
}

private fun exactGenerationError(
    action: PreparedAction,
    current: GenerationSnapshot
): String? = when {
    current.serviceGeneration != action.serviceGeneration ->
        ActionLedgerErrors.SERVICE_GENERATION_CHANGED
    current.uiGeneration != action.uiGeneration -> ActionLedgerErrors.UI_GENERATION_CHANGED
    else -> null
}
