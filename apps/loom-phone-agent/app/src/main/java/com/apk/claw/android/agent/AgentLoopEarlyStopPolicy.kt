package com.apk.claw.android.agent

object AgentLoopEarlyStopPolicy {
    fun shouldStop(stuckSignalCount: Int, toolPolicy: AgentToolPolicy): Boolean {
        val threshold = if (toolPolicy == AgentToolPolicy.OBSERVE_ONLY) 1 else 2
        return stuckSignalCount >= threshold
    }

    fun completionMessage(lastPartialSummary: String): String {
        val partial = lastPartialSummary.takeIf { it.isNotBlank() }?.let {
            "\n\nPartial result:\n${it.take(400)}"
        }.orEmpty()
        return "Stopped early because the Agent repeated the same tool call without useful screen progress.$partial"
    }
}
