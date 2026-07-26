package com.apk.claw.android.workflow

import com.apk.claw.android.ClawApplication
import com.apk.claw.android.rpa.HYBRID_EXECUTION_MODE
import com.apk.claw.android.rpa.RpaRunStatus
import com.apk.claw.android.rpa.RpaStep
import com.apk.claw.android.rpa.RpaWorkflow
import com.apk.claw.android.rpa.RpaWorkflowRunner
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.utils.XLog
import java.io.File
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * 工作流模板管理器
 * 负责：模板保存、加载、匹配、执行、学习
 */
object WorkflowTemplateManager {

    private const val TAG = "WorkflowTemplateManager"
    private const val TEMPLATE_DIR = "workflow_templates"
    private const val HYBRID_STEP_BUDGET_MS = 120_000L
    private const val MAX_HYBRID_TEMPLATE_WAIT_MS = 600_000L
    private const val HYBRID_POLL_INTERVAL_MS = 25L
    private val placeholderRegex = Regex("\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}")
    private val learnedPromptRegex = Regex("从任务\\s*\"(.+)\"\\s*学习生成")

    private val messagePatterns = listOf(
        Regex("(?:给|向)\\s*([^，,。.!！；;]+?)\\s*(?:发消息|发送消息|发信息|发送信息|告诉|通知|说)\\s*(?:说|内容是|内容为|为|:|：)?\\s*[\"“”']?(.+?)[\"“”']?\\s*$", RegexOption.IGNORE_CASE),
        Regex("(?:搜索|查找|找一下|找)\\s*([^，,。.!！；;]+?)\\s*[，,。.!！；;\\s]*(?:发消息|发送消息|发信息|发送信息)\\s*(?:说|内容是|内容为|为|:|：)?\\s*[\"“”']?(.+?)[\"“”']?\\s*$", RegexOption.IGNORE_CASE),
        Regex("(?:发消息|发送消息|发信息|发送信息)\\s*(?:给|到)?\\s*([^，,。.!！；;]+?)\\s*(?:说|内容是|内容为|为|:|：)\\s*[\"“”']?(.+?)[\"“”']?\\s*$", RegexOption.IGNORE_CASE),
        Regex("(?:tell|message|send)\\s+([^,，。.!！；;]+?)\\s+(?:that|saying|with|:)\\s*[\"“”']?(.+?)[\"“”']?\\s*$", RegexOption.IGNORE_CASE)
    )

    private val searchPatterns = listOf(
        Regex("(?:搜索|搜一下|查找|找一下|find|search)\\s*[\"“”']?([^，,。.!！；;]+)[\"“”']?", RegexOption.IGNORE_CASE)
    )

    private val canonicalParamOrder = listOf("contact_name", "message", "keyword", "app")
    private val displayNameToToolName = mapOf(
        "Screenshot" to "take_screenshot",
        "截屏" to "take_screenshot",
        "スクリーンショット" to "take_screenshot",
        "Send File" to "send_file",
        "发送文件" to "send_file",
        "ファイル送信" to "send_file",
        "Wait" to "wait",
        "等待" to "wait",
        "待機" to "wait",
        "Get Screen Info" to "get_screen_info",
        "获取屏幕信息" to "get_screen_info",
        "画面情報を取得" to "get_screen_info",
        "Finish Task" to "finish",
        "完成任务" to "finish",
        "タスク完了" to "finish",
        "Open App" to "open_app",
        "打开应用" to "open_app",
        "アプリを開く" to "open_app",
        "Get Installed Apps" to "get_installed_apps",
        "获取应用列表" to "get_installed_apps",
        "アプリ一覧を取得" to "get_installed_apps",
        "System Key" to "system_key",
        "系统按键" to "system_key",
        "システムキー" to "system_key",
        "Tap" to "tap",
        "点击" to "tap",
        "タップ" to "tap",
        "Swipe" to "swipe",
        "滑动" to "swipe",
        "スワイプ" to "swipe",
        "Drag" to "drag",
        "拖拽" to "drag",
        "Input Text" to "input_text",
        "输入文本" to "input_text",
        "テキスト入力" to "input_text",
        "Find Node" to "find_node_info",
        "查找节点" to "find_node_info",
        "ノード検索" to "find_node_info",
        "Long Press" to "long_press",
        "长按" to "long_press",
        "長押し" to "long_press",
        "Repeat Actions" to "repeat_actions",
        "重复执行动作" to "repeat_actions",
        "アクションを繰り返す" to "repeat_actions",
        "Search App" to "search_app_in_store",
        "搜索APP" to "search_app_in_store",
        "アプリを検索" to "search_app_in_store",
        "Clipboard" to "clipboard",
        "剪贴板" to "clipboard",
        "クリップボード" to "clipboard",
        "Scroll to Find" to "scroll_to_find",
        "滚动查找" to "scroll_to_find",
        "スクロールして検索" to "scroll_to_find"
    )

