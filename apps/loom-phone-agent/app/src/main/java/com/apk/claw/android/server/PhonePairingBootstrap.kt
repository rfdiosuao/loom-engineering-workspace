package com.apk.claw.android.server

import com.apk.claw.android.utils.KVUtils
import com.google.gson.JsonObject
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Phone-owned, short-lived bootstrap pairing.
 *
 * LAN pairing proves possession of a high-entropy bootstrap secret and encrypts
 * the long-lived credentials. The six-digit code is accepted only over USB
 * loopback and is never sent over ordinary LAN HTTP.
 */
object PhonePairingBootstrap {
    const val DEFAULT_TTL_MS = 5 * 60_000L
    internal const val PENDING_CREDENTIAL_VALID_UNTIL = Long.MAX_VALUE
    private const val MAX_ATTEMPTS_PER_REMOTE = 5
    private const val MAX_TOTAL_ATTEMPTS = 12
    private const val MAX_ATTEMPTS_PER_SOURCE_WINDOW = 8
    private const val SOURCE_ATTEMPT_WINDOW_MS = 10 * 60_000L
    private const val MAX_SOURCE_WINDOWS = 64
    private const val MAX_SESSIONS = 8
    private const val PROTOCOL_VERSION = "3"
    private const val CLAIM_DOMAIN = "LOOM-PAIR-CLAIM-V3"
    private const val RESPONSE_DOMAIN = "LOOM-PAIR-RESPONSE-V3"
    private const val KEY_INFO_DOMAIN = "LOOM-PHONE-PAIRING-V3"
    private const val ENCRYPTION_ALGORITHM = "AES-256-GCM-HKDF-SHA256"

    data class SessionView(
        val sessionId: String,
        val code: String,
        val payload: String,
        val expiresAt: Long,
        val transportHint: String
    )

    data class ClaimRequest(
        val sessionId: String,
        val code: String,
        val nonce: String,
        val proof: String,
        val transport: String,
        val deviceInstanceId: String,
        val launcherId: String,
        val launcherName: String
    )

    data class Credentials(
        val phoneToken: String,
        val launcherId: String,
        val launcherName: String,
        val launcherSecret: String,
        val pairedAt: Long
    )

    data class EncryptedCredentials(
        val algorithm: String,
        val iv: String,
        val ciphertext: String
    )

    data class ClaimResult(
        val success: Boolean,
        val errorCode: String = "",
        val message: String = "",
        val retryable: Boolean = false,
        val credentials: Credentials? = null,
        val encryptedCredentials: EncryptedCredentials? = null,
        val sessionId: String = "",
        val nonce: String = "",
        val launcherId: String = "",
        val pairedAt: Long = 0L
    )

    private data class PairingSession(
        val sessionId: String,
        val code: String,
        val bootstrapSecret: ByteArray,
        val deviceInstanceId: String,
        val expiresAt: Long,
        val transportHint: String,
        var failedAttempts: Int = 0,
        val failedAttemptsByRemote: MutableMap<String, Int> = mutableMapOf(),
        val usedNonces: MutableSet<String> = mutableSetOf(),
        var claimed: Boolean = false
    )

    private data class SourceAttemptWindow(
        var startedAt: Long,
        var failedAttempts: Int = 0
    )

    private val random = SecureRandom()
    private val sessions = LinkedHashMap<String, PairingSession>()
    private val sourceAttemptWindows = LinkedHashMap<String, SourceAttemptWindow>()
    private var clock: () -> Long = { System.currentTimeMillis() }
    private var credentialPromoter: (Credentials, Long) -> Unit = ::promoteCredentials

    @Synchronized
    fun createSession(
        baseUrl: String,
        deviceInstanceId: String,
        deviceName: String,
        transportHint: String = if (baseUrl.contains("127.0.0.1")) "usb" else "lan",
        ttlMs: Long = DEFAULT_TTL_MS
    ): SessionView {
        prune(clock())
        while (sessions.size >= MAX_SESSIONS) {
            val firstKey = sessions.keys.firstOrNull() ?: break
            sessions.remove(firstKey)
        }
        val now = clock()
        val sessionId = randomHex(16)
        val code = String.format("%06d", random.nextInt(1_000_000))
        val bootstrapSecret = randomBytes(32)
        val normalizedTransport = if (transportHint.equals("usb", ignoreCase = true)) "usb" else "lan"
        val expiresAt = now + ttlMs.coerceAtLeast(1_000L)
        sessions[sessionId] = PairingSession(
            sessionId = sessionId,
            code = code,
            bootstrapSecret = bootstrapSecret,
            deviceInstanceId = deviceInstanceId,
            expiresAt = expiresAt,
            transportHint = normalizedTransport
        )
        val fields = mutableListOf(
            "v" to PROTOCOL_VERSION,
            "b" to baseUrl,
            "d" to deviceInstanceId,
            "s" to sessionId,
            "n" to deviceName,
            "x" to normalizedTransport
        )
        if (normalizedTransport == "usb") {
            fields += "c" to code
        } else {
            fields += "k" to bootstrapSecret.toHex()
        }
        val payload = fields.joinToString("&", prefix = "lumi://pair?") { (key, value) ->
            "$key=${URLEncoder.encode(value, "UTF-8")}"
        }
        return SessionView(sessionId, code, payload, expiresAt, normalizedTransport)
    }

