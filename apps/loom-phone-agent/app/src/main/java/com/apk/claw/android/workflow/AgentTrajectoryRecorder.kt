package com.apk.claw.android.workflow

import java.util.IdentityHashMap

enum class TrajectoryEvidenceKind(val scheme: String) {
    SCREENSHOT("screenshot"),
    TREE("tree"),
    CHECKPOINT("checkpoint")
}

data class TrajectoryEvidenceRef(
    val reference: String,
    val kind: TrajectoryEvidenceKind
) {
    init {
        require(TrajectoryBoundaryValidator.isValidEvidence(this)) { "invalid_evidence_reference" }
    }
}

data class TrajectoryAction(
    val toolId: String,
    val toolName: String,
    val params: Map<String, Any?>,
    val success: Boolean,
    val safetyLabel: String = "",
    val riskDeclaration: TemplateRiskLevel = TemplateRiskLevel.UNKNOWN,
    val description: String = "",
    val semanticSelector: SemanticSelector? = null,
    val visualAnchor: VisualAnchorSpec? = null,
    val preCheckpoint: StepCheckpoint? = null,
    val postCheckpoint: StepCheckpoint? = null,
    val preEvidence: TrajectoryEvidenceRef? = null,
    val postEvidence: TrajectoryEvidenceRef? = null
)

class AgentTrajectoryRecorder {
    private data class PendingAction(
        val toolId: String,
        val toolName: String,
        val params: Map<String, Any?>,
        val safetyLabel: String,
        val riskDeclaration: TemplateRiskLevel,
        val description: String,
        val semanticSelector: SemanticSelector?,
        val visualAnchor: VisualAnchorSpec?,
        val preCheckpoint: StepCheckpoint?,
        val preEvidence: TrajectoryEvidenceRef?
    )

    private val pendingActions = mutableMapOf<String, PendingAction>()
    private val usedToolIds = mutableSetOf<String>()
    private val completedActions = mutableListOf<TrajectoryAction>()

    fun beforeAction(
        toolId: String,
        toolName: String,
        params: Map<String, Any?>,
        evidence: TrajectoryEvidenceRef? = null,
        safetyLabel: String = "",
        description: String = "",
        semanticSelector: SemanticSelector? = null,
        visualAnchor: VisualAnchorSpec? = null,
        preCheckpoint: StepCheckpoint? = null,
        riskDeclaration: TemplateRiskLevel? = null
    ) {
        require(toolId.isNotBlank()) { "blank_tool_id" }
        require(toolId !in usedToolIds) { "duplicate_tool_id" }
        val metadataReason = TrajectoryBoundaryValidator.recorderMetadataReason(
            toolName, safetyLabel, description, semanticSelector, visualAnchor, preCheckpoint, evidence
        )
        require(metadataReason == null) { metadataReason ?: "invalid_action_metadata" }
        val normalizedParams = normalizeToolParamAliases(toolName, params)
        val sanitizedParams = sanitizeTrajectoryParams(toolName, normalizedParams)
        require(sanitizedParams is TrajectoryParamsSanitization.Safe) { "unsafe_parameter_value" }
        require(validateToolParams(toolName, sanitizedParams.params)) { "invalid_tool_params" }
        val retainedParams = projectTrajectoryParams(toolName, sanitizedParams.params)
        val normalizedRisk = TemplateEligibilityPolicy.classifyRecordedRisk(
            toolName, retainedParams, riskDeclaration, safetyLabel, description, semanticSelector
        )

        usedToolIds += toolId
        pendingActions[toolId] = PendingAction(
            toolId = toolId,
            toolName = toolName,
            params = retainedParams,
            safetyLabel = safetyLabel.take(MAX_RETAINED_SEMANTIC_LENGTH),
            riskDeclaration = normalizedRisk,
            description = description.take(MAX_RETAINED_SEMANTIC_LENGTH),
            semanticSelector = semanticSelector,
            visualAnchor = visualAnchor,
            preCheckpoint = preCheckpoint,
            preEvidence = evidence
        )
    }

