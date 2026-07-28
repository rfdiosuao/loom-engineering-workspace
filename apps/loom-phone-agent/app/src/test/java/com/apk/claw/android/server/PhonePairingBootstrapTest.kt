package com.apk.claw.android.server

import java.net.URI
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PhonePairingBootstrapTest {
    private var now = 1_000_000L
    private val promoted = mutableListOf<PhonePairingBootstrap.Credentials>()
    private val previousCredentialDeadlines = mutableListOf<Long>()

    @Before
    fun reset() {
        now = 1_000_000L
        promoted.clear()
        previousCredentialDeadlines.clear()
        PhonePairingBootstrap.resetForTests()
        PhonePairingBootstrap.configureForTests(
            clock = { now },
            credentialPromoter = { credentials, previousValidUntil ->
                promoted += credentials
                previousCredentialDeadlines += previousValidUntil
            }
        )
    }

    @Test
    fun creates_lan_payload_with_short_lived_bootstrap_secret_only() {
        val session = createLanSession()
        val query = parseQuery(session.payload)

        assertTrue(session.code.matches(Regex("\\d{6}")))
        assertEquals("3", query["v"])
        assertEquals("lan", query["x"])
        assertTrue(query["k"].orEmpty().matches(Regex("[0-9a-f]{64}")))
        assertFalse(query.containsKey("c"))
        assertFalse(session.payload.contains("phoneToken", ignoreCase = true))
        assertFalse(session.payload.contains("launcherSecret", ignoreCase = true))
    }

    @Test
    fun lan_claim_returns_encrypted_credentials_and_is_single_use() {
        val session = createLanSession()
        val request = lanClaim(session, nonce = "nonce-0123456789abcdef")

        val first = PhonePairingBootstrap.claim(request, remoteAddress = "192.168.1.30")
        val replay = PhonePairingBootstrap.claim(request, remoteAddress = "192.168.1.30")

        assertTrue(first.success)
        assertEquals(1, promoted.size)
        assertEquals(
            PhonePairingBootstrap.PENDING_CREDENTIAL_VALID_UNTIL,
            previousCredentialDeadlines.single()
        )
        assertNull(first.credentials)
        assertEquals("AES-256-GCM-HKDF-SHA256", first.encryptedCredentials!!.algorithm)
        assertFalse(first.encryptedCredentials!!.ciphertext.contains(promoted.single().phoneToken))
        assertFalse(first.encryptedCredentials!!.ciphertext.contains(promoted.single().launcherSecret))
        assertFalse(replay.success)
        assertEquals("phone_pairing_code_replayed", replay.errorCode)
        assertEquals(1, promoted.size)
    }

    @Test
    fun lan_nonce_replay_is_rejected_before_a_valid_proof_can_be_reused() {
        val session = createLanSession()
        val nonce = "nonce-0123456789abcdef"
        val invalid = PhonePairingBootstrap.claim(
            lanClaim(session, nonce).copy(proof = "00".repeat(32)),
            remoteAddress = "192.168.1.30"
        )
        val replay = PhonePairingBootstrap.claim(
            lanClaim(session, nonce),
            remoteAddress = "192.168.1.30"
        )

        assertEquals("phone_pairing_proof_invalid", invalid.errorCode)
        assertEquals("phone_pairing_nonce_replayed", replay.errorCode)
        assertTrue(promoted.isEmpty())
    }

    @Test
    fun failed_lan_proofs_are_limited_per_remote_and_session() {
        val session = createLanSession()

        repeat(4) { index ->
            val invalid = PhonePairingBootstrap.claim(
                lanClaim(session, "nonce-remote-a-00000$index").copy(proof = "00".repeat(32)),
                remoteAddress = "192.168.1.30"
            )
            assertEquals("phone_pairing_proof_invalid", invalid.errorCode)
        }
        val limited = PhonePairingBootstrap.claim(
            lanClaim(session, "nonce-remote-a-000004").copy(proof = "00".repeat(32)),
            remoteAddress = "192.168.1.30"
        )
        val otherRemote = PhonePairingBootstrap.claim(
            lanClaim(session, "nonce-remote-b-000000"),
            remoteAddress = "192.168.1.31"
        )

        assertEquals("phone_pairing_rate_limited", limited.errorCode)
        assertTrue(otherRemote.success)
    }

    @Test
    fun six_digit_code_only_claims_over_usb_loopback() {
        val session = PhonePairingBootstrap.createSession(
            baseUrl = "http://127.0.0.1:19527",
            deviceInstanceId = "lumi-phone-a",
            deviceName = "Pixel",
            transportHint = "usb"
        )
        val lanAttempt = PhonePairingBootstrap.claim(
            usbClaim(session),
            remoteAddress = "192.168.1.30"
        )
        val usb = PhonePairingBootstrap.claim(
            usbClaim(session),
            remoteAddress = "127.0.0.1"
        )

        assertEquals("phone_pairing_transport_invalid", lanAttempt.errorCode)
        assertTrue(usb.success)
        assertTrue(usb.credentials!!.phoneToken.length >= 48)
        assertTrue(usb.credentials!!.launcherSecret.length >= 48)
        assertNotEquals(usb.credentials!!.phoneToken, usb.credentials!!.launcherSecret)
    }

    @Test
    fun unknown_usb_codes_are_source_limited_before_session_lookup() {
        val session = PhonePairingBootstrap.createSession(
            baseUrl = "http://127.0.0.1:19527",
            deviceInstanceId = "lumi-phone-a",
            deviceName = "Pixel",
            transportHint = "usb"
        )
        val wrongCode = if (session.code == "000000") "000001" else "000000"

        var result: PhonePairingBootstrap.ClaimResult? = null
        repeat(PhonePairingBootstrapTestConstants.SOURCE_LIMIT_ATTEMPTS) {
            result = PhonePairingBootstrap.claim(
                PhonePairingBootstrap.ClaimRequest(
                    sessionId = "",
                    code = wrongCode,
                    nonce = "",
                    proof = "",
                    transport = "usb",
                    deviceInstanceId = "",
                    launcherId = "loom-desktop-a",
                    launcherName = "LOOM"
                ),
                remoteAddress = "127.0.0.1"
            )
        }

        assertEquals("phone_pairing_rate_limited", result!!.errorCode)
        assertTrue(promoted.isEmpty())
    }

    @Test
    fun lan_session_cannot_be_downgraded_to_usb_code_claim() {
        val session = createLanSession()
        val result = PhonePairingBootstrap.claim(
            usbClaim(session),
            remoteAddress = "127.0.0.1"
        )

        assertEquals("phone_pairing_transport_invalid", result.errorCode)
        assertTrue(promoted.isEmpty())
    }

    @Test
    fun expired_session_and_device_mismatch_do_not_promote_credentials() {
        val expired = createLanSession(ttlMs = 300_000L)
        now += 300_001L
        val expiredResult = PhonePairingBootstrap.claim(
            lanClaim(expired, "nonce-expired-00000000"),
            remoteAddress = "192.168.1.30"
        )
        now = 1_000_000L
        val mismatchSession = createLanSession()
        val mismatch = PhonePairingBootstrap.claim(
            lanClaim(mismatchSession, "nonce-mismatch-0000000").copy(
                deviceInstanceId = "lumi-phone-b"
            ),
            remoteAddress = "192.168.1.30"
        )

        assertEquals("phone_pairing_code_expired", expiredResult.errorCode)
        assertEquals("phone_pairing_device_mismatch", mismatch.errorCode)
        assertTrue(promoted.isEmpty())
    }

    private fun createLanSession(ttlMs: Long = PhonePairingBootstrap.DEFAULT_TTL_MS) =
        PhonePairingBootstrap.createSession(
            baseUrl = "http://192.168.1.8:9527",
            deviceInstanceId = "lumi-phone-a",
            deviceName = "Pixel",
            transportHint = "lan",
            ttlMs = ttlMs
        )

    private fun lanClaim(
        session: PhonePairingBootstrap.SessionView,
        nonce: String
    ): PhonePairingBootstrap.ClaimRequest {
        val query = parseQuery(session.payload)
        val launcherId = "loom-desktop-a"
        val proofInput = listOf(
            "LOOM-PAIR-CLAIM-V3",
            session.sessionId,
            nonce,
            "lumi-phone-a",
            launcherId
        ).joinToString("\n")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(hexToBytes(query.getValue("k")), "HmacSHA256"))
        val proof = mac.doFinal(proofInput.toByteArray()).toHex()
        return PhonePairingBootstrap.ClaimRequest(
            sessionId = session.sessionId,
            code = "",
            nonce = nonce,
            proof = proof,
            transport = "lan",
            deviceInstanceId = "lumi-phone-a",
            launcherId = launcherId,
            launcherName = "LOOM"
        )
    }

    private fun usbClaim(session: PhonePairingBootstrap.SessionView) =
        PhonePairingBootstrap.ClaimRequest(
            sessionId = session.sessionId,
            code = session.code,
            nonce = "",
            proof = "",
            transport = "usb",
            deviceInstanceId = "lumi-phone-a",
            launcherId = "loom-desktop-a",
            launcherName = "LOOM"
        )

    private fun parseQuery(payload: String): Map<String, String> {
        return URI(payload).rawQuery.split("&").associate { field ->
            val parts = field.split("=", limit = 2)
            parts[0] to java.net.URLDecoder.decode(parts.getOrElse(1) { "" }, "UTF-8")
        }
    }

    private fun hexToBytes(value: String): ByteArray =
        value.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    private fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it.toInt() and 0xff) }
}

private object PhonePairingBootstrapTestConstants {
    const val SOURCE_LIMIT_ATTEMPTS = 8
}