    @Synchronized
    fun claim(request: ClaimRequest, remoteAddress: String): ClaimResult {
        val now = clock()
        prune(now)
        val transport = request.transport.trim().lowercase()
        val remoteKey = normalizeRemoteAddress(remoteAddress)
        if (isSourceRateLimited(remoteKey, now)) {
            return rateLimitedError()
        }
        if (transport !in setOf("usb", "lan")) {
            recordSourceFailure(remoteKey, now)
            return pairingError(
                "phone_pairing_transport_invalid",
                "配对通道无效，请重新发起配对。"
            )
        }
        val requestedSession = request.sessionId.trim()
        val session = when {
            requestedSession.isNotEmpty() -> sessions[requestedSession]
            transport == "usb" -> sessions.values
                .filter {
                    !it.claimed &&
                        it.expiresAt > now &&
                        it.transportHint == "usb" &&
                        it.code == request.code.trim()
                }
                .maxByOrNull { it.expiresAt }
            else -> null
        }
        if (session == null) {
            recordSourceFailure(remoteKey, now)
            return sourceInvalidOrLimited(
                remoteKey,
                now,
                "phone_pairing_code_invalid",
                "配对信息无效，请在手机上刷新后重试。"
            )
        }

        if (session.claimed) {
            return pairingError(
                "phone_pairing_code_replayed",
                "配对信息已使用，请在手机上生成新的配对信息。"
            )
        }
        if (session.expiresAt <= now) {
            return pairingError(
                "phone_pairing_code_expired",
                "配对信息已过期，请在手机上刷新。",
                retryable = true
            )
        }
        if (request.deviceInstanceId.isNotBlank() &&
            request.deviceInstanceId != session.deviceInstanceId
        ) {
            return pairingError(
                "phone_pairing_device_mismatch",
                "配对信息与当前手机不一致，请重新扫码。"
            )
        }

        if (transport != session.transportHint) {
            recordFailure(session, remoteKey, now)
            return invalidOrLimited(
                session,
                remoteKey,
                now,
                "phone_pairing_transport_invalid",
                "配对通道与手机生成的配对信息不一致，请重新发起配对。"
            )
        }
        if (isRateLimited(session, remoteKey)) {
            return rateLimitedError()
        }

        when (transport) {
            "usb" -> {
                if (!isLoopback(remoteKey)) {
                    recordFailure(session, remoteKey, now)
                    return invalidOrLimited(
                        session,
                        remoteKey,
                        now,
                        "phone_pairing_transport_invalid",
                        "6 位配对码仅允许通过 USB 本机通道使用。"
                    )
                }
                if (!constantTimeEquals(request.code.trim(), session.code)) {
                    recordFailure(session, remoteKey, now)
                    return invalidOrLimited(
                        session,
                        remoteKey,
                        now,
                        "phone_pairing_code_invalid",
                        "配对码不正确，请检查后重试。"
                    )
                }
            }
            "lan" -> {
                val nonce = request.nonce.trim()
                if (!nonce.matches(Regex("[A-Za-z0-9_-]{16,128}"))) {
                    recordFailure(session, remoteKey, now)
                    return invalidOrLimited(
                        session,
                        remoteKey,
                        now,
                        "phone_pairing_request_invalid",
                        "配对请求无效，请重新扫码。"
                    )
                }
                if (!session.usedNonces.add(nonce)) {
                    return pairingError(
                        "phone_pairing_nonce_replayed",
                        "配对请求已使用，请重新发起配对。"
                    )
                }
                val launcherId = sanitizeId(request.launcherId)
                val expectedProof = hmacHex(
                    session.bootstrapSecret,
                    claimInput(
                        session.sessionId,
                        nonce,
                        session.deviceInstanceId,
                        launcherId
                    )
                )
                if (!constantTimeEquals(request.proof.trim().lowercase(), expectedProof)) {
                    recordFailure(session, remoteKey, now)
                    return invalidOrLimited(
                        session,
                        remoteKey,
                        now,
                        "phone_pairing_proof_invalid",
                        "配对校验失败，请重新扫码。"
                    )
                }
            }
        }

        val launcherId = sanitizeId(request.launcherId).ifBlank { "loom-${randomHex(8)}" }
        val credentials = Credentials(
            phoneToken = randomHex(32),
            launcherId = launcherId,
            launcherName = request.launcherName.trim().take(80).ifBlank { "LOOM" },
            launcherSecret = randomHex(32),
            pairedAt = now
        )
        credentialPromoter(credentials, PENDING_CREDENTIAL_VALID_UNTIL)
        session.claimed = true
        if (transport == "usb") {
            return ClaimResult(
                success = true,
                credentials = credentials,
                sessionId = session.sessionId,
                launcherId = launcherId,
                pairedAt = now
            )
        }
        val encrypted = encryptCredentials(
            session = session,
            nonce = request.nonce.trim(),
            credentials = credentials
        )
        return ClaimResult(
            success = true,
            encryptedCredentials = encrypted,
            sessionId = session.sessionId,
            nonce = request.nonce.trim(),
            launcherId = launcherId,
            pairedAt = now
        )
    }

