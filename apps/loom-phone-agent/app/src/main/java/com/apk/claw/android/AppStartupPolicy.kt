package com.apk.claw.android

object AppStartupPolicy {
    fun shouldStartControlPlane(llmConfigured: Boolean): Boolean = true

    fun shouldStartAgent(llmConfigured: Boolean): Boolean = llmConfigured

    fun shouldReconnectChannels(llmConfigured: Boolean): Boolean = llmConfigured
}
