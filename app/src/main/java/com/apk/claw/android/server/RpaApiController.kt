package com.apk.claw.android.server

import com.apk.claw.android.rpa.RpaActionNormalizer
import com.apk.claw.android.rpa.RpaRunJson
import com.apk.claw.android.rpa.RpaWorkflowParser
import com.apk.claw.android.rpa.RpaWorkflowRunner
import com.apk.claw.android.utils.XLog
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD

object RpaApiController {
    private const val TAG = "RpaApiController"

    fun handleRun(session: NanoHTTPD.IHTTPSession, requireToken: Boolean = true): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return response(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                ApiErrorPayload.build("invalid_json", "Invalid JSON body", "rpa", retryable = false),
                "Invalid JSON body"
            )

        return try {
            val parsed = RpaWorkflowParser.parseRunRequest(json)
            val validationErrors = RpaWorkflowParser.validate(parsed.workflow)
            if (validationErrors.isNotEmpty()) {
                return response(
                    NanoHTTPD.Response.Status.OK,
                    false,
                    ApiErrorPayload.build(
                        errorCode = "invalid_workflow",
                        message = validationErrors.joinToString("; "),
                        mode = "rpa",
                        currentStep = "validate",
                        retryable = false
                    ),
                    validationErrors.joinToString("; ")
                )
            }

            val result = RpaWorkflowRunner.start(parsed.workflow)
            if (!result.accepted) {
                return response(
                    NanoHTTPD.Response.Status.OK,
                    false,
                    ApiErrorPayload.build(
                        errorCode = result.errorCode,
                        message = result.message,
                        mode = "rpa",
                        currentStep = "precheck",
                        retryable = result.retryable
                    ),
                    result.message
                )
            }

            val snapshot = result.snapshot!!
            val data = RpaRunJson.snapshot(snapshot).apply {
                addProperty("accepted", true)
                add("workflow", RpaRunJson.workflowSummary(parsed.workflow))
            }
            response(NanoHTTPD.Response.Status.OK, true, data, null)
        } catch (e: Exception) {
            XLog.e(TAG, "RPA run request failed: ${e.message}")
            response(
                NanoHTTPD.Response.Status.OK,
                false,
                ApiErrorPayload.build(
                    errorCode = "invalid_workflow",
                    message = e.message ?: "Invalid RPA workflow",
                    mode = "rpa",
                    currentStep = "validate",
                    retryable = false
                ),
                e.message ?: "Invalid RPA workflow"
            )
        }
    }

    fun handleValidate(session: NanoHTTPD.IHTTPSession, requireToken: Boolean = true): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return response(
                NanoHTTPD.Response.Status.BAD_REQUEST,
                false,
                ApiErrorPayload.build("invalid_json", "Invalid JSON body", "rpa", currentStep = "validate"),
                "Invalid JSON body"
            )

        return try {
            val parsed = RpaWorkflowParser.parseRunRequest(json)
            val errors = RpaWorkflowParser.validate(parsed.workflow)
            val data = JsonObject().apply {
                addProperty("valid", errors.isEmpty())
                add("workflow", RpaRunJson.workflowSummary(parsed.workflow))
                add("errors", JsonArray().apply { errors.forEach { add(it) } })
            }
            response(NanoHTTPD.Response.Status.OK, errors.isEmpty(), data, errors.firstOrNull())
        } catch (e: Exception) {
            val data = ApiErrorPayload.build(
                errorCode = "invalid_workflow",
                message = e.message ?: "Invalid RPA workflow",
                mode = "rpa",
                currentStep = "validate"
            )
            response(NanoHTTPD.Response.Status.OK, false, data, e.message ?: "Invalid RPA workflow")
        }
    }

    fun handleGetRun(
        session: NanoHTTPD.IHTTPSession,
        runId: String,
        requireToken: Boolean = true
    ): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val snapshot = RpaWorkflowRunner.get(runId)
            ?: return response(
                NanoHTTPD.Response.Status.NOT_FOUND,
                false,
                ApiErrorPayload.build("rpa_run_not_found", "RPA run not found: $runId", "rpa"),
                "RPA run not found"
            )
        return response(NanoHTTPD.Response.Status.OK, true, RpaRunJson.snapshot(snapshot), null)
    }

    fun handleListRuns(session: NanoHTTPD.IHTTPSession, requireToken: Boolean = true): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val runs = RpaWorkflowRunner.list()
        val data = JsonObject().apply {
            addProperty("count", runs.size)
            add("runs", JsonArray().apply {
                runs.forEach { add(RpaRunJson.snapshot(it)) }
            })
        }
        return response(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    fun handleCancel(
        session: NanoHTTPD.IHTTPSession,
        runId: String,
        requireToken: Boolean = true
    ): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val snapshot = RpaWorkflowRunner.cancel(runId)
            ?: return response(
                NanoHTTPD.Response.Status.NOT_FOUND,
                false,
                ApiErrorPayload.build("rpa_run_not_found", "RPA run not found: $runId", "rpa"),
                "RPA run not found"
            )
        return response(NanoHTTPD.Response.Status.OK, true, RpaRunJson.snapshot(snapshot), null)
    }

    fun handleCapabilities(session: NanoHTTPD.IHTTPSession, requireToken: Boolean = true): NanoHTTPD.Response {
        val authError = checkAuthIfNeeded(session, requireToken)
        if (authError != null) return authError

        val data = JsonObject().apply {
            addProperty("schema", "apkclaw.rpa.v1")
            addProperty("mode", "rpa")
            addProperty("llmRequired", false)
            addProperty("statefulRuns", true)
            addProperty("cancelSupported", true)
            addProperty("statusSupported", true)
            add("actions", JsonArray().apply {
                RpaActionNormalizer.supportedActions().forEach { add(it) }
            })
        }
        return response(NanoHTTPD.Response.Status.OK, true, data, null)
    }

    private fun checkAuthIfNeeded(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean
    ): NanoHTTPD.Response? {
        if (!requireToken) return null
        return if (TokenValidator.validate(session)) {
            null
        } else {
            response(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                false,
                ApiErrorPayload.build("unauthorized", "Unauthorized: invalid or missing token", "rpa"),
                "Unauthorized: invalid or missing token"
            )
        }
    }

    private fun response(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonObject?,
        error: String?
    ): NanoHTTPD.Response {
        return LumiSecurityController.jsonElementResponse(status, success, data, error)
    }
}