    @Synchronized
    internal fun configureForTests(
        clock: () -> Long,
        credentialPromoter: (Credentials, Long) -> Unit
    ) {
        this.clock = clock
        this.credentialPromoter = credentialPromoter
    }

    @Synchronized
    internal fun resetForTests() {
        sessions.clear()
        sourceAttemptWindows.clear()
        clock = { System.currentTimeMillis() }
        credentialPromoter = ::promoteCredentials
    }

    private fun encryptCredentials(
        session: PairingSession,
        nonce: String,
        credentials: Credentials
    ): EncryptedCredentials {
        val plaintext = JsonObject().apply {
            addProperty("phoneToken", credentials.phoneToken)
            addProperty("launcherId", credentials.launcherId)
            addProperty("launcherName", credentials.launcherName)
            addProperty("launcherSecret", credentials.launcherSecret)
            addProperty("pairedAt", credentials.pairedAt)
        }.toString().toByteArray(Charsets.UTF_8)
        val iv = randomBytes(12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.ENCRYPT_MODE,
            SecretKeySpec(deriveKey(session.bootstrapSecret, session.sessionId, nonce), "AES"),
            GCMParameterSpec(128, iv)
        )
        cipher.updateAAD(
            responseAad(
                session.sessionId,
                nonce,
                session.deviceInstanceId,
                credentials.launcherId
            )
        )
        return EncryptedCredentials(
            algorithm = ENCRYPTION_ALGORITHM,
            iv = iv.toHex(),
            ciphertext = cipher.doFinal(plaintext).toHex()
        )
    }

