package com.apk.claw.android.rpa

import com.google.gson.JsonArray
import com.google.gson.JsonObject

object RpaRunJson {
    fun snapshot(snapshot: RpaRunSnapshot): JsonObject {
        val hybrid = snapshot.mode == HYBRID_EXECUTION_MODE
        val screenTreeMs = saturatingSum(snapshot.steps) { record ->
            saturatingAdd(record.treeSnapshotMs, record.treeLookupMs)
        }
        val stepMs = saturatingSum(snapshot.steps) { it.actionMs }
        val toolCallMs = saturatingSum(snapshot.steps) { it.toolCallMs }
        return JsonObject().apply {
            addProperty("runId", snapshot.runId)
            addProperty("workflowId", snapshot.workflowId)
            addProperty("workflowName", snapshot.workflowName)
            addProperty("status", snapshot.status.wireName)
            addProperty("mode", snapshot.mode)
            addProperty("currentStep", if (hybrid) snapshot.currentStep.coerceAtLeast(0) else snapshot.currentStep)
            addProperty("totalSteps", if (hybrid) snapshot.totalSteps.coerceAtLeast(0) else snapshot.totalSteps)
            addProperty("currentStepId", snapshot.currentStepId)
            addProperty("currentAction", snapshot.currentAction)
            addProperty("message", snapshot.message)
            addProperty("errorCode", snapshot.errorCode)
            addProperty("retryable", snapshot.retryable)
            addProperty("startedAt", snapshot.startedAt)
            addProperty("updatedAt", snapshot.updatedAt)
            addProperty("finishedAt", snapshot.finishedAt)
            addProperty("totalMs", if (hybrid) snapshot.totalMs.coerceAtLeast(0L) else snapshot.totalMs)
            if (hybrid) {
                addProperty("dispatchCount", snapshot.dispatchCount.coerceAtLeast(0))
                addProperty("rounds", snapshot.rounds.coerceAtLeast(0))
                addProperty("outcomeState", snapshot.outcomeState)
                addProperty("templateStatus", snapshot.templateStatus)
                addProperty("templateRevision", snapshot.templateRevision.coerceAtLeast(0))
                addProperty("validationProgress", snapshot.validationProgress)
                addProperty("promotionEligible", snapshot.promotionEligible)
                addProperty("promotionIneligibleReason", snapshot.promotionIneligibleReason)
                addProperty("fallbackStepIndex", snapshot.fallbackStepIndex.coerceAtLeast(0))
                addProperty("compactTreeReads", snapshot.compactTreeReads.coerceAtLeast(0))
                addProperty("fullTreeReads", snapshot.fullTreeReads.coerceAtLeast(0))
            }
            add("metrics", JsonObject().apply {
                addProperty("totalMs", if (hybrid) snapshot.totalMs.coerceAtLeast(0L) else snapshot.totalMs)
                addProperty("screenTreeMs", if (hybrid) screenTreeMs else 0L)
                addProperty("llmRoundMs", 0L)
                addProperty("toolCallMs", if (hybrid) toolCallMs else 0L)
                addProperty("toolCallMeasured", hybrid && snapshot.dispatchCount > 0)
                addProperty("stepMs", if (hybrid) stepMs else 0L)
                addProperty("rounds", 0)
                addProperty("mode", snapshot.mode)
                addProperty("stepsExecuted", snapshot.steps.count { it.status == "succeeded" })
                addProperty("stepsTotal", if (hybrid) snapshot.totalSteps.coerceAtLeast(0) else snapshot.totalSteps)
                if (hybrid) {
                    addProperty("resolverRounds", snapshot.rounds.coerceAtLeast(0))
                    addProperty("dispatchCount", snapshot.dispatchCount.coerceAtLeast(0))
                    addProperty("outcomeState", snapshot.outcomeState)
                    addProperty("templateStatus", snapshot.templateStatus)
                    addProperty("templateRevision", snapshot.templateRevision.coerceAtLeast(0))
                    addProperty("validationProgress", snapshot.validationProgress)
                    addProperty("promotionEligible", snapshot.promotionEligible)
                    addProperty("promotionIneligibleReason", snapshot.promotionIneligibleReason)
                    addProperty("fallbackStepIndex", snapshot.fallbackStepIndex.coerceAtLeast(0))
                    addProperty("compactTreeReads", snapshot.compactTreeReads.coerceAtLeast(0))
                    addProperty("fullTreeReads", snapshot.fullTreeReads.coerceAtLeast(0))
                }
            })
            add("steps", JsonArray().apply {
                snapshot.steps.forEach { add(stepRecord(it)) }
            })
        }
    }

