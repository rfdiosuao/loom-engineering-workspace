package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PcPairingReadinessPolicyTest {
    @Test
    fun usb_pairing_remains_ready_when_lan_address_is_missing() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = null,
            serverRunning = true,
            serverPort = 9527
        )

        assertTrue(result.ready)
        assertEquals("http://127.0.0.1:9527", result.baseUrl)
        assertEquals("usb", result.transportHint)
        assertEquals("", result.errorCode)
    }

    @Test
    fun first_pairing_does_not_require_an_existing_token() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
            serverRunning = true,
            serverPort = 9527
        )

        assertTrue(result.ready)
        assertEquals("http://192.168.1.8:9527", result.baseUrl)
        assertEquals("lan", result.transportHint)
    }

    @Test
    fun refuses_pairing_when_server_is_not_actually_listening() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
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
            serverRunning = true,
            serverPort = 9531
        )

        assertTrue(result.ready)
        assertEquals("http://192.168.1.8:9531", result.baseUrl)
        assertEquals("lan", result.transportHint)
        assertEquals("", result.errorCode)
    }
}
