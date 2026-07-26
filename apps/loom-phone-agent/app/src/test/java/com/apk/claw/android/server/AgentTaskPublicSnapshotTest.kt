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
        assertTrue(public.has("progressLog"))
        assertEquals("tool", public["progressLog"].asJsonArray[0].asJsonObject["type"].asString)
        assertFalse(public["progressLog"].asJsonArray[0].asJsonObject.has("parameters"))
        assertFalse(public.has("prompt"))
        assertFalse(public.has("result"))
        assertFalse(public.has("events"))
        assertFalse(serialized.contains("sk-secret-123456789"))
    }

    @Test
    fun hybrid_public_snapshot_allows_only_additive_scalar_metrics() {
        val task = JsonObject().apply {
            addProperty("mode", "hybrid_rpa")
            addProperty("templateStatus", "validating")
            addProperty("templateRevision", 2)
            addProperty("validationProgress", "2/3")
            addProperty("promotionEligible", true)
            addProperty("promotionIneligibleReason", "")
            addProperty("fallbackStepIndex", 3)
            add("metrics", JsonObject().apply {
                addProperty("resolverPolicy", "TREE_PREFERRED")
                addProperty("resolverUsed", "RESOURCE_ID")
                addProperty("uiGeneration", 9)
                addProperty("frameId", "frame-9")
                addProperty("frameSource", "fresh")
                addProperty("frameAgeMs", 4)
                addProperty("outcomeState", "verified")
                addProperty("treeSnapshotMs", 2)
                addProperty("treeLookupMs", 1)
                addProperty("treeCacheHit", true)
                addProperty("nodesVisited", 7)
                addProperty("compactTreeReads", 1)
                addProperty("fullTreeReads", 0)
                addProperty("selectorText", "private-screen-text")
                addProperty("params", "secret-value")
                addProperty("rawTree", "private-screen-text")
            })
        }

        val public = AgentTaskPublicSnapshot.sanitize(task)
        val serialized = public.toString()

        listOf(
            "templateStatus", "templateRevision", "validationProgress", "promotionEligible",
            "promotionIneligibleReason", "fallbackStepIndex"
        ).forEach { assertTrue("missing public field $it", public.has(it)) }
        listOf(
            "resolverPolicy", "resolverUsed", "uiGeneration", "frameId", "frameSource", "frameAgeMs",
            "outcomeState", "treeSnapshotMs", "treeLookupMs", "treeCacheHit", "nodesVisited",
            "compactTreeReads", "fullTreeReads"
        ).forEach { assertTrue("missing metric $it", public["metrics"].asJsonObject.has(it)) }
        listOf("selectorText", "params", "rawTree", "private-screen-text", "secret-value").forEach {
            assertFalse("leaked $it", serialized.contains(it, ignoreCase = true))
        }
    }
}
