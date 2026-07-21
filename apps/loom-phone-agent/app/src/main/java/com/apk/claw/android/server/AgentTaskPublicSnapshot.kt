package com.apk.claw.android.server

import com.google.gson.JsonElement
import com.google.gson.JsonObject

object AgentTaskPublicSnapshot {
    private val secretRegex = Regex("""(?i)\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,})""")
    private val emailRegex = Regex("""[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}""")
    private val longNumberRegex = Regex("""\b\d{7,}\b""")

    fun sanitize(task: JsonObject): JsonObject {
        return JsonObject().apply {
            for (key in PUBLIC_FIELDS) {
                task.get(key)?.takeIf { !it.isJsonNull }?.let { value ->
                    addPublicValue(key, value)
                }
            }
            task.get("agentReport")?.takeIf { it.isJsonObject }?.asJsonObject?.let {
                add("agentReport", PhoneAgentReportBuilder.publicReport(it))
            }
            task.get("metrics")?.takeIf { it.isJsonObject }?.asJsonObject?.let {
                add("metrics", sanitizeMetrics(it))
            }
            task.get("progressLog")?.takeIf { it.isJsonArray }?.asJsonArray?.let {
                add("progressLog", sanitizeProgressLog(it))
            }
        }
    }

    private fun sanitizeProgressLog(progressLog: com.google.gson.JsonArray): com.google.gson.JsonArray {
        val safeItems = progressLog
            .filter { it.isJsonObject }
            .map { item ->
                JsonObject().apply {
                    val source = item.asJsonObject
                    for (key in PROGRESS_FIELDS) {
                        val value = source.get(key) ?: continue
                        if (value.isJsonNull || !value.isJsonPrimitive) continue
                        val primitive = value.asJsonPrimitive
                        when {
                            primitive.isString -> addProperty(key, redact(primitive.asString, 240))
                            primitive.isBoolean -> addProperty(key, primitive.asBoolean)
                            primitive.isNumber -> add(key, primitive.deepCopy())
                        }
                    }
                }
            }
            .takeLast(3)
        return com.google.gson.JsonArray().apply { safeItems.forEach { add(it) } }
    }

    private fun JsonObject.addPublicValue(key: String, value: JsonElement) {
        if (value.isJsonPrimitive) {
            val primitive = value.asJsonPrimitive
            when {
                primitive.isString -> addProperty(key, redact(primitive.asString, 240))
                primitive.isBoolean -> addProperty(key, primitive.asBoolean)
                primitive.isNumber -> add(key, primitive.deepCopy())
                else -> add(key, primitive.deepCopy())
            }
        } else if (value.isJsonObject && key == "queue") {
            add(key, sanitizeQueue(value.asJsonObject))
        }
    }

    private fun sanitizeMetrics(metrics: JsonObject): JsonObject {
        return JsonObject().apply {
            for (key in METRIC_FIELDS) {
                val value = metrics.get(key) ?: continue
                if (value.isJsonNull) continue
                if (value.isJsonPrimitive && value.asJsonPrimitive.isString) {
                    addProperty(key, redact(value.asString, 240))
                } else {
                    add(key, value.deepCopy())
                }
            }
        }
    }

    private fun sanitizeQueue(queue: JsonObject): JsonObject {
        return JsonObject().apply {
            for (key in QUEUE_FIELDS) {
                val value = queue.get(key) ?: continue
                if (!value.isJsonNull) addPublicValue(key, value)
            }
        }
    }

    private fun redact(value: String, limit: Int): String {
        return value
            .replace(secretRegex, "[redacted-secret]")
            .replace(emailRegex, "[redacted-email]")
            .replace(longNumberRegex, "[redacted-number]")
            .take(limit)
    }

    private val PUBLIC_FIELDS = setOf(
        "taskId",
        "id",
        "status",
        "priority",
        "createdAt",
        "startedAt",
        "finishedAt",
        "queueMs",
        "queueDepth",
        "queuePosition",
        "currentTaskId",
        "cancelRequested",
        "mode",
        "screenHash",
        "contractVersion",
        "progressLogSchema",
        "error",
        "queue"
    )

    private val QUEUE_FIELDS = setOf(
        "queueMs",
        "queueDepth",
        "queuePosition",
        "currentTaskId",
        "cancelRequested"
    )

    private val METRIC_FIELDS = setOf(
        "totalMs",
        "precheckMs",
        "screenTreeMs",
        "screenshotMs",
        "llmRoundMs",
        "toolCallMs",
        "actionVerifyMs",
        "cacheHit",
        "templateHit",
        "agentFallback",
        "fallbackReason",
        "rounds",
        "mode"
    )

    private val PROGRESS_FIELDS = setOf(
        "round",
        "type",
        "toolId",
        "text",
        "time"
    )
}
