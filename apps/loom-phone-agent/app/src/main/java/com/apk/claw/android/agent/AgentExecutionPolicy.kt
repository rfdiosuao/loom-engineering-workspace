package com.apk.claw.android.agent

enum class AgentExecutionMode(val wireName: String) {
    OBSERVE("observe"),
    SAFE("safe"),
    FULL("full");
}

object AgentExecutionPolicy {
    private val defaultRounds = mapOf(
        AgentExecutionMode.OBSERVE to 1,
        AgentExecutionMode.SAFE to 12,
        AgentExecutionMode.FULL to 30
    )

    private val roundCaps = mapOf(
        AgentExecutionMode.OBSERVE to 3,
        AgentExecutionMode.SAFE to 12,
        AgentExecutionMode.FULL to 30
    )

    fun resolveMode(
        requestedMode: String?,
        toolPolicy: AgentToolPolicy,
        readOnly: Boolean
    ): AgentExecutionMode {
        val normalized = requestedMode?.trim()?.lowercase()
        return when (normalized) {
            "observe", "read", "readonly", "read_only", "observe_only" -> AgentExecutionMode.OBSERVE
            "safe", "safe_action", "safe-actions", "confirm" -> AgentExecutionMode.SAFE
            "full", "full_access", "full-access", "deep", "auto" -> AgentExecutionMode.FULL
            else -> when {
                readOnly || toolPolicy == AgentToolPolicy.OBSERVE_ONLY -> AgentExecutionMode.OBSERVE
                toolPolicy == AgentToolPolicy.SAFE_ACTION -> AgentExecutionMode.SAFE
                else -> AgentExecutionMode.FULL
            }
        }
    }

    fun defaultMaxRounds(mode: AgentExecutionMode): Int = defaultRounds[mode] ?: 30

    fun maxRoundCap(mode: AgentExecutionMode): Int = roundCaps[mode] ?: 30

    fun resolveMaxRounds(requestedMaxRounds: Int?, mode: AgentExecutionMode): Int {
        val requested = requestedMaxRounds ?: defaultMaxRounds(mode)
        return requested.coerceIn(1, maxRoundCap(mode))
    }
}
