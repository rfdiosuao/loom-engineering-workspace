package com.apk.claw.android.server

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class PhoneRuntimeMetricsTest {
    @Test
    fun aggregates_task_cache_template_fallback_and_busy_rates_without_prompt_text() {
        val recorder = PhoneRuntimeMetrics(maxErrors = 4)

        recorder.record(
            PhoneRuntimeMetricEvent(
                mode = "observe_fast",
                success = true,
                totalMs = 40,
                rounds = 0,
                cacheHit = false,
            )
        )
        recorder.record(
            PhoneRuntimeMetricEvent(
                mode = "observe_fast",
                success = true,
                totalMs = 8,
                rounds = 0,
                cacheHit = true,
            )
        )
        recorder.record(
            PhoneRuntimeMetricEvent(
                mode = "template",
                success = true,
                totalMs = 22,
                rounds = 0,
                templateHit = true,
            )
        )
        recorder.record(
            PhoneRuntimeMetricEvent(
                mode = "agent_fallback",
                success = false,
                totalMs = 90,
                rounds = 1,
                templateHit = true,
                agentFallback = true,
                errorCode = "task_busy",
                reason = "busy while prompt=send private code 123456",
                fallbackReason = "template/action_fast failed",
            )
        )

        val snapshot = recorder.snapshot(
            queueDepth = 2,
            currentTaskId = "task-running",
            busy = true,
        )

        assertEquals(4, snapshot["taskCount"].asInt)
        assertEquals(3, snapshot["successCount"].asInt)
        assertEquals(1, snapshot["failureCount"].asInt)
        assertEquals(1, snapshot["busyCount"].asInt)
        assertEquals(2, snapshot["queueDepth"].asInt)
        assertEquals("task-running", snapshot["currentTaskId"].asString)
        assertEquals(40L, snapshot["avgTotalMs"].asLong)
        assertEquals(0.25, snapshot["avgRounds"].asDouble, 0.001)
        assertEquals(0.25, snapshot["cacheHitRate"].asDouble, 0.001)
        assertEquals(0.5, snapshot["templateHitRate"].asDouble, 0.001)
        assertEquals(0.25, snapshot["agentFallbackRate"].asDouble, 0.001)
        assertEquals(2, snapshot.getAsJsonObject("modeCounts")["observe_fast"].asInt)
        assertEquals(1, snapshot.getAsJsonObject("modeCounts")["template"].asInt)
        assertEquals(1, snapshot.getAsJsonObject("modeCounts")["agent_fallback"].asInt)
        assertEquals("task_busy", snapshot.getAsJsonArray("lastErrors")[0].asJsonObject["errorCode"].asString)
        assertFalse(snapshot.toString().contains("123456"))
    }

    @Test
    fun extracts_metric_event_from_result_payload() {
        val result = JsonObject().apply {
            addProperty("mode", "agent")
            addProperty("errorCode", "action_failed")
            add("fallback", JsonObject().apply {
                addProperty("from", "template/action_fast")
                addProperty("errorCode", "action_failed")
            })
            add("metrics", JsonObject().apply {
                addProperty("mode", "agent_fallback")
                addProperty("totalMs", 75)
                addProperty("rounds", 1)
                addProperty("cacheHit", false)
                addProperty("templateHit", true)
                addProperty("agentFallback", true)
            })
        }

        val event = PhoneRuntimeMetrics.eventFromResult(success = false, data = result)

        assertEquals("agent_fallback", event.mode)
        assertEquals(false, event.success)
        assertEquals(75L, event.totalMs)
        assertEquals(1, event.rounds)
        assertEquals(true, event.templateHit)
        assertEquals(true, event.agentFallback)
        assertEquals("action_failed", event.errorCode)
    }
}
