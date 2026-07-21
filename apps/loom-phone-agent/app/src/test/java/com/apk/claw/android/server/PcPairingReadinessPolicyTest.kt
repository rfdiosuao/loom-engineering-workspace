package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PcPairingReadinessPolicyTest {
    @Test
    fun refuses_pairing_when_lan_address_is_missing() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = null,
            tokenConfigured = true,
            serverRunning = true,
            serverPort = 9527
        )

        assertFalse(result.ready)
        assertEquals("lan_unavailable", result.errorCode)
        assertTrue(result.message.contains("LAN", ignoreCase = true))
    }

    @Test
    fun refuses_pairing_when_token_is_missing() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
            tokenConfigured = false,
            serverRunning = true,
            serverPort = 9527
        )

        assertFalse(result.ready)
        assertEquals("api_token_missing", result.errorCode)
        assertTrue(result.message.contains("token", ignoreCase = true))
    }

    @Test
    fun refuses_pairing_when_server_is_not_actually_listening() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
            tokenConfigured = true,
            serverRunning = false,
            serverPort = null
        )

        assertFalse(result.ready)
        assertEquals("config_server_not_running", result.errorCode)
        assertTrue(result.message.contains("LAN Config", ignoreCase = true))
    }

    @Test
    fun ready_pairing_uses_actual_runtime_port() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
            tokenConfigured = true,
            serverRunning = true,
            serverPort = 9531
        )

        assertTrue(result.ready)
        assertEquals("http://192.168.1.8:9531", result.baseUrl)
        assertEquals("", result.errorCode)
    }
}
