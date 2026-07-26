package com.apk.claw.android.server

import android.app.KeyguardManager
import android.content.Context
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.rpa.HYBRID_EXECUTION_MODE
import com.apk.claw.android.rpa.RpaWorkflowRunner
import com.apk.claw.android.service.AccessibilityStateInspector
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.workflow.DeviceProfileProvider
import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateValidationScheduler
import com.apk.claw.android.workflow.ValidationReadiness
import com.apk.claw.android.workflow.ValidationResetResult
import com.apk.claw.android.workflow.ValidationResult
import com.apk.claw.android.workflow.ValidationScheduleResult
import com.apk.claw.android.workflow.WorkflowTemplate
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.workflow.TemplateExecutionResult
import com.apk.claw.android.workflow.ValidationSkipReason
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonArray
import fi.iki.elonen.NanoHTTPD
import java.util.UUID

/**
 * Workflow 模板 API 控制器
 * 提供模板管理、模板执行的 HTTP API
 */
object WorkflowApiController {

    private const val TAG = "WorkflowApiController"
    private const val MIME_JSON_UTF8 = "application/json; charset=utf-8"
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create()

    /**
     * 验证 Token
     */
    fun checkAuth(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response? {
        if (!TokenValidator.validate(session)) {
            XLog.w(TAG, "Unauthorized API request from ${session.remoteIpAddress}")
            return jsonResponse(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                false,
                null,
                "Unauthorized: invalid or missing token"
            )
        }
        return null
    }

    internal fun authorizeLifecycle(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean,
        validator: (NanoHTTPD.IHTTPSession) -> Boolean = TokenValidator::validate
    ): NanoHTTPD.Response? {
        if (!requireToken || validator(session)) return null
        return LumiSecurityController.jsonElementResponse(
            NanoHTTPD.Response.Status.UNAUTHORIZED,
            false,
            ApiErrorPayload.build(
                errorCode = "unauthorized",
                message = "Unauthorized: invalid or missing token",
                mode = "workflow",
                currentStep = "authorize",
                retryable = false
            ),
            "Unauthorized: invalid or missing token"
        )
    }

    internal fun validationFailure(reason: ValidationSkipReason): JsonObject {
        val contract = when (reason) {
            ValidationSkipReason.TASK_QUEUE_BUSY -> ValidationError("task_busy", "Agent task queue is busy", "precheck", true)
            ValidationSkipReason.RPA_BUSY,
            ValidationSkipReason.VALIDATION_ALREADY_ACTIVE -> ValidationError("rpa_busy", "RPA validation is busy", "precheck", true)
            ValidationSkipReason.ACCESSIBILITY_UNHEALTHY ->
                ValidationError("accessibility_unavailable", "Accessibility service is unavailable", "precheck", true)
            ValidationSkipReason.PROFILE_MISMATCH ->
                ValidationError("profile_mismatch", "Fresh foreground profile does not match the template", "profile", false)
            ValidationSkipReason.RISK_NOT_ALLOWED ->
                ValidationError("risk_not_allowed", "Template risk is not eligible for automatic validation", "risk", false)
            ValidationSkipReason.DEVICE_LOCKED -> ValidationError("device_locked", "Device is locked", "precheck", true)
            ValidationSkipReason.PACKAGE_NOT_RESTORABLE ->
                ValidationError("package_not_restorable", "Template package cannot be restored", "reset", false)
            ValidationSkipReason.RESET_NOT_RESTORABLE ->
                ValidationError("reset_not_restorable", "Template reset state cannot be restored", "reset", false)
            ValidationSkipReason.TEMPLATE_NOT_VALIDATABLE ->
                ValidationError("template_not_validatable", "Template lifecycle state cannot be validated", "validate", false)
        }
        return ApiErrorPayload.build(
            errorCode = contract.errorCode,
            message = contract.message,
            mode = "hybrid_rpa",
            currentStep = contract.currentStep,
            retryable = contract.retryable
        )
    }

    private data class ValidationError(
        val errorCode: String,
        val message: String,
        val currentStep: String,
        val retryable: Boolean
    )

    fun handleValidateTemplate(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response {
        authorizeLifecycle(session, requireToken)?.let { return it }
        val request = ToolApiController.parseJsonBody(session)
            ?: return lifecycleFailure("invalid_json", "Invalid JSON body", "validate")
        val templateId = request.optionalString("templateId")
            ?: request.optionalString("template_id")
            ?: return lifecycleFailure("missing_template_id", "Missing required parameter: templateId", "validate")
        val template = WorkflowTemplateManager.getTemplate(templateId)
            ?: return lifecycleFailure("template_not_found", "Template not found", "validate")
        val expectedRevision = request.optionalPositiveInt("templateRevision", "template_revision")
        if (request.hasAny("templateRevision", "template_revision") && expectedRevision == null) {
            return lifecycleFailure("invalid_template_revision", "templateRevision must be positive", "validate")
        }
        if (expectedRevision != null && expectedRevision != template.revision) {
            return lifecycleFailure("revision_conflict", "Template revision has changed", "validate")
        }
        if (!RpaWorkflowRunner.isHybridEngineInstalled()) {
            return lifecycleFailure(
                "hybrid_engine_unavailable",
                "Hybrid RPA engine is not configured",
                "precheck"
            )
        }

        val scheduler = TemplateValidationScheduler(
            readiness = { current -> validationReadiness(current) },
            reset = { current -> resetTemplate(current) },
            execute = { current, resetId -> executeValidation(current, resetId) },
            persist = { updated -> WorkflowTemplateManager.persistValidationRevision(updated) }
        )
        return when (val scheduled = scheduler.enqueue(template)) {
            is ValidationScheduleResult.Skipped -> lifecycleResponse(
                NanoHTTPD.Response.Status.OK,
                false,
                validationFailure(scheduled.reason),
                validationFailure(scheduled.reason)["message"].asString
            )
            is ValidationScheduleResult.Completed -> lifecycleResponse(
                NanoHTTPD.Response.Status.OK,
                true,
                templateLifecycleJson(scheduled.template).apply {
                    addProperty("resetSucceeded", scheduled.resetSucceeded)
                    addProperty("stepsExecuted", scheduled.stepsExecuted)
                },
                null
            )
        }
    }

    fun handleDisableTemplate(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response {
        authorizeLifecycle(session, requireToken)?.let { return it }
        val request = ToolApiController.parseJsonBody(session)
            ?: return lifecycleFailure("invalid_json", "Invalid JSON body", "disable")
        val templateId = request.optionalString("templateId")
            ?: request.optionalString("template_id")
            ?: return lifecycleFailure("missing_template_id", "Missing required parameter: templateId", "disable")
        val expectedRevision = request.optionalPositiveInt("templateRevision", "template_revision")
        if (request.hasAny("templateRevision", "template_revision") && expectedRevision == null) {
            return lifecycleFailure("invalid_template_revision", "templateRevision must be positive", "disable")
        }
        return when (val result = WorkflowTemplateManager.disableTemplate(templateId, expectedRevision)) {
            WorkflowTemplateManager.DisableResult.NotFound ->
                lifecycleFailure("template_not_found", "Template not found", "disable")
            is WorkflowTemplateManager.DisableResult.RevisionConflict ->
                lifecycleFailure("revision_conflict", "Template revision has changed", "disable")
            is WorkflowTemplateManager.DisableResult.Disabled -> lifecycleResponse(
                NanoHTTPD.Response.Status.OK,
                true,
                templateLifecycleJson(result.template).apply {
                    addProperty("changed", result.changed)
                    addProperty("idempotent", !result.changed)
                },
                null
            )
        }
    }

    private fun validationReadiness(template: WorkflowTemplate): ValidationReadiness {
        val app = ClawApplication.instance
        val keyguard = app.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val accessibility = AccessibilityStateInspector.inspect(app)
        val packageRestorable = template.targetPackage.isNotBlank() && runCatching {
            app.packageManager.getPackageInfo(template.targetPackage, 0)
        }.isSuccess
        return ValidationReadiness(
            taskQueueIdle = AgentApiController.isIdleForTemplateValidation(),
            deviceUnlocked = keyguard?.isKeyguardLocked != true,
            accessibilityHealthy = accessibility.healthy,
            expectedPackageRestorable = packageRestorable,
            resetRestorable = template.targetPackage.isNotBlank(),
            profileId = DeviceProfileProvider.current()
        )
    }

    private fun resetTemplate(template: WorkflowTemplate): ValidationResetResult {
        val resetId = "reset-${UUID.randomUUID().toString().take(16)}"
        val result = ToolRegistry.executeTool(
            "open_app",
            mapOf(
                "package_name" to template.targetPackage,
                "verify_foreground" to true,
                "check_launch_dialog" to false,
                "force_reopen" to true,
                "wait_after" to 0
            )
        )
        val restored = result.isSuccess && DeviceProfileProvider.current() == template.targetProfileId
        return ValidationResetResult(resetId, restored)
    }

    private fun executeValidation(template: WorkflowTemplate, resetId: String): ValidationResult {
        val result = RpaWorkflowRunner.runHybridValidation(WorkflowTemplateManager.toHybridWorkflow(template))
        val steps = result?.steps.orEmpty()
        val covered = steps.mapNotNull { record ->
            record.resolverUsed.takeIf { it.isNotBlank() }?.let { name ->
                runCatching { ResolverKind.valueOf(name) }.getOrNull()
            }
        }.toSet()
        return ValidationResult(
            profileId = DeviceProfileProvider.current(),
            resetId = resetId,
            success = result?.success == true,
            coveredResolvers = covered,
            allOutcomesVerified = result?.success == true &&
                steps.size == template.steps.size && steps.all { it.outcomeState == "verified" },
            usedStaleFrame = steps.any { it.frameSource.isNotBlank() && it.frameSource != "fresh" },
            serviceRebound = result?.errorCode in setOf("service_generation_changed", "service_instance_changed"),
            retriedAfterDispatch = steps.any { it.attempts > 1 && it.dispatchCount > 1 },
            unresolvedWindows = result?.errorCode in setOf("target_unresolved", "target_ambiguous"),
            templateRevision = template.revision
        )
    }

    private fun templateLifecycleJson(template: WorkflowTemplate): JsonObject = JsonObject().apply {
        addProperty("templateId", template.id)
        addProperty("templateStatus", template.status.name.lowercase())
        addProperty("templateRevision", template.revision)
        addProperty(
            "validationProgress",
            "${template.validationState.consecutiveSuccesses.coerceIn(0, template.validationState.target)}/${template.validationState.target}"
        )
        addProperty("promotionEligible", template.riskLevel in setOf(TemplateRiskLevel.READ_ONLY, TemplateRiskLevel.REVERSIBLE))
        addProperty(
            "promotionIneligibleReason",
            if (template.riskLevel in setOf(TemplateRiskLevel.READ_ONLY, TemplateRiskLevel.REVERSIBLE)) "" else "risk_not_allowed"
        )
        addProperty("executionMode", template.executionMode)
    }

    private fun lifecycleFailure(
        errorCode: String,
        message: String,
        currentStep: String,
        retryable: Boolean = false
    ): NanoHTTPD.Response = lifecycleResponse(
        NanoHTTPD.Response.Status.OK,
        false,
        ApiErrorPayload.build(errorCode, message, HYBRID_EXECUTION_MODE, currentStep, retryable),
        message
    )

    private fun lifecycleResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonObject,
        error: String?
    ): NanoHTTPD.Response = LumiSecurityController.jsonElementResponse(status, success, data, error)

    /**
     * 获取所有模板
     * GET /api/workflow/templates
     */
    fun handleGetTemplates(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val templates = WorkflowTemplateManager.getAllTemplates()
        val arr = JsonArray()

        for (template in templates) {
            val obj = JsonObject().apply {
                addProperty("id", template.id)
                addProperty("name", template.name)
                addProperty("description", template.description)
                addProperty("taskPattern", template.taskPattern)
                addProperty("appName", template.appName ?: "")
                addProperty("successCount", template.successCount)
                addProperty("failCount", template.failCount)
                addProperty("successRate", template.successRate())
                addProperty("lastUsedAt", template.lastUsedAt)
                addProperty("createdAt", template.createdAt)
                addProperty("templateStatus", template.status.name.lowercase())
                addProperty("templateRevision", template.revision)
                addProperty(
                    "validationProgress",
                    "${template.validationState.consecutiveSuccesses.coerceIn(0, template.validationState.target)}/${template.validationState.target}"
                )
                addProperty("executionMode", template.executionMode)
                // 步骤概要
                val stepsArr = JsonArray()
                for (step in template.steps) {
                    stepsArr.add(JsonObject().apply {
                        addProperty("toolName", step.toolName)
                        addProperty("description", step.description)
                    })
                }
                add("stepsSummary", stepsArr)
            }
            arr.add(obj)
        }

        val result = JsonObject().apply {
            addProperty("success", true)
            addProperty("count", templates.size)
            add("templates", arr)
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, true, result.toString(), null)
    }

    /**
     * 获取单个模板详情
     * GET /api/workflow/template?id=xxx
     */
    fun handleGetTemplate(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val templateId = session.parameters["id"]?.firstOrNull() ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing parameter: id"
        )

        val template = WorkflowTemplateManager.getTemplate(templateId.toString())
        if (template == null) {
            return jsonResponse(NanoHTTPD.Response.Status.OK, false, null, "Template not found")
        }

        // 完整模板详情
        val templateJson = gson.toJson(template)

        val result = JsonObject().apply {
            addProperty("success", true)
            add("template", gson.fromJson(templateJson, JsonObject::class.java))
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, true, result.toString(), null)
    }

    /**
     * 执行模板
     * POST /api/workflow/execute
     * Body: {"templateId": "xxx", "params": {"contact_name": "张三", "message": "你好"}}
     */
    fun handleExecuteTemplate(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val templateId = json.get("templateId")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing required parameter: templateId"
        )

        val template = WorkflowTemplateManager.getTemplate(templateId)
        if (template == null) {
            return jsonResponse(NanoHTTPD.Response.Status.OK, false, null, "Template not found")
        }

        // 解析参数
        val params = mutableMapOf<String, String>()
        if (json.has("params")) {
            val paramsJson = json.getAsJsonObject("params")
            paramsJson.entrySet().forEach { (key, value) ->
                if (value.isJsonPrimitive) {
                    params[key] = value.asString
                }
            }
        }

        XLog.i(TAG, "Executing template: ${template.name}, params=$params")

        // 执行模板
        val result = WorkflowTemplateManager.executeTemplate(template, params)

        val responseJson = templateExecutionJson(template, result)

        return jsonResponse(
            NanoHTTPD.Response.Status.OK,
            result.success,
            responseJson.toString(),
            result.errorMessage
        )
    }

