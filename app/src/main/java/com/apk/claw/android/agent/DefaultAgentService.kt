package com.apk.claw.android.agent

import android.os.Build
import android.graphics.Rect
import android.util.DisplayMetrics
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.R
import com.apk.claw.android.agent.langchain.LangChain4jToolBridge
import com.apk.claw.android.agent.llm.LlmClient
import com.apk.claw.android.agent.llm.LlmClientFactory
import com.apk.claw.android.agent.llm.LlmResponse
import com.apk.claw.android.agent.llm.StreamingListener
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.impl.GetScreenInfoTool
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.server.CrashLogApiController
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.reflect.TypeToken
import dev.langchain4j.data.message.AiMessage
import dev.langchain4j.data.message.ChatMessage
import dev.langchain4j.data.message.SystemMessage
import dev.langchain4j.data.message.ToolExecutionResultMessage
import dev.langchain4j.data.message.UserMessage
import dev.langchain4j.agent.tool.ToolExecutionRequest
import dev.langchain4j.agent.tool.ToolSpecification
import java.io.File
import java.util.LinkedList
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class DefaultAgentService : AgentService {

    companion object {
        private const val TAG = "AgentService"
        private val GSON = Gson()

        /** LLM API 调用失败时的最大重试次数 */
        private const val MAX_API_RETRIES = 3
        /** 死循环检测：滑动窗口大小 */
        private const val LOOP_DETECT_WINDOW = 4

        /** Strict observation mode: tools in this set do not navigate, tap, type, or alter device state. */
        private val READ_ONLY_ALLOWED_TOOLS = setOf(
            "get_screen_info",
            "take_screenshot",
            "find_node_info",
            "get_installed_apps",
            "wait",
            "finish"
        )

        /** Narrow observe-only screen tasks to the current UI tree. */
        private val CURRENT_SCREEN_ONLY_TOOLS = setOf(
            "get_screen_info",
            "finish"
        )

        /** Safe action mode can operate the current UI but cannot touch files, clipboard, schedules, or suggestions. */
        private val SAFE_ACTION_ALLOWED_TOOLS = READ_ONLY_ALLOWED_TOOLS + setOf(
            "open_app",
            "tap",
            "long_press",
            "swipe",
            "drag",
            "scroll_to_find",
            "collect_list_items",
            "input_text",
            "system_key"
        )

        private val TEMPORARY_ALLOW_TEXTS = listOf(
            "本次允许",
            "仅本次允许",
            "仅此次允许",
            "允许一次",
            "允许本次",
            "本次打开",
            "Just once",
            "Only this time"
        )

        private val PERSISTENT_ALLOW_TEXTS = listOf(
            "始终允许",
            "总是允许",
            "一直允许",
            "始终打开",
            "Always allow",
            "Always"
        )

        private val BLOCKED_SAFE_ACTION_TAP_KEYWORDS = listOf(
            "支付",
            "付款",
            "收银台",
            "下单",
            "提交订单",
            "确认订单",
            "购买",
            "立即购买",
            "充值",
            "开通",
            "订阅",
            "转账",
            "提现",
            "银行卡",
            "密码",
            "验证码",
            "登录",
            "微信登录",
            "QQ登录",
            "授权登录",
            "账号绑定",
            "绑定手机",
            "实名认证",
            "用户协议",
            "隐私政策",
            "同意并继续",
            "删除",
            "清除数据",
            "清理缓存",
            "格式化",
            "恢复出厂",
            "卸载",
            "注销账号",
            "退出登录",
            "退出游戏",
            "上报日志",
            "上传日志",
            "payment",
            "pay now",
            "purchase",
            "buy now",
            "checkout",
            "recharge",
            "subscribe",
            "login",
            "sign in",
            "authorize",
            "clear cache",
            "delete",
            "uninstall",
            "factory reset",
            "upload logs",
            "report logs",
            "log out",
            "exit game"
        )

        /** 是否将网络请求/响应原始数据输出到沙盒缓存文件，方便调试 */
        @JvmField
        var FILE_LOGGING_ENABLED = false
        @JvmField
        var FILE_LOGGING_CACHE_DIR: File? = null
    }

    private lateinit var config: AgentConfig
    private lateinit var llmClient: LlmClient
    private lateinit var toolSpecs: List<dev.langchain4j.agent.tool.ToolSpecification>
    private var executor: ExecutorService? = null
    private val running = AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)

    override fun initialize(config: AgentConfig) {
        this.config = config
        this.llmClient = LlmClientFactory.create(config)
        this.toolSpecs = LangChain4jToolBridge.buildToolSpecifications()
        this.executor = Executors.newSingleThreadExecutor()
        XLog.i(TAG, "Agent initialized: provider=${config.provider}, model=${config.modelName}, streaming=${config.streaming}")
    }

    override fun updateConfig(config: AgentConfig) {
        if (running.get()) {
            cancel()
            XLog.w(TAG, "Task was running during config update, cancelled")
        }
        executor?.shutdownNow()
        initialize(config)
        XLog.i(TAG, "Agent config updated, new model: ${config.modelName}")
    }

    override fun executeTask(userPrompt: String, callback: AgentCallback, options: AgentRunOptions) {
        if (running.get()) {
            callback.onError(0, IllegalStateException("Agent is already running a task"), 0)
            return
        }

        running.set(true)
        cancelled.set(false)

        executor?.submit {
            try {
                runAgentLoop(userPrompt, callback, options)
            } catch (t: Throwable) {
                XLog.e(TAG, "Agent execution error", t)
                CrashLogApiController.recordThrowable(ClawApplication.instance, "agent-loop", t)
                callback.onError(0, if (t is Exception) t else RuntimeException(t), 0)
            } finally {
                running.set(false)
            }
        }
    }

    // ==================== 环境预检 ====================

    private fun preCheck(): String? {
        if (ClawAccessibilityService.getInstance() == null) {
            return ClawApplication.instance.getString(R.string.agent_accessibility_not_enabled)
        }
        return null
    }

    // ==================== 设备上下文 ====================

    private fun buildDeviceContext(): String {
        val app = ClawApplication.instance
        val sb = StringBuilder()
        sb.append("\n\n## 设备信息\n")
        sb.append("- 品牌: ").append(Build.BRAND).append("\n")
        sb.append("- 型号: ").append(Build.MODEL).append("\n")
        sb.append("- Android 版本: ").append(Build.VERSION.RELEASE)
            .append(" (API ").append(Build.VERSION.SDK_INT).append(")\n")

        try {
            val wm = app
                .getSystemService(android.content.Context.WINDOW_SERVICE) as WindowManager
            val dm = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(dm)
            sb.append("- 屏幕分辨率: ").append(dm.widthPixels).append("x").append(dm.heightPixels).append("\n")
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to get display metrics", e)
        }

        sb.append("- 已注册工具数: ").append(ToolRegistry.getAllTools().size).append("\n")

        val appName = try {
            val appInfo = app.packageManager.getApplicationInfo(app.packageName, 0)
            app.packageManager.getApplicationLabel(appInfo).toString()
        } catch (_: Exception) { "Agent Phone" }
        sb.append("\n## 本应用信息\n")
        sb.append("- 应用名: ").append(appName).append("\n")
        sb.append("- 包名: ").append(app.packageName).append("\n")
        sb.append("- 当用户提到'自己/本应用/这个应用'时，指的就是上述应用\n")

        return sb.toString()
    }

    private fun allowedToolsFor(options: AgentRunOptions, userPrompt: String): Set<String>? {
        return when (options.toolPolicy) {
            AgentToolPolicy.OBSERVE_ONLY -> {
                if (isCurrentScreenOnlyObservation(userPrompt)) {
                    CURRENT_SCREEN_ONLY_TOOLS
                } else {
                    READ_ONLY_ALLOWED_TOOLS
                }
            }
            AgentToolPolicy.SAFE_ACTION -> SAFE_ACTION_ALLOWED_TOOLS
            AgentToolPolicy.FULL_ACCESS -> null
        }
    }

    private fun isCurrentScreenOnlyObservation(userPrompt: String): Boolean {
        val prompt = userPrompt.lowercase(Locale.US)
        val explicitlyAppInventory = listOf(
            "installed app",
            "app list",
            "launcher apps",
            "安装应用",
            "应用列表",
            "已安装",
            "所有应用",
            "全部应用",
            "可启动应用"
        ).any { prompt.contains(it.lowercase(Locale.US)) }
        if (explicitlyAppInventory) return false

        val explicitlyOnlyScreenInfo = listOf(
            "only use get_screen_info",
            "只允许你使用 get_screen_info",
            "只允许 get_screen_info",
            "不要使用 get_installed_apps",
            "不要查询安装应用"
        ).any { prompt.contains(it.lowercase(Locale.US)) }
        if (explicitlyOnlyScreenInfo) return true

        return listOf(
            "current screen",
            "current page",
            "visible",
            "foreground",
            "当前屏幕",
            "当前页面",
            "当前手机屏幕",
            "当前应用",
            "可见",
            "前台",
            "页面结构",
            "屏幕节点"
        ).any { prompt.contains(it.lowercase(Locale.US)) }
    }

    private fun buildToolPolicyContext(options: AgentRunOptions, allowedTools: Set<String>?): String {
        if (allowedTools == null) {
            return """

## 工具策略
- 当前任务启用了 full_access 工具策略。
- 只有在用户明确要求时才操作手机；观察类任务应直接观察并总结。
""".trimIndent()
        }
        val policyName = options.toolPolicy.wireName
        val boundary = if (options.toolPolicy == AgentToolPolicy.OBSERVE_ONLY) {
            "你只能观察和总结，不能改变手机状态。"
        } else {
            "你可以执行必要的界面操作，但不能访问剪贴板、发送文件、修改定时任务或处理主动建议。遇到“本次允许/始终允许”这类系统弹窗时，优先选择“本次允许”，不要选择会长期保存状态的选项。"
        }
        return """

## 工具策略
- 当前任务启用了 tool_policy=$policyName。
- $boundary
- 允许工具：${allowedTools.joinToString(", ")}。
- 禁止调用允许列表之外的任何工具；如果用户请求越界操作，请用 finish 说明工具策略已阻止操作。
""".trimIndent()
    }

    private data class ToolGuardResult(val params: Map<String, Any>, val blockedReason: String? = null)

    private fun guardSafeActionToolCall(toolName: String, params: Map<String, Any>, options: AgentRunOptions): ToolGuardResult {
        if (options.toolPolicy != AgentToolPolicy.SAFE_ACTION || toolName != "tap") return ToolGuardResult(params)
        val x = numberParam(params, "x") ?: return ToolGuardResult(params)
        val y = numberParam(params, "y") ?: return ToolGuardResult(params)
        val service = ClawAccessibilityService.getInstance() ?: return ToolGuardResult(params)

        val persistentAllow = findVisibleNodesByExactText(service, PERSISTENT_ALLOW_TEXTS)
        try {
            val target = persistentAllow.firstOrNull { nodeContainsPoint(it, x, y) }
            if (target == null) {
                blockedSafeActionTargetAt(service, x, y)?.let { label ->
                    return ToolGuardResult(
                        params,
                        "Safe-action guard blocked tap on sensitive target: $label"
                    )
                }
                return ToolGuardResult(params)
            }
            val temporary = findVisibleNodesByExactText(service, TEMPORARY_ALLOW_TEXTS)
            try {
                val oneTime = temporary.firstOrNull() ?: return ToolGuardResult(params)
                val bounds = Rect()
                oneTime.getBoundsInScreen(bounds)
                if (bounds.isEmpty) return ToolGuardResult(params)
                XLog.i(TAG, "safe_action tap guard rewrote persistent allow tap (${nodeText(target)}) to temporary allow (${nodeText(oneTime)}) at ${bounds.centerX()},${bounds.centerY()}")
                return ToolGuardResult(params.toMutableMap().apply {
                    put("x", bounds.centerX())
                    put("y", bounds.centerY())
                })
            } finally {
                ClawAccessibilityService.recycleNodes(temporary)
            }
        } finally {
            ClawAccessibilityService.recycleNodes(persistentAllow)
        }
    }

    private fun numberParam(params: Map<String, Any>, key: String): Int? {
        val value = params[key] ?: return null
        return when (value) {
            is Number -> value.toInt()
            else -> value.toString().toDoubleOrNull()?.toInt()
        }
    }

    private fun findVisibleNodesByExactText(
        service: ClawAccessibilityService,
        texts: List<String>
    ): MutableList<AccessibilityNodeInfo> {
        val result = mutableListOf<AccessibilityNodeInfo>()
        for (text in texts) {
            val nodes = service.findNodesByText(text)
            for (node in nodes) {
                val nodeText = nodeText(node)
                if (node.isVisibleToUser && texts.any { it == nodeText }) {
                    result.add(node)
                } else {
                    node.recycle()
                }
            }
        }
        return result
    }

    private fun nodeContainsPoint(node: AccessibilityNodeInfo, x: Int, y: Int): Boolean {
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        return bounds.contains(x, y)
    }

    private fun nodeText(node: AccessibilityNodeInfo): String {
        return node.text?.toString()?.trim().orEmpty()
    }

    private fun blockedSafeActionTargetAt(service: ClawAccessibilityService, x: Int, y: Int): String? {
        val tree: JsonObject = service.screenTreeJson ?: return null
        val nodes = tree.getAsJsonArray("nodes") ?: return null
        var matchedLabel: String? = null
        var matchedArea = Int.MAX_VALUE
        for (element in nodes) {
            if (!element.isJsonObject) continue
            val node = element.asJsonObject
            val bounds = node.getAsJsonObject("bounds") ?: continue
            val left = jsonInt(bounds, "left") ?: continue
            val top = jsonInt(bounds, "top") ?: continue
            val right = jsonInt(bounds, "right") ?: continue
            val bottom = jsonInt(bounds, "bottom") ?: continue
            if (x !in left..right || y !in top..bottom) continue
            val label = listOf(
                jsonString(node, "text"),
                jsonString(node, "description"),
                jsonString(node, "resourceId"),
                jsonString(node, "className")
            ).filter { it.isNotBlank() }.joinToString(" ")
            if (label.isBlank()) continue
            val normalized = label.lowercase(Locale.ROOT)
            if (BLOCKED_SAFE_ACTION_TAP_KEYWORDS.none { normalized.contains(it.lowercase(Locale.ROOT)) }) continue
            val area = maxOf(1, (right - left) * (bottom - top))
            if (area < matchedArea) {
                matchedArea = area
                matchedLabel = label
            }
        }
        return matchedLabel
    }

    private fun jsonString(json: JsonObject, key: String): String {
        return try {
            json.get(key)?.takeIf { it.isJsonPrimitive }?.asString?.trim().orEmpty()
        } catch (_: Exception) {
            ""
        }
    }

    private fun jsonInt(json: JsonObject, key: String): Int? {
        return try {
            json.get(key)?.takeIf { it.isJsonPrimitive }?.asInt
        } catch (_: Exception) {
            null
        }
    }

    // ==================== LLM 调用（带重试） ====================

    private fun chatWithRetry(
        messages: List<ChatMessage>,
        callback: AgentCallback,
        iteration: Int,
        activeToolSpecs: List<ToolSpecification>
    ): LlmResponse {
        var lastException: Exception? = null
        for (attempt in 0 until MAX_API_RETRIES) {
            if (cancelled.get()) throw RuntimeException(ClawApplication.instance.getString(R.string.agent_task_cancelled))
            try {
                return if (config.streaming) {
                    val textBuilder = StringBuilder()
                    llmClient.chatStreaming(messages, activeToolSpecs, object : StreamingListener {
                        override fun onPartialText(token: String) {
                            textBuilder.append(token)
                            callback.onContent(iteration, token)
                        }
                        override fun onComplete(response: LlmResponse) {}
                        override fun onError(error: Throwable) {}
                    })
                } else {
                    llmClient.chat(messages, activeToolSpecs)
                }
            } catch (e: Exception) {
                lastException = e
                val msg = e.message ?: ""
                // Token 耗尽或认证失败不重试
                if (msg.contains("401") || msg.contains("403") || msg.contains("insufficient")) {
                    throw e
                }
                val delay = (Math.pow(2.0, attempt.toDouble()) * 1000).toLong()
                XLog.w(TAG, "LLM API call failed (attempt ${attempt + 1}/$MAX_API_RETRIES), retrying in ${delay}ms: $msg")
                try {
                    Thread.sleep(delay)
                } catch (ie: InterruptedException) {
                    Thread.currentThread().interrupt()
                    throw e
                }
            }
        }
        throw lastException!!
    }

    // ==================== 死循环检测 ====================

    private data class RoundFingerprint(val screenHash: Int, val toolCall: String)

    private fun isStuckInLoop(history: LinkedList<RoundFingerprint>): Boolean {
        if (history.size < LOOP_DETECT_WINDOW) return false
        val first = history.first()
        return history.all { it == first }
    }

    // ==================== 上下文压缩 ====================

    /** 保护区：最近 N 轮完整保留 */
    private val KEEP_RECENT_ROUNDS = 3

    /** 大输出观察类工具 → 压缩后占位符 */
    private val OBSERVATION_PLACEHOLDERS = mapOf(
        "get_screen_info" to "[屏幕信息已省略]",
        "take_screenshot" to "[截图结果已省略]",
        "find_node_info" to "[节点查找结果已省略]",
        "get_installed_apps" to "[应用列表已省略]",
        "scroll_to_find" to "[滚动查找结果已省略]",
        "collect_list_items" to "[列表采集结果已省略]"
    )

    /**
     * 发送前压缩历史消息，节省 input token：
     * - get_screen_info：全局只保留最新一条完整结果
     * - 保护区（最近 KEEP_RECENT_ROUNDS 轮）：完整保留
     * - 保护区外：AI thinking 不动，tool result 压缩为一行摘要
     */
    private fun compressHistoryForSend(messages: MutableList<ChatMessage>) {
        // 压缩前统计总字符数
        val charsBefore = messages.sumOf { msg ->
            when (msg) {
                is AiMessage -> (msg.text()?.length ?: 0) + (msg.toolExecutionRequests()?.sumOf { it.arguments()?.length ?: 0 } ?: 0)
                is ToolExecutionResultMessage -> msg.text().length
                is UserMessage -> msg.singleText().length
                is SystemMessage -> msg.text().length
                else -> 0
            }
        }
        val msgCountBefore = messages.size

        // 0. get_screen_info 特殊处理：无视分级，全局只保留最新一条完整结果
        val screenPlaceholder = OBSERVATION_PLACEHOLDERS["get_screen_info"]!!
        val lastScreenIdx = messages.indexOfLast {
            it is ToolExecutionResultMessage && it.toolName() == "get_screen_info"
        }
        for (i in messages.indices) {
            val msg = messages[i]
            if (msg is ToolExecutionResultMessage
                && msg.toolName() == "get_screen_info"
                && i != lastScreenIdx
                && msg.text() != screenPlaceholder
            ) {
                messages[i] = ToolExecutionResultMessage.from(msg.id(), msg.toolName(), screenPlaceholder)
            }
        }

        // 1. 找出所有 AiMessage 的索引，每个代表一轮
        val aiIndices = messages.indices.filter { messages[it] is AiMessage }
        if (aiIndices.size <= KEEP_RECENT_ROUNDS) return

        val totalRounds = aiIndices.size

        for (roundIdx in aiIndices.indices) {
            val roundFromEnd = totalRounds - roundIdx
            if (roundFromEnd <= KEEP_RECENT_ROUNDS) break // 保护区

            val aiIndex = aiIndices[roundIdx]

            // 收集本轮的 ToolExecutionResultMessage 索引
            var j = aiIndex + 1
            while (j < messages.size && messages[j] is ToolExecutionResultMessage) {
                compressToolResultMessage(messages, j)
                j++
            }
        }

        // 压缩后统计
        val charsAfter = messages.sumOf { msg ->
            when (msg) {
                is AiMessage -> (msg.text()?.length ?: 0) + (msg.toolExecutionRequests()?.sumOf { it.arguments()?.length ?: 0 } ?: 0)
                is ToolExecutionResultMessage -> msg.text().length
                is UserMessage -> msg.singleText().length
                is SystemMessage -> msg.text().length
                else -> 0
            }
        }
        val saved = charsBefore - charsAfter
        if (saved > 0) {
            XLog.i(TAG, "上下文压缩: ${charsBefore}→${charsAfter}字符, 节省${saved}字符(${saved * 100 / charsBefore}%), 轮数=${aiIndices.size}")
        }
    }

    /** 压缩 Tool Result：观察类工具用占位符，其他工具截取摘要 */
    private fun compressToolResultMessage(messages: MutableList<ChatMessage>, index: Int) {
        val msg = messages[index] as ToolExecutionResultMessage
        val text = msg.text()
        if (text.length <= 100) return // 已足够简短，无需压缩

        val placeholder = OBSERVATION_PLACEHOLDERS[msg.toolName()]
        if (placeholder != null) {
            messages[index] = ToolExecutionResultMessage.from(msg.id(), msg.toolName(), placeholder)
            return
        }

        // 其他工具：解析 JSON 提取摘要
        val compressed = summarizeToolResult(text)
        messages[index] = ToolExecutionResultMessage.from(msg.id(), msg.toolName(), compressed)
    }

    /** 将 ToolResult JSON 压缩为一行摘要 */
    private fun summarizeToolResult(resultJson: String): String {
        return try {
            val mapType = object : TypeToken<Map<String, Any?>>() {}.type
            val map: Map<String, Any?> = GSON.fromJson(resultJson, mapType)
            val isSuccess = map["isSuccess"] as? Boolean ?: false
            if (isSuccess) {
                val data = map["data"]?.toString() ?: "ok"
                "✓ " + if (data.length > 80) data.take(80) + "..." else data
            } else {
                val error = map["error"]?.toString() ?: "failed"
                "✗ " + if (error.length > 80) error.take(80) + "..." else error
            }
        } catch (_: Exception) {
            if (resultJson.length > 80) resultJson.take(80) + "..." else resultJson
        }
    }

    // ==================== 主执行循环 ====================

    private fun runAgentLoop(userPrompt: String, callback: AgentCallback, options: AgentRunOptions) {
        // 环境预检
        preCheck()?.let {
            val error = RuntimeException(it)
            CrashLogApiController.recordThrowable(ClawApplication.instance, "precheck", error)
            callback.onError(0, error, 0)
            return
        }

        // 构建 System Prompt（原始 + 设备上下文 + 记忆上下文）
        val allowedTools = allowedToolsFor(options, userPrompt)
        val fullSystemPrompt = config.systemPrompt +
            buildDeviceContext() +
            buildToolPolicyContext(options, allowedTools)
        val activeToolSpecs = if (allowedTools != null) {
            toolSpecs.filter { allowedTools.contains(it.name()) }
        } else {
            toolSpecs
        }

        val messages = mutableListOf<ChatMessage>()
        messages.add(SystemMessage.from(fullSystemPrompt))
        messages.add(UserMessage.from(userPrompt))

        var iterations = 0
        var totalTokens = 0
        val maxIterations = options.maxRounds?.coerceIn(1, config.maxIterations) ?: config.maxIterations
        val loopHistory = LinkedList<RoundFingerprint>()
        var lastScreenHash = 0
        var lastPartialSummary = ""
        var stuckSignalCount = 0

        while (iterations < maxIterations && !cancelled.get()) {
            iterations++
            callback.onLoopStart(iterations)

            // 发送前分级压缩历史消息，节省 token
            compressHistoryForSend(messages)

            // LLM 调用（带重试）
            val llmResponse: LlmResponse
            try {
                val llmStartedAt = System.currentTimeMillis()
                llmResponse = chatWithRetry(messages, callback, iterations, activeToolSpecs)
                callback.onMetrics(iterations, llmRoundMs = System.currentTimeMillis() - llmStartedAt)
            } catch (t: Throwable) {
                XLog.e(TAG, "LLM API call failed after retries", t)
                val error = RuntimeException(
                    ClawApplication.instance.getString(R.string.agent_api_call_failed, t.message)
                )
                CrashLogApiController.recordThrowable(ClawApplication.instance, "llm-call", error)
                callback.onError(iterations, error, totalTokens)
                return
            }

            // 累加 token 用量
            llmResponse.tokenUsage?.totalTokenCount()?.let { totalTokens += it }

            // 将 AI 消息添加到历史（需要构造 AiMessage）
            val aiMessage = if (llmResponse.hasToolExecutionRequests()) {
                if (llmResponse.text.isNullOrEmpty()) {
                    AiMessage.from(llmResponse.toolExecutionRequests)
                } else {
                    AiMessage.from(llmResponse.text, llmResponse.toolExecutionRequests)
                }
            } else {
                AiMessage.from(llmResponse.text ?: "")
            }
            messages.add(aiMessage)

            // 非流式模式下推送思考内容
            if (!config.streaming && !llmResponse.text.isNullOrEmpty()) {
                callback.onContent(iterations, llmResponse.text)
            }

            // 如果没有工具调用，Agent 认为完成了
            if (!llmResponse.hasToolExecutionRequests()) {
                val finalAnswer = llmResponse.text ?: ClawApplication.instance.getString(R.string.agent_task_completed)
                callback.onComplete(iterations, finalAnswer, totalTokens)
                return
            }

            // 执行工具调用
            for (toolRequest in llmResponse.toolExecutionRequests) {
                if (cancelled.get()) {
                    callback.onComplete(iterations, ClawApplication.instance.getString(R.string.agent_task_cancel), totalTokens)
                    return
                }

                val toolName = toolRequest.name() ?: ""
                val displayName = ToolRegistry.getInstance().getDisplayName(toolName)
                val toolArgs = toolRequest.arguments() ?: "{}"
                callback.onToolCall(iterations, toolName, displayName, toolArgs)

                // 解析参数
                val mapType = object : TypeToken<Map<String, Any>>() {}.type
                var params: Map<String, Any>? = try {
                    GSON.fromJson(toolArgs, mapType)
                } catch (e: Exception) {
                    HashMap()
                }
                if (params == null) params = HashMap()
                val guard = guardSafeActionToolCall(toolName, params, options)
                params = guard.params

                val toolStartedAt = System.currentTimeMillis()
                val result = if (!guard.blockedReason.isNullOrBlank()) {
                    ToolResult.error(
                        "${guard.blockedReason}. Ask OpenClaw/user for explicit confirmation or call finish with a blocked safety summary."
                    )
                } else if (allowedTools != null && !allowedTools.contains(toolName)) {
                    ToolResult.error(
                        "Tool policy '${options.toolPolicy.wireName}' blocked tool '$toolName'. Allowed tools: " +
                            allowedTools.joinToString(", ") +
                            ". Call finish with a summary instead."
                    )
                } else {
                    ToolRegistry.getInstance().executeTool(toolName, params)
                }
                callback.onMetrics(iterations, toolCallMs = System.currentTimeMillis() - toolStartedAt)
                val paramsString = if (params.isEmpty()) "" else params.toString()
                callback.onToolResult(iterations, toolName, displayName, paramsString, result)

                // 检测到系统弹窗阻塞 → 截图通知用户并结束任务
                if (!result.isSuccess && result.error == GetScreenInfoTool.SYSTEM_DIALOG_BLOCKED) {
                    XLog.w(TAG, "System dialog blocked, notifying user and stopping task")
                    callback.onSystemDialogBlocked(iterations, totalTokens)
                    return
                }

                // finish 工具 → 任务完成
                if (toolName == "finish" && result.isSuccess) {
                    val finishData = result.data
                    callback.onComplete(iterations, finishData ?: ClawApplication.instance.getString(R.string.agent_task_completed), totalTokens)
                    return
                }

                // 记录指纹用于死循环检测
                if (toolName == "get_screen_info" && result.isSuccess && result.data != null) {
                    lastScreenHash = result.data.hashCode()
                }
                if (toolName.isNotEmpty()) {
                    val fingerprintHash = if (result.isSuccess && result.data != null) {
                        result.data.hashCode()
                    } else {
                        lastScreenHash
                    }
                    if (result.isSuccess && !result.data.isNullOrBlank()) {
                        lastPartialSummary = result.data.take(400)
                    }
                    loopHistory.addLast(RoundFingerprint(fingerprintHash, "$toolName:$toolArgs"))
                    if (loopHistory.size > LOOP_DETECT_WINDOW) {
                        loopHistory.removeFirst()
                    }
                }

                // 添加工具结果到消息
                val resultJson = GSON.toJson(result)
                messages.add(ToolExecutionResultMessage.from(toolRequest, resultJson))
                XLog.d(TAG, "displayName:$displayName toolName:$toolName")
            }

            // 死循环检测
            if (isStuckInLoop(loopHistory)) {
                stuckSignalCount += 1
                XLog.w(TAG, "Dead loop detected at iteration $iterations")
                if (AgentLoopEarlyStopPolicy.shouldStop(stuckSignalCount, options.toolPolicy)) {
                    callback.onComplete(
                        iterations,
                        AgentLoopEarlyStopPolicy.completionMessage(lastPartialSummary),
                        totalTokens
                    )
                    return
                }
                messages.add(
                    UserMessage.from(
                        "[System notice] The last few tool calls repeated without useful screen progress. " +
                            "Use a different strategy, or call finish if the current tool result already answers the task. " +
                            "For simple observation tasks, summarize the latest screen information and finish now."
                    )
                )
                loopHistory.clear()
            } else {
                stuckSignalCount = 0
            }
            XLog.d(TAG, "轮数:$iterations all=$totalTokens 本轮=${llmResponse.tokenUsage?.totalTokenCount()}")
        }

        if (cancelled.get()) {
            callback.onComplete(iterations, ClawApplication.instance.getString(R.string.agent_task_cancel), totalTokens)
        } else {
            val partial = if (lastPartialSummary.isNotBlank()) {
                "\n\nPartial result:\n$lastPartialSummary"
            } else {
                ""
            }
            callback.onComplete(
                iterations,
                "Reached round budget of $maxIterations. Return a bounded follow-up task if more work is needed.$partial",
                totalTokens
            )
        }
    }

    override fun cancel() {
        cancelled.set(true)
    }

    override fun shutdown() {
        cancel()
        executor?.shutdownNow()
    }

    override fun isRunning(): Boolean = running.get()
}
