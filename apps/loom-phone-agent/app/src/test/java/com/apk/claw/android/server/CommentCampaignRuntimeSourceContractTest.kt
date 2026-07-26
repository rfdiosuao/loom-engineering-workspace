package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentCampaignRuntimeSourceContractTest {
    @Test
    fun production_runtime_installs_the_android_executor_instead_of_an_unavailable_stub() {
        val source = sequenceOf(
            File("app/src/main/java/com/apk/claw/android/server/CommentCampaignRuntime.kt"),
            File("src/main/java/com/apk/claw/android/server/CommentCampaignRuntime.kt")
        ).firstOrNull { it.isFile }?.readText() ?: error("CommentCampaignRuntime.kt not found")

        assertTrue(source.contains("AndroidCommentDeviceStepExecutor"))
        assertTrue(!source.contains("comment_driver_unavailable"))
    }
}
