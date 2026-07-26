package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import com.apk.claw.android.workflow.VisualAnchorSpec
import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.JsonPrimitive
import com.google.gson.Strictness
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import java.io.StringReader
import java.util.UUID
import java.math.BigDecimal

object RpaWorkflowParser {
    data class ParseResult(
        val workflow: RpaWorkflow,
        val sync: Boolean = false
    )

    private val placeholderRegex = Regex("\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}")
    private val legacyStepControlKeys = setOf(
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
    private val hybridStepControlKeys = legacyStepControlKeys + setOf(
        "resolverPolicy",
        "allowedResolvers",
        "validatedResolvers",
        "semanticSelector",
        "visualAnchor",
        "preCheckpoint",
        "postCheckpoint"
    )

    private val hybridActions = setOf(
        "open_app",
        "wait_stable",
        "assert_package",
        "assert_semantic",
        "assert_frame",
        "tap_semantic",
        "tap_anchor",
        "tap_normalized",
        "swipe_normalized",
        "drag_normalized",
        "long_press_anchor",
        "back",
        "home",
        "wait",
        "finish"
    )

    fun parseRunRequest(rawJson: String): ParseResult = parseRunRequest(parseRawRoot(rawJson))

    fun parseRunRequest(root: JsonObject): ParseResult {
        val workflowRoot = root.objectValue("workflow") ?: root
        val hybrid = workflowRoot.requestsHybridMode()
        if (hybrid) validateHybridJson(root)
        val requestParams = if (hybrid) {
            root.strictOptionalObject("params")?.strictStringMap("params").orEmpty()
        } else {
            root.objectValue("params")?.stringMapValue().orEmpty()
        }
        val workflow = parseWorkflow(workflowRoot, requestParams)
        val sync = if (hybrid) root.strictOptionalBoolean("sync") ?: false else root.booleanValue("sync", false)
        return ParseResult(workflow, sync)
    }

    fun parseWorkflow(rawJson: String, requestParams: Map<String, String> = emptyMap()): RpaWorkflow =
        parseWorkflow(parseRawRoot(rawJson), requestParams)

    fun parseWorkflow(root: JsonObject, requestParams: Map<String, String> = emptyMap()): RpaWorkflow {
        val hybrid = root.requestsHybridMode()
        if (hybrid) {
            validateHybridJson(root)
            validateHybridStringMap(requestParams, "request params")
            listOf(
                "workflowId",
                "workflow_id",
                "id",
                "name",
                "templateId",
                "targetProfileId",
                "templateStatus",
                "validationProgress",
                "promotionIneligibleReason"
            )
                .forEach { root.strictOptionalString(it) }
        }
        val workflowParams = if (hybrid) {
            root.strictOptionalObject("params")?.strictStringMap("params").orEmpty()
        } else {
            root.objectValue("params")?.stringMapValue().orEmpty()
        }
        val params = workflowParams + requestParams
        val executionMode = if (hybrid) root.strictRequiredString("executionMode") else "rpa"
        val schemaVersion = if (hybrid) root.strictOptionalInt("schemaVersion") ?: 1 else 1
        val templateId = if (hybrid) root.strictOptionalString("templateId").orEmpty() else ""
        val templateRevision = if (hybrid) root.strictOptionalInt("templateRevision") ?: 0 else 0
        val targetProfileId = if (hybrid) root.strictOptionalString("targetProfileId").orEmpty() else ""
        val templateStatus = if (hybrid) root.strictOptionalString("templateStatus").orEmpty() else ""
        val validationProgress = if (hybrid) root.strictOptionalString("validationProgress").orEmpty() else ""
        val promotionEligible = if (hybrid) root.strictOptionalBoolean("promotionEligible") ?: false else false
        val promotionIneligibleReason = if (hybrid) {
            root.strictOptionalString("promotionIneligibleReason").orEmpty()
        } else {
            ""
        }
        if (hybrid) {
            if (root.has("schemaVersion") && schemaVersion != 2) {
                throw IllegalArgumentException("schemaVersion must be 2")
            }
            if (root.has("templateId") && !isSafeIdentifier(templateId)) {
                throw IllegalArgumentException("templateId is invalid")
            }
            if (root.has("templateRevision") && templateRevision <= 0) {
                throw IllegalArgumentException("templateRevision is invalid")
            }
            if (root.has("targetProfileId") && !isSafeIdentifier(targetProfileId)) {
                throw IllegalArgumentException("targetProfileId is invalid")
            }
        }
        val stepsJson = (if (hybrid) root.strictOptionalArray("steps") else root.arrayValue("steps"))
            ?: throw IllegalArgumentException("RPA workflow must include steps")
        if (hybrid && stepsJson.size() > MAX_HYBRID_STEPS) {
            throw IllegalArgumentException("RPA workflow has too many steps")
        }
        val id = root.stringAny("workflowId", "workflow_id", "id")
            .ifBlank { "rpa_workflow_${UUID.randomUUID()}" }
        val name = root.stringValue("name", id)
        val steps = stepsJson.mapIndexed { index, element ->
            if (hybrid && !element.isJsonObject) throw IllegalArgumentException("steps[$index] must be an object")
            parseStep(element.asJsonObject, index, params, hybrid)
        }
        return RpaWorkflow(
            id = id,
            name = name,
            version = if (hybrid) root.strictOptionalInt("version") ?: 1 else root.intValue("version", 1),
            steps = steps,
            params = params,
            maxDurationMs = if (hybrid) {
                root.strictLongAny("maxDurationMs", "max_duration_ms", default = 300_000L)
                    .requireRange("maxDurationMs", 1_000L, 1_800_000L)
            } else {
                root.longAny("maxDurationMs", "max_duration_ms", default = 300_000L)
                    .coerceIn(1_000L, 1_800_000L)
            },
            schemaVersion = schemaVersion,
            executionMode = executionMode,
            templateId = templateId,
            templateRevision = templateRevision,
            targetProfileId = targetProfileId,
            templateStatus = templateStatus,
            validationProgress = validationProgress,
            promotionEligible = promotionEligible,
            promotionIneligibleReason = promotionIneligibleReason
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
        if (workflow.executionMode !in setOf("rpa", "hybrid_rpa")) {
            errors += "RPA workflow has unsupported executionMode: ${workflow.executionMode}"
        }
        if (workflow.executionMode == "hybrid_rpa") {
            if (workflow.schemaVersion != 2) errors += "Hybrid workflow schemaVersion must be 2"
            if (!isSafeIdentifier(workflow.templateId)) errors += "Hybrid workflow templateId is invalid"
            if (workflow.templateRevision <= 0) errors += "Hybrid workflow templateRevision must be positive"
            if (!isSafeIdentifier(workflow.targetProfileId)) errors += "Hybrid workflow targetProfileId is invalid"
        }
        val seenStepIds = mutableSetOf<String>()
        workflow.steps.forEachIndexed { index, step ->
            val action = RpaActionNormalizer.normalize(step.action)
            if (action.isBlank()) {
                errors += "Step ${index + 1} is missing action"
            } else if (workflow.executionMode == "hybrid_rpa" && action !in hybridActions) {
                errors += "Step ${index + 1} has unsupported hybrid action: ${step.action}"
            } else if (workflow.executionMode != "hybrid_rpa" && !RpaActionNormalizer.isSupported(action)) {
                errors += "Step ${index + 1} has unsupported action: ${step.action}"
            }
            unresolvedPlaceholders(step.params).forEach { name ->
                errors += "Step ${index + 1} has unresolved param: $name"
            }
            if (workflow.executionMode == "hybrid_rpa") {
                if (containsInvalidHybridNumber(step.params)) {
                    errors += "Step ${index + 1} has invalid numeric param"
                }
                if (!isSafeIdentifier(step.id)) errors += "Step ${index + 1} id is invalid"
                if (!seenStepIds.add(step.id)) errors += "Step ${index + 1} has duplicate id: ${step.id}"
                validateHybridStep(step, index, errors)
            }
        }
        return errors
    }

    private fun parseStep(root: JsonObject, index: Int, params: Map<String, String>, hybrid: Boolean): RpaStep {
        if (hybrid) {
            listOf("id", "stepId", "action", "type", "toolName", "description")
                .forEach { root.strictOptionalString(it) }
        }
        val action = root.stringAny("action", "type", "toolName")
        val explicitParams = (if (hybrid) root.strictOptionalObject("params") else root.objectValue("params"))
            ?.let { jsonToMap(it, params) }
            ?: collectInlineParams(root, params, hybrid)
        val guard = (if (hybrid) root.strictOptionalObject("guard") else root.objectValue("guard"))
            ?.let { parseGuard(it, params, hybrid) } ?: RpaStepGuard()
        val resolverPolicy = if (hybrid) {
            root.strictOptionalEnum<ResolverPolicy>("resolverPolicy") ?: ResolverPolicy.DIRECT
        } else ResolverPolicy.DIRECT
        val allowedResolvers = if (hybrid) {
            root.strictOptionalEnumSet<ResolverKind>("allowedResolvers") ?: emptySet()
        } else emptySet()
        val validatedResolvers = if (hybrid) {
            root.strictOptionalEnumSet<ResolverKind>("validatedResolvers") ?: emptySet()
        } else emptySet()
        val semanticSelector = if (hybrid) root.strictOptionalObject("semanticSelector")?.let(::parseSemanticSelector) else null
        val visualAnchor = if (hybrid) root.strictOptionalObject("visualAnchor")?.let(::parseVisualAnchor) else null
        val preCheckpoint = if (hybrid) root.strictOptionalObject("preCheckpoint")?.let(::parseCheckpoint) else null
        val postCheckpoint = if (hybrid) root.strictOptionalObject("postCheckpoint")?.let(::parseCheckpoint) else null
        return RpaStep(
            id = root.stringAny("id", "stepId").ifBlank { "step_${index + 1}" },
            action = RpaActionNormalizer.normalize(action),
            params = explicitParams,
            description = resolveString(root.stringValue("description", action), params),
            waitAfterMs = if (hybrid) root.strictLongAny("waitAfterMs", "wait_after_ms", "waitAfter", "wait_after", default = 0L)
                .requireRange("waitAfterMs", 0L, 30_000L) else root.longAny("waitAfterMs", "wait_after_ms", "waitAfter", "wait_after", default = 0L).coerceIn(0L, 30_000L),
            timeoutMs = if (hybrid) root.strictLongAny("timeoutMs", "timeout_ms", default = 5_000L)
                .requireRange("timeoutMs", 100L, 120_000L) else root.longAny("timeoutMs", "timeout_ms", default = 5_000L).coerceIn(100L, 120_000L),
            maxRetries = if (hybrid) root.strictIntAny("maxRetries", "max_retries", default = 0)
                .requireRange("maxRetries", 0, 10) else root.intAny("maxRetries", "max_retries", default = 0).coerceIn(0, 10),
            retryDelayMs = if (hybrid) root.strictLongAny("retryDelayMs", "retry_delay_ms", default = 300L)
                .requireRange("retryDelayMs", 0L, 30_000L) else root.longAny("retryDelayMs", "retry_delay_ms", default = 300L).coerceIn(0L, 30_000L),
            guard = guard,
            resolverPolicy = resolverPolicy,
            allowedResolvers = allowedResolvers,
            validatedResolvers = validatedResolvers,
            semanticSelector = semanticSelector,
            visualAnchor = visualAnchor,
            preCheckpoint = preCheckpoint,
            postCheckpoint = postCheckpoint,
            resolverPolicyExplicit = hybrid && root.has("resolverPolicy")
        )
    }

    private fun validateHybridStep(step: RpaStep, index: Int, errors: MutableList<String>) {
        val label = "Step ${index + 1}"
        if (!step.resolverPolicyExplicit) {
            errors += "$label must declare resolverPolicy explicitly"
        }
        if (step.allowedResolvers.isEmpty()) {
            errors += "$label must declare resolverPolicy and non-empty allowedResolvers"
        }
        if (step.validatedResolvers.isEmpty()) {
            errors += "$label must declare non-empty validatedResolvers"
        }
        if (!step.allowedResolvers.containsAll(step.validatedResolvers)) {
            errors += "$label validatedResolvers must be a subset of allowedResolvers"
        }
        if (ResolverKind.EPHEMERAL_REF in step.allowedResolvers) {
            errors += "$label cannot authorize EPHEMERAL_REF in production"
        }
        when (step.resolverPolicy) {
            ResolverPolicy.DIRECT -> {
                if (step.allowedResolvers != setOf(ResolverKind.DIRECT) ||
                    step.validatedResolvers != setOf(ResolverKind.DIRECT)
                ) {
                    errors += "$label DIRECT resolverPolicy requires allowed and validated DIRECT only"
                }
                if (DirectAction.fromWireName(step.action) == null) {
                    errors += "$label DIRECT resolverPolicy has unsupported action: ${step.action}"
                }
            }
            ResolverPolicy.TREE_PREFERRED -> {
                if (step.allowedResolvers.none { it in TREE_RESOLVERS }) {
                    errors += "$label TREE_PREFERRED requires a declared semantic resolver"
                }
            }
            ResolverPolicy.VISION_REQUIRED -> {
                if (ResolverKind.VISUAL_ANCHOR !in step.allowedResolvers) {
                    errors += "$label VISION_REQUIRED requires VISUAL_ANCHOR"
                }
            }
            ResolverPolicy.DUAL_CONFIRM -> {
                if (ResolverKind.VISUAL_ANCHOR !in step.allowedResolvers ||
                    step.allowedResolvers.none { it in TREE_RESOLVERS }
                ) {
                    errors += "$label DUAL_CONFIRM requires semantic and visual resolvers"
                }
            }
        }
        val selector = step.semanticSelector
        if (step.allowedResolvers.any { it in TREE_RESOLVERS } && selector == null) {
            errors += "$label semantic resolver requires semanticSelector"
        }
        if (ResolverKind.RESOURCE_ID in step.allowedResolvers && selector?.resourceId.isNullOrBlank()) {
            errors += "$label RESOURCE_ID requires semanticSelector.resourceId"
        }
        if (ResolverKind.CONTENT_DESCRIPTION in step.allowedResolvers && selector?.contentDescription.isNullOrBlank()) {
            errors += "$label CONTENT_DESCRIPTION requires semanticSelector.contentDescription"
        }
        if (ResolverKind.TEXT_CLASS in step.allowedResolvers && selector?.text.isNullOrBlank()) {
            errors += "$label TEXT_CLASS requires semanticSelector.text"
        }
        if (ResolverKind.STRUCTURAL in step.allowedResolvers && selector?.structuralPath.isNullOrEmpty()) {
            errors += "$label STRUCTURAL requires semanticSelector.structuralPath"
        }
        if (ResolverKind.VISUAL_ANCHOR in step.allowedResolvers && step.visualAnchor == null) {
            errors += "$label VISUAL_ANCHOR requires visualAnchor"
        }
        if (ResolverKind.NORMALIZED_COORDINATE in step.allowedResolvers &&
            step.preCheckpoint?.perceptualHash.isNullOrBlank()
        ) {
            errors += "$label NORMALIZED_COORDINATE requires preCheckpoint.perceptualHash"
        }
        if (ResolverKind.NORMALIZED_COORDINATE in step.allowedResolvers &&
            (step.preCheckpoint?.expectedWindowId == null ||
                step.preCheckpoint.expectedDisplayTransform == null)
        ) {
            errors += "$label NORMALIZED_COORDINATE requires persisted window and display transform"
        }
    }

    private fun parseSemanticSelector(root: JsonObject): SemanticSelector {
        val structuralPath = root.strictOptionalIntList("structuralPath") ?: emptyList()
        if (structuralPath.size > MAX_STRUCTURAL_PATH || structuralPath.any { it !in 0..MAX_STRUCTURAL_INDEX }) {
            throw IllegalArgumentException("semanticSelector.structuralPath is invalid")
        }
        return SemanticSelector(
            resourceId = root.strictOptionalString("resourceId")?.takeIf { it.isNotBlank() },
            contentDescription = root.strictOptionalString("contentDescription")?.takeIf { it.isNotBlank() },
            text = root.strictOptionalString("text")?.takeIf { it.isNotBlank() },
            className = root.strictOptionalString("className")?.takeIf { it.isNotBlank() },
            packageName = root.strictOptionalString("packageName")?.takeIf { it.isNotBlank() },
            structuralPath = structuralPath
        ).also { selector ->
            val values = listOfNotNull(
                selector.resourceId,
                selector.contentDescription,
                selector.text,
                selector.className,
                selector.packageName
            )
            if (values.any { it.length > MAX_HYBRID_STRING }) {
                throw IllegalArgumentException("semanticSelector value is too long")
            }
            if (values.isEmpty() && structuralPath.isEmpty()) {
                throw IllegalArgumentException("semanticSelector is empty")
            }
        }
    }

    private fun parseVisualAnchor(root: JsonObject): VisualAnchorSpec {
        val assetName = root.strictRequiredString("assetName")
        if (!SAFE_ASSET_NAME.matches(assetName) || assetName == "." || assetName == "..") {
            throw IllegalArgumentException("visualAnchor.assetName is invalid")
        }
        val regionRoot = root.strictRequiredObject("searchRegion")
        val region = NormalizedRect(
            left = regionRoot.strictRequiredFloat("left"),
            top = regionRoot.strictRequiredFloat("top"),
            right = regionRoot.strictRequiredFloat("right"),
            bottom = regionRoot.strictRequiredFloat("bottom")
        )
        if (region.left !in 0f..1f || region.top !in 0f..1f ||
            region.right !in 0f..1f || region.bottom !in 0f..1f ||
            region.right <= region.left || region.bottom <= region.top
        ) {
            throw IllegalArgumentException("visualAnchor.searchRegion is invalid")
        }
        val tapOffsetX = root.strictRequiredFloat("tapOffsetX")
        val tapOffsetY = root.strictRequiredFloat("tapOffsetY")
        val minimumConfidence = root.strictOptionalFloat("minimumConfidence") ?: 0.88f
        val scaleVariants = root.strictOptionalFloatList("scaleVariants") ?: listOf(0.90f, 1.00f, 1.10f)
        if (tapOffsetX !in 0f..1f || tapOffsetY !in 0f..1f ||
            minimumConfidence !in 0f..1f || scaleVariants.isEmpty() ||
            scaleVariants.size > 9 || scaleVariants.any { it !in 0.75f..1.25f }
        ) {
            throw IllegalArgumentException("visualAnchor numeric field is invalid")
        }
        return VisualAnchorSpec(
            assetName = assetName,
            searchRegion = region,
            tapOffsetX = tapOffsetX,
            tapOffsetY = tapOffsetY,
            minimumConfidence = minimumConfidence,
            scaleVariants = scaleVariants
        )
    }

    private fun parseCheckpoint(root: JsonObject): StepCheckpoint = StepCheckpoint(
        expectedPackage = root.strictOptionalString("expectedPackage")?.takeIf { it.isNotBlank() },
        requiredSelector = root.strictOptionalObject("requiredSelector")?.let(::parseSemanticSelector),
        forbiddenSelector = root.strictOptionalObject("forbiddenSelector")?.let(::parseSemanticSelector),
        perceptualHash = root.strictOptionalString("perceptualHash")?.takeIf { it.isNotBlank() },
        maximumHammingDistance = root.strictOptionalInt("maximumHammingDistance") ?: 8,
        expectedWindowId = root.strictOptionalInt("expectedWindowId"),
        expectedDisplayTransform = root.strictOptionalObject("expectedDisplayTransform")
            ?.let(::parseDisplayTransformCheckpoint)
    ).also {
        if (it.maximumHammingDistance !in 0..MAX_FINGERPRINT_DISTANCE) {
            throw IllegalArgumentException("checkpoint.maximumHammingDistance is invalid")
        }
        if (it.perceptualHash != null && !PerceptualFingerprint.isValid(it.perceptualHash)) {
            throw IllegalArgumentException("checkpoint.perceptualHash is invalid")
        }
        if (it.expectedWindowId != null && it.expectedWindowId !in 0..MAX_WINDOW_ID) {
            throw IllegalArgumentException("checkpoint.expectedWindowId is invalid")
        }
    }

    private fun parseDisplayTransformCheckpoint(root: JsonObject): DisplayTransformCheckpoint {
        val checkpoint = DisplayTransformCheckpoint(
            displayId = root.strictRequiredInt("displayId"),
            widthPx = root.strictRequiredInt("widthPx"),
            heightPx = root.strictRequiredInt("heightPx"),
            screenshotWidthPx = root.strictRequiredInt("screenshotWidthPx"),
            screenshotHeightPx = root.strictRequiredInt("screenshotHeightPx"),
            rotation = root.strictRequiredInt("rotation"),
            densityDpi = root.strictRequiredInt("densityDpi"),
            insetLeft = root.strictRequiredInt("insetLeft"),
            insetTop = root.strictRequiredInt("insetTop"),
            insetRight = root.strictRequiredInt("insetRight"),
            insetBottom = root.strictRequiredInt("insetBottom")
        )
        if (checkpoint.displayId !in 0..MAX_DISPLAY_ID ||
            checkpoint.widthPx !in 1..MAX_DISPLAY_DIMENSION ||
            checkpoint.heightPx !in 1..MAX_DISPLAY_DIMENSION ||
            checkpoint.screenshotWidthPx !in 1..MAX_DISPLAY_DIMENSION ||
            checkpoint.screenshotHeightPx !in 1..MAX_DISPLAY_DIMENSION ||
            checkpoint.rotation !in 0..3 || checkpoint.densityDpi !in 1..MAX_DENSITY_DPI ||
            listOf(checkpoint.insetLeft, checkpoint.insetTop, checkpoint.insetRight, checkpoint.insetBottom)
                .any { it !in 0..MAX_DISPLAY_DIMENSION } ||
            checkpoint.insetLeft + checkpoint.insetRight >= checkpoint.widthPx ||
            checkpoint.insetTop + checkpoint.insetBottom >= checkpoint.heightPx
        ) {
            throw IllegalArgumentException("checkpoint.expectedDisplayTransform is invalid")
        }
        return checkpoint
    }

    private fun parseGuard(root: JsonObject, params: Map<String, String>, hybrid: Boolean): RpaStepGuard {
        if (hybrid) {
            GUARD_STRING_FIELDS.forEach { name -> root.strictOptionalString(name) }
            GUARD_LIST_FIELDS.forEach { name -> root.strictOptionalStringList(name) }
        }
        return RpaStepGuard(
            expectedPackage = root.stringAny("expectedPackage", "expected_package")
                .ifBlank { null }
                ?.let { resolveString(it, params) },
            requireText = (if (hybrid) root.strictStringListAny("requireText", "require_text", "requiredText", "required_text")
                else root.stringListAny("requireText", "require_text", "requiredText", "required_text"))
                .map { resolveString(it, params) },
            forbidText = (if (hybrid) root.strictStringListAny("forbidText", "forbid_text", "forbiddenText", "forbidden_text")
                else root.stringListAny("forbidText", "forbid_text", "forbiddenText", "forbidden_text"))
                .map { resolveString(it, params) }
        )
    }

    private fun collectInlineParams(
        root: JsonObject,
        params: Map<String, String>,
        hybrid: Boolean
    ): Map<String, Any> {
        val controlKeys = if (hybrid) hybridStepControlKeys else legacyStepControlKeys
        return root.entrySet()
            .filter { (key, _) -> key !in controlKeys }
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

    private fun JsonObject.strictOptionalArray(name: String): JsonArray? {
        val value = get(name) ?: return null
        if (!value.isJsonArray) throw IllegalArgumentException("$name must be an array")
        return value.asJsonArray
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

    private fun JsonObject.strictOptionalBoolean(name: String): Boolean? {
        val value = get(name) ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isBoolean) {
            throw IllegalArgumentException("$name must be a boolean")
        }
        return value.asBoolean
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

    private fun JsonObject.strictStringListAny(vararg names: String): List<String> {
        names.forEach { name -> strictOptionalStringList(name) }
        return names.firstNotNullOfOrNull { name -> strictOptionalStringList(name) }.orEmpty()
    }

    private fun JsonObject.strictOptionalStringList(name: String): List<String>? {
        val value = get(name) ?: return null
        if (!value.isJsonArray) throw IllegalArgumentException("$name must be an array")
        if (value.asJsonArray.size() > MAX_HYBRID_LIST_ITEMS) {
            throw IllegalArgumentException("$name has too many values")
        }
        return value.asJsonArray.mapIndexed { index, item ->
            if (!item.isJsonPrimitive || !item.asJsonPrimitive.isString) {
                throw IllegalArgumentException("$name[$index] must be a string")
            }
            item.asString
        }
    }

    private fun JsonObject.strictOptionalObject(name: String): JsonObject? {
        val value = get(name) ?: return null
        if (!value.isJsonObject) throw IllegalArgumentException("$name must be an object")
        return value.asJsonObject
    }

    private fun JsonObject.strictRequiredObject(name: String): JsonObject =
        strictOptionalObject(name) ?: throw IllegalArgumentException("$name is required")

    private fun JsonObject.strictOptionalString(name: String): String? {
        val value = get(name) ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isString) {
            throw IllegalArgumentException("$name must be a string")
        }
        return value.asString
    }

    private fun JsonObject.strictRequiredString(name: String): String =
        strictOptionalString(name) ?: throw IllegalArgumentException("$name is required")

    private fun JsonObject.strictRequiredInt(name: String): Int =
        strictOptionalInt(name) ?: throw IllegalArgumentException("$name is required")

    private fun JsonObject.strictOptionalInt(name: String): Int? {
        val value = get(name) ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isNumber || !INTEGER_PATTERN.matches(value.asString)) {
            throw IllegalArgumentException("$name must be an integer")
        }
        return value.asString.toIntOrNull() ?: throw IllegalArgumentException("$name is out of range")
    }

    private fun JsonObject.strictOptionalLong(name: String): Long? {
        val value = get(name) ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isNumber || !INTEGER_PATTERN.matches(value.asString)) {
            throw IllegalArgumentException("$name must be an integer")
        }
        return value.asString.toLongOrNull() ?: throw IllegalArgumentException("$name is out of range")
    }

    private fun JsonObject.strictIntAny(vararg names: String, default: Int): Int {
        names.forEach { strictOptionalInt(it) }
        return names.firstNotNullOfOrNull { strictOptionalInt(it) } ?: default
    }

    private fun JsonObject.strictLongAny(vararg names: String, default: Long): Long {
        names.forEach { strictOptionalLong(it) }
        return names.firstNotNullOfOrNull { strictOptionalLong(it) } ?: default
    }

    private inline fun <reified T : Enum<T>> JsonObject.strictOptionalEnum(name: String): T? {
        val raw = strictOptionalString(name) ?: return null
        return enumValues<T>().firstOrNull { it.name == raw }
            ?: throw IllegalArgumentException("$name has invalid value: $raw")
    }

    private inline fun <reified T : Enum<T>> JsonObject.strictOptionalEnumSet(name: String): Set<T>? {
        val value = get(name) ?: return null
        if (!value.isJsonArray) throw IllegalArgumentException("$name must be an array")
        if (value.asJsonArray.size() > enumValues<T>().size) {
            throw IllegalArgumentException("$name has too many values")
        }
        val parsed = value.asJsonArray.map { item ->
            if (!item.isJsonPrimitive || !item.asJsonPrimitive.isString) {
                throw IllegalArgumentException("$name values must be strings")
            }
            val raw = item.asString
            enumValues<T>().firstOrNull { it.name == raw }
                ?: throw IllegalArgumentException("$name has invalid value: $raw")
        }
        if (parsed.toSet().size != parsed.size) throw IllegalArgumentException("$name contains duplicates")
        return parsed.toSet()
    }

    private fun JsonObject.strictOptionalIntList(name: String): List<Int>? {
        val value = get(name) ?: return null
        if (!value.isJsonArray) throw IllegalArgumentException("$name must be an array")
        return value.asJsonArray.mapIndexed { index, item ->
            if (!item.isJsonPrimitive || !item.asJsonPrimitive.isNumber || !INTEGER_PATTERN.matches(item.asString)) {
                throw IllegalArgumentException("$name[$index] must be an integer")
            }
            item.asString.toIntOrNull() ?: throw IllegalArgumentException("$name[$index] is out of range")
        }
    }

    private fun JsonObject.strictRequiredFloat(name: String): Float =
        strictOptionalFloat(name) ?: throw IllegalArgumentException("$name is required")

    private fun JsonObject.strictOptionalFloat(name: String): Float? {
        val value = get(name) ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isNumber) {
            throw IllegalArgumentException("$name must be a number")
        }
        return value.asString.toFloatOrNull()?.takeIf { it.isFinite() }
            ?: throw IllegalArgumentException("$name must be finite")
    }