    internal fun templateExecutionJson(
        template: WorkflowTemplate,
        result: TemplateExecutionResult
    ): JsonObject = JsonObject().apply {
        addProperty("success", result.success)
        addProperty("templateId", result.templateId)
        addProperty("templateName", template.name)
        addProperty("stepsExecuted", result.stepsExecuted)
        addProperty("stepsTotal", result.stepsTotal)
        addProperty("executionTimeMs", result.executionTimeMs)
        addProperty("mode", result.mode)
        addProperty("outcomeState", result.outcomeState)
        if (result.errorMessage != null) {
            addProperty("error", result.errorMessage)
        }
        if (!result.success) {
            val message = result.errorMessage ?: "Template execution failed"
            val errorCode = result.errorCode.ifBlank { "template_execution_failed" }
            addProperty("errorCode", errorCode)
            addProperty("message", message)
            addProperty(
                "currentStep",
                if (errorCode in setOf("template_status_invalid", "profile_mismatch")) "authorize" else "execute"
            )
            addProperty("retryable", false)
        }
    }

    /**
     * 创建模板
     * POST /api/workflow/create
     * Body: {
     *   "name": "微信发消息",
     *   "description": "打开微信，给联系人发送消息",
     *   "taskPattern": "微信.*发消息",
     *   "keywords": ["微信", "发消息"],
     *   "appName": "微信",
     *   "steps": [
     *     {"toolName": "open_app", "paramsTemplate": {"package_name": "com.tencent.mm"}, "description": "打开微信"},
     *     {"toolName": "wait", "paramsTemplate": {"duration_ms": 2000}, "description": "等待加载"},
     *     ...
     *   ]
     * }
     */
    fun handleCreateTemplate(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val name = json.optionalString("name") ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: name"
        )
        val description = json.optionalString("description") ?: ""
        val taskPattern = json.optionalString("taskPattern") ?: ""
        val appName = json.optionalString("appName")?.takeIf { it.isNotBlank() }

