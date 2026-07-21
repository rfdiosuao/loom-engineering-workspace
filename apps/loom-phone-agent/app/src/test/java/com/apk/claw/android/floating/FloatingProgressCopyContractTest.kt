package com.apk.claw.android.floating

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FloatingProgressCopyContractTest {

    @Test
    fun chineseFloatingProgressUsesHumanReadableCopy() {
        val stringsFile = sequenceOf(
            File("app/src/main/res/values-zh/strings.xml"),
            File("src/main/res/values-zh/strings.xml")
        ).firstOrNull { it.isFile } ?: error("Chinese strings.xml not found")

        val text = stringsFile.readText()
        val floatingCopy = Regex(
            "<string name=\"floating_log_(?:idle|received|running|action|success|error)\">(.*?)</string>",
            setOf(RegexOption.DOT_MATCHES_ALL)
        ).findAll(text).joinToString("\n") { it.groupValues[1] }

        assertTrue(floatingCopy.contains("正在"))
        assertTrue(floatingCopy.contains("任务已完成"))
        assertFalse(floatingCopy.contains("status="))
        assertFalse(floatingCopy.contains("round="))
        assertFalse(floatingCopy.contains("mode="))
        assertFalse(floatingCopy.contains("action="))
        assertFalse(floatingCopy.contains("target="))
    }

    @Test
    fun homeTaskConsoleAvoidsWireProtocolFields() {
        val stringsFile = sequenceOf(
            File("app/src/main/res/values-zh/strings.xml"),
            File("src/main/res/values-zh/strings.xml")
        ).firstOrNull { it.isFile } ?: error("Chinese strings.xml not found")
        val activityFile = sequenceOf(
            File("app/src/main/java/com/apk/claw/android/ui/home/HomeActivity.kt"),
            File("src/main/java/com/apk/claw/android/ui/home/HomeActivity.kt")
        ).firstOrNull { it.isFile } ?: error("HomeActivity.kt not found")

        val idleCopy = Regex(
            "<string name=\"home_task_console_idle\">(.*?)</string>",
            setOf(RegexOption.DOT_MATCHES_ALL)
        ).find(stringsFile.readText())?.groupValues?.get(1).orEmpty()
        val activityText = activityFile.readText()
        val consoleBuilder = activityText.substringAfter("private fun buildTaskConsoleText")
            .substringBefore("private fun controlPlaneAddressLabel")

        assertTrue(consoleBuilder.contains("FloatingCircleManager.getRecentLog"))

        listOf("status=", "mode=", "channel=", "messageId=", "step=", "action=", "totalMs=", "updatedAt=")
            .forEach { token ->
                assertFalse("Idle copy exposes $token", idleCopy.contains(token))
                assertFalse("Home console exposes $token", consoleBuilder.contains(token))
            }
    }

    @Test
    fun chineseToolProgressHasItsOwnSequentialStageNumber() {
        val stringsFile = sequenceOf(
            File("app/src/main/res/values-zh/strings.xml"),
            File("src/main/res/values-zh/strings.xml")
        ).firstOrNull { it.isFile } ?: error("Chinese strings.xml not found")

        val toolCopy = Regex("<string name=\"floating_history_tool\">(.*?)</string>")
            .find(stringsFile.readText())?.groupValues?.get(1).orEmpty()

        assertTrue(toolCopy.contains("\u8c03\u7528\u5de5\u5177"))
        assertTrue(toolCopy.contains("\u7b2c %1${'$'}d \u9636\u6bb5"))
    }
}