    private fun JsonObject.strictOptionalFloatList(name: String): List<Float>? {
        val value = get(name) ?: return null
        if (!value.isJsonArray) throw IllegalArgumentException("$name must be an array")
        return value.asJsonArray.mapIndexed { index, item ->
            if (!item.isJsonPrimitive || !item.asJsonPrimitive.isNumber) {
                throw IllegalArgumentException("$name[$index] must be a number")
            }
            item.asString.toFloatOrNull()?.takeIf { it.isFinite() }
                ?: throw IllegalArgumentException("$name[$index] must be finite")
        }
    }

    private fun isSafeIdentifier(value: String): Boolean =
        SAFE_IDENTIFIER.matches(value) && value != "." && value != ".."

    private fun JsonObject.requestsHybridMode(): Boolean {
        val value = get("executionMode") ?: return false
        return value.isJsonPrimitive && value.asJsonPrimitive.isString && value.asString == "hybrid_rpa"
    }

    private fun JsonObject.strictStringMap(label: String): Map<String, String> {
        if (entrySet().size > MAX_HYBRID_MAP_ENTRIES) {
            throw IllegalArgumentException("$label has too many entries")
        }
        return entrySet().associate { (key, value) ->
            if (key.length > MAX_HYBRID_STRING || !value.isJsonPrimitive || !value.asJsonPrimitive.isString) {
                throw IllegalArgumentException("$label values must be bounded strings")
            }
            key to value.asString.also {
                if (it.length > MAX_HYBRID_PARAM_STRING) {
                    throw IllegalArgumentException("$label value is too long")
                }
            }
        }
    }

