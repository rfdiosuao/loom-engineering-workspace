package com.apk.claw.android.agent

import org.junit.Assert.assertEquals
import org.junit.Test

class AgentExecutionPolicyTest {
    @Test
    fun resolves_low_default_round_budgets_by_mode() {
        assertEquals(1, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.OBSERVE))
        assertEquals(12, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.SAFE))
        assertEquals(30, AgentExecutionPolicy.resolveMaxRounds(null, AgentExecutionMode.FULL))
    }

    @Test
    fun clamps_explicit_round_budgets_to_mode_caps() {
        assertEquals(3, AgentExecutionPolicy.resolveMaxRounds(99, AgentExecutionMode.OBSERVE))
        assertEquals(12, AgentExecutionPolicy.resolveMaxRounds(99, AgentExecutionMode.SAFE))
        assertEquals(30, AgentExecutionPolicy.resolveMaxRounds(99, AgentExecutionMode.FULL))
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
