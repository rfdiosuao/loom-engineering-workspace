package com.apk.claw.android.server

import android.os.Build
import android.app.KeyguardManager
import android.content.Context
import android.os.PowerManager
import android.provider.Settings
import com.apk.claw.android.BuildConfig
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.TaskStartNavigationPolicy
import com.apk.claw.android.agent.AgentCallback
import com.apk.claw.android.agent.AgentConfig
import com.apk.claw.android.agent.AgentExecutionMode
import com.apk.claw.android.agent.AgentExecutionPolicy
import com.apk.claw.android.agent.AgentRunOptions
import com.apk.claw.android.agent.AgentService
import com.apk.claw.android.agent.AgentServiceFactory
import com.apk.claw.android.agent.AgentToolPolicy
import com.apk.claw.android.agent.ActionFastExecutor
import com.apk.claw.android.agent.ActionFastTransitionPolicy
import com.apk.claw.android.agent.ScreenObservationBuilder
import com.apk.claw.android.server.CrashLogApiController
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.service.AccessibilityStateInspector
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.impl.InputTextTool
import com.apk.claw.android.tool.impl.OpenAppTool
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.reflect.TypeToken
import fi.iki.elonen.NanoHTTPD
import java.util.Locale
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Agent API 控制器
 * 提供外部 HTTP API 用于让 Agent 智能执行任务
 */
object AgentApiController {

    private const val TAG = "AgentApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private const val DEFAULT_TASK_TIMEOUT_SEC = 600L
    private const val MAX_TASK_TIMEOUT_SEC = 600L
    private const val DEFAULT_TASK_MAX_ROUNDS = 60
    private const val MAX_TASK_MAX_ROUNDS = 120
    private const val MAX_ASYNC_TASKS = 24
    private const val MAX_ACTIVE_ASYNC_TASKS = 12
    private const val ASYNC_WORKER_BUSY_WAIT_MS = 200L
    private val gson = Gson()

    // Agent 服务实例（独立于主 App 的 Agent）
    private var agentService: AgentService? = null

    // 任务执行锁，防止并发任务
    private val taskLock = Object()
    @Volatile
    private var isTaskRunning = false
    @Volatile
    private var asyncWorkerRunning = false
    private val asyncTasks = linkedMapOf<String, AsyncTaskState>()
    private val runtimeMetrics = PhoneRuntimeMetrics()

    private fun claimTaskSlotLocked(): Boolean {
        if (isTaskRunning) return false
        isTaskRunning = true
        return true
    }

    private fun releaseTaskSlotLocked() {
        isTaskRunning = false
    }

    private fun releasePreclaimedTaskSlotIfNeeded(preclaimedTaskSlot: Boolean) {
        if (preclaimedTaskSlot) {
            synchronized(taskLock) { releaseTaskSlotLocked() }
        }
    }

    /**
     * 验证 Token
     */
    fun checkAuth(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response? {
        if (!TokenValidator.validate(session)) {
            XLog.w(TAG, "Unauthorized API request from ${session.remoteIpAddress}")
            return jsonResponse(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                false,
                null,
                "Unauthorized: invalid or missing token"
            )
        }
        return null
    }

    /**
     * 处理执行任务请求
     * POST /api/agent/execute_task
     * Body: {"prompt": "打开微信", "use_template": true, "template_params": {"contact_name": "张三"}}
     *
     * 这是一个同步 API，会等待 Agent 完成任务后返回结果
     * 最长等待时间：600 秒
     *
     * 新增参数:
     * - use_template: 是否优先使用模板执行（默认 true）
     * - template_params: 模板参数（替换模板中的占位符）
     * - force_agent: 强制使用 Agent 执行，跳过模板匹配（默认 false）
     * - read_only: 严格只读模式，禁止 Agent 执行点击/输入/滑动/打开应用等动作（默认 false）
     * - tool_policy: observe_only / safe_action / full_access（默认 full_access；read_only=true 时强制 observe_only）
     */
    fun handleExecuteTask(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        return handleExecuteTaskInternal(session, preclaimedTaskSlot = false)
    }

    private fun handleExecuteTaskInternal(
        session: NanoHTTPD.IHTTPSession,
        preclaimedTaskSlot: Boolean
    ): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) {
            releasePreclaimedTaskSlotIfNeeded(preclaimedTaskSlot)
            return authError
        }
        val metrics = ApiMetrics("agent")