    private fun validateHybridStringMap(value: Map<String, String>, label: String) {
        if (value.size > MAX_HYBRID_MAP_ENTRIES || value.any {
                (key, item) -> key.length > MAX_HYBRID_STRING || item.length > MAX_HYBRID_PARAM_STRING
            }
        ) {
            throw IllegalArgumentException("$label is too large")
        }
    }

    private fun validateHybridJson(root: JsonElement) {
        var nodes = 0
        fun visit(value: JsonElement, depth: Int) {
            nodes++
            if (nodes > MAX_HYBRID_JSON_NODES) throw IllegalArgumentException("hybrid JSON has too many nodes")
            if (depth > MAX_HYBRID_NESTING_DEPTH) throw IllegalArgumentException("hybrid JSON is too deeply nested")
            when {
                value.isJsonObject -> {
                    val entries = value.asJsonObject.entrySet()
                    if (entries.size > MAX_HYBRID_MAP_ENTRIES) {
                        throw IllegalArgumentException("hybrid object has too many entries")
                    }
                    entries.forEach { (key, child) ->
                        if (key.length > MAX_HYBRID_STRING) throw IllegalArgumentException("hybrid key is too long")
                        visit(child, depth + 1)
                    }
                }
                value.isJsonArray -> {
                    if (value.asJsonArray.size() > MAX_HYBRID_LIST_ITEMS) {
                        throw IllegalArgumentException("hybrid array has too many values")
                    }
                    value.asJsonArray.forEach { visit(it, depth + 1) }
                }
                value.isJsonPrimitive && value.asJsonPrimitive.isString -> {
                    if (value.asString.length > MAX_HYBRID_PARAM_STRING) {
                        throw IllegalArgumentException("hybrid string is too long")
                    }
                }
                value.isJsonPrimitive && value.asJsonPrimitive.isNumber -> {
                    val numeric = runCatching { BigDecimal(value.asString) }.getOrNull()
                        ?: throw IllegalArgumentException("hybrid number is not finite")
                    if (numeric.abs() > MAX_HYBRID_NUMERIC_MAGNITUDE) {
                        throw IllegalArgumentException("hybrid number is out of range")
                    }
                }
            }
        }
        visit(root, 0)
    }