    // 模板缓存
    private val templates = ConcurrentHashMap<String, WorkflowTemplate>()
    private val lifecycleLock = Any()
    private val promotionCoordinator = TemplatePromotionCoordinator()

    // 是否已初始化
    private var initialized = false

    data class TemplateParamResolution(
        val params: Map<String, String>,
        val missingParams: List<String>
    )

    /**
     * 初始化，加载所有模板
     */
    fun initialize() {
        if (initialized) return

        val app = ClawApplication.instance
        val templateDir = File(app.filesDir, TEMPLATE_DIR)
        if (!templateDir.exists()) {
            templateDir.mkdirs()
        }

        try {
            WorkflowTemplateStore(templateDir).load().forEach { template ->
                templates[template.id] = template
            }
            XLog.i(TAG, "Loaded ${templates.size} workflow templates")
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to load template index", e)
        }

        initialized = true
    }

    /**
     * 保存模板到磁盘
     */
    private fun saveTemplates() {
        val app = ClawApplication.instance
        val templateDir = File(app.filesDir, TEMPLATE_DIR)
        if (!templateDir.exists()) {
            templateDir.mkdirs()
        }

        try {
            WorkflowTemplateStore(templateDir).save(templates.values)
            XLog.d(TAG, "Saved ${templates.size} templates to disk")
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to save templates", e)
        }
    }

    // ==================== 模板匹配 ====================

    fun matchTemplate(userPrompt: String): WorkflowTemplate? = null

    fun matchTemplate(userPrompt: String, profileId: String): WorkflowTemplate? {
        initialize()
        return selectActiveTemplateForPrompt(templates.values, userPrompt, profileId)?.let { template ->
            ensureTemplateParameterized(template).also {
                XLog.i(TAG, "Template matched: ${it.name}")
            }
        }
    }

    internal fun selectActiveTemplateForPrompt(
        candidates: Collection<WorkflowTemplate>,
        userPrompt: String,
        profileId: String
    ): WorkflowTemplate? {
        if (profileId.isBlank()) return null
        val activeCandidates = candidates.filter {
            promotionCoordinator.match(it, profileId) == MatchDecision.MATCH
        }
        return activeCandidates.mapNotNull { template ->
            val score = calculateMatchScore(template, userPrompt)
            if (score > 0.5f) {
                template to score
            } else {
                null
            }
        }.maxByOrNull { it.second }?.first
    }

    /**
     * 计算模板与任务的匹配分数
     * 注意：中文没有大小写概念，直接匹配
     */
    private fun calculateMatchScore(template: WorkflowTemplate, prompt: String): Float {
        var score = 0f

        // 1. 任务模式匹配（正则，忽略大小写对英文有效）
        try {
            if (Regex(template.taskPattern, RegexOption.IGNORE_CASE).containsMatchIn(prompt)) {
                score += 0.6f
            }
        } catch (e: Exception) {
            // 正则无效，跳过
        }

        // 2. 关键词匹配（直接匹配，中文不转小写）
        val keywordMatches = template.keywords.count { keyword ->
            prompt.contains(keyword)  // 直接匹配，中文关键词无需lowercase
        }
        if (template.keywords.isNotEmpty()) {
            score += (keywordMatches.toFloat() / template.keywords.size) * 0.3f
        }

        // 3. 应用名匹配（直接匹配）
        if (template.appName != null) {
            if (prompt.contains(template.appName)) {
                score += 0.1f
            }
        }

        return score
    }

    // ==================== 模板执行 ====================

