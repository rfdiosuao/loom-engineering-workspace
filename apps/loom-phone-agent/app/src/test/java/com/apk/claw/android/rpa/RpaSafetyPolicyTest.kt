package com.apk.claw.android.rpa

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RpaSafetyPolicyTest {
    @Test
    fun allows_normal_navigation_step() {
        val decision = RpaSafetyPolicy.inspect(
            RpaStep(
                id = "open",
                action = "open_app",
                params = mapOf("package" to "com.example.app")
            )
        )

        assertTrue(decision.allowed)
    }

    @Test
    fun blocks_sensitive_target_text_by_default() {
        val decision = RpaSafetyPolicy.inspect(
            RpaStep(
                id = "pay",
                action = "tap_text",
                params = mapOf("text" to "Pay now")
            )
        )

        assertFalse(decision.allowed)
        assertEquals("safety_blocked", decision.errorCode)
    }

    @Test
    fun blocks_dangerous_action_name() {
        val decision = RpaSafetyPolicy.inspect(
            RpaStep(
                id = "delete",
                action = "delete",
                params = emptyMap()
            )
        )

        assertFalse(decision.allowed)
        assertEquals("safety_blocked", decision.errorCode)
    }
}
