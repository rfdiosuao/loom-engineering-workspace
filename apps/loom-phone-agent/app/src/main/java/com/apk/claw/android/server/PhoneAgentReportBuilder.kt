package com.apk.claw.android.server

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject

object PhoneAgentReportBuilder {
    private const val SCHEMA = "apkclaw.agent_report.v1"
    private val terminalStatuses = setOf("success", "error", "cancelled", "failed")
    private val apiKeyRegex = Regex("""(?i)\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,})""")
    private val emailRegex = Regex("""[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}""")
    private val longNumberRegex = Regex("""\b\d{7,}\b""")

    fun fromTask(
        status: String,
        prompt: String,
        result: JsonObject?,
        error: String?,
        events: JsonArray,
        queueMs: Long,
        queueDepth: Int,
        queuePosition: Int?
    ): JsonObject {
        result?.get("agentReport")?.takeIf { it.isJsonObject }?.asJsonObject?.let { existing ->
            return normalizeExisting(
                existing = existing,
                status = status,
                error = error,
                queueMs = queueMs,
                queueDepth = queueDepth,
                queuePosition = queuePosition
            )
        }

        val normalizedStatus = status.ifBlank { "unknown" }
        val resultSuccess = result?.get("success")?.asBooleanOrNull()
        val completed = normalizedStatus in terminalStatuses || resultSuccess != null
        val errorCode = result?.stringValue("errorCode")
            ?: if (!error.isNullOrBlank() && normalizedStatus !in setOf("success", "running", "queued")) normalizedStatus else ""
        val message = firstNonBlank(
            error,
            result?.stringValue("error"),
            result?.stringValue("message"),
            result?.stringValue("answer"),
            latestEvent(events)?.stringValue("message")
        )
        val currentStep = firstNonBlank(
            result?.stringValue("currentStep"),
            latestEvent(events)?.stringValue("type"),
            normalizedStatus
        )
        val needsCodex = errorCode.isNotBlank() || normalizedStatus in setOf("error", "failed")
        val completedSummary = completedSummary(events)

        return base(
            status = normalizedStatus,
            currentStep = currentStep,
            completed = completed,
            needsCodex = needsCodex,
            headline = headline(normalizedStatus, currentStep, message, needsCodex),
            completedSummary = completedSummary,
            lastEvent = latestEvent(events),
            queueMs = queueMs,
            queueDepth = queueDepth,
            queuePosition = queuePosition
        ).apply {
            if (!message.isNullOrBlank()) addProperty("message", sanitizeText(message, 500))
            if (needsCodex) {
                add("exception", exception(errorCode.ifBlank { normalizedStatus }, message))
                addProperty("fixHint", fixHint(errorCode.ifBlank { normalizedStatus }, message))
            }
        }
    }

    fun failure(
        errorCode: String,
        message: String,
        currentStep: String = "failed"
    ): JsonObject {
        val code = errorCode.ifBlank { "phone_task_failed" }
        return base(
            status = "error",
            currentStep = currentStep.ifBlank { "failed" },
            completed = true,
            needsCodex = true,
            headline = headline("error", currentStep, message, true),
            completedSummary = "Task stopped before completion",
            lastEvent = null,
            queueMs = 0L,
            queueDepth = 0,
            queuePosition = null
        ).apply {
            addProperty("message", sanitizeText(message, 500))
            add("exception", exception(code, message))
            addProperty("fixHint", fixHint(code, message))
        }
    }

    fun publicReport(report: JsonObject?): JsonObject {
        if (report == null) return JsonObject()
        return JsonObject().apply {
            val allowed = setOf(
                "schema",
                "status",
                "headline",
                "currentStep",
                "completed",
                "terminal",
                "successful",
                "needsCodex",
                "completedSummary",
                "message",
                "fixHint",
                "queueMs",
                "queueDepth",
                "queuePosition"
            )
            report.entrySet().forEach { (key, value) ->
                if (key !in allowed || value.isJsonNull) return@forEach
                when {
                    value.isJsonPrimitive && value.asJsonPrimitive.isString ->
                        addProperty(key, sanitizeText(value.asString, if (key == "fixHint") 600 else 240))
                    else -> add(key, value.deepCopy())
                }
            }
            report.get("lastEvent")?.takeIf { it.isJsonObject }?.asJsonObject?.let {
                add("lastEvent", sanitizeEvent(it))
            }
            report.get("exception")?.takeIf { it.isJsonObject }?.asJsonObject?.let {
                add("exception", sanitizeException(it))
            }
            if (!has("schema")) addProperty("schema", SCHEMA)
        }
    }

