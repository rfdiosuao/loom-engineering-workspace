package com.apk.claw.android.runtime

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LinuxRuntimeCompanionSourceContractTest {
    @Test
    fun `PRoot runtime is a separate signature protected companion`() {
        val settings = File("../settings.gradle.kts").readText()
        val manifest = File("../linux-runtime/src/main/AndroidManifest.xml").readText()
        val provider = File("../linux-runtime/src/main/java/com/luming/linuxruntime/LinuxRuntimeProvider.kt").readText()

        assertTrue(settings.contains("include(\":linux-runtime\")"))
        assertTrue(manifest.contains("signature"))
        assertTrue(manifest.contains("com.luming.linuxruntime.permission.EXECUTE"))
        assertFalse(manifest.contains("android.permission.INTERNET"))
        assertTrue(provider.contains("workspace.text.batch"))
        assertTrue(provider.contains("workspace.jsonl.transform"))
        assertFalse(provider.contains("agent.cli.batch"))
        assertFalse(provider.contains("getString(\"command\")"))
        assertFalse(provider.contains("getStringArray(\"argv\")"))
    }

    @Test
    fun `companion ships audited binaries rootfs SBOM and rollback installer`() {
        val installer = File("../linux-runtime/src/main/java/com/luming/linuxruntime/LinuxRuntimeInstaller.kt").readText()
        val sbom = File("../linux-runtime/src/main/assets/runtime-sbom.spdx.json")
        val notice = File("../linux-runtime/THIRD_PARTY_NOTICES.md")

        assertTrue(installer.contains("staging"))
        assertTrue(installer.contains("sha256"))
        assertTrue(installer.contains("rollback"))
        assertTrue(installer.contains("GZIPInputStream"))
        assertTrue(installer.contains("ownershipWarningsOnly"))
        assertFalse(installer.contains(".toPath()"))
        assertFalse(installer.contains("waitFor(timeoutMs, TimeUnit"))
        assertTrue(sbom.exists())
        assertTrue(notice.exists())
        assertTrue(File("../linux-runtime/LICENSES/THIRD_PARTY_NOTICES.md").exists())
        assertTrue(File("../linux-runtime/build.gradle.kts").readText().contains("assets.directories.add(\"LICENSES\")"))
        assertTrue(File("../linux-runtime/src/main/assets/runtime/x86_64/proot").exists())
        assertTrue(File("../linux-runtime/src/main/assets/runtime/x86_64/rootfs.tgz").exists())
        assertTrue(File("../linux-runtime/src/main/assets/runtime/arm64-v8a/proot").exists())
        assertTrue(File("../linux-runtime/src/main/assets/runtime/arm64-v8a/rootfs.tgz").exists())
    }
}
