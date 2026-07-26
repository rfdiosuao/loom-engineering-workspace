package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentTerminalCompletionPolicyTest {
    @Test
    fun successful_terminal_completion_remains_successful_and_compilable() {
        val decision = AgentTerminalCompletionPolicy.decide(
            successful = true,
            finalAnswer = "done",
            rounds = 2,
            tokens = 10
        )

        assertTrue(decision.result.success)
        assertTrue(decision.shouldCompile)
        assertEquals("done", decision.result.answer)
    }

    @Test
    fun cancellation_budget_and_loop_stop_are_unsuccessful_and_structured() {
        listOf("cancelled", "round budget reached", "loop stopped").forEach { message ->
            val decision = AgentTerminalCompletionPolicy.decide(
                successful = false,
                finalAnswer = message,
                rounds = 3,
                tokens = 20
            )
            val payload = AgentTerminalCompletionPolicy.failurePayload(decision.result, mode = "agent")

            assertFalse(decision.result.success)
            assertFalse(decision.shouldCompile)
            assertEquals("agent_execution_incomplete", payload["errorCode"].asString)
            assertEquals(message, payload["message"].asString)
            assertEquals("complete", payload["currentStep"].asString)
            assertEquals("agent", payload["mode"].asString)
            assertTrue(payload["retryable"].asBoolean)
        }
    }
}