    private fun parseRawRoot(rawJson: String): JsonObject {
        val lenientRoot = try {
            JsonParser.parseString(rawJson)
        } catch (error: Exception) {
            throw IllegalArgumentException("invalid JSON", error)
        }
        if (!lenientRoot.isJsonObject) throw IllegalArgumentException("JSON root must be an object")
        val root = lenientRoot.asJsonObject
        val workflowRoot = root.objectValue("workflow") ?: root
        return if (workflowRoot.requestsHybridMode()) parseStrictHybridRoot(rawJson) else root
    }

    private fun parseStrictHybridRoot(rawJson: String): JsonObject {
        try {
            JsonReader(StringReader(rawJson)).use { reader ->
                reader.setStrictness(Strictness.STRICT)
                val root = readStrictJsonValue(reader, StrictJsonBudget(), 0)
                if (reader.peek() != JsonToken.END_DOCUMENT) {
                    throw IllegalArgumentException("hybrid JSON has trailing data")
                }
                if (!root.isJsonObject) throw IllegalArgumentException("hybrid JSON root must be an object")
                return root.asJsonObject
            }
        } catch (error: IllegalArgumentException) {
            throw error
        } catch (error: Exception) {
            throw IllegalArgumentException("hybrid JSON must use strict RFC syntax", error)
        }
    }

