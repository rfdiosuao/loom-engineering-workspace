package com.apk.claw.android.service

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeAwareTapIntegrationSourceContractTest {

    @Test
    fun agentTapAndClickRefUseLiveNodeTargeting() {
        val tapTool = source("tool/impl/mobile/TapTool.java")
        val controller = source("server/AgentApiController.kt")
        val service = source("service/ClawAccessibilityService.java")

        assertTrue(tapTool.contains("service.performNodeAwareTap(x, y, duration)"))
        assertTrue(controller.substringAfter("private fun clickJsonNodeFast")
            .substringBefore("private fun scrollFast")
            .contains("service.performNodeAwareTap(x, y, 100L)"))
        assertTrue(service.contains("public boolean performNodeAwareTap(int x, int y, long durationMs)"))
    }

    private fun source(relativePath: String): String {
        return sequenceOf(
            File("app/src/main/java/com/apk/claw/android/$relativePath"),
            File("src/main/java/com/apk/claw/android/$relativePath")
        ).firstOrNull { it.isFile }?.readText() ?: error("Source not found: $relativePath")
    }
}
