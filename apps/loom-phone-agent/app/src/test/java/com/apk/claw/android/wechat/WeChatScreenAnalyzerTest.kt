package com.apk.claw.android.wechat

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WeChatScreenAnalyzerTest {
    @Test
    fun extracts_contact_latest_message_input_and_send_button_from_chat_screen() {
        val screen = WeChatScreenAnalyzer.analyze(
            tree = tree(
                node("title", "TextView", "Alice", top = 44, bottom = 100),
                node("msg-1", "TextView", "昨天 20:00", top = 260, bottom = 300),
                node("msg-2", "TextView", "你好，在吗？", top = 820, bottom = 900),
                node("input", "EditText", "", top = 2200, bottom = 2290, editable = true),
                node("send", "Button", "发送", top = 2200, bottom = 2290, clickable = true)
            )
        )

        assertTrue(screen.isWeChat)
        assertEquals("Alice", screen.contact)
        assertEquals("你好，在吗？", screen.latestMessage)
        assertEquals("input", screen.inputNodeId)
        assertEquals("send", screen.sendNodeId)
        assertFalse(screen.isGroupChat)
    }

    @Test
    fun marks_group_chat_when_title_looks_like_member_count() {
        val screen = WeChatScreenAnalyzer.analyze(
            tree = tree(
                node("title", "TextView", "客户群(12)", top = 44, bottom = 100),
                node("msg", "TextView", "今天有空吗", top = 820, bottom = 900),
                node("input", "EditText", "", top = 2200, bottom = 2290, editable = true)
            )
        )

        assertTrue(screen.isGroupChat)
        assertEquals("客户群(12)", screen.contact)
    }

    private fun tree(vararg nodes: JsonObject): JsonObject {
        return JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.tencent.mm")
                addProperty("currentApp", "微信")
                addProperty("width", 1080)
                addProperty("height", 2400)
            })
            add("nodes", JsonArray().apply {
                nodes.forEach { add(it) }
            })
        }
    }

    private fun node(
        id: String,
        className: String,
        text: String,
        top: Int,
        bottom: Int,
        clickable: Boolean = false,
        editable: Boolean = false
    ): JsonObject {
        return JsonObject().apply {
            addProperty("id", id)
            addProperty("className", className)
            addProperty("text", text)
            addProperty("description", "")
            addProperty("resourceId", "")
            addProperty("packageName", "com.tencent.mm")
            addProperty("visible", true)
            addProperty("clickable", clickable)
            addProperty("editable", editable)
            addProperty("enabled", true)
            add("bounds", JsonObject().apply {
                addProperty("left", 0)
                addProperty("top", top)
                addProperty("right", 1000)
                addProperty("bottom", bottom)
                addProperty("centerX", 500)
                addProperty("centerY", (top + bottom) / 2)
            })
        }
    }
}