    fun afterAction(
        toolId: String,
        success: Boolean,
        evidence: TrajectoryEvidenceRef? = null,
        postCheckpoint: StepCheckpoint? = null
    ) {
        require(toolId.isNotBlank()) { "blank_tool_id" }
        val pending = pendingActions[toolId] ?: throw IllegalArgumentException("unmatched_tool_id")
        require(TrajectoryBoundaryValidator.isValidCheckpoint(postCheckpoint)) { "invalid_checkpoint" }
        require(TrajectoryBoundaryValidator.isValidEvidence(evidence)) { "invalid_evidence_reference" }
        pendingActions.remove(toolId)
        if (pending.toolName == "finish") return
        completedActions += TrajectoryAction(
            toolId = pending.toolId,
            toolName = pending.toolName,
            params = pending.params,
            success = success,
            safetyLabel = pending.safetyLabel,
            riskDeclaration = pending.riskDeclaration,
            description = pending.description,
            semanticSelector = pending.semanticSelector,
            visualAnchor = pending.visualAnchor,
            preCheckpoint = pending.preCheckpoint,
            postCheckpoint = postCheckpoint,
            preEvidence = pending.preEvidence,
            postEvidence = evidence
        )
    }

    fun completed(): List<TrajectoryAction> = completedActions.toList()

    fun pendingAction(toolId: String): TrajectoryAction? = pendingActions[toolId]?.let { pending ->
        TrajectoryAction(
            toolId = pending.toolId,
            toolName = pending.toolName,
            params = pending.params,
            success = false,
            safetyLabel = pending.safetyLabel,
            riskDeclaration = pending.riskDeclaration,
            description = pending.description,
            semanticSelector = pending.semanticSelector,
            visualAnchor = pending.visualAnchor,
            preCheckpoint = pending.preCheckpoint,
            preEvidence = pending.preEvidence
        )
    }
}

