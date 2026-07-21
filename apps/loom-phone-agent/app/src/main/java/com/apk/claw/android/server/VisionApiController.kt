package com.apk.claw.android.server

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.Base64
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.utils.XLog
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

object VisionApiController {
    private const val TAG = "VisionApi"
    private const val ACTION_PREVIEW_DELAY_MS = 450L
    private const val DEFAULT_GRID_COLUMNS = 6
    private const val DEFAULT_GRID_ROWS = 12
    private const val DEFAULT_MAX_LONG_SIDE = 1600

    fun handleStatus(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val currentScreen = DeviceProfileApiController.buildCurrentScreenInfoForApi()
        val data = JsonObject().apply {
            addProperty("mode", "vision")
            addProperty("available", ClawAccessibilityService.getInstance() != null)
            addProperty("requiresAccessibilityService", true)
            addProperty("capturedAt", isoNow())
            add("currentScreen", currentScreen)
            add("vision", DeviceProfileApiController.buildVisionHintsForApi(currentScreen))
            add("input", buildInputSpec())
            add("safety", VisionSafetyGuard.policyJson())
        }
        return LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleFrame(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val service = ClawAccessibilityService.getInstance()
            ?: return errorResponse(NanoHTTPD.Response.Status.OK, "accessibility_reenable_required", "Accessibility service is not running", mode = "screenshot")

        val includeScreenshot = getBooleanParam(session, "includeScreenshot")
            ?: getBooleanParam(session, "include_screenshot")
            ?: true
        val overlayGrid = getBooleanParam(session, "overlayGrid")
            ?: getBooleanParam(session, "overlay_grid")
            ?: true
        val format = (getStringParam(session, "format") ?: "jpeg").lowercase(Locale.US)
        val jpegQuality = (getIntParam(session, "quality") ?: 82).coerceIn(45, 95)
        val maxLongSide = (getIntParam(session, "maxLongSide")
            ?: getIntParam(session, "max_long_side")
            ?: DEFAULT_MAX_LONG_SIDE).coerceIn(480, 4096)
        val gridColumns = (getIntParam(session, "gridColumns")
            ?: getIntParam(session, "grid_columns")
            ?: DEFAULT_GRID_COLUMNS).coerceIn(2, 12)
        val gridRows = (getIntParam(session, "gridRows")
            ?: getIntParam(session, "grid_rows")
            ?: DEFAULT_GRID_ROWS).coerceIn(2, 24)

        var bitmap: Bitmap? = null
        var rendered: Bitmap? = null
        var scaled: Bitmap? = null

        return try {
            val data = JsonObject()
            val currentScreen = DeviceProfileApiController.buildCurrentScreenInfoForApi()
            data.addProperty("mode", "vision")
            data.addProperty("capturedAt", isoNow())
            data.add("currentScreen", currentScreen)
            data.add("vision", DeviceProfileApiController.buildVisionHintsForApi(currentScreen))
            data.add("input", buildInputSpec())
            data.add("safety", VisionSafetyGuard.policyJson())

            if (includeScreenshot) {
                bitmap = service.takeScreenshot(5000)
                    ?: return errorResponse(NanoHTTPD.Response.Status.OK, "screenshot_failed", "Failed to take screenshot. Requires Android 11+ (API 30).", mode = "screenshot", retryable = true)
                val originalWidth = bitmap!!.width
                val originalHeight = bitmap!!.height
                rendered = if (overlayGrid) drawGridOverlay(bitmap!!, gridColumns, gridRows) else bitmap
                scaled = scaleForTransport(rendered!!, maxLongSide)
                val encoded = encodeBitmap(scaled!!, format, jpegQuality)
                data.add("image", JsonObject().apply {
                    addProperty("mime", encoded.mime)
                    addProperty("base64", encoded.base64)
                    addProperty("width", scaled!!.width)
                    addProperty("height", scaled!!.height)
                    addProperty("originalWidth", originalWidth)
                    addProperty("originalHeight", originalHeight)
                    addProperty("orientation", if (originalWidth > originalHeight) "landscape" else "portrait")
                    addProperty("format", encoded.format)
                    addProperty("quality", if (encoded.format == "jpeg") jpegQuality else 100)
                    addProperty("overlayGrid", overlayGrid)
                    addProperty("maxLongSide", maxLongSide)
                })
                data.add("coordinateSpace", buildCoordinateSpace(originalWidth, originalHeight, scaled!!.width, scaled!!.height, gridColumns, gridRows))
            } else {
                val metrics = ClawApplication.instance.resources.displayMetrics
                data.add("coordinateSpace", buildCoordinateSpace(metrics.widthPixels, metrics.heightPixels, metrics.widthPixels, metrics.heightPixels, gridColumns, gridRows))
            }

            LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "vision frame failed: ${e.message}")
            errorResponse(NanoHTTPD.Response.Status.OK, "screenshot_failed", "Vision frame failed: ${e.message}", mode = "screenshot", retryable = true)
        } finally {
            recycleIfDistinct(scaled, rendered)
            recycleIfDistinct(rendered, bitmap)
            bitmap?.takeUnless { it.isRecycled }?.recycle()
        }
    }

