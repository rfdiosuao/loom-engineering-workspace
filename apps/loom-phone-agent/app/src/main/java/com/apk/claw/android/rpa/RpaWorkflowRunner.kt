package com.apk.claw.android.rpa

import android.view.accessibility.AccessibilityNodeInfo
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.ToolResult
import com.apk.claw.android.utils.XLog
import com.google.gson.GsonBuilder
import java.io.File
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal class RpaExecutionLease internal constructor(
    private val release: () -> Unit
) : AutoCloseable {
    private val closed = AtomicBoolean(false)

    override fun close() {
        if (closed.compareAndSet(false, true)) release()
    }
}

object RpaWorkflowRunner {
    private const val TAG = "RpaWorkflowRunner"
    private val gson = GsonBuilder().setPrettyPrinting().create()
    private val executor = Executors.newSingleThreadExecutor()
    private val activeOwner = AtomicReference<Any?>(null)
    private val runs = ConcurrentHashMap<String, MutableRun>()
    private val handoffs = ConcurrentHashMap<String, AgentHandoffContext>()
    @Volatile
    private var hybridEngine: HybridWorkflowExecutor? = null

    fun installHybridEngine(engine: HybridWorkflowExecutor?) {
        hybridEngine = engine
    }

    fun isHybridEngineInstalled(): Boolean = hybridEngine != null

    fun isAccessibilityReady(): Boolean = ClawAccessibilityService.getInstance() != null

    fun runHybridValidation(workflow: RpaWorkflow): HybridRunResult? {
        val engine = hybridEngine ?: return null
        val errors = RpaWorkflowParser.validate(workflow)
        if (errors.isNotEmpty()) return null
        return engine.runValidation(
            workflow = workflow,
            runId = "validation_${UUID.randomUUID().toString().take(12)}"
        )
    }

    fun start(workflow: RpaWorkflow): RpaStartResult =
        if (workflow.executionMode == HYBRID_EXECUTION_MODE) startHybrid(workflow) else startLegacy(workflow)

    private fun startLegacy(workflow: RpaWorkflow): RpaStartResult {
        val validationErrors = RpaWorkflowParser.validate(workflow)
        if (validationErrors.isNotEmpty()) {
            return RpaStartResult(
                accepted = false,
                errorCode = "invalid_workflow",
                message = validationErrors.joinToString("; "),
                retryable = false
            )
        }
        if (ClawAccessibilityService.getInstance() == null) {
            return RpaStartResult(
                accepted = false,
                errorCode = "accessibility_reenable_required",
                message = "Accessibility service is not running",
                retryable = true
            )
        }
        val executionLease = tryAcquireExecutionLease()
        if (executionLease == null) {
            return RpaStartResult(
                accepted = false,
                errorCode = "rpa_busy",
                message = "An RPA workflow is already running",
                retryable = true
            )
        }

        try {
            val now = System.currentTimeMillis()
            val runId = "rpa_${UUID.randomUUID().toString().take(8)}"
            val run = MutableRun(
                workflow = workflow,
                snapshot = RpaRunSnapshot(
                    runId = runId,
                    workflowId = workflow.id,
                    workflowName = workflow.name,
                    status = RpaRunStatus.QUEUED,
                    currentStep = 0,
                    totalSteps = workflow.steps.size,
                    message = "queued",
                    startedAt = now,
                    updatedAt = now
                )
            )
            runs[runId] = run
            persist(run.snapshot())

            submitWithLease(executionLease) {
                execute(run)
            }
            return RpaStartResult(accepted = true, snapshot = run.snapshot())
        } catch (error: Throwable) {
            executionLease.close()
            throw error
        }
    }