    /**
     * 执行模板
     * @param template 模板
     * @param params 实际参数（替换模板中的占位符）
     * @return 执行结果
     */
    fun executeTemplate(
        template: WorkflowTemplate,
        params: Map<String, String> = emptyMap(),
        freshProfileProvider: () -> String = DeviceProfileProvider::current
    ): TemplateExecutionResult {
        if (template.executionMode == HYBRID_EXECUTION_MODE) {
            hybridExecutionPrecondition(
                template,
                runCatching { freshProfileProvider() }.getOrDefault("")
            )?.let { return it }
            initialize()
            return executeHybridTemplate(template, params)
        }

        initialize()

        val startTime = System.currentTimeMillis()
        var stepsExecuted = 0
        val expandedParams = expandParamAliases(params)
        val missingParams = getMissingTemplateParams(template, expandedParams)

        if (missingParams.isNotEmpty()) {
            return TemplateExecutionResult(
                success = false,
                templateId = template.id,
                stepsExecuted = 0,
                stepsTotal = template.steps.size,
                errorMessage = "Missing template params: ${missingParams.joinToString(", ")}",
                executionTimeMs = System.currentTimeMillis() - startTime
            )
        }

        XLog.i(TAG, "Executing template: ${template.name}, steps=${template.steps.size}")

        try {
            for (step in template.steps) {
                val toolName = normalizeToolName(step.toolName)
                // 替换参数占位符
                val actualParams = resolveParams(step.paramsTemplate, expandedParams)

                XLog.d(TAG, "Step ${stepsExecuted + 1}: $toolName(${actualParams})")

                // 执行工具
                var result: ToolResult
                var retryCount = 0

                do {
                    result = ToolRegistry.executeTool(toolName, actualParams)

                    if (!result.isSuccess && step.failureHandling != null && retryCount < step.failureHandling.maxRetries) {
                        retryCount++
                        XLog.w(TAG, "Step failed, retry $retryCount/${step.failureHandling.maxRetries}")
                        Thread.sleep(step.failureHandling.retryDelay.toLong())
                    } else {
                        break
                    }
                } while (true)

                // 验证步骤失败 → 尝试后备步骤
                if (!result.isSuccess && step.isVerification && step.failureHandling?.fallbackSteps != null) {
                    XLog.w(TAG, "Verification failed, trying fallback steps")
                    for (fallbackStep in step.failureHandling.fallbackSteps) {
                        val fallbackToolName = normalizeToolName(fallbackStep.toolName)
                        val fallbackParams = resolveParams(fallbackStep.paramsTemplate, expandedParams)
                        val fallbackResult = ToolRegistry.executeTool(fallbackToolName, fallbackParams)
                        if (fallbackResult.isSuccess) {
                            result = fallbackResult
                            break
                        }
                    }
                }

                // 步骤失败
                if (!result.isSuccess) {
                    XLog.e(TAG, "Step failed: $toolName, error=${result.error}")
                    updateTemplateStats(template.id, false)
                    return TemplateExecutionResult(
                        success = false,
                        templateId = template.id,
                        stepsExecuted = stepsExecuted,
                        stepsTotal = template.steps.size,
                        errorMessage = "Step ${stepsExecuted + 1} ($toolName) failed: ${result.error}",
                        executionTimeMs = System.currentTimeMillis() - startTime
                    )
                }

                stepsExecuted++

                // 等待
                if (step.waitFor > 0) {
                    Thread.sleep(step.waitFor.toLong())
                }
            }

            // 全部成功
            updateTemplateStats(template.id, true)
            XLog.i(TAG, "Template executed successfully: ${template.name}")

            return TemplateExecutionResult(
                success = true,
                templateId = template.id,
                stepsExecuted = stepsExecuted,
                stepsTotal = template.steps.size,
                executionTimeMs = System.currentTimeMillis() - startTime
            )

        } catch (e: Exception) {
            XLog.e(TAG, "Template execution error", e)
            updateTemplateStats(template.id, false)
            return TemplateExecutionResult(
                success = false,
                templateId = template.id,
                stepsExecuted = stepsExecuted,
                stepsTotal = template.steps.size,
                errorMessage = e.message ?: "Unknown error",
                executionTimeMs = System.currentTimeMillis() - startTime
            )
        }
    }

    internal fun hybridExecutionPrecondition(
        template: WorkflowTemplate,
        freshProfileId: String
    ): TemplateExecutionResult? {
        val decision = promotionCoordinator.match(template, freshProfileId)
        if (decision == MatchDecision.MATCH) return null
        val errorCode = when (decision) {
            MatchDecision.NOT_ACTIVE -> "template_status_invalid"
            MatchDecision.PROFILE_MISMATCH -> "profile_mismatch"
            MatchDecision.MATCH -> return null
        }
        val message = when (decision) {
            MatchDecision.NOT_ACTIVE -> "Hybrid template is not active with current revision evidence"
            MatchDecision.PROFILE_MISMATCH -> "Fresh foreground profile does not match the hybrid template"
            MatchDecision.MATCH -> return null
        }
        return TemplateExecutionResult(
            success = false,
            templateId = template.id,
            stepsExecuted = 0,
            stepsTotal = template.steps.size,
            errorMessage = message,
            errorCode = errorCode,
            mode = HYBRID_EXECUTION_MODE,
            outcomeState = "blocked"
        )
    }

