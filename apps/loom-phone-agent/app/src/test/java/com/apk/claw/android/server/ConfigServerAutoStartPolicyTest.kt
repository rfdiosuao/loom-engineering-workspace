package com.apk.claw.android.server

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigServerAutoStartPolicyTest {
    @Test
    fun enabled_config_server_should_auto_start_even_when_llm_is_not_configured() {
        assertTrue(
            ConfigServerAutoStartPolicy.shouldAutoStart(
                configServerEnabled = true,
                llmConfigured = false
            )
        )
    }

    @Test
    fun disabled_config_server_should_not_auto_start() {
        assertFalse(
            ConfigServerAutoStartPolicy.shouldAutoStart(
                configServerEnabled = false,
                llmConfigured = true
            )
        )
    }
}