    private fun startHybrid(workflow: RpaWorkflow): RpaStartResult {
        val validationErrors = RpaWorkflowParser.validate(workflow)
        if (validationErrors.isNotEmpty()) {
            return RpaStartResult(
                accepted = false,
                errorCode = "invalid_workflow",
                message = validationErrors.joinToString("; "),
                retryable = false
            )
        }
        val engine = hybridEngine ?: return RpaStartResult(
            accepted = false,
            errorCode = "hybrid_engine_unavailable",
            message = "Hybrid RPA engine is not configured",
            retryable = false
        )
        if (ClawAccessibilityService.getInstance() == null) {
            return RpaStartResult(
                accepted = false,
                errorCode = "accessibility_reenable_required",
                message = "Accessibility service is not running",
                retryable = true
            )
        }
        val executionLease = tryAcquireExecutionLease()
        if (executionLease == null) {
            return RpaStartResult(
                accepted = false,
                errorCode = "rpa_busy",
                message = "An RPA workflow is already running",
                retryable = true
            )
        }

        try {
            val now = System.currentTimeMillis()
            val runId = "rpa_${UUID.randomUUID().toString().take(8)}"
            val run = MutableRun(
                workflow = workflow,
                snapshot = RpaRunSnapshot(
                    runId = runId,
                    workflowId = workflow.id,
                    workflowName = workflow.name,
                    status = RpaRunStatus.QUEUED,
                    currentStep = 0,
                    totalSteps = workflow.steps.size,
                    message = "queued",
                    startedAt = now,
                    updatedAt = now,
                    mode = HYBRID_EXECUTION_MODE
                )
            )
            runs[runId] = run
            persist(run.snapshot())

            submitWithLease(executionLease) {
                executeHybrid(run, engine)
            }
            return RpaStartResult(accepted = true, snapshot = run.snapshot())
        } catch (error: Throwable) {
            executionLease.close()
            throw error
        }
    }

    fun get(runId: String): RpaRunSnapshot? = runs[runId]?.snapshot()

    fun getAgentHandoff(runId: String): AgentHandoffContext? = handoffs[runId]

    fun list(): List<RpaRunSnapshot> = runs.values.map { it.snapshot() }.sortedByDescending { it.updatedAt }

    fun isIdle(): Boolean = activeOwner.get() == null

    internal fun tryAcquireExecutionLease(): RpaExecutionLease? = tryAcquireLease()

    internal fun tryAcquireValidationLease(): RpaExecutionLease? = tryAcquireLease()

    private fun tryAcquireLease(): RpaExecutionLease? {
        val owner = Any()
        if (!activeOwner.compareAndSet(null, owner)) return null
        return RpaExecutionLease { activeOwner.compareAndSet(owner, null) }
    }

    private fun submitWithLease(lease: RpaExecutionLease, action: () -> Unit) {
        try {
            executor.submit {
                try {
                    action()
                } finally {
                    lease.close()
                }
            }
        } catch (error: Throwable) {
            lease.close()
            throw error
        }
    }

    fun cancel(runId: String): RpaRunSnapshot? {
        val run = runs[runId] ?: return null
        run.cancelRequested.set(true)
        if (run.snapshot().status == RpaRunStatus.QUEUED) {
            run.update(
                status = RpaRunStatus.CANCELLED,
                message = "cancelled before start",
                errorCode = "cancelled",
                retryable = false,
                finishedAt = System.currentTimeMillis()
            )
        }
        return run.snapshot()
    }

