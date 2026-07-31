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

    val wireName: String
        get() = name.lowercase().replace('_', '-')

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
                name.startsWith("ap") ||
                    name.startsWith("swlan") ||
                    name.contains("softap") ||
                    name.startsWith("br-wlan") ||
                    name.startsWith("ap_br") -> HOTSPOT_HOST
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

        fun reachableCandidates(addresses: Collection<PhoneInterfaceAddress>): List<PhoneNetworkCandidate> {
            return addresses.asSequence()
                .filter { it.siteLocal && !it.loopback && !it.linkLocal && !it.anyLocal }
                .map { address ->
                    PhoneNetworkCandidate(
                        interfaceName = address.interfaceName,
                        address = address.address,
                        mode = classifyInterface(address.interfaceName)
                    )
                }
                .filter { it.mode in LAN_CAPABLE_MODES }
                .sortedWith(
                    compareBy<PhoneNetworkCandidate>(
                        { priority(it.mode) },
                        { it.interfaceName },
                        { it.address }
                    )
                )
                .distinctBy { it.address }
                .toList()
        }

        private val LAN_CAPABLE_MODES = setOf(
            HOTSPOT_HOST,
            WIFI_CLIENT,
            ETHERNET,
            USB_TETHERING
        )

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

data class PhoneInterfaceAddress(
    val interfaceName: String,
    val address: String,
    val siteLocal: Boolean = true,
    val loopback: Boolean = false,
    val linkLocal: Boolean = false,
    val anyLocal: Boolean = false
)

data class PhoneNetworkCandidate(
    val interfaceName: String,
    val address: String,
    val mode: PhoneNetworkMode
)
