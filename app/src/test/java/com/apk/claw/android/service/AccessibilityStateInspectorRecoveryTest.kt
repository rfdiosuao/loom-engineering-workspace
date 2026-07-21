package com.apk.claw.android.service

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityStateInspectorRecoveryTest {
    @Test
    fun stale_state_means_enabled_in_settings_but_not_bound() {
        val state = AccessibilityStateInspector.State(
            masterEnabled = true,
            listedInSettings = true,
            enabledInSettings = true,
            boundToProcess = false
        )

        assertEquals("stale", state.machineState)
        assertEquals("accessibility_stale", state.errorCode)
        assertTrue(state.retryable)
        assertTrue(state.recoveryHint.contains("reopen", ignoreCase = true))
    }

    @Test
    fun bound_but_disabled_state_is_distinct_from_fully_disabled() {
        val state = AccessibilityStateInspector.State(
            masterEnabled = false,
            listedInSettings = false,
            enabledInSettings = false,
            boundToProcess = true
        )

        assertEquals("bound_but_disabled_in_settings", state.machineState)
        assertEquals("accessibility_bound_but_disabled_in_settings", state.errorCode)
        assertFalse(state.retryable)
    }

    @Test
    fun reenable_required_state_is_distinct_from_plain_disabled() {
        val state = AccessibilityStateInspector.State(
            masterEnabled = true,
            listedInSettings = false,
            enabledInSettings = false,
            boundToProcess = false
        )

        assertEquals("reenable_required", state.machineState)
        assertEquals("accessibility_reenable_required", state.errorCode)
        assertTrue(state.recoveryHint.contains("Accessibility", ignoreCase = true))
    }

    @Test
    fun plain_disabled_state_remains_available_for_master_off() {
        val state = AccessibilityStateInspector.State(
            masterEnabled = false,
            listedInSettings = false,
            enabledInSettings = false,
            boundToProcess = false
        )

        assertEquals("disabled", state.machineState)
        assertEquals("accessibility_disabled", state.errorCode)
    }
}
