package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class RpaRouteContractTest {
    @Test
    fun config_server_exposes_legacy_and_lumi_rpa_routes() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

        assertTrue(source.contains("/api/rpa/run"))
        assertTrue(source.contains("/api/rpa/runs"))
        assertTrue(source.contains("/api/rpa/validate"))
        assertTrue(source.contains("/api/rpa/capabilities"))
        assertTrue(source.contains("/api/lumi/rpa/run"))
        assertTrue(source.contains("/api/lumi/rpa/runs"))
        assertTrue(source.contains("/api/lumi/rpa/validate"))
        assertTrue(source.contains("/api/lumi/rpa/capabilities"))
        assertTrue(source.contains("RpaApiController.handleRun(it, requireToken = false)"))
    }
}
