package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class PhoneNetworkModeTest {
    @Test
    fun classifies_representative_phone_interface_names() {
        assertEquals(PhoneNetworkMode.NONE, PhoneNetworkMode.classify(emptyList()))
        assertEquals(PhoneNetworkMode.WIFI_CLIENT, PhoneNetworkMode.classify(listOf("wlan0")))
        assertEquals(PhoneNetworkMode.HOTSPOT_HOST, PhoneNetworkMode.classify(listOf("ap0")))
        assertEquals(PhoneNetworkMode.HOTSPOT_HOST, PhoneNetworkMode.classify(listOf("swlan0")))
        assertEquals(PhoneNetworkMode.HOTSPOT_HOST, PhoneNetworkMode.classify(listOf("softap0")))
        assertEquals(PhoneNetworkMode.USB_TETHERING, PhoneNetworkMode.classify(listOf("rndis0")))
        assertEquals(PhoneNetworkMode.USB_TETHERING, PhoneNetworkMode.classify(listOf("usb0")))
        assertEquals(PhoneNetworkMode.ETHERNET, PhoneNetworkMode.classify(listOf("eth0")))
        assertEquals(PhoneNetworkMode.CELLULAR, PhoneNetworkMode.classify(listOf("rmnet_data0")))
    }

    @Test
    fun returns_all_reachable_candidates_in_stable_priority_order() {
        val candidates = PhoneNetworkMode.reachableCandidates(
            listOf(
                PhoneInterfaceAddress("rmnet_data0", "10.23.4.5"),
                PhoneInterfaceAddress("wlan0", "192.168.1.9"),
                PhoneInterfaceAddress("ap0", "192.168.43.1"),
                PhoneInterfaceAddress("rndis0", "192.168.42.129"),
                PhoneInterfaceAddress("eth0", "192.168.88.7"),
                PhoneInterfaceAddress("lo", "127.0.0.1", siteLocal = false, loopback = true),
                PhoneInterfaceAddress("wlan0", "169.254.2.3", siteLocal = false, linkLocal = true),
                PhoneInterfaceAddress("wlan0", "192.168.1.9")
            )
        )

        assertEquals(
            listOf(
                PhoneNetworkCandidate("ap0", "192.168.43.1", PhoneNetworkMode.HOTSPOT_HOST),
                PhoneNetworkCandidate("wlan0", "192.168.1.9", PhoneNetworkMode.WIFI_CLIENT),
                PhoneNetworkCandidate("eth0", "192.168.88.7", PhoneNetworkMode.ETHERNET),
                PhoneNetworkCandidate("rndis0", "192.168.42.129", PhoneNetworkMode.USB_TETHERING)
            ),
            candidates
        )
        assertFalse(candidates.any { it.address == "10.23.4.5" })
    }
}