    private fun executeHybridTemplate(
        template: WorkflowTemplate,
        params: Map<String, String>
    ): TemplateExecutionResult {
        val startedAt = System.currentTimeMillis()
        val expandedParams = expandParamAliases(params)
        val missingParams = getMissingTemplateParams(template, expandedParams)
        if (missingParams.isNotEmpty()) {
            return TemplateExecutionResult(
                success = false,
                templateId = template.id,
                stepsExecuted = 0,
                stepsTotal = template.steps.size,
                errorMessage = "Missing template params: ${missingParams.joinToString(", ")}",
                executionTimeMs = System.currentTimeMillis() - startedAt,
                errorCode = "missing_template_params",
                mode = HYBRID_EXECUTION_MODE,
                outcomeState = "blocked"
            )
        }
        val workflow = toHybridWorkflow(template, expandedParams)
        val start = RpaWorkflowRunner.start(workflow)
        if (!start.accepted) {
            return TemplateExecutionResult(
                success = false,
                templateId = template.id,
                stepsExecuted = 0,
                stepsTotal = template.steps.size,
                errorMessage = start.message,
                executionTimeMs = System.currentTimeMillis() - startedAt,
                errorCode = start.errorCode,
                mode = HYBRID_EXECUTION_MODE,
                outcomeState = "blocked"
            )
        }

        val runId = start.snapshot?.runId.orEmpty()
        val deadline = startedAt + template.steps.sumOf { step ->
            step.waitFor.coerceAtLeast(0).toLong() + HYBRID_STEP_BUDGET_MS
        }.coerceAtMost(MAX_HYBRID_TEMPLATE_WAIT_MS)
        var snapshot = start.snapshot
        while (snapshot != null && snapshot.status in setOf(RpaRunStatus.QUEUED, RpaRunStatus.RUNNING) &&
            System.currentTimeMillis() < deadline
        ) {
            Thread.sleep(HYBRID_POLL_INTERVAL_MS)
            snapshot = RpaWorkflowRunner.get(runId)
        }
        val terminal = snapshot
        if (terminal == null || terminal.status in setOf(RpaRunStatus.QUEUED, RpaRunStatus.RUNNING)) {
            RpaWorkflowRunner.cancel(runId)
            return TemplateExecutionResult(
                success = false,
                templateId = template.id,
                stepsExecuted = terminal?.steps?.size ?: 0,
                stepsTotal = template.steps.size,
                errorMessage = "Hybrid template execution timed out",
                executionTimeMs = System.currentTimeMillis() - startedAt,
                errorCode = "hybrid_timeout",
                mode = HYBRID_EXECUTION_MODE,
                outcomeState = "timeout",
                handoffContext = RpaWorkflowRunner.getAgentHandoff(runId)
            )
        }
        val success = terminal.status == RpaRunStatus.SUCCEEDED
        updateTemplateStats(template.id, success)
        if (!success) {
            recordTemplateRuntimeFailure(
                templateId = template.id,
                revision = template.revision,
                profileId = DeviceProfileProvider.current(),
                errorCode = terminal.errorCode
            )
        }
        return TemplateExecutionResult(
            success = success,
            templateId = template.id,
            stepsExecuted = terminal.steps.count { it.status == "succeeded" },
            stepsTotal = template.steps.size,
            errorMessage = terminal.message.takeIf { !success },
            executionTimeMs = System.currentTimeMillis() - startedAt,
            errorCode = terminal.errorCode,
            mode = HYBRID_EXECUTION_MODE,
            outcomeState = terminal.outcomeState,
            handoffContext = RpaWorkflowRunner.getAgentHandoff(runId)
        )
    }

    internal fun toHybridWorkflow(
        template: WorkflowTemplate,
        params: Map<String, String> = emptyMap()
    ): RpaWorkflow {
        val expandedParams = expandParamAliases(params)
        return RpaWorkflow(
            id = template.id,
            name = template.name,
            version = template.revision,
            steps = template.steps.mapIndexed { index, step ->
                RpaStep(
                    id = "step_${index + 1}",
                    action = hybridAction(step),
                    params = resolveParams(step.paramsTemplate, expandedParams),
                    description = step.description,
                    waitAfterMs = step.waitFor.coerceAtLeast(0).toLong(),
                    resolverPolicy = step.resolverPolicy,
                    allowedResolvers = step.allowedResolvers,
                    validatedResolvers = step.validatedResolvers,
                    semanticSelector = step.semanticSelector,
                    visualAnchor = step.visualAnchor,
                    preCheckpoint = step.preCheckpoint,
                    postCheckpoint = step.postCheckpoint,
                    resolverPolicyExplicit = true
                )
            },
            params = expandedParams,
            schemaVersion = 2,
            executionMode = HYBRID_EXECUTION_MODE,
            templateId = template.id,
            templateRevision = template.revision,
            targetProfileId = template.targetProfileId.ifBlank { template.validationState.profileId },
            templateStatus = template.status.name.lowercase(),
            validationProgress = validationProgress(template.validationState),
            promotionEligible = template.status == TemplateStatus.ACTIVE,
            promotionIneligibleReason = if (template.status == TemplateStatus.ACTIVE) "" else template.status.name.lowercase()
        )
    }

    private fun hybridAction(step: WorkflowTemplate.WorkflowStep): String = when (normalizeToolName(step.toolName)) {
        "system_key" -> step.paramsTemplate["key"]?.toString()?.lowercase().orEmpty()
        "tap" -> if (step.semanticSelector != null) "tap_semantic" else if (step.visualAnchor != null) "tap_anchor" else "tap_normalized"
        "swipe" -> "swipe_normalized"
        "drag" -> "drag_normalized"
        "long_press" -> "long_press_anchor"
        else -> normalizeToolName(step.toolName)
    }

