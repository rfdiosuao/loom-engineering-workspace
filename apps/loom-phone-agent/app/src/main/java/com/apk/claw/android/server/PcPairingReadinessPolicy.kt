package com.apk.claw.android.server

enum class PairingTransportMode {
    AUTO,
    USB,
    LAN
}

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
        serverPort: Int?,
        transportMode: PairingTransportMode = PairingTransportMode.AUTO
    ): Result {
        if (!serverRunning || serverPort == null) {
            return Result(
                ready = false,
                baseUrl = "",
                transportHint = "",
                errorCode = "config_server_not_running",
                message = "手机连接服务尚未启动，请在手机端打开 LAN Config/电脑配对并启动连接服务后重试。",
                retryable = true
            )
        }
        val ip = lanIp.orEmpty().trim()
        val transport = when (transportMode) {
            PairingTransportMode.USB -> "usb"
            PairingTransportMode.LAN -> {
                if (ip.isBlank()) {
                    return Result(
                        ready = false,
                        baseUrl = "",
                        transportHint = "lan",
                        errorCode = "config_lan_unavailable",
                        message = "当前没有可用的局域网地址，请改用 USB 配对或检查网络后重试。",
                        retryable = true
                    )
                }
                "lan"
            }
            PairingTransportMode.AUTO -> if (ip.isBlank()) "usb" else "lan"
        }
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
