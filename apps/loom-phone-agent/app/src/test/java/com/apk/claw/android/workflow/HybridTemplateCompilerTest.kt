package com.apk.claw.android.workflow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridTemplateCompilerTest {
    @Test
    fun explicitly_read_only_navigation_compiles_to_a_draft() {
        val result = HybridTemplateCompiler.compile(
            "open settings and enter network",
            "Settings",
            listOf(tap("tap-1", SemanticSelector(resourceId = "android:id/title"))),
            "emulator-profile"
        )

        assertTrue(result is CompileResult.Compiled)
        val template = (result as CompileResult.Compiled).template
        assertEquals(TemplateStatus.DRAFT, template.status)
        assertEquals(ResolverPolicy.TREE_PREFERRED, template.steps.single().resolverPolicy)
        assertFalse(template.steps.single().validatedResolvers.isNotEmpty())
    }

    @Test
    fun compiler_requires_explicit_read_only_risk_for_gestures() {
        val result = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(TrajectoryAction("tap-1", "tap", mapOf("x" to 1, "y" to 2), true, safetyLabel = "Network")),
            "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("risk_declaration_required"), result)
    }

    @Test
    fun compiler_rejects_open_app_that_can_dismiss_a_launch_dialog() {
        val omitted = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(openApp("open", mapOf("package_name" to "com.android.settings"))),
            "emulator-profile"
        )
        val enabled = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(openApp("open", mapOf("package_name" to "com.android.settings", "check_launch_dialog" to true))),
            "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("open_app_launch_dialog_agent_only"), omitted)
        assertEquals(CompileResult.Ineligible("open_app_launch_dialog_agent_only"), enabled)
    }

    @Test
    fun compiler_rejects_blank_and_duplicate_direct_action_ids() {
        val blank = HybridTemplateCompiler.compile(
            "open settings", "Settings", listOf(openApp("")), "emulator-profile"
        )
        val duplicate = HybridTemplateCompiler.compile(
            "open settings", "Settings", listOf(openApp("open"), openApp("open")), "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("blank_tool_id"), blank)
        assertEquals(CompileResult.Ineligible("duplicate_tool_id"), duplicate)
    }

    @Test
    fun compiler_rejects_blank_profile_empty_and_observation_only_trajectories() {
        val blankProfile = HybridTemplateCompiler.compile("open", "Settings", listOf(openApp("open")), " ")
        val empty = HybridTemplateCompiler.compile("open", "Settings", emptyList(), "emulator-profile")
        val observation = HybridTemplateCompiler.compile(
            "open",
            "Settings",
            listOf(TrajectoryAction("screen", "take_screenshot", emptyMap(), true, riskDeclaration = TemplateRiskLevel.READ_ONLY)),
            "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("blank_profile_id"), blankProfile)
        assertEquals(CompileResult.Ineligible("empty_trajectory"), empty)
        assertEquals(CompileResult.Ineligible("no_executable_actions"), observation)
    }

    @Test
    fun compiler_validates_and_projects_finish_summary_from_direct_input() {
        val result = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(
                openApp("open"),
                TrajectoryAction(
                    "finish", "finish", mapOf("summary" to "QUJDRA==!REVGSA=="), true,
                    riskDeclaration = TemplateRiskLevel.READ_ONLY
                )
            ),
            "emulator-profile"
        )
        val missingSummary = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(openApp("open"), TrajectoryAction("finish", "finish", emptyMap(), true, riskDeclaration = TemplateRiskLevel.READ_ONLY)),
            "emulator-profile"
        )
        val malformedSummary = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(
                openApp("open"),
                TrajectoryAction(
                    "finish", "finish", mapOf("summary" to listOf("not", "a", "string")), true,
                    riskDeclaration = TemplateRiskLevel.READ_ONLY
                )
            ),
            "emulator-profile"
        )

        assertTrue(result is CompileResult.Compiled)
        val template = (result as CompileResult.Compiled).template
        assertEquals(listOf("open_app"), template.steps.map { it.toolName })
        assertFalse(template.steps.any { it.paramsTemplate.containsKey("summary") })
        assertEquals(CompileResult.Ineligible("invalid_tool_params"), missingSummary)
        assertEquals(CompileResult.Ineligible("invalid_tool_params"), malformedSummary)
    }

    @Test
    fun compiler_uses_only_production_safe_tree_resolvers() {
        val resource = compiledStep(tap("resource", SemanticSelector(resourceId = "id/network")))
        val description = compiledStep(tap("description", SemanticSelector(contentDescription = "Network")))
        val text = compiledStep(tap("text", SemanticSelector(text = "Network")))
        val className = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(tap("class", SemanticSelector(className = "Button"))), "emulator-profile"
        )
        val packageName = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(tap("package", SemanticSelector(packageName = "settings"))), "emulator-profile"
        )
        val structural = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(tap("structural", SemanticSelector(structuralPath = listOf(0, 1)))), "emulator-profile"
        )

        assertEquals(setOf(ResolverKind.RESOURCE_ID), resource.allowedResolvers)
        assertEquals(setOf(ResolverKind.CONTENT_DESCRIPTION), description.allowedResolvers)
        assertEquals(setOf(ResolverKind.TEXT_CLASS), text.allowedResolvers)
        assertEquals(CompileResult.Ineligible("empty_tree_resolver_set"), className)
        assertEquals(CompileResult.Ineligible("empty_tree_resolver_set"), packageName)
        assertEquals(CompileResult.Ineligible("empty_tree_resolver_set"), structural)
    }

    @Test
    fun compiler_rejects_system_key_swipe_and_drag_without_production_adapters() {
        fun action(tool: String, params: Map<String, Any?>, anchor: VisualAnchorSpec? = null) = TrajectoryAction(
            tool,
            tool,
            params,
            true,
            riskDeclaration = TemplateRiskLevel.READ_ONLY,
            visualAnchor = anchor
        )
        val systemKey = HybridTemplateCompiler.compile(
            "back", "Settings", listOf(action("system_key", mapOf("key" to "back"))), "emulator-profile"
        )
        val swipe = HybridTemplateCompiler.compile(
            "swipe", "Settings",
            listOf(action("swipe", mapOf("start_x" to 1, "start_y" to 1, "end_x" to 2, "end_y" to 2), validAnchor())),
            "emulator-profile"
        )
        val drag = HybridTemplateCompiler.compile(
            "drag", "Settings",
            listOf(action("drag", mapOf("start_x" to 1, "start_y" to 1, "end_x" to 2, "end_y" to 2), validAnchor())),
            "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("production_adapter_unavailable"), systemKey)
        assertEquals(CompileResult.Ineligible("production_adapter_unavailable"), swipe)
        assertEquals(CompileResult.Ineligible("production_adapter_unavailable"), drag)
    }

    @Test
    fun compiler_uses_vision_only_when_anchor_is_the_only_evidence() {
        val result = HybridTemplateCompiler.compile(
            "open settings",
            "Settings",
            listOf(
                TrajectoryAction(
                    "tap-1",
                    "tap",
                    mapOf("x" to 1, "y" to 2),
                    true,
                    safetyLabel = "Network",
                    riskDeclaration = TemplateRiskLevel.READ_ONLY,
                    visualAnchor = validAnchor()
                )
            ),
            "emulator-profile"
        )

        val step = (result as CompileResult.Compiled).template.steps.single()
        assertEquals(ResolverPolicy.VISION_REQUIRED, step.resolverPolicy)
        assertEquals(setOf(ResolverKind.VISUAL_ANCHOR), step.allowedResolvers)
    }

    @Test
    fun compiler_allows_only_anchor_backed_long_press_and_rejects_coordinate_only_tap() {
        val longPress = HybridTemplateCompiler.compile(
            "hold network",
            "Settings",
            listOf(
                TrajectoryAction(
                    "hold-1",
                    "long_press",
                    mapOf("x" to 1, "y" to 2, "duration_ms" to 800),
                    true,
                    riskDeclaration = TemplateRiskLevel.READ_ONLY,
                    semanticSelector = SemanticSelector(text = "Network"),
                    visualAnchor = validAnchor()
                )
            ),
            "emulator-profile"
        )
        val coordinateOnly = HybridTemplateCompiler.compile(
            "tap network",
            "Settings",
            listOf(
                TrajectoryAction(
                    "tap-1",
                    "tap",
                    mapOf("x" to 1, "y" to 2),
                    true,
                    riskDeclaration = TemplateRiskLevel.READ_ONLY
                )
            ),
            "emulator-profile"
        )

        val step = (longPress as CompileResult.Compiled).template.steps.single()
        assertEquals(ResolverPolicy.VISION_REQUIRED, step.resolverPolicy)
        assertEquals(setOf(ResolverKind.VISUAL_ANCHOR), step.allowedResolvers)
        assertEquals(CompileResult.Ineligible("production_adapter_unavailable"), coordinateOnly)
    }

    @Test
    fun compiler_rejects_invalid_evidence_and_unsafe_params() {
        val blankSelector = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(tap("blank", SemanticSelector(resourceId = " "))), "emulator-profile"
        )
        val invalidAnchor = HybridTemplateCompiler.compile(
            "open",
            "Settings",
            listOf(tap("anchor", null, VisualAnchorSpec("", NormalizedRect(0f, 0f, 1f, 1f), 0.5f, 0.5f))),
            "emulator-profile"
        )
        val unsafeParams = HybridTemplateCompiler.compile(
            "open",
            "Settings",
            listOf(openApp("open", mapOf("payload" to "{serialized}"))),
            "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("invalid_semantic_selector"), blankSelector)
        assertEquals(CompileResult.Ineligible("invalid_visual_anchor"), invalidAnchor)
        assertEquals(CompileResult.Ineligible("unsafe_parameter_value"), unsafeParams)
    }

    @Test
    fun compiler_revalidates_direct_metadata_checkpoints_anchors_and_tool_params() {
        val longLabel = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(openApp("open").copy(safetyLabel = "x".repeat(201))), "emulator-profile"
        )
        val longPrompt = HybridTemplateCompiler.compile(
            "x".repeat(201), "Settings", listOf(openApp("open")), "emulator-profile"
        )
        val longAppName = HybridTemplateCompiler.compile(
            "open", "x".repeat(129), listOf(openApp("open")), "emulator-profile"
        )
        val longSelector = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(tap("tap", SemanticSelector(resourceId = "x".repeat(129)))), "emulator-profile"
        )
        val invalidCheckpoint = HybridTemplateCompiler.compile(
            "open",
            "Settings",
            listOf(openApp("open").copy(preCheckpoint = StepCheckpoint(perceptualHash = "?".repeat(129)))),
            "emulator-profile"
        )
        val invalidVariants = HybridTemplateCompiler.compile(
            "open",
            "Settings",
            listOf(tap("tap", null, validAnchor().copy(scaleVariants = List(9) { 1f }))),
            "emulator-profile"
        )
        val unknownParam = HybridTemplateCompiler.compile(
            "open", "Settings", listOf(openApp("open", mapOf("payload" to "plain text."))), "emulator-profile"
        )

        assertEquals(CompileResult.Ineligible("invalid_action_metadata"), longLabel)
        assertEquals(CompileResult.Ineligible("invalid_compile_metadata"), longPrompt)
        assertEquals(CompileResult.Ineligible("invalid_compile_metadata"), longAppName)
        assertEquals(CompileResult.Ineligible("invalid_semantic_selector"), longSelector)
        assertEquals(CompileResult.Ineligible("invalid_checkpoint"), invalidCheckpoint)
        assertEquals(CompileResult.Ineligible("invalid_visual_anchor"), invalidVariants)
        assertEquals(CompileResult.Ineligible("invalid_tool_params"), unknownParam)
    }

    private fun compiledStep(action: TrajectoryAction): WorkflowTemplate.WorkflowStep =
        (HybridTemplateCompiler.compile("open", "Settings", listOf(action), "emulator-profile") as CompileResult.Compiled)
            .template.steps.single()

    private fun tap(
        id: String,
        selector: SemanticSelector?,
        anchor: VisualAnchorSpec? = null
    ) = TrajectoryAction(
        id,
        "tap",
        mapOf("x" to 1, "y" to 2),
        true,
        safetyLabel = "Network",
        riskDeclaration = TemplateRiskLevel.READ_ONLY,
        semanticSelector = selector,
        visualAnchor = anchor
    )

    private fun openApp(
        id: String,
        params: Map<String, Any?> = mapOf("package_name" to "com.android.settings", "check_launch_dialog" to false)
    ) = TrajectoryAction(
        id,
        "open_app",
        params,
        true,
        riskDeclaration = TemplateRiskLevel.READ_ONLY
    )

    private fun validAnchor() = VisualAnchorSpec(
        "network-anchor",
        NormalizedRect(0f, 0f, 1f, 1f),
        0.5f,
        0.5f
    )
}
