package com.apk.claw.android.server

import android.graphics.BitmapFactory
import android.util.Base64
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 工具 API 控制器
 * 提供外部 HTTP API 用于执行 Android 工具操作
 * 需要 Token 验证
 */
object ToolApiController {

    private const val TAG = "ToolApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private const val ACTION_PREVIEW_DELAY_MS = 900L
    private val gson = Gson()

    /**
     * 验证 Token 并返回错误响应（如果失败）
     * @return null 表示验证通过，否则返回错误响应
     */
    fun checkAuth(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response? {
        if (!TokenValidator.validate(session)) {
            XLog.w(TAG, "Unauthorized API request from ${session.remoteIpAddress}")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                false,
                ApiErrorPayload.build(
                    errorCode = "unauthorized",
                    message = "Unauthorized: invalid or missing token",
                    mode = "auth",
                    currentStep = "failed",
                    retryable = false
                ),
                "Unauthorized: invalid or missing token"
            )
        }
        return null
    }

    /**
     * 处理 POST 请求的 JSON body（支持 UTF-8）
     */
    fun parseJsonBody(session: NanoHTTPD.IHTTPSession): JsonObject? {
        val postData = readJsonBodyUtf8(session)
        if (postData.isBlank()) {
            XLog.e(TAG, "Empty JSON body")
            return null
        }

        XLog.d(TAG, "POST JSON body received (${postData.length} chars)")

        return try {
            gson.fromJson(postData, JsonObject::class.java)
        } catch (e: Exception) {
            XLog.e(TAG, "Invalid JSON: ${e.message}, raw: $postData")
            null
        }
    }

    private fun readJsonBodyUtf8(session: NanoHTTPD.IHTTPSession): String {
        val contentLength = session.headers["content-length"]?.toIntOrNull()
            ?: session.headers["Content-Length"]?.toIntOrNull()
            ?: 0

        if (contentLength > 0) {
            try {
                val buffer = ByteArray(contentLength)
                var total = 0
                while (total < contentLength) {
                    val read = session.inputStream.read(buffer, total, contentLength - total)
                    if (read <= 0) break
                    total += read
                }
                if (total > 0) {
                    return String(buffer, 0, total, Charsets.UTF_8)
                }
            } catch (e: IOException) {
                XLog.e(TAG, "Failed to read raw UTF-8 body: ${e.message}")
            } catch (e: Exception) {
                XLog.e(TAG, "Unexpected error reading raw body: ${e.message}")
            }
        }

        val files = mutableMapOf<String, String>()
        try {
            session.parseBody(files)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to parse body: ${e.message}")
            return ""
        }

        return files["postData"] ?: ""
    }

    /**
     * 执行工具并返回响应
     */
    fun executeToolAndRespond(toolName: String, params: Map<String, Any>): NanoHTTPD.Response {
        val result = executeTool(toolName, params)

        if (!result.isSuccess) {
            return structuredToolError(toolName, result.error ?: "Tool failed", retryable = true)
        }

        return jsonResponse(
            NanoHTTPD.Response.Status.OK,
            true,
            result.data,
            null
        )
    }

    // ==================== 具体工具处理 ====================