internal object TrajectoryBoundaryValidator {
    private val packageName = Regex("^[A-Za-z][A-Za-z0-9_.]{0,127}$")
    private val opaqueReference = Regex("^(?:screenshot|tree|checkpoint)://[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    private val hash = Regex("^[A-Za-z0-9_-]{1,128}$")
    private val anchorName = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    fun isValidRecorderMetadata(
        toolName: String,
        safetyLabel: String,
        description: String,
        selector: SemanticSelector?,
        anchor: VisualAnchorSpec?,
        checkpoint: StepCheckpoint?,
        evidence: TrajectoryEvidenceRef?
    ): Boolean = recorderMetadataReason(toolName, safetyLabel, description, selector, anchor, checkpoint, evidence) == null

    fun recorderMetadataReason(
        toolName: String,
        safetyLabel: String,
        description: String,
        selector: SemanticSelector?,
        anchor: VisualAnchorSpec?,
        checkpoint: StepCheckpoint?,
        evidence: TrajectoryEvidenceRef?
    ): String? = when {
        toolName.length !in 1..MAX_TOOL_NAME_LENGTH || safetyLabel.length > MAX_TRANSIENT_SEMANTIC_LENGTH ||
            description.length > MAX_TRANSIENT_SEMANTIC_LENGTH -> "invalid_action_metadata"
        selector != null && !isUsableSelector(selector) -> "invalid_semantic_selector"
        anchor != null && !isUsableAnchor(anchor) -> "invalid_visual_anchor"
        !isValidCheckpoint(checkpoint) -> "invalid_checkpoint"
        !isValidEvidence(evidence) -> "invalid_evidence_reference"
        else -> null
    }

    fun isValidPersistedActionMetadata(action: TrajectoryAction): Boolean =
        action.toolName.length in 1..MAX_TOOL_NAME_LENGTH &&
            action.safetyLabel.length <= MAX_RETAINED_SEMANTIC_LENGTH &&
            action.description.length <= MAX_RETAINED_SEMANTIC_LENGTH &&
            isValidEvidence(action.preEvidence) && isValidEvidence(action.postEvidence)

    fun isValidCompileMetadata(prompt: String, appName: String?, profileId: String): Boolean =
        prompt.isNotBlank() && prompt.length <= 200 && (appName == null || appName.length <= 128) && profileId.length <= 128

    fun isValidEvidence(evidence: TrajectoryEvidenceRef?): Boolean = evidence == null ||
        opaqueReference.matches(evidence.reference) && evidence.reference.startsWith("${evidence.kind.scheme}://")

    fun isValidCheckpoint(checkpoint: StepCheckpoint?): Boolean {
        if (checkpoint == null) return true
        return (checkpoint.expectedPackage == null || packageName.matches(checkpoint.expectedPackage)) &&
            (checkpoint.perceptualHash == null || hash.matches(checkpoint.perceptualHash)) &&
            checkpoint.maximumHammingDistance in 0..64 &&
            (checkpoint.requiredSelector == null || isUsableSelector(checkpoint.requiredSelector)) &&
            (checkpoint.forbiddenSelector == null || isUsableSelector(checkpoint.forbiddenSelector))
    }

    fun isUsableSelector(selector: SemanticSelector): Boolean {
        val fields = listOf(
            selector.resourceId, selector.contentDescription, selector.text, selector.className, selector.packageName
        )
        return fields.none { it != null && (it.isBlank() || it.length > 128) } &&
            (fields.any { !it.isNullOrBlank() } || selector.structuralPath.isNotEmpty()) &&
            selector.structuralPath.size <= 32 && selector.structuralPath.all { it in 0..10_000 }
    }

    fun isUsableAnchor(anchor: VisualAnchorSpec): Boolean {
        val region = anchor.searchRegion
        return anchorName.matches(anchor.assetName) &&
            region.left.isFinite() && region.top.isFinite() && region.right.isFinite() && region.bottom.isFinite() &&
            region.left >= 0f && region.top >= 0f && region.right <= 1f && region.bottom <= 1f &&
            region.left < region.right && region.top < region.bottom &&
            anchor.tapOffsetX.isFinite() && anchor.tapOffsetY.isFinite() &&
            anchor.tapOffsetX in 0f..1f && anchor.tapOffsetY in 0f..1f &&
            anchor.minimumConfidence.isFinite() && anchor.minimumConfidence > 0f && anchor.minimumConfidence <= 1f &&
            anchor.scaleVariants.isNotEmpty() && anchor.scaleVariants.size <= 8 &&
            anchor.scaleVariants.all { it.isFinite() && it > 0f }
    }
}

private const val MAX_RETAINED_SEMANTIC_LENGTH = 200
private const val MAX_TRANSIENT_SEMANTIC_LENGTH = 4096
private const val MAX_TOOL_NAME_LENGTH = 32
private const val MAX_PARAM_DEPTH = 8
private const val MAX_PARAM_CONTAINER_ENTRIES = 64
private const val MAX_PARAM_STRING_LENGTH = 256
private const val MAX_PARAM_KEY_LENGTH = 128
private const val MAX_PARAM_NODES = 128
private const val MAX_PARAM_SERIALIZED_BYTES = 1024

private val sensitiveParameterKey = Regex("token|secret|password|clipboard|authorization|api[_-]?key|private[_-]?key", RegexOption.IGNORE_CASE)
private val rawEvidenceParameterKey = Regex("screenshot|image|tree|accessibility", RegexOption.IGNORE_CASE)
internal sealed interface TrajectoryParamsSanitization {
    data class Safe(val params: Map<String, Any?>) : TrajectoryParamsSanitization
    data object Unsafe : TrajectoryParamsSanitization
}

internal fun normalizeToolParamAliases(toolName: String, params: Map<String, Any?>): Map<String, Any?> {
    if (toolName != "system_key") return params
    val key = params["key"] as? String ?: return params
    val normalized = when (key.trim().lowercase()) {
        "recent", "recents", "recent-apps", "recent apps" -> "recent_apps"
        "volumeup", "volume-up", "volume up" -> "volume_up"
        "volumedown", "volume-down", "volume down" -> "volume_down"
        else -> key.trim().lowercase()
    }
    return params + ("key" to normalized)
}

internal fun sanitizeTrajectoryParams(toolName: String, params: Map<String, Any?>): TrajectoryParamsSanitization {
    if (params.size > MAX_PARAM_CONTAINER_ENTRIES) return TrajectoryParamsSanitization.Unsafe
    return sanitizeMap(toolName, params, 0, IdentityHashMap(), SanitizationBudget())?.let(TrajectoryParamsSanitization::Safe)
        ?: TrajectoryParamsSanitization.Unsafe
}

internal fun projectTrajectoryParams(toolName: String, params: Map<String, Any?>): Map<String, Any?> =
    if (toolName == "finish") emptyMap() else params

private class SanitizationBudget {
    private var nodes = 0
    private var bytes = 0