    /**
     * 解析参数，替换占位符
     * 占位符格式: ${param_name}
     */
    private fun resolveParams(
        paramsTemplate: Map<String, Any>,
        actualParams: Map<String, String>
    ): Map<String, Any> {
        val expandedParams = expandParamAliases(actualParams)
        return paramsTemplate.mapValues { (_, value) ->
            when (value) {
                is String -> {
                    // 替换占位符
                    var resolved: String = value
                    expandedParams.forEach { (key, actualValue) ->
                        resolved = resolved.replace("\${$key}", actualValue)
                    }
                    val unresolved = extractPlaceholders(resolved)
                    if (unresolved.isNotEmpty()) {
                        throw IllegalArgumentException("Missing template params: ${unresolved.joinToString(", ")}")
                    }
                    resolved
                }
                is Number -> value
                is Boolean -> value
                else -> value
            }
        }
    }

    /**
     * 更新模板统计
     */
    private fun updateTemplateStats(templateId: String, success: Boolean) {
        val template = templates[templateId]
        if (template != null) {
            val updated = template.copy(
                lastUsedAt = System.currentTimeMillis(),
                successCount = if (success) template.successCount + 1 else template.successCount,
                failCount = if (!success) template.failCount + 1 else template.failCount
            )
            templates[templateId] = updated
            saveTemplates()
        }
    }

    // ==================== 模板管理 ====================

    /**
     * 创建新模板
     */
    fun createTemplate(
        name: String,
        description: String,
        taskPattern: String,
        keywords: List<String>,
        appName: String?,
        steps: List<WorkflowTemplate.WorkflowStep>
    ): WorkflowTemplate {
        initialize()

        val normalizedSteps = steps.map { step ->
            val toolName = normalizeToolName(step.toolName)
            if (toolName == step.toolName) step else step.copy(toolName = toolName)
        }

        val template = WorkflowTemplate(
            id = UUID.randomUUID().toString(),
            name = name,
            description = description,
            taskPattern = taskPattern,
            keywords = keywords,
            appName = appName,
            steps = normalizedSteps,
            createdAt = System.currentTimeMillis(),
            lastUsedAt = 0,
            successCount = 0,
            failCount = 0
        )

        templates[template.id] = template
        saveTemplates()

        XLog.i(TAG, "Created template: $name, id=${template.id}")
        return template
    }

    /**
     * 删除模板
     */
    fun deleteTemplate(templateId: String): Boolean {
        initialize()

        val removed = templates.remove(templateId)
        if (removed != null) {
            saveTemplates()
            XLog.i(TAG, "Deleted template: ${removed.name}")
            return true
        }
        return false
    }

    /**
     * 获取所有模板
     */
    fun getAllTemplates(): List<WorkflowTemplate> {
        initialize()
        return templates.values.toList().sortedByDescending { it.successCount }
    }

    /**
     * 获取模板
     */
    fun getTemplate(templateId: String): WorkflowTemplate? {
        initialize()
        return templates[templateId]
    }

    fun saveDraft(template: WorkflowTemplate): WorkflowTemplate? {
        if (template.status != TemplateStatus.DRAFT || template.executionMode != HYBRID_EXECUTION_MODE ||
            template.id.isBlank() || template.revision <= 0 || template.targetPackage.isBlank() ||
            !DeviceProfileProvider.isTrustedProfileId(template.targetProfileId)
        ) return null
        val draft = template.copy(
            status = TemplateStatus.DRAFT,
            successCount = 0,
            failCount = 0,
            lastUsedAt = 0L,
            activatedAt = 0L,
            degradedAt = 0L,
            degradedReason = "",
            steps = template.steps.map { it.copy(validatedResolvers = emptySet()) },
            validationState = ValidationState(
                profileId = template.targetProfileId,
                validatedRevision = template.revision
            )
        )
        initialize()
        synchronized(lifecycleLock) {
            if (templates.containsKey(draft.id)) return null
            templates[draft.id] = draft
            saveTemplates()
        }
        return draft
    }

    fun canRunHybridFastPath(template: WorkflowTemplate, freshProfileId: String): Boolean =
        template.executionMode == HYBRID_EXECUTION_MODE &&
            promotionCoordinator.match(template, freshProfileId) == MatchDecision.MATCH

    fun recordTemplateValidation(templateId: String, result: ValidationResult): WorkflowTemplate? =
        updateTemplateLifecycle(templateId, result.templateRevision) { template ->
            promotionCoordinator.recordValidation(template, result)
        }

    fun recordTemplateRuntimeFailure(
        templateId: String,
        revision: Int,
        profileId: String,
        errorCode: String
    ): WorkflowTemplate? = updateTemplateLifecycle(templateId, revision) { template ->
        promotionCoordinator.recordRuntimeFailure(template, profileId, revision, errorCode)
    }

    sealed interface DisableResult {
        data class Disabled(val template: WorkflowTemplate, val changed: Boolean) : DisableResult
        data object NotFound : DisableResult
        data class RevisionConflict(val currentRevision: Int) : DisableResult
    }

