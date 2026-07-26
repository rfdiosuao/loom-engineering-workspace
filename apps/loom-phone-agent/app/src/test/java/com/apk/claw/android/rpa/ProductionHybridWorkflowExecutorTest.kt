package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.ValidationState
import com.apk.claw.android.workflow.VisualAnchorSpec
import com.apk.claw.android.workflow.WorkflowTemplate
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.workflow.WorkflowTemplateStore
import com.google.gson.JsonParser
import java.io.File
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ProductionHybridWorkflowExecutorTest {
    @get:Rule
    val temporary = TemporaryFolder()

    @After
    fun clearInstalledEngine() {
        RpaWorkflowRunner.installHybridEngine(null)
    }

    @Test
    fun installation_is_lazy_independent_of_llm_and_does_not_claim_accessibility_readiness() {
        var providerCalls = 0
        HybridRuntimeInstaller.install(
            filesDirectory = temporary.newFolder("install-files"),
            apiLevel = 30,
            serviceProvider = ProductionPlatformServiceProvider {
                providerCalls += 1
                null
            }
        )

        assertTrue(RpaWorkflowRunner.isHybridEngineInstalled())
        assertFalse(RpaWorkflowRunner.isAccessibilityReady())
        assertEquals(0, providerCalls)

        val source = source("ClawApplication.kt")
        val kvInit = source.indexOf("KVUtils.init(this)")
        val tools = source.indexOf("registerAllTools")
        val install = source.indexOf("HybridRuntimeInstaller.install(this)")
        val llmRead = source.indexOf("KVUtils.hasLlmConfig()")
        assertTrue(kvInit >= 0)
        assertTrue(tools > kvInit)
        assertTrue(install > tools)
        assertTrue(llmRead > install)
    }

    @Test
    fun installation_failure_is_contained_and_leaves_runtime_unavailable() {
        RpaWorkflowRunner.installHybridEngine(object : HybridWorkflowExecutor {
            override fun run(
                workflow: RpaWorkflow,
                runId: String,
                resumeFrom: AgentHandoffContext?,
                cancelled: () -> Boolean,
                deadlineAt: Long
            ) = HybridRunResult(true, emptyList(), outcomeState = "verified", dispatchCount = 0, rounds = 0)
        })

        val installed = HybridRuntimeInstaller.installSafely {
            throw java.io.IOException("storage unavailable")
        }

        assertFalse(installed)
        assertFalse(RpaWorkflowRunner.isHybridEngineInstalled())
    }

    @Test
    fun production_authorization_binds_execution_to_stored_active_template_and_exact_projection() {
        val filesDirectory = temporary.newFolder("authorized-files")
        val templateRoot = File(filesDirectory, "workflow_templates")
        val active = activeTemplate()
        WorkflowTemplateStore(templateRoot).save(listOf(active))
        val expected = WorkflowTemplateManager.toHybridWorkflow(active)
        var providerCalls = 0
        val service = FakePlatformService()
        val executor = ProductionHybridWorkflowExecutor(
            filesDirectory = filesDirectory,
            apiLevel = 30,
            serviceProvider = ProductionPlatformServiceProvider {
                providerCalls += 1
                service
            }
        )

        val forged = executor.run(
            expected.copy(steps = listOf(directStep(action = "back"))),
            "forged-run",
            deadlineAt = Long.MAX_VALUE
        )
        val unknown = executor.run(
            expected.copy(templateId = "unknown-template"),
            "unknown-run",
            deadlineAt = Long.MAX_VALUE
        )
        val exact = executor.run(expected, "authorized-run", deadlineAt = Long.MAX_VALUE)

        assertEquals("template_not_authorized", forged.errorCode)
        assertEquals("template_not_authorized", unknown.errorCode)
        assertFalse(forged.templateAuthorized)
        assertFalse(unknown.templateAuthorized)
        assertEquals(0, forged.dispatchCount + unknown.dispatchCount)
        assertTrue(exact.success)
        assertTrue(exact.templateAuthorized)
        assertTrue(providerCalls > 0)
        assertEquals(1, service.platformCalls)
    }

    @Test
    fun production_validation_requires_exact_stored_validatable_revision() {
        val filesDirectory = temporary.newFolder("validation-files")
        val draft = activeTemplate().copy(
            status = TemplateStatus.VALIDATING,
            activatedAt = 0L,
            validationState = activeTemplate().validationState.copy(consecutiveSuccesses = 2)
        )
        WorkflowTemplateStore(File(filesDirectory, "workflow_templates")).save(listOf(draft))
        val workflow = WorkflowTemplateManager.toHybridWorkflow(draft)
        val service = FakePlatformService()
        val executor = ProductionHybridWorkflowExecutor(
            filesDirectory = filesDirectory,
            apiLevel = 30,
            serviceProvider = ProductionPlatformServiceProvider { service }
        )

        val ordinaryRun = executor.run(workflow, "draft-run", deadlineAt = Long.MAX_VALUE)
        val validation = executor.runValidation(workflow, "validation-run", deadlineAt = Long.MAX_VALUE)
        val wrongRevision = executor.runValidation(
            workflow.copy(templateRevision = 2),
            "wrong-validation-run",
            deadlineAt = Long.MAX_VALUE
        )

        assertEquals("template_not_authorized", ordinaryRun.errorCode)
        assertTrue(validation.success)
        assertTrue(validation.templateAuthorized)
        assertEquals("template_not_authorized", wrongRevision.errorCode)
        assertEquals(1, service.platformCalls)
    }

    @Test
    fun invalid_template_namespace_is_blocked_before_service_or_asset_access() {
        var providerCalls = 0
        val reader = RecordingAssetReader()
        val executor = executor(
            temporary.newFolder("invalid-files"),
            apiLevel = 30,
            provider = ProductionPlatformServiceProvider {
                providerCalls += 1
                FakePlatformService()
            },
            reader = reader
        )

        val blank = executor.run(
            workflow(directStep(), templateId = ""),
            "invalid-template-run",
            deadlineAt = Long.MAX_VALUE
        )
        val revision = executor.run(
            workflow(directStep(), revision = 0),
            "invalid-revision-run",
            deadlineAt = Long.MAX_VALUE
        )

        assertEquals("blocked", blank.outcomeState)
        assertEquals("blocked", revision.outcomeState)
        assertEquals(0, blank.dispatchCount + revision.dispatchCount)
        assertEquals(0, providerCalls)
        assertTrue(reader.calls.isEmpty())
    }

    @Test
    fun factory_shared_ledger_recovers_dispatching_as_uncertain_without_second_platform_call() {
        val filesDirectory = temporary.newFolder("restart-files")
        val runId = "run-restart"
        val service = FakePlatformService()
        val store = ActionLedgerStore(File(filesDirectory, "workflow_templates"))
        val preparedAction = PreparedAction(
            runId,
            "step-1",
            1,
            7L,
            "service-1",
            ResolverKind.DIRECT,
            DirectPayload(DirectAction.BACK, evidence = service.evidence(FreshnessRequirement.ReadOnly))
        )
        val prepared = preparedAction.toLedgerEntry(1L)
        store.prepare(prepared)
        val dispatching = prepared.copy(
            state = ActionLedgerState.DISPATCHING,
            dispatchedAt = 2L
        )
        store.compareAndTransition(
            ActionIdentity(runId, "step-1", 1),
            ActionLedgerState.PREPARED,
            dispatching
        )
        store.compareAndTransition(
            ActionIdentity(runId, "step-1", 1),
            ActionLedgerState.DISPATCHING,
            dispatching.copy(dispatchInvoked = true)
        )
        val executor = executor(filesDirectory, 30, ProductionPlatformServiceProvider { service })

        val result = executor.run(directWorkflow(), runId, deadlineAt = Long.MAX_VALUE)

        assertEquals("uncertain", result.outcomeState)
        assertEquals(ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH, result.errorCode)
        assertEquals(0, service.platformCalls)
        assertEquals(
            ActionLedgerState.UNCERTAIN,
            store.load(ActionIdentity(runId, "step-1", 1))!!.state
        )
    }

    @Test
    fun api24_supports_semantic_and_direct_paths_with_fresh_stamped_verification() {
        val service = FakePlatformService()
        val executor = executor(
            temporary.newFolder("api24-tree-files"),
            24,
            ProductionPlatformServiceProvider { service }
        )

        val semantic = executor.run(
            workflow(semanticStep()),
            "api24-semantic-run",
            deadlineAt = Long.MAX_VALUE
        )
        val direct = executor.run(
            workflow(directStep()),
            "api24-direct-run",
            deadlineAt = Long.MAX_VALUE
        )

        assertTrue(semantic.success)
        assertTrue(direct.success)
        assertEquals("verified", semantic.outcomeState)
        assertEquals("verified", direct.outcomeState)
        assertEquals(2, service.platformCalls)
    }

    @Test
    fun api30_visual_uses_exact_template_revision_without_namespace_fallback() {
        val service = FakePlatformService()
        val reader = RecordingAssetReader("template-1", 3)
        val executor = executor(
            temporary.newFolder("visual-files"),
            30,
            ProductionPlatformServiceProvider { service },
            reader
        )

        val exact = executor.run(
            workflow(visualStep(), revision = 3),
            "visual-exact-run",
            deadlineAt = Long.MAX_VALUE
        )
        val wrongRevision = executor.run(
            workflow(visualStep(), revision = 4),
            "visual-wrong-revision-run",
            deadlineAt = Long.MAX_VALUE
        )

        assertTrue(exact.success)
        assertEquals("verified", exact.outcomeState)
        assertFalse(wrongRevision.success)
        assertTrue(wrongRevision.agentHandoffRequired)
        assertEquals(1, exact.dispatchCount)
        assertEquals(0, wrongRevision.dispatchCount)
        assertEquals(
            listOf(
                AssetRead("template-1", 3, "anchor.webp"),
                AssetRead("template-1", 4, "anchor.webp")
            ),
            reader.calls
        )
        assertEquals(1, service.platformCalls)
    }

    @Test
    fun api24_visual_is_typed_unsupported_before_asset_or_platform_access() {
        val service = FakePlatformService()
        val reader = RecordingAssetReader("template-1", 1)
        val executor = executor(
            temporary.newFolder("api24-visual-files"),
            24,
            ProductionPlatformServiceProvider { service },
            reader
        )

        val result = executor.run(
            workflow(visualStep()),
            "api24-visual-run",
            deadlineAt = Long.MAX_VALUE
        )

        assertFalse(result.success)
        assertTrue(result.agentHandoffRequired)
        assertEquals("visual_capture_unsupported", result.errorCode)
        assertEquals(0, result.dispatchCount)
        assertEquals(0, service.platformCalls)
        assertTrue(reader.calls.isEmpty())
    }

    @Test
    fun structural_normalized_swipe_drag_and_dangerous_actions_handoff_with_zero_platform_calls() {
        val service = FakePlatformService()
        val executor = executor(
            temporary.newFolder("closed-files"),
            apiLevel = 30,
            provider = ProductionPlatformServiceProvider { service },
            reader = RecordingAssetReader("template-1", 1)
        )
        val workflows = listOf(
            workflow(structuralStep()),
            workflow(normalizedStep()),
            workflow(visualMotionStep("swipe_normalized")),
            workflow(visualMotionStep("drag_normalized")),
            workflow(directStep(action = "back", description = "delete account")),
            workflow(dangerousSemanticStep())
        )

        val results = workflows.mapIndexed { index, item ->
            executor.run(item, "closed-run-$index", deadlineAt = Long.MAX_VALUE)
        }

        assertTrue(results.all { !it.success && it.agentHandoffRequired })
        assertTrue(results.all { it.dispatchCount == 0 })
        assertEquals(0, service.platformCalls)
    }

    private fun executor(
        filesDirectory: File,
        apiLevel: Int,
        provider: ProductionPlatformServiceProvider,
        reader: VisualAssetReader? = null
    ) = ProductionHybridWorkflowExecutor(
        filesDirectory = filesDirectory,
        apiLevel = apiLevel,
        serviceProvider = provider,
        visualAssetReader = reader,
        visualDecoder = VisualAssetDecoder {
            LumaPlane(2, 2, intArrayOf(20, 220, 20, 220))
        },
        templateAuthorizer = ProductionTemplateAuthorizer.allowAll()
    )

    private fun directWorkflow() = workflow(directStep(action = "back"))

    private fun directStep(
        action: String = "open_app",
        description: String = ""
    ) = RpaStep(
        "step-1",
        action,
        params = if (action == "open_app") mapOf("package_name" to "demo.app") else emptyMap(),
        description = description,
        resolverPolicy = ResolverPolicy.DIRECT,
        allowedResolvers = setOf(ResolverKind.DIRECT),
        validatedResolvers = setOf(ResolverKind.DIRECT),
        resolverPolicyExplicit = true
    )

    private fun semanticStep() = RpaStep(
        "step-1",
        "tap_semantic",
        resolverPolicy = ResolverPolicy.TREE_PREFERRED,
        allowedResolvers = setOf(ResolverKind.RESOURCE_ID),
        validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
        semanticSelector = SemanticSelector(resourceId = "demo:id/target", packageName = "demo.app"),
        postCheckpoint = StepCheckpoint(expectedPackage = "demo.app"),
        resolverPolicyExplicit = true
    )

    private fun dangerousSemanticStep() = semanticStep().copy(
        semanticSelector = SemanticSelector(
            resourceId = "demo:id/delete_account",
            packageName = "demo.app"
        )
    )

    private fun visualStep() = RpaStep(
        "step-1",
        "tap_anchor",
        resolverPolicy = ResolverPolicy.VISION_REQUIRED,
        allowedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        validatedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        visualAnchor = visualAnchor(),
        postCheckpoint = StepCheckpoint(expectedPackage = "demo.app"),
        resolverPolicyExplicit = true
    )

    private fun structuralStep() = RpaStep(
        "step-1",
        "tap_semantic",
        resolverPolicy = ResolverPolicy.TREE_PREFERRED,
        allowedResolvers = setOf(ResolverKind.STRUCTURAL),
        validatedResolvers = setOf(ResolverKind.STRUCTURAL),
        semanticSelector = SemanticSelector(structuralPath = listOf(0, 1)),
        resolverPolicyExplicit = true
    )

    private fun normalizedStep() = RpaStep(
        "step-1",
        "tap_normalized",
        resolverPolicy = ResolverPolicy.TREE_PREFERRED,
        allowedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
        validatedResolvers = setOf(ResolverKind.RESOURCE_ID, ResolverKind.NORMALIZED_COORDINATE),
        semanticSelector = SemanticSelector(resourceId = "missing:id/target"),
        preCheckpoint = coordinateCheckpoint(),
        resolverPolicyExplicit = true
    )

    private fun visualMotionStep(action: String) = RpaStep(
        "step-1",
        action,
        resolverPolicy = ResolverPolicy.VISION_REQUIRED,
        allowedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        validatedResolvers = setOf(ResolverKind.VISUAL_ANCHOR),
        visualAnchor = visualAnchor(),
        resolverPolicyExplicit = true
    )

    private fun visualAnchor() = VisualAnchorSpec(
        "anchor.webp",
        NormalizedRect(0f, 0f, 1f, 1f),
        0.5f,
        0.5f,
        minimumConfidence = 0.99f,
        scaleVariants = listOf(1f)
    )

    private fun coordinateCheckpoint() = StepCheckpoint(
        expectedPackage = "demo.app",
        perceptualHash = "pf2:${"0".repeat(64)}:80:10:0000000000000000",
        expectedWindowId = 3,
        expectedDisplayTransform = DisplayTransformCheckpoint(0, 20, 20, 20, 20, 0, 420, 0, 0, 0, 0)
    )

    private fun workflow(
        step: RpaStep,
        templateId: String = "template-1",
        revision: Int = 1
    ) = RpaWorkflow(
        id = "workflow-1",
        name = "workflow",
        steps = listOf(step),
        schemaVersion = 2,
        executionMode = HYBRID_EXECUTION_MODE,
        templateId = templateId,
        templateRevision = revision,
        targetProfileId = "profile-1"
    )

    private fun activeTemplate() = WorkflowTemplate(
        id = "template-1",
        name = "workflow",
        description = "safe active template",
        taskPattern = "open demo",
        keywords = listOf("open", "demo"),
        appName = "Demo",
        steps = listOf(
            WorkflowTemplate.WorkflowStep(
                toolName = "open_app",
                paramsTemplate = mapOf("package_name" to "demo.app"),
                description = "open demo",
                waitFor = 0,
                resolverPolicy = ResolverPolicy.DIRECT,
                allowedResolvers = setOf(ResolverKind.DIRECT),
                validatedResolvers = setOf(ResolverKind.DIRECT)
            )
        ),
        createdAt = 1L,
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        status = TemplateStatus.ACTIVE,
        riskLevel = TemplateRiskLevel.READ_ONLY,
        validationState = ValidationState(
            profileId = "profile-1",
            consecutiveSuccesses = 3,
            validatedResolvers = setOf(ResolverKind.DIRECT),
            validatedResetIds = setOf("reset-a", "reset-b"),
            validatedRevision = 1
        ),
        revision = 1,
        targetPackage = "demo.app",
        targetProfileId = "profile-1",
        activatedAt = 2L
    )

    private fun source(name: String): String {
        val direct = File("src/main/java/com/apk/claw/android/$name")
        return (if (direct.exists()) direct else File("app/src/main/java/com/apk/claw/android/$name")).readText()
    }

    private data class AssetRead(val templateId: String, val revision: Int, val assetName: String)

    private class RecordingAssetReader(
        private val availableTemplateId: String? = null,
        private val availableRevision: Int? = null
    ) : VisualAssetReader {
        val calls = mutableListOf<AssetRead>()

        override fun read(templateId: String, revision: Int, assetName: String): ByteArray? {
            calls += AssetRead(templateId, revision, assetName)
            return if (templateId == availableTemplateId && revision == availableRevision) {
                byteArrayOf(1, 2, 3)
            } else {
                null
            }
        }
    }

    private class FakePlatformService : ProductionPlatformService {
        override val identity: Any = Any()
        var platformCalls = 0
        var captures = 0

        override fun generationSnapshot() = GenerationSnapshot(7L, "service-1")

        override fun capture(requirement: FreshnessRequirement): UiEvidence = evidence(requirement)

        fun evidence(requirement: FreshnessRequirement): UiEvidence {
            captures += 1
            val after = (requirement as? FreshnessRequirement.AuthorizeAfter)?.capturedAfter
                ?: System.currentTimeMillis()
            val nodes = """{
              "currentPackage":"demo.app",
              "metrics":{"uiGeneration":7,"serviceGeneration":"service-1"},
              "keyNodes":[{
                "ref":"node-1","resourceId":"demo:id/target","description":"Target","text":"Target",
                "className":"android.widget.Button","packageName":"demo.app","visible":true,
                "enabled":true,"clickable":true,"bounds":{"left":1,"top":1,"right":3,"bottom":3}
              }]
            }"""
            return UiEvidence(
                7L,
                "service-1",
                "demo.app",
                3,
                after + 2L,
                DisplayTransform(0, 20, 20, 20, 20, 0, 420, 0, 0, 0, 0),
                JsonParser.parseString(nodes).asJsonObject,
                "frame-$captures",
                "fresh",
                after + 1L,
                1L,
                LumaPlane(20, 20, IntArray(400) { if (it % 2 == 0) 20 else 220 }),
                identity
            )
        }

        override fun dispatchSemantic(
            resolution: SemanticResolution.Unique,
            expectedGeneration: Long
        ): DispatchResult {
            platformCalls += 1
            return DispatchResult(true, dispatchedAt = System.currentTimeMillis())
        }

        override fun performTap(x: Int, y: Int): Boolean {
            platformCalls += 1
            return true
        }

        override fun performLongPress(x: Int, y: Int, durationMs: Long): Boolean {
            platformCalls += 1
            return true
        }

        override fun openApp(packageName: String): Boolean {
            platformCalls += 1
            return true
        }

        override fun pressBack(): Boolean {
            platformCalls += 1
            return true
        }

        override fun pressHome(): Boolean {
            platformCalls += 1
            return true
        }

        override fun currentPackageName(): String = "demo.app"
    }
}
