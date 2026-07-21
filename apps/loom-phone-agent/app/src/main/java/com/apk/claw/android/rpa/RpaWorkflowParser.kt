package com.apk.claw.android.rpa

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import java.util.UUID

object RpaWorkflowParser {
    data class ParseResult(
        val workflow: RpaWorkflow,
        val sync: Boolean = false
    )

    private val placeholderRegex = Regex("\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}")
    private val stepControlKeys = setOf(
        "id",
        "stepId",
        "action",
        "type",
        "toolName",
        "params",
        "description",
        "waitAfterMs",
        "wait_after_ms",
        "waitAfter",
        "wait_after",
        "timeoutMs",
        "timeout_ms",
        "maxRetries",
        "max_retries",
        "retryDelayMs",
        "retry_delay_ms",
        "guard"
    )

    fun parseRunRequest(root: JsonObject): ParseResult {
        val requestParams = root.objectValue("params")?.stringMapValue().orEmpty()
        val workflowRoot = root.objectValue("workflow") ?: root
        val workflow = parseWorkflow(workflowRoot, requestParams)
        val sync = root.booleanValue("sync", false)
        return ParseResult(workflow, sync)
    }

    fun parseWorkflow(root: JsonObject, requestParams: Map<String, String> = emptyMap()): RpaWorkflow {
        val workflowParams = root.objectValue("params")?.stringMapValue().orEmpty()
        val params = workflowParams + requestParams
        val stepsJson = root.arrayValue("steps")
            ?: throw IllegalArgumentException("RPA workflow must include steps")
        val id = root.stringAny("workflowId", "workflow_id", "id")
            .ifBlank { "rpa_workflow_${UUID.randomUUID()}" }
        val name = root.stringValue("name", id)
        val steps = stepsJson.mapIndexed { index, element ->
            parseStep(element.asJsonObject, index, params)
        }
        return RpaWorkflow(
            id = id,
            name = name,
            version = root.intValue("version", 1),
            steps = steps,
            params = params,
            maxDurationMs = root.longAny("maxDurationMs", "max_duration_ms", default = 300_000L)
                .coerceIn(1_000L, 1_800_000L)
        )
    }

    fun validate(workflow: RpaWorkflow): List<String> {
        val errors = mutableListOf<String>()
        if (workflow.steps.isEmpty()) {
            errors += "RPA workflow must have at least one step"
        }
        if (workflow.steps.size > 200) {
            errors += "RPA workflow has too many steps: ${workflow.steps.size}"
        }
        workflow.steps.forEachIndexed { index, step ->
            val action = RpaActionNormalizer.normalize(step.action)
            if (action.isBlank()) {
                errors += "Step ${index + 1} is missing action"
            } else if (!RpaActionNormalizer.isSupported(action)) {
                errors += "Step ${index + 1} has unsupported action: ${step.action}"
            }
            unresolvedPlaceholders(step.params).forEach { name ->
                errors += "Step ${index + 1} has unresolved param: $name"
            }
        }
        return errors
    }

    private fun parseStep(root: JsonObject, index: Int, params: Map<String, String>): RpaStep {
        val action = root.stringAny("action", "type", "toolName")
        val explicitParams = root.objectValue("params")
            ?.let { jsonToMap(it, params) }
            ?: collectInlineParams(root, params)
        val guard = root.objectValue("guard")?.let { parseGuard(it, params) } ?: RpaStepGuard()
        return RpaStep(
            id = root.stringAny("id", "stepId").ifBlank { "step_${index + 1}" },
            action = RpaActionNormalizer.normalize(action),
            params = explicitParams,
            description = resolveString(root.stringValue("description", action), params),
            waitAfterMs = root.longAny("waitAfterMs", "wait_after_ms", "waitAfter", "wait_after", default = 0L)
                .coerceIn(0L, 30_000L),
            timeoutMs = root.longAny("timeoutMs", "timeout_ms", default = 5_000L)
                .coerceIn(100L, 120_000L),
            maxRetries = root.intAny("maxRetries", "max_retries", default = 0)
                .coerceIn(0, 10),
            retryDelayMs = root.longAny("retryDelayMs", "retry_delay_ms", default = 300L)
                .coerceIn(0L, 30_000L),
            guard = guard
        )
    }

    private fun parseGuard(root: JsonObject, params: Map<String, String>): RpaStepGuard {
        return RpaStepGuard(
            expectedPackage = root.stringAny("expectedPackage", "expected_package")
                .ifBlank { null }
                ?.let { resolveString(it, params) },
            requireText = root.stringListAny("requireText", "require_text", "requiredText", "required_text")
                .map { resolveString(it, params) },
            forbidText = root.stringListAny("forbidText", "forbid_text", "forbiddenText", "forbidden_text")
                .map { resolveString(it, params) }
        )
    }

