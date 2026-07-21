package com.apk.claw.android.agent

object ActionFastTransitionPolicy {
    data class StepResult(
        val currentStep: String,
        val retryable: Boolean
    )

    fun requiresStablePostObserve(action: String): Boolean {
        return action == "home" || action == "back"
    }

    fun currentStepAfterAction(
        action: String,
        actionSucceeded: Boolean,
        transitionStable: Boolean
    ): StepResult {
        if (!actionSucceeded) return StepResult("failed", retryable = false)
        if (requiresStablePostObserve(action) && !transitionStable) {
            return StepResult("transition_pending", retryable = true)
        }
        return StepResult("complete", retryable = false)
    }
}
