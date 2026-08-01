package com.apk.claw.android.release

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseVersionContractTest {
    @Test
    fun `LumiAgent 6_65 is frozen for default and Android 7 variants`() {
        val build = File("build.gradle.kts").readText()

        assertTrue(build.contains("versionCode = 934"))
        assertTrue(
            build.contains(
                "if (android7Compat) \"6.65-stability-android7\" else \"6.65-stability\""
            )
        )
    }

    @Test
    fun `release notes bind phone and desktop versions`() {
        val notes = File("../../../docs/RELEASE_NOTES_2.4.4.md").readText()

        assertTrue(notes.contains("麓鸣 Desktop `2.4.4`"))
        assertTrue(notes.contains("LumiAgent `6.65-stability`"))
        assertTrue(notes.contains("versionCode `934`"))
    }
}