    private fun collectInlineParams(root: JsonObject, params: Map<String, String>): Map<String, Any> {
        return root.entrySet()
            .filter { (key, _) -> key !in stepControlKeys }
            .mapNotNull { (key, value) -> jsonToAny(value, params)?.let { key to it } }
            .toMap()
    }

    private fun jsonToMap(root: JsonObject, params: Map<String, String>): Map<String, Any> {
        return root.entrySet()
            .mapNotNull { (key, value) -> jsonToAny(value, params)?.let { key to it } }
            .toMap()
    }

    private fun jsonToAny(value: JsonElement, params: Map<String, String>): Any? {
        if (value.isJsonNull) return null
        if (value.isJsonPrimitive) {
            val primitive = value.asJsonPrimitive
            return when {
                primitive.isBoolean -> primitive.asBoolean
                primitive.isNumber -> parseNumber(primitive.asString)
                else -> resolveString(primitive.asString, params)
            }
        }
        if (value.isJsonArray) {
            return value.asJsonArray.mapNotNull { jsonToAny(it, params) }
        }
        if (value.isJsonObject) {
            return jsonToMap(value.asJsonObject, params)
        }
        return null
    }

    private fun parseNumber(text: String): Number {
        val longValue = text.toLongOrNull()
        if (longValue != null) {
            return if (longValue in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong()) longValue.toInt() else longValue
        }
        return text.toDoubleOrNull() ?: 0
    }

    private fun resolveString(value: String, params: Map<String, String>): String {
        return placeholderRegex.replace(value) { match ->
            params[match.groupValues[1]] ?: match.value
        }
    }

    private fun unresolvedPlaceholders(value: Any?): Set<String> {
        return when (value) {
            is String -> placeholderRegex.findAll(value).map { it.groupValues[1] }.toSet()
            is Map<*, *> -> value.values.flatMap { unresolvedPlaceholders(it) }.toSet()
            is Iterable<*> -> value.flatMap { unresolvedPlaceholders(it) }.toSet()
            else -> emptySet()
        }
    }

    private fun JsonObject.stringMapValue(): Map<String, String> {
        return entrySet()
            .mapNotNull { (key, value) ->
                if (value.isJsonPrimitive) key to value.asString else null
            }
            .toMap()
    }

    private fun JsonObject.objectValue(name: String): JsonObject? {
        return get(name)?.takeIf { it.isJsonObject }?.asJsonObject
    }

    private fun JsonObject.arrayValue(name: String): JsonArray? {
        return get(name)?.takeIf { it.isJsonArray }?.asJsonArray
    }

    private fun JsonObject.stringAny(vararg names: String): String {
        return names.firstNotNullOfOrNull { name ->
            get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asString }.getOrNull() }
        }?.trim().orEmpty()
    }

    private fun JsonObject.stringValue(name: String, default: String = ""): String {
        return get(name)?.takeIf { it.isJsonPrimitive }?.let {
            runCatching { it.asString }.getOrDefault(default)
        } ?: default
    }

    private fun JsonObject.intValue(name: String, default: Int = 0): Int {
        return get(name)?.takeIf { it.isJsonPrimitive }?.let {
            runCatching { it.asInt }.getOrDefault(default)
        } ?: default
    }

    private fun JsonObject.intAny(vararg names: String, default: Int = 0): Int {
        return names.firstNotNullOfOrNull { name ->
            get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asInt }.getOrNull() }
        } ?: default
    }

    private fun JsonObject.longAny(vararg names: String, default: Long = 0L): Long {
        return names.firstNotNullOfOrNull { name ->
            get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asLong }.getOrNull() }
        } ?: default
    }

    private fun JsonObject.booleanValue(name: String, default: Boolean): Boolean {
        return get(name)?.takeIf { it.isJsonPrimitive }?.let {
            runCatching { it.asBoolean }.getOrDefault(default)
        } ?: default
    }

    private fun JsonObject.stringListAny(vararg names: String): List<String> {
        val value = names.firstNotNullOfOrNull { name -> get(name) } ?: return emptyList()
        if (value.isJsonArray) {
            return value.asJsonArray.mapNotNull { item ->
                item.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asString }.getOrNull() }
            }
        }
        if (value.isJsonPrimitive) return listOf(value.asString)
        return emptyList()
    }
}