    fun consume(nodeCount: Int, byteCount: Int): Boolean {
        nodes += nodeCount
        bytes += byteCount
        return nodes <= MAX_PARAM_NODES && bytes <= MAX_PARAM_SERIALIZED_BYTES
    }
}

private fun sanitizeMap(
    toolName: String,
    values: Map<*, *>,
    depth: Int,
    activeContainers: IdentityHashMap<Any, Unit>,
    budget: SanitizationBudget
): Map<String, Any?>? {
    if (depth > MAX_PARAM_DEPTH || values.size > MAX_PARAM_CONTAINER_ENTRIES || activeContainers.put(values, Unit) != null ||
        !budget.consume(1, 0)
    ) return null
    return try {
        val sanitized = linkedMapOf<String, Any?>()
        for ((key, value) in values) {
            val stringKey = key as? String ?: return null
            if (stringKey.length > MAX_PARAM_KEY_LENGTH || !budget.consume(1, stringKey.length)) return null
            if (rawEvidenceParameterKey.containsMatchIn(stringKey)) return null
            if (sensitiveParameterKey.containsMatchIn(stringKey) && !(toolName == "system_key" && stringKey == "key")) continue
            when (val result = sanitizeTrajectoryValue(toolName, stringKey, value, depth + 1, activeContainers, budget)) {
                is JsonValueSanitization.Safe -> sanitized[stringKey] = result.value
                JsonValueSanitization.Unsafe -> return null
            }
        }
        sanitized
    } finally {
        activeContainers.remove(values)
    }
}

private fun sanitizeTrajectoryList(
    toolName: String,
    values: List<*>,
    depth: Int,
    activeContainers: IdentityHashMap<Any, Unit>,
    budget: SanitizationBudget
): List<Any?>? {
    if (depth > MAX_PARAM_DEPTH || values.size > MAX_PARAM_CONTAINER_ENTRIES || activeContainers.put(values, Unit) != null ||
        !budget.consume(1, 0)
    ) return null
    return try {
        values.map { value ->
            when (val result = sanitizeTrajectoryValue(toolName, null, value, depth + 1, activeContainers, budget)) {
                is JsonValueSanitization.Safe -> result.value
                JsonValueSanitization.Unsafe -> return null
            }
        }
    } finally {
        activeContainers.remove(values)
    }
}

private sealed interface JsonValueSanitization {
    data class Safe(val value: Any?) : JsonValueSanitization
    data object Unsafe : JsonValueSanitization
}

private fun sanitizeTrajectoryValue(
    toolName: String,
    parameterKey: String?,
    value: Any?,
    depth: Int,
    activeContainers: IdentityHashMap<Any, Unit>,
    budget: SanitizationBudget
): JsonValueSanitization = when (value) {
    null -> if (budget.consume(1, 4)) JsonValueSanitization.Safe(null) else JsonValueSanitization.Unsafe
    is String -> if (budget.consume(1, value.length) && isSafeParameterString(toolName, parameterKey, value)) JsonValueSanitization.Safe(value) else JsonValueSanitization.Unsafe
    is Boolean, is Byte, is Short, is Int, is Long -> if (budget.consume(1, 8)) JsonValueSanitization.Safe(value) else JsonValueSanitization.Unsafe
    is Float -> if (budget.consume(1, 8) && value.isFinite()) JsonValueSanitization.Safe(value) else JsonValueSanitization.Unsafe
    is Double -> if (budget.consume(1, 8) && value.isFinite()) JsonValueSanitization.Safe(value) else JsonValueSanitization.Unsafe
    is Map<*, *> -> sanitizeMap(toolName, value, depth, activeContainers, budget)?.let(JsonValueSanitization::Safe)
        ?: JsonValueSanitization.Unsafe
    is List<*> -> sanitizeTrajectoryList(toolName, value, depth, activeContainers, budget)?.let(JsonValueSanitization::Safe)
        ?: JsonValueSanitization.Unsafe
    else -> JsonValueSanitization.Unsafe
}

private fun isSafeParameterString(toolName: String, parameterKey: String?, value: String): Boolean {
    if (value.length > MAX_PARAM_STRING_LENGTH) return false
    if (isClosedSchemaStringParameter(toolName, parameterKey) || (toolName == "finish" && parameterKey == "summary")) return true
    val trimmed = value.trim()
    if (trimmed.startsWith("{") || trimmed.startsWith("[") || trimmed.startsWith("<") ||
        trimmed.startsWith("data:", ignoreCase = true)
    ) return false
    return true
}

private fun isClosedSchemaStringParameter(toolName: String, parameterKey: String?): Boolean =
    (toolName == "open_app" && parameterKey == "package_name") ||
        (toolName == "system_key" && parameterKey == "key")

internal fun validateToolParams(toolName: String, params: Map<String, Any?>): Boolean {
    val keys = params.keys
    return when (toolName) {
        "open_app" -> keys.all { it in setOf("package_name", "verify_foreground", "check_launch_dialog", "force_reopen", "wait_after") } &&
            packageName(params["package_name"]) && optionalBoolean(params, "verify_foreground") &&
            optionalBoolean(params, "check_launch_dialog") && optionalBoolean(params, "force_reopen") && optionalWaitAfter(params)
        "system_key" -> keys.all { it in setOf("key", "wait_after") } && systemKey(params["key"]) && optionalWaitAfter(params)
        "tap" -> keys.all { it in setOf("x", "y", "duration_ms", "wait_after") } &&
            coordinate(params["x"]) && coordinate(params["y"]) && optionalDuration(params, "duration_ms", 0, 10_000) && optionalWaitAfter(params)
        "swipe" -> keys.all { it in setOf("start_x", "start_y", "end_x", "end_y", "duration_ms", "wait_after") } &&
            listOf("start_x", "start_y", "end_x", "end_y").all { coordinate(params[it]) } &&
            optionalDuration(params, "duration_ms", 0, 10_000) && optionalWaitAfter(params)
        "drag" -> keys.all { it in setOf("start_x", "start_y", "end_x", "end_y", "hold_ms", "duration_ms", "wait_after") } &&
            listOf("start_x", "start_y", "end_x", "end_y").all { coordinate(params[it]) } &&
            optionalDuration(params, "hold_ms", 80, 2_000) && optionalDuration(params, "duration_ms", 120, 3_000) && optionalWaitAfter(params)
        "long_press" -> keys.all { it in setOf("x", "y", "duration_ms", "wait_after") } &&
            coordinate(params["x"]) && coordinate(params["y"]) && optionalDuration(params, "duration_ms", 0, 10_000) && optionalWaitAfter(params)
        "wait" -> keys == setOf("duration_ms") && integerInRange(params["duration_ms"], 0, 30_000)
        "take_screenshot", "get_screen_info" -> params.isEmpty()
        "finish" -> keys == setOf("summary") && boundedString(params["summary"])
        else -> false
    }
}

private fun packageName(value: Any?): Boolean = value is String && Regex("^[A-Za-z][A-Za-z0-9_.]{0,127}$").matches(value)
private fun coordinate(value: Any?): Boolean = integerInRange(value, 0, 100_000)
private fun optionalBoolean(params: Map<String, Any?>, key: String): Boolean = !params.containsKey(key) || params[key] is Boolean
private fun optionalWaitAfter(params: Map<String, Any?>): Boolean = optionalDuration(params, "wait_after", 0, 10_000)
private fun optionalDuration(params: Map<String, Any?>, key: String, min: Int, max: Int): Boolean =
    !params.containsKey(key) || integerInRange(params[key], min, max)
private fun integerInRange(value: Any?, min: Int, max: Int): Boolean = value is Int && value in min..max
private fun boundedString(value: Any?): Boolean = value is String && value.length <= MAX_PARAM_STRING_LENGTH
private fun systemKey(value: Any?): Boolean = value is String && value in setOf(
    "back", "home", "recent_apps", "enter", "power", "volume_up", "volume_down", "notifications",
    "collapse_notifications", "lock_screen", "unlock_screen"
)
