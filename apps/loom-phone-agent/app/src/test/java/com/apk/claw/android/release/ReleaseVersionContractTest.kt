package com.apk.claw.android.release

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseVersionContractTest {
    @Test
    fun `LumiAgent 6_66 is frozen for default and Android 7 variants`() {
        val build = File("build.gradle.kts").readText()

        assertTrue(build.contains("versionCode = 935"))
        assertTrue(
            build.contains(
                "if (android7Compat) \"6.66-stability-android7\" else \"6.66-stability\""
            )
        )
    }

    @Test
    fun `release notes bind phone and desktop versions`() {
        val notes = File("../../../docs/RELEASE_NOTES_2.4.5.md").readText()

        assertTrue(notes.contains("麓鸣 Desktop `2.4.5`"))
        assertTrue(notes.contains("LumiAgent `6.66-stability`"))
        assertTrue(notes.contains("versionCode `935`"))
    }
}
