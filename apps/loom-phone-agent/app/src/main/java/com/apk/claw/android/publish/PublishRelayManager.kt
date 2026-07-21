package com.apk.claw.android.publish

import com.apk.claw.android.server.PublishApiController
import com.apk.claw.android.server.TokenValidator
import com.apk.claw.android.server.VisionApiController
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

object PublishRelayManager {

    private const val TAG = "PublishRelayManager"
    private const val PUBLISH_PACKET_SCHEMA = "openclaw.publish.packet.v1"
    private const val SCREENSHOT_PACKET_SCHEMA = "openclaw.phone.screenshot.v1"
    private const val DEFAULT_SCREENSHOT_FORMAT = "jpeg"
    private const val DEFAULT_SCREENSHOT_QUALITY = 82
    private const val DEFAULT_SCREENSHOT_MAX_LONG_SIDE = 1600
    private const val DEFAULT_SCREENSHOT_GRID_COLUMNS = 6
    private const val DEFAULT_SCREENSHOT_GRID_ROWS = 12
    private const val DEFAULT_WAIT_MS = 15_000L
    private const val DEFAULT_LEASE_MS = 30_000L
    private const val RETRY_DELAY_MS = 5_000L
    private val gson = Gson()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .callTimeout(60, TimeUnit.SECONDS)
        .build()

    @Volatile
    private var pollingJob: Job? = null

    data class Config(
        val baseUrl: String,
        val channelId: String,
        val token: String,
        val enabled: Boolean,
    )

    data class RelayPollPacket(
        val packetId: String,
        val leaseId: String,
        val channelId: String,
        val leaseUntil: Long,
        val attempts: Int,
        val packet: JsonObject,
    )

    data class RelayExecutionResult(
        val success: Boolean,
        val statusCode: Int,
        val responseText: String,
        val responseJson: JsonObject?,
        val errorMessage: String,
    )

    data class RelayCheckResult(
        val ok: Boolean,
        val message: String,
        val healthStatusCode: Int? = null,
        val channelStatusCode: Int? = null,
    )

    fun syncFromStorage() {
        if (!KVUtils.isPublishRelayEnabled()) {
            stop()
            return
        }
        startIfNeeded()
    }

    fun reconnectIfNeeded() {
        if (pollingJob?.isActive == true) return
        if (KVUtils.isPublishRelayEnabled()) {
            startIfNeeded()
        }
    }

    fun stop() {
        pollingJob?.cancel()
        pollingJob = null
    }

    fun checkRelayConfig(baseUrl: String, channelId: String, relayToken: String): RelayCheckResult {
        val normalizedBaseUrl = normalizeBaseUrl(baseUrl)
        val normalizedChannelId = channelId.trim()
        val normalizedToken = relayToken.trim()
        if (normalizedBaseUrl.isBlank()) {
            return RelayCheckResult(false, "Relay base URL is empty")
        }
        if (normalizedChannelId.isBlank()) {
            return RelayCheckResult(false, "Channel ID is empty")
        }

        return try {
            val healthResponse = getJson("$normalizedBaseUrl/health", normalizedToken)
            if (healthResponse.statusCode !in 200..299) {
                return RelayCheckResult(
                    false,
                    "Relay health check failed: HTTP ${healthResponse.statusCode}",
                    healthStatusCode = healthResponse.statusCode,
                )
            }

            val statusUrl = "$normalizedBaseUrl/api/lumi/relay/status?channelId=${URLEncoder.encode(normalizedChannelId, Charsets.UTF_8.name())}"
            val channelResponse = getJson(statusUrl, normalizedToken)
            if (channelResponse.statusCode !in 200..299) {
                return RelayCheckResult(
                    false,
                    "Relay channel check failed: HTTP ${channelResponse.statusCode}",
                    healthStatusCode = healthResponse.statusCode,
                    channelStatusCode = channelResponse.statusCode,
                )
            }

            RelayCheckResult(
                true,
                "Relay reachable",
                healthStatusCode = healthResponse.statusCode,
                channelStatusCode = channelResponse.statusCode,
            )
        } catch (error: Exception) {
            RelayCheckResult(false, error.message ?: "Relay check failed")
        }
    }

