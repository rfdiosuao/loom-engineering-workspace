package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentTaskPublicSnapshotTest {
    @Test
    fun public_snapshot_strips_prompt_result_events_and_secrets() {
        val task = JsonObject().apply {
            addProperty("taskId", "task-1")
            addProperty("status", "running")
            addProperty("prompt", "collect private screen with sk-secret-123456789")
            addProperty("priority", 5)
            addProperty("queueMs", 12)
            addProperty("queueDepth", 1)
            addProperty("queuePosition", 1)
            addProperty("currentTaskId", "task-1")
            addProperty("cancelRequested", false)
            addProperty("mode", "agent")
            addProperty("screenHash", "hash-1")
            addProperty("contractVersion", 1)
            addProperty("progressLogSchema", "apkclaw.progress_log.v1")
            add("metrics", JsonObject().apply {
                addProperty("totalMs", 44)
                addProperty("rounds", 1)
            })
            add("result", JsonObject().apply {
                addProperty("answer", "private answer sk-secret-123456789")
            })
            add("events", JsonArray().apply {
                add(JsonObject().apply {
                    addProperty("type", "tool_call")
                    addProperty("parameters", """{"token":"sk-secret-123456789"}""")
                })
            })
            add("progressLog", JsonArray().apply {
                add(JsonObject().apply {
                    addProperty("round", 1)
                    addProperty("type", "tool")
                    addProperty("toolId", "get_screen_info")
                    addProperty("text", "第 1 阶段：读取当前页面 sk-secret-123456789")
                    addProperty("time", 123L)
                    addProperty("parameters", "private")
                })
            })
            add("agentReport", JsonObject().apply {
                addProperty("schema", "apkclaw.agent_report.v1")
                addProperty("status", "running")
                addProperty("headline", "running: using sk-secret-123456789")
                addProperty("currentStep", "tool_call")
                addProperty("completed", false)
                addProperty("needsCodex", false)
            })
        }

        val public = AgentTaskPublicSnapshot.sanitize(task)
        val serialized = public.toString()

        assertEquals("task-1", public["taskId"].asString)
        assertEquals("running", public["status"].asString)
        assertEquals("agent", public["mode"].asString)
        assertEquals("hash-1", public["screenHash"].asString)
        assertTrue(public.has("agentReport"))
        assertTrue(public.has("metrics"))
        assertEquals(1, public["contractVersion"].asInt)
        assertEquals("apkclaw.progress_log.v1", public["progressLogSchema"].asString)
        assertTrue(public.has("progressLog"))
        assertEquals("tool", public["progressLog"].asJsonArray[0].asJsonObject["type"].asString)
        assertFalse(public["progressLog"].asJsonArray[0].asJsonObject.has("parameters"))
        assertFalse(public.has("prompt"))
        assertFalse(public.has("result"))
        assertFalse(public.has("events"))
        assertFalse(serialized.contains("sk-secret-123456789"))
    }

    @Test
    fun legacy_task_without_progress_schema_remains_compatible() {
        val task = JsonObject().apply {
            addProperty("taskId", "legacy-task")
            addProperty("status", "running")
            add("progressLog", JsonArray().apply {
                add(JsonObject().apply {
                    addProperty("round", 2)
                    addProperty("type", "tool")
                    addProperty("text", "第 2 阶段：执行手机操作")
                    addProperty("time", 456L)
                })
            })
        }

        val public = AgentTaskPublicSnapshot.sanitize(task)

        assertFalse(public.has("progressLogSchema"))
        assertFalse(public.has("contractVersion"))
        assertEquals("第 2 阶段：执行手机操作", public["progressLog"].asJsonArray[0].asJsonObject["text"].asString)
    }
}