    private fun execute(run: MutableRun) {
        val workflow = run.workflow
        val startedAt = run.snapshot().startedAt
        run.update(status = RpaRunStatus.RUNNING, message = "running")

        val service = ClawAccessibilityService.getInstance()
        if (service == null) {
            run.update(
                status = RpaRunStatus.FAILED,
                message = "Accessibility service is not running",
                errorCode = "accessibility_reenable_required",
                retryable = true,
                finishedAt = System.currentTimeMillis()
            )
            return
        }

        for ((index, step) in workflow.steps.withIndex()) {
            if (run.cancelRequested.get()) {
                run.update(
                    status = RpaRunStatus.CANCELLED,
                    currentStep = index,
                    currentStepId = step.id,
                    currentAction = step.action,
                    message = "cancelled",
                    errorCode = "cancelled",
                    retryable = false,
                    finishedAt = System.currentTimeMillis()
                )
                return
            }
            if (System.currentTimeMillis() - startedAt > workflow.maxDurationMs) {
                run.update(
                    status = RpaRunStatus.FAILED,
                    currentStep = index + 1,
                    currentStepId = step.id,
                    currentAction = step.action,
                    message = "RPA workflow timed out",
                    errorCode = "rpa_timeout",
                    retryable = true,
                    finishedAt = System.currentTimeMillis()
                )
                return
            }

            val normalizedStep = step.copy(action = RpaActionNormalizer.normalize(step.action))
            run.update(
                status = RpaRunStatus.RUNNING,
                currentStep = index + 1,
                currentStepId = normalizedStep.id,
                currentAction = normalizedStep.action,
                message = normalizedStep.description.ifBlank { normalizedStep.action }
            )

            val safety = RpaSafetyPolicy.inspect(normalizedStep)
            if (!safety.allowed) {
                failStep(run, index, normalizedStep, safety.message, safety.errorCode, retryable = false)
                return
            }

            val guardBefore = checkGuard(service, normalizedStep.guard)
            if (!guardBefore.isSuccess) {
                failStep(run, index, normalizedStep, guardBefore.error.orEmpty(), "guard_failed", retryable = true)
                return
            }

            val record = executeWithRetries(service, normalizedStep, index)
            run.addStep(record)
            if (record.status != "succeeded") {
                run.update(
                    status = RpaRunStatus.FAILED,
                    message = record.message,
                    errorCode = record.errorCode,
                    retryable = record.retryable,
                    finishedAt = System.currentTimeMillis()
                )
                return
            }

            if (normalizedStep.waitAfterMs > 0L && !sleepInterruptibly(normalizedStep.waitAfterMs, run)) {
                run.update(
                    status = RpaRunStatus.CANCELLED,
                    message = "cancelled",
                    errorCode = "cancelled",
                    retryable = false,
                    finishedAt = System.currentTimeMillis()
                )
                return
            }

            val guardAfter = checkGuard(service, normalizedStep.guard)
            if (!guardAfter.isSuccess) {
                failStep(run, index, normalizedStep, guardAfter.error.orEmpty(), "guard_failed", retryable = true)
                return
            }
        }

        run.update(
            status = RpaRunStatus.SUCCEEDED,
            currentStep = workflow.steps.size,
            currentStepId = workflow.steps.lastOrNull()?.id.orEmpty(),
            currentAction = workflow.steps.lastOrNull()?.action.orEmpty(),
            message = "RPA workflow completed",
            errorCode = "",
            retryable = false,
            finishedAt = System.currentTimeMillis()
        )
    }

    private fun executeHybrid(run: MutableRun, engine: HybridWorkflowExecutor) {
        val initial = run.snapshot()
        run.update(status = RpaRunStatus.RUNNING, message = "running")
        try {
            val deadlineAt = if (run.workflow.maxDurationMs <= 0L ||
                initial.startedAt > Long.MAX_VALUE - run.workflow.maxDurationMs
            ) Long.MAX_VALUE else initial.startedAt + run.workflow.maxDurationMs
            val result = engine.run(
                workflow = run.workflow,
                runId = initial.runId,
                cancelled = { run.cancelRequested.get() },
                deadlineAt = deadlineAt
            )
            result.handoffContext?.let { handoffs[initial.runId] = it } ?: handoffs.remove(initial.runId)
            result.steps.forEach(run::addStep)
            val status = when {
                result.success -> RpaRunStatus.SUCCEEDED
                result.errorCode == "cancelled" -> RpaRunStatus.CANCELLED
                else -> RpaRunStatus.FAILED
            }
            val stoppedIndex = when {
                result.success -> run.workflow.steps.size
                result.stoppedStepIndex > 0 -> result.stoppedStepIndex
                else -> result.steps.size
            }
            val stoppedStep = run.workflow.steps.getOrNull((stoppedIndex - 1).coerceAtLeast(0))
            run.update(
                status = status,
                currentStep = stoppedIndex,
                currentStepId = stoppedStep?.id.orEmpty(),
                currentAction = stoppedStep?.action.orEmpty(),
                message = if (result.success) "Hybrid RPA workflow completed" else result.errorCode,
                errorCode = result.errorCode,
                retryable = false,
                finishedAt = System.currentTimeMillis(),
                dispatchCount = result.dispatchCount,
                rounds = result.rounds,
                outcomeState = result.outcomeState,
                fallbackStepIndex = if (result.success) 0 else stoppedIndex,
                compactTreeReads = saturatedIntSum(result.steps.map { it.compactTreeReads }),
                fullTreeReads = saturatedIntSum(result.steps.map { it.fullTreeReads }),
                templateStatus = if (result.templateAuthorized) run.workflow.templateStatus else null,
                templateRevision = if (result.templateAuthorized) run.workflow.templateRevision else null,
                validationProgress = if (result.templateAuthorized) run.workflow.validationProgress else null,
                promotionEligible = if (result.templateAuthorized) run.workflow.promotionEligible else null,
                promotionIneligibleReason = if (result.templateAuthorized) run.workflow.promotionIneligibleReason else null
            )
        } catch (_: Throwable) {
            run.update(
                status = RpaRunStatus.FAILED,
                message = "hybrid_engine_failure",
                errorCode = "hybrid_engine_failure",
                retryable = false,
                finishedAt = System.currentTimeMillis(),
                outcomeState = "blocked"
            )
        } finally {
            if (run.snapshot().status == RpaRunStatus.RUNNING) {
                run.update(
                    status = RpaRunStatus.FAILED,
                    message = "hybrid_engine_failure",
                    errorCode = "hybrid_engine_failure",
                    retryable = false,
                    finishedAt = System.currentTimeMillis(),
                    outcomeState = "blocked"
                )
            }
        }
    }

