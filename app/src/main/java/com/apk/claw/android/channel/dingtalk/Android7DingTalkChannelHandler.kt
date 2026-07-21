package com.apk.claw.android.channel.dingtalk

import com.apk.claw.android.channel.Channel
import com.apk.claw.android.channel.ChannelHandler
import com.apk.claw.android.utils.XLog

/**
 * DingTalk stream SDK uses Android O-only bytecode. The Android 7 compatibility
 * package keeps phone/relay control available while disabling this optional channel.
 */
class Android7DingTalkChannelHandler : ChannelHandler {
    override val channel = Channel.DINGTALK

    override fun isConnected(): Boolean = false

    override fun init() {
        XLog.w(TAG, "DingTalk is disabled in the Android 7 compatibility package")
    }

    override fun disconnect() = Unit

    override fun reinitFromStorage() {
        init()
    }

    override fun sendMessage(content: String, messageID: String) {
        warnDisabled()
    }

    override fun sendImage(imageBytes: ByteArray, messageID: String) {
        warnDisabled()
    }

    override fun sendFile(file: java.io.File, messageID: String) {
        warnDisabled()
    }

    private fun warnDisabled() {
        XLog.w(TAG, "DingTalk action ignored in the Android 7 compatibility package")
    }

    companion object {
        private const val TAG = "DingTalkCompat"
    }
}