    private fun startIfNeeded() {
        if (pollingJob?.isActive == true) return
        pollingJob = scope.launch {
            XLog.i(TAG, "Publish relay worker started")
            while (isActive) {
                val config = readConfig()
                if (!config.enabled) {
                    delay(RETRY_DELAY_MS)
                    continue
                }
                if (config.baseUrl.isBlank() || config.channelId.isBlank()) {
                    XLog.w(TAG, "Publish relay config incomplete")
                    delay(RETRY_DELAY_MS)
                    continue
                }
                if (!TokenValidator.isTokenConfigured()) {
                    XLog.w(TAG, "Publish relay waiting for API token")
                    delay(RETRY_DELAY_MS)
                    continue
                }
                if (!ClawAccessibilityService.isRunning()) {
                    XLog.w(TAG, "Publish relay waiting for accessibility service")
                    delay(RETRY_DELAY_MS)
                    continue
                }

                try {
                    val packet = pollRelayPacket(config)
                    if (packet == null) {
                        continue
                    }

                    val execution = executePacketLocally(packet)
                    completeRelayPacket(config, packet, execution)
                } catch (e: Exception) {
                    XLog.e(TAG, "Publish relay loop failed", e)
                    delay(RETRY_DELAY_MS)
                }
            }
            XLog.i(TAG, "Publish relay worker stopped")
        }
    }

    private fun readConfig(): Config {
        return Config(
            baseUrl = KVUtils.getPublishRelayBaseUrl().trim(),
            channelId = KVUtils.getPublishRelayChannelId().trim(),
            token = KVUtils.getPublishRelayToken().trim(),
            enabled = KVUtils.isPublishRelayEnabled(),
        )
    }

    private fun normalizeBaseUrl(value: String): String {
        return value.trim().trimEnd('/')
    }

    private fun pollRelayPacket(config: Config): RelayPollPacket? {
        val clientId = KVUtils.ensurePublishRelayClientId()
        val pollUrl = buildString {
            append(normalizeBaseUrl(config.baseUrl))
            append("/api/lumi/relay/poll?channelId=")
            append(URLEncoder.encode(config.channelId, Charsets.UTF_8.name()))
            append("&clientId=")
            append(URLEncoder.encode(clientId, Charsets.UTF_8.name()))
            append("&waitMs=")
            append(DEFAULT_WAIT_MS)
            append("&leaseMs=")
            append(DEFAULT_LEASE_MS)
        }

        val response = getJson(pollUrl, config.token)
        if (response.statusCode !in 200..299) {
            throw IllegalStateException("Relay poll failed: HTTP ${response.statusCode}")
        }

        val data = response.bodyJson?.getAsJsonObject("data")
        if (data == null || !data.has("packet") || data.get("packet").isJsonNull) {
            return null
        }

        val packetObj = data.getAsJsonObject("packet")
        return RelayPollPacket(
            packetId = data.get("packetId")?.asString.orEmpty(),
            leaseId = data.get("leaseId")?.asString.orEmpty(),
            channelId = data.get("channelId")?.asString.orEmpty(),
            leaseUntil = data.get("leaseUntil")?.asLong ?: 0L,
            attempts = data.get("attempts")?.asInt ?: 0,
            packet = packetObj,
        )
    }

    private fun executePacketLocally(packet: RelayPollPacket): RelayExecutionResult {
        val schema = packetSchema(packet.packet)
        return when (schema) {
            PUBLISH_PACKET_SCHEMA -> executePublishPacketLocally(packet)
            SCREENSHOT_PACKET_SCHEMA -> executeScreenshotPacketLocally(packet)
            else -> RelayExecutionResult(
                success = false,
                statusCode = 400,
                responseText = "",
                responseJson = null,
                errorMessage = "Unsupported relay packet schema: $schema",
            )
        }
    }

    private fun executePublishPacketLocally(packet: RelayPollPacket): RelayExecutionResult {
        if (!KVUtils.hasLlmConfig()) {
            return RelayExecutionResult(
                success = false,
                statusCode = 503,
                responseText = "",
                responseJson = null,
                errorMessage = "Publish relay waiting for LLM config",
            )
        }

        val bodyBytes = gson.toJson(packet.packet).toByteArray(Charsets.UTF_8)
        val session = object : NanoHTTPD.IHTTPSession {
            private val headers = mutableMapOf(
                "content-type" to "application/json; charset=utf-8",
                "content-length" to bodyBytes.size.toString(),
                "x-agent-phone-token" to KVUtils.getApiToken(),
            )

            override fun execute() = Unit
            override fun getCookies(): NanoHTTPD.CookieHandler {
                throw UnsupportedOperationException("Cookies are not used")
            }

            override fun getHeaders(): MutableMap<String, String> = headers
            override fun getInputStream(): InputStream = ByteArrayInputStream(bodyBytes)
            override fun getMethod(): NanoHTTPD.Method = NanoHTTPD.Method.POST
            override fun getParms(): MutableMap<String, String> = mutableMapOf()
            override fun getParameters(): MutableMap<String, MutableList<String>> = mutableMapOf()
            override fun getQueryParameterString(): String = ""
            override fun getUri(): String = "/api/lumi/publish/packet"
            override fun parseBody(files: MutableMap<String, String>) {
                files["postData"] = String(bodyBytes, Charsets.UTF_8)
            }
            override fun getRemoteIpAddress(): String = "127.0.0.1"
            override fun getRemoteHostName(): String = "localhost"
        }

        val response = PublishApiController.handleExecutePacket(session)
        return parseRelayExecutionResponse(response)
    }

