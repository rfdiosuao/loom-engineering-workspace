package com.apk.claw.android.server

import com.apk.claw.android.BuildConfig
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.util.concurrent.atomic.AtomicLong

object PhoneEventStreamController {
    const val MIME_EVENT_STREAM = "text/event-stream; charset=utf-8"
    private const val SNAPSHOT_INTERVAL_MS = 1000L
    const val RETRY_MS = 3000L
    private const val MAX_CONNECTIONS = 2
    private const val MAX_STREAM_MS = 60 * 60 * 1000L
    private val sequence = AtomicLong(0L)
    private val connectionGate = PhoneEventStreamConnectionGate(MAX_CONNECTIONS)

    fun handleEvents(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val lease = connectionGate.tryAcquire()
            ?: return eventStreamBusyResponse()
        val input = PhoneEventStreamInputStream(
            lease = lease,
            helloProvider = { helloEvent() },
            snapshotProvider = { AgentApiController.eventStreamSnapshot() },
            eventIdProvider = { sequence.incrementAndGet() },
            snapshotIntervalMs = SNAPSHOT_INTERVAL_MS,
            maxStreamMs = MAX_STREAM_MS
        )
        val response = PhoneEventStreamResponse(input)
        response.addHeader("Cache-Control", "no-cache")
        response.addHeader("Connection", "keep-alive")
        response.addHeader("X-Accel-Buffering", "no")
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader(
            "Access-Control-Allow-Headers",
            "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN, X-LUMI-LAUNCHER-ID, X-LUMI-TIMESTAMP, X-LUMI-NONCE, X-LUMI-SIGNATURE, X-LUMI-BODY-SHA256"
        )
        return response
    }

    fun snapshotEvent(
        status: JsonObject,
        metrics: JsonObject,
        tasks: List<JsonObject>,
        nowMs: Long = System.currentTimeMillis()
    ): JsonObject {
        return JsonObject().apply {
            addProperty("schema", "apkclaw.event_stream.snapshot.v1")
            addProperty("timestampMs", nowMs)
            addProperty("version", BuildConfig.VERSION_NAME)
            add("status", status)
            add("metrics", metrics)
            add("tasks", JsonArray().apply { tasks.forEach { add(it) } })
        }
    }

    fun formatSse(
        event: String,
        data: JsonObject,
        id: Long? = null,
        retryMs: Long? = null
    ): String {
        val builder = StringBuilder()
        if (id != null) builder.append("id: ").append(id).append('\n')
        if (retryMs != null) builder.append("retry: ").append(retryMs).append('\n')
        builder.append("event: ").append(event).append('\n')
        data.toString().lineSequence().forEach { line ->
            builder.append("data: ").append(line).append('\n')
        }
        builder.append('\n')
        return builder.toString()
    }

    private fun eventStreamBusyResponse(): NanoHTTPD.Response {
        val data = JsonObject().apply {
            addProperty("success", false)
            addProperty("errorCode", "event_stream_busy")
            addProperty("error", "Too many active phone event streams")
            addProperty("maxConnections", MAX_CONNECTIONS)
        }
        val response = NanoHTTPD.newFixedLengthResponse(
            NanoHTTPD.Response.Status.SERVICE_UNAVAILABLE,
            "application/json; charset=utf-8",
            data.toString()
        )
        response.addHeader("Cache-Control", "no-cache")
        response.addHeader("Access-Control-Allow-Origin", "*")
        return response
    }

    private fun helloEvent(): JsonObject {
        return JsonObject().apply {
            addProperty("schema", "apkclaw.event_stream.hello.v1")
            addProperty("timestampMs", System.currentTimeMillis())
            addProperty("version", BuildConfig.VERSION_NAME)
            addProperty("snapshotIntervalMs", SNAPSHOT_INTERVAL_MS)
        }
    }
}
