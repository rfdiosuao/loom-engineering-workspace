package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import java.util.Locale

data class PhoneRuntimeMetricEvent(
    val mode: String,
    val success: Boolean,
    val totalMs: Long = 0L,
    val rounds: Int = 0,
    val cacheHit: Boolean = false,
    val templateHit: Boolean = false,
    val agentFallback: Boolean = false,
    val errorCode: String? = null,
    val reason: String? = null,
    val fallbackReason: String? = null,
)

class PhoneRuntimeMetrics(private val maxErrors: Int = 8) {
    private val lock = Object()
    private val modeCounts = linkedMapOf<String, Int>()
    private val lastErrors = ArrayDeque<JsonObject>()
    private var taskCount = 0
    private var successCount = 0
    private var failureCount = 0
    private var busyCount = 0
    private var totalMsSum = 0L
    private var roundsSum = 0
    private var cacheHitCount = 0
    private var templateHitCount = 0
    private var agentFallbackCount = 0

    fun record(event: PhoneRuntimeMetricEvent) {
        val mode = normalizeMode(event.mode)
        synchronized(lock) {
            taskCount += 1
            if (event.success) successCount += 1 else failureCount += 1
            if (event.errorCode == "task_busy") busyCount += 1
            totalMsSum += event.totalMs.coerceAtLeast(0L)
            roundsSum += event.rounds.coerceAtLeast(0)
            if (event.cacheHit) cacheHitCount += 1
            if (event.templateHit) templateHitCount += 1
            if (event.agentFallback) agentFallbackCount += 1
            modeCounts[mode] = (modeCounts[mode] ?: 0) + 1
            if (!event.success || !event.errorCode.isNullOrBlank()) {
                appendErrorLocked(event, mode)
            }
        }
    }

    fun snapshot(queueDepth: Int, currentTaskId: String?, busy: Boolean): JsonObject {
        synchronized(lock) {
            val denominator = taskCount.coerceAtLeast(1)
            return JsonObject().apply {
                addProperty("taskCount", taskCount)
                addProperty("successCount", successCount)
                addProperty("failureCount", failureCount)
                addProperty("busyCount", busyCount)
                addProperty("queueDepth", queueDepth.coerceAtLeast(0))
                addProperty("busy", busy)
                if (!currentTaskId.isNullOrBlank()) addProperty("currentTaskId", currentTaskId)
                addProperty("avgTotalMs", if (taskCount == 0) 0L else totalMsSum / taskCount)
                addProperty("avgRounds", if (taskCount == 0) 0.0 else roundsSum.toDouble() / taskCount.toDouble())
                addProperty("cacheHitRate", cacheHitCount.toDouble() / denominator.toDouble())
                addProperty("templateHitRate", templateHitCount.toDouble() / denominator.toDouble())
                addProperty("agentFallbackRate", agentFallbackCount.toDouble() / denominator.toDouble())
                add("modeCounts", JsonObject().apply {
                    modeCounts.forEach { (mode, count) -> addProperty(mode, count) }
                })
                add("lastErrors", JsonArray().apply {
                    lastErrors.forEach { add(it.deepCopy()) }
                })
            }
        }
    }

    private fun appendErrorLocked(event: PhoneRuntimeMetricEvent, mode: String) {
        while (lastErrors.size >= maxErrors.coerceAtLeast(1)) {
            lastErrors.removeFirst()
        }
        lastErrors.addLast(JsonObject().apply {
            addProperty("mode", mode)
            addProperty("errorCode", sanitize(event.errorCode ?: "phone_task_failed"))
            if (!event.reason.isNullOrBlank()) addProperty("reason", sanitize(event.reason))
            if (!event.fallbackReason.isNullOrBlank()) addProperty("fallbackReason", sanitize(event.fallbackReason))
        })
    }

    private fun normalizeMode(value: String): String {
        return value.trim().lowercase(Locale.US).ifBlank { "unknown" }
    }

    private fun sanitize(value: String): String {
        return value
            .replace(Regex("\\b\\d{4,}\\b"), "[number]")
            .replace(Regex("(?i)(prompt|token|password|secret|apikey|api_key)=\\S+"), "$1=[redacted]")
            .take(180)
    }

    companion object {
        fun eventFromResult(success: Boolean, data: JsonObject?): PhoneRuntimeMetricEvent {
            val result = data ?: JsonObject()
            val metrics = result.get("metrics")?.takeIf { it.isJsonObject }?.asJsonObject
            val mode = stringAny(metrics, "mode") ?: stringAny(result, "mode") ?: "unknown"
            val fallback = result.get("fallback")?.takeIf { it.isJsonObject }?.asJsonObject
            val errorCode = stringAny(result, "errorCode")
                ?: stringAny(metrics, "errorCode")
                ?: stringAny(fallback, "errorCode")
            val fallbackReason = stringAny(result, "fallbackReason")
                ?: stringAny(metrics, "fallbackReason")
                ?: stringAny(fallback, "from")
                ?: ""
            val templateHit = boolAny(metrics, "templateHit")
                || boolAny(result, "templateHit")
                || result.has("templateId")
                || mode == "template"
                || fallbackReason.contains("template", ignoreCase = true)
            val agentFallback = boolAny(metrics, "agentFallback")
                || boolAny(result, "agentFallback")
                || mode.contains("fallback", ignoreCase = true)
                || fallback != null
            return PhoneRuntimeMetricEvent(
                mode = mode,
                success = success,
                totalMs = longAny(metrics, "totalMs") ?: longAny(result, "totalMs") ?: 0L,
                rounds = intAny(metrics, "rounds") ?: intAny(result, "rounds") ?: 0,
                cacheHit = boolAny(metrics, "cacheHit") || boolAny(result, "cacheHit"),
                templateHit = templateHit,
                agentFallback = agentFallback,
                errorCode = errorCode,
                reason = stringAny(result, "reason") ?: stringAny(result, "error"),
                fallbackReason = fallbackReason.ifBlank { null },
            )
        }

        private fun stringAny(json: JsonObject?, name: String): String? {
            val value = json?.get(name) ?: return null
            if (!value.isJsonPrimitive) return null
            return runCatching { value.asString }.getOrNull()?.takeIf { it.isNotBlank() }
        }

        private fun boolAny(json: JsonObject?, name: String): Boolean {
            val value = json?.get(name) ?: return false
            if (!value.isJsonPrimitive) return false
            return runCatching { value.asBoolean }.getOrDefault(false)
        }

        private fun longAny(json: JsonObject?, name: String): Long? {
            val value = json?.get(name) ?: return null
            if (!value.isJsonPrimitive) return null
            return runCatching { value.asLong }.getOrNull()
        }

        private fun intAny(json: JsonObject?, name: String): Int? {
            val value = json?.get(name) ?: return null
            if (!value.isJsonPrimitive) return null
            return runCatching { value.asInt }.getOrNull()
        }
    }
}