    fun disableTemplate(templateId: String, expectedRevision: Int? = null): DisableResult {
        initialize()
        synchronized(lifecycleLock) {
            val current = templates[templateId] ?: return DisableResult.NotFound
            if (current.status == TemplateStatus.DISABLED) return DisableResult.Disabled(current, changed = false)
            if (expectedRevision != null && (expectedRevision <= 0 || expectedRevision != current.revision)) {
                return DisableResult.RevisionConflict(current.revision)
            }
            val updated = applyRevisionBoundDisable(current, current.revision)
            templates[templateId] = updated
            saveTemplates()
            return DisableResult.Disabled(updated, changed = true)
        }
    }

    fun persistValidationRevision(template: WorkflowTemplate): Boolean {
        initialize()
        synchronized(lifecycleLock) {
            val current = templates[template.id] ?: return false
            if (current.revision != template.revision || current.status == TemplateStatus.DISABLED) return false
            templates[template.id] = template
            saveTemplates()
            return true
        }
    }

    private fun updateTemplateLifecycle(
        templateId: String,
        expectedRevision: Int,
        update: (WorkflowTemplate) -> WorkflowTemplate
    ): WorkflowTemplate? {
        initialize()
        synchronized(lifecycleLock) {
            val current = templates[templateId] ?: return null
            val updated = applyRevisionBoundLifecycleUpdate(current, expectedRevision, update)
            if (updated === current || updated == current) return current
            templates[templateId] = updated
            saveTemplates()
            return updated
        }
    }

    internal fun applyRevisionBoundLifecycleUpdate(
        current: WorkflowTemplate,
        expectedRevision: Int,
        update: (WorkflowTemplate) -> WorkflowTemplate
    ): WorkflowTemplate {
        if (expectedRevision <= 0 || current.revision != expectedRevision) return current
        return update(current)
    }

    internal fun applyRevisionBoundDisable(
        current: WorkflowTemplate,
        expectedRevision: Int
    ): WorkflowTemplate {
        if (current.status == TemplateStatus.DISABLED) return current
        if (expectedRevision <= 0 || current.revision != expectedRevision) return current
        return current.copy(
            status = TemplateStatus.DISABLED,
            validationState = current.validationState.copy(
                consecutiveSuccesses = 0,
                validatedResolvers = emptySet(),
                validatedResetIds = emptySet()
            )
        )
    }

    private fun validationProgress(state: ValidationState): String {
        val target = state.target.coerceAtLeast(1)
        return "${state.consecutiveSuccesses.coerceIn(0, target)}/$target"
    }

    /**
     * 清空所有模板
     */
    fun clearAllTemplates() {
        templates.clear()
        saveTemplates()
        XLog.i(TAG, "Cleared all templates")
    }

    // ==================== 模板学习 ====================

    /**
     * 从成功的Agent执行中学习模板
     * @param userPrompt 用户原始任务
     * @param toolCalls 工具调用历史
     * @param appName 目标应用名
     */
    fun learnFromExecution(
        userPrompt: String,
        toolCalls: List<ToolCallRecord>,
        appName: String?,
        success: Boolean
    ): WorkflowTemplate? {
        if (!success || toolCalls.isEmpty()) return null

        initialize()

        // 提取关键词
        val keywords = extractKeywords(userPrompt)

        // 生成任务模式（简化版）
        val taskPattern = generateTaskPattern(userPrompt, appName)
        val promptParams = inferParamsFromPrompt(userPrompt, appName)

        // 转换工具调用为步骤
        var inputTextIndex = 0
        val steps = toolCalls.map { call ->
            val toolName = normalizeToolName(call.toolName)
            val currentInputTextIndex = if (toolName == "input_text") inputTextIndex++ else -1
            WorkflowTemplate.WorkflowStep(
                toolName = toolName,
                paramsTemplate = parameterizeParams(toolName, call.params, promptParams, currentInputTextIndex),
                description = call.description ?: call.toolName,
                waitFor = call.waitFor,
                isVerification = call.isVerification,
                failureHandling = null
            )
        }

        // 检查是否已有相似模板
        val existing = findSimilarTemplate(taskPattern, keywords)
        if (existing != null) {
            // 已存在，更新统计而非新建
            val parameterized = ensureTemplateParameterized(existing)
            XLog.i(TAG, "Similar template exists: ${parameterized.name}, skipping creation")
            return parameterized
        }

        // 创建新模板
        val name = generateTemplateName(userPrompt, appName)
        val template = createTemplate(
            name = name,
            description = "从任务 \"$userPrompt\" 学习生成",
            taskPattern = taskPattern,
            keywords = keywords,
            appName = appName,
            steps = steps
        )

        XLog.i(TAG, "Learned template from execution: $name")
        return template
    }

    /**
     * 根据用户新 prompt 和外部传入参数，为模板执行准备最终参数。
     * 外部传入参数优先级更高；缺失的常见参数会从 prompt 中自动抽取。
     */
    fun resolveTemplateParams(
        template: WorkflowTemplate,
        userPrompt: String,
        providedParams: Map<String, String> = emptyMap()
    ): TemplateParamResolution {
        val inferredParams = inferParamsFromPrompt(userPrompt, template.appName)
        val merged = expandParamAliases(inferredParams + providedParams)
        return TemplateParamResolution(
            params = merged,
            missingParams = getMissingTemplateParams(template, merged)
        )
    }

