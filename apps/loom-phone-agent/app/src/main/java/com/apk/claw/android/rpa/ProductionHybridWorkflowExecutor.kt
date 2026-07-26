package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.workflow.WorkflowTemplateStore
import java.io.File

internal enum class ProductionTemplatePurpose { EXECUTION, VALIDATION }

internal fun interface ProductionTemplateAuthorizer {
    fun authorize(workflow: RpaWorkflow, purpose: ProductionTemplatePurpose): Boolean

    companion object {
        fun allowAll(): ProductionTemplateAuthorizer = ProductionTemplateAuthorizer { _, _ -> true }
    }
}

private class StoredProductionTemplateAuthorizer(
    workflowTemplateRoot: File
) : ProductionTemplateAuthorizer {
    private val store = WorkflowTemplateStore(workflowTemplateRoot)

    override fun authorize(workflow: RpaWorkflow, purpose: ProductionTemplatePurpose): Boolean =
        runCatching {
            val template = store.load().singleOrNull { stored ->
                stored.id == workflow.templateId && stored.revision == workflow.templateRevision
            } ?: return@runCatching false
            if (template.riskLevel !in ALLOWED_RISKS) return@runCatching false
            val lifecycleAllowed = when (purpose) {
                ProductionTemplatePurpose.EXECUTION ->
                    template.status == TemplateStatus.ACTIVE &&
                        template.validationState.validatedRevision == template.revision &&
                        template.steps.all { step -> step.validatedResolvers.containsAll(step.allowedResolvers) }
                ProductionTemplatePurpose.VALIDATION ->
                    template.status in VALIDATABLE_STATUSES
            }
            lifecycleAllowed && WorkflowTemplateManager.toHybridWorkflow(template, workflow.params) == workflow
        }.getOrDefault(false)

    companion object {
        private val ALLOWED_RISKS = setOf(TemplateRiskLevel.READ_ONLY, TemplateRiskLevel.REVERSIBLE)
        private val VALIDATABLE_STATUSES = setOf(
            TemplateStatus.DRAFT,
            TemplateStatus.VALIDATING,
            TemplateStatus.DEGRADED
        )
    }
}

internal class ProductionHybridRuntimeFactory(
    filesDirectory: File,
    private val apiLevel: Int,
    private val serviceProvider: ProductionPlatformServiceProvider,
    visualAssetReader: VisualAssetReader? = null,
    private val visualDecoder: VisualAssetDecoder = AndroidVisualAssetDecoder,
    private val clock: () -> Long = System::currentTimeMillis
) {
    private val ledgerAssembly = ProductionLedgerAssembly.create(filesDirectory, clock)
    private val assetReader = visualAssetReader ?: StoreVisualAssetReader(
        VisualAssetStore(ledgerAssembly.workflowTemplateRoot)
    )

    fun create(templateId: String, templateRevision: Int): HybridRpaEngine {
        require(isValidTemplateId(templateId)) { "production_template_id_invalid" }
        require(templateRevision > 0) { "production_template_revision_invalid" }

        val evidenceSource = ProductionHybridEvidenceSource(serviceProvider)
        val generation = {
            runCatching { serviceProvider.current()?.generationSnapshot() }.getOrNull()
        }
        val arbiter = HybridResolutionArbiter(
            semantic = ProductionSemanticChannel(clock),
            visual = ProductionVisualChannel(
                templateId = templateId,
                revision = templateRevision,
                apiLevel = apiLevel,
                assetReader = assetReader,
                decoder = visualDecoder,
                clock = clock
            ),
            apiLevel = apiLevel
        )
        val dispatcher = ProductionActionDispatcher(
            serviceProvider = serviceProvider,
            clock = clock
        )
        val verifier = ProductionOutcomeVerifier(evidenceSource)
        return HybridRpaEngine(
            evidenceSource = evidenceSource,
            arbiter = arbiter,
            executor = ledgerAssembly.singleDispatchExecutor(dispatcher, verifier, generation),
            generation = generation,
            clock = clock,
            resumeProofVerifier = ledgerAssembly.resumeProofVerifier
        )
    }

    private fun isValidTemplateId(templateId: String): Boolean =
        TEMPLATE_ID_PATTERN.matches(templateId) && templateId != "." && templateId != ".."

    companion object {
        private val TEMPLATE_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    }
}

