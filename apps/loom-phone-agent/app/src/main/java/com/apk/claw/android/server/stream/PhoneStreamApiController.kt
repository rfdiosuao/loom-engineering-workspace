package com.apk.claw.android.server.stream

import android.content.Context
import com.apk.claw.android.server.LumiSecurityController
import com.apk.claw.android.server.ToolApiController
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD

object PhoneStreamApiController {
    private const val MIME_H264 = "application/vnd.luming.h264"
    private val clientSessionPattern = Regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

    fun handleCreate(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val body = ToolApiController.parseJsonBody(session)
            ?: return jsonError(NanoHTTPD.Response.Status.BAD_REQUEST, "phone_stream_input_invalid", "Invalid JSON body")
        val clientSessionId = body.string("clientSessionId")
        val launcherId = session.headers["x-lumi-launcher-id"].orEmpty().trim()
        if (!clientSessionPattern.matches(clientSessionId) || launcherId.isBlank()) {
            return jsonError(NanoHTTPD.Response.Status.BAD_REQUEST, "phone_stream_input_invalid", "Invalid stream session identity")
        }
        val grant = PhoneStreamManager.requestStart(
            context.applicationContext,
            clientSessionId,
            launcherId,
            PhoneStreamOptions(
                fps = body.int("fps", 15),
                maxLongSide = body.int("maxLongSide", 1280),
                bitRate = body.int("bitRate", 2_400_000)
            )
        )
        return LumiSecurityController.jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            true,
            grantJson(grant),
            null
        )
    }

    fun handleH264(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val sessionId = session.parameters["sessionId"]?.firstOrNull().orEmpty().trim()
        val launcherId = session.headers["x-lumi-launcher-id"].orEmpty().trim()
        val streamToken = session.headers["x-lumi-stream-token"].orEmpty().trim()
        val input = PhoneStreamRuntime.sessions.open(sessionId, streamToken, launcherId)
            ?: return jsonError(NanoHTTPD.Response.Status.FORBIDDEN, "phone_stream_grant_invalid", "Stream grant is invalid or expired")
        return NanoHTTPD.newChunkedResponse(NanoHTTPD.Response.Status.OK, MIME_H264, input).apply {
            addHeader("Cache-Control", "no-store")
            addHeader("X-Content-Type-Options", "nosniff")
            addHeader("X-Lumi-Stream-Protocol", "lumi-h264-framed-v1")
        }
    }

    fun handleStop(context: Context, session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val body = ToolApiController.parseJsonBody(session)
            ?: return jsonError(NanoHTTPD.Response.Status.BAD_REQUEST, "phone_stream_input_invalid", "Invalid JSON body")
        val launcherId = session.headers["x-lumi-launcher-id"].orEmpty().trim()
        val stopped = PhoneStreamManager.stop(
            context.applicationContext,
            body.string("sessionId"),
            body.string("streamToken"),
            launcherId
        )
        return LumiSecurityController.jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            true,
            JsonObject().apply {
                addProperty("stopped", stopped)
                addProperty("state", if (stopped) "stopped" else "not_found")
            },
            null
        )
    }

    private fun grantJson(grant: PhoneStreamGrant): JsonObject = JsonObject().apply {
        addProperty("state", grant.state)
        addProperty("sessionId", grant.sessionId)
        addProperty("streamToken", grant.streamToken)
        addProperty("tokenExpiresAtEpochMs", grant.tokenExpiresAtEpochMs)
        addProperty("requiresUserConsent", grant.requiresUserConsent)
        addProperty("codec", grant.codec)
        addProperty("width", grant.width)
        addProperty("height", grant.height)
        addProperty("fps", grant.options.fps)
        addProperty("message", grant.message)
        addProperty("fallback", if (grant.state == "active") "none" else "snapshot")
    }

    private fun jsonError(status: NanoHTTPD.Response.IStatus, code: String, message: String): NanoHTTPD.Response =
        LumiSecurityController.jsonElementResponse(
            status,
            false,
            JsonObject().apply {
                addProperty("errorCode", code)
                addProperty("message", message)
                addProperty("fallback", "snapshot")
            },
            message
        )

    private fun JsonObject.string(key: String): String =
        get(key)?.takeIf { it.isJsonPrimitive }?.asString?.trim().orEmpty()

    private fun JsonObject.int(key: String, fallback: Int): Int =
        runCatching { get(key)?.asInt ?: fallback }.getOrDefault(fallback)
}