        // 关键词
        val keywords = mutableListOf<String>()
        if (json.has("keywords")) {
            val keywordsArr = json.getAsJsonArray("keywords")
            keywordsArr.forEach { elem ->
                keywords.add(elem.asString)
            }
        }

        // 步骤
        val steps = mutableListOf<WorkflowTemplate.WorkflowStep>()
        if (json.has("steps")) {
            val stepsArr = json.getAsJsonArray("steps")
            stepsArr.forEach { elem ->
                val stepObj = elem.asJsonObject
                val toolName = stepObj.get("toolName").asString
                val description = stepObj.get("description")?.asString ?: toolName
                val waitFor = stepObj.get("waitFor")?.asInt ?: 500
                val isVerification = stepObj.get("isVerification")?.asBoolean ?: false

                val paramsTemplate = mutableMapOf<String, Any>()
                if (stepObj.has("paramsTemplate")) {
                    val paramsObj = stepObj.getAsJsonObject("paramsTemplate")
                    paramsObj.entrySet().forEach { (key, value) ->
                        when {
                            value.isJsonNull -> {}
                            !value.isJsonPrimitive -> paramsTemplate[key] = value.toString()
                            value.asJsonPrimitive.isNumber -> paramsTemplate[key] = value.asNumber
                            value.asJsonPrimitive.isBoolean -> paramsTemplate[key] = value.asBoolean
                            else -> paramsTemplate[key] = value.asString
                        }
                    }
                }

                steps.add(WorkflowTemplate.WorkflowStep(
                    toolName = toolName,
                    paramsTemplate = paramsTemplate,
                    description = description,
                    waitFor = waitFor,
                    isVerification = isVerification
                ))
            }
        }

