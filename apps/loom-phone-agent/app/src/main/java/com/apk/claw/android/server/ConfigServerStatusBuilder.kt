package com.apk.claw.android.server

import com.google.gson.JsonNull
import com.google.gson.JsonArray
import com.google.gson.JsonObject

object ConfigServerStatusBuilder {
    fun addTo(
        target: JsonObject,
        running: Boolean,
        address: String?,
        actualPort: Int?,
        defaultPort: Int,
        candidates: List<PhoneNetworkCandidate> = emptyList()
    ) {
        target.addProperty("configServerRunning", running)
        if (address != null) {
            target.addProperty("configServerAddress", address)
        } else {
            target.add("configServerAddress", JsonNull.INSTANCE)
        }
        if (actualPort != null) {
            target.addProperty("configServerPort", actualPort)
        } else {
            target.add("configServerPort", JsonNull.INSTANCE)
        }
        target.addProperty("serverPort", actualPort ?: defaultPort)
        target.addProperty("networkMode", candidates.firstOrNull()?.mode?.wireName ?: PhoneNetworkMode.NONE.wireName)
        target.addProperty("usbLoopbackAvailable", running)
        target.add("networkCandidates", JsonArray().apply {
            if (running && actualPort != null) {
                candidates.forEach { candidate ->
                    add(JsonObject().apply {
                        addProperty("interface", candidate.interfaceName)
                        addProperty("address", candidate.address)
                        addProperty("mode", candidate.mode.wireName)
                        addProperty("baseUrl", "http://${candidate.address}:$actualPort")
                    })
                }
            }
        })
    }
}
