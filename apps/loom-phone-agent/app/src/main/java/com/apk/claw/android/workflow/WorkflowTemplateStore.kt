package com.apk.claw.android.workflow

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.ConcurrentHashMap

class WorkflowTemplateStoreLoadException(
    val code: String,
    val source: String,
    cause: Throwable? = null
) : IllegalStateException("workflow_template_store_load_failed code=$code source=$source", cause)

class WorkflowTemplateStore(
    private val directory: File,
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create(),
    private val rename: (File, File) -> Boolean = { source, destination -> source.renameTo(destination) }
) {
    private val target = File(directory, "template_index.json")
    private val pending = File(directory, "template_index.json.tmp")
    private val backup = File(directory, "template_index.json.bak")
    private val corrupt = File(directory, "template_index.json.corrupt")
    private val directoryLock = directoryLocks.computeIfAbsent(directoryLockKey(directory)) { Any() }

    fun save(templates: Collection<WorkflowTemplate>) = synchronized(directoryLock) {
        saveLocked(templates)
    }

    private fun saveLocked(templates: Collection<WorkflowTemplate>) {
        directory.mkdirs()
        FileOutputStream(pending).use { output ->
            output.write(gson.toJson(templates.sortedBy { it.id }).toByteArray(Charsets.UTF_8))
            output.fd.sync()
        }
        if (backup.exists()) check(backup.delete())
        if (target.exists()) check(moveWithinDirectory(target, backup))
        try {
            check(moveWithinDirectory(pending, target))
        } catch (error: Exception) {
            if (!target.exists() && backup.exists()) runCatching { moveWithinDirectory(backup, target) }
            throw IllegalStateException("template_index_replace_failed", error)
        }
        if (backup.exists()) check(backup.delete())
    }

    fun load(): List<WorkflowTemplate> = synchronized(directoryLock) {
        loadLocked()
    }

    private fun loadLocked(): List<WorkflowTemplate> {
        if (!target.exists()) {
            if (!backup.exists()) return emptyList()
            val recovered = readAndParse(backup, "backup")
            check(moveWithinDirectory(backup, target))
            return recovered
        }

        return try {
            readAndParse(target, "primary")
        } catch (primaryFailure: WorkflowTemplateStoreLoadException) {
            if (!backup.exists()) throw primaryFailure
            try {
                val recovered = readAndParse(backup, "backup")
                promoteBackupAfterCorruptPrimary()
                recovered
            } catch (backupFailure: WorkflowTemplateStoreLoadException) {
                throw WorkflowTemplateStoreLoadException(
                    "primary_and_backup_invalid",
                    "primary",
                    backupFailure
                )
            }
        }
    }

    private fun promoteBackupAfterCorruptPrimary() {
        if (corrupt.exists()) check(corrupt.delete())
        check(moveWithinDirectory(target, corrupt))
        if (!moveWithinDirectory(backup, target)) {
            if (!target.exists() && corrupt.exists()) moveWithinDirectory(corrupt, target)
            error("template_index_backup_promotion_failed")
        }
    }

    private fun moveWithinDirectory(source: File, destination: File): Boolean = rename(source, destination)

    private fun readAndParse(file: File, source: String): List<WorkflowTemplate> = try {
        parseAndMigrate(file.readText(), source)
    } catch (error: WorkflowTemplateStoreLoadException) {
        throw error
    } catch (error: Exception) {
        throw WorkflowTemplateStoreLoadException("index_read_failed", source, error)
    }

    private fun parseAndMigrate(json: String, source: String): List<WorkflowTemplate> {
        val root = try {
            JsonParser.parseString(json)
        } catch (error: Exception) {
            throw WorkflowTemplateStoreLoadException("invalid_index_json", source, error)
        }
        val templates = when {
            root.isJsonArray -> root.asJsonArray
            root.isJsonObject -> root.asJsonObject.arrayValue("templates")
                ?: throw WorkflowTemplateStoreLoadException("invalid_index_root", source)
            else -> throw WorkflowTemplateStoreLoadException("invalid_index_root", source)
        }
        return templates.mapIndexed { index, element ->
            if (!element.isJsonObject) {
                throw WorkflowTemplateStoreLoadException("invalid_template", "$source:template[$index]")
            }
            try {
                parseTemplate(element.asJsonObject, source, index)
            } catch (error: WorkflowTemplateStoreLoadException) {
                throw error
            } catch (error: Exception) {
                throw WorkflowTemplateStoreLoadException("invalid_template", "$source:template[$index]", error)
            }
        }
    }

    private fun parseTemplate(obj: JsonObject, source: String, index: Int): WorkflowTemplate {
        val id = obj.stringValue("id")
        require(id.isNotBlank()) { "missing template id" }
        val storedSchemaVersion = obj.intValue("schemaVersion")
        if (storedSchemaVersion > 2) {
            throw WorkflowTemplateStoreLoadException(
                "unsupported_schema_version",
                "$source:template[$index]:$id"
            )
        }
        val legacy = storedSchemaVersion < 2
        val revision = obj.intValue("revision", 1)
        val primarySteps = parseSteps(
            obj.arrayValue("steps") ?: throw WorkflowTemplateStoreLoadException(
                "invalid_primary_step",
                "$source:template[$index]:$id:steps"
            ),
            id,
            "steps",
            "invalid_primary_step"
        )
        return WorkflowTemplate(
            id = id,
            name = obj.stringValue("name"),
            description = obj.stringValue("description"),
            taskPattern = obj.stringValue("taskPattern"),
            keywords = obj.stringListValue("keywords"),
            appName = obj.stringOrNull("appName"),
            steps = primarySteps,
            createdAt = obj.longValue("createdAt"),
            lastUsedAt = obj.longValue("lastUsedAt"),
            successCount = obj.intValue("successCount"),
            failCount = obj.intValue("failCount"),
            schemaVersion = 2,
            status = if (legacy) TemplateStatus.DEGRADED else obj.enumValue("status", TemplateStatus.DRAFT),
            executionMode = obj.stringValue("executionMode", "hybrid_rpa"),
            defaultResolverPolicy = obj.strictEnumValue("defaultResolverPolicy", ResolverPolicy.TREE_PREFERRED),
            riskLevel = obj.enumValue("riskLevel", TemplateRiskLevel.UNKNOWN),
            validationState = if (legacy) ValidationState() else parseValidationState(obj.strictObjectOrNull("validationState")),
            revision = revision,
            sourceAgentTaskId = obj.stringValue("sourceAgentTaskId"),
            targetPackage = obj.stringValue("targetPackage"),
            targetVersionCode = obj.longValue("targetVersionCode"),
            targetProfileId = obj.stringValue("targetProfileId"),
            activatedAt = obj.longValue("activatedAt"),
            degradedAt = obj.longValue("degradedAt"),
            degradedReason = obj.stringValue("degradedReason"),
            visualAssetDirectory = obj.stringValue("visualAssetDirectory")
        )
    }

    private fun parseSteps(
        steps: JsonArray,
        templateId: String,
        path: String,
        failureCode: String
    ): List<WorkflowTemplate.WorkflowStep> = steps.mapIndexed { index, element ->
        val stepPath = "$path[$index]"
        if (!element.isJsonObject) {
            throw WorkflowTemplateStoreLoadException(failureCode, "template:$templateId:$stepPath")
        }
        try {
            parseStep(element.asJsonObject, templateId, stepPath)
        } catch (error: WorkflowTemplateStoreLoadException) {
            throw error
        } catch (error: Exception) {
            throw WorkflowTemplateStoreLoadException(failureCode, "template:$templateId:$stepPath", error)
        }
    }

    private fun parseStep(
        obj: JsonObject,
        templateId: String,
        stepPath: String
    ): WorkflowTemplate.WorkflowStep {
        val toolName = obj.stringValue("toolName")
        require(toolName.isNotBlank()) { "missing step toolName" }
        val params = obj.objectValue("paramsTemplate")
            ?: throw IllegalArgumentException("missing paramsTemplate")
        val failureHandling = obj.get("failureHandling")?.takeUnless { it.isJsonNull }?.let { value ->
            require(value.isJsonObject) { "invalid failureHandling" }
            parseFailureHandling(value.asJsonObject, templateId, stepPath)
        }
        return WorkflowTemplate.WorkflowStep(
            toolName = toolName,
            paramsTemplate = params.entrySet()
                .mapNotNull { (key, value) -> jsonToTemplateParam(value)?.let { key to it } }
                .toMap(),
            description = obj.stringValue("description", toolName),
            waitFor = obj.intValue("waitFor", 500),
            isVerification = obj.booleanValue("isVerification"),
            failureHandling = failureHandling,
            resolverPolicy = obj.strictEnumValue("resolverPolicy", ResolverPolicy.TREE_PREFERRED),
            allowedResolvers = obj.strictResolverSetValue("allowedResolvers"),
            validatedResolvers = obj.strictResolverSetValue("validatedResolvers"),
            semanticSelector = obj.strictObjectOrNull("semanticSelector")?.let(::parseSemanticSelector),
            visualAnchor = obj.strictObjectOrNull("visualAnchor")?.let(::parseVisualAnchor),
            preCheckpoint = obj.strictObjectOrNull("preCheckpoint")?.let(::parseCheckpoint),
            postCheckpoint = obj.strictObjectOrNull("postCheckpoint")?.let(::parseCheckpoint)
        )
    }

    private fun parseFailureHandling(
        obj: JsonObject,
        templateId: String,
        stepPath: String
    ): WorkflowTemplate.FailureHandling {
        val fallbackValue = obj.get("fallbackSteps")
        val fallbackSteps = when {
            fallbackValue == null || fallbackValue.isJsonNull -> null
            !fallbackValue.isJsonArray -> throw WorkflowTemplateStoreLoadException(
                "invalid_fallback_step",
                "template:$templateId:$stepPath:fallbackSteps"
            )
            else -> parseSteps(
                fallbackValue.asJsonArray,
                templateId,
                "$stepPath:fallbackSteps",
                "invalid_fallback_step"
            )
        }
        return WorkflowTemplate.FailureHandling(
            maxRetries = obj.intValue("maxRetries", 3),
            retryDelay = obj.intValue("retryDelay", 1000),
            fallbackSteps = fallbackSteps
        )
    }

    private fun parseValidationState(obj: JsonObject?): ValidationState {
        if (obj == null) return ValidationState(validatedRevision = 0)
        return ValidationState(
            target = TemplateLifecyclePolicy.REQUIRED_CONSECUTIVE_SUCCESSES,
            profileId = obj.stringValue("profileId"),
            consecutiveSuccesses = obj.intValue("consecutiveSuccesses"),
            failures = obj.intValue("failures"),
            validatedResolvers = obj.strictResolverSetValue("validatedResolvers"),
            validatedResetIds = obj.stringListValue("validatedResetIds").toSet(),
            lastValidationAt = obj.longValue("lastValidationAt"),
            validatedRevision = if (obj.has("validatedRevision")) obj.intValue("validatedRevision") else 0
        )
    }

    private fun parseSemanticSelector(obj: JsonObject): SemanticSelector = SemanticSelector(
        resourceId = obj.strictStringOrNull("resourceId"),
        contentDescription = obj.strictStringOrNull("contentDescription"),
        text = obj.strictStringOrNull("text"),
        className = obj.strictStringOrNull("className"),
        packageName = obj.strictStringOrNull("packageName"),
        structuralPath = obj.strictIntListValue("structuralPath")
    )

    private fun parseVisualAnchor(obj: JsonObject): VisualAnchorSpec = VisualAnchorSpec(
        assetName = obj.requiredStringValue("assetName"),
        searchRegion = obj.requiredObjectValue("searchRegion").let(::parseNormalizedRect),
        tapOffsetX = obj.requiredFloatValue("tapOffsetX"),
        tapOffsetY = obj.requiredFloatValue("tapOffsetY"),
        minimumConfidence = obj.strictFloatValue("minimumConfidence", 0.88f),
        scaleVariants = obj.strictFloatListValue("scaleVariants", listOf(0.90f, 1.00f, 1.10f))
    )

    private fun parseNormalizedRect(obj: JsonObject): NormalizedRect = NormalizedRect(
        left = obj.requiredFloatValue("left"),
        top = obj.requiredFloatValue("top"),
        right = obj.requiredFloatValue("right"),
        bottom = obj.requiredFloatValue("bottom")
    )

    private fun parseCheckpoint(obj: JsonObject): StepCheckpoint = StepCheckpoint(
        expectedPackage = obj.strictStringOrNull("expectedPackage"),
        requiredSelector = obj.strictObjectOrNull("requiredSelector")?.let(::parseSemanticSelector),
        forbiddenSelector = obj.strictObjectOrNull("forbiddenSelector")?.let(::parseSemanticSelector),
        perceptualHash = obj.strictStringOrNull("perceptualHash"),
        maximumHammingDistance = obj.strictIntValue("maximumHammingDistance", 8),
        expectedWindowId = obj.strictIntOrNull("expectedWindowId")?.also {
            require(it in 0..MAX_CHECKPOINT_WINDOW_ID) { "invalid expectedWindowId" }
        },
        expectedDisplayTransform = obj.strictObjectOrNull("expectedDisplayTransform")
            ?.let(::parseDisplayTransformCheckpoint)
    )

    private fun parseDisplayTransformCheckpoint(obj: JsonObject): DisplayTransformCheckpoint {
        require(obj.keySet() == DISPLAY_TRANSFORM_FIELDS) { "invalid expectedDisplayTransform" }
        val transform = DisplayTransformCheckpoint(
            displayId = obj.requiredIntValue("displayId"),
            widthPx = obj.requiredIntValue("widthPx"),
            heightPx = obj.requiredIntValue("heightPx"),
            screenshotWidthPx = obj.requiredIntValue("screenshotWidthPx"),
            screenshotHeightPx = obj.requiredIntValue("screenshotHeightPx"),
            rotation = obj.requiredIntValue("rotation"),
            densityDpi = obj.requiredIntValue("densityDpi"),
            insetLeft = obj.requiredIntValue("insetLeft"),
            insetTop = obj.requiredIntValue("insetTop"),
            insetRight = obj.requiredIntValue("insetRight"),
            insetBottom = obj.requiredIntValue("insetBottom")
        )
        require(
            transform.displayId in 0..MAX_CHECKPOINT_DISPLAY_ID &&
                transform.widthPx in 1..MAX_CHECKPOINT_DISPLAY_DIMENSION &&
                transform.heightPx in 1..MAX_CHECKPOINT_DISPLAY_DIMENSION &&
                transform.screenshotWidthPx in 1..MAX_CHECKPOINT_DISPLAY_DIMENSION &&
                transform.screenshotHeightPx in 1..MAX_CHECKPOINT_DISPLAY_DIMENSION &&
                transform.rotation in 0..3 &&
                transform.densityDpi in 1..MAX_CHECKPOINT_DENSITY_DPI &&
                listOf(transform.insetLeft, transform.insetTop, transform.insetRight, transform.insetBottom)
                    .all { it in 0..MAX_CHECKPOINT_DISPLAY_DIMENSION } &&
                transform.insetLeft + transform.insetRight < transform.widthPx &&
                transform.insetTop + transform.insetBottom < transform.heightPx
        ) { "invalid expectedDisplayTransform" }
        return transform
    }

    private fun jsonToTemplateParam(value: JsonElement): Any? {
        if (value.isJsonNull) return null
        if (value.isJsonPrimitive) {
            val primitive = value.asJsonPrimitive
            return when {
                primitive.isBoolean -> primitive.asBoolean
                primitive.isNumber -> jsonNumberParam(value)
                else -> primitive.asString
            }
        }
        if (value.isJsonArray) return value.asJsonArray.mapNotNull(::jsonToTemplateParam)
        if (value.isJsonObject) {
            return value.asJsonObject.entrySet()
                .mapNotNull { (key, item) -> jsonToTemplateParam(item)?.let { key to it } }
                .toMap()
        }
        return null
    }

    private fun jsonNumberParam(value: JsonElement): Number {
        val text = runCatching { value.asString }.getOrNull().orEmpty()
        val longValue = text.toLongOrNull()
        if (longValue != null) {
            return if (longValue in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong()) longValue.toInt() else longValue
        }
        return text.toDoubleOrNull() ?: value.asNumber
    }

    private inline fun <reified T : Enum<T>> JsonObject.strictEnumValue(name: String, default: T): T {
        val value = get(name) ?: return default
        require(value.isJsonPrimitive && value.asJsonPrimitive.isString) { "invalid $name" }
        return enumValues<T>().firstOrNull { it.name == value.asString }
            ?: throw IllegalArgumentException("unknown $name")
    }

    private fun JsonObject.strictResolverSetValue(name: String): Set<ResolverKind> {
        val value = get(name) ?: return emptySet()
        require(value.isJsonArray) { "invalid $name" }
        return value.asJsonArray.map { resolver ->
            require(resolver.isJsonPrimitive && resolver.asJsonPrimitive.isString) { "invalid $name" }
            ResolverKind.values().firstOrNull { it.name == resolver.asString }
                ?: throw IllegalArgumentException("unknown $name")
        }.toSet()
    }

    private fun JsonObject.strictObjectOrNull(name: String): JsonObject? {
        val value = get(name) ?: return null
        require(value.isJsonObject) { "invalid $name" }
        return value.asJsonObject
    }

    private fun JsonObject.requiredObjectValue(name: String): JsonObject =
        strictObjectOrNull(name) ?: throw IllegalArgumentException("missing $name")

    private fun JsonObject.strictStringOrNull(name: String): String? {
        val value = get(name) ?: return null
        if (value.isJsonNull) return null
        require(value.isJsonPrimitive && value.asJsonPrimitive.isString) { "invalid $name" }
        return value.asString
    }

    private fun JsonObject.requiredStringValue(name: String): String =
        strictStringOrNull(name)?.takeIf { it.isNotBlank() } ?: throw IllegalArgumentException("missing $name")

    private fun JsonObject.strictIntValue(name: String, default: Int): Int {
        val value = get(name) ?: return default
        require(value.isJsonPrimitive && value.asJsonPrimitive.isNumber) { "invalid $name" }
        return value.asString.toIntOrNull() ?: throw IllegalArgumentException("invalid $name")
    }

    private fun JsonObject.strictIntOrNull(name: String): Int? {
        val value = get(name) ?: return null
        require(value.isJsonPrimitive && value.asJsonPrimitive.isNumber) { "invalid $name" }
        return value.asString.toIntOrNull() ?: throw IllegalArgumentException("invalid $name")
    }

    private fun JsonObject.requiredIntValue(name: String): Int =
        strictIntOrNull(name) ?: throw IllegalArgumentException("missing $name")

    private fun JsonObject.requiredFloatValue(name: String): Float {
        val value = get(name) ?: throw IllegalArgumentException("missing $name")
        require(value.isJsonPrimitive && value.asJsonPrimitive.isNumber) { "invalid $name" }
        return value.asString.toFloatOrNull() ?: throw IllegalArgumentException("invalid $name")
    }

    private fun JsonObject.strictFloatValue(name: String, default: Float): Float {
        if (!has(name)) return default
        return requiredFloatValue(name)
    }

    private fun JsonObject.strictIntListValue(name: String): List<Int> {
        val value = get(name) ?: return emptyList()
        require(value.isJsonArray) { "invalid $name" }
        return value.asJsonArray.map { item ->
            require(item.isJsonPrimitive && item.asJsonPrimitive.isNumber) { "invalid $name" }
            item.asString.toIntOrNull() ?: throw IllegalArgumentException("invalid $name")
        }
    }

    private fun JsonObject.strictFloatListValue(name: String, default: List<Float>): List<Float> {
        val value = get(name) ?: return default
        require(value.isJsonArray) { "invalid $name" }
        return value.asJsonArray.map { item ->
            require(item.isJsonPrimitive && item.asJsonPrimitive.isNumber) { "invalid $name" }
            item.asString.toFloatOrNull() ?: throw IllegalArgumentException("invalid $name")
        }
    }

    private inline fun <reified T : Enum<T>> JsonObject.enumValue(name: String, default: T): T =
        get(name)?.takeIf { it.isJsonPrimitive }?.let { value ->
            enumValues<T>().firstOrNull { it.name == value.asString }
        } ?: default

    private fun JsonObject.stringValue(name: String, default: String = ""): String =
        get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asString }.getOrDefault(default) } ?: default

    private fun JsonObject.stringOrNull(name: String): String? = stringValue(name).ifBlank { null }

    private fun JsonObject.intValue(name: String, default: Int = 0): Int =
        get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asInt }.getOrDefault(default) } ?: default

    private fun JsonObject.longValue(name: String, default: Long = 0L): Long =
        get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asLong }.getOrDefault(default) } ?: default

    private fun JsonObject.booleanValue(name: String, default: Boolean = false): Boolean =
        get(name)?.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asBoolean }.getOrDefault(default) } ?: default

    private fun JsonObject.stringListValue(name: String): List<String> =
        arrayValue(name)?.mapNotNull { value ->
            value.takeIf { it.isJsonPrimitive }?.let { runCatching { it.asString }.getOrNull() }
        } ?: emptyList()

    private fun JsonObject.objectValue(name: String): JsonObject? =
        get(name)?.takeIf { it.isJsonObject }?.asJsonObject

    private fun JsonObject.arrayValue(name: String) = get(name)?.takeIf { it.isJsonArray }?.asJsonArray

    companion object {
        private val directoryLocks = ConcurrentHashMap<String, Any>()
        private fun directoryLockKey(directory: File): String =
            runCatching { directory.canonicalPath }.getOrElse { directory.absolutePath }

        private const val MAX_CHECKPOINT_WINDOW_ID = 1_000_000
        private const val MAX_CHECKPOINT_DISPLAY_ID = 1_024
        private const val MAX_CHECKPOINT_DISPLAY_DIMENSION = 16_384
        private const val MAX_CHECKPOINT_DENSITY_DPI = 2_000
        private val DISPLAY_TRANSFORM_FIELDS = setOf(
            "displayId",
            "widthPx",
            "heightPx",
            "screenshotWidthPx",
            "screenshotHeightPx",
            "rotation",
            "densityDpi",
            "insetLeft",
            "insetTop",
            "insetRight",
            "insetBottom"
        )
    }
}
