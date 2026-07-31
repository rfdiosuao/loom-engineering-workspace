package com.apk.claw.android.server

/** Network-interface classification used by connection state reporting and Task 4 address policy. */
enum class PhoneNetworkMode {
    NONE,
    WIFI_CLIENT,
    HOTSPOT_HOST,
    USB_TETHERING,
    ETHERNET,
    CELLULAR,
    OTHER;

    companion object {
        fun classify(interfaceNames: Collection<String>): PhoneNetworkMode {
            if (interfaceNames.isEmpty()) return NONE
            return interfaceNames
                .map(::classifyInterface)
                .minByOrNull(::priority)
                ?: NONE
        }

        fun classifyInterface(interfaceName: String): PhoneNetworkMode {
            val name = interfaceName.lowercase()
            return when {
                name.startsWith("ap") || name.startsWith("swlan") || name.contains("softap") -> HOTSPOT_HOST
                name.startsWith("wlan") -> WIFI_CLIENT
                name.startsWith("rndis") || name.startsWith("usb") -> USB_TETHERING
                name.startsWith("eth") -> ETHERNET
                isCellularOnly(interfaceName) -> CELLULAR
                else -> OTHER
            }
        }

        fun isCellularOnly(interfaceName: String): Boolean {
            val name = interfaceName.lowercase()
            return name.startsWith("rmnet") ||
                name.startsWith("ccmni") ||
                name.startsWith("pdp") ||
                name.startsWith("wwan")
        }

        fun interfacePriority(interfaceName: String): Int = priority(classifyInterface(interfaceName))

        private fun priority(mode: PhoneNetworkMode): Int = when (mode) {
            HOTSPOT_HOST -> 0
            WIFI_CLIENT -> 1
            ETHERNET -> 2
            USB_TETHERING -> 3
            OTHER -> 8
            CELLULAR -> 9
            NONE -> 10
        }
    }
}
