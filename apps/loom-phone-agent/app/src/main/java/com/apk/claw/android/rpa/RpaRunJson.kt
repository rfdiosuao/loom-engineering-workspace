package com.apk.claw.android.rpa

import com.google.gson.JsonArray
import com.google.gson.JsonObject

object RpaRunJson {
    fun snapshot(snapshot: RpaRunSnapshot): JsonObject {
        return JsonObject().apply {
            addProperty("runId", snapshot.runId)
            addProperty("workflowId", snapshot.workflowId)
            addProperty("workflowName", snapshot.workflowName)
            addProperty("status", snapshot.status.wireName)
            addProperty("mode", snapshot.mode)
            addProperty("currentStep", snapshot.currentStep)
            addProperty("totalSteps", snapshot.totalSteps)
            addProperty("currentStepId", snapshot.currentStepId)
            addProperty("currentAction", snapshot.currentAction)
            addProperty("message", snapshot.message)
            addProperty("errorCode", snapshot.errorCode)
            addProperty("retryable", snapshot.retryable)
            addProperty("startedAt", snapshot.startedAt)
            addProperty("updatedAt", snapshot.updatedAt)
            addProperty("finishedAt", snapshot.finishedAt)
            addProperty("totalMs", snapshot.totalMs)
            add("metrics", JsonObject().apply {
                addProperty("totalMs", snapshot.totalMs)
                addProperty("rounds", 0)
                addProperty("mode", snapshot.mode)
                addProperty("stepsExecuted", snapshot.steps.count { it.status == "succeeded" })
                addProperty("stepsTotal", snapshot.totalSteps)
            })
            add("steps", JsonArray().apply {
                snapshot.steps.forEach { add(stepRecord(it)) }
            })
        }
    }

    fun stepRecord(record: RpaStepRecord): JsonObject {
        return JsonObject().apply {
            addProperty("index", record.index)
            addProperty("stepId", record.stepId)
            addProperty("action", record.action)
            addProperty("status", record.status)
            addProperty("attempts", record.attempts)
            addProperty("actionMs", record.actionMs)
            addProperty("message", record.message)
            addProperty("errorCode", record.errorCode)
            addProperty("retryable", record.retryable)
            addProperty("startedAt", record.startedAt)
            addProperty("finishedAt", record.finishedAt)
        }
    }

    fun workflowSummary(workflow: RpaWorkflow): JsonObject {
        return JsonObject().apply {
            addProperty("workflowId", workflow.id)
            addProperty("name", workflow.name)
            addProperty("version", workflow.version)
            addProperty("stepsTotal", workflow.steps.size)
            add("actions", JsonArray().apply {
                workflow.steps.forEach { add(it.action) }
            })
        }
    }
}
