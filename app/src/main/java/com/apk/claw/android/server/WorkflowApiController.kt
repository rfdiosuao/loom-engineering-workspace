package com.apk.claw.android.server

import com.apk.claw.android.workflow.WorkflowTemplate
import com.apk.claw.android.workflow.WorkflowTemplateManager
import com.apk.claw.android.workflow.TemplateExecutionResult
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonArray
import fi.iki.elonen.NanoHTTPD

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

        val responseJson = JsonObject().apply {
            addProperty("success", result.success)
            addProperty("templateId", result.templateId)
            addProperty("templateName", template.name)
            addProperty("stepsExecuted", result.stepsExecuted)
            addProperty("stepsTotal", result.stepsTotal)
            addProperty("executionTimeMs", result.executionTimeMs)
            if (result.errorMessage != null) {
                addProperty("error", result.errorMessage)
            }
        }

        return jsonResponse(
            NanoHTTPD.Response.Status.OK,
            result.success,
            responseJson.toString(),
            result.errorMessage
        )
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
}