        if (steps.isEmpty()) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Template must have at least one step")
        }

        val template = WorkflowTemplateManager.createTemplate(
            name = name,
            description = description,
            taskPattern = taskPattern,
            keywords = keywords,
            appName = appName,
            steps = steps
        )

        XLog.i(TAG, "Template created: $name, id=${template.id}")

        val result = JsonObject().apply {
            addProperty("success", true)
            addProperty("templateId", template.id)
            addProperty("name", template.name)
            addProperty("message", "Template created successfully")
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, true, result.toString(), null)
    }

    /**
     * 删除模板
     * POST /api/workflow/delete
     * Body: {"templateId": "xxx"}
     */
    fun handleDeleteTemplate(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val templateId = json.get("templateId")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: templateId"
        )

        val deleted = WorkflowTemplateManager.deleteTemplate(templateId)

        val result = JsonObject().apply {
            addProperty("success", deleted)
            addProperty("templateId", templateId)
            if (deleted) {
                addProperty("message", "Template deleted")
            } else {
                addProperty("error", "Template not found")
            }
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, deleted, result.toString(), null)
    }

    /**
     * 匹配模板（测试）
     * POST /api/workflow/match
     * Body: {"prompt": "微信给张三发消息说你好"}
     * 返回匹配的最佳模板，不执行
     */
    fun handleMatchTemplate(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
        if (json == null) {
            return jsonResponse(NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Invalid JSON body")
        }

        val prompt = json.get("prompt")?.asString ?: return jsonResponse(
            NanoHTTPD.Response.Status.BAD_REQUEST, false, null, "Missing: prompt"
        )

        val template = WorkflowTemplateManager.matchTemplate(prompt)

        val result = JsonObject().apply {
            addProperty("success", template != null)
            addProperty("prompt", prompt)
            if (template != null) {
                addProperty("templateId", template.id)
                addProperty("templateName", template.name)
                addProperty("successRate", template.successRate())
            } else {
                addProperty("message", "No matching template found")
            }
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, true, result.toString(), null)
    }

    /**
     * 清空所有模板
     * POST /api/workflow/clear
     */
    fun handleClearTemplates(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = checkAuth(session)
        if (authError != null) return authError

        WorkflowTemplateManager.clearAllTemplates()

        val result = JsonObject().apply {
            addProperty("success", true)
            addProperty("message", "All templates cleared")
        }

        return jsonResponse(NanoHTTPD.Response.Status.OK, true, result.toString(), null)
    }

    private fun jsonResponse(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: String?,
        error: String?
    ): NanoHTTPD.Response {
        val json = JsonObject().apply {
            addProperty("success", success)
            if (data != null) addProperty("data", data)
            if (error != null) addProperty("error", error)
        }
        val response = NanoHTTPD.newFixedLengthResponse(status, MIME_JSON_UTF8, json.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.addHeader("Access-Control-Allow-Headers", "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN")
        return response
    }

    private fun JsonObject.optionalString(name: String): String? {
        return get(name)?.takeIf { it.isJsonPrimitive }?.let {
            runCatching { it.asString }.getOrNull()
        }
    }

    private fun JsonObject.hasAny(vararg names: String): Boolean = names.any(::has)

    private fun JsonObject.optionalPositiveInt(vararg names: String): Int? {
        val value = names.firstNotNullOfOrNull { name -> get(name) } ?: return null
        if (!value.isJsonPrimitive || !value.asJsonPrimitive.isNumber) return null
        return runCatching { value.asInt }.getOrNull()?.takeIf { it > 0 }
    }
}
