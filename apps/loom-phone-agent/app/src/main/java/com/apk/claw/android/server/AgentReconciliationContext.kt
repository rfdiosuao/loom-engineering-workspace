package com.apk.claw.android.server

import com.apk.claw.android.rpa.AgentHandoffContext

data class AgentReconciliationInstructions(
    val prompt: String,
    val allowReplayFailedStep: Boolean
)

object AgentReconciliationContextBuilder {
    fun build(originalGoal: String, handoff: AgentHandoffContext): AgentReconciliationInstructions {
        @Suppress("UNUSED_VARIABLE")
        val goalRetainedByCaller = originalGoal
        val completed = handoff.completedSteps.joinToString(separator = "; ") { step ->
            "#${step.stepIndex}:${step.action}:${step.resolverUsed}:${step.outcomeState}"
        }.ifBlank { "none" }
        val failed = handoff.failedStep
        val uncertain = handoff.replayForbiddenUntilProof || failed.outcomeState == "uncertain"
        return AgentReconciliationInstructions(
            prompt = buildString {
                append("[Hybrid reconciliation]\n")
                append("Template: ").append(handoff.templateId).append(" revision ")
                    .append(handoff.templateRevision.coerceAtLeast(1)).append('\n')
                append("Completed verified steps: ").append(completed).append('\n')
                append("Failed step: #").append(failed.stepIndex).append(':').append(failed.action)
                    .append(" error=").append(failed.errorCode)
                    .append(" outcome=").append(failed.outcomeState).append('\n')
                if (uncertain) {
                    append("Outcome is UNCERTAIN. Reconcile by observation first. ")
                    append("Do not repeat any action until the old postcondition is proven absent.")
                }
            },
            allowReplayFailedStep = !uncertain
        )
    }
}
