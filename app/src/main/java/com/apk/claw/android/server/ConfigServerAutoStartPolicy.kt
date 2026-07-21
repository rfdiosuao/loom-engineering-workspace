package com.apk.claw.android.server

object ConfigServerAutoStartPolicy {
    fun shouldAutoStart(
        configServerEnabled: Boolean,
        llmConfigured: Boolean
    ): Boolean {
        return configServerEnabled
    }
}
