package com.apk.claw.android.service

import com.apk.claw.android.server.ConfigServerAutoStartPolicy

object KeepAliveRecoveryPolicy {
    fun shouldStartForegroundService(foregroundServiceRunning: Boolean): Boolean {
        return !foregroundServiceRunning
    }

    fun shouldHealConfigServer(
        configServerEnabled: Boolean,
        llmConfigured: Boolean,
        configServerRunning: Boolean
    ): Boolean {
        return !configServerRunning &&
            ConfigServerAutoStartPolicy.shouldAutoStart(configServerEnabled, llmConfigured)
    }
}
