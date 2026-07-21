package com.apk.claw.android.wechat

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject

object WeChatScreenAnalyzer {
    data class Screen(
        val isWeChat: Boolean,
        val currentPackage: String,
        val contact: String,
        val latestMessage: String,
        val inputNodeId: String,
        val sendNodeId: String,
        val isGroupChat: Boolean
    )

    fun analyze(tree: JsonObject): Screen {
        val screen = tree.objectOrNull("screen") ?: JsonObject()
        val nodes = tree.arrayOrNull("nodes") ?: JsonArray()
        val currentPackage = screen.stringOrEmpty("currentPackage")
        val isWeChat = currentPackage == WECHAT_PACKAGE ||
            nodes.asSequence().mapNotNull { it.asObjectOrNull()?.stringOrEmpty("packageName") }.any { it == WECHAT_PACKAGE }
        val screenHeight = screen.intOrDefault("height", 0).takeIf { it > 0 } ?: 2400
        val visibleNodes = nodes.mapNotNull { it.asObjectOrNull() }
            .filter { it.booleanOrDefault("visible", true) }

        val inputNode = visibleNodes
            .filter { it.booleanOrDefault("editable", false) && it.booleanOrDefault("enabled", true) }
            .maxByOrNull { it.boundsTop() }
        val inputTop = inputNode?.boundsTop() ?: (screenHeight * 0.82f).toInt()

        val contact = visibleNodes
            .filter { it.textValue().isNotBlank() }
            .filter { it.boundsTop() in 1..((screenHeight * 0.20f).toInt()) }
            .map { it.textValue() }
            .firstOrNull { !isChromeText(it) }
            .orEmpty()

        val latestMessage = visibleNodes
            .filter { it.textValue().isNotBlank() }
            .filter { !it.booleanOrDefault("editable", false) }
            .filter { it.boundsBottom() < inputTop }
            .filter { !isChromeText(it.textValue()) }
            .filter { it.textValue() != contact }
            .maxByOrNull { it.boundsBottom() }
            ?.textValue()
            .orEmpty()

        val sendNode = visibleNodes.firstOrNull { node ->
            node.booleanOrDefault("enabled", true) &&
                (node.textValue().equals("发送", ignoreCase = true) || node.textValue().equals("send", ignoreCase = true)) &&
                (node.booleanOrDefault("clickable", false) || node.boundsTop() >= inputTop - 120)
        }

        return Screen(
            isWeChat = isWeChat,
            currentPackage = currentPackage,
            contact = contact,
            latestMessage = latestMessage,
            inputNodeId = inputNode?.stringOrEmpty("id").orEmpty(),
            sendNodeId = sendNode?.stringOrEmpty("id").orEmpty(),
            isGroupChat = looksLikeGroupChat(contact)
        )
    }

    private fun looksLikeGroupChat(value: String): Boolean {
        return Regex("""[（(]\d{2,}[)）]""").containsMatchIn(value) ||
            value.contains("群") && Regex("""\d{2,}""").containsMatchIn(value)
    }

    private fun isChromeText(value: String): Boolean {
        val text = value.trim()
        return text in setOf("微信", "返回", "更多功能按钮，已折叠", "发送", "Send") ||
            Regex("""^\d{1,2}:\d{2}$""").matches(text) ||
            Regex("""^(昨天|今天)\s*\d{1,2}:\d{2}$""").matches(text)
    }

    private fun JsonObject.textValue(): String {
        return stringOrEmpty("text").ifBlank { stringOrEmpty("description") }.replace("\\s+".toRegex(), " ").trim()
    }

    private fun JsonObject.boundsTop(): Int = objectOrNull("bounds")?.intOrDefault("top", 0) ?: 0

    private fun JsonObject.boundsBottom(): Int = objectOrNull("bounds")?.intOrDefault("bottom", 0) ?: 0

    private fun JsonElement.asObjectOrNull(): JsonObject? {
        return if (isJsonObject) asJsonObject else null
    }

    private fun JsonObject.objectOrNull(name: String): JsonObject? {
        val value = get(name) ?: return null
        return if (value.isJsonObject) value.asJsonObject else null
    }

    private fun JsonObject.arrayOrNull(name: String): JsonArray? {
        val value = get(name) ?: return null
        return if (value.isJsonArray) value.asJsonArray else null
    }

    private fun JsonObject.stringOrEmpty(name: String): String {
        val value = get(name) ?: return ""
        if (value.isJsonNull) return ""
        return runCatching { value.asString.orEmpty() }.getOrDefault("")
    }

    private fun JsonObject.intOrDefault(name: String, default: Int): Int {
        val value = get(name) ?: return default
        if (value.isJsonNull) return default
        return runCatching { value.asInt }.getOrDefault(default)
    }

    private fun JsonObject.booleanOrDefault(name: String, default: Boolean): Boolean {
        val value = get(name) ?: return default
        if (value.isJsonNull) return default
        return runCatching { value.asBoolean }.getOrDefault(default)
    }

    private const val WECHAT_PACKAGE = "com.tencent.mm"
}
