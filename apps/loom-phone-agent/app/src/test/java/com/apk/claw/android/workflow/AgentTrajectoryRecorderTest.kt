package com.apk.claw.android.workflow

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class AgentTrajectoryRecorderTest {
    @Test
    fun runtime_tool_source_contracts_match_closed_trajectory_schemas() {
        source("impl/OpenAppTool.java").also { source ->
            assertToolParameter(source, "package_name", "string", true)
            assertToolParameter(source, "verify_foreground", "boolean", false)
            assertToolParameter(source, "check_launch_dialog", "boolean", false)
            assertToolParameter(source, "force_reopen", "boolean", false)
        }
        source("impl/SystemKeyTool.java").also { source ->
            assertToolParameter(source, "key", "string", true)
        }
        source("impl/mobile/TapTool.java").also { source ->
            assertToolParameter(source, "x", "integer", true)
            assertToolParameter(source, "y", "integer", true)
            assertTrue(source.contains("optionalLong(params, \"duration_ms\", 100)"))
        }
        source("impl/mobile/SwipeTool.java").also { source ->
            listOf("start_x", "start_y", "end_x", "end_y").forEach { assertToolParameter(source, it, "integer", true) }
            assertToolParameter(source, "duration_ms", "integer", false)
        }
        source("impl/mobile/DragTool.java").also { source ->
            listOf("start_x", "start_y", "end_x", "end_y").forEach { assertToolParameter(source, it, "integer", true) }
            assertToolParameter(source, "hold_ms", "integer", false)
            assertToolParameter(source, "duration_ms", "integer", false)
            assertTrue(source.contains("clamp(optionalLong(params, \"hold_ms\", 350), 80, 2000)"))
            assertTrue(source.contains("clamp(optionalLong(params, \"duration_ms\", 700), 120, 3000)"))
        }
        source("impl/mobile/LongPressTool.java").also { source ->
            assertToolParameter(source, "x", "integer", true)
            assertToolParameter(source, "y", "integer", true)
            assertToolParameter(source, "duration_ms", "integer", false)
        }
        source("impl/WaitTool.java").also { source ->
            assertToolParameter(source, "duration_ms", "integer", true)
            assertTrue(source.contains("duration < 0 || duration > 30000"))
        }
        source("impl/GetScreenInfoTool.java").also { assertTrue(it.contains("Collections.emptyList()")) }
        source("impl/TakeScreenshotTool.java").also { assertTrue(it.contains("Collections.emptyList()")) }
        source("impl/FinishTool.java").also { assertToolParameter(it, "summary", "string", true) }
    }

    @Test
    fun recorder_keeps_a_capped_label_and_normalized_risk_without_full_semantics() {
        val recorder = AgentTrajectoryRecorder()
        val longLabel = "a".repeat(200) + " publish"

        recorder.beforeAction(
            "tool-1", "tap", tapParams(), evidence("before"), safetyLabel = longLabel,
            riskDeclaration = TemplateRiskLevel.READ_ONLY
        )
        recorder.afterAction("tool-1", true, evidence("after"))

        val action = recorder.completed().single()
        assertEquals(200, action.safetyLabel.length)
        assertEquals(TemplateRiskLevel.SIDE_EFFECT, action.riskDeclaration)
        assertEquals("screenshot://before", action.preEvidence?.reference)
        assertEquals(TrajectoryEvidenceKind.SCREENSHOT, action.preEvidence?.kind)
    }

    @Test
    fun recorder_only_classifies_open_app_read_only_when_dialog_is_explicitly_disabled() {
        val recorder = AgentTrajectoryRecorder()

        recorder.beforeAction("tap", "tap", tapParams(), evidence("tap"))
        recorder.afterAction("tap", true, evidence("tap-after"))
        recorder.beforeAction("open-unknown", "open_app", openAppParams(), evidence("open"))
        recorder.afterAction("open-unknown", true, evidence("open-after"))
        recorder.beforeAction("open-safe", "open_app", openAppParams(checkLaunchDialog = false), evidence("safe"))
        recorder.afterAction("open-safe", true, evidence("safe-after"))

        assertEquals(TemplateRiskLevel.UNKNOWN, recorder.completed()[0].riskDeclaration)
        assertEquals(TemplateRiskLevel.UNKNOWN, recorder.completed()[1].riskDeclaration)
        assertEquals(TemplateRiskLevel.READ_ONLY, recorder.completed()[2].riskDeclaration)
    }

    @Test
    fun recorder_rejects_blank_duplicate_lifetime_and_unmatched_tool_ids() {
        val recorder = AgentTrajectoryRecorder()

        assertRejected("blank_tool_id") { recorder.beforeAction("", "tap", tapParams(), evidence("before")) }
        recorder.beforeAction("tool-1", "tap", tapParams(), evidence("before"))
        assertRejected("duplicate_tool_id") { recorder.beforeAction("tool-1", "tap", tapParams(), evidence("again")) }
        assertRejected("unmatched_tool_id") { recorder.afterAction("unknown", true, evidence("after")) }
        recorder.afterAction("tool-1", true, evidence("after"))
        assertRejected("duplicate_tool_id") { recorder.beforeAction("tool-1", "tap", tapParams(), evidence("reuse")) }
    }

    @Test
    fun recorder_exempts_non_secret_system_key_but_redacts_actual_secret_keys() {
        val recorder = AgentTrajectoryRecorder()
        recorder.beforeAction("key", "system_key", mapOf("key" to "home", "api_key" to "secret"), evidence("before"))
        recorder.afterAction("key", true, evidence("after"))

        val params = recorder.completed().single().params
        assertEquals("home", params["key"])
        assertFalse(params.containsKey("api_key"))
    }

    @Test
    fun evidence_references_require_matching_closed_kinds() {
        val valid = TrajectoryEvidenceRef("screenshot://capture-1", TrajectoryEvidenceKind.SCREENSHOT)

        assertEquals(TrajectoryEvidenceKind.SCREENSHOT, valid.kind)
        assertRejected("invalid_evidence_reference") {
            TrajectoryEvidenceRef("tree://capture-1", TrajectoryEvidenceKind.SCREENSHOT)
        }
        assertRejected("invalid_evidence_reference") { TrajectoryEvidenceRef("data:image/value", TrajectoryEvidenceKind.SCREENSHOT) }
    }

    @Test
    fun recorder_validates_then_projects_all_finish_summaries() {
        listOf(
            "done", "{serialized}", "<node className=value>", "data:image/value", "QUJDREVG R0hJ", "qujdrevgr0hj",
            "QuJdReVgR0hJ", "qujd-rev_gr0", "QUJD.REVG", "QUJD~REVG", "QUJD-REVG", "QUJD:REVG", "QUJD: REVG", "QUJD!REVG",
            "QUJDRA==!REVGSA==", "QUJDRA!REVGSAc",
            "QUJD;REVG", "QUJD,REVG", "QUJD|REVG", "QUJD".repeat(40)
        ).forEachIndexed { index, value ->
            val recorder = AgentTrajectoryRecorder()
            recorder.beforeAction("tool-$index", "finish", mapOf("summary" to value), evidence("$index"))
            assertEquals(emptyMap<String, Any?>(), recorder.pendingAction("tool-$index")?.params)
            recorder.afterAction("tool-$index", true, evidence("after-$index"))
            assertTrue(recorder.completed().isEmpty())
        }
        assertRejected("unsafe_parameter_value") {
            AgentTrajectoryRecorder().beforeAction("oversized", "finish", mapOf("summary" to "x".repeat(257)))
        }
    }

    @Test
    fun recorder_enforces_closed_runtime_tool_parameter_schemas() {
        val invalidParams = listOf(
            "open_app" to emptyMap<String, Any?>(),
            "open_app" to mapOf("package" to "com.android.settings"),
            "open_app" to mapOf("package_name" to "com.android.settings", "check_launch_dialog" to 1),
            "system_key" to mapOf("key" to "not-a-key"),
            "tap" to mapOf("x" to 1),
            "swipe" to mapOf("start_x" to 1, "start_y" to 2, "end_x" to 3, "end_y" to 4, "durationMs" to 5),
            "drag" to mapOf("start_x" to 1, "start_y" to 2, "end_x" to 3, "end_y" to 4, "hold_ms" to "80"),
            "wait" to mapOf("duration_ms" to "100"),
            "wait" to mapOf("duration_ms" to 30_001),
            "finish" to emptyMap<String, Any?>(),
            "get_screen_info" to mapOf("payload" to "plain text.")
        )

        invalidParams.forEachIndexed { index, (tool, params) ->
            assertRejected("invalid_tool_params") {
                AgentTrajectoryRecorder().beforeAction("schema-$index", tool, params, evidence("schema-$index"))
            }
        }
    }

    @Test
    fun recorder_preserves_valid_runtime_tool_parameters() {
        val actions = listOf(
            "open_app" to mapOf("package_name" to "test.demo", "check_launch_dialog" to false),
            "system_key" to mapOf("key" to "recent apps"),
            "tap" to tapParams() + ("duration_ms" to 100),
            "swipe" to mapOf("start_x" to 0, "start_y" to 1, "end_x" to 2, "end_y" to 3, "duration_ms" to 500),
            "drag" to mapOf("start_x" to 0, "start_y" to 1, "end_x" to 2, "end_y" to 3, "hold_ms" to 80, "duration_ms" to 120),
            "long_press" to mapOf("x" to 1, "y" to 2, "duration_ms" to 1000),
            "wait" to mapOf("duration_ms" to 3),
            "take_screenshot" to emptyMap<String, Any?>(),
            "get_screen_info" to emptyMap<String, Any?>(),
            "finish" to mapOf("summary" to "done"),
            "finish" to mapOf("summary" to "status: done")
        )
        val recorder = AgentTrajectoryRecorder()

        actions.forEachIndexed { index, (tool, params) ->
            recorder.beforeAction("tool-$index", tool, params, evidence("before-$index"))
            recorder.afterAction("tool-$index", true, evidence("after-$index"))
        }

        assertEquals("recent_apps", recorder.completed()[1].params["key"])
        assertEquals(
            actions.filter { (tool, _) -> tool != "finish" }.map { (_, params) -> params }.filterIndexed { index, _ -> index != 1 },
            recorder.completed().map { it.params }.filterIndexed { index, _ -> index != 1 }
        )
    }

    @Test
    fun recorder_omits_finish_then_compiles_only_the_executable_step() {
        val recorder = AgentTrajectoryRecorder()
        recorder.beforeAction(
            "open", "open_app", openAppParams(checkLaunchDialog = false), evidence("open-before")
        )
        recorder.afterAction("open", true, evidence("open-after"))
        recorder.beforeAction("finish", "finish", mapOf("summary" to "done"), evidence("finish-before"))
        recorder.afterAction("finish", true, evidence("finish-after"))

        val actions = recorder.completed()
        assertEquals(listOf("open_app"), actions.map { it.toolName })
        assertTrue(actions.none { it.toolName == "finish" || it.params.containsKey("summary") })

        val result = HybridTemplateCompiler.compile("open settings", "Settings", actions, "emulator-profile")
        assertTrue(result is CompileResult.Compiled)
        val template = (result as CompileResult.Compiled).template
        assertEquals(TemplateStatus.DRAFT, template.status)
        assertEquals(listOf("open_app"), template.steps.map { it.toolName })
    }

    @Test
    fun finish_only_recorded_trajectory_is_ineligible_without_a_retained_action() {
        val recorder = AgentTrajectoryRecorder()
        recorder.beforeAction("finish", "finish", mapOf("summary" to "done"), evidence("finish-before"))
        recorder.afterAction("finish", true, evidence("finish-after"))

        assertTrue(recorder.completed().isEmpty())
        assertEquals(
            CompileResult.Ineligible("empty_trajectory"),
            HybridTemplateCompiler.compile("finish", "Settings", recorder.completed(), "emulator-profile")
        )
    }

    @Test
    fun recorder_enforces_json_type_depth_size_and_cycle_limits() {
        val cyclic = mutableMapOf<String, Any?>()
        cyclic["self"] = cyclic
        var deep: Any? = "leaf"
        repeat(9) { deep = listOf(deep) }
        val oversized = List(65) { it }

        listOf<Any?>(cyclic, deep, oversized, CustomNumber(), Double.NaN, Float.POSITIVE_INFINITY).forEachIndexed { index, value ->
            assertRejected("unsafe_parameter_value") {
                AgentTrajectoryRecorder().beforeAction("tool-$index", "tap", tapParams() + ("x" to value), evidence("limit-$index"))
            }
        }
    }

    @Test
    fun invalid_before_metadata_never_enters_pending_state_and_invalid_after_metadata_preserves_it() {
        val invalidBefore = AgentTrajectoryRecorder()
        assertRejected("invalid_action_metadata") {
            invalidBefore.beforeAction("bad", "tap", tapParams(), safetyLabel = "x".repeat(4097))
        }
        assertNull(invalidBefore.pendingAction("bad"))
        assertTrue(invalidBefore.completed().isEmpty())

        val recorder = AgentTrajectoryRecorder()
        recorder.beforeAction("pending", "tap", tapParams(), evidence("before"))
        assertRejected("invalid_checkpoint") {
            recorder.afterAction("pending", true, postCheckpoint = StepCheckpoint(perceptualHash = "?".repeat(129)))
        }
        assertTrue(recorder.pendingAction("pending") != null)
        assertTrue(recorder.completed().isEmpty())
        recorder.afterAction("pending", true, evidence("after"))
        assertEquals(1, recorder.completed().size)
    }

    private fun source(relativePath: String): String =
        File("src/main/java/com/apk/claw/android/tool/$relativePath").readText()

    private fun assertToolParameter(source: String, name: String, type: String, required: Boolean) {
        val start = source.indexOf("\"$name\"")
        assertTrue("Missing ToolParameter name: $name", start >= 0)
        val parameterStart = source.lastIndexOf("new ToolParameter", start)
        val nextParameter = source.indexOf("new ToolParameter", start + name.length)
        val declaration = source.substring(parameterStart, if (nextParameter == -1) source.length else nextParameter)
        assertTrue("Wrong ToolParameter type for $name", declaration.contains("\"$type\""))
        assertTrue("Wrong ToolParameter required flag for $name", Regex(",\\s*$required\\s*\\)").containsMatchIn(declaration))
    }

    private fun openAppParams(checkLaunchDialog: Boolean? = null): Map<String, Any?> = buildMap {
        put("package_name", "com.android.settings")
        checkLaunchDialog?.let { put("check_launch_dialog", it) }
    }

    private fun tapParams(): Map<String, Any?> = mapOf("x" to 1, "y" to 2)

    private fun evidence(reference: String) = TrajectoryEvidenceRef(
        "screenshot://$reference", TrajectoryEvidenceKind.SCREENSHOT
    )

    private fun assertRejected(reason: String, block: () -> Unit) {
        try {
            block()
            fail("Expected rejection: $reason")
        } catch (error: IllegalArgumentException) {
            assertEquals(reason, error.message)
        }
    }

    @Suppress("OVERRIDE_DEPRECATION")
    private class CustomNumber : Number() {
        override fun toByte() = 0.toByte()
        override fun toChar() = 0.toChar()
        override fun toDouble() = 0.0
        override fun toFloat() = 0f
        override fun toInt() = 0
        override fun toLong() = 0L
        override fun toShort() = 0.toShort()
    }
}