    internal fun executeHybridForTest(
        workflow: RpaWorkflow,
        engine: HybridWorkflowExecutor
    ): RpaRunSnapshot {
        val now = System.currentTimeMillis()
        val run = MutableRun(
            workflow = workflow,
            snapshot = RpaRunSnapshot(
                runId = "rpa_test_runner",
                workflowId = workflow.id,
                workflowName = workflow.name,
                status = RpaRunStatus.QUEUED,
                currentStep = 0,
                totalSteps = workflow.steps.size,
                startedAt = now,
                updatedAt = now,
                mode = HYBRID_EXECUTION_MODE
            )
        )
        executeHybrid(run, engine)
        return run.snapshot()
    }

    private fun executeWithRetries(
        service: ClawAccessibilityService,
        step: RpaStep,
        index: Int
    ): RpaStepRecord {
        val startedAt = System.currentTimeMillis()
        var attempts = 0
        var lastResult: ToolResult = ToolResult.error("not executed")
        val maxAttempts = step.maxRetries + 1
        while (attempts < maxAttempts) {
            attempts += 1
            val actionStart = System.currentTimeMillis()
            lastResult = runCatching { executeAction(service, step) }
                .getOrElse { ToolResult.error(it.message ?: "RPA action failed") }
            val actionMs = System.currentTimeMillis() - actionStart
            if (lastResult.isSuccess) {
                val now = System.currentTimeMillis()
                return RpaStepRecord(
                    index = index + 1,
                    stepId = step.id,
                    action = step.action,
                    status = "succeeded",
                    attempts = attempts,
                    actionMs = actionMs,
                    message = lastResult.data.orEmpty().take(500),
                    startedAt = startedAt,
                    finishedAt = now
                )
            }
            if (attempts < maxAttempts) {
                sleepInterruptibly(step.retryDelayMs, null)
            }
        }

        val now = System.currentTimeMillis()
        return RpaStepRecord(
            index = index + 1,
            stepId = step.id,
            action = step.action,
            status = "failed",
            attempts = attempts,
            actionMs = now - startedAt,
            message = lastResult.error.orEmpty().take(500),
            errorCode = "rpa_step_failed",
            retryable = true,
            startedAt = startedAt,
            finishedAt = now
        )
    }

