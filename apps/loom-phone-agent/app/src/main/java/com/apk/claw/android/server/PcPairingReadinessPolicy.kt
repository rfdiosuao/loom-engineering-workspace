package com.apk.claw.android.server

object PcPairingReadinessPolicy {
    data class Result(
        val ready: Boolean,
        val baseUrl: String,
        val transportHint: String,
        val errorCode: String,
        val message: String,
        val retryable: Boolean
    )

    fun evaluate(
        lanIp: String?,
        serverRunning: Boolean,
        serverPort: Int?
    ): Result {
        if (!serverRunning || serverPort == null) {
            return Result(
                ready = false,
                baseUrl = "",
                transportHint = "",
                errorCode = "config_server_not_running",
                message = "手机连接服务尚未启动，请返回后重试。",
                retryable = true
            )
        }
        val ip = lanIp.orEmpty().trim()
        val transport = if (ip.isBlank()) "usb" else "lan"
        val host = if (transport == "usb") "127.0.0.1" else ip
        return Result(
            ready = true,
            baseUrl = "http://$host:$serverPort",
            transportHint = transport,
            errorCode = "",
            message = "ready",
            retryable = false
        )
    }
}
