package com.apk.claw.android.skill

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SkillCenterSourceContractTest {
    @Test
    fun `settings opens a first class Skill Center`() {
        val activity = File("src/main/java/com/apk/claw/android/ui/settings/SettingsActivity.kt").readText()
        val viewModel = File("src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt").readText()
        val manifest = File("src/main/AndroidManifest.xml").readText()
        val strings = File("src/main/res/values-zh/strings.xml").readText()

        assertTrue(activity.contains("MenuAction.SKILL_CENTER"))
        assertTrue(activity.contains("SkillCenterActivity::class.java"))
        assertTrue(viewModel.contains("SKILL_CENTER"))
        assertTrue(manifest.contains(".ui.skill.SkillCenterActivity"))
        assertTrue(strings.contains("Skill 中心"))
        assertTrue(strings.contains("Linux 运行时"))
    }

    @Test
    fun `Agent gets a typed skill tool without arbitrary command surface`() {
        val registry = File("src/main/java/com/apk/claw/android/tool/ToolRegistry.kt").readText()
        val tool = File("src/main/java/com/apk/claw/android/tool/impl/RunSkillTool.kt").readText()

        assertTrue(registry.contains("register(RunSkillTool())"))
        assertTrue(tool.contains("workspace.text.batch"))
        assertTrue(tool.contains("workspace.jsonl.transform"))
        assertFalse(tool.contains("command"))
        assertFalse(tool.contains("argv"))
        assertFalse(tool.contains("ProcessBuilder"))
    }
}
