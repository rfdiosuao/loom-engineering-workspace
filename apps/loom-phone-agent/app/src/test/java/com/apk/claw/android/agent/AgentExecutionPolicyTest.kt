package com.apk.claw.android.agent

import org.junit.Assert.assertEquals
import org.junit.Test

class AgentExecutionPolicyTest {
    @Test
    fun resolves_default_round_budgets_by_mode() {
        assertEquals(1, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.OBSERVE))
        assertEquals(60, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.SAFE))
        assertEquals(60, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.FULL))
    }

    @Test
    fun clamps_explicit_round_budgets_to_mode_caps() {
        assertEquals(3, AgentExecutionPolicy.resolveMaxRounds(99, AgentExecutionMode.OBSERVE))
        assertEquals(120, AgentExecutionPolicy.resolveMaxRounds(999, AgentExecutionMode.SAFE))
        assertEquals(120, AgentExecutionPolicy.resolveMaxRounds(999, AgentExecutionMode.FULL))
    }

    @Test
    fun honors_explicit_round_budgets_up_to_absolute_cap() {
        assertEquals(120, AgentExecutionPolicy.absoluteMaxRounds())
        assertEquals(120, AgentExecutionPolicy.resolveMaxRounds(120, AgentExecutionMode.SAFE))
        assertEquals(120, AgentExecutionPolicy.resolveMaxRounds(120, AgentExecutionMode.FULL))
    }

    @Test
    fun agent_config_defaults_match_absolute_round_cap() {
        assertEquals(120, AgentConfig(apiKey = "key", baseUrl = "https://example.com").maxIterations)
        assertEquals(
            120,
            AgentConfig.Builder()
                .apiKey("key")
                .baseUrl("https://example.com")
                .build()
                .maxIterations
        )
    }

    @Test
    fun derives_mode_from_request_and_tool_policy() {
        assertEquals(AgentExecutionMode.OBSERVE, AgentExecutionPolicy.resolveMode("observe", AgentToolPolicy.FULL_ACCESS, false))
        assertEquals(AgentExecutionMode.SAFE, AgentExecutionPolicy.resolveMode("safe", AgentToolPolicy.FULL_ACCESS, false))
        assertEquals(AgentExecutionMode.FULL, AgentExecutionPolicy.resolveMode("full", AgentToolPolicy.SAFE_ACTION, false))
        assertEquals(AgentExecutionMode.OBSERVE, AgentExecutionPolicy.resolveMode(null, AgentToolPolicy.OBSERVE_ONLY, true))
        assertEquals(AgentExecutionMode.SAFE, AgentExecutionPolicy.resolveMode(null, AgentToolPolicy.SAFE_ACTION, false))
        assertEquals(AgentExecutionMode.FULL, AgentExecutionPolicy.resolveMode(null, AgentToolPolicy.FULL_ACCESS, false))
    }
}
