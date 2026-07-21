package com.apk.claw.android.agent

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentLoopEarlyStopPolicyTest {
    @Test
    fun observe_mode_stops_on_first_repeated_no_progress_signal() {
        assertTrue(AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount = 1, toolPolicy = AgentToolPolicy.OBSERVE_ONLY))
    }

    @Test
    fun safe_and_full_modes_get_one_replan_signal_before_stopping() {
        assertFalse(AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount = 1, toolPolicy = AgentToolPolicy.SAFE_ACTION))
        assertFalse(AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount = 1, toolPolicy = AgentToolPolicy.FULL_ACCESS))
        assertTrue(AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount = 2, toolPolicy = AgentToolPolicy.SAFE_ACTION))
        assertTrue(AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount = 2, toolPolicy = AgentToolPolicy.FULL_ACCESS))
    }
}
