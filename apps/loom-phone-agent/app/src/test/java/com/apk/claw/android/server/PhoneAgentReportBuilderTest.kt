package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneAgentReportBuilderTest {
    @Test
    fun running_report_summarizes_current_step_and_completed_actions() {
        val events = JsonArray().apply {
            add(JsonObject().apply {
                addProperty("type", "submitted")
                addProperty("time", 100L)
                addProperty("success", true)
                addProperty("message", "Task accepted")
            })
            add(JsonObject().apply {
                addProperty("type", "action_fast_click")
                addProperty("time", 200L)
                addProperty("success", true)
                addProperty("toolName", "click_text")
                addProperty("message", "Clicked 登录")
            })
            add(JsonObject().apply {
                addProperty("type", "running")
                addProperty("time", 300L)
                addProperty("message", "Waiting for next screen")
            })
        }

        val report = PhoneAgentReportBuilder.fromTask(
            status = "running",
            prompt = "点击登录",
            result = null,
            error = null,
            events = events,
            queueMs = 12L,
            queueDepth = 0,
            queuePosition = null
        )

        assertEquals("apkclaw.agent_report.v1", report["schema"].asString)
        assertEquals("running", report["status"].asString)
        assertEquals("running", report["currentStep"].asString)
        assertFalse(report["completed"].asBoolean)
        assertFalse(report["needsCodex"].asBoolean)
        assertTrue(report["headline"].asString.contains("running"))
        assertTrue(report["completedSummary"].asString.contains("1"))
        assertTrue(report["lastEvent"].asJsonObject["message"].asString.contains("Waiting"))
    }

    @Test
    fun failure_report_contains_exception_and_codex_fix_hint() {
        val report = PhoneAgentReportBuilder.failure(
            errorCode = "accessibility_off",
            message = "Accessibility is enabled in Android Settings but is not bound to the APKClaw process.",
            currentStep = "failed"
        )

        assertEquals("failed", report["currentStep"].asString)
        assertTrue(report["completed"].asBoolean)
        assertTrue(report["needsCodex"].asBoolean)
        assertEquals("accessibility_off", report["exception"].asJsonObject["code"].asString)
        assertEquals("apkclaw_accessibility", report["exception"].asJsonObject["repairTarget"].asString)
        assertTrue(report["fixHint"].asString.contains("Accessibility"))
    }

    @Test
    fun public_report_redacts_prompt_and_tool_parameters() {
        val events = JsonArray().apply {
            add(JsonObject().apply {
                addProperty("type", "tool_call")
                addProperty("round", 2)
                addProperty("toolName", "input_text")
                addProperty("parameters", """{"apiKey":"sk-secret-123456789","phone":"18812345678"}""")
                addProperty("message", "using Bearer abcdefghijklmnop for user@example.com")
            })
        }

        val report = PhoneAgentReportBuilder.fromTask(
            status = "running",
            prompt = "task contains sk-secret-123456789 user@example.com 18812345678",
            result = null,
            error = null,
            events = events,
            queueMs = 10L,
            queueDepth = 1,
            queuePosition = 1
        )
        val serialized = report.toString()

        assertFalse(report.has("promptPreview"))
        assertFalse(serialized.contains("sk-secret-123456789"))
        assertFalse(serialized.contains("18812345678"))
        assertFalse(serialized.contains("user@example.com"))
        assertFalse(report["lastEvent"].asJsonObject.has("parameters"))
        assertTrue(report["lastEvent"].asJsonObject["message"].asString.contains("[redacted"))
    }

    @Test
    fun outer_task_status_overrides_stale_inner_report() {
        val result = JsonObject().apply {
            addProperty("success", true)
            add("agentReport", JsonObject().apply {
                addProperty("schema", "apkclaw.agent_report.v1")
                addProperty("status", "success")
                addProperty("headline", "success: leaked sk-secret-123456789")
                addProperty("currentStep", "complete")
                addProperty("completed", true)
                addProperty("needsCodex", false)
                addProperty("promptPreview", "sk-secret-123456789")
                add("lastEvent", JsonObject().apply {
                    addProperty("type", "tool_call")
                    addProperty("parameters", """{"token":"sk-secret-123456789"}""")
                })
            })
        }

        val report = PhoneAgentReportBuilder.fromTask(
            status = "cancelled",
            prompt = "cancel sk-secret-123456789",
            result = result,
            error = "cancelled by caller",
            events = JsonArray(),
            queueMs = 88L,
            queueDepth = 3,
            queuePosition = 2
        )
        val serialized = report.toString()

        assertEquals("cancelled", report["status"].asString)
        assertEquals("cancelled", report["currentStep"].asString)
        assertFalse(report["needsCodex"].asBoolean)
        assertEquals(88L, report["queueMs"].asLong)
        assertEquals(3, report["queueDepth"].asInt)
        assertEquals(2, report["queuePosition"].asInt)
        assertFalse(serialized.contains("sk-secret-123456789"))
        assertFalse(report.has("promptPreview"))
    }
}
