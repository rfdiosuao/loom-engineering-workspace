package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseSigningSourceContractTest {
    @Test
    fun release_build_fails_fast_when_signing_material_is_incomplete() {
        val source = File("build.gradle.kts").readText()

        assertTrue(source.contains("validateReleaseSigning"))
        assertTrue(source.contains("GradleException"))
        assertTrue(source.contains("KEYSTORE_FILE"))
        assertTrue(source.contains("KEYSTORE_PASSWORD"))
        assertTrue(source.contains("KEY_ALIAS"))
        assertTrue(source.contains("KEY_PASSWORD"))
        assertTrue(source.contains("startParameter.taskNames"))
        assertTrue(source.contains("contains(\"Release\", ignoreCase = true)"))
    }
}
