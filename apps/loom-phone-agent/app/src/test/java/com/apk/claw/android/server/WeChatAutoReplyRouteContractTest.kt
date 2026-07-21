package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class WeChatAutoReplyRouteContractTest {
    @Test
    fun config_server_exposes_signed_and_token_wechat_auto_reply_routes() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

        assertTrue(source.contains("\"/api/lumi/wechat/auto_reply\""))
        assertTrue(source.contains("WeChatAutoReplyApiController.handleAutoReply"))
        assertTrue(source.contains("\"/api/tool/wechat_auto_reply\""))
    }
}
