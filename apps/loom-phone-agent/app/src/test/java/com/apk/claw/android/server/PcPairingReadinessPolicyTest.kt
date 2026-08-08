package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PcPairingReadinessPolicyTest {
    @Test
    fun explicit_usb_mode_keeps_loopback_ready_when_wifi_lan_address_exists() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.1.8",
            serverRunning = true,
            serverPort = 9527,
            transportMode = PairingTransportMode.USB
        )

        assertTrue(result.ready)
        assertEquals("http://127.0.0.1:9527", result.baseUrl)
        assertEquals("usb", result.transportHint)
    }

    @Test
    fun explicit_usb_mode_keeps_loopback_ready_when_hotspot_address_exists() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = "192.168.43.1",
            serverRunning = true,
            serverPort = 9527,
            transportMode = PairingTransportMode.USB
        )

        assertTrue(result.ready)
        assertEquals("http://127.0.0.1:9527", result.baseUrl)
        assertEquals("usb", result.transportHint)
    }

    @Test
    fun explicit_usb_mode_remains_ready_when_lan_is_unavailable() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = null,
            serverRunning = true,
            serverPort = 9527,
            transportMode = PairingTransportMode.USB
        )

        assertTrue(result.ready)
        assertEquals("http://127.0.0.1:9527", result.baseUrl)
        assertEquals("usb", result.transportHint)
    }

    @Test
    fun explicit_lan_mode_reports_unavailable_without_a_lan_address() {
        val result = PcPairingReadinessPolicy.evaluate(
            lanIp = null,
            serverRunning = true,
            serverPort = 9527,
            transportMode = PairingTransportMode.LAN
        )

        assertFalse(result.ready)
        assertEquals("config_lan_unavailable", result.errorCode)
    }

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