internal class ProductionHybridWorkflowExecutor(
    filesDirectory: File,
    apiLevel: Int,
    serviceProvider: ProductionPlatformServiceProvider = CurrentClawPlatformServiceProvider,
    visualAssetReader: VisualAssetReader? = null,
    visualDecoder: VisualAssetDecoder = AndroidVisualAssetDecoder,
    clock: () -> Long = System::currentTimeMillis,
    templateAuthorizer: ProductionTemplateAuthorizer? = null
) : HybridWorkflowExecutor {
    private val factory = ProductionHybridRuntimeFactory(
        filesDirectory = filesDirectory,
        apiLevel = apiLevel,
        serviceProvider = serviceProvider,
        visualAssetReader = visualAssetReader,
        visualDecoder = visualDecoder,
        clock = clock
    )
    private val authorizer = templateAuthorizer ?: StoredProductionTemplateAuthorizer(
        File(filesDirectory.canonicalFile, "workflow_templates").canonicalFile
    )

    override fun run(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext?,
        cancelled: () -> Boolean,
        deadlineAt: Long
    ): HybridRunResult = runAuthorized(
        workflow,
        runId,
        resumeFrom,
        cancelled,
        deadlineAt,
        ProductionTemplatePurpose.EXECUTION
    )

    override fun runValidation(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext?,
        cancelled: () -> Boolean,
        deadlineAt: Long
    ): HybridRunResult = runAuthorized(
        workflow,
        runId,
        resumeFrom,
        cancelled,
        deadlineAt,
        ProductionTemplatePurpose.VALIDATION
    )

    private fun runAuthorized(
        workflow: RpaWorkflow,
        runId: String,
        resumeFrom: AgentHandoffContext?,
        cancelled: () -> Boolean,
        deadlineAt: Long,
        purpose: ProductionTemplatePurpose
    ): HybridRunResult {
        if (RpaWorkflowParser.validate(workflow).isNotEmpty() ||
            !TEMPLATE_ID_PATTERN.matches(workflow.templateId) ||
            workflow.templateId == "." || workflow.templateId == ".." ||
            workflow.templateRevision <= 0
        ) {
            return invalidWorkflow()
        }
        if (!authorizer.authorize(workflow, purpose)) {
            return invalidWorkflow("template_not_authorized")
        }
        val engine = runCatching {
            factory.create(workflow.templateId, workflow.templateRevision)
        }.getOrElse {
            return invalidWorkflow(templateAuthorized = true)
        }
        return engine.run(workflow, runId, resumeFrom, cancelled, deadlineAt).copy(
            templateAuthorized = true
        )
    }

    private fun invalidWorkflow(
        errorCode: String = "invalid_workflow",
        templateAuthorized: Boolean = false
    ): HybridRunResult = HybridRunResult(
        success = false,
        steps = emptyList(),
        errorCode = errorCode,
        outcomeState = "blocked",
        dispatchCount = 0,
        rounds = 0,
        agentHandoffRequired = true,
        stoppedStepIndex = 0,
        templateAuthorized = templateAuthorized
    )

    companion object {
        private val TEMPLATE_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    }
}

private class ProductionHybridEvidenceSource(
    private val serviceProvider: ProductionPlatformServiceProvider
) : HybridEvidenceSource {
    override fun capture(requirement: FreshnessRequirement): UiEvidence {
        val service = serviceProvider.current()
            ?: throw IllegalStateException("accessibility_service_unavailable")
        return service.capture(requirement)
    }
}