    private fun executeAction(service: ClawAccessibilityService, step: RpaStep): ToolResult {
        return when (step.action) {
            "open_app" -> ToolRegistry.executeTool(
                "open_app",
                mapOf(
                    "package_name" to requiredString(step, "package_name", "packageName", "package"),
                    "verify_foreground" to booleanParam(step, true, "verify_foreground", "verifyForeground"),
                    "check_launch_dialog" to booleanParam(step, true, "check_launch_dialog", "checkLaunchDialog"),
                    "force_reopen" to booleanParam(step, false, "force_reopen", "forceReopen")
                )
            )
            "wait_text" -> waitForText(service, requiredString(step, "text", "label"), step.timeoutMs)
            "assert_text" -> assertText(service, requiredString(step, "text", "label"))
            "assert_package" -> assertPackage(service, requiredString(step, "package_name", "packageName", "package"))
            "tap_text" -> clickNodes(
                service.findNodesByText(requiredString(step, "text", "label")),
                "text=${requiredString(step, "text", "label")}",
                service
            )
            "tap_description" -> clickNodes(
                service.findNodesByDescription(requiredString(step, "contentDescription", "content_description", "description", "desc")),
                "description=${requiredString(step, "contentDescription", "content_description", "description", "desc")}",
                service
            )
            "tap_resource_id" -> clickNodes(
                service.findNodesById(requiredString(step, "resourceId", "resource_id", "viewId", "view_id")),
                "resourceId=${requiredString(step, "resourceId", "resource_id", "viewId", "view_id")}",
                service
            )
            "tap" -> {
                val x = intParam(step, "x", "centerX", "center_x")
                val y = intParam(step, "y", "centerY", "center_y")
                val durationMs = longParam(step, 100L, "duration_ms", "durationMs")
                if (service.performTap(x, y, durationMs)) ToolResult.success("Tapped at ($x, $y)") else ToolResult.error("Failed to tap at ($x, $y)")
            }
            "input_text" -> ToolRegistry.executeTool(
                "input_text",
                mapOf(
                    "text" to requiredString(step, "text", "value", "input"),
                    "clear_first" to booleanParam(step, true, "clear_first", "clearFirst")
                )
            )
            "swipe", "scroll" -> swipe(service, step)
            "back" -> if (service.pressBack()) ToolResult.success("Pressed back") else ToolResult.error("Failed to press back")
            "home" -> if (service.pressHome()) ToolResult.success("Pressed home") else ToolResult.error("Failed to press home")
            "wait" -> {
                val durationMs = longParam(step, step.timeoutMs, "duration_ms", "durationMs", "ms")
                    .coerceIn(0L, 120_000L)
                Thread.sleep(durationMs)
                ToolResult.success("Waited ${durationMs}ms")
            }
            "screenshot" -> ToolRegistry.executeTool("take_screenshot", emptyMap())
            "observe" -> ToolRegistry.executeTool("get_screen_info", emptyMap())
            else -> ToolResult.error("Unsupported RPA action: ${step.action}")
        }
    }

    private fun waitForText(service: ClawAccessibilityService, text: String, timeoutMs: Long): ToolResult {
        val deadline = System.currentTimeMillis() + timeoutMs.coerceIn(100L, 120_000L)
        var attempts = 0
        while (System.currentTimeMillis() <= deadline) {
            attempts += 1
            val nodes = service.findNodesByText(text)
            try {
                if (nodes.isNotEmpty()) {
                    return ToolResult.success("Text appeared after $attempts checks: $text")
                }
            } finally {
                ClawAccessibilityService.recycleNodes(nodes)
            }
            Thread.sleep(150L)
        }
        return ToolResult.error("Text not found before timeout: $text")
    }

    private fun assertText(service: ClawAccessibilityService, text: String): ToolResult {
        val nodes = service.findNodesByText(text)
        return try {
            if (nodes.isNotEmpty()) ToolResult.success("Text found: $text") else ToolResult.error("Text not found: $text")
        } finally {
            ClawAccessibilityService.recycleNodes(nodes)
        }
    }

    private fun assertPackage(service: ClawAccessibilityService, expected: String): ToolResult {
        val actual = service.currentPackageName.orEmpty()
        return if (actual == expected) {
            ToolResult.success("Foreground package matched: $actual")
        } else {
            ToolResult.error("Foreground package mismatch: expected=$expected, actual=$actual")
        }
    }

    private fun checkGuard(service: ClawAccessibilityService, guard: RpaStepGuard): ToolResult {
        guard.expectedPackage?.takeIf { it.isNotBlank() }?.let { expected ->
            val actual = service.currentPackageName.orEmpty()
            if (actual != expected) {
                return ToolResult.error("Guard failed: expectedPackage=$expected, actual=$actual")
            }
        }
        for (text in guard.requireText) {
            val result = assertText(service, text)
            if (!result.isSuccess) return ToolResult.error("Guard failed: required text missing: $text")
        }
        for (text in guard.forbidText) {
            val nodes = service.findNodesByText(text)
            try {
                if (nodes.isNotEmpty()) return ToolResult.error("Guard failed: forbidden text visible: $text")
            } finally {
                ClawAccessibilityService.recycleNodes(nodes)
            }
        }
        return ToolResult.success("Guard passed")
    }

