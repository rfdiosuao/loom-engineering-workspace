package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentCampaignRouteSourceContractTest {
    private val source = sequenceOf(
        File("app/src/main/java/com/apk/claw/android/server/ConfigServer.kt"),
        File("src/main/java/com/apk/claw/android/server/ConfigServer.kt")
    ).firstOrNull { it.isFile }?.readText() ?: error("ConfigServer.kt not found")

    @Test
    fun token_and_lumi_surfaces_expose_the_same_five_campaign_operations() {
        listOf("prepare", "status", "confirm", "cancel", "resume").forEach { operation ->
            assertTrue(source.contains("/api/comment-campaign/$operation"))
            assertTrue(source.contains("/api/lumi/comment-campaign/$operation"))
        }
        assertTrue(source.contains("handleLumiJson(session)"))
        assertTrue(source.contains("CommentCampaignApiController.handle"))
    }
}