    private fun deriveKey(secret: ByteArray, sessionId: String, nonce: String): ByteArray {
        val extract = Mac.getInstance("HmacSHA256")
        extract.init(SecretKeySpec(sessionId.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val pseudoRandomKey = extract.doFinal(secret)
        val expand = Mac.getInstance("HmacSHA256")
        expand.init(SecretKeySpec(pseudoRandomKey, "HmacSHA256"))
        val info = "$KEY_INFO_DOMAIN\n$nonce".toByteArray(Charsets.UTF_8) + byteArrayOf(1)
        return expand.doFinal(info).copyOf(32)
    }

    private fun promoteCredentials(credentials: Credentials, previousValidUntil: Long) {
        KVUtils.promotePhonePairingCredentials(
            phoneToken = credentials.phoneToken,
            launcherId = credentials.launcherId,
            launcherName = credentials.launcherName,
            launcherSecret = credentials.launcherSecret,
            pairedAt = credentials.pairedAt,
            previousValidUntil = previousValidUntil
        )
    }

    private fun claimInput(
        sessionId: String,
        nonce: String,
        deviceInstanceId: String,
        launcherId: String
    ): String = listOf(
        CLAIM_DOMAIN,
        sessionId,
        nonce,
        deviceInstanceId,
        launcherId
    ).joinToString("\n")

    private fun responseAad(
        sessionId: String,
        nonce: String,
        deviceInstanceId: String,
        launcherId: String
    ): ByteArray = listOf(
        RESPONSE_DOMAIN,
        sessionId,
        nonce,
        deviceInstanceId,
        launcherId
    ).joinToString("\n").toByteArray(Charsets.UTF_8)

    private fun isRateLimited(session: PairingSession, remoteKey: String): Boolean {
        return session.failedAttempts >= MAX_TOTAL_ATTEMPTS ||
            (session.failedAttemptsByRemote[remoteKey] ?: 0) >= MAX_ATTEMPTS_PER_REMOTE
    }

    private fun recordFailure(session: PairingSession, remoteKey: String, now: Long) {
        session.failedAttempts += 1
        session.failedAttemptsByRemote[remoteKey] =
            (session.failedAttemptsByRemote[remoteKey] ?: 0) + 1
        recordSourceFailure(remoteKey, now)
    }

    private fun invalidOrLimited(
        session: PairingSession,
        remoteKey: String,
        now: Long,
        code: String,
        message: String
    ): ClaimResult {
        return if (isRateLimited(session, remoteKey) || isSourceRateLimited(remoteKey, now)) {
            rateLimitedError()
        } else {
            pairingError(code, message, retryable = true)
        }
    }

    private fun sourceInvalidOrLimited(
        remoteKey: String,
        now: Long,
        code: String,
        message: String
    ): ClaimResult {
        return if (isSourceRateLimited(remoteKey, now)) {
            rateLimitedError()
        } else {
            pairingError(code, message, retryable = true)
        }
    }

    private fun rateLimitedError() = pairingError(
        "phone_pairing_rate_limited",
        "配对尝试次数过多，请稍后刷新配对信息后重试。",
        retryable = true
    )

    private fun isSourceRateLimited(remoteKey: String, now: Long): Boolean {
        val window = sourceAttemptWindows[remoteKey] ?: return false
        if (now - window.startedAt >= SOURCE_ATTEMPT_WINDOW_MS) {
            sourceAttemptWindows.remove(remoteKey)
            return false
        }
        return window.failedAttempts >= MAX_ATTEMPTS_PER_SOURCE_WINDOW
    }

    private fun recordSourceFailure(remoteKey: String, now: Long) {
        val current = sourceAttemptWindows[remoteKey]
        val window = if (
            current == null ||
            now - current.startedAt >= SOURCE_ATTEMPT_WINDOW_MS
        ) {
            SourceAttemptWindow(startedAt = now).also {
                sourceAttemptWindows[remoteKey] = it
            }
        } else {
            current
        }
        window.failedAttempts += 1
        while (sourceAttemptWindows.size > MAX_SOURCE_WINDOWS) {
            val firstKey = sourceAttemptWindows.keys.firstOrNull() ?: break
            sourceAttemptWindows.remove(firstKey)
        }
    }

    private fun pairingError(
        code: String,
        message: String,
        retryable: Boolean = false
    ) = ClaimResult(
        success = false,
        errorCode = code,
        message = message,
        retryable = retryable
    )

    private fun prune(now: Long) {
        val iterator = sessions.entries.iterator()
        while (iterator.hasNext()) {
            val session = iterator.next().value
            if (session.expiresAt + DEFAULT_TTL_MS < now) iterator.remove()
        }
        val sourceIterator = sourceAttemptWindows.entries.iterator()
        while (sourceIterator.hasNext()) {
            if (now - sourceIterator.next().value.startedAt >= SOURCE_ATTEMPT_WINDOW_MS) {
                sourceIterator.remove()
            }
        }
    }

    private fun randomBytes(byteCount: Int): ByteArray {
        return ByteArray(byteCount).also(random::nextBytes)
    }

    private fun randomHex(byteCount: Int): String = randomBytes(byteCount).toHex()

    private fun sanitizeId(value: String): String {
        return value.trim()
            .replace(Regex("[^A-Za-z0-9_.:-]"), "-")
            .replace(Regex("-+"), "-")
            .trim('-', '.', ':', '_')
            .take(80)
    }

    private fun normalizeRemoteAddress(value: String): String {
        return value.trim().removePrefix("/").lowercase().ifBlank { "unknown" }
    }

    private fun isLoopback(remoteAddress: String): Boolean {
        return remoteAddress == "localhost" ||
            remoteAddress == "::1" ||
            remoteAddress == "0:0:0:0:0:0:0:1" ||
            remoteAddress.startsWith("127.")
    }

    private fun hmacHex(key: ByteArray, text: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(text.toByteArray(Charsets.UTF_8)).toHex()
    }

    private fun constantTimeEquals(left: String, right: String): Boolean {
        return MessageDigest.isEqual(
            left.toByteArray(Charsets.UTF_8),
            right.toByteArray(Charsets.UTF_8)
        )
    }

    private fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it.toInt() and 0xff) }
}
