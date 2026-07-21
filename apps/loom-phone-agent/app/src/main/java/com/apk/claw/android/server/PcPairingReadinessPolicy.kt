package com.apk.claw.android.server

object PcPairingReadinessPolicy {
    data class Result(
        val ready: Boolean,
        val baseUrl: String,
        val errorCode: String,
        val message: String,
        val retryable: Boolean
    )

    fun evaluate(
        lanIp: String?,
        tokenConfigured: Boolean,
        serverRunning: Boolean,
        serverPort: Int?
    ): Result {
        val ip = lanIp.orEmpty().trim()
        if (ip.isBlank()) {
            return Result(
                ready = false,
                baseUrl = "",
                errorCode = "lan_unavailable",
                message = "Connect this phone to WiFi/LAN or enable hotspot before PC Pairing.",
                retryable = true
            )
        }
        if (!tokenConfigured) {
            return Result(
                ready = false,
                baseUrl = "",
                errorCode = "api_token_missing",
                message = "Set an API token before PC Pairing.",
                retryable = false
            )
        }
        if (!serverRunning || serverPort == null) {
            return Result(
                ready = false,
                baseUrl = "",
                errorCode = "config_server_not_running",
                message = "LAN Config is not listening yet. Enable LAN Config or retry PC Pairing after the server starts.",
                retryable = true
            )
        }
        return Result(
            ready = true,
            baseUrl = "http://$ip:$serverPort",
            errorCode = "",
            message = "ready",
            retryable = false
        )
    }
}
