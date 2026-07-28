package com.apk.claw.android.server

import android.util.Base64
import com.apk.claw.android.BuildConfig
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Locale
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object LumiSecurityController {
    private const val TAG = "LumiSecurity"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private const val HEADER_LAUNCHER_ID = "x-lumi-launcher-id"
    private const val HEADER_TIMESTAMP = "x-lumi-timestamp"
    private const val HEADER_NONCE = "x-lumi-nonce"
    private const val HEADER_SIGNATURE = "x-lumi-signature"
    private const val HEADER_BODY_SHA256 = "x-lumi-body-sha256"
    private const val MAX_CLOCK_SKEW_MS = 120_000L
    private const val NONCE_TTL_MS = 5 * 60_000L
    private const val MAX_SIGNED_BODY_BYTES = 64L * 1024L * 1024L

    private val random = SecureRandom()
    private val nonceCache = LinkedHashMap<String, Long>()

    fun handleIdentityChallenge(
        session: NanoHTTPD.IHTTPSession,
        listeningPort: Int
    ): NanoHTTPD.Response {
        if (!UsbIdentityChallenge.isLoopbackPeer(session.remoteIpAddress)) {
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "USB identity challenge is only available on device loopback"
            )
        }
        val rawContentLength = session.headers["content-length"]
            ?: session.headers["Content-Length"]
        val contentLength = rawContentLength?.toLongOrNull()
        if (
            (rawContentLength != null && contentLength == null) ||
            !UsbIdentityChallenge.isAllowedBodyLength(contentLength ?: 0L)
        ) {
            return jsonElementResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "USB identity challenge body is too large"
            )
        }
        val json = ToolApiController.parseJsonBody(session)
            ?: return jsonElementResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Invalid JSON body"
            )
        val protocol = json.stringOrEmpty("protocol")
        val nonce = json.stringOrEmpty("nonce")
        if (protocol != UsbIdentityChallenge.PROTOCOL || !UsbIdentityChallenge.isValidNonce(nonce)) {
            return jsonElementResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                null,
                "Invalid USB identity challenge"
            )
        }
        val token = KVUtils.getApiToken()
        if (token.isBlank()) {
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Phone token is not configured"
            )
        }
        val deviceInstanceId = KVUtils.ensureLumiDeviceInstanceId()
        val data = JsonObject().apply {
            addProperty("protocol", UsbIdentityChallenge.PROTOCOL)
            addProperty("nonce", nonce)
            addProperty("packageName", BuildConfig.APPLICATION_ID)
            addProperty("version", BuildConfig.VERSION_NAME)
            addProperty("versionCode", BuildConfig.VERSION_CODE)
            addProperty("deviceInstanceId", deviceInstanceId)
            addProperty("listeningPort", listeningPort)
            addProperty(
                "proof",
                UsbIdentityChallenge.proof(
                    token = token,
                    nonce = nonce,
                    packageName = BuildConfig.APPLICATION_ID,
                    versionCode = BuildConfig.VERSION_CODE.toLong(),
                    deviceInstanceId = deviceInstanceId,
                    listeningPort = listeningPort
                )
            )
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleBootstrapClaim(
        session: NanoHTTPD.IHTTPSession,
        listeningPort: Int
    ): NanoHTTPD.Response {
        val rawContentLength = session.headers["content-length"]
            ?: session.headers["Content-Length"]
        val contentLength = rawContentLength?.toLongOrNull()
        if (
            (rawContentLength != null && contentLength == null) ||
            (contentLength != null && contentLength > 8 * 1024L)
        ) {
            return pairingErrorResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                "phone_pairing_request_invalid",
                "配对请求无效，请刷新配对码后重试。",
                false
            )
        }
        val json = ToolApiController.parseJsonBody(session)
            ?: return pairingErrorResponse(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                "phone_pairing_request_invalid",
                "配对请求无效，请刷新配对码后重试。",
                false
            )
        val result = PhonePairingBootstrap.claim(
            PhonePairingBootstrap.ClaimRequest(
                sessionId = json.stringOrEmpty("sessionId")
                    .ifBlank { json.stringOrEmpty("session_id") },
                code = json.stringOrEmpty("code"),
                nonce = json.stringOrEmpty("nonce"),
                proof = json.stringOrEmpty("proof"),
                transport = json.stringOrEmpty("transport"),
                deviceInstanceId = json.stringOrEmpty("deviceInstanceId")
                    .ifBlank { json.stringOrEmpty("device_instance_id") },
                launcherId = json.stringOrEmpty("launcherId")
                    .ifBlank { json.stringOrEmpty("launcher_id") },
                launcherName = json.stringOrEmpty("launcherName")
                    .ifBlank { json.stringOrEmpty("launcher_name") }
            ),
            remoteAddress = session.remoteIpAddress.orEmpty()
        )
        if (!result.success) {
            val status = when (result.errorCode) {
                "phone_pairing_code_replayed",
                "phone_pairing_nonce_replayed",
                "phone_pairing_proof_invalid",
                "phone_pairing_transport_invalid",
                "phone_pairing_device_mismatch" -> NanoHTTPD.Response.Status.FORBIDDEN
                "phone_pairing_rate_limited" -> NanoHTTPD.Response.Status.FORBIDDEN
                else -> NanoHTTPD.Response.Status.BAD_REQUEST
            }
            return pairingErrorResponse(
                status,
                result.errorCode,
                result.message,
                result.retryable
            )
        }

        val data = JsonObject().apply {
            addProperty("paired", true)
            addProperty("sessionId", result.sessionId)
            addProperty("nonce", result.nonce)
            addProperty("launcherId", result.launcherId)
            addProperty("pairedAt", result.pairedAt)
            addProperty("algorithm", "HMAC-SHA256")
            addProperty("signatureVersion", 1)
            addProperty("timestampSkewMs", MAX_CLOCK_SKEW_MS)
            addProperty("deviceInstanceId", KVUtils.ensureLumiDeviceInstanceId())
            addProperty("packageName", BuildConfig.APPLICATION_ID)
            addProperty("version", BuildConfig.VERSION_NAME)
            addProperty("versionCode", BuildConfig.VERSION_CODE)
            addProperty("listeningPort", listeningPort)
            result.encryptedCredentials?.let { encrypted ->
                add("encryptedCredentials", JsonObject().apply {
                    addProperty("algorithm", encrypted.algorithm)
                    addProperty("iv", encrypted.iv)
                    addProperty("ciphertext", encrypted.ciphertext)
                })
            }
            result.credentials?.let { credentials ->
                addProperty("phoneToken", credentials.phoneToken)
                addProperty("launcherName", credentials.launcherName)
                addProperty("launcherSecret", credentials.launcherSecret)
            }
        }
        XLog.i(TAG, "LOOM bootstrap pairing completed for launcher ${result.launcherId}")
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleBootstrapConfirm(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val launcherId = session.headers[HEADER_LAUNCHER_ID]?.trim().orEmpty()
        if (!KVUtils.confirmPhonePairingCredentials(launcherId)) {
            return pairingErrorResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                "phone_pairing_credential_invalid",
                "配对确认失败，旧连接仍然保留。",
                true
            )
        }
        return jsonElementResponse(
            NanoHTTPD.Response.Status.OK,
            true,
            JsonObject().apply {
                addProperty("confirmed", true)
                addProperty("launcherId", launcherId)
            },
            null
        )
    }

    fun handlePair(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session) ?: JsonObject()
        val requestedLauncherId = json.stringOrEmpty("launcherId")
            .ifBlank { json.stringOrEmpty("launcher_id") }
            .ifBlank { "openclaw-${randomToken(8)}" }
        val launcherId = sanitizeId(requestedLauncherId)
        val launcherName = json.stringOrEmpty("launcherName")
            .ifBlank { json.stringOrEmpty("launcher_name") }
            .ifBlank { "OpenClaw Launcher" }
            .take(80)

        val currentId = KVUtils.getLumiLauncherId()
        val currentSecret = KVUtils.getLumiLauncherSecret()
        val secret = if (currentId == launcherId && currentSecret.isNotBlank()) {
            currentSecret
        } else {
            randomToken(32)
        }
        val pairedAt = if (currentId == launcherId && KVUtils.getLumiLauncherPairedAt() > 0L) {
            KVUtils.getLumiLauncherPairedAt()
        } else {
            System.currentTimeMillis()
        }

        KVUtils.setLumiLauncherId(launcherId)
        KVUtils.setLumiLauncherName(launcherName)
        KVUtils.setLumiLauncherSecret(secret)
        KVUtils.setLumiLauncherPairedAt(pairedAt)

        XLog.i(TAG, "Launcher paired: id=$launcherId, name=$launcherName")
        val data = JsonObject().apply {
            addProperty("paired", true)
            addProperty("launcherId", launcherId)
            addProperty("launcherName", launcherName)
            addProperty("launcherSecret", secret)
            addProperty("pairedAt", pairedAt)
            addProperty("algorithm", "HMAC-SHA256")
            addProperty("signatureVersion", 1)
            addProperty("timestampSkewMs", MAX_CLOCK_SKEW_MS)
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleStatus(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val launcherId = KVUtils.getLumiLauncherId()
        val data = JsonObject().apply {
            addProperty("paired", launcherId.isNotBlank() && KVUtils.getLumiLauncherSecret().isNotBlank())
            addProperty("launcherId", launcherId)
            addProperty("launcherName", KVUtils.getLumiLauncherName())
            addProperty("pairedAt", KVUtils.getLumiLauncherPairedAt())
            addProperty("algorithm", "HMAC-SHA256")
            addProperty("signatureVersion", 1)
            addProperty("launcherOnlyNamespace", "/api/lumi")
            addProperty("eventStreamSupported", true)
            addProperty("eventStreamPath", "/api/lumi/events")
        }
        return jsonElementResponse(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun authorize(session: NanoHTTPD.IHTTPSession, bodyBytes: ByteArray = ByteArray(0)): NanoHTTPD.Response? {
        KVUtils.clearExpiredPreviousPhoneCredentials()
        val storedLauncherId = KVUtils.getLumiLauncherId()
        val storedSecret = KVUtils.getLumiLauncherSecret()
        val previousLauncherId = KVUtils.getPreviousLumiLauncherId()
        val previousSecret = KVUtils.getPreviousLumiLauncherSecret()
        val previousValid = KVUtils.getPreviousPhoneCredentialValidUntil() > System.currentTimeMillis()
        if (storedLauncherId.isBlank() || storedSecret.isBlank()) {
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Lumi launcher is not paired"
            )
        }

        val headers = session.headers
        val launcherId = headers[HEADER_LAUNCHER_ID]?.trim().orEmpty()
        val timestampText = headers[HEADER_TIMESTAMP]?.trim().orEmpty()
        val nonce = headers[HEADER_NONCE]?.trim().orEmpty()
        val signature = headers[HEADER_SIGNATURE]?.trim().orEmpty()
        val declaredBodyHash = headers[HEADER_BODY_SHA256]?.trim().orEmpty().lowercase(Locale.US)
        if (launcherId.isBlank() || timestampText.isBlank() || nonce.isBlank() || signature.isBlank() || declaredBodyHash.isBlank()) {
            XLog.w(TAG, "Missing Lumi security headers from ${session.remoteIpAddress}")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Missing Lumi security headers"
            )
        }
        val secret = when {
            launcherId == storedLauncherId -> storedSecret
            previousValid && launcherId == previousLauncherId -> previousSecret
            else -> ""
        }
        if (secret.isBlank()) {
            XLog.w(TAG, "Unknown Lumi launcher id: $launcherId")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Unknown Lumi launcher"
            )
        }

        val timestamp = normalizeTimestamp(timestampText.toLongOrNull())
            ?: return jsonElementResponse(NanoHTTPD.Response.Status.FORBIDDEN, false, null, "Invalid Lumi timestamp")
        val now = System.currentTimeMillis()
        if (kotlin.math.abs(now - timestamp) > MAX_CLOCK_SKEW_MS) {
            XLog.w(TAG, "Rejected stale Lumi request: timestamp=$timestamp, now=$now")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Lumi request timestamp is outside the allowed window"
            )
        }
        if (!rememberNonce(launcherId, nonce, now)) {
            XLog.w(TAG, "Rejected replayed Lumi nonce: $nonce")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Lumi nonce has already been used"
            )
        }

        val bodyHash = sha256Hex(bodyBytes)
        if (declaredBodyHash != bodyHash) {
            XLog.w(TAG, "Rejected Lumi request with body hash mismatch")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Lumi body hash mismatch"
            )
        }

        val signatureInput = listOf(
            session.method.name,
            pathWithQuery(session),
            timestampText,
            nonce,
            bodyHash
        ).joinToString("\n")
        val expected = hmacBase64Url(secret, signatureInput)
        if (!constantTimeEquals(signature, expected)) {
            XLog.w(TAG, "Invalid Lumi signature from ${session.remoteIpAddress}")
            return jsonElementResponse(
                NanoHTTPD.Response.Status.FORBIDDEN,
                false,
                null,
                "Invalid Lumi signature"
            )
        }

        return null
    }

    fun readBodyForSignature(session: NanoHTTPD.IHTTPSession): ByteArray {
        val contentLength = session.headers["content-length"]?.toLongOrNull()
            ?: session.headers["Content-Length"]?.toLongOrNull()
            ?: 0L
        if (contentLength <= 0L) return ByteArray(0)
        if (contentLength > MAX_SIGNED_BODY_BYTES) {
            throw IllegalArgumentException("Signed Lumi request body is too large")
        }

        val bytes = ByteArray(contentLength.toInt())
        var total = 0
        while (total < bytes.size) {
            val read = session.inputStream.read(bytes, total, bytes.size - total)
            if (read <= 0) break
            total += read
        }
        return if (total == bytes.size) bytes else bytes.copyOf(total)
    }

    fun launcherOnlyResponse(): NanoHTTPD.Response {
        return jsonElementResponse(
            NanoHTTPD.Response.Status.FORBIDDEN,
            false,
            null,
            "This advanced endpoint requires the Lumi launcher secure channel. Use /api/lumi/* with signed headers."
        )
    }

    fun jsonElementResponse(
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
        response.addHeader(
            "Access-Control-Allow-Headers",
            "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN, X-LUMI-LAUNCHER-ID, X-LUMI-TIMESTAMP, X-LUMI-NONCE, X-LUMI-SIGNATURE, X-LUMI-BODY-SHA256"
        )
        return response
    }

    private fun pairingErrorResponse(
        status: NanoHTTPD.Response.IStatus,
        errorCode: String,
        message: String,
        retryable: Boolean
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", false)
            addProperty("errorCode", errorCode)
            addProperty("message", message)
            addProperty("retryable", retryable)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type")
        return response
    }

    private fun rememberNonce(launcherId: String, nonce: String, now: Long): Boolean {
        val key = "$launcherId:$nonce"
        synchronized(nonceCache) {
            val iterator = nonceCache.entries.iterator()
            while (iterator.hasNext()) {
                if (iterator.next().value <= now) iterator.remove()
            }
            if (nonceCache.containsKey(key)) return false
            nonceCache[key] = now + NONCE_TTL_MS
            return true
        }
    }

    private fun normalizeTimestamp(value: Long?): Long? {
        if (value == null || value <= 0L) return null
        return if (value < 10_000_000_000L) value * 1000L else value
    }

    private fun pathWithQuery(session: NanoHTTPD.IHTTPSession): String {
        val query = session.queryParameterString
            ?.takeUnless { it.equals("null", ignoreCase = true) }
            .orEmpty()
        return if (query.isBlank()) session.uri else "${session.uri}?$query"
    }

    private fun randomToken(byteCount: Int): String {
        val bytes = ByteArray(byteCount)
        random.nextBytes(bytes)
        return Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
    }

    private fun sanitizeId(value: String): String {
        return value.trim()
            .replace(Regex("[^A-Za-z0-9_.:-]"), "-")
            .replace(Regex("-+"), "-")
            .trim('-', '.', ':', '_')
            .take(80)
            .ifBlank { "openclaw-${randomToken(8)}" }
    }

    private fun hmacBase64Url(secret: String, text: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return Base64.encodeToString(
            mac.doFinal(text.toByteArray(Charsets.UTF_8)),
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
    }

    private fun sha256Hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun constantTimeEquals(a: String, b: String): Boolean {
        val left = a.toByteArray(Charsets.UTF_8)
        val right = b.toByteArray(Charsets.UTF_8)
        var diff = left.size xor right.size
        val max = maxOf(left.size, right.size)
        for (index in 0 until max) {
            val l = if (index < left.size) left[index].toInt() else 0
            val r = if (index < right.size) right[index].toInt() else 0
            diff = diff or (l xor r)
        }
        return diff == 0
    }

    private fun JsonObject.stringOrEmpty(name: String): String {
        val value = get(name) ?: return ""
        if (value.isJsonNull) return ""
        return try {
            value.asString.orEmpty()
        } catch (_: Exception) {
            ""
        }
    }
}