    fun handleAction(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val service = ClawAccessibilityService.getInstance()
        if (service == null) {
            return errorResponse(NanoHTTPD.Response.Status.OK, "accessibility_reenable_required", "Accessibility service is not running", mode = "vision_action")
        }
        val json = ToolApiController.parseJsonBody(session)
            ?: return errorResponse(NanoHTTPD.Response.Status.BAD_REQUEST, "invalid_json", "Invalid JSON body", mode = "vision_action")
        val action = getStringAny(json, "action", "type")?.lowercase(Locale.US)
            ?: return errorResponse(NanoHTTPD.Response.Status.BAD_REQUEST, "missing_action", "Missing action", mode = "vision_action")
        val safety = VisionSafetyGuard.inspect(action, json, service.currentPackageName)
        if (!safety.allowed) {
            val data = ApiErrorPayload.build(
                errorCode = "safety_blocked",
                message = safety.reason,
                mode = "vision_action",
                currentStep = "failed",
                retryable = false
            ).apply {
                addProperty("action", action)
                addProperty("blocked", true)
                add("safety", safety.toJson())
            }
            return LumiSecurityController.jsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                data,
                safety.reason
            )
        }
        val metrics = ClawApplication.instance.resources.displayMetrics
        val screenWidth = getIntAny(json, "screenWidth", "screen_width") ?: metrics.widthPixels
        val screenHeight = getIntAny(json, "screenHeight", "screen_height") ?: metrics.heightPixels
        val visualize = getBooleanAny(json, "visualize") ?: true
        val traceId = getStringAny(json, "traceId", "trace_id")

