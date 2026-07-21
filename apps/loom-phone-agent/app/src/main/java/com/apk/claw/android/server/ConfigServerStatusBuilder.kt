package com.apk.claw.android.server

import com.google.gson.JsonNull
import com.google.gson.JsonObject

object ConfigServerStatusBuilder {
    fun addTo(
        target: JsonObject,
        running: Boolean,
        address: String?,
        actualPort: Int?,
        defaultPort: Int
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
    }
}
