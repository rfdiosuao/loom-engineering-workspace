package com.apk.claw.android.agent

enum class AgentToolPolicy(val wireName: String) {
    OBSERVE_ONLY("observe_only"),
    SAFE_ACTION("safe_action"),
    FULL_ACCESS("full_access");

    companion object {
        fun fromWireName(value: String?): AgentToolPolicy {
            return when (value?.trim()?.lowercase()) {
                "observe_only", "readonly", "read_only", "read-only" -> OBSERVE_ONLY
                "safe_action", "safe-actions", "safe_action_only", "safe" -> SAFE_ACTION
                "full_access", "full-access", "full", "unrestricted" -> FULL_ACCESS
                else -> FULL_ACCESS
            }
        }
    }
}

data class AgentRunOptions(
    val readOnly: Boolean = false,
    val toolPolicy: AgentToolPolicy = AgentToolPolicy.FULL_ACCESS,
    val maxRounds: Int? = null
)

interface AgentService {
    fun initialize(config: AgentConfig)
    fun updateConfig(config: AgentConfig)
    fun executeTask(userPrompt: String, callback: AgentCallback, options: AgentRunOptions = AgentRunOptions())
    fun cancel()
    fun shutdown()
    fun isRunning(): Boolean
}
