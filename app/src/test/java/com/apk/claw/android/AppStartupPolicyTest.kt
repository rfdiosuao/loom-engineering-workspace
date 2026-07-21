package com.apk.claw.android

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppStartupPolicyTest {
    @Test
    fun control_plane_starts_without_llm_config() {
        assertTrue(AppStartupPolicy.shouldStartControlPlane(llmConfigured = false))
    }

    @Test
    fun agent_and_channel_reconnect_still_require_llm_config() {
        assertFalse(AppStartupPolicy.shouldStartAgent(llmConfigured = false))
        assertTrue(AppStartupPolicy.shouldStartAgent(llmConfigured = true))
        assertFalse(AppStartupPolicy.shouldReconnectChannels(llmConfigured = false))
        assertTrue(AppStartupPolicy.shouldReconnectChannels(llmConfigured = true))
    }
}
