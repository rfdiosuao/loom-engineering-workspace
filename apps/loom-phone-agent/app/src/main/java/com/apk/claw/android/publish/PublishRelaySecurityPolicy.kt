package com.apk.claw.android.publish

import java.net.URI

object PublishRelaySecurityPolicy {

    fun mayExecute(relayBaseUrl: String, draftOnly: Boolean): Boolean {
        if (draftOnly) return true
        val uri = runCatching { URI(relayBaseUrl.trim()) }.getOrNull() ?: return false
        val scheme = uri.scheme?.lowercase().orEmpty()
        val host = uri.host?.lowercase().orEmpty()
        return scheme == "https" ||
            (scheme == "http" && (host == "127.0.0.1" || host == "localhost" || host == "::1"))
    }
}