        return try {
            val execution = when (action) {
                "tap" -> executeTap(json, screenWidth, screenHeight, visualize, traceId)
                "long_press", "longpress" -> executeLongPress(json, screenWidth, screenHeight, visualize, traceId)
                "swipe" -> executeSwipe(json, screenWidth, screenHeight, visualize, traceId)
                "drag" -> executeDrag(json, screenWidth, screenHeight, visualize, traceId)
                else -> return errorResponse(NanoHTTPD.Response.Status.BAD_REQUEST, "unsupported_action", "Unsupported vision action: $action", mode = "vision_action")
            }

            val data = execution.data.apply {
                addProperty("action", action)
                addProperty("visualize", visualize)
                add("safety", safety.toJson())
                if (!traceId.isNullOrBlank()) addProperty("traceId", traceId)
                addProperty("executedAt", isoNow())
            }
            LumiSecurityController.jsonElementResponse(
                NanoHTTPD.Response.Status.OK,
                execution.result.isSuccess,
                data,
                execution.result.error
            )
        } catch (e: IllegalArgumentException) {
            errorResponse(NanoHTTPD.Response.Status.BAD_REQUEST, "invalid_action", e.message ?: "Invalid vision action", mode = "vision_action")
        } catch (e: Exception) {
            XLog.e(TAG, "vision action failed: ${e.message}")
            errorResponse(NanoHTTPD.Response.Status.OK, "vision_action_failed", "Vision action failed: ${e.message}", mode = "vision_action", retryable = true)
        }
    }

    private fun executeTap(
        json: JsonObject,
        screenWidth: Int,
        screenHeight: Int,
        visualize: Boolean,
        traceId: String?
    ): Execution {
        val point = resolvePoint(json, "", screenWidth, screenHeight)
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 100
        showActionPreviewIfNeeded(visualize, "tap", point.x, point.y, traceId)
        val result = ToolRegistry.executeTool("tap", mapOf("x" to point.x, "y" to point.y, "duration_ms" to durationMs))
        showActionResultIfNeeded(visualize, result.isSuccess, point.x, point.y)
        return Execution(result, JsonObject().apply {
            add("point", point.toJson())
            addProperty("durationMs", durationMs)
            addProperty("message", result.data ?: "")
        })
    }

    private fun executeLongPress(
        json: JsonObject,
        screenWidth: Int,
        screenHeight: Int,
        visualize: Boolean,
        traceId: String?
    ): Execution {
        val point = resolvePoint(json, "", screenWidth, screenHeight)
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 650
        showActionPreviewIfNeeded(visualize, "long_press", point.x, point.y, traceId)
        val result = ToolRegistry.executeTool("long_press", mapOf("x" to point.x, "y" to point.y, "duration_ms" to durationMs))
        showActionResultIfNeeded(visualize, result.isSuccess, point.x, point.y)
        return Execution(result, JsonObject().apply {
            add("point", point.toJson())
            addProperty("durationMs", durationMs)
            addProperty("message", result.data ?: "")
        })
    }

    private fun executeSwipe(
        json: JsonObject,
        screenWidth: Int,
        screenHeight: Int,
        visualize: Boolean,
        traceId: String?
    ): Execution {
        val start = resolvePoint(json, "start", screenWidth, screenHeight)
        val end = resolvePoint(json, "end", screenWidth, screenHeight)
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 420
        showSwipePreviewIfNeeded(visualize, start.x, start.y, end.x, end.y, durationMs, traceId)
        val result = ToolRegistry.executeTool(
            "swipe",
            mapOf("start_x" to start.x, "start_y" to start.y, "end_x" to end.x, "end_y" to end.y, "duration_ms" to durationMs)
        )
        showActionResultIfNeeded(visualize, result.isSuccess, end.x, end.y)
        return Execution(result, JsonObject().apply {
            add("start", start.toJson())
            add("end", end.toJson())
            addProperty("durationMs", durationMs)
            addProperty("message", result.data ?: "")
        })
    }

    private fun executeDrag(
        json: JsonObject,
        screenWidth: Int,
        screenHeight: Int,
        visualize: Boolean,
        traceId: String?
    ): Execution {
        val start = resolvePoint(json, "start", screenWidth, screenHeight)
        val end = resolvePoint(json, "end", screenWidth, screenHeight)
        val holdMs = getIntAny(json, "holdMs", "hold_ms") ?: 350
        val durationMs = getIntAny(json, "durationMs", "duration_ms") ?: 700
        showDragPreviewIfNeeded(visualize, start.x, start.y, end.x, end.y, holdMs, durationMs, traceId)
        val result = ToolRegistry.executeTool(
            "drag",
            mapOf("start_x" to start.x, "start_y" to start.y, "end_x" to end.x, "end_y" to end.y, "hold_ms" to holdMs, "duration_ms" to durationMs)
        )
        showActionResultIfNeeded(visualize, result.isSuccess, end.x, end.y)
        return Execution(result, JsonObject().apply {
            add("start", start.toJson())
            add("end", end.toJson())
            addProperty("holdMs", holdMs)
            addProperty("durationMs", durationMs)
            addProperty("message", result.data ?: "")
        })
    }

    private fun resolvePoint(json: JsonObject, prefix: String, screenWidth: Int, screenHeight: Int): Point {
        val nested = when (prefix) {
            "start" -> json.getAsJsonObjectOrNull("start") ?: json.getAsJsonObjectOrNull("from")
            "end" -> json.getAsJsonObjectOrNull("end") ?: json.getAsJsonObjectOrNull("to")
            else -> json.getAsJsonObjectOrNull("point")
        }
        if (nested != null) {
            return resolvePoint(nested, "", screenWidth, screenHeight)
        }

        val x = getIntAny(json, key(prefix, "X"), key(prefix, "x"))
        val y = getIntAny(json, key(prefix, "Y"), key(prefix, "y"))
        if (x != null && y != null) return checkedPoint(x, y, screenWidth, screenHeight, "screen")

        val nx = getDoubleAny(json, key(prefix, "Nx"), key(prefix, "nx"), key(prefix, "NormalizedX"), key(prefix, "normalizedX"), key(prefix, "normalized_x"))
        val ny = getDoubleAny(json, key(prefix, "Ny"), key(prefix, "ny"), key(prefix, "NormalizedY"), key(prefix, "normalizedY"), key(prefix, "normalized_y"))
        if (nx != null && ny != null) {
            return checkedPoint((nx * (screenWidth - 1)).roundToInt(), (ny * (screenHeight - 1)).roundToInt(), screenWidth, screenHeight, "normalized")
        }

        val imageX = getDoubleAny(json, key(prefix, "ImageX"), key(prefix, "imageX"), key(prefix, "image_x"))
        val imageY = getDoubleAny(json, key(prefix, "ImageY"), key(prefix, "imageY"), key(prefix, "image_y"))
        val imageWidth = getDoubleAny(json, "imageWidth", "image_width")
        val imageHeight = getDoubleAny(json, "imageHeight", "image_height")
        if (imageX != null && imageY != null && imageWidth != null && imageHeight != null && imageWidth > 0 && imageHeight > 0) {
            return checkedPoint((imageX * screenWidth / imageWidth).roundToInt(), (imageY * screenHeight / imageHeight).roundToInt(), screenWidth, screenHeight, "image")
        }

        val gridCell = getStringAny(json, key(prefix, "GridCell"), key(prefix, "gridCell"), key(prefix, "grid_cell"))
        if (!gridCell.isNullOrBlank()) {
            val columns = (getIntAny(json, "gridColumns", "grid_columns") ?: DEFAULT_GRID_COLUMNS).coerceIn(2, 12)
            val rows = (getIntAny(json, "gridRows", "grid_rows") ?: DEFAULT_GRID_ROWS).coerceIn(2, 24)
            return gridCellPoint(gridCell, columns, rows, screenWidth, screenHeight)
        }

        throw IllegalArgumentException("Missing ${if (prefix.isBlank()) "" else "$prefix "}coordinates. Use x/y, nx/ny, imageX/imageY+imageWidth/imageHeight, or gridCell.")
    }

    private fun checkedPoint(x: Int, y: Int, width: Int, height: Int, source: String): Point {
        if (x < 0 || y < 0 || x >= width || y >= height) {
            throw IllegalArgumentException("Coordinates ($x, $y) out of screen bounds (${width}x${height})")
        }
        return Point(x, y, source)
    }

    private fun gridCellPoint(cell: String, columns: Int, rows: Int, width: Int, height: Int): Point {
        val match = Regex("^([A-Za-z]+)(\\d{1,2})$").matchEntire(cell.trim())
            ?: throw IllegalArgumentException("Invalid grid cell: $cell")
        val columnLabel = match.groupValues[1].uppercase(Locale.US)
        val row = match.groupValues[2].toInt() - 1
        var column = 0
        for (char in columnLabel) {
            column = column * 26 + (char - 'A' + 1)
        }
        column -= 1
        if (column !in 0 until columns || row !in 0 until rows) {
            throw IllegalArgumentException("Grid cell $cell is outside ${columns}x${rows}")
        }
        return checkedPoint(
            (((column + 0.5) / columns) * (width - 1)).roundToInt(),
            (((row + 0.5) / rows) * (height - 1)).roundToInt(),
            width,
            height,
            "grid"
        )
    }

    private fun drawGridOverlay(source: Bitmap, columns: Int, rows: Int): Bitmap {
        val bitmap = source.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(bitmap)
        val cellWidth = bitmap.width.toFloat() / columns
        val cellHeight = bitmap.height.toFloat() / rows
        val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(100, 255, 214, 75)
            strokeWidth = max(1f, min(bitmap.width, bitmap.height) / 520f)
        }
        val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(235, 255, 255, 255)
            textSize = max(10f, min(cellWidth, cellHeight) * 0.2f)
            setShadowLayer(3f, 1f, 1f, Color.BLACK)
        }
        for (column in 0..columns) {
            val x = column * cellWidth
            canvas.drawLine(x, 0f, x, bitmap.height.toFloat(), linePaint)
        }
        for (row in 0..rows) {
            val y = row * cellHeight
            canvas.drawLine(0f, y, bitmap.width.toFloat(), y, linePaint)
        }
        for (row in 0 until rows) {
            for (column in 0 until columns) {
                val label = "${columnLabel(column)}${row + 1}"
                canvas.drawText(label, column * cellWidth + 6f, row * cellHeight + textPaint.textSize + 4f, textPaint)
            }
        }
        return bitmap
    }

    private fun scaleForTransport(source: Bitmap, maxLongSide: Int): Bitmap {
        val longSide = max(source.width, source.height)
        if (longSide <= maxLongSide) return source
        val scale = maxLongSide.toFloat() / longSide
        val width = max(1, (source.width * scale).roundToInt())
        val height = max(1, (source.height * scale).roundToInt())
        return Bitmap.createScaledBitmap(source, width, height, true)
    }

    private fun encodeBitmap(bitmap: Bitmap, requestedFormat: String, jpegQuality: Int): EncodedImage {
        val format = if (requestedFormat == "png") "png" else "jpeg"
        val compressFormat = if (format == "png") Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG
        val output = ByteArrayOutputStream()
        bitmap.compress(compressFormat, if (format == "png") 100 else jpegQuality, output)
        return EncodedImage(
            mime = if (format == "png") "image/png" else "image/jpeg",
            format = format,
            base64 = Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
        )
    }

    private fun buildCoordinateSpace(
        screenWidth: Int,
        screenHeight: Int,
        imageWidth: Int,
        imageHeight: Int,
        gridColumns: Int,
        gridRows: Int
    ): JsonObject {
        return JsonObject().apply {
            addProperty("screenWidth", screenWidth)
            addProperty("screenHeight", screenHeight)
            addProperty("imageWidth", imageWidth)
            addProperty("imageHeight", imageHeight)
            addProperty("actionCoordinates", "screen_pixels")
            addProperty("imageToScreenX", screenWidth.toDouble() / imageWidth.toDouble())
            addProperty("imageToScreenY", screenHeight.toDouble() / imageHeight.toDouble())
            add("grid", JsonObject().apply {
                addProperty("columns", gridColumns)
                addProperty("rows", gridRows)
                addProperty("cellFormat", "A1")
                addProperty("firstCell", "A1")
                addProperty("lastCell", "${columnLabel(gridColumns - 1)}$gridRows")
            })
        }
    }

    private fun buildInputSpec(): JsonObject {
        return JsonObject().apply {
            addProperty("coordinatePriority", "gridCell > imageX/imageY > nx/ny > x/y")
            addProperty("safetyMetadata", "For tap/long_press/swipe/drag include targetLabel and reason. Sensitive targets are blocked.")
            addProperty("tapExample", """{"action":"tap","gridCell":"C7"}""")
            addProperty("swipeExample", """{"action":"swipe","start":{"nx":0.5,"ny":0.78},"end":{"nx":0.5,"ny":0.35}}""")
            addProperty("dragExample", """{"action":"drag","start":{"imageX":320,"imageY":700},"end":{"imageX":520,"imageY":700},"imageWidth":720,"imageHeight":1600}""")
        }
    }

    private fun showActionPreviewIfNeeded(visualize: Boolean, action: String, x: Int, y: Int, traceId: String?) {
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

    private fun showSwipePreviewIfNeeded(visualize: Boolean, startX: Int, startY: Int, endX: Int, endY: Int, durationMs: Int, traceId: String?) {
        if (!visualize) return
        try {
            FloatingCircleManager.showSwipePreview(ClawApplication.instance, startX, startY, endX, endY, durationMs, traceId, ACTION_PREVIEW_DELAY_MS)
            Thread.sleep(ACTION_PREVIEW_DELAY_MS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        } catch (e: Exception) {
            XLog.w(TAG, "Failed to show swipe preview: ${e.message}")
        }
    }

    private fun showDragPreviewIfNeeded(visualize: Boolean, startX: Int, startY: Int, endX: Int, endY: Int, holdMs: Int, durationMs: Int, traceId: String?) {
        if (!visualize) return
        try {
            FloatingCircleManager.showDragPreview(ClawApplication.instance, startX, startY, endX, endY, holdMs, durationMs, traceId, ACTION_PREVIEW_DELAY_MS)
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

    private fun errorResponse(
        status: NanoHTTPD.Response.IStatus,
        errorCode: String,
        message: String,
        mode: String = "vision",
        retryable: Boolean = false
    ): NanoHTTPD.Response {
        return LumiSecurityController.jsonElementResponse(
            status,
            false,
            ApiErrorPayload.build(
                errorCode = errorCode,
                message = message,
                mode = mode,
                currentStep = "failed",
                retryable = retryable
            ),
            message
        )
    }

    private fun getStringParam(session: NanoHTTPD.IHTTPSession, name: String): String? =
        session.parameters[name]?.firstOrNull()?.takeIf { it.isNotBlank() }

    private fun getIntParam(session: NanoHTTPD.IHTTPSession, name: String): Int? =
        getStringParam(session, name)?.toIntOrNull()

    private fun getBooleanParam(session: NanoHTTPD.IHTTPSession, name: String): Boolean? =
        getStringParam(session, name)?.let { it == "1" || it.equals("true", ignoreCase = true) || it.equals("yes", ignoreCase = true) }

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

    private fun getDoubleAny(json: JsonObject, vararg names: String): Double? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asDouble
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

    private fun JsonObject.getAsJsonObjectOrNull(name: String): JsonObject? {
        val value: JsonElement = get(name) ?: return null
        return if (value.isJsonObject) value.asJsonObject else null
    }

    private fun key(prefix: String, suffix: String): String {
        if (prefix.isBlank()) return suffix
        if (suffix.contains("_")) return "${prefix}_$suffix"
        return prefix + suffix.replaceFirstChar { char -> char.uppercase(Locale.US) }
    }

    private fun columnLabel(index: Int): String {
        var value = index + 1
        val out = StringBuilder()
        while (value > 0) {
            val rem = (value - 1) % 26
            out.insert(0, ('A'.code + rem).toChar())
            value = (value - 1) / 26
        }
        return out.toString()
    }

    private fun recycleIfDistinct(candidate: Bitmap?, other: Bitmap?) {
        if (candidate != null && candidate !== other && !candidate.isRecycled) {
            candidate.recycle()
        }
    }

    private fun isoNow(): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSZ", Locale.US).format(Date())

    private data class Point(val x: Int, val y: Int, val source: String) {
        fun toJson(): JsonObject = JsonObject().apply {
            addProperty("x", x)
            addProperty("y", y)
            addProperty("source", source)
        }
    }

    private data class EncodedImage(val mime: String, val format: String, val base64: String)

    private data class Execution(val result: ToolResult, val data: JsonObject)
}