    private fun getMissingTemplateParams(
        template: WorkflowTemplate,
        params: Map<String, String>
    ): List<String> {
        val expandedParams = expandParamAliases(params)
        return getTemplatePlaceholders(template)
            .filter { expandedParams[it].isNullOrBlank() }
            .sorted()
    }

    private fun getTemplatePlaceholders(template: WorkflowTemplate): Set<String> {
        return template.steps
            .flatMap { step -> step.paramsTemplate.values.flatMap { value -> extractPlaceholders(value) } }
            .toSet()
    }

    private fun extractPlaceholders(value: Any?): Set<String> {
        return when (value) {
            is String -> placeholderRegex.findAll(value).map { it.groupValues[1] }.toSet()
            is Map<*, *> -> value.values.flatMap { extractPlaceholders(it) }.toSet()
            is Iterable<*> -> value.flatMap { extractPlaceholders(it) }.toSet()
            else -> emptySet()
        }
    }

    private fun ensureTemplateParameterized(template: WorkflowTemplate): WorkflowTemplate {
        val sourcePrompt = learnedPromptRegex.find(template.description)?.groupValues?.getOrNull(1)
            ?: return template
        val promptParams = inferParamsFromPrompt(sourcePrompt, template.appName)

        var inputTextIndex = 0
        var changed = false
        val updatedSteps = template.steps.map { step ->
            val toolName = normalizeToolName(step.toolName)
            val currentInputTextIndex = if (toolName == "input_text") inputTextIndex++ else -1
            val paramsTemplate = parameterizeParams(
                toolName = toolName,
                params = step.paramsTemplate,
                promptParams = promptParams,
                inputTextIndex = currentInputTextIndex
            )
            if (toolName != step.toolName || paramsTemplate != step.paramsTemplate) {
                changed = true
                step.copy(toolName = toolName, paramsTemplate = paramsTemplate)
            } else {
                step
            }
        }

        if (!changed) return template

        val updated = template.copy(steps = updatedSteps)
        templates[updated.id] = updated
        saveTemplates()
        XLog.i(TAG, "Normalized learned template: ${updated.name}")
        return updated
    }

    private fun parameterizeParams(
        toolName: String,
        params: Map<String, Any>,
        promptParams: Map<String, String>,
        inputTextIndex: Int
    ): Map<String, Any> {
        if (promptParams.isEmpty()) return params

        return params.mapValues { (key, value) ->
            when (value) {
                is String -> parameterizeStringParam(toolName, key, value, promptParams, inputTextIndex)
                else -> value
            }
        }
    }

    private fun parameterizeStringParam(
        toolName: String,
        key: String,
        value: String,
        promptParams: Map<String, String>,
        inputTextIndex: Int
    ): String {
        if (!canParameterizeParam(key) || placeholderRegex.containsMatchIn(value)) {
            return value
        }

        findPlaceholderForValue(value, promptParams)?.let { placeholder ->
            return "\${$placeholder}"
        }

        // input_text 是最常见的变量承载点。遇到轻微格式差异时，用执行顺序兜底。
        if (toolName == "input_text" && key == "text") {
            val placeholder = when {
                promptParams.containsKey("contact_name") && promptParams.containsKey("message") && inputTextIndex == 0 -> "contact_name"
                promptParams.containsKey("contact_name") && promptParams.containsKey("message") && inputTextIndex == 1 -> "message"
                promptParams.containsKey("keyword") && inputTextIndex == 0 -> "keyword"
                else -> null
            }
            if (placeholder != null) {
                return "\${$placeholder}"
            }
        }

        return value
    }

    private fun canParameterizeParam(key: String): Boolean {
        return key in setOf("text", "keyword", "query", "message", "content", "contact_name", "target")
    }

    private fun findPlaceholderForValue(value: String, promptParams: Map<String, String>): String? {
        val normalizedValue = normalizeParamValue(value)
        if (normalizedValue.isEmpty()) return null

        for (key in canonicalParamOrder) {
            val paramValue = promptParams[key] ?: continue
            if (normalizeParamValue(paramValue) == normalizedValue) {
                return key
            }
        }

        return null
    }

    private fun inferParamsFromPrompt(prompt: String, appName: String?): Map<String, String> {
        val params = mutableMapOf<String, String>()

        for (pattern in messagePatterns) {
            val match = pattern.find(prompt) ?: continue
            val contact = cleanCapturedValue(match.groupValues.getOrNull(1).orEmpty())
            val message = cleanMessageValue(match.groupValues.getOrNull(2).orEmpty())
            if (contact.isNotEmpty() && message.isNotEmpty()) {
                params["contact_name"] = contact
                params["message"] = message
                break
            }
        }

        for (pattern in searchPatterns) {
            val match = pattern.find(prompt) ?: continue
            val keyword = cleanCapturedValue(match.groupValues.getOrNull(1).orEmpty())
            if (keyword.isNotEmpty()) {
                params["keyword"] = keyword
                break
            }
        }

        if (!appName.isNullOrBlank()) {
            params["app"] = appName
        }

        return expandParamAliases(params)
    }

