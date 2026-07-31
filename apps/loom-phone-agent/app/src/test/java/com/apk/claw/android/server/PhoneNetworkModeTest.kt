package com.apk.claw.android.server

import org.junit.Assert.assertEquals
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
}
