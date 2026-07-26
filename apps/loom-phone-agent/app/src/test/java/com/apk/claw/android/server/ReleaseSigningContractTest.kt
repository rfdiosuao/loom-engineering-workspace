package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseSigningContractTest {
    @Test
    fun release_signing_identity_has_a_machine_verifiable_contract() {
        val fingerprint = File("../release/trusted-signing-cert.sha256").readText().trim()
        val verifier = File("../tools/verify-release-signature.ps1").readText()

        assertTrue(fingerprint.matches(Regex("^[0-9A-F]{64}$")))
        assertTrue(verifier.contains("apksigner"))
        assertTrue(verifier.contains("certificate SHA-256 digest"))
        assertTrue(verifier.contains("APK signing certificate mismatch"))
    }
}
