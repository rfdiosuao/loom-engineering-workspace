package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.SemanticSelector
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

    @Test
    fun blocks_sensitive_semantic_selector_fields() {
        val selectors = listOf(
            SemanticSelector(text = "Delete account"),
            SemanticSelector(contentDescription = "Authorize payment"),
            SemanticSelector(resourceId = "demo:id/privacy_permission")
        )

        selectors.forEachIndexed { index, selector ->
            val decision = RpaSafetyPolicy.inspect(
                RpaStep(
                    id = "semantic-$index",
                    action = "tap_semantic",
                    semanticSelector = selector
                )
            )

            assertFalse("selector=$selector", decision.allowed)
            assertEquals("safety_blocked", decision.errorCode)
        }
    }
}