    private fun clickNodes(nodes: List<AccessibilityNodeInfo>, target: String, service: ClawAccessibilityService): ToolResult {
        if (nodes.isEmpty()) return ToolResult.error("Target not found: $target")
        return try {
            if (service.clickNode(nodes.first())) ToolResult.success("Clicked target: $target") else ToolResult.error("Failed to click target: $target")
        } finally {
            ClawAccessibilityService.recycleNodes(nodes)
        }
    }

    private fun swipe(service: ClawAccessibilityService, step: RpaStep): ToolResult {
        if (hasAny(step, "startX", "start_x")) {
            val startX = intParam(step, "startX", "start_x")
            val startY = intParam(step, "startY", "start_y")
            val endX = intParam(step, "endX", "end_x")
            val endY = intParam(step, "endY", "end_y")
            val durationMs = longParam(step, 350L, "duration_ms", "durationMs")
            val ok = service.performSwipe(startX, startY, endX, endY, durationMs)
            return if (ok) ToolResult.success("Swiped from ($startX, $startY) to ($endX, $endY)") else ToolResult.error("Failed to swipe")
        }
        val direction = stringParam(step, "direction").ifBlank { "down" }
        val metrics = service.resources.displayMetrics
        val centerX = metrics.widthPixels / 2
        val centerY = metrics.heightPixels / 2
        val leftX = (metrics.widthPixels * 0.25f).toInt()
        val rightX = (metrics.widthPixels * 0.75f).toInt()
        val upperY = (metrics.heightPixels * 0.30f).toInt()
        val lowerY = (metrics.heightPixels * 0.72f).toInt()
        val durationMs = longParam(step, 350L, "duration_ms", "durationMs")
        val ok = when (direction.lowercase()) {
            "up" -> service.performSwipe(centerX, upperY, centerX, lowerY, durationMs)
            "left" -> service.performSwipe(leftX, centerY, rightX, centerY, durationMs)
            "right" -> service.performSwipe(rightX, centerY, leftX, centerY, durationMs)
            else -> service.performSwipe(centerX, lowerY, centerX, upperY, durationMs)
        }
        return if (ok) ToolResult.success("Swiped $direction") else ToolResult.error("Failed to swipe $direction")
    }

    private fun failStep(
        run: MutableRun,
        index: Int,
        step: RpaStep,
        message: String,
        errorCode: String,
        retryable: Boolean
    ) {
        val now = System.currentTimeMillis()
        run.addStep(
            RpaStepRecord(
                index = index + 1,
                stepId = step.id,
                action = step.action,
                status = "failed",
                attempts = 0,
                actionMs = 0L,
                message = message.take(500),
                errorCode = errorCode,
                retryable = retryable,
                startedAt = now,
                finishedAt = now
            )
        )
        run.update(
            status = RpaRunStatus.FAILED,
            message = message,
            errorCode = errorCode,
            retryable = retryable,
            finishedAt = now
        )
    }

    private fun requiredString(step: RpaStep, vararg keys: String): String {
        return keys.firstNotNullOfOrNull { key -> step.params[key]?.toString()?.takeIf { it.isNotBlank() } }
            ?: throw IllegalArgumentException("Missing required parameter: ${keys.first()}")
    }

    private fun stringParam(step: RpaStep, key: String): String = step.params[key]?.toString().orEmpty()

    private fun intParam(step: RpaStep, vararg keys: String): Int {
        val value = keys.firstNotNullOfOrNull { key -> step.params[key] }
            ?: throw IllegalArgumentException("Missing required parameter: ${keys.first()}")
        return when (value) {
            is Number -> value.toInt()
            else -> value.toString().toInt()
        }
    }

    private fun longParam(step: RpaStep, default: Long, vararg keys: String): Long {
        val value = keys.firstNotNullOfOrNull { key -> step.params[key] } ?: return default
        return when (value) {
            is Number -> value.toLong()
            else -> value.toString().toLong()
        }
    }

