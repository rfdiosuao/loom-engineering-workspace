package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UsbIdentityChallengeTest {
    @Test
    fun acceptsOnlyLoopbackPeers() {
        assertTrue(UsbIdentityChallenge.isLoopbackPeer("127.0.0.1"))
        assertTrue(UsbIdentityChallenge.isLoopbackPeer("::1"))
        assertTrue(UsbIdentityChallenge.isLoopbackPeer("0:0:0:0:0:0:0:1"))
        assertFalse(UsbIdentityChallenge.isLoopbackPeer("192.168.1.20"))
        assertFalse(UsbIdentityChallenge.isLoopbackPeer(null))
    }

    @Test
    fun challenge_proof_is_stable_and_bound_to_nonce_package_installation_and_port() {
        val nonce = "abcdefghijklmnopqrstuvwxyzABCDEF0123456789_-"

        val proof = UsbIdentityChallenge.proof(
            token = "phone-secret",
            nonce = nonce,
            packageName = "com.apk.claw.android",
            versionCode = 922,
            deviceInstanceId = "lumi-4f71395a-e29f-4c5f-b2a0-97cefeff44b7",
            listeningPort = 9527
        )

        assertEquals("loom-usb-bind-v3", UsbIdentityChallenge.PROTOCOL)
        assertEquals("S7otp3YvfoTld8vz-jB9QLIr66OLJyx6zYLo-V_g6UQ", proof)
        assertTrue(UsbIdentityChallenge.isValidNonce(nonce))
        assertFalse(UsbIdentityChallenge.isValidNonce("short"))
    }

    @Test
    fun rejects_oversized_or_invalid_unauthenticated_request_bodies() {
        assertTrue(UsbIdentityChallenge.isAllowedBodyLength(0))
        assertTrue(UsbIdentityChallenge.isAllowedBodyLength(UsbIdentityChallenge.MAX_BODY_BYTES))
        assertFalse(UsbIdentityChallenge.isAllowedBodyLength(UsbIdentityChallenge.MAX_BODY_BYTES + 1))
        assertFalse(UsbIdentityChallenge.isAllowedBodyLength(-1))
        assertNull("not-a-number".toLongOrNull())
    }
}
