package com.apk.claw.android.privilege

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShizukuIntegrationContractTest {
    @Test
    fun `official API is integrated while automatic Sui remains disabled`() {
        val build = File("build.gradle.kts").readText()
        val application = File("src/main/java/com/apk/claw/android/ClawApplication.kt").readText()

        assertTrue(build.contains("libs.shizuku.api"))
        assertTrue(build.contains("libs.shizuku.provider"))
        assertTrue(application.contains("ShizukuProvider.disableAutomaticSuiInitialization()"))
        assertTrue(
            application.indexOf("ShizukuProvider.disableAutomaticSuiInitialization()") <
                application.indexOf("super.attachBaseContext(base)")
        )
    }

    @Test
    fun `backend tracks binder and permission without exposing a shell`() {
        val source = File("src/main/java/com/apk/claw/android/privilege/ShizukuPrivilegeBackend.kt").readText()

        assertTrue(source.contains("Shizuku.addBinderReceivedListener"))
        assertTrue(source.contains("Shizuku.addBinderDeadListener"))
        assertTrue(source.contains("Shizuku.addRequestPermissionResultListener"))
        assertTrue(source.contains("Shizuku.requestPermission"))
        for (forbidden in listOf("newProcess", "ProcessBuilder", "Runtime.getRuntime", "rish", "/system/bin/sh")) {
            assertFalse("forbidden=$forbidden", source.contains(forbidden))
        }
    }

    @Test
    fun `settings exposes explicit enhanced capability status above ordinary settings`() {
        val layout = File("src/main/res/layout/activity_settings.xml").readText()
        val activity = File("src/main/java/com/apk/claw/android/ui/settings/SettingsActivity.kt").readText()
        val strings = File("src/main/res/values-zh/strings.xml").readText()

        assertTrue(layout.indexOf("@+id/capabilityGroup") < layout.indexOf("@+id/modelGroup"))
        assertTrue(activity.contains("MenuAction.ENHANCED_CAPABILITY"))
        assertTrue(strings.contains("增强设备能力"))
        assertTrue(strings.contains("保持标准模式"))
        assertTrue(strings.contains("Shizuku"))
    }
}