        // 检查无障碍服务
        val precheckStartedAt = System.currentTimeMillis()
        val accessibilityState = AccessibilityStateInspector.inspect(ClawApplication.instance)
        if (!accessibilityState.healthy) {
            metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)
            val message = accessibilityUnavailableMessage(accessibilityState)
            releasePreclaimedTaskSlotIfNeeded(preclaimedTaskSlot)
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData(accessibilityState.errorCode, message, metrics, accessibilityState),
                message
            )
        }

        // 检查 LLM 配置
        if (!KVUtils.hasLlmConfig()) {
            metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)
            releasePreclaimedTaskSlotIfNeeded(preclaimedTaskSlot)
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData("model_not_configured", "LLM not configured. Please configure LLM in Settings first.", metrics),
                "LLM not configured. Please configure LLM in Settings first."
            )
        }
        metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)

        // 检查是否有任务正在执行
        if (!preclaimedTaskSlot) {
            synchronized(taskLock) {
                if (!claimTaskSlotLocked()) {
                    return trackedJsonElementResponse(
                        NanoHTTPD.Response.Status.OK,
                        false,
                        failureData("task_busy", "A task is already running, please wait", metrics),
                        "A task is already running, please wait"
                    )
                }
            }
        }

        try {
        val json = ToolApiController.parseJsonBody(session)
        if (json == null) {
            synchronized(taskLock) { releaseTaskSlotLocked() }
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }
        val asyncTaskId = json.get("_async_task_id")?.asString
        val asyncTask = if (asyncTaskId.isNullOrBlank()) null else synchronized(taskLock) { asyncTasks[asyncTaskId] }

        val prompt = json.get("prompt")?.asString
        if (prompt.isNullOrEmpty()) {
            synchronized(taskLock) { releaseTaskSlotLocked() }
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing required parameter: prompt")
        }

        // 解析模板相关参数
        val useTemplate = json.get("use_template")?.asBoolean ?: true  // 默认优先使用模板
        val forceAgent = json.get("force_agent")?.asBoolean ?: false   // 强制 Agent 执行
        val learnTemplate = json.get("learn_template")?.asBoolean ?: false
        val readOnly = (json.get("read_only") ?: json.get("readOnly"))?.asBoolean ?: false
        val requestedToolPolicy = AgentToolPolicy.fromWireName(
            (json.get("tool_policy") ?: json.get("toolPolicy"))?.asString
        )
        val requestedMode = (json.get("mode") ?: json.get("taskMode"))?.asString
        val initialExecutionMode = AgentExecutionPolicy.resolveMode(requestedMode, requestedToolPolicy, readOnly)
        val toolPolicy = when {
            readOnly || initialExecutionMode == AgentExecutionMode.OBSERVE -> AgentToolPolicy.OBSERVE_ONLY
            initialExecutionMode == AgentExecutionMode.SAFE && requestedToolPolicy == AgentToolPolicy.FULL_ACCESS -> AgentToolPolicy.SAFE_ACTION
            else -> requestedToolPolicy
        }
        val executionMode = AgentExecutionPolicy.resolveMode(requestedMode, toolPolicy, readOnly)
        val effectiveReadOnly = readOnly || toolPolicy == AgentToolPolicy.OBSERVE_ONLY
        val requestedTimeoutSec = (
            json.get("timeout_sec")
                ?: json.get("timeoutSec")
                ?: json.get("max_wait_sec")
                ?: json.get("maxWaitSec")
            )?.asLong ?: DEFAULT_TASK_TIMEOUT_SEC
        val taskTimeoutSec = requestedTimeoutSec.coerceIn(30L, MAX_TASK_TIMEOUT_SEC)
        val requestedMaxRounds = (
            json.get("max_rounds")
                ?: json.get("maxRounds")
            )?.asInt
        val taskMaxRounds = AgentExecutionPolicy.resolveMaxRounds(requestedMaxRounds, executionMode)

        val templateParams = mutableMapOf<String, String>()
        if (json.has("template_params")) {
            val paramsObj = json.getAsJsonObject("template_params")
            paramsObj.entrySet().forEach { (key, value) ->
                if (value.isJsonPrimitive) {
                    templateParams[key] = value.asString
                }
            }
        }

        XLog.i(TAG, "Executing Agent task: $prompt, mode=${executionMode.wireName}, useTemplate=$useTemplate, forceAgent=$forceAgent, learnTemplate=$learnTemplate, readOnly=$effectiveReadOnly, toolPolicy=${toolPolicy.wireName}, timeoutSec=$taskTimeoutSec, maxRounds=$taskMaxRounds")

        // 1. 如果允许使用模板，先尝试模板匹配和执行
        var agentPrompt = prompt
        var templateFallbackReason: String? = null
        if (useTemplate && !forceAgent && toolPolicy != AgentToolPolicy.OBSERVE_ONLY) {
            val requestedTemplate = findRequestedTemplate(json)
            val matchedTemplate = requestedTemplate ?: WorkflowTemplateManager.matchTemplate(prompt)
            if (matchedTemplate != null && (requestedTemplate != null || matchedTemplate.successRate() >= 0.6f)) {
                val resolvedTemplateParams = WorkflowTemplateManager.resolveTemplateParams(
                    template = matchedTemplate,
                    userPrompt = prompt,
                    providedParams = templateParams
                )

                if (resolvedTemplateParams.missingParams.isEmpty()) {
                    XLog.i(TAG, "Using template: ${matchedTemplate.name}, successRate=${matchedTemplate.successRate()}, params=${resolvedTemplateParams.params}")
                    metrics.templateHit = true

                    // 显示悬浮窗运行状态
                    FloatingCircleManager.setRunningStateFromApi(1)

                    val templateResult = WorkflowTemplateManager.executeTemplate(matchedTemplate, resolvedTemplateParams.params)
                    metrics.addToolCall(templateResult.executionTimeMs)

                    if (templateResult.success) {
                        synchronized(taskLock) { releaseTaskSlotLocked() }
                        FloatingCircleManager.setSuccessState()
                        metrics.mode = "template"
                        metrics.rounds = 0
                        val data = JsonObject().apply {
                            addProperty("success", true)
                            addProperty("mode", "template")
                            addProperty("readOnly", false)
                            addProperty("toolPolicy", toolPolicy.wireName)
                            addProperty("templateId", templateResult.templateId)
                            addProperty("templateName", matchedTemplate.name)
                            addProperty("stepsExecuted", templateResult.stepsExecuted)
                            addProperty("stepsTotal", templateResult.stepsTotal)
                            addProperty("executionTimeMs", templateResult.executionTimeMs)
                            addProperty("answer", "任务完成")
                            addProperty("error", "")
                            add("metrics", metrics.toJson())
                            add("progress", JsonArray().apply {
                                add(JsonObject().apply {
                                    addProperty("type", "template_complete")
                                    addProperty("round", 0)
                                    addProperty("time", System.currentTimeMillis())
                                    addProperty("success", true)
                                    addProperty("message", "Template completed")
                                })
                            })
                            add("agentReport", PhoneAgentReportBuilder.fromTask(
                                status = "success",
                                prompt = prompt,
                                result = this,
                                error = null,
                                events = get("progress").asJsonArray,
                                queueMs = 0L,
                                queueDepth = 0,
                                queuePosition = null
                            ))
                        }

                        return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
                    }

                    val templateError = templateResult.errorMessage ?: "Template execution failed"
                    XLog.w(TAG, "Template failed, falling back to Agent: $templateError")
                    templateFallbackReason = "template_failed:${templateResult.stepsExecuted}/${templateResult.stepsTotal}:${templateError.take(180)}"
                    metrics.mode = "agent_fallback"
                    metrics.agentFallback = true
                    metrics.fallbackReason = templateFallbackReason
                    agentPrompt = "$prompt\n\n[Template fast path failed]\nTemplate: ${matchedTemplate.name}\nSteps: ${templateResult.stepsExecuted}/${templateResult.stepsTotal}\nError: $templateError\nContinue from the current screen and avoid repeating completed steps."
                } else {
                    XLog.i(
                        TAG,
                        "Template matched but params missing (${resolvedTemplateParams.missingParams.joinToString(", ")}), falling back to Agent"
                    )
                    templateFallbackReason = "template_params_missing:${resolvedTemplateParams.missingParams.joinToString(",").take(180)}"
                    metrics.templateHit = true
                    metrics.mode = "agent_fallback"
                    metrics.agentFallback = true
                    metrics.fallbackReason = templateFallbackReason
                }
            }
        }

        // 2. 模板不匹配或强制 Agent 执行 → 使用 Agent 执行

        // 初始化 Agent（如果需要）
        try {
            initAgentIfNeeded()
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to initialize Agent", e)
            synchronized(taskLock) { releaseTaskSlotLocked() }
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData("agent_init_failed", "Failed to initialize Agent: ${e.message}", metrics),
                "Failed to initialize Agent: ${e.message}"
            )
        }

        // 同步执行任务，等待完成
        val resultLatch = CountDownLatch(1)
        val resultRef = AtomicReference<TaskExecuteResult>()
        val agentEvents = mutableListOf<JsonObject>()

        fun recordAgentEvent(
            type: String,
            round: Int,
            toolId: String? = null,
            toolName: String? = null,
            parameters: String? = null,
            success: Boolean? = null,
            message: String? = null
        ) {
            synchronized(agentEvents) {
                if (agentEvents.size >= 80) {
                    agentEvents.removeAt(0)
                }
                agentEvents.add(JsonObject().apply {
                    addProperty("type", type)
                    addProperty("round", round)
                    addProperty("time", System.currentTimeMillis())
                    if (!toolId.isNullOrBlank()) addProperty("toolId", toolId)
                    if (!toolName.isNullOrBlank()) addProperty("toolName", toolName)
                    if (!parameters.isNullOrBlank()) addProperty("parameters", parameters.take(500))
                    if (success != null) addProperty("success", success)
                    if (!message.isNullOrBlank()) addProperty("message", message.take(500))
                })
            }
            asyncTask?.addEvent(type, round, toolId, toolName, parameters, success, message)
        }

        fun eventsJsonArray(): JsonArray {
            return JsonArray().apply {
                synchronized(agentEvents) {
                    agentEvents.forEach { add(it) }
                }
            }
        }
        if (!templateFallbackReason.isNullOrBlank()) {
            recordAgentEvent("template_fallback", 0, success = false, message = "${templateFallbackReason}; continuing with Agent fallback")
        }

        // 工具调用记录（用于学习模板）
        val toolCallRecords = mutableListOf<WorkflowTemplateManager.ToolCallRecord>()
        var detectedAppName: String? = null

        // 只有 full_access 保持旧行为回到桌面；受限策略不自动改变当前手机状态。
        if (TaskStartNavigationPolicy.shouldPressHomeBeforeHttpTask(toolPolicy)) {
            ClawAccessibilityService.getInstance()?.pressHome()
        }

        // 显示悬浮窗运行状态
        FloatingCircleManager.setRunningStateFromApi(1)

        agentService?.executeTask(agentPrompt, object : AgentCallback {
            override fun onLoopStart(round: Int) {
                XLog.d(TAG, "Agent loop start: round=$round")
                recordAgentEvent("loop_start", round)
                // 更新悬浮窗轮数
                FloatingCircleManager.setRunningStateFromApi(round)
            }

            override fun onContent(round: Int, content: String) {
                XLog.d(TAG, "Agent content: $content")
                recordAgentEvent("content", round, message = content)
            }

            override fun onToolCall(round: Int, toolId: String, toolName: String, parameters: String) {
                XLog.d(TAG, "Tool call: $toolName($toolId), params=$parameters")
                recordAgentEvent("tool_call", round, toolId = toolId, toolName = toolName, parameters = parameters)
                FloatingCircleManager.setAgentToolProgress(round, toolId)

                // 记录工具调用（用于学习模板）
                try {
                    val paramsMap: Map<String, Any> = if (parameters.isNotEmpty()) {
                        gson.fromJson(parameters, object : TypeToken<Map<String, Any>>() {}.type) ?: emptyMap()
                    } else {
                        emptyMap()
                    }

                    // 检测应用名
                    if (toolId == "open_app" && paramsMap.containsKey("package_name")) {
                        val packageName = paramsMap["package_name"] as String
                        detectedAppName = getAppNameFromPackage(packageName)
                    }

                    toolCallRecords.add(WorkflowTemplateManager.ToolCallRecord(
                        toolName = toolId,
                        params = paramsMap,
                        description = toolName,
                        waitFor = 500
                    ))
                } catch (e: Exception) {
                    XLog.w(TAG, "Failed to record tool call: ${e.message}")
                }
            }

            override fun onToolResult(round: Int, toolId: String, toolName: String, parameters: String, result: ToolResult) {
                XLog.d(TAG, "Tool result: $toolName, success=${result.isSuccess}")
                recordAgentEvent(
                    "tool_result",
                    round,
                    toolId = toolId,
                    toolName = toolName,
                    parameters = parameters,
                    success = result.isSuccess,
                    message = result.data ?: result.error
                )
            }

            override fun onComplete(round: Int, finalAnswer: String, totalTokens: Int) {
                XLog.i(TAG, "Task complete: rounds=$round, tokens=$totalTokens")
                recordAgentEvent("complete", round, success = true, message = finalAnswer)
                resultRef.set(TaskExecuteResult(success = true, answer = finalAnswer, rounds = round, tokens = totalTokens))
                synchronized(taskLock) { releaseTaskSlotLocked() }
                // 显示悬浮窗成功状态
                FloatingCircleManager.setSuccessState()
                resultLatch.countDown()

                // 学习模板（异步，不阻塞响应）
                val recordsToLearn = toolCallRecords.toList()
                val appNameToLearn = detectedAppName
                if (learnTemplate && recordsToLearn.isNotEmpty()) {
                    Thread({
                        try {
                            val learnedTemplate = WorkflowTemplateManager.learnFromExecution(
                                userPrompt = prompt,
                                toolCalls = recordsToLearn,
                                appName = appNameToLearn,
                                success = true
                            )
                            if (learnedTemplate != null) {
                                XLog.i(TAG, "Learned template: ${learnedTemplate.name}")
                            }
                        } catch (e: Exception) {
                            XLog.w(TAG, "Failed to learn template: ${e.message}")
                        }
                    }, "WorkflowTemplateLearning").apply {
                        isDaemon = true
                        start()
                    }
                }
            }

            override fun onError(round: Int, error: Exception, totalTokens: Int) {
                XLog.e(TAG, "Task error: ${error.message}")
                recordAgentEvent("error", round, success = false, message = error.message ?: "Unknown error")
                resultRef.set(TaskExecuteResult(success = false, error = error.message ?: "Unknown error", rounds = round, tokens = totalTokens))
                synchronized(taskLock) { releaseTaskSlotLocked() }
                // 显示悬浮窗错误状态
                FloatingCircleManager.setErrorState()
                resultLatch.countDown()
            }

            override fun onSystemDialogBlocked(round: Int, totalTokens: Int) {
                XLog.w(TAG, "System dialog blocked")
                recordAgentEvent("system_dialog_blocked", round, success = false, message = "System dialog blocked the screen")
                resultRef.set(TaskExecuteResult(success = false, error = "System dialog blocked the screen", rounds = round, tokens = totalTokens))
                synchronized(taskLock) { releaseTaskSlotLocked() }
                // 显示悬浮窗错误状态
                FloatingCircleManager.setErrorState()
                resultLatch.countDown()
            }

            override fun onMetrics(round: Int, llmRoundMs: Long, toolCallMs: Long) {
                metrics.rounds = maxOf(metrics.rounds, round)
                if (llmRoundMs > 0) metrics.addLlmRound(llmRoundMs)
                if (toolCallMs > 0) metrics.addToolCall(toolCallMs)
            }
        }, AgentRunOptions(readOnly = effectiveReadOnly, toolPolicy = toolPolicy, maxRounds = taskMaxRounds))

        // 等待任务完成；Lumi 可按任务传入 timeout_sec，避免复杂任务被短超时窗口截断。
        try {
            val completed = resultLatch.await(taskTimeoutSec, TimeUnit.SECONDS)
            if (!completed) {
                XLog.w(TAG, "Task timeout, cancelling")
                agentService?.cancel()
                synchronized(taskLock) { isTaskRunning = false }
                val timeoutMessage = "Task timeout (${taskTimeoutSec}s)"
                recordAgentEvent("timeout", -1, success = false, message = timeoutMessage)
                val timeoutData = JsonObject().apply {
                    addProperty("success", false)
                    addProperty("mode", metrics.mode)
                    addProperty("answer", "")
                    addProperty("error", timeoutMessage)
                    addProperty("errorCode", "timeout")
                    if (!templateFallbackReason.isNullOrBlank()) addProperty("fallbackReason", templateFallbackReason)
                    addProperty("rounds", 0)
                    addProperty("tokens", 0)
                    addProperty("readOnly", effectiveReadOnly)
                    addProperty("toolPolicy", toolPolicy.wireName)
                    addProperty("timeoutSec", taskTimeoutSec)
                    addProperty("maxRounds", taskMaxRounds)
                    add("events", eventsJsonArray())
                    metrics.rounds = 0
                    add("metrics", metrics.toJson())
                    add("agentReport", PhoneAgentReportBuilder.failure("timeout", timeoutMessage, "failed"))
                }
                return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, false, timeoutData, "Task timed out after ${taskTimeoutSec}s")
            }
        } catch (e: InterruptedException) {
            XLog.e(TAG, "Task interrupted", e)
            agentService?.cancel()
            synchronized(taskLock) { releaseTaskSlotLocked() }
            Thread.currentThread().interrupt()
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData("interrupted", "Task interrupted", metrics),
                "Task interrupted"
            )
        }

        val result = resultRef.get()
        val data = JsonObject().apply {
            addProperty("success", result.success)
            addProperty("mode", metrics.mode)
            addProperty("answer", result.answer ?: "")
            addProperty("error", result.error ?: "")
            if (!result.error.isNullOrBlank()) addProperty("errorCode", "agent_error")
            if (!templateFallbackReason.isNullOrBlank()) addProperty("fallbackReason", templateFallbackReason)
            addProperty("rounds", result.rounds)
            addProperty("tokens", result.tokens)
            addProperty("readOnly", effectiveReadOnly)
                addProperty("toolPolicy", toolPolicy.wireName)
                addProperty("maxRounds", taskMaxRounds)
                val finalEvents = eventsJsonArray()
                add("events", finalEvents)
                metrics.rounds = result.rounds
                add("metrics", metrics.toJson())
                add("agentReport", PhoneAgentReportBuilder.fromTask(
                    status = if (result.success) "success" else "error",
                    prompt = prompt,
                    result = this,
                    error = result.error,
                    events = finalEvents,
                    queueMs = 0L,
                    queueDepth = 0,
                    queuePosition = null
                ))
            }

        return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, result.success, data, null)
        } catch (t: Throwable) {
            XLog.e(TAG, "Unhandled Agent task exception: ${t.message}", t)
            CrashLogApiController.recordThrowable(ClawApplication.instance, "agent-execute-task", t)
            synchronized(taskLock) { releaseTaskSlotLocked() }
            FloatingCircleManager.setErrorState()
            val publicMessage = "Unhandled Agent runtime error: ${t.javaClass.simpleName}"
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData("agent_unhandled_exception", publicMessage, metrics),
                publicMessage
            )
        }
    }

    /**
     * 处理取消任务请求
     * POST /api/agent/cancel_task
     */
    fun handleCancelTask(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        synchronized(taskLock) {
            if (!isTaskRunning) {
                return jsonResponse(NanoHTTPD.Response.Status.OK, true, "No task running", null)
            }
        }

        agentService?.cancel()
        synchronized(taskLock) { releaseTaskSlotLocked() }

        XLog.i(TAG, "Task cancelled via API")
        return jsonResponse(NanoHTTPD.Response.Status.OK, true, "Task cancelled", null)
    }

    fun handleObserveFast(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val metrics = ApiMetrics("observe_fast")
        val precheckStartedAt = System.currentTimeMillis()
        val accessibilityState = AccessibilityStateInspector.inspect(ClawApplication.instance)
        val service = ClawAccessibilityService.getInstance()
        if (!accessibilityState.healthy || service == null) {
            metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)
            val message = accessibilityUnavailableMessage(accessibilityState)
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData(accessibilityState.errorCode, message, metrics, accessibilityState),
                message
            )
        }
        metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)

        val capturedAt = System.currentTimeMillis()
        val screenStartedAt = System.currentTimeMillis()
        val tree = service.screenTreeJson
        val screenTreeMs = System.currentTimeMillis() - screenStartedAt
        metrics.addScreenTree(screenTreeMs)
        if (tree == null) {
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData("system_dialog_blocked", "System dialog blocked the screen", metrics),
                "System dialog blocked the screen"
            )
        }

        val data = ScreenObservationBuilder.build(tree, capturedAt = capturedAt, durationMs = metrics.elapsedMs())
        val knownHash = firstQueryParam(session, "screenHash", "knownHash", "known_hash")
        val debug = queryBoolean(session, "debug") || queryBoolean(session, "full")
        val compactData = ScreenObservationBuilder.compactIfUnchanged(data, knownHash = knownHash, debug = debug)
        metrics.cacheHit = compactData.get("cacheHit")?.takeIf { it.isJsonPrimitive }?.asBoolean ?: false
        if (queryBoolean(session, "full")) {
            compactData.addProperty("full", true)
            compactData.add("fullTree", tree.deepCopy())
        }
        compactData.add("metrics", metrics.toJson())
        compactData.addProperty("durationMs", metrics.elapsedMs())
        return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, true, compactData, null)
    }

    fun handleActionFast(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val metrics = ApiMetrics("action_fast")
        val precheckStartedAt = System.currentTimeMillis()
        val accessibilityState = AccessibilityStateInspector.inspect(ClawApplication.instance)
        val service = ClawAccessibilityService.getInstance()
        if (!accessibilityState.healthy || service == null) {
            metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)
            val message = accessibilityUnavailableMessage(accessibilityState)
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                failureData(accessibilityState.errorCode, message, metrics, accessibilityState),
                message
            )
        }
        metrics.addPrecheck(System.currentTimeMillis() - precheckStartedAt)

        val json = ToolApiController.parseJsonBody(session)
            ?: return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                failureData("invalid_json", "Invalid JSON body", metrics),
                "Invalid JSON body"
            )
        val action = ActionFastExecutor.normalizeAction(getStringAny(json, "action", "type", "name"))
        if (action.isBlank()) {
            return trackedJsonElementResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                failureData("missing_action", "Missing required parameter: action", metrics),
                "Missing required parameter: action"
            )
        }
        val beforeObservedAt = service.currentPackageObservedAt
        val beforePackage = runCatching { service.currentPackageName }.getOrNull()
        val observeAfter = getBooleanAny(json, "observeAfter", "observe_after") ?: true
        val beforeObservation = readFastObservation(service, metrics)
        val beforeHash = jsonStringOrEmpty(beforeObservation, "screenHash")
        val safetyText = listOf(
            ActionFastExecutor.safetyTextFrom(json),
            refSafetyTextFromObservation(ActionFastExecutor.refFrom(json), beforeObservation)
        ).filter { it.isNotBlank() }.joinToString(" ")
        ActionFastExecutor.rejectDangerous(action, safetyText)?.let { reason ->
            val blocked = failureData("safety_blocked", reason, metrics)
            blocked.addProperty("action", action)
            blocked.addProperty("beforeHash", beforeHash)
            blocked.add("events", fastActionEvents("blocked", action, false, reason))
            return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, false, blocked, reason)
        }

        val toolStartedAt = System.currentTimeMillis()
        val result = try {
            executeFastAction(service, json, action)
        } catch (e: IllegalArgumentException) {
            ToolResult.error(e.message ?: "Invalid action_fast parameters")
        } catch (t: Throwable) {
            XLog.e(TAG, "action_fast failed: ${t.message}", t)
            ToolResult.error(t.message ?: "action_fast failed")
        }
        val actionMs = System.currentTimeMillis() - toolStartedAt
        metrics.addToolCall(actionMs)
        val verifyStartedAt = System.currentTimeMillis()
        val transitionStable = if (result.isSuccess && ActionFastTransitionPolicy.requiresStablePostObserve(action)) {
            waitForSystemActionTransition(service, beforeObservedAt, beforePackage)
        } else {
            true
        }
        val afterObservation = readFastObservation(service, metrics)
        val verifyMs = System.currentTimeMillis() - verifyStartedAt
        metrics.actionVerifyMs += verifyMs
        val afterHash = jsonStringOrEmpty(afterObservation, "screenHash")
        val changed = beforeHash.isNotBlank() && afterHash.isNotBlank() && beforeHash != afterHash
        val stepResult = ActionFastTransitionPolicy.currentStepAfterAction(
            action = action,
            actionSucceeded = result.isSuccess,
            transitionStable = transitionStable
        )
        val events = fastActionEvents(
            if (stepResult.currentStep == "transition_pending") "transition_pending" else if (result.isSuccess) "completed" else "failed",
            action,
            result.isSuccess,
            result.data ?: result.error
        )
        val data = JsonObject().apply {
            addProperty("mode", "action_fast")
            addProperty("action", action)
            addProperty("success", result.isSuccess)
            addProperty("actionMs", actionMs)
            addProperty("verifyMs", verifyMs)
            addProperty("beforeHash", beforeHash)
            addProperty("afterHash", afterHash)
            addProperty("changed", changed)
            addProperty("currentStep", stepResult.currentStep)
            addProperty("message", result.data ?: "")
            addProperty("retryable", stepResult.retryable)
            if (stepResult.currentStep == "transition_pending") {
                addProperty("transitionPending", true)
                addProperty("message", "${result.data ?: "Action completed"}; screen transition is still pending, re-observe before using post-action state.")
            }
            if (!result.isSuccess) {
                addProperty("error", result.error ?: "Action failed")
                addProperty("errorCode", "action_failed")
                addProperty("message", result.error ?: "Action failed")
            }
            add("events", events)
        }

        if (observeAfter) {
            afterObservation?.let { observed ->
                data.addProperty("screenHash", jsonStringOrEmpty(observed, "screenHash"))
                data.addProperty("summary", jsonStringOrEmpty(observed, "summary"))
                data.addProperty("currentPackage", jsonStringOrEmpty(observed, "currentPackage"))
            }
        }
        data.add("metrics", metrics.toJson())
        data.add("agentReport", PhoneAgentReportBuilder.fromTask(
            status = if (result.isSuccess) "success" else "error",
            prompt = action,
            result = data,
            error = result.error,
            events = events,
            queueMs = 0L,
            queueDepth = 0,
            queuePosition = null
        ))
        return trackedJsonElementResponse(NanoHTTPD.Response.Status.OK, result.isSuccess, data, result.error)
    }

    fun handleCreateAsyncTask(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        val prompt = json.get("prompt")?.asString
        if (prompt.isNullOrBlank()) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing required parameter: prompt")
        }

        val taskId = UUID.randomUUID().toString()
        val priority = getIntAny(json, "priority")?.coerceIn(-100, 100) ?: 0
        json.addProperty("_async_task_id", taskId)
        val bodyBytes = json.toString().toByteArray(Charsets.UTF_8)
        val task = AsyncTaskState(
            id = taskId,
            prompt = prompt,
            bodyBytes = bodyBytes,
            sourceSession = session,
            priority = priority
        )
        synchronized(taskLock) {
            pruneAsyncTasksLocked()
            val items = queueItemsLocked()
            if (!AgentTaskQueuePolicy.canAcceptNewTask(items, MAX_ACTIVE_ASYNC_TASKS)) {
                val metrics = ApiMetrics("queue")
                return trackedJsonElementResponse(
                    NanoHTTPD.Response.Status.OK,
                    false,
                    failureData(
                        "task_queue_full",
                        "APKClaw task queue is full; retry after a running or queued task finishes",
                        metrics
                    ),
                    "APKClaw task queue is full; retry later"
                )
            }
            asyncTasks[taskId] = task
            pruneAsyncTasksLocked()
        }
        task.addEvent("submitted", 0, message = "Task accepted by APKClaw")
        ensureAsyncWorker()

        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, taskJson(task, includeEvents = true), null)
    }

    fun handleGetAsyncTask(session: NanoHTTPD.IHTTPSession, taskId: String): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError
        val task = synchronized(taskLock) { asyncTasks[taskId] }
            ?: return jsonResponse(NanoHTTPD.Response.Status.NOT_FOUND, false, null, "Task not found")
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, taskJson(task, includeEvents = true), null)
    }

    fun handleGetAsyncTaskEvents(session: NanoHTTPD.IHTTPSession, taskId: String): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError
        val task = synchronized(taskLock) { asyncTasks[taskId] }
            ?: return jsonResponse(NanoHTTPD.Response.Status.NOT_FOUND, false, null, "Task not found")
        val eventArray = task.eventsJsonArray()
        val data = JsonObject().apply {
            addProperty("taskId", task.id)
            addProperty("status", task.status)
            addProperty("cancelRequested", task.cancelRequested)
            add("events", eventArray)
            AgentProgressLogBuilder.attachTo(this, eventArray)
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleCancelAsyncTask(session: NanoHTTPD.IHTTPSession, taskId: String): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError
        val task = synchronized(taskLock) { asyncTasks[taskId] }
            ?: return jsonResponse(NanoHTTPD.Response.Status.NOT_FOUND, false, null, "Task not found")

        if (!AgentTaskQueuePolicy.canCancel(task.status)) {
            return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, taskJson(task, includeEvents = true), null)
        }
        task.cancelRequested = true
        if (task.status == "queued") {
            task.status = "cancelled"
            task.finishedAt = System.currentTimeMillis()
            task.error = "cancelled"
            task.addEvent("cancelled", -1, success = false, message = "Queued task cancelled via API")
            runtimeMetrics.record(
                PhoneRuntimeMetricEvent(
                    mode = "cancelled",
                    success = false,
                    errorCode = "cancelled",
                    reason = "queued task cancelled"
                )
            )
        } else {
            agentService?.cancel()
            task.addEvent("cancel_requested", -1, success = false, message = "Running task cancellation requested via API")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, taskJson(task, includeEvents = true), null)
    }

    /**
     * 处理获取状态请求
     * GET /api/agent/status
     */
    fun handleGetStatus(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, statusSnapshot(), null)
    }

    fun statusSnapshot(): JsonObject {
        val accessibilityState = AccessibilityStateInspector.inspect(ClawApplication.instance)
        val accessibilityRunning = accessibilityState.boundToProcess
        val queueDepth = synchronized(taskLock) { asyncQueueDepthLocked() }
        val currentTaskId = synchronized(taskLock) { currentAsyncTaskIdLocked() }
        return JsonObject().apply {
            addProperty("taskRunning", synchronized(taskLock) { isTaskRunning })
            addProperty("busy", synchronized(taskLock) { isTaskRunning || currentTaskId != null })
            addProperty("queueSupported", true)
            addProperty("queueDepth", queueDepth)
            if (!currentTaskId.isNullOrBlank()) addProperty("currentTaskId", currentTaskId)
            addProperty("agentInitialized", agentService != null)
            addProperty("llmConfigured", KVUtils.hasLlmConfig())
            addProperty("accessibilityRunning", accessibilityRunning)
            addAccessibilityStateProperties(this, accessibilityState)
            addProperty("screenshotSupported", accessibilityState.healthy && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R)
            addProperty("screenInfoSupported", accessibilityState.healthy)
            addProperty("overlayPermission", Settings.canDrawOverlays(ClawApplication.instance))
            addProperty("cursorOverlayEnabled", FloatingCircleManager.isShowing())
            addProperty("cursorPreviewSupported", true)
            val wakeState = getWakeState()
            addProperty("screenOn", wakeState.screenOn)
            addProperty("interactive", wakeState.interactive)
            addProperty("keyguardLocked", wakeState.keyguardLocked)
            addProperty("deviceLocked", wakeState.deviceLocked)
            val accessibilityService = ClawAccessibilityService.getInstance()
            val currentPackage = accessibilityService?.currentPackageName.orEmpty()
            if (currentPackage.isNotBlank()) {
                addProperty("currentPackage", currentPackage)
                addProperty("currentPackageObservedAt", accessibilityService?.currentPackageObservedAt ?: 0L)
            }
            addProperty("version", BuildConfig.VERSION_NAME)
            addProperty("versionCode", BuildConfig.VERSION_CODE)
            addProperty("versionInfo", BuildConfig.VERSION_INFO)
            addProperty("serverTime", System.currentTimeMillis())
            ConfigServerStatusBuilder.addTo(
                target = this,
                running = ConfigServerManager.isRunning(),
                address = ConfigServerManager.getAddress(),
                actualPort = ConfigServerManager.getPort(),
                defaultPort = ConfigServer.PORT
            )
            // 手机当前时间,供启动器计算"手机↔电脑时钟偏差",用手机时钟签名 Lumi 请求,
            // 客户手机时间不准也不会导致签名 403。
            addProperty("serverTime", System.currentTimeMillis())
        }

    }

    fun handleGetMetrics(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, runtimeMetricsSnapshot(), null)
    }

    fun eventStreamSnapshot(): JsonObject {
        return PhoneEventStreamController.snapshotEvent(
            status = statusSnapshot(),
            metrics = runtimeMetricsSnapshot(),
            tasks = recentTaskSnapshots(limit = 5)
        )
    }

    /**
     * POST /api/device/wake
     * Wakes the screen for incoming Lumi tasks. This does not bypass secure lock screens.
     */
    fun handleWakeDevice(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError
        consumeOptionalBody(session)

        val before = getWakeState()
        var wakeAttempted = false
        var wakeRequested = false
        if (!before.interactive || !before.screenOn) {
            wakeAttempted = true
            wakeRequested = wakeScreen()
            try {
                Thread.sleep(600)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        val after = getWakeState()

        val data = JsonObject().apply {
            addProperty("wakeAttempted", wakeAttempted)
            addProperty("wakeRequested", wakeRequested)
            addProperty("screenOn", after.screenOn)
            addProperty("interactive", after.interactive)
            addProperty("keyguardLocked", after.keyguardLocked)
            addProperty("deviceLocked", after.deviceLocked)
            addProperty(
                "message",
                when {
                    after.keyguardLocked || after.deviceLocked -> "Screen is awake, but the device is locked. Please unlock it before running tasks."
                    after.interactive || after.screenOn -> "Screen is awake and ready."
                    else -> "Wake request sent, but the screen is still not interactive."
                }
            )
            add("before", before.toJson())
            add("after", after.toJson())
        }

        return jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            after.interactive || after.screenOn,
            data,
            if (after.interactive || after.screenOn) null else "Failed to wake screen"
        )
    }

    private fun consumeOptionalBody(session: NanoHTTPD.IHTTPSession) {
        val contentLength = session.headers["content-length"]?.toIntOrNull()
            ?: session.headers["Content-Length"]?.toIntOrNull()
            ?: 0
        if (contentLength <= 0) return
        try {
            val buffer = ByteArray(1024)
            var remaining = contentLength
            while (remaining > 0) {
                val read = session.inputStream.read(buffer, 0, minOf(buffer.size, remaining))
                if (read <= 0) break
                remaining -= read
            }
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to consume optional wake body: ${e.message}")
        }
    }

    private fun wakeScreen(durationMs: Long = 4000L): Boolean {
        return try {
            val powerManager = ClawApplication.instance.getSystemService(Context.POWER_SERVICE) as? PowerManager
                ?: return false
            @Suppress("DEPRECATION")
            val wakeLock = powerManager.newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
                "AgentPhone:ApiWake"
            )
            wakeLock.setReferenceCounted(false)
            wakeLock.acquire(durationMs)
            XLog.i(TAG, "Wake screen requested via API")
            true
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to wake screen: ${e.message}")
            false
        }
    }

    private fun getWakeState(): WakeState {
        val context = ClawApplication.instance
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val keyguardManager = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val interactive = powerManager?.isInteractive ?: true
        val screenOn = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT_WATCH) {
            powerManager?.isInteractive ?: interactive
        } else {
            @Suppress("DEPRECATION")
            powerManager?.isScreenOn ?: interactive
        }
        val keyguardLocked = keyguardManager?.isKeyguardLocked ?: false
        val deviceLocked = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            keyguardManager?.isDeviceLocked ?: keyguardLocked
        } else {
            keyguardLocked
        }
        return WakeState(screenOn, interactive, keyguardLocked, deviceLocked)
    }

    private data class WakeState(
        val screenOn: Boolean,
        val interactive: Boolean,
        val keyguardLocked: Boolean,
        val deviceLocked: Boolean
    ) {
        fun toJson(): JsonObject {
            return JsonObject().apply {
                addProperty("screenOn", screenOn)
                addProperty("interactive", interactive)
                addProperty("keyguardLocked", keyguardLocked)
                addProperty("deviceLocked", deviceLocked)
            }
        }
    }

    private fun initAgentIfNeeded() {
        if (agentService == null) {
            agentService = AgentServiceFactory.create()
            val config = getAgentConfig()
            agentService?.initialize(config)
            XLog.i(TAG, "Agent initialized for API")
        } else {
            // 更新配置
            val config = getAgentConfig()
            agentService?.updateConfig(config)
        }
    }

    private fun getAgentConfig(): AgentConfig {
        var baseUrl = KVUtils.getLlmBaseUrl().trim()
        if (baseUrl.isEmpty()) baseUrl = "https://api.openai.com/v1"
        return AgentConfig.Builder()
            .apiKey(KVUtils.getLlmApiKey())
            .baseUrl(baseUrl)
            .modelName(KVUtils.getLlmModelName())
            .temperature(0.1)
            .maxIterations(AgentExecutionPolicy.defaultMaxRounds(AgentExecutionMode.FULL))
            .build()
    }

    private fun jsonResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: String?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) addProperty("data", data)
            if (error != null) addProperty("error", error)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }

    private fun jsonElementResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonElement?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) add("data", data)
            if (error != null) addProperty("error", error)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }

    private fun trackedJsonElementResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonObject,
        error: String?
    ): NanoHTTPD.Response {
        runtimeMetrics.record(PhoneRuntimeMetrics.eventFromResult(success = success, data = data))
        return jsonElementResponse(status, success, data, error)
    }

    private fun queueItemsLocked(): List<AgentTaskQueuePolicy.Item> {
        return asyncTasks.values.map { task ->
            AgentTaskQueuePolicy.Item(
                id = task.id,
                status = task.status,
                priority = task.priority,
                createdAt = task.createdAt
            )
        }
    }

    private fun currentAsyncTaskIdLocked(): String? {
        return asyncTasks.values.firstOrNull { it.status == "running" }?.id
    }

    private fun asyncQueueDepthLocked(): Int {
        return AgentTaskQueuePolicy.queueDepth(queueItemsLocked())
    }

    private fun recentTaskSnapshots(limit: Int): List<JsonObject> {
        synchronized(taskLock) {
            val items = queueItemsLocked()
            val queueDepth = AgentTaskQueuePolicy.queueDepth(items)
            val currentTaskId = currentAsyncTaskIdLocked()
            return asyncTasks.values
                .sortedWith(
                    compareByDescending<AsyncTaskState> { it.status == "running" }
                        .thenByDescending { it.createdAt }
                )
                .take(limit.coerceIn(1, 20))
                .map { task ->
                    AgentTaskPublicSnapshot.sanitize(
                        task.toJson(
                            includeEvents = false,
                            queueDepth = queueDepth,
                            queuePosition = AgentTaskQueuePolicy.queuePosition(items, task.id),
                            currentTaskId = currentTaskId,
                        )
                    )
                }
        }
    }

    private fun taskJson(task: AsyncTaskState, includeEvents: Boolean): JsonObject {
        synchronized(taskLock) {
            val items = queueItemsLocked()
            return task.toJson(
                includeEvents = includeEvents,
                queueDepth = AgentTaskQueuePolicy.queueDepth(items),
                queuePosition = AgentTaskQueuePolicy.queuePosition(items, task.id),
                currentTaskId = currentAsyncTaskIdLocked(),
            )
        }
    }

    private fun runtimeMetricsSnapshot(): JsonObject {
        synchronized(taskLock) {
            return runtimeMetrics.snapshot(
                queueDepth = asyncQueueDepthLocked(),
                currentTaskId = currentAsyncTaskIdLocked(),
                busy = isTaskRunning || currentAsyncTaskIdLocked() != null,
            )
        }
    }

    private fun pruneAsyncTasksLocked() {
        if (asyncTasks.size <= MAX_ASYNC_TASKS) return
        val removable = asyncTasks.values
            .filter { it.status !in setOf("queued", "running") }
            .sortedBy { it.finishedAt ?: it.createdAt }
        val removeCount = asyncTasks.size - MAX_ASYNC_TASKS
        removable.take(removeCount).forEach { asyncTasks.remove(it.id) }
    }

    private fun ensureAsyncWorker() {
        synchronized(taskLock) {
            if (asyncWorkerRunning) return
            asyncWorkerRunning = true
        }
        Thread({
            runAsyncWorkerLoop()
        }, "LumiAgentTaskQueue").apply {
            isDaemon = true
            start()
        }
    }

    private fun runAsyncWorkerLoop() {
        while (true) {
            val task = synchronized(taskLock) {
                val nextId = AgentTaskQueuePolicy.nextQueuedId(queueItemsLocked())
                if (nextId == null) {
                    asyncWorkerRunning = false
                    return
                }
                val nextTask = asyncTasks[nextId] ?: return@synchronized null
                if (!claimTaskSlotLocked()) {
                    null
                } else nextTask.also {
                    it.status = "running"
                    it.startedAt = System.currentTimeMillis()
                }
            }
            if (task == null) {
                try {
                    Thread.sleep(ASYNC_WORKER_BUSY_WAIT_MS)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    synchronized(taskLock) { asyncWorkerRunning = false }
                    return
                }
                continue
            }
            task.addEvent("running", 0, message = "Task worker started")
            try {
                val response = handleExecuteTaskInternal(
                    CachedBodySession(task.sourceSession, task.bodyBytes),
                    preclaimedTaskSlot = true
                )
                val text = response.data.bufferedReader(Charsets.UTF_8).use { it.readText() }
                task.rawResponse = text
                val payload = gson.fromJson(text, JsonObject::class.java)
                val success = payload?.get("success")?.asBoolean ?: false
                val data = payload?.get("data")?.takeIf { it.isJsonObject }?.asJsonObject
                task.result = data
                val finalEvents = data?.get("events")?.takeIf { it.isJsonArray }?.asJsonArray
                if (finalEvents != null) task.replaceEvents(finalEvents)
                task.error = payload?.get("error")?.asString ?: data?.get("error")?.asString
                if (task.cancelRequested) {
                    task.status = "cancelled"
                    task.error = "cancelled"
                    task.addEvent("cancelled", -1, success = false, message = "Task stopped after cancellation request")
                } else {
                    task.status = if (success) "success" else "error"
                }
                task.finishedAt = System.currentTimeMillis()
            } catch (t: Throwable) {
                XLog.e(TAG, "Async Agent task failed: ${t.message}", t)
                CrashLogApiController.recordThrowable(ClawApplication.instance, "async-agent-task", t)
                synchronized(taskLock) { releaseTaskSlotLocked() }
                task.error = t.message ?: "Async task failed"
                task.status = if (task.cancelRequested) "cancelled" else "error"
                task.finishedAt = System.currentTimeMillis()
                task.addEvent(task.status, -1, success = false, message = task.error)
            }
        }
    }

    private class AsyncTaskState(
        val id: String,
        val prompt: String,
        val bodyBytes: ByteArray,
        val sourceSession: NanoHTTPD.IHTTPSession,
        val priority: Int
    ) {
        @Volatile var status: String = "queued"
        @Volatile var cancelRequested: Boolean = false
        @Volatile var startedAt: Long? = null
        @Volatile var finishedAt: Long? = null
        @Volatile var error: String? = null
        @Volatile var result: JsonObject? = null
        @Volatile var rawResponse: String? = null
        val createdAt: Long = System.currentTimeMillis()
        private val events = mutableListOf<JsonObject>()

        fun addEvent(
            type: String,
            round: Int,
            toolId: String? = null,
            toolName: String? = null,
            parameters: String? = null,
            success: Boolean? = null,
            message: String? = null
        ) {
            synchronized(events) {
                if (events.size >= 100) events.removeAt(0)
                events.add(JsonObject().apply {
                    addProperty("type", type)
                    addProperty("round", round)
                    addProperty("time", System.currentTimeMillis())
                    if (!toolId.isNullOrBlank()) addProperty("toolId", toolId)
                    if (!toolName.isNullOrBlank()) addProperty("toolName", toolName)
                    if (!parameters.isNullOrBlank()) addProperty("parameters", parameters.take(500))
                    if (success != null) addProperty("success", success)
                    if (!message.isNullOrBlank()) addProperty("message", message.take(500))
                })
            }
        }

        fun replaceEvents(nextEvents: JsonArray) {
            synchronized(events) {
                events.clear()
                nextEvents.forEach { event ->
                    if (event.isJsonObject) events.add(event.asJsonObject)
                }
            }
        }

        fun eventsJsonArray(): JsonArray {
            return JsonArray().apply {
                synchronized(events) {
                    events.forEach { add(it) }
                }
            }
        }

        fun toJson(
            includeEvents: Boolean,
            queueDepth: Int,
            queuePosition: Int?,
            currentTaskId: String?
        ): JsonObject {
            val now = System.currentTimeMillis()
            val queueMs = ((startedAt ?: finishedAt ?: now) - createdAt).coerceAtLeast(0L)
            val eventArray = eventsJsonArray()
            return JsonObject().apply {
                addProperty("taskId", id)
                addProperty("status", status)
                addProperty("prompt", prompt.take(300))
                addProperty("priority", priority)
                addProperty("createdAt", createdAt)
                addProperty("queueMs", queueMs)
                addProperty("queueDepth", queueDepth)
                addProperty("cancelRequested", cancelRequested)
                if (queuePosition != null) addProperty("queuePosition", queuePosition)
                if (!currentTaskId.isNullOrBlank()) addProperty("currentTaskId", currentTaskId)
                if (startedAt != null) addProperty("startedAt", startedAt)
                if (finishedAt != null) addProperty("finishedAt", finishedAt)
                if (!error.isNullOrBlank()) addProperty("error", error)
                result?.let { add("result", it) }
                result?.get("metrics")?.let { add("metrics", it) }
                result?.get("mode")?.takeIf { it.isJsonPrimitive }?.let { add("mode", it) }
                result?.get("screenHash")?.takeIf { it.isJsonPrimitive }?.let { add("screenHash", it) }
                add("agentReport", PhoneAgentReportBuilder.fromTask(
                    status = status,
                    prompt = prompt,
                    result = result,
                    error = error,
                    events = eventArray,
                    queueMs = queueMs,
                    queueDepth = queueDepth,
                    queuePosition = queuePosition
                ))
                AgentProgressLogBuilder.attachTo(this, eventArray)
                if (includeEvents) add("events", eventArray)
            }
        }
    }

    private class ApiMetrics(initialMode: String) {
        private val startedAt = System.currentTimeMillis()
        var mode: String = initialMode
        var precheckMs: Long = 0L
        var screenTreeMs: Long = 0L
        var screenshotMs: Long = 0L
        var llmRoundMs: Long = 0L
        var toolCallMs: Long = 0L
        var actionVerifyMs: Long = 0L
        var cacheHit: Boolean = false
        var templateHit: Boolean = false
        var agentFallback: Boolean = false
        var fallbackReason: String? = null
        var rounds: Int = 0

        fun elapsedMs(): Long = (System.currentTimeMillis() - startedAt).coerceAtLeast(0L)

        fun addPrecheck(value: Long) {
            precheckMs += value.coerceAtLeast(0L)
        }

        fun addScreenTree(value: Long) {
            screenTreeMs += value.coerceAtLeast(0L)
        }

        fun addLlmRound(value: Long) {
            llmRoundMs += value.coerceAtLeast(0L)
        }

        fun addToolCall(value: Long) {
            toolCallMs += value.coerceAtLeast(0L)
        }

        fun toJson(): JsonObject {
            return JsonObject().apply {
                addProperty("totalMs", elapsedMs())
                addProperty("precheckMs", precheckMs)
                addProperty("screenTreeMs", screenTreeMs)
                addProperty("screenshotMs", screenshotMs)
                addProperty("llmRoundMs", llmRoundMs)
                addProperty("toolCallMs", toolCallMs)
                addProperty("actionVerifyMs", actionVerifyMs)
                addProperty("cacheHit", cacheHit)
                addProperty("templateHit", templateHit)
                addProperty("agentFallback", agentFallback)
                if (!fallbackReason.isNullOrBlank()) addProperty("fallbackReason", fallbackReason)
                addProperty("rounds", rounds)
                addProperty("mode", mode)
            }
        }
    }

    private fun executeFastAction(
        service: ClawAccessibilityService,
        json: JsonObject,
        action: String
    ): ToolResult {
        return when (action) {
            "click_text" -> clickTextFast(service, requiredStringAny(json, "text", "targetText", "target_text", "label"))
            "click_description", "click_element" -> clickTargetFast(
                service,
                ActionFastExecutor.clickTargetFrom(json)
                    ?: throw IllegalArgumentException("Missing required parameter: text, contentDescription, or resourceId")
            )
            "click_node" -> clickNodeFast(service, requiredStringAny(json, "nodeId", "node_id", "id"))
            "click_ref" -> clickRefFast(
                service,
                ActionFastExecutor.refFrom(json)
                    ?: throw IllegalArgumentException("Missing required parameter: ref")
            )
            "tap" -> {
                val x = getIntAny(json, "x", "centerX", "center_x")
                    ?: return ToolResult.error("Missing required parameter: x")
                val y = getIntAny(json, "y", "centerY", "center_y")
                    ?: return ToolResult.error("Missing required parameter: y")
                val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 100
                if (service.performTap(x, y, durationMs.toLong())) {
                    ToolResult.success("Tapped at ($x, $y)")
                } else {
                    ToolResult.error("Failed to tap at ($x, $y)")
                }
            }
            "input" -> {
                val text = requiredStringAny(json, "text", "value", "input")
                val clearFirst = getBooleanAny(json, "clearFirst", "clear_first") ?: true
                InputTextTool().execute(mapOf("text" to text, "clear_first" to clearFirst))
            }
            "open_app" -> {
                val packageName = requiredStringAny(json, "packageName", "package_name", "package")
                val verifyForeground = getBooleanAny(json, "verifyForeground", "verify_foreground") ?: true
                val checkLaunchDialog = getBooleanAny(json, "checkLaunchDialog", "check_launch_dialog", "dialogCheck", "dialog_check") ?: true
                val forceReopen = getBooleanAny(json, "forceReopen", "force_reopen") ?: false
                OpenAppTool().execute(mapOf(
                    "package_name" to packageName,
                    "verify_foreground" to verifyForeground,
                    "check_launch_dialog" to checkLaunchDialog,
                    "force_reopen" to forceReopen
                ))
            }
            "back" -> if (service.pressBack()) ToolResult.success("Pressed back") else ToolResult.error("Failed to press back")
            "home" -> if (service.pressHome()) ToolResult.success("Pressed home") else ToolResult.error("Failed to press home")
            "scroll" -> scrollFast(service, getStringAny(json, "direction") ?: "down", getIntAny(json, "durationMs", "duration_ms") ?: 350)
            "wait_text" -> waitElementFast(
                service,
                ActionFastExecutor.waitTargetFrom(json)
                    ?: throw IllegalArgumentException("Missing required parameter: text or resourceId"),
                getIntAny(json, "timeoutMs", "timeout_ms") ?: 3000
            )
            else -> ToolResult.error("Unsupported action_fast action: $action")
        }
    }

    private fun readFastObservation(service: ClawAccessibilityService, metrics: ApiMetrics): JsonObject? {
        val startedAt = System.currentTimeMillis()
        val observed = runCatching {
            service.screenTreeJson?.let { tree -> ScreenObservationBuilder.build(tree, durationMs = 0L) }
        }.getOrNull()
        metrics.addScreenTree(System.currentTimeMillis() - startedAt)
        return observed
    }

    private fun waitForSystemActionTransition(
        service: ClawAccessibilityService,
        beforeObservedAt: Long,
        beforePackage: String?
    ): Boolean {
        val deadline = System.currentTimeMillis() + 900L
        var sawTree = false
        while (System.currentTimeMillis() < deadline) {
            try {
                Thread.sleep(60L)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return false
            }
            val currentPackage = runCatching { service.currentPackageName }.getOrNull()
            val observedAt = service.currentPackageObservedAt
            val treeAvailable = runCatching { service.screenTreeJson != null }.getOrDefault(false)
            sawTree = sawTree || treeAvailable
            if (treeAvailable && (observedAt > beforeObservedAt || (!beforePackage.isNullOrBlank() && currentPackage != beforePackage))) {
                return true
            }
        }
        return sawTree && service.currentPackageObservedAt > beforeObservedAt
    }

    private fun clickTextFast(service: ClawAccessibilityService, text: String): ToolResult {
        return clickTargetFast(service, ActionFastExecutor.ClickTarget("text", text))
    }

    private fun clickTargetFast(service: ClawAccessibilityService, target: ActionFastExecutor.ClickTarget): ToolResult {
        val nodes = when (target.kind) {
            "description" -> service.findNodesByDescription(target.value)
            "resource_id" -> service.findNodesById(target.value)
            else -> service.findNodesByText(target.value)
        }
        if (nodes.isEmpty()) {
            return ToolResult.error("Target not found: ${target.kind}=${target.value}")
        }
        return try {
            val clicked = service.clickNode(nodes.first())
            if (clicked) {
                ToolResult.success("Clicked target: ${target.kind}=${target.value}")
            } else {
                ToolResult.error("Failed to click target: ${target.kind}=${target.value}")
            }
        } finally {
            ClawAccessibilityService.recycleNodes(nodes)
        }
    }

    private fun clickRefFast(service: ClawAccessibilityService, ref: String): ToolResult {
        val tree = service.screenTreeJson ?: return ToolResult.error("Screen tree unavailable")
        val nodes = tree.get("nodes")?.takeIf { it.isJsonArray }?.asJsonArray ?: return ToolResult.error("Screen tree has no nodes")
        val node = nodes.firstOrNull { element ->
            element.isJsonObject && ScreenObservationBuilder.stableRefForNode(element.asJsonObject).equals(ref, ignoreCase = true)
        }?.asJsonObject ?: return ToolResult.error("Ref not found: $ref")
        return clickJsonNodeFast(service, node, "ref: $ref")
    }

    private fun clickNodeFast(service: ClawAccessibilityService, nodeId: String): ToolResult {
        val tree = service.screenTreeJson ?: return ToolResult.error("Screen tree unavailable")
        val nodes = tree.get("nodes")?.takeIf { it.isJsonArray }?.asJsonArray ?: return ToolResult.error("Screen tree has no nodes")
        val node = nodes.firstOrNull { element ->
            element.isJsonObject && element.asJsonObject.get("id")?.asString == nodeId
        }?.asJsonObject ?: return ToolResult.error("Node not found: $nodeId")
        return clickJsonNodeFast(service, node, "node: $nodeId")
    }

    private fun clickJsonNodeFast(service: ClawAccessibilityService, node: JsonObject, targetName: String): ToolResult {
        val bounds = node.get("bounds")?.takeIf { it.isJsonObject }?.asJsonObject
            ?: return ToolResult.error("Node has no bounds: $targetName")
        val x = jsonIntOrNull(bounds, "centerX") ?: return ToolResult.error("Node has no centerX: $targetName")
        val y = jsonIntOrNull(bounds, "centerY") ?: return ToolResult.error("Node has no centerY: $targetName")
        return if (service.performNodeAwareTap(x, y, 100L)) {
            ToolResult.success("Clicked $targetName")
        } else {
            ToolResult.error("Failed to click $targetName")
        }
    }

    private fun scrollFast(service: ClawAccessibilityService, direction: String, durationMs: Int): ToolResult {
        val metrics = service.resources.displayMetrics
        val centerX = metrics.widthPixels / 2
        val centerY = metrics.heightPixels / 2
        val leftX = (metrics.widthPixels * 0.25f).toInt()
        val rightX = (metrics.widthPixels * 0.75f).toInt()
        val upperY = (metrics.heightPixels * 0.30f).toInt()
        val lowerY = (metrics.heightPixels * 0.72f).toInt()
        val normalized = direction.trim().lowercase(Locale.US)
        val success = when (normalized) {
            "up" -> service.performSwipe(centerX, upperY, centerX, lowerY, durationMs.toLong())
            "left" -> service.performSwipe(leftX, centerY, rightX, centerY, durationMs.toLong())
            "right" -> service.performSwipe(rightX, centerY, leftX, centerY, durationMs.toLong())
            else -> service.performSwipe(centerX, lowerY, centerX, upperY, durationMs.toLong())
        }
        return if (success) ToolResult.success("Scrolled $normalized") else ToolResult.error("Failed to scroll $normalized")
    }

    private fun jsonStringOrEmpty(json: JsonObject?, name: String): String {
        val value = json?.get(name) ?: return ""
        if (value.isJsonNull) return ""
        return runCatching { value.asString.orEmpty() }.getOrDefault("")
    }

    private fun jsonIntOrNull(json: JsonObject, name: String): Int? {
        val value = json.get(name) ?: return null
        if (value.isJsonNull) return null
        return runCatching { value.asInt }.getOrNull()
    }

    private fun refSafetyTextFromObservation(ref: String?, observation: JsonObject?): String {
        if (ref.isNullOrBlank() || observation == null) return ""
        for (arrayName in listOf("selectors", "keyNodes", "inputNodes")) {
            val nodes = observation.get(arrayName)?.takeIf { it.isJsonArray }?.asJsonArray ?: continue
            nodes.forEach { element ->
                if (!element.isJsonObject) return@forEach
                val node = element.asJsonObject
                if (!jsonStringOrEmpty(node, "ref").equals(ref, ignoreCase = true)) return@forEach
                return safetyTextFromObservedNode(node)
            }
        }
        return ""
    }

    private fun safetyTextFromObservedNode(node: JsonObject): String {
        val actionBody = node.get("actionBody")?.takeIf { it.isJsonObject }?.asJsonObject
        return listOf(
            jsonStringOrEmpty(node, "label"),
            jsonStringOrEmpty(node, "text"),
            jsonStringOrEmpty(node, "description"),
            jsonStringOrEmpty(node, "resourceId"),
            jsonStringOrEmpty(node, "className"),
            jsonStringOrEmpty(actionBody, "text"),
            jsonStringOrEmpty(actionBody, "contentDescription"),
            jsonStringOrEmpty(actionBody, "resourceId")
        ).filter { it.isNotBlank() }.joinToString(" ")
    }

    private fun waitElementFast(
        service: ClawAccessibilityService,
        target: ActionFastExecutor.WaitTarget,
        timeoutMs: Int
    ): ToolResult {
        val deadline = System.currentTimeMillis() + timeoutMs.coerceIn(100, 15000)
        var attempts = 0
        while (System.currentTimeMillis() <= deadline) {
            attempts += 1
            val nodes = when (target.kind) {
                "description" -> service.findNodesByDescription(target.value)
                "resource_id" -> service.findNodesById(target.value)
                else -> service.findNodesByText(target.value)
            }
            try {
                if (nodes.isNotEmpty()) {
                    return ToolResult.success("Element appeared after $attempts checks: ${target.kind}=${target.value}")
                }
            } finally {
                ClawAccessibilityService.recycleNodes(nodes)
            }
            try {
                Thread.sleep(150)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return ToolResult.error("Interrupted while waiting for element: ${target.kind}=${target.value}")
            }
        }
        return ToolResult.error("Element not found before timeout: ${target.kind}=${target.value}")
    }

    private fun fastActionEvents(
        type: String,
        action: String,
        success: Boolean,
        message: String?
    ): JsonArray {
        return JsonArray().apply {
            add(JsonObject().apply {
                addProperty("type", "action_fast_$type")
                addProperty("round", 0)
                addProperty("time", System.currentTimeMillis())
                addProperty("toolName", action)
                addProperty("success", success)
                if (!message.isNullOrBlank()) addProperty("message", message.take(500))
            })
        }
    }

    private fun firstQueryParam(session: NanoHTTPD.IHTTPSession, vararg names: String): String? {
        return names.firstNotNullOfOrNull { name ->
            session.parameters[name]?.firstOrNull()?.takeIf { it.isNotBlank() }
        }
    }

    private fun queryBoolean(session: NanoHTTPD.IHTTPSession, name: String): Boolean {
        return session.parameters[name]?.firstOrNull()?.let { value ->
            value.equals("true", ignoreCase = true) || value == "1" || value.equals("yes", ignoreCase = true)
        } ?: false
    }

    private fun requiredStringAny(json: JsonObject, vararg names: String): String {
        return getStringAny(json, *names)
            ?: throw IllegalArgumentException("Missing required parameter: ${names.first()}")
    }

    private fun getStringAny(json: JsonObject, vararg names: String): String? {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            runCatching { value.asString.trim() }.getOrNull()?.takeIf { it.isNotBlank() }
        }
    }

    private fun getIntAny(json: JsonObject, vararg names: String): Int? {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            runCatching { value.asInt }.getOrNull()
        }
    }

    private fun getBooleanAny(json: JsonObject, vararg names: String): Boolean? {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            runCatching { value.asBoolean }.getOrNull()
        }
    }

    private fun failureData(
        errorCode: String,
        message: String,
        metrics: ApiMetrics,
        accessibilityState: AccessibilityStateInspector.State? = null
    ): JsonObject {
        return JsonObject().apply {
            addProperty("success", false)
            addProperty("mode", metrics.mode)
            addProperty("currentStep", "failed")
            addProperty("answer", "")
            addProperty("message", message)
            addProperty("error", message)
            addProperty("errorCode", errorCode)
            addProperty("retryable", accessibilityState?.retryable ?: false)
            accessibilityState?.recoveryHint?.takeIf { it.isNotBlank() }?.let {
                addProperty("recoveryHint", it)
                addProperty("fixHint", it)
            }
            addProperty("rounds", metrics.rounds)
            add("metrics", metrics.toJson())
            accessibilityState?.let { addAccessibilityStateProperties(this, it) }
            add("agentReport", PhoneAgentReportBuilder.failure(errorCode, message, "failed"))
        }
    }

    private fun addAccessibilityStateProperties(
        target: JsonObject,
        state: AccessibilityStateInspector.State
    ) {
        target.addProperty("accessibilityRunning", state.boundToProcess)
        target.addProperty("accessibilityMasterEnabled", state.masterEnabled)
        target.addProperty("accessibilityListedInSettings", state.listedInSettings)
        target.addProperty("accessibilityEnabledInSettings", state.enabledInSettings)
        target.addProperty("accessibilityBound", state.boundToProcess)
        target.addProperty("accessibilityStale", state.staleEnabledNotBound)
        target.addProperty("accessibilityHealthy", state.healthy)
        target.addProperty("accessibilityState", state.machineState)
        target.addProperty("accessibilityLegacyState", state.legacyMachineState)
        target.addProperty("accessibilityErrorCode", state.errorCode)
        target.addProperty("accessibilityRetryable", state.retryable)
        if (state.recoveryHint.isNotBlank()) target.addProperty("accessibilityRecoveryHint", state.recoveryHint)
    }

    private fun accessibilityUnavailableMessage(state: AccessibilityStateInspector.State): String {
        return state.recoveryHint.ifBlank { "Accessibility service is not running" }
    }

    private fun findRequestedTemplate(json: JsonObject): com.apk.claw.android.workflow.WorkflowTemplate? {
        val requested = listOf(
            json.get("template_id")?.asString,
            json.get("templateId")?.asString,
            json.get("template_name")?.asString,
            json.get("templateName")?.asString,
            json.get("template")?.asString
        ).firstOrNull { !it.isNullOrBlank() } ?: return null
        WorkflowTemplateManager.getTemplate(requested)?.let { return it }
        return WorkflowTemplateManager.getAllTemplates().firstOrNull { template ->
            template.id.equals(requested, ignoreCase = true) ||
                template.name.equals(requested, ignoreCase = true)
        }
    }

    data class TaskExecuteResult(
        val success: Boolean,
        val answer: String? = null,
        val error: String? = null,
        val rounds: Int = 0,
        val tokens: Int = 0
    )

    /**
     * 从包名获取应用名（常见应用的映射）
     */
    private fun getAppNameFromPackage(packageName: String): String? {
        val appMap = mapOf(
            "com.tencent.mm" to "微信",
            "com.tencent.mobileqq" to "QQ",
            "com.alibaba.android.rimet" to "钉钉",
            "com.ss.android.article.news" to "抖音",
            "com.taobao.taobao" to "淘宝",
            "com.jingdong.app.mall" to "京东",
            "com.sina.weibo" to "微博",
            "com.alibaba.wireless" to "支付宝",
            "com.tencent.qqlive" to "腾讯视频",
            "com.netease.cloudmusic" to "网易云音乐",
            "com.sankuai.meituan" to "美团",
            "com.sankuai.meituan.takeoutnew" to "美团外卖",
            "com.xiaomi.market" to "小米应用商店",
            "com.android.settings" to "设置"
        )
        return appMap[packageName]
            ?: packageName.split(".").lastOrNull()?.replaceFirstChar { char ->
                if (char.isLowerCase()) char.titlecase(Locale.getDefault()) else char.toString()
            }
    }
}
