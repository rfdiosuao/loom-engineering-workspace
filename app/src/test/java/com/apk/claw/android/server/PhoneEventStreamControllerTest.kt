package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneEventStreamControllerTest {
    @Test
    fun sse_format_uses_event_stream_contract() {
        val data = JsonObject().apply {
            addProperty("schema", "apkclaw.event_stream.snapshot.v1")
            addProperty("online", true)
        }

        val text = PhoneEventStreamController.formatSse(
            event = "snapshot",
            data = data,
            id = 7L,
            retryMs = 3000L
        )

        assertEquals("text/event-stream; charset=utf-8", PhoneEventStreamController.MIME_EVENT_STREAM)
        assertTrue(text.startsWith("id: 7\nretry: 3000\nevent: snapshot\n"))
        assertTrue(text.contains("data: {\"schema\":\"apkclaw.event_stream.snapshot.v1\",\"online\":true}\n\n"))
    }

    @Test
    fun snapshot_event_contains_status_metrics_and_tasks_slots() {
        val status = JsonObject().apply { addProperty("accessibilityRunning", true) }
        val metrics = JsonObject().apply { addProperty("totalMs", 12) }
        val rawTask = JsonObject().apply {
            addProperty("taskId", "task-1")
            addProperty("status", "running")
            addProperty("prompt", "private task content")
        }
        val task = AgentTaskPublicSnapshot.sanitize(
            AgentProgressLogBuilder.attachTo(rawTask, JsonArray().apply {
                add(JsonObject().apply {
                    addProperty("type", "tool_call")
                    addProperty("round", 1)
                    addProperty("time", 100L)
                    addProperty("toolId", "get_screen_info")
                    addProperty("message", "private screen content")
                })
            })
        )

        val snapshot = PhoneEventStreamController.snapshotEvent(
            status = status,
            metrics = metrics,
            tasks = listOf(task),
            nowMs = 1234L
        )

        assertEquals("apkclaw.event_stream.snapshot.v1", snapshot["schema"].asString)
        assertEquals(1234L, snapshot["timestampMs"].asLong)
        assertTrue(snapshot["status"].asJsonObject["accessibilityRunning"].asBoolean)
        assertEquals(12, snapshot["metrics"].asJsonObject["totalMs"].asInt)
        assertEquals(1, snapshot["tasks"].asJsonArray.size())
        val streamedTask = snapshot["tasks"].asJsonArray[0].asJsonObject
        assertEquals(1, streamedTask["contractVersion"].asInt)
        assertEquals("apkclaw.progress_log.v1", streamedTask["progressLogSchema"].asString)
        assertEquals("第 1 阶段：读取当前页面", streamedTask["progressLog"].asJsonArray[0].asJsonObject["text"].asString)
        assertTrue(!streamedTask.has("prompt"))
        assertTrue(!streamedTask.toString().contains("private screen content"))
    }
}
