package com.apk.claw.android.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KeepAliveRecoveryPolicyTest {
    @Test
    fun stopped_foreground_service_should_be_restarted() {
        assertTrue(KeepAliveRecoveryPolicy.shouldStartForegroundService(foregroundServiceRunning = false))
        assertFalse(KeepAliveRecoveryPolicy.shouldStartForegroundService(foregroundServiceRunning = true))
    }

    @Test
    fun enabled_dead_config_server_should_be_healed_even_without_llm_config() {
        assertTrue(
            KeepAliveRecoveryPolicy.shouldHealConfigServer(
                configServerEnabled = true,
                llmConfigured = false,
                configServerRunning = false
            )
        )
    }

    @Test
    fun running_or_disabled_config_server_should_not_be_healed() {
        assertFalse(
            KeepAliveRecoveryPolicy.shouldHealConfigServer(
                configServerEnabled = true,
                llmConfigured = true,
                configServerRunning = true
            )
        )
        assertFalse(
            KeepAliveRecoveryPolicy.shouldHealConfigServer(
                configServerEnabled = false,
                llmConfigured = true,
                configServerRunning = false
            )
        )
    }
}