    private fun base(
        status: String,
        currentStep: String,
        completed: Boolean,
        needsCodex: Boolean,
        headline: String,
        completedSummary: String,
        lastEvent: JsonObject?,
        queueMs: Long,
        queueDepth: Int,
        queuePosition: Int?
    ): JsonObject {
        return JsonObject().apply {
            addProperty("schema", SCHEMA)
            addProperty("status", status)
            addProperty("headline", sanitizeText(headline, 240))
            addProperty("currentStep", sanitizeText(currentStep, 120))
            addProperty("completed", completed)
            addProperty("terminal", status in terminalStatuses)
            addProperty("successful", status == "success")
            addProperty("needsCodex", needsCodex)
            addProperty("completedSummary", sanitizeText(completedSummary, 240))
            addProperty("queueMs", queueMs.coerceAtLeast(0L))
            addProperty("queueDepth", queueDepth.coerceAtLeast(0))
            if (queuePosition != null) addProperty("queuePosition", queuePosition)
            if (lastEvent != null) add("lastEvent", sanitizeEvent(lastEvent))
        }
    }

    private fun normalizeExisting(
        existing: JsonObject,
        status: String,
        error: String?,
        queueMs: Long,
        queueDepth: Int,
        queuePosition: Int?
    ): JsonObject {
        val normalizedStatus = status.ifBlank { existing.stringValue("status").ifBlank { "unknown" } }
        val terminal = normalizedStatus in terminalStatuses
        val needsCodex = normalizedStatus in setOf("error", "failed") || (!error.isNullOrBlank() && normalizedStatus != "cancelled")
        val currentStep = if (terminal) {
            normalizedStatus
        } else {
            firstNonBlank(existing.stringValue("currentStep"), normalizedStatus)
        }
        val message = firstNonBlank(error, existing.stringValue("message"), existing.stringValue("headline"), currentStep)
        return publicReport(existing).apply {
            addProperty("schema", SCHEMA)
            addProperty("status", normalizedStatus)
            addProperty("currentStep", sanitizeText(currentStep, 120))
            addProperty("completed", terminal)
            addProperty("terminal", terminal)
            addProperty("successful", normalizedStatus == "success")
            addProperty("needsCodex", needsCodex)
            addProperty("headline", sanitizeText(headline(normalizedStatus, currentStep, message, needsCodex), 240))
            addProperty("queueMs", queueMs.coerceAtLeast(0L))
            addProperty("queueDepth", queueDepth.coerceAtLeast(0))
            if (queuePosition != null) addProperty("queuePosition", queuePosition)
            remove("promptPreview")
        }
    }

    private fun headline(status: String, currentStep: String, message: String?, needsCodex: Boolean): String {
        val prefix = if (needsCodex) "exception" else status
        val detail = firstNonBlank(message, currentStep)
        return "$prefix: $detail"
    }

    private fun completedSummary(events: JsonArray): String {
        val successes = events.mapJsonObjects()
            .filter { event ->
                event.get("success")?.asBooleanOrNull() == true &&
                    event.stringValue("type") !in setOf("submitted", "running", "queued")
            }
        if (successes.isEmpty()) return "No completed actions yet"
        val last = successes.last()
        val label = firstNonBlank(last.stringValue("toolName"), last.stringValue("type"), last.stringValue("message"))
        return "${successes.size} completed action(s); last: $label"
    }

    private fun latestEvent(events: JsonArray): JsonObject? {
        return events.mapJsonObjects().lastOrNull()
    }

