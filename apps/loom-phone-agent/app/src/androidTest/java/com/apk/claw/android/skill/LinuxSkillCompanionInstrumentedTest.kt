package com.apk.claw.android.skill

import android.content.pm.PackageManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.apk.claw.android.runtime.LinuxRuntimeCompanionClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LinuxSkillCompanionInstrumentedTest {
    @Test
    fun cold_install_then_repeated_skill_runs_are_stable_and_offline() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        val installed = LinuxRuntimeCompanionClient.install(context)
        assertTrue("install failed: ${installed.code} ${installed.output}", installed.success)
        assertEquals("ready", installed.code)
        assertEquals("proot-5.1.107.89+alpine-3.22.5", installed.runtimeVersion)

        val first = LinuxRuntimeCompanionClient.execute(
            "workspace.text.batch",
            "unique_sort",
            "beta\nalpha\nalpha\n",
            context
        )
        val second = LinuxRuntimeCompanionClient.execute(
            "workspace.text.batch",
            "unique_sort",
            "beta\nalpha\nalpha\n",
            context
        )
        assertTrue("first failed: ${first.code} ${first.output}", first.success)
        assertTrue("second failed: ${second.code} ${second.output}", second.success)
        assertEquals("alpha\nbeta", first.output.trim())
        assertEquals(first.output, second.output)
        assertTrue("first run too slow: ${first.durationMs}", first.durationMs < 5_000)
        assertTrue("second run too slow: ${second.durationMs}", second.durationMs < 5_000)

        val rejected = LinuxRuntimeCompanionClient.execute(
            "agent.cli.batch",
            "anything",
            "ignored",
            context
        )
        assertFalse(rejected.success)
        assertEquals("skill_not_allowlisted", rejected.code)
        assertEquals(
            PackageManager.PERMISSION_DENIED,
            context.packageManager.checkPermission(
                "android.permission.INTERNET",
                LinuxRuntimeCompanionClient.COMPANION_PACKAGE
            )
        )
    }
}
