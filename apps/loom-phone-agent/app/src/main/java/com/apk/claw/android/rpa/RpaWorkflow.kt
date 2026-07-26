package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint
import com.apk.claw.android.workflow.VisualAnchorSpec

data class RpaWorkflow(
    val id: String,
    val name: String,
    val version: Int = 1,
    val steps: List<RpaStep>,
    val params: Map<String, String> = emptyMap(),
    val maxDurationMs: Long = 300_000L,
    val schemaVersion: Int = 1,
    val executionMode: String = "rpa",
    val templateId: String = "",
    val templateRevision: Int = 0,
    val targetProfileId: String = "",
    val templateStatus: String = "",
    val validationProgress: String = "",
    val promotionEligible: Boolean = false,
    val promotionIneligibleReason: String = ""
)

data class RpaStep(
    val id: String,
    val action: String,
    val params: Map<String, Any> = emptyMap(),
    val description: String = "",
    val waitAfterMs: Long = 0L,
    val timeoutMs: Long = 5_000L,
    val maxRetries: Int = 0,
    val retryDelayMs: Long = 300L,
    val guard: RpaStepGuard = RpaStepGuard(),
    val resolverPolicy: ResolverPolicy = ResolverPolicy.DIRECT,
    val allowedResolvers: Set<ResolverKind> = emptySet(),
    val validatedResolvers: Set<ResolverKind> = emptySet(),
    val semanticSelector: SemanticSelector? = null,
    val visualAnchor: VisualAnchorSpec? = null,
    val preCheckpoint: StepCheckpoint? = null,
    val postCheckpoint: StepCheckpoint? = null,
    val resolverPolicyExplicit: Boolean = allowedResolvers.isNotEmpty() || validatedResolvers.isNotEmpty()
)

data class RpaStepGuard(
    val expectedPackage: String? = null,
    val requireText: List<String> = emptyList(),
    val forbidText: List<String> = emptyList()
)

enum class RpaRunStatus(val wireName: String) {
    QUEUED("queued"),
    RUNNING("running"),
    SUCCEEDED("succeeded"),
    FAILED("failed"),
    CANCELLED("cancelled")
}

data class RpaStepRecord(
    val index: Int,
    val stepId: String,
    val action: String,
    val status: String,
    val attempts: Int,
    val actionMs: Long,
    val message: String = "",
    val errorCode: String = "",
    val retryable: Boolean = false,
    val startedAt: Long,
    val finishedAt: Long,
    val resolverPolicy: String = "",
    val resolverUsed: String = "",
    val treeSnapshotMs: Long = 0L,
    val treeLookupMs: Long = 0L,
    val treeCacheHit: Boolean = false,
    val nodesVisited: Int = 0,
    val captureMs: Long = 0L,
    val matchMs: Long = 0L,
    val verifyMs: Long = 0L,
    val frameId: String = "",
    val frameSource: String = "",
    val frameAgeMs: Long = 0L,
    val uiGeneration: Long = 0L,
    val outcomeState: String = "",
    val dispatchCount: Int = 0,
    val rounds: Int = 0,
    val compactTreeReads: Int = 0,
    val fullTreeReads: Int = 0,
    val toolCallMs: Long = 0L,
    val mode: String = "rpa"
)

data class RpaRunSnapshot(
    val runId: String,
    val workflowId: String,
    val workflowName: String,
    val status: RpaRunStatus,
    val currentStep: Int,
    val totalSteps: Int,
    val currentStepId: String = "",
    val currentAction: String = "",
    val message: String = "",
    val errorCode: String = "",
    val retryable: Boolean = false,
    val startedAt: Long,
    val updatedAt: Long,
    val finishedAt: Long = 0L,
    val totalMs: Long = updatedAt - startedAt,
    val mode: String = "rpa",
    val steps: List<RpaStepRecord> = emptyList(),
    val dispatchCount: Int = 0,
    val rounds: Int = 0,
    val outcomeState: String = "",
    val templateStatus: String = "",
    val templateRevision: Int = 0,
    val validationProgress: String = "",
    val promotionEligible: Boolean = false,
    val promotionIneligibleReason: String = "",
    val fallbackStepIndex: Int = 0,
    val compactTreeReads: Int = 0,
    val fullTreeReads: Int = 0
)

data class RpaStartResult(
    val accepted: Boolean,
    val snapshot: RpaRunSnapshot? = null,
    val errorCode: String = "",
    val message: String = "",
    val retryable: Boolean = false
)
