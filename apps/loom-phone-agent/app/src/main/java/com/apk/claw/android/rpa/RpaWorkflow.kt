package com.apk.claw.android.rpa

data class RpaWorkflow(
    val id: String,
    val name: String,
    val version: Int = 1,
    val steps: List<RpaStep>,
    val params: Map<String, String> = emptyMap(),
    val maxDurationMs: Long = 300_000L
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
    val guard: RpaStepGuard = RpaStepGuard()
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
    val finishedAt: Long
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
    val steps: List<RpaStepRecord> = emptyList()
)

data class RpaStartResult(
    val accepted: Boolean,
    val snapshot: RpaRunSnapshot? = null,
    val errorCode: String = "",
    val message: String = "",
    val retryable: Boolean = false
)
