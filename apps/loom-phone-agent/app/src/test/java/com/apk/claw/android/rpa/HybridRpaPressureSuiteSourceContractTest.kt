package com.apk.claw.android.rpa

import com.google.gson.JsonParser
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.workflow.WorkflowTemplateStore
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class HybridRpaPressureSuiteSourceContractTest {
    private val repository = File("..").canonicalFile

    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun fixture_is_debug_only_and_has_no_sensitive_visible_text() {
        val debugManifest = File("src/debug/AndroidManifest.xml").readText()
        val releaseManifest = File("src/main/AndroidManifest.xml").readText()
        val layout = File("src/debug/res/layout/activity_hybrid_rpa_fixture.xml").readText()
        val activity = File("src/debug/java/com/apk/claw/android/debug/HybridRpaFixtureActivity.kt").readText()

        assertTrue(debugManifest.contains(".debug.HybridRpaFixtureActivity"))
        assertTrue(debugManifest.contains("android:exported=\"true\""))
        assertTrue(debugManifest.contains("android:permission=\"android.permission.DUMP\""))
        assertFalse(releaseManifest.contains("HybridRpaFixtureActivity"))
        assertTrue(layout.contains("@+id/native_target"))
        assertTrue(layout.contains("@+id/delayed_target"))
        assertTrue(layout.contains("@+id/reset_target"))
        assertTrue(layout.contains("@+id/result_text"))
        assertTrue(layout.split("Twin label").size >= 3)
        assertTrue(activity.contains("postDelayed"))
        assertTrue(activity.contains("700L"))
        assertTrue(activity.contains("HYBRID_RPA_CONFIGURE"))
        assertTrue(activity.contains("HYBRID_RPA_RESTORE"))
        assertTrue(activity.contains("TokenValidator.setToken"))
        assertTrue(activity.contains("ConfigServerManager.start"))
        assertTrue(activity.contains("MAX_TOKEN_LENGTH"))
        assertTrue(activity.contains("getSharedPreferences(RECOVERY_PREFS, Context.MODE_PRIVATE)"))
        assertTrue(activity.contains("KEY_ORIGINAL_SERVER_RUNNING"))
        assertTrue(activity.contains("ConfigServerManager.isRunning()"))
        assertTrue(activity.contains("HYBRID_RPA_SNAPSHOT_ONLY"))
        assertTrue(activity.contains("KVUtils.sync()"))
        assertTrue(activity.contains("storageRestored"))
        assertTrue(activity.contains(".commit()"))
        assertFalse(activity.contains("configurationSnapshotTaken"))

        val blockedVisibleWords = listOf("account", "network", "payment", "delete", "login", "publish", "privacy")
        blockedVisibleWords.forEach { word ->
            assertFalse("fixture layout must not expose $word", layout.contains(word, ignoreCase = true))
        }
    }

    @Test
    fun fixture_data_matches_active_authorized_projection() {
        val fixtureText = File(repository, "tools/fixtures/hybrid-native-run.json")
            .readText()
            .replace("__PROFILE_ID__", "000000000000000000000000")
        val fixture = JsonParser.parseString(fixtureText).asJsonObject
        val template = fixture.getAsJsonObject("templateIndex")
            .getAsJsonArray("templates")[0].asJsonObject
        val workflow = fixture.getAsJsonObject("rpaRunPayload")
            .getAsJsonObject("workflow")

        assertEquals("hybrid-native-fixture", template["id"].asString)
        assertEquals("ACTIVE", template["status"].asString)
        assertEquals("REVERSIBLE", template["riskLevel"].asString)
        assertEquals(926, template["targetVersionCode"].asInt)
        assertEquals("000000000000000000000000", template.getAsJsonObject("validationState")["profileId"].asString)
        assertEquals(1, template["revision"].asInt)
        assertEquals("hybrid-native-fixture", workflow["templateId"].asString)
        assertEquals(1, workflow["templateRevision"].asInt)
        assertEquals("000000000000000000000000", workflow["targetProfileId"].asString)
        assertEquals("TREE_PREFERRED", workflow.getAsJsonArray("steps")[0].asJsonObject["resolverPolicy"].asString)
        assertEquals(
            "native_verified",
            workflow.getAsJsonArray("steps")[0].asJsonObject
                .getAsJsonObject("postCheckpoint")
                .getAsJsonObject("requiredSelector")["text"].asString
        )

        val storeDirectory = temporaryFolder.newFolder("workflow_templates")
        File(storeDirectory, "template_index.json")
            .writeText(fixture.getAsJsonObject("templateIndex").toString())
        val stored = WorkflowTemplateStore(storeDirectory).load().single()
        val parsed = RpaWorkflowParser.parseRunRequest(
            fixture.getAsJsonObject("rpaRunPayload")
        ).workflow

        assertEquals(WorkflowTemplateManager.toHybridWorkflow(stored, parsed.params), parsed)
    }

    @Test
    fun pressure_script_hard_fails_live_core_and_redacts_tokens() {
        val script = File(repository, "tools/hybrid-rpa-emulator-pressure.ps1").readText()

        assertTrue(script.contains("MandatoryLive"))
        assertTrue(script.contains("success_rate_below_29_of_30"))
        assertTrue(script.contains("Sanitize-Record"))
        assertTrue(script.contains("Redact-Text"))
        assertTrue(script.contains("token\\s*[:=]"))
        assertTrue(script.contains("run-as"))
        assertTrue(script.contains("hybrid-rpa-pressure.json"))
        assertTrue(script.contains("ValidateRange(30, 30)"))
        assertTrue(script.contains("screenshot_live"))
        assertTrue(script.contains("pressure_report_contains_token"))
        assertTrue(script.contains("TemplateIndexTouched"))
        assertTrue(script.contains("TemplateBackupCreated"))
        assertTrue(script.contains("TemplateTransactionCreated"))
        assertTrue(script.contains("Recover-AbandonedTemplateTransaction"))
        assertTrue(script.contains("template_index_abandoned_restore_failed"))
        assertTrue(script.contains("Snapshot-FixtureConfiguration"))
        assertTrue(script.contains("fixture_configuration_restore_unconfirmed"))
        assertTrue(script.contains("Get-MandatoryLiveFailures"))
        assertTrue(script.contains("${'$'}matches.Count -ne 1"))
        assertTrue(script.contains("${'$'}rank = [Math]::Ceiling(${'$'}sorted.Count * ${'$'}Percent)"))
        assertTrue(script.contains("requiredMetricNames"))
        assertTrue(script.contains("invalidMetricContracts"))
        assertTrue(script.contains("metricToolCallMs"))
        assertTrue(script.contains("dispatchCount -le 0"))
        assertFalse(script.contains("IsPathFullyQualified"))
        assertFalse(script.contains("ConvertFrom-Json -Depth"))
        assertFalse(script.contains("set-user-rotation"))
        assertTrue(script.contains("if (-not [string]::IsNullOrEmpty(${'$'}Body))"))
        assertFalse(script.contains("uninstall"))
    }

    @Test
    fun stability_version_is_formalized_for_both_supported_variants() {
        val build = File("build.gradle.kts").readText()
        assertTrue(build.contains("versionCode = 934"))
        assertTrue(build.contains("if (android7Compat) \"6.65-stability-android7\" else \"6.65-stability\""))
    }
}