    private fun readStrictJsonValue(
        reader: JsonReader,
        budget: StrictJsonBudget,
        depth: Int
    ): JsonElement {
        budget.nodes++
        if (budget.nodes > MAX_HYBRID_JSON_NODES) throw IllegalArgumentException("hybrid JSON has too many nodes")
        if (depth > MAX_HYBRID_NESTING_DEPTH) throw IllegalArgumentException("hybrid JSON is too deeply nested")
        return when (reader.peek()) {
            JsonToken.BEGIN_OBJECT -> {
                reader.beginObject()
                val result = JsonObject()
                val names = mutableSetOf<String>()
                var entries = 0
                while (reader.hasNext()) {
                    entries++
                    if (entries > MAX_HYBRID_MAP_ENTRIES) {
                        throw IllegalArgumentException("hybrid object has too many entries")
                    }
                    val name = reader.nextName()
                    if (name.length > MAX_HYBRID_STRING) throw IllegalArgumentException("hybrid key is too long")
                    if (!names.add(name)) throw IllegalArgumentException("hybrid JSON contains a duplicate key")
                    result.add(name, readStrictJsonValue(reader, budget, depth + 1))
                }
                reader.endObject()
                result
            }
            JsonToken.BEGIN_ARRAY -> {
                reader.beginArray()
                val result = JsonArray()
                var items = 0
                while (reader.hasNext()) {
                    items++
                    if (items > MAX_HYBRID_LIST_ITEMS) {
                        throw IllegalArgumentException("hybrid array has too many values")
                    }
                    result.add(readStrictJsonValue(reader, budget, depth + 1))
                }
                reader.endArray()
                result
            }
            JsonToken.STRING -> JsonPrimitive(reader.nextString())
            JsonToken.NUMBER -> {
                val lexeme = reader.nextString()
                if (!RFC_JSON_NUMBER.matches(lexeme)) throw IllegalArgumentException("hybrid number is invalid")
                val number = runCatching { BigDecimal(lexeme) }.getOrNull()
                    ?: throw IllegalArgumentException("hybrid number is invalid")
                JsonPrimitive(number)
            }
            JsonToken.BOOLEAN -> JsonPrimitive(reader.nextBoolean())
            JsonToken.NULL -> {
                reader.nextNull()
                JsonNull.INSTANCE
            }
            else -> throw IllegalArgumentException("hybrid JSON token is invalid")
        }
    }

