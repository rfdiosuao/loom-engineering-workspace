package com.apk.claw.android.agent

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionFastExecutorTest {
    @Test
    fun normalizes_common_fast_action_aliases() {
        assertEquals("click_text", ActionFastExecutor.normalizeAction("tap_text"))
        assertEquals("click_node", ActionFastExecutor.normalizeAction("tap_node"))
        assertEquals("input", ActionFastExecutor.normalizeAction("input_text"))
        assertEquals("back", ActionFastExecutor.normalizeAction("press_back"))
        assertEquals("home", ActionFastExecutor.normalizeAction("press_home"))
        assertEquals("wait_text", ActionFastExecutor.normalizeAction("wait_for_text"))
        assertEquals("click_description", ActionFastExecutor.normalizeAction("tap_description"))
        assertEquals("click_description", ActionFastExecutor.normalizeAction("click_desc"))
        assertEquals("open_app", ActionFastExecutor.normalizeAction("open_settings"))
        assertEquals("click_ref", ActionFastExecutor.normalizeAction("tap_ref"))
        assertEquals("click_ref", ActionFastExecutor.normalizeAction("ref_click"))
    }

    @Test
    fun rejects_dangerous_fast_actions_and_sensitive_targets() {
        assertTrue(ActionFastExecutor.rejectDangerous("delete", "confirm")!!.contains("dangerous"))
        assertTrue(ActionFastExecutor.rejectDangerous("click_text", "Pay now")!!.contains("sensitive"))
        assertTrue(ActionFastExecutor.rejectDangerous("input", "password")!!.contains("sensitive"))
        assertNull(ActionFastExecutor.rejectDangerous("click_text", "Settings"))
    }

    @Test
    fun builds_safety_text_from_all_fast_action_target_fields() {
        val target = JsonObject().apply {
            addProperty("contentDescription", "Pay now")
            addProperty("resourceId", "com.example:id/payment")
            addProperty("targetLabel", "Confirm payment")
            addProperty("reason", "continue checkout")
        }

        val safetyText = ActionFastExecutor.safetyTextFrom(target)

        assertTrue(safetyText.contains("Pay now"))
        assertTrue(safetyText.contains("com.example:id/payment"))
        assertTrue(safetyText.contains("Confirm payment"))
        assertTrue(safetyText.contains("continue checkout"))
        assertTrue(ActionFastExecutor.rejectDangerous("click_description", safetyText)!!.contains("sensitive"))
    }

    @Test
    fun extracts_wait_targets_for_text_and_resource_id() {
        val byText = JsonObject().apply {
            addProperty("targetText", "Continue")
        }
        val textTarget = ActionFastExecutor.waitTargetFrom(byText)
        assertEquals("text", textTarget?.kind)
        assertEquals("Continue", textTarget?.value)

        val byResourceId = JsonObject().apply {
            addProperty("resourceId", "com.example:id/done")
        }
        val resourceTarget = ActionFastExecutor.waitTargetFrom(byResourceId)
        assertEquals("resource_id", resourceTarget?.kind)
        assertEquals("com.example:id/done", resourceTarget?.value)

        val byDescription = JsonObject().apply {
            addProperty("contentDescription", "Search")
        }
        val descriptionTarget = ActionFastExecutor.waitTargetFrom(byDescription)
        assertEquals("description", descriptionTarget?.kind)
        assertEquals("Search", descriptionTarget?.value)
    }

    @Test
    fun extracts_click_targets_for_text_description_and_resource_id() {
        val byText = JsonObject().apply {
            addProperty("text", "Continue")
        }
        val textTarget = ActionFastExecutor.clickTargetFrom(byText)
        assertEquals("text", textTarget?.kind)
        assertEquals("Continue", textTarget?.value)

        val byDescription = JsonObject().apply {
            addProperty("contentDescription", "Search")
        }
        val descriptionTarget = ActionFastExecutor.clickTargetFrom(byDescription)
        assertEquals("description", descriptionTarget?.kind)
        assertEquals("Search", descriptionTarget?.value)

        val byResourceId = JsonObject().apply {
            addProperty("resourceId", "com.example:id/search")
        }
        val resourceTarget = ActionFastExecutor.clickTargetFrom(byResourceId)
        assertEquals("resource_id", resourceTarget?.kind)
        assertEquals("com.example:id/search", resourceTarget?.value)
    }

    @Test
    fun extracts_snapshot_refs_for_fast_actions() {
        val byRef = JsonObject().apply {
            addProperty("target_ref", "ref_abc123")
        }

        assertEquals("ref_abc123", ActionFastExecutor.refFrom(byRef))
    }
}