    /**
     * 处理 tap 工具
     * POST /api/tool/tap
     * Body: {"x": 100, "y": 200}
     */
    fun handleTap(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val x = json.get("x")?.asInt ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing required parameter: x"
        )
        val y = json.get("y")?.asInt ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing required parameter: y"
        )
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 100
        val traceId = getStringAny(json, "traceId", "trace_id")
        val visualize = getBooleanAny(json, "visualize") ?: false

        showActionPreviewIfNeeded(visualize, "tap", x, y, traceId)
        val result = executeTool("tap", mapOf("x" to x, "y" to y, "duration_ms" to durationMs))
        showActionResultIfNeeded(visualize, result.isSuccess, x, y)
        if (!result.isSuccess) {
            return structuredToolError("tap", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("x", x)
            addProperty("y", y)
            addProperty("durationMs", durationMs)
            addProperty("visualize", visualize)
            if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 swipe 工具
     * POST /api/tool/swipe
     * Body: {"start_x": 0, "start_y": 500, "end_x": 500, "end_y": 500, "duration_ms": 300}
     */
    fun handleSwipe(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val startX = getIntAny(json, "startX", "start_x") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: start_x"
        )
        val startY = getIntAny(json, "startY", "start_y") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: start_y"
        )
        val endX = getIntAny(json, "endX", "end_x") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: end_x"
        )
        val endY = getIntAny(json, "endY", "end_y") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: end_y"
        )
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 300
        val traceId = getStringAny(json, "traceId", "trace_id")
        val visualize = getBooleanAny(json, "visualize") ?: false

        showSwipePreviewIfNeeded(visualize, startX, startY, endX, endY, durationMs, traceId)
        val result = executeTool(
            "swipe",
            mapOf(
                "start_x" to startX,
                "start_y" to startY,
                "end_x" to endX,
                "end_y" to endY,
                "duration_ms" to durationMs
            )
        )
        showActionResultIfNeeded(visualize, result.isSuccess, endX, endY)
        if (!result.isSuccess) {
            return structuredToolError("swipe", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("startX", startX)
            addProperty("startY", startY)
            addProperty("endX", endX)
            addProperty("endY", endY)
            addProperty("durationMs", durationMs)
            addProperty("visualize", visualize)
            if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 drag 工具
     * POST /api/tool/drag
     * Body: {"start_x": 0, "start_y": 500, "end_x": 500, "end_y": 500, "hold_ms": 350, "duration_ms": 700}
     */
    fun handleDrag(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val startX = getIntAny(json, "startX", "start_x") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: start_x"
        )
        val startY = getIntAny(json, "startY", "start_y") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: start_y"
        )
        val endX = getIntAny(json, "endX", "end_x") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: end_x"
        )
        val endY = getIntAny(json, "endY", "end_y") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: end_y"
        )
        val holdMs = getIntAny(json, "holdMs", "hold_ms") ?: 350
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 700
        val traceId = getStringAny(json, "traceId", "trace_id")
        val visualize = getBooleanAny(json, "visualize") ?: false

        showDragPreviewIfNeeded(visualize, startX, startY, endX, endY, holdMs, durationMs, traceId)
        val result = executeTool(
            "drag",
            mapOf(
                "start_x" to startX,
                "start_y" to startY,
                "end_x" to endX,
                "end_y" to endY,
                "hold_ms" to holdMs,
                "duration_ms" to durationMs
            )
        )
        showActionResultIfNeeded(visualize, result.isSuccess, endX, endY)
        if (!result.isSuccess) {
            return structuredToolError("drag", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("startX", startX)
            addProperty("startY", startY)
            addProperty("endX", endX)
            addProperty("endY", endY)
            addProperty("holdMs", holdMs)
            addProperty("durationMs", durationMs)
            addProperty("visualize", visualize)
            if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 long_press 工具
     * POST /api/tool/long_press
     * Body: {"x": 100, "y": 200, "duration_ms": 1000}
     */
    fun handleLongPress(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val x = json.get("x")?.asInt ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: x"
        )
        val y = json.get("y")?.asInt ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: y"
        )
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 500
        val traceId = getStringAny(json, "traceId", "trace_id")
        val visualize = getBooleanAny(json, "visualize") ?: false

        showActionPreviewIfNeeded(visualize, "long_press", x, y, traceId)
        val result = executeTool(
            "long_press",
            mapOf("x" to x, "y" to y, "duration_ms" to durationMs)
        )
        showActionResultIfNeeded(visualize, result.isSuccess, x, y)
        if (!result.isSuccess) {
            return structuredToolError("long_press", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("x", x)
            addProperty("y", y)
            addProperty("durationMs", durationMs)
            addProperty("visualize", visualize)
            if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 screenshot 工具
     * GET /api/tool/screenshot
     * 返回 base64 编码的 PNG 图片
     */
    fun handleScreenshot(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val result = ToolRegistry.executeTool("take_screenshot", emptyMap())

        if (!result.isSuccess) {
            return structuredScreenshotError(result.error ?: "Screenshot failed", retryable = true)
        }

        // 结果是文件路径，读取并转为 base64
        val filePath = result.data
            ?: return structuredScreenshotError("Screenshot path is empty", retryable = true)
        val file = File(filePath)
        if (!file.exists()) {
            return structuredScreenshotError("Screenshot file not found", retryable = true)
        }

        val bytes = file.readBytes()
        val base64 = Base64.encodeToString(bytes, Base64.NO_WRAP)

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        val width = bounds.outWidth.takeIf { it > 0 }
        val height = bounds.outHeight.takeIf { it > 0 }
        val orientation = if (width != null && height != null && width > height) "landscape" else "portrait"

        val data = JsonObject().apply {
            addProperty("mime", "image/png")
            addProperty("base64", base64)
            if (width != null) addProperty("width", width)
            if (height != null) addProperty("height", height)
            addProperty("orientation", orientation)
            addProperty("capturedAt", isoNow())
        }

        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 get_screen_info 工具
     * GET /api/tool/get_screen_info
     * 返回 UI 层级树
     */
    private fun structuredScreenshotError(message: String, retryable: Boolean): NanoHTTPD.Response {
        return jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            false,
            ApiErrorPayload.build(
                errorCode = "screenshot_failed",
                message = message,
                mode = "screenshot",
                currentStep = "failed",
                retryable = retryable
            ),
            message
        )
    }

    private fun structuredToolError(
        toolName: String,
        message: String,
        errorCode: String = toolErrorCode(toolName),
        retryable: Boolean
    ): NanoHTTPD.Response {
        return jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            false,
            ApiErrorPayload.build(
                errorCode = errorCode,
                message = message,
                mode = toolMode(toolName),
                currentStep = "failed",
                retryable = retryable
            ),
            message
        )
    }

    private fun toolMode(toolName: String): String {
        return when (toolName) {
            "get_screen_info", "screen_tree", "find_node_info" -> "read"
            "take_screenshot" -> "screenshot"
            else -> "tool"
        }
    }

    private fun toolErrorCode(toolName: String): String {
        return when (toolName) {
            "get_screen_info" -> "screen_info_failed"
            "screen_tree" -> "screen_tree_failed"
            "take_screenshot" -> "screenshot_failed"
            else -> "${toolName.lowercase(Locale.US).replace(Regex("[^a-z0-9_]+"), "_").trim('_')}_failed"
        }
    }

    fun handleGetScreenInfo(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        return executeToolAndRespond("get_screen_info", emptyMap())
    }

    /**
     * 处理结构化 screen tree
     * GET /api/tool/screen_tree
     */
    fun handleScreenTree(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val service = ClawAccessibilityService.getInstance()
            ?: return structuredToolError(
                toolName = "screen_tree",
                message = "Accessibility service is not running",
                errorCode = "accessibility_reenable_required",
                retryable = false
            )

        val tree = service.screenTreeJson
            ?: return structuredToolError(
                toolName = "screen_tree",
                message = "System dialog blocked the screen",
                errorCode = "system_dialog_blocked",
                retryable = true
            )

        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, tree, null)
    }

    /**
     * 处理 find_node_info 工具
     * POST /api/tool/find_node_info
     * Body: {"text": "登录", "resource_id": "com.app:id/button"}
     */
    fun handleFindNodeInfo(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val params = mutableMapOf<String, Any>()
        if (json.has("text")) params["text"] = json.get("text").asString
        if (json.has("resource_id")) params["resource_id"] = json.get("resource_id").asString

        return executeToolAndRespond("find_node_info", params)
    }

    /**
     * 处理 open_app 工具
     * POST /api/tool/open_app
     * Body: {"package_name": "com.example.app"}
     */
    fun handleOpenApp(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val packageName = json.get("package_name")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: package_name"
        )
        val verifyForeground = getBooleanAny(json, "verify_foreground", "verifyForeground") ?: true

        return executeToolAndRespond(
            "open_app",
            mapOf("package_name" to packageName, "verify_foreground" to verifyForeground)
        )
    }

    /**
     * 处理 input_text 工具
     * POST /api/tool/input_text
     * Body: {"text": "Hello World"}
     */
    fun handleInputText(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val text = json.get("text")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: text"
        )
        val traceId = getStringAny(json, "traceId", "trace_id")

        val result = executeTool("input_text", mapOf("text" to text))
        if (!result.isSuccess) {
            return structuredToolError("input_text", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("traceId", traceId ?: "")
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 system_key 工具
     * POST /api/tool/system_key
     * Body: {"key": "back"}  // back, home, recent, notification, settings
     */
    fun handleSystemKey(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val key = json.get("key")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: key"
        )
        val traceId = getStringAny(json, "traceId", "trace_id")
        val normalizedKey = normalizeSystemKey(key)

        val result = executeTool("system_key", mapOf("key" to normalizedKey))
        if (!result.isSuccess) {
            return structuredToolError("system_key", result.error ?: "Tool failed", retryable = true)
        }

        val data = JsonObject().apply {
            addProperty("key", key)
            addProperty("normalizedKey", normalizedKey)
            if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
            addProperty("executedAt", isoNow())
            addProperty("message", result.data ?: "")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    /**
     * 处理 get_installed_apps 工具
     * GET /api/tool/get_installed_apps
     */
    fun handleGetInstalledApps(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        return executeToolAndRespond("get_installed_apps", emptyMap())
    }

    /**
     * 处理 wait 工具
     * POST /api/tool/wait
     * Body: {"duration_ms": 1000}
     */
    fun handleWait(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val durationMs = json.get("duration_ms")?.asInt ?: 1000

        return executeToolAndRespond("wait", mapOf("duration_ms" to durationMs))
    }

    /**
     * 处理 scroll_to_find 工具
     * POST /api/tool/scroll_to_find
     * Body: {"target_text": "目标文本", "direction": "down", "max_swipes": 10}
     */
    fun handleScrollToFind(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val params = mutableMapOf<String, Any>()
        if (json.has("target_text")) params["target_text"] = json.get("target_text").asString
        if (json.has("direction")) params["direction"] = json.get("direction").asString
        if (json.has("max_swipes")) params["max_swipes"] = json.get("max_swipes").asInt

        return executeToolAndRespond("scroll_to_find", params)
    }

    // ==================== 工具方法 ====================

    /**
     * 创建 JSON 响应（UTF-8）
     */
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

    private fun executeTool(toolName: String, params: Map<String, Any>): ToolResult {
        XLog.d(TAG, "Execute tool: $toolName, params=${sanitizeParamsForLog(params)}")
        return try {
            ToolRegistry.executeTool(toolName, params)
        } catch (e: Exception) {
            XLog.e(TAG, "Tool execution error", e)
            ToolResult.error("Exception: ${e.message}")
        }
    }

    private fun showActionPreviewIfNeeded(
        visualize: Boolean,
        action: String,
        x: Int,
        y: Int,
        traceId: String?
    ) {
        if (!visualize) return
        try {
            FloatingCircleManager.showActionPreview(ClawApplication.instance, action, x, y, traceId)
            Thread.sleep(ACTION_PREVIEW_DELAY_MS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to show action preview: ${e.message}")
        }
    }

    private fun showSwipePreviewIfNeeded(
        visualize: Boolean,
        startX: Int,
        startY: Int,
        endX: Int,
        endY: Int,
        durationMs: Int,
        traceId: String?
    ) {
        if (!visualize) return
        try {
            FloatingCircleManager.showSwipePreview(
                ClawApplication.instance,
                startX,
                startY,
                endX,
                endY,
                durationMs,
                traceId,
                ACTION_PREVIEW_DELAY_MS
            )
            Thread.sleep(ACTION_PREVIEW_DELAY_MS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to show swipe preview: ${e.message}")
        }
    }

    private fun showDragPreviewIfNeeded(
        visualize: Boolean,
        startX: Int,
        startY: Int,
        endX: Int,
        endY: Int,
        holdMs: Int,
        durationMs: Int,
        traceId: String?
    ) {
        if (!visualize) return
        try {
            FloatingCircleManager.showDragPreview(
                ClawApplication.instance,
                startX,
                startY,
                endX,
                endY,
                holdMs,
                durationMs,
                traceId,
                ACTION_PREVIEW_DELAY_MS
            )
            Thread.sleep(ACTION_PREVIEW_DELAY_MS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to show drag preview: ${e.message}")
        }
    }

    private fun showActionResultIfNeeded(visualize: Boolean, success: Boolean, x: Int, y: Int) {
        if (!visualize) return
        try {
            FloatingCircleManager.showActionResult(success, x, y)
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to show action result: ${e.message}")
        }
    }

    private fun sanitizeParamsForLog(params: Map<String, Any>): Map<String, Any> {
        return params.mapValues { (key, value) ->
            val lower = key.lowercase(Locale.US)
            if (lower.contains("token") || lower.contains("secret") || lower.contains("password") || lower.contains("apikey") || lower == "text") {
                "***"
            } else {
                value
            }
        }
    }

    private fun getIntAny(json: JsonObject, vararg names: String): Int? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asInt
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    private fun getStringAny(json: JsonObject, vararg names: String): String? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asString
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    private fun getBooleanAny(json: JsonObject, vararg names: String): Boolean? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asBoolean
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    private fun normalizeSystemKey(key: String): String {
        return when (key.trim().lowercase(Locale.US)) {
            "back" -> "back"
            "home" -> "home"
            "recent", "recents", "recent_apps", "recent-apps", "recent apps" -> "recent_apps"
            "enter" -> "enter"
            "power" -> "power"
            "volume_up", "volume-up", "volume up", "volumeup" -> "volume_up"
            "volume_down", "volume-down", "volume down", "volumedown" -> "volume_down"
            else -> key.trim().lowercase(Locale.US)
        }
    }

    private fun isoNow(): String {
        return SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date())
    }

    /**
     * 获取可用工具列表
     * GET /api/tool/list
     */
    fun handleToolList(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val tools = ToolRegistry.getAllTools()
        val arr = com.google.gson.JsonArray()
        for (tool in tools) {
            val obj = JsonObject().apply {
                addProperty("name", tool.getName())
                addProperty("displayName", tool.getDisplayName())
                addProperty("description", tool.getDescription())
            }
            arr.add(obj)
        }

        val json = JsonObject().apply {
            addProperty("success", true)
            add("tools", arr)
        }
        val response = NanoHTTPD.newFixedLengthResponse(NanoHTTPD.Response.Status.OK, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }
}
