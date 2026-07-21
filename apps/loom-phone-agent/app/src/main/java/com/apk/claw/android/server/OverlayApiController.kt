package com.apk.claw.android.server

import android.provider.Settings
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.floating.FloatingCircleManager
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.util.Locale

object OverlayApiController {
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"

    fun handleCursor(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        val enabled = getBooleanAny(json, "enabled") ?: true
        val app = ClawApplication.instance

        if (enabled) {
            if (!Settings.canDrawOverlays(app)) {
                return jsonResponse(NanoHTTPD.Response.Status.OK, false, null, "Overlay permission is not granted")
            }
            FloatingCircleManager.show(app)
        } else {
            FloatingCircleManager.hide()
        }

        val data = JsonObject().apply {
            addProperty("enabled", FloatingCircleManager.isShowing())
            addProperty("overlayPermission", Settings.canDrawOverlays(app))
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleCursorPreview(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        val app = ClawApplication.instance
        if (!Settings.canDrawOverlays(app)) {
            return jsonResponse(NanoHTTPD.Response.Status.OK, false, null, "Overlay permission is not granted")
        }

        val metrics = app.resources.displayMetrics
        val x = getIntAny(json, "x") ?: metrics.widthPixels / 2
        val y = getIntAny(json, "y") ?: metrics.heightPixels / 2
        val action = getStringAny(json, "action")?.lowercase(Locale.US) ?: "tap"
        val traceId = getStringAny(json, "traceId", "trace_id")
        val durationMs = (getIntAny(json, "durationMs", "duration_ms") ?: 2400).coerceIn(800, 8000)

        FloatingCircleManager.showCursorPreview(app, action, x, y, traceId, durationMs.toLong())

        val data = JsonObject().apply {
            addProperty("x", x)
            addProperty("y", y)
            addProperty("action", action)
            addProperty("durationMs", durationMs)
            addProperty("traceId", traceId ?: "")
            addProperty("enabled", true)
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
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
        return baseResponse(status, json)
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
        return baseResponse(status, json)
    }

    private fun baseResponse(status: NanoHTTPD.Response.IStatus, json: JsonObject): NanoHTTPD.Response {
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
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
                value.asString.takeIf { it.isNotBlank() }
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
}
