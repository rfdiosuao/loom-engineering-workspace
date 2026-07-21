package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject

/** Builds a small, privacy-safe progress summary from the raw agent event stream. */
object AgentProgressLogBuilder {
    const val CONTRACT_VERSION = 1
    const val SCHEMA = "apkclaw.progress_log.v1"

    private val SAFE_TOOL_ID = Regex("[a-z0-9_.-]+")
    private val TOOL_LABELS = mapOf(
        "open_app" to "打开应用",
        "get_screen_info" to "读取当前页面",
        "tap" to "点击页面元素",
        "click" to "点击页面元素",
        "input_text" to "输入文本",
        "type_text" to "输入文本",
        "swipe" to "滚动查找内容",
        "scroll_to_find" to "滚动查找内容",
        "system_key" to "执行系统按键",
        "press_key" to "执行系统按键",
        "screenshot" to "截取当前页面",
        "take_screenshot" to "截取当前页面",
        "finish" to "整理执行结果",
        "collect_list_items" to "收集页面列表",
        "wait_element" to "等待页面元素"
    )

    fun attachTo(target: JsonObject, events: JsonArray): JsonObject {
        target.addProperty("contractVersion", CONTRACT_VERSION)
        target.addProperty("progressLogSchema", SCHEMA)
        target.add("progressLog", fromEvents(events))
        return target
    }

    fun fromEvents(events: JsonArray, limit: Int = 3): JsonArray {
        val items = mutableListOf<JsonObject>()
        events.forEach { element ->
            if (!element.isJsonObject) return@forEach
            eventToProgress(element.asJsonObject)?.let { item ->
                val previous = items.lastOrNull()
                if (previous == null || progressKey(previous) != progressKey(item)) {
                    items.add(item)
                }
            }
        }

        val safeLimit = limit.coerceIn(1, 20)
        return JsonArray().apply {
            items.takeLast(safeLimit).forEach { add(it) }
        }
    }

    private fun eventToProgress(event: JsonObject): JsonObject? {
        val eventType = event.stringValue("type")?.lowercase() ?: return null
        val round = (event.intValue("round") ?: 0).coerceAtLeast(0)
        val toolId = safeToolId(event.stringValue("toolId"))
        val time = event.longValue("time")?.takeIf { it >= 0L }
        val (type, text) = when (eventType) {
            "loop_start" -> "thinking" to stageText(round, "分析下一步")
            "tool_call" -> "tool" to stageText(round, toolLabel(toolId))
            "tool_result" -> {
                if (event.booleanValue("success") != false) return null
                "error" to stageText(round, "${toolLabel(toolId)}失败")
            }
            "complete", "success" -> "success" to "任务执行完成"
            "error", "failed" -> "error" to "任务执行失败，请查看电脑端诊断"
            "timeout" -> "error" to "任务执行超时，请查看电脑端诊断"
            "cancelled", "canceled" -> "status" to "任务已取消"
            "system_dialog_blocked" -> "error" to "系统弹窗阻止了任务执行"
            "submitted", "queued" -> "status" to "任务已进入执行队列"
            "running" -> "status" to "任务正在执行"
            "cancel_requested" -> "status" to "正在取消任务"
            "template_fallback" -> "status" to "正在切换执行方案"
            else -> return null
        }

        return JsonObject().apply {
            addProperty("round", round)
            addProperty("type", type)
            if (!toolId.isNullOrBlank() && eventType in setOf("tool_call", "tool_result")) {
                addProperty("toolId", toolId)
            }
            addProperty("text", text)
            if (time != null) addProperty("time", time)
        }
    }

    private fun stageText(round: Int, action: String): String {
        return if (round > 0) "第 $round 阶段：$action" else action
    }

    private fun toolLabel(toolId: String?): String = TOOL_LABELS[toolId] ?: "执行手机操作"

    private fun safeToolId(value: String?): String? {
        val normalized = value?.trim()?.lowercase()?.take(80) ?: return null
        return normalized.takeIf { it.matches(SAFE_TOOL_ID) && TOOL_LABELS.containsKey(it) }
    }

    private fun progressKey(item: JsonObject): String {
        return "${item.stringValue("type")}|${item.stringValue("toolId")}|${item.stringValue("text")}"
    }

    private fun JsonObject.stringValue(key: String): String? = runCatching {
        get(key)?.takeIf { it.isJsonPrimitive }?.asString
    }.getOrNull()

    private fun JsonObject.intValue(key: String): Int? = runCatching {
        get(key)?.takeIf { it.isJsonPrimitive }?.asInt
    }.getOrNull()

    private fun JsonObject.longValue(key: String): Long? = runCatching {
        get(key)?.takeIf { it.isJsonPrimitive }?.asLong
    }.getOrNull()

    private fun JsonObject.booleanValue(key: String): Boolean? = runCatching {
        get(key)?.takeIf { it.isJsonPrimitive }?.asBoolean
    }.getOrNull()
}
