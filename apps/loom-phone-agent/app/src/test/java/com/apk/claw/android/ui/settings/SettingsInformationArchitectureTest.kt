package com.apk.claw.android.ui.settings

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsInformationArchitectureTest {
    @Test
    fun loom_connection_group_is_first_and_has_fixed_action_order() {
        val layout = File("src/main/res/layout/activity_settings.xml").readText()
        val activity = File("src/main/java/com/apk/claw/android/ui/settings/SettingsActivity.kt").readText()

        assertTrue(layout.indexOf("@+id/connectionGroup") < layout.indexOf("@+id/modelGroup"))
        val connectionBlock = activity.substringAfter("val connectionGroup")
            .substringBefore("val modelGroup")
        assertTrue(connectionBlock.indexOf("MenuAction.PC_PAIRING") < connectionBlock.indexOf("MenuAction.LAN_CONFIG"))
        assertTrue(connectionBlock.indexOf("MenuAction.LAN_CONFIG") < connectionBlock.indexOf("MenuAction.CONNECTION_DIAGNOSTICS"))
    }

    @Test
    fun publish_relay_entry_is_hidden_but_runtime_protocol_remains() {
        val layout = File("src/main/res/layout/activity_settings.xml").readText()
        val activity = File("src/main/java/com/apk/claw/android/ui/settings/SettingsActivity.kt").readText()
        val viewModel = File("src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt").readText()
        val appViewModel = File("src/main/java/com/apk/claw/android/AppViewModel.kt").readText()
        val application = File("src/main/java/com/apk/claw/android/ClawApplication.kt").readText()

        assertFalse(layout.contains("publishGroup"))
        assertFalse(activity.contains("PUBLISH_RELAY"))
        assertFalse(viewModel.contains("PUBLISH_RELAY"))
        assertTrue(File("src/main/java/com/apk/claw/android/publish/PublishRelayManager.kt").exists())
        assertTrue(appViewModel.contains("PublishRelayManager.syncFromStorage()"))
        assertTrue(application.contains("PublishRelayManager.reconnectIfNeeded()"))
    }

    @Test
    fun connection_row_uses_transport_specific_status_copy() {
        val strings = File("src/main/res/values-zh/strings.xml").readText()

        assertTrue(strings.contains("连接方式与局域网"))
        assertTrue(strings.contains("USB 可用"))
        assertTrue(strings.contains("局域网可用：%1\$s"))
        assertTrue(strings.contains("热点可用：%1\$s"))
        assertTrue(strings.contains("服务已关闭"))
        assertTrue(strings.contains("正在切换"))
    }
}