    private fun booleanParam(step: RpaStep, default: Boolean, vararg keys: String): Boolean {
        val value = keys.firstNotNullOfOrNull { key -> step.params[key] } ?: return default
        return when (value) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            else -> value.toString().toBoolean()
        }
    }

    private fun hasAny(step: RpaStep, vararg keys: String): Boolean = keys.any { step.params.containsKey(it) }

    private fun sleepInterruptibly(durationMs: Long, run: MutableRun?): Boolean {
        if (durationMs <= 0L) return true
        val deadline = System.currentTimeMillis() + durationMs
        while (System.currentTimeMillis() < deadline) {
            if (run?.cancelRequested?.get() == true) return false
            val remaining = deadline - System.currentTimeMillis()
            Thread.sleep(remaining.coerceAtMost(150L))
        }
        return true
    }

    private fun persist(snapshot: RpaRunSnapshot) {
        runCatching {
            val dir = File(ClawApplication.instance.filesDir, "rpa_runs")
            if (!dir.exists()) dir.mkdirs()
            File(dir, "${snapshot.runId}.json").writeText(gson.toJson(RpaRunJson.snapshot(snapshot)))
        }.onFailure { error ->
            runCatching { XLog.w(TAG, "Failed to persist RPA run: ${error.message}") }
        }
    }

    private class MutableRun(
        val workflow: RpaWorkflow,
        initialSteps: List<RpaStepRecord> = emptyList(),
        snapshot: RpaRunSnapshot
    ) {
        val cancelRequested = AtomicBoolean(false)
        private val lock = Any()
        private val records = initialSteps.toMutableList()
        private var current = snapshot

        fun snapshot(): RpaRunSnapshot = synchronized(lock) { current.copy(steps = records.toList()) }

        fun addStep(record: RpaStepRecord) {
            synchronized(lock) {
                records += record
                current = current.copy(updatedAt = System.currentTimeMillis(), steps = records.toList())
            }
            persist(snapshot())
        }

        fun update(
            status: RpaRunStatus? = null,
            currentStep: Int? = null,
            currentStepId: String? = null,
            currentAction: String? = null,
            message: String? = null,
            errorCode: String? = null,
            retryable: Boolean? = null,
            finishedAt: Long? = null,
            dispatchCount: Int? = null,
            rounds: Int? = null,
            outcomeState: String? = null,
            fallbackStepIndex: Int? = null,
            compactTreeReads: Int? = null,
            fullTreeReads: Int? = null,
            templateStatus: String? = null,
            templateRevision: Int? = null,
            validationProgress: String? = null,
            promotionEligible: Boolean? = null,
            promotionIneligibleReason: String? = null
        ) {
            synchronized(lock) {
                val now = System.currentTimeMillis()
                val doneAt = finishedAt ?: current.finishedAt
                current = current.copy(
                    status = status ?: current.status,
                    currentStep = currentStep ?: current.currentStep,
                    currentStepId = currentStepId ?: current.currentStepId,
                    currentAction = currentAction ?: current.currentAction,
                    message = message ?: current.message,
                    errorCode = errorCode ?: current.errorCode,
                    retryable = retryable ?: current.retryable,
                    updatedAt = now,
                    finishedAt = doneAt,
                    totalMs = (if (doneAt > 0L) doneAt else now) - current.startedAt,
                    steps = records.toList(),
                    dispatchCount = dispatchCount ?: current.dispatchCount,
                    rounds = rounds ?: current.rounds,
                    outcomeState = outcomeState ?: current.outcomeState,
                    fallbackStepIndex = fallbackStepIndex ?: current.fallbackStepIndex,
                    compactTreeReads = compactTreeReads ?: current.compactTreeReads,
                    fullTreeReads = fullTreeReads ?: current.fullTreeReads,
                    templateStatus = templateStatus ?: current.templateStatus,
                    templateRevision = templateRevision ?: current.templateRevision,
                    validationProgress = validationProgress ?: current.validationProgress,
                    promotionEligible = promotionEligible ?: current.promotionEligible,
                    promotionIneligibleReason = promotionIneligibleReason ?: current.promotionIneligibleReason
                )
            }
            persist(snapshot())
        }
    }

    private fun saturatedIntSum(values: Iterable<Int>): Int {
        var total = 0L
        for (value in values) {
            total = (total + value.coerceAtLeast(0).toLong()).coerceAtMost(Int.MAX_VALUE.toLong())
        }
        return total.toInt()
    }
}