    fun stepRecord(record: RpaStepRecord): JsonObject {
        val hybrid = record.mode == HYBRID_EXECUTION_MODE
        return JsonObject().apply {
            addProperty("index", if (hybrid) record.index.coerceAtLeast(0) else record.index)
            addProperty("stepId", record.stepId)
            addProperty("action", record.action)
            addProperty("status", record.status)
            addProperty("attempts", if (hybrid) record.attempts.coerceAtLeast(0) else record.attempts)
            addProperty("actionMs", if (hybrid) record.actionMs.coerceAtLeast(0L) else record.actionMs)
            addProperty("message", record.message)
            addProperty("errorCode", record.errorCode)
            addProperty("retryable", record.retryable)
            addProperty("startedAt", record.startedAt)
            addProperty("finishedAt", record.finishedAt)
            if (hybrid) {
                addProperty("resolverPolicy", record.resolverPolicy)
                addProperty("resolverUsed", record.resolverUsed)
                addProperty("treeSnapshotMs", record.treeSnapshotMs.coerceAtLeast(0L))
                addProperty("treeLookupMs", record.treeLookupMs.coerceAtLeast(0L))
                addProperty("treeCacheHit", record.treeCacheHit)
                addProperty("nodesVisited", record.nodesVisited.coerceAtLeast(0))
                addProperty("captureMs", record.captureMs.coerceAtLeast(0L))
                addProperty("matchMs", record.matchMs.coerceAtLeast(0L))
                addProperty("verifyMs", record.verifyMs.coerceAtLeast(0L))
                addProperty("frameId", record.frameId)
                addProperty("frameSource", record.frameSource)
                addProperty("frameAgeMs", record.frameAgeMs.coerceAtLeast(0L))
                addProperty("uiGeneration", record.uiGeneration.coerceAtLeast(0L))
                addProperty("outcomeState", record.outcomeState)
                addProperty("dispatchCount", record.dispatchCount.coerceAtLeast(0))
                addProperty("rounds", record.rounds.coerceAtLeast(0))
                addProperty("compactTreeReads", record.compactTreeReads.coerceAtLeast(0))
                addProperty("fullTreeReads", record.fullTreeReads.coerceAtLeast(0))
                addProperty("toolCallMs", record.toolCallMs.coerceAtLeast(0L))
                addProperty("mode", record.mode)
            }
        }
    }

    fun workflowSummary(workflow: RpaWorkflow): JsonObject {
        return JsonObject().apply {
            addProperty("workflowId", workflow.id)
            addProperty("name", workflow.name)
            addProperty("version", workflow.version)
            addProperty("stepsTotal", workflow.steps.size)
            if (workflow.executionMode == HYBRID_EXECUTION_MODE) {
                addProperty("schemaVersion", workflow.schemaVersion)
                addProperty("executionMode", workflow.executionMode)
                addProperty("templateId", workflow.templateId)
                addProperty("templateRevision", workflow.templateRevision)
                addProperty("targetProfileId", workflow.targetProfileId)
            }
            add("actions", JsonArray().apply {
                workflow.steps.forEach { add(it.action) }
            })
        }
    }

    private fun saturatingSum(
        records: List<RpaStepRecord>,
        value: (RpaStepRecord) -> Long
    ): Long {
        var total = 0L
        records.forEach { record -> total = saturatingAdd(total, value(record)) }
        return total
    }

    private fun saturatingAdd(left: Long, right: Long): Long {
        val safeLeft = left.coerceAtLeast(0L)
        val safeRight = right.coerceAtLeast(0L)
        return if (Long.MAX_VALUE - safeLeft < safeRight) Long.MAX_VALUE else safeLeft + safeRight
    }
}
