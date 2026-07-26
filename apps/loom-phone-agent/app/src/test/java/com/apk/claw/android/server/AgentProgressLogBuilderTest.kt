package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class AgentProgressLogBuilderTest {
    @Test
    fun builds_same_three_line_chinese_progress_contract_from_raw_events() {
        val events = JsonArray().apply {
            add(event("loop_start", round = 4, time = 100L))
            add(event("tool_call", round = 4, time = 200L, toolId = "get_screen_info"))
            add(event("tool_result", round = 4, time = 250L, toolId = "get_screen_info", success = true))
            add(event("complete", round = 4, time = 300L, success = true))
        }

        val log = AgentProgressLogBuilder.fromEvents(events)

        assertEquals(3, log.size())
        assertEquals("thinking", log[0].asJsonObject["type"].asString)
        assertEquals("第 4 阶段：分析下一步", log[0].asJsonObject["text"].asString)
        assertEquals("tool", log[1].asJsonObject["type"].asString)
        assertEquals("get_screen_info", log[1].asJsonObject["toolId"].asString)
        assertEquals("第 4 阶段：读取当前页面", log[1].asJsonObject["text"].asString)
        assertEquals(200L, log[1].asJsonObject["time"].asLong)
        assertEquals("success", log[2].asJsonObject["type"].asString)
        assertEquals("任务执行完成", log[2].asJsonObject["text"].asString)
    }

    @Test
    fun failed_tool_result_is_visible_without_copying_private_event_message() {
        val events = JsonArray().apply {
            add(event("tool_result", round = 2, time = 500L, toolId = "tap", success = false, message = "secret screen text"))
        }

        val item = AgentProgressLogBuilder.fromEvents(events)[0].asJsonObject

        assertEquals("error", item["type"].asString)
        assertEquals("第 2 阶段：点击页面元素失败", item["text"].asString)
        assertFalse(item.toString().contains("secret screen text"))
    }

    private fun event(
        type: String,
        round: Int,
        time: Long,
        toolId: String? = null,
        success: Boolean? = null,
        message: String? = null
    ): JsonObject = JsonObject().apply {
        addProperty("type", type)
        addProperty("round", round)
        addProperty("time", time)
        if (toolId != null) addProperty("toolId", toolId)
        if (success != null) addProperty("success", success)
        if (message != null) addProperty("message", message)
    }
}
