package com.apk.claw.android.server

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import okio.ByteString.Companion.toByteString

object UsbIdentityChallenge {
    const val PROTOCOL = "loom-usb-bind-v3"
    const val MAX_BODY_BYTES = 4 * 1024L
    private val NONCE_PATTERN = Regex("^[A-Za-z0-9_-]{32,128}$")
    private val LOOPBACK_PEERS = setOf("127.0.0.1", "::1", "0:0:0:0:0:0:0:1")

    fun isValidNonce(value: String): Boolean = NONCE_PATTERN.matches(value)

    fun isAllowedBodyLength(contentLength: Long): Boolean {
        return contentLength in 0..MAX_BODY_BYTES
    }

    fun isLoopbackPeer(remoteIpAddress: String?): Boolean {
        return remoteIpAddress?.trim()?.lowercase() in LOOPBACK_PEERS
    }

    fun proof(
        token: String,
        nonce: String,
        packageName: String,
        versionCode: Long,
        deviceInstanceId: String,
        listeningPort: Int
    ): String {
        require(token.isNotBlank()) { "Phone token is not configured" }
        require(isValidNonce(nonce)) { "Invalid identity challenge nonce" }
        require(deviceInstanceId.isNotBlank()) { "Phone installation identity is not configured" }
        require(listeningPort in 1..65535) { "Invalid ConfigServer listening port" }
        val signatureInput = listOf(
            PROTOCOL,
            nonce,
            packageName,
            versionCode.toString(),
            deviceInstanceId,
            listeningPort.toString()
        ).joinToString("\n")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal(signatureInput.toByteArray(Charsets.UTF_8))
            .toByteString()
            .base64Url()
            .trimEnd('=')
    }
}