    private fun containsInvalidHybridNumber(value: Any?): Boolean = when (value) {
        null, is String, is Boolean, is Char -> false
        is Double -> !value.isFinite() || value.toBigDecimal().abs() > MAX_HYBRID_NUMERIC_MAGNITUDE
        is Float -> !value.isFinite() || value.toBigDecimal().abs() > MAX_HYBRID_NUMERIC_MAGNITUDE
        is Number -> runCatching { BigDecimal(value.toString()).abs() > MAX_HYBRID_NUMERIC_MAGNITUDE }
            .getOrDefault(true)
        is Map<*, *> -> value.entries.any { containsInvalidHybridNumber(it.key) || containsInvalidHybridNumber(it.value) }
        is Iterable<*> -> value.any(::containsInvalidHybridNumber)
        is Array<*> -> value.any(::containsInvalidHybridNumber)
        else -> false
    }

    private fun Long.requireRange(name: String, minimum: Long, maximum: Long): Long {
        if (this !in minimum..maximum) throw IllegalArgumentException("$name is out of range")
        return this
    }

    private fun Int.requireRange(name: String, minimum: Int, maximum: Int): Int {
        if (this !in minimum..maximum) throw IllegalArgumentException("$name is out of range")
        return this
    }

    private val TREE_RESOLVERS = setOf(
        ResolverKind.RESOURCE_ID,
        ResolverKind.CONTENT_DESCRIPTION,
        ResolverKind.TEXT_CLASS,
        ResolverKind.STRUCTURAL
    )
    private val INTEGER_PATTERN = Regex("-?(?:0|[1-9][0-9]*)")
    private val RFC_JSON_NUMBER = Regex("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
    private val SAFE_IDENTIFIER = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    private val SAFE_ASSET_NAME = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    private val GUARD_STRING_FIELDS = setOf("expectedPackage", "expected_package")
    private val GUARD_LIST_FIELDS = setOf(
        "requireText", "require_text", "requiredText", "required_text",
        "forbidText", "forbid_text", "forbiddenText", "forbidden_text"
    )
    private const val MAX_HYBRID_STRING = 256
    private const val MAX_HYBRID_PARAM_STRING = 4_096
    private const val MAX_HYBRID_MAP_ENTRIES = 64
    private const val MAX_HYBRID_LIST_ITEMS = 256
    private const val MAX_HYBRID_NESTING_DEPTH = 8
    private const val MAX_HYBRID_JSON_NODES = 10_000
    private const val MAX_HYBRID_STEPS = 200
    private const val MAX_STRUCTURAL_PATH = 32
    private const val MAX_STRUCTURAL_INDEX = 4_096
    private const val MAX_FINGERPRINT_DISTANCE = 64
    private const val MAX_WINDOW_ID = 1_000_000
    private const val MAX_DISPLAY_ID = 1_024
    private const val MAX_DISPLAY_DIMENSION = 16_384
    private const val MAX_DENSITY_DPI = 2_000
    private val MAX_HYBRID_NUMERIC_MAGNITUDE = BigDecimal("9007199254740991")

    private class StrictJsonBudget(var nodes: Int = 0)
}