    private fun exception(errorCode: String, message: String): JsonObject {
        return JsonObject().apply {
            addProperty("code", sanitizeText(errorCode, 120))
            addProperty("message", sanitizeText(message, 500))
            addProperty("repairTarget", repairTarget(errorCode))
            addProperty("codexInstruction", codexInstruction(errorCode))
        }
    }

    private fun repairTarget(errorCode: String): String {
        return when (errorCode) {
            "accessibility_off",
            "stale_enabled_not_bound",
            "accessibility_stale",
            "accessibility_disabled",
            "accessibility_reenable_required",
            "accessibility_bound_but_disabled_in_settings" -> "apkclaw_accessibility"
            "model_not_configured", "model_not_ready" -> "phone_model_config"
            "task_busy" -> "phone_task_queue"
            "timeout" -> "phone_task_timeout"
            "system_dialog_blocked" -> "phone_system_dialog"
            "auth_failed", "unauthorized", "forbidden" -> "lumi_pairing"
            "device_offline" -> "phone_network"
            "action_failed", "safety_blocked" -> "action_fast_selector"
            else -> "apkclaw_agent_runtime"
        }
    }

    private fun codexInstruction(errorCode: String): String {
        return when (repairTarget(errorCode)) {
            "apkclaw_accessibility" -> "Inspect accessibility binding, stale enabled state, keep-alive, and background kill recovery."
            "phone_model_config" -> "Check LOOM phone model sync and APKClaw LLM configuration."
            "phone_task_queue" -> "Inspect the running task, queue depth, and cancel/retry policy."
            "phone_task_timeout" -> "Inspect slow step, long Agent loop, blocked screen, and timeout budget."
            "phone_system_dialog" -> "Inspect system dialog blocker and require explicit user confirmation if needed."
            "lumi_pairing" -> "Repair Lumi pairing/signature headers without changing token semantics."
            "phone_network" -> "Check phone URL, LAN reachability, server keep-alive, and process survival."
            "action_fast_selector" -> "Inspect selector/action_fast parameters and safety guard."
            else -> "Inspect APKClaw Agent runtime logs, crash logs, metrics, and last task events."
        }
    }

    private fun fixHint(errorCode: String, message: String): String {
        return sanitizeText("${codexInstruction(errorCode)} Last error: $message", 600)
    }

    private fun sanitizeException(exception: JsonObject): JsonObject {
        return JsonObject().apply {
            addProperty("code", sanitizeText(exception.stringValue("code"), 120))
            addProperty("message", sanitizeText(exception.stringValue("message"), 500))
            addProperty("repairTarget", sanitizeText(exception.stringValue("repairTarget"), 120))
            addProperty("codexInstruction", sanitizeText(exception.stringValue("codexInstruction"), 500))
        }
    }

    private fun sanitizeEvent(event: JsonObject): JsonObject {
        return JsonObject().apply {
            for (key in listOf("type", "round", "time", "toolId", "toolName", "success")) {
                val value = event.get(key) ?: continue
                if (!value.isJsonNull) add(key, value.deepCopy())
            }
            val message = event.stringValue("message")
            if (message.isNotBlank()) addProperty("message", sanitizeText(message, 240))
        }
    }

    private fun sanitizeText(value: String, limit: Int): String {
        if (value.isBlank()) return ""
        return value
            .replace(apiKeyRegex, "[redacted-secret]")
            .replace(emailRegex, "[redacted-email]")
            .replace(longNumberRegex, "[redacted-number]")
            .take(limit)
    }

    private fun JsonArray.mapJsonObjects(): List<JsonObject> {
        return mapNotNull { element -> element.takeIf { it.isJsonObject }?.asJsonObject }
    }

    private fun JsonObject.stringValue(key: String): String {
        val value: JsonElement = get(key) ?: return ""
        if (value.isJsonNull) return ""
        return runCatching { value.asString.trim() }.getOrDefault("")
    }

    private fun JsonElement.asBooleanOrNull(): Boolean? {
        return runCatching { asBoolean }.getOrNull()
    }

    private fun firstNonBlank(vararg values: String?): String {
        return values.firstOrNull { !it.isNullOrBlank() }?.trim().orEmpty()
    }
}