    private fun cleanCapturedValue(value: String): String {
        return value.trim()
            .trim('"', '\'', '“', '”', '‘', '’')
            .trim()
    }

    private fun cleanMessageValue(value: String): String {
        var cleaned = cleanCapturedValue(value)
        val prefixes = listOf("说", "内容是", "内容为", "消息是", "消息为", "为", ":", "：")
        var changed: Boolean
        do {
            changed = false
            for (prefix in prefixes) {
                if (cleaned.startsWith(prefix)) {
                    cleaned = cleaned.removePrefix(prefix).trim()
                    changed = true
                }
            }
        } while (changed)
        return cleanCapturedValue(cleaned)
    }

    private fun normalizeParamValue(value: String): String {
        return cleanMessageValue(value).replace("\\s+".toRegex(), "")
    }

    private fun expandParamAliases(params: Map<String, String>): Map<String, String> {
        val expanded = params.toMutableMap()

        fun alias(from: String, to: String) {
            val value = expanded[from]
            if (!value.isNullOrBlank() && expanded[to].isNullOrBlank()) {
                expanded[to] = value
            }
        }

        alias("contact_name", "target")
        alias("target", "contact_name")
        alias("message", "content")
        alias("content", "message")
        alias("keyword", "query")
        alias("query", "keyword")
        alias("app", "app_name")
        alias("app_name", "app")

        return expanded
    }

    private fun normalizeToolName(toolName: String): String {
        return displayNameToToolName[toolName] ?: toolName
    }

    /**
     * 提取关键词
     */
    private fun extractKeywords(prompt: String): List<String> {
        val commonKeywords = listOf(
            "微信", "qq", "支付宝", "淘宝", "抖音", "微博", "美团",
            "发消息", "发送", "搜索", "打开", "查找", "联系人",
            "wechat", "message", "search", "open", "find", "contact"
        )
        return commonKeywords.filter { keyword ->
            prompt.lowercase().contains(keyword.lowercase())
        }
    }

    /**
     * 生成任务模式
     */
    private fun generateTaskPattern(prompt: String, appName: String?): String {
        val app = appName?.lowercase() ?: ""
        val promptLower = prompt.lowercase()

        // 常见模式
        if (promptLower.contains("发消息") || promptLower.contains("发送消息")) {
            return if (app.isNotEmpty()) "$app.*发消息" else ".*发消息"
        }
        if (promptLower.contains("搜索")) {
            return if (app.isNotEmpty()) "$app.*搜索" else ".*搜索"
        }
        if (promptLower.contains("打开")) {
            return if (app.isNotEmpty()) "打开$app" else "打开.*"
        }

        // 通用模式：取前几个关键词
        val words = prompt.split(" ", ",", "，", "。", "!", "！").filter { it.isNotBlank() }
        return if (words.isNotEmpty()) words.take(3).joinToString(".*") else prompt.take(20)
    }

    /**
     * 生成模板名称
     */
    private fun generateTemplateName(prompt: String, appName: String?): String {
        val app = appName ?: ""
        val shortPrompt = if (prompt.length > 30) prompt.take(30) + "..." else prompt
        return "$app - $shortPrompt"
    }

    /**
     * 查找相似模板
     */
    private fun findSimilarTemplate(taskPattern: String, keywords: List<String>): WorkflowTemplate? {
        return templates.values.find { template ->
            // 任务模式相似度 > 80%
            val patternSimilarity = calculatePatternSimilarity(template.taskPattern, taskPattern)
            // 关键词重叠 > 50%
            val keywordOverlap = if (keywords.isEmpty() || template.keywords.isEmpty()) 0f
            else keywords.count { template.keywords.contains(it) }.toFloat() / keywords.size

            patternSimilarity > 0.8f || keywordOverlap > 0.5f
        }
    }

    /**
     * 计算模式相似度（简单实现）
     */
    private fun calculatePatternSimilarity(pattern1: String, pattern2: String): Float {
        if (pattern1 == pattern2) return 1f
        if (pattern1.contains(pattern2) || pattern2.contains(pattern1)) return 0.8f

        val commonChars = pattern1.chars().filter { pattern2.contains(it.toChar()) }.count()
        val maxLen = maxOf(pattern1.length, pattern2.length)
        return if (maxLen == 0) 0f else commonChars.toFloat() / maxLen
    }

    /**
     * 工具调用记录（用于学习）
     */
    data class ToolCallRecord(
        val toolName: String,
        val params: Map<String, Any>,
        val description: String? = null,
        val waitFor: Int = 500,
        val isVerification: Boolean = false
    )
}