    private fun executeScreenshotPacketLocally(packet: RelayPollPacket): RelayExecutionResult {
        val query = buildRelayScreenshotQuery(packet.packet)
        val session = object : NanoHTTPD.IHTTPSession {
            private val parameters = query.mapValues { (_, value) -> mutableListOf(value) }.toMutableMap()

            override fun execute() = Unit
            override fun getCookies(): NanoHTTPD.CookieHandler {
                throw UnsupportedOperationException("Cookies are not used")
            }

            override fun getHeaders(): MutableMap<String, String> = mutableMapOf(
                "x-agent-phone-token" to KVUtils.getApiToken(),
            )

            override fun getInputStream(): InputStream = ByteArrayInputStream(ByteArray(0))
            override fun getMethod(): NanoHTTPD.Method = NanoHTTPD.Method.GET
            override fun getParms(): MutableMap<String, String> = mutableMapOf()
            override fun getParameters(): MutableMap<String, MutableList<String>> = parameters
            override fun getQueryParameterString(): String = query.entries.joinToString("&") { (key, value) ->
                "${urlEncode(key)}=${urlEncode(value)}"
            }
            override fun getUri(): String = "/api/lumi/vision/frame"
            override fun parseBody(files: MutableMap<String, String>) = Unit
            override fun getRemoteIpAddress(): String = "127.0.0.1"
            override fun getRemoteHostName(): String = "localhost"
        }

        val response = VisionApiController.handleFrame(session)
        return parseScreenshotRelayResponse(response)
    }

    private fun parseRelayExecutionResponse(response: NanoHTTPD.Response): RelayExecutionResult {
        val statusCode = response.status.requestStatus
        val responseText = response.use { item ->
            item.getData()?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        }
        val responseJson = runCatching {
            gson.fromJson(responseText, JsonObject::class.java)
        }.getOrNull()
        val success = when {
            responseJson?.has("success") == true && responseJson.get("success").isJsonPrimitive ->
                responseJson.get("success").asBoolean
            statusCode in 200..299 -> true
            else -> false
        }
        val errorMessage = responseJson?.get("error")?.takeIf { it.isJsonPrimitive }?.asString.orEmpty()
        return RelayExecutionResult(
            success = success,
            statusCode = statusCode,
            responseText = responseText,
            responseJson = responseJson,
            errorMessage = errorMessage,
        )
    }

    private fun parseScreenshotRelayResponse(response: NanoHTTPD.Response): RelayExecutionResult {
        val base = parseRelayExecutionResponse(response)
        if (!base.success || base.responseJson == null) return base
        val data = base.responseJson.getAsJsonObject("data") ?: return RelayExecutionResult(
            success = false,
            statusCode = base.statusCode,
            responseText = "",
            responseJson = base.responseJson,
            errorMessage = "Missing vision data payload",
        )
        val image = data.getAsJsonObject("image") ?: return RelayExecutionResult(
            success = false,
            statusCode = base.statusCode,
            responseText = "",
            responseJson = base.responseJson,
            errorMessage = "Missing screenshot image payload",
        )
        val screenshot = JsonObject().apply {
            image.get("mime")?.takeIf { it.isJsonPrimitive }?.let { addProperty("mime", it.asString) }
            image.get("base64")?.takeIf { it.isJsonPrimitive }?.let { addProperty("base64", it.asString) }
            data.get("capturedAt")?.takeIf { it.isJsonPrimitive }?.let { addProperty("capturedAt", it.asString) }
            image.get("width")?.takeIf { it.isJsonPrimitive }?.let { addProperty("width", it.asInt) }
            image.get("height")?.takeIf { it.isJsonPrimitive }?.let { addProperty("height", it.asInt) }
            image.get("orientation")?.takeIf { it.isJsonPrimitive }?.let { addProperty("orientation", it.asString) }
        }
        return RelayExecutionResult(
            success = true,
            statusCode = base.statusCode,
            responseText = "",
            responseJson = screenshot,
            errorMessage = "",
        )
    }

