package com.apk.claw.android.runtime

import com.apk.claw.android.skill.LinuxSkillRuntimeState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LinuxRuntimeInstallPolicyTest {
    private val distribution = LinuxRuntimeDistribution(
        downloadUrl = "https://downloads.example.com/LumiLinuxRuntime.apk",
        sha256 = "a".repeat(64),
        packageName = LinuxRuntimeCompanionClient.COMPANION_PACKAGE,
        minVersionCode = 1L,
        signerSha256 = "b".repeat(64)
    )

    @Test
    fun `missing companion is downloaded before runtime initialization`() {
        val decision = LinuxRuntimeInstallPolicy.decide(
            runtimeState = LinuxSkillRuntimeState.MISSING,
            companionInstalled = false,
            distribution = distribution
        )

        assertEquals(LinuxRuntimeInstallAction.DOWNLOAD_COMPANION, decision.action)
        assertEquals("companion_install_required", decision.code)
    }

    @Test
    fun `installed companion is initialized without another download`() {
        val decision = LinuxRuntimeInstallPolicy.decide(
            runtimeState = LinuxSkillRuntimeState.MISSING,
            companionInstalled = true,
            distribution = distribution
        )

        assertEquals(LinuxRuntimeInstallAction.INITIALIZE_RUNTIME, decision.action)
    }

    @Test
    fun `missing distribution is a configuration error instead of companion missing loop`() {
        val decision = LinuxRuntimeInstallPolicy.decide(
            runtimeState = LinuxSkillRuntimeState.MISSING,
            companionInstalled = false,
            distribution = null
        )

        assertEquals(LinuxRuntimeInstallAction.BLOCKED, decision.action)
        assertEquals("companion_distribution_missing", decision.code)
    }

    @Test
    fun `distribution requires https immutable digest exact package and signer`() {
        assertTrue(distribution.isValid())
        assertFalse(distribution.copy(downloadUrl = "http://downloads.example.com/runtime.apk").isValid())
        assertFalse(distribution.copy(sha256 = "abc").isValid())
        assertFalse(distribution.copy(packageName = "com.example.fake").isValid())
        assertFalse(distribution.copy(signerSha256 = "abc").isValid())
    }
}
