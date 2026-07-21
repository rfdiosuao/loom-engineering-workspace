package com.apk.claw.android.server

import android.content.Context
import com.apk.claw.android.BuildConfig
import com.apk.claw.android.channel.ChannelManager
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.utils.KVUtils
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.apk.claw.android.utils.XLog
import fi.iki.elonen.NanoHTTPD

/**
 * 局域网 HTTP 配置服务器
 * 提供 H5 页面用于在电脑浏览器上配置钉钉/飞书 key
 */
class ConfigServer(
    private val context: Context,
    port: Int = PORT
) : NanoHTTPD(port) {

    companion object {
        private const val TAG = "ConfigServer"
        const val PORT = 9527
        private const val MIME_HTML = "text/html"
        private const val MIME_JSON = "application/json"
    }

    private val gson = Gson()

    override fun serve(session: IHTTPSession): Response {
        // CORS 预检请求
        if (session.method == Method.OPTIONS) {
            return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_PLAINTEXT, ""))
        }

        val uri = session.uri
        val method = session.method

        return try {
            when {
                (uri == "/" || uri == "/index.html") && method == Method.GET -> serveHtml()
                uri == "/api/channels" && method == Method.GET -> handleGetChannels()
                uri == "/api/channels" && method == Method.POST -> handlePostChannels(session)
                uri == "/api/llm" && method == Method.GET -> handleGetLlm()
                uri == "/api/llm" && method == Method.POST -> handlePostLlm(session)
                // ==================== Lumi Secure Channel (Token + HMAC required) ====================
                uri == "/api/lumi/security/pair" && method == Method.POST -> LumiSecurityController.handlePair(session)
                uri == "/api/lumi/security/status" && method == Method.GET -> LumiSecurityController.handleStatus(session)
                uri == "/api/lumi/events" && method == Method.GET -> handleLumiGet(session) {
                    PhoneEventStreamController.handleEvents(it)
                }
                uri == "/api/lumi/device/profile" && method == Method.GET -> handleLumiGet(session) {
                    DeviceProfileApiController.handleGetProfile(it)
                }
                uri == "/api/lumi/agent/execute_task" && method == Method.POST -> handleLumiJson(session) {
                    AgentApiController.handleExecuteTask(it)
                }
                uri == "/api/lumi/agent/observe_fast" && method == Method.GET -> handleLumiGet(session) {
                    AgentApiController.handleObserveFast(it)
                }
                uri == "/api/lumi/agent/action_fast" && method == Method.POST -> handleLumiJson(session) {
                    AgentApiController.handleActionFast(it)
                }
                uri == "/api/lumi/rpa/run" && method == Method.POST -> handleLumiJson(session) {
                    RpaApiController.handleRun(it, requireToken = false)
                }
                uri == "/api/lumi/rpa/validate" && method == Method.POST -> handleLumiJson(session) {
                    RpaApiController.handleValidate(it, requireToken = false)
                }
                uri == "/api/lumi/rpa/capabilities" && method == Method.GET -> handleLumiGet(session) {
                    RpaApiController.handleCapabilities(it, requireToken = false)
                }
                uri == "/api/lumi/rpa/runs" && method == Method.GET -> handleLumiGet(session) {
                    RpaApiController.handleListRuns(it, requireToken = false)
                }
                uri.startsWith("/api/lumi/rpa/runs/") && uri.endsWith("/cancel") && method == Method.POST -> handleLumiJson(session) {
                    val runId = uri.removePrefix("/api/lumi/rpa/runs/").removeSuffix("/cancel").trimEnd('/')
                    RpaApiController.handleCancel(it, runId, requireToken = false)
                }
                uri.startsWith("/api/lumi/rpa/runs/") && method == Method.GET -> handleLumiGet(session) {
                    val runId = uri.removePrefix("/api/lumi/rpa/runs/").trimEnd('/')
                    RpaApiController.handleGetRun(it, runId, requireToken = false)
                }
                uri == "/api/lumi/metrics" && method == Method.GET -> handleLumiGet(session) {
                    AgentApiController.handleGetMetrics(it)
                }
                uri == "/api/lumi/agent/metrics" && method == Method.GET -> handleLumiGet(session) {
                    AgentApiController.handleGetMetrics(it)
                }
                uri == "/api/lumi/agent/tasks" && method == Method.POST -> handleLumiJson(session) {
                    AgentApiController.handleCreateAsyncTask(it)
                }
                uri.startsWith("/api/lumi/agent/tasks/") && method == Method.GET -> handleLumiGet(session) {
                    val taskId = uri.removePrefix("/api/lumi/agent/tasks/").removeSuffix("/events")
                    if (uri.endsWith("/events")) {
                        AgentApiController.handleGetAsyncTaskEvents(it, taskId)
                    } else {
                        AgentApiController.handleGetAsyncTask(it, taskId)
                    }
                }
                uri.startsWith("/api/lumi/agent/tasks/") && uri.endsWith("/cancel") && method == Method.POST -> handleLumiJson(session) {
                    val taskId = uri.removePrefix("/api/lumi/agent/tasks/").removeSuffix("/cancel").trimEnd('/')
                    AgentApiController.handleCancelAsyncTask(it, taskId)
                }
                uri == "/api/lumi/agent/cancel_task" && method == Method.POST -> handleLumiJson(session) {
                    AgentApiController.handleCancelTask(it)
                }
                uri == "/api/lumi/collect/list" && method == Method.POST -> handleLumiJson(session) {
                    CollectApiController.handleCollectList(it)
                }
                uri == "/api/lumi/wechat/auto_reply" && method == Method.POST -> handleLumiJson(session) {
                    WeChatAutoReplyApiController.handleAutoReply(it)
                }
                uri == "/api/lumi/vision/status" && method == Method.GET -> handleLumiGet(session) {
                    VisionApiController.handleStatus(it)
                }
                uri == "/api/lumi/vision/frame" && method == Method.GET -> handleLumiGet(session) {
                    VisionApiController.handleFrame(it)
                }
                uri == "/api/lumi/vision/action" && method == Method.POST -> handleLumiJson(session) {
                    VisionApiController.handleAction(it)
                }
                uri == "/api/lumi/debug/crashes/latest" && method == Method.GET -> handleLumiGet(session) {
                    CrashLogApiController.handleLatest(context, it)
                }
                uri == "/api/lumi/debug/crashes/export" && method == Method.POST -> handleLumiJson(session) {
                    CrashLogApiController.handleExport(context, it)
                }
                uri == "/api/lumi/media/import_image" && method == Method.POST -> handleLumiJson(session) {
                    MediaApiController.handleImportImageJson(context, it)
                }
                uri == "/api/lumi/media/import_video" && method == Method.POST -> handleLumiJson(session) {
                    MediaApiController.handleImportVideoJson(context, it)
                }
                uri == "/api/lumi/media/record/start" && method == Method.POST -> handleLumiJson(session) {
                    MediaApiController.handleStartScreenRecord(context, it)
                }
                uri == "/api/lumi/media/record/stop" && method == Method.POST -> handleLumiJson(session) {
                    MediaApiController.handleStopScreenRecord(context, it)
                }
                uri == "/api/lumi/media/record/status" && method == Method.GET -> handleLumiGet(session) {
                    MediaApiController.handleScreenRecordStatus(context, it)
                }
                uri == "/api/lumi/media/videos" && method == Method.GET -> handleLumiGet(session) {
                    MediaApiController.handleListVideos(context, it)
                }
                uri == "/api/lumi/media/video" && method == Method.GET -> handleLumiGet(session) {
                    MediaApiController.handleDownloadVideo(context, it)
                }
                uri == "/api/lumi/publish/execute" && method == Method.POST -> handleLumiJson(session) {
                    PublishApiController.handleExecutePacket(it)
                }
                uri == "/api/lumi/publish/packet" && method == Method.POST -> handleLumiJson(session) {
                    PublishApiController.handleExecutePacket(it)
                }
                // 电脑端把 LLM 模型配置同步到手机（地址/密钥/模型名）。
                uri == "/api/lumi/config/llm/import" && method == Method.POST -> handleLumiJson(session) {
                    handleImportLlmConfig(it)
                }
                uri == "/api/lumi/config/llm/export" && method == Method.GET -> handleLumiGet(session) {
                    handleExportLlmConfig()
                }
                // ==================== Tool API (Token required) ====================
                uri == "/api/tool/list" && method == Method.GET -> ToolApiController.handleToolList(session)
                uri == "/api/tool/tap" && method == Method.POST -> ToolApiController.handleTap(session)
                uri == "/api/tool/swipe" && method == Method.POST -> ToolApiController.handleSwipe(session)
                uri == "/api/tool/drag" && method == Method.POST -> ToolApiController.handleDrag(session)
                uri == "/api/tool/long_press" && method == Method.POST -> ToolApiController.handleLongPress(session)
                uri == "/api/tool/screenshot" && method == Method.GET -> ToolApiController.handleScreenshot(session)
                uri == "/api/tool/get_screen_info" && method == Method.GET -> ToolApiController.handleGetScreenInfo(session)
                uri == "/api/tool/observe_fast" && method == Method.GET -> AgentApiController.handleObserveFast(session)
                uri == "/api/tool/action_fast" && method == Method.POST -> AgentApiController.handleActionFast(session)
                uri == "/api/tool/screen_tree" && method == Method.GET -> ToolApiController.handleScreenTree(session)
                uri == "/api/tool/ui-tree" && method == Method.GET -> ToolApiController.handleScreenTree(session)
                uri == "/api/tool/find_node_info" && method == Method.POST -> ToolApiController.handleFindNodeInfo(session)
                uri == "/api/tool/open_app" && method == Method.POST -> ToolApiController.handleOpenApp(session)
                uri == "/api/tool/input_text" && method == Method.POST -> ToolApiController.handleInputText(session)
                uri == "/api/tool/system_key" && method == Method.POST -> ToolApiController.handleSystemKey(session)
                uri == "/api/tool/get_installed_apps" && method == Method.GET -> ToolApiController.handleGetInstalledApps(session)
                uri == "/api/tool/wait" && method == Method.POST -> ToolApiController.handleWait(session)
                uri == "/api/tool/scroll_to_find" && method == Method.POST -> ToolApiController.handleScrollToFind(session)
                uri == "/api/tool/wechat_auto_reply" && method == Method.POST -> WeChatAutoReplyApiController.handleAutoReply(session)
                // ==================== Collector API (Token required) ====================
                uri == "/api/collect/list" && method == Method.POST -> LumiSecurityController.launcherOnlyResponse()
                uri.startsWith("/api/vision/") -> LumiSecurityController.launcherOnlyResponse()
                // ==================== Overlay API (Token required) ====================
                uri == "/api/overlay/cursor" && method == Method.POST -> OverlayApiController.handleCursor(session)
                uri == "/api/overlay/cursor/preview" && method == Method.POST -> OverlayApiController.handleCursorPreview(session)
                // ==================== Media API (Token required) ====================
                uri == "/api/media/import_image" && method == Method.POST -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/import_video" && method == Method.POST -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/record/start" && method == Method.POST -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/record/stop" && method == Method.POST -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/record/status" && method == Method.GET -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/videos" && method == Method.GET -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/media/video" && method == Method.GET -> LumiSecurityController.launcherOnlyResponse()
                // ==================== Agent API (Token required) ====================
                uri == "/api/device/status" && method == Method.GET -> AgentApiController.handleGetStatus(session)
                uri == "/api/metrics" && method == Method.GET -> AgentApiController.handleGetMetrics(session)
                uri == "/api/device/wake" && method == Method.POST -> AgentApiController.handleWakeDevice(session)
                uri == "/api/device/profile" && method == Method.GET -> LumiSecurityController.launcherOnlyResponse()
                uri == "/api/agent/status" && method == Method.GET -> AgentApiController.handleGetStatus(session)
                uri == "/api/agent/execute_task" && method == Method.POST -> AgentApiController.handleExecuteTask(session)
                uri == "/api/agent/cancel_task" && method == Method.POST -> AgentApiController.handleCancelTask(session)
                // ==================== RPA API (Token required) ====================
                uri == "/api/rpa/run" && method == Method.POST -> RpaApiController.handleRun(session)
                uri == "/api/rpa/validate" && method == Method.POST -> RpaApiController.handleValidate(session)
                uri == "/api/rpa/capabilities" && method == Method.GET -> RpaApiController.handleCapabilities(session)
                uri == "/api/rpa/runs" && method == Method.GET -> RpaApiController.handleListRuns(session)
                uri.startsWith("/api/rpa/runs/") && uri.endsWith("/cancel") && method == Method.POST -> {
                    val runId = uri.removePrefix("/api/rpa/runs/").removeSuffix("/cancel").trimEnd('/')
                    RpaApiController.handleCancel(session, runId)
                }
                uri.startsWith("/api/rpa/runs/") && method == Method.GET -> {
                    val runId = uri.removePrefix("/api/rpa/runs/").trimEnd('/')
                    RpaApiController.handleGetRun(session, runId)
                }
                // ==================== Workflow Template API (Token required) ====================
                uri == "/api/workflow/templates" && method == Method.GET -> WorkflowApiController.handleGetTemplates(session)
                uri == "/api/workflow/template" && method == Method.GET -> WorkflowApiController.handleGetTemplate(session)
                uri == "/api/workflow/execute" && method == Method.POST -> WorkflowApiController.handleExecuteTemplate(session)
                uri == "/api/workflow/create" && method == Method.POST -> WorkflowApiController.handleCreateTemplate(session)
                uri == "/api/workflow/delete" && method == Method.POST -> WorkflowApiController.handleDeleteTemplate(session)
                uri == "/api/workflow/match" && method == Method.POST -> WorkflowApiController.handleMatchTemplate(session)
                uri == "/api/workflow/clear" && method == Method.POST -> WorkflowApiController.handleClearTemplates(session)
                // ==================== Debug (仅 DEBUG 构建) ====================
                uri == "/debug.html" && method == Method.GET && BuildConfig.DEBUG -> serveDebugHtml()
                uri == "/api/debug/tools" && method == Method.GET && BuildConfig.DEBUG -> handleGetTools()
                uri == "/api/debug/execute" && method == Method.POST && BuildConfig.DEBUG -> handleExecuteTool(session)
                uri == "/api/debug/screen-full" && method == Method.GET && BuildConfig.DEBUG -> handleGetScreenFull()
                uri.startsWith("/api/debug/file") && method == Method.GET && BuildConfig.DEBUG -> handleServeFile(session)
                else -> corsResponse(
                    newFixedLengthResponse(
                        Response.Status.NOT_FOUND, MIME_JSON,
                        """{"code":-1,"message":"not found"}"""
                    )
                )
            }
        } catch (e: Exception) {
            XLog.e(TAG, "Server error: ${e.message}")
            val message = e.message ?: "Internal server error"
            val payload = ApiErrorPayload.build(
                errorCode = "internal_error",
                message = message,
                mode = "server",
                currentStep = "failed",
                retryable = true
            )
            corsResponse(
                newFixedLengthResponse(
                    Response.Status.INTERNAL_ERROR, MIME_JSON,
                    payload.toString()
                )
            )
        }
    }

    private fun handleLumiGet(session: IHTTPSession, handler: (IHTTPSession) -> Response): Response {
        val authError = LumiSecurityController.authorize(session)
        if (authError != null) return corsResponse(authError)
        return handler(session)
    }

    private fun handleLumiJson(session: IHTTPSession, handler: (IHTTPSession) -> Response): Response {
        val bodyBytes = try {
            LumiSecurityController.readBodyForSignature(session)
        } catch (e: Exception) {
            return corsResponse(
                LumiSecurityController.jsonElementResponse(
                    Response.Status.BAD_REQUEST,
                    false,
                    null,
                    e.message ?: "Invalid signed Lumi request body"
                )
            )
        }
        val authError = LumiSecurityController.authorize(session, bodyBytes)
        if (authError != null) return corsResponse(authError)
        return handler(CachedBodySession(session, bodyBytes))
    }

    private fun serveHtml(): Response {
        val inputStream = context.assets.open("web/index.html")
        val html = inputStream.bufferedReader().use { it.readText() }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_HTML, html))
    }

    // 电脑端推送 LLM 模型配置 -> 写入手机本地 LLM 设置（地址/密钥/模型名）。
    // 只覆盖非空字段，避免清掉用户已有配置；返回当前结果（密钥脱敏）。
    private fun handleImportLlmConfig(session: IHTTPSession): Response {
        return try {
            val bodyBytes = LumiSecurityController.readBodyForSignature(session)
            val payload = Gson().fromJson(String(bodyBytes, Charsets.UTF_8), JsonObject::class.java)
            val obj = payload?.get("data")?.takeIf { it.isJsonObject }?.asJsonObject ?: payload
            fun str(key: String): String =
                obj?.get(key)?.takeIf { it.isJsonPrimitive }?.asString?.trim() ?: ""
            val baseUrl = str("baseUrl").ifEmpty { str("base_url") }
            val apiKey = str("apiKey").ifEmpty { str("api_key") }
            val model = str("model").ifEmpty { str("modelName") }
            if (baseUrl.isNotBlank()) KVUtils.setLlmBaseUrl(baseUrl)
            if (apiKey.isNotBlank()) KVUtils.setLlmApiKey(apiKey)
            if (model.isNotBlank()) KVUtils.setLlmModelName(model)
            LumiSecurityController.jsonElementResponse(Response.Status.OK, true, currentLlmJson(), null)
        } catch (e: Exception) {
            LumiSecurityController.jsonElementResponse(
                Response.Status.BAD_REQUEST, false, null, e.message ?: "import llm config failed"
            )
        }
    }

    private fun handleExportLlmConfig(): Response {
        return LumiSecurityController.jsonElementResponse(Response.Status.OK, true, currentLlmJson(), null)
    }

    private fun currentLlmJson(): JsonObject = JsonObject().apply {
        addProperty("baseUrl", KVUtils.getLlmBaseUrl())
        addProperty("model", KVUtils.getLlmModelName())
        addProperty("apiKeySet", KVUtils.getLlmApiKey().isNotEmpty())
    }

    private fun handleGetChannels(): Response {
        val data = JsonObject().apply {
            addProperty("dingtalkAppKey", KVUtils.getDingtalkAppKey())
            addProperty("dingtalkAppSecret", KVUtils.getDingtalkAppSecret())
            addProperty("feishuAppId", KVUtils.getFeishuAppId())
            addProperty("feishuAppSecret", KVUtils.getFeishuAppSecret())
            addProperty("qqAppId", KVUtils.getQqAppId())
            addProperty("qqAppSecret", KVUtils.getQqAppSecret())
            addProperty("discordBotToken", KVUtils.getDiscordBotToken())
            addProperty("telegramBotToken", KVUtils.getTelegramBotToken())
        }
        val result = JsonObject().apply {
            addProperty("code", 0)
            add("data", data)
            addProperty("message", "ok")
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun handlePostChannels(session: IHTTPSession): Response {
        // NanoHTTPD 要求先 parseBody 才能读取 POST body
        val files = mutableMapOf<String, String>()
        session.parseBody(files)
        val body = files["postData"] ?: ""

        val json = try {
            gson.fromJson(body, JsonObject::class.java)
        } catch (e: Exception) {
            return corsResponse(
                newFixedLengthResponse(
                    Response.Status.BAD_REQUEST, MIME_JSON,
                    """{"code":-1,"message":"invalid json"}"""
                )
            )
        }

        var reinitDingtalk = false
        var reinitFeishu = false
        var reinitQQ = false
        var reinitDiscord = false
        var reinitTelegram = false

        // 钉钉配置
        if (json.has("dingtalkAppKey")) {
            val value = json.get("dingtalkAppKey").asString
            KVUtils.setDingtalkAppKey(value)
            reinitDingtalk = true
        }
        if (json.has("dingtalkAppSecret")) {
            val value = json.get("dingtalkAppSecret").asString
            // 如果是脱敏值则跳过
            if (!isMaskedValue(value)) {
                KVUtils.setDingtalkAppSecret(value)
                reinitDingtalk = true
            }
        }

        // 飞书配置
        if (json.has("feishuAppId")) {
            val value = json.get("feishuAppId").asString
            KVUtils.setFeishuAppId(value)
            reinitFeishu = true
        }
        if (json.has("feishuAppSecret")) {
            val value = json.get("feishuAppSecret").asString
            if (!isMaskedValue(value)) {
                KVUtils.setFeishuAppSecret(value)
                reinitFeishu = true
            }
        }

        // QQ 配置
        if (json.has("qqAppId")) {
            val value = json.get("qqAppId").asString
            KVUtils.setQqAppId(value)
            reinitQQ = true
        }
        if (json.has("qqAppSecret")) {
            val value = json.get("qqAppSecret").asString
            if (!isMaskedValue(value)) {
                KVUtils.setQqAppSecret(value)
                reinitQQ = true
            }
        }

        // Discord 配置
        if (json.has("discordBotToken")) {
            val value = json.get("discordBotToken").asString
            if (!isMaskedValue(value)) {
                KVUtils.setDiscordBotToken(value)
                reinitDiscord = true
            }
        }

        // Telegram 配置
        if (json.has("telegramBotToken")) {
            val value = json.get("telegramBotToken").asString
            if (!isMaskedValue(value)) {
                KVUtils.setTelegramBotToken(value)
                reinitTelegram = true
            }
        }

        // 重新初始化对应通道
        if (reinitDingtalk) {
            ChannelManager.reinitDingTalkFromStorage()
        }
        if (reinitFeishu) {
            ChannelManager.reinitFeiShuFromStorage()
        }
        if (reinitQQ) {
            ChannelManager.reinitQQFromStorage()
        }
        if (reinitDiscord) {
            ChannelManager.reinitDiscordFromStorage()
        }
        if (reinitTelegram) {
            ChannelManager.reinitTelegramFromStorage()
        }

        // 通知 Settings 页面刷新绑定状态
        if (reinitDingtalk || reinitFeishu || reinitQQ || reinitDiscord || reinitTelegram) {
            ConfigServerManager.notifyConfigChanged()
        }

        val result = JsonObject().apply {
            addProperty("code", 0)
            addProperty("message", "ok")
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun handleGetLlm(): Response {
        val apiKey = KVUtils.getLlmApiKey()
        val data = JsonObject().apply {
            addProperty("llmApiKeyMasked", maskSecret(apiKey))
            addProperty("llmApiKeyConfigured", apiKey.isNotBlank())
            addProperty("llmBaseUrl", KVUtils.getLlmBaseUrl())
            addProperty("llmModelName", KVUtils.getLlmModelName())
        }
        val result = JsonObject().apply {
            addProperty("code", 0)
            add("data", data)
            addProperty("message", "ok")
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun handlePostLlm(session: IHTTPSession): Response {
        val files = mutableMapOf<String, String>()
        session.parseBody(files)
        val body = files["postData"] ?: ""

        val json = try {
            gson.fromJson(body, JsonObject::class.java)
        } catch (e: Exception) {
            return corsResponse(
                newFixedLengthResponse(
                    Response.Status.BAD_REQUEST, MIME_JSON,
                    """{"code":-1,"message":"invalid json"}"""
                )
            )
        }

        if (json.has("llmApiKey")) {
            val value = json.get("llmApiKey").asString
            if (!isMaskedValue(value)) {
                KVUtils.setLlmApiKey(value)
            }
        }
        if (json.has("llmBaseUrl")) {
            KVUtils.setLlmBaseUrl(json.get("llmBaseUrl").asString)
        }
        if (json.has("llmModelName")) {
            val value = json.get("llmModelName").asString.trim()
            KVUtils.setLlmModelName(if (value.isEmpty()) "" else value)
        }

        ConfigServerManager.notifyConfigChanged()

        val result = JsonObject().apply {
            addProperty("code", 0)
            addProperty("message", "ok")
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    // ==================== Debug (仅 DEBUG 构建) ====================
    
    private fun handleGetScreenFull(): Response {
        val service = com.apk.claw.android.service.ClawAccessibilityService.getInstance()
            ?: return corsResponse(
                newFixedLengthResponse(
                    Response.Status.OK, MIME_JSON,
                    """{"code":-1,"message":"Accessibility service is not running"}"""
                )
            )
        val tree = service.screenTreeFull
        val data = JsonObject().apply {
            addProperty("success", tree != null)
            addProperty("data", tree ?: "")
        }
        val result = JsonObject().apply {
            addProperty("code", 0)
            add("data", data)
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun serveDebugHtml(): Response {
        val inputStream = context.assets.open("web/debug.html")
        val html = inputStream.bufferedReader().use { it.readText() }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_HTML, html))
    }

    private fun handleGetTools(): Response {
        val tools = ToolRegistry.getAllTools()
        val arr = JsonArray()
        for (tool in tools) {
            val obj = JsonObject().apply {
                addProperty("name", tool.getName())
                addProperty("displayName", tool.getDisplayName())
                addProperty("description", tool.getDescription())
                val params = JsonArray()
                for (p in tool.getParameters()) {
                    params.add(JsonObject().apply {
                        addProperty("name", p.name)
                        addProperty("type", p.type)
                        addProperty("description", p.description)
                        addProperty("required", p.isRequired)
                    })
                }
                add("parameters", params)
            }
            arr.add(obj)
        }
        val result = JsonObject().apply {
            addProperty("code", 0)
            add("data", arr)
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun handleExecuteTool(session: IHTTPSession): Response {
        val files = mutableMapOf<String, String>()
        session.parseBody(files)
        val body = files["postData"] ?: ""

        val json = try {
            gson.fromJson(body, JsonObject::class.java)
        } catch (e: Exception) {
            return corsResponse(
                newFixedLengthResponse(
                    Response.Status.BAD_REQUEST, MIME_JSON,
                    """{"code":-1,"message":"invalid json"}"""
                )
            )
        }

        val toolName = json.get("tool")?.asString ?: return corsResponse(
            newFixedLengthResponse(
                Response.Status.BAD_REQUEST, MIME_JSON,
                """{"code":-1,"message":"missing tool name"}"""
            )
        )

        val params = mutableMapOf<String, Any>()
        try {
            json.getAsJsonObject("params")?.entrySet()?.forEach { (key, value) ->
                when {
                    value.isJsonNull -> {}
                    !value.isJsonPrimitive -> params[key] = value.toString()
                    value.asJsonPrimitive.isNumber -> params[key] = value.asNumber
                    value.asJsonPrimitive.isBoolean -> params[key] = value.asBoolean
                    else -> params[key] = value.asString
                }
            }
        } catch (e: Exception) {
            XLog.e(TAG, "Debug param parse error: ${e.message}")
        }

        XLog.d(TAG, "Debug execute: $toolName params=$params")

        val toolResult = try {
            ToolRegistry.executeTool(toolName, params)
        } catch (e: Exception) {
            XLog.e(TAG, "Debug execute error", e)
            ToolResult.error("Exception: ${e.message}")
        }

        val data = JsonObject().apply {
            addProperty("success", toolResult.isSuccess)
            addProperty("data", toolResult.data)
            addProperty("error", toolResult.error)
        }
        val result = JsonObject().apply {
            addProperty("code", 0)
            add("data", data)
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, MIME_JSON, result.toString()))
    }

    private fun handleServeFile(session: IHTTPSession): Response {
        val path = session.parameters["path"]?.firstOrNull() ?: return corsResponse(
            newFixedLengthResponse(
                Response.Status.BAD_REQUEST, MIME_JSON,
                """{"code":-1,"message":"missing path param"}"""
            )
        )
        // 安全校验：只允许访问 cache 目录下的文件
        val cacheDir = context.cacheDir.absolutePath
        val file = java.io.File(path)
        if (!file.exists() || !file.absolutePath.startsWith(cacheDir)) {
            return corsResponse(
                newFixedLengthResponse(
                    Response.Status.NOT_FOUND, MIME_JSON,
                    """{"code":-1,"message":"file not found or access denied"}"""
                )
            )
        }
        val mime = when (file.extension.lowercase()) {
            "png" -> "image/png"
            "jpg", "jpeg" -> "image/jpeg"
            "webp" -> "image/webp"
            else -> "application/octet-stream"
        }
        return corsResponse(newFixedLengthResponse(Response.Status.OK, mime, file.inputStream(), file.length()))
    }

    /**
     * 脱敏：只显示后4位，前面用 * 替代
     */
    private fun maskSecret(secret: String): String {
        if (secret.isEmpty()) return ""
        if (secret.length <= 4) return secret
        return "*".repeat(secret.length - 4) + secret.takeLast(4)
    }

    /**
     * 判断是否为脱敏后的值（包含 *）
     */
    private fun isMaskedValue(value: String): Boolean {
        return value.contains("*")
    }

    private fun corsResponse(response: Response): Response {
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader(
            "Access-Control-Allow-Headers",
            "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN, X-LUMI-LAUNCHER-ID, X-LUMI-TIMESTAMP, X-LUMI-NONCE, X-LUMI-SIGNATURE, X-LUMI-BODY-SHA256"
        )
        return response
    }
}