    private fun buildRelayScreenshotQuery(packet: JsonObject): Map<String, String> {
        val options = packet.getAsJsonObject("options") ?: packet
        return mapOf(
            "_lumi" to "1",
            "includeScreenshot" to packetBoolean(options, "includeScreenshot", true).toString(),
            "overlayGrid" to packetBoolean(options, "overlayGrid", false).toString(),
            "format" to packetString(options, "format", DEFAULT_SCREENSHOT_FORMAT),
            "quality" to packetInt(options, "quality", DEFAULT_SCREENSHOT_QUALITY).coerceIn(45, 95).toString(),
            "maxLongSide" to packetInt(options, "maxLongSide", DEFAULT_SCREENSHOT_MAX_LONG_SIDE).coerceIn(480, 4096).toString(),
            "gridColumns" to packetInt(options, "gridColumns", DEFAULT_SCREENSHOT_GRID_COLUMNS).coerceIn(2, 12).toString(),
            "gridRows" to packetInt(options, "gridRows", DEFAULT_SCREENSHOT_GRID_ROWS).coerceIn(2, 24).toString(),
        )
    }

    private fun packetSchema(packet: JsonObject): String {
        return packetString(packet, "schema", "")
    }

    private fun packetString(packet: JsonObject, key: String, fallback: String): String {
        val element = packet.get(key)
        return if (element != null && element.isJsonPrimitive) element.asString else fallback
    }

    private fun packetInt(packet: JsonObject, key: String, fallback: Int): Int {
        val element = packet.get(key)
        return if (element != null && element.isJsonPrimitive) {
            element.asInt
        } else {
            fallback
        }
    }

    private fun packetBoolean(packet: JsonObject, key: String, fallback: Boolean): Boolean {
        val element = packet.get(key)
        return if (element != null && element.isJsonPrimitive) {
            val value = element.asString.trim()
            value == "1" || value.equals("true", ignoreCase = true) || value.equals("yes", ignoreCase = true)
        } else {
            fallback
        }
    }

    private fun urlEncode(value: String): String {
        return URLEncoder.encode(value, Charsets.UTF_8.name())
    }

    private fun completeRelayPacket(
        config: Config,
        packet: RelayPollPacket,
        execution: RelayExecutionResult,
    ) {
        val payload = JsonObject().apply {
            addProperty("packetId", packet.packetId)
            addProperty("leaseId", packet.leaseId)
            addProperty("clientId", KVUtils.getPublishRelayClientId())
            addProperty("channelId", packet.channelId.ifBlank { config.channelId })
            addProperty("success", execution.success)
            addProperty("statusCode", execution.statusCode)
            addProperty("error", execution.errorMessage)
            addProperty("responseText", execution.responseText)
            execution.responseJson?.let { add("result", it) }
        }

        val completeUrl = "${normalizeBaseUrl(config.baseUrl)}/api/lumi/relay/complete"
        val response = postJson(completeUrl, payload, config.token)
        if (response.statusCode !in 200..299) {
            throw IllegalStateException("Relay complete failed: HTTP ${response.statusCode}")
        }
        XLog.i(
            TAG,
            "Publish relay packet ${packet.packetId} completed: success=${execution.success}, status=${execution.statusCode}"
        )
    }

    private fun getJson(url: String, relayToken: String): HttpResponse {
        val requestBuilder = Request.Builder()
            .url(url)
            .get()
            .header("Accept", "application/json")
        addRelayAuthHeaders(requestBuilder, relayToken)
        val request = requestBuilder.build()
        return httpRequest(request)
    }

    private fun postJson(url: String, payload: JsonObject, relayToken: String): HttpResponse {
        val requestBody = gson.toJson(payload).toRequestBody("application/json; charset=utf-8".toMediaType())
        val requestBuilder = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("Accept", "application/json")
        addRelayAuthHeaders(requestBuilder, relayToken)
        val request = requestBuilder.build()
        return httpRequest(request)
    }

    private fun addRelayAuthHeaders(requestBuilder: Request.Builder, relayToken: String) {
        val token = relayToken.trim()
        if (token.isBlank()) return
        requestBuilder.header("Authorization", "Bearer $token")
        requestBuilder.header("X-OpenClaw-Relay-Token", token)
    }

    private fun httpRequest(request: Request): HttpResponse {
        httpClient.newCall(request).execute().use { response ->
            val bodyText = response.body?.string().orEmpty()
            val bodyJson = runCatching {
                if (bodyText.isBlank()) null else gson.fromJson(bodyText, JsonObject::class.java)
            }.getOrNull()
            return HttpResponse(response.code, bodyText, bodyJson)
        }
    }

    private data class HttpResponse(
        val statusCode: Int,
        val bodyText: String,
        val bodyJson: JsonObject?,
    )
}
