package com.apk.claw.android.server

import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.impl.InputTextTool
import com.apk.claw.android.wechat.WeChatAutoReplyPolicy
import com.apk.claw.android.wechat.WeChatScreenAnalyzer
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import fi.iki.elonen.NanoHTTPD

object WeChatAutoReplyApiController {
    fun handleAutoReply(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val authError = ToolApiController.checkAuth(session)
        if (authError != null) return authError

        val json = ToolApiController.parseJsonBody(session)
            ?: return response(false, errorData("invalid_json", "Invalid JSON body"))
        val replyText = stringAny(json, "replyText", "reply_text", "reply")
        val autoSend = boolAny(json, "autoSend", "auto_send") ?: false
        val allowGroupChat = boolAny(json, "allowGroupChat", "allow_group_chat") ?: false
        val whitelist = stringSetAny(json, "whitelist", "allowContacts", "allow_contacts")
        val contactOverride = stringAny(json, "contact", "contactName", "contact_name")

        val service = ClawAccessibilityService.getInstance()
            ?: return response(false, errorData("accessibility_reenable_required", "Accessibility service is not running"))
        val tree = service.screenTreeJson
            ?: return response(false, errorData("screen_tree_unavailable", "Screen tree unavailable"))
        val observed = WeChatScreenAnalyzer.analyze(tree)
        val contact = contactOverride.ifBlank { observed.contact }

        val data = observedData(observed, contact, replyText, autoSend)
        if (!observed.isWeChat) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "failed")
            data.addProperty("errorCode", "not_wechat")
            data.addProperty("message", "Current foreground app is not WeChat.")
            return response(false, data)
        }

        val decision = WeChatAutoReplyPolicy.decide(
            contact = contact,
            incomingText = observed.latestMessage,
            replyText = replyText,
            autoSend = autoSend,
            whitelist = whitelist,
            isGroupChat = observed.isGroupChat,
            allowGroupChat = allowGroupChat
        )
        data.addProperty("policyMode", decision.mode)
        data.addProperty("shouldSend", decision.shouldSend)
        if (!decision.allowed) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "blocked")
            data.addProperty("errorCode", decision.errorCode)
            data.addProperty("message", decision.message)
            return response(false, data)
        }

        if (observed.inputNodeId.isBlank()) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "failed")
            data.addProperty("errorCode", "input_not_found")
            data.addProperty("message", "WeChat input field not found on current screen.")
            return response(false, data)
        }
        if (!tapNodeById(service, tree, observed.inputNodeId)) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "failed")
            data.addProperty("errorCode", "input_focus_failed")
            data.addProperty("message", "Failed to focus WeChat input field.")
            return response(false, data)
        }

        val inputResult = InputTextTool().execute(mapOf("text" to replyText, "clear_first" to true))
        data.addProperty("drafted", inputResult.isSuccess)
        if (!inputResult.isSuccess) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "failed")
            data.addProperty("errorCode", "draft_failed")
            data.addProperty("message", inputResult.error ?: "Failed to draft WeChat reply.")
            return response(false, data)
        }
        data.add("events", JsonArray().apply {
            add(event("drafted", "Reply drafted in WeChat input field."))
        })

        if (!decision.shouldSend) {
            data.addProperty("success", true)
            data.addProperty("currentStep", "drafted")
            data.addProperty("sent", false)
            data.addProperty("message", "Reply drafted. Manual confirmation required.")
            return response(true, data)
        }

        sleepQuietly(180L)
        val postDraftTree = service.screenTreeJson ?: tree
        val postDraftObserved = WeChatScreenAnalyzer.analyze(postDraftTree)
        val sendNodeId = postDraftObserved.sendNodeId.ifBlank { observed.sendNodeId }
        if (sendNodeId.isBlank()) {
            data.addProperty("success", false)
            data.addProperty("currentStep", "send_failed")
            data.addProperty("sent", false)
            data.addProperty("errorCode", "send_button_not_found")
            data.addProperty("message", "Reply drafted, but WeChat send button was not found.")
            return response(false, data)
        }
        val sent = tapNodeById(service, postDraftTree, sendNodeId)
        data.addProperty("success", sent)
        data.addProperty("sent", sent)
        data.addProperty("currentStep", if (sent) "sent" else "send_failed")
        data.addProperty("message", if (sent) "Reply sent." else "Reply drafted, but tapping send failed.")
        if (!sent) data.addProperty("errorCode", "send_tap_failed")
        data.add("events", JsonArray().apply {
            add(event("drafted", "Reply drafted in WeChat input field."))
            add(event(if (sent) "sent" else "send_failed", if (sent) "Reply sent." else "Send tap failed."))
        })
        return response(sent, data)
    }

    private fun observedData(
        observed: WeChatScreenAnalyzer.Screen,
        contact: String,
        replyText: String,
        autoSend: Boolean
    ): JsonObject {
        return JsonObject().apply {
            addProperty("mode", "wechat_auto_reply")
            addProperty("currentStep", "observed")
            addProperty("currentPackage", observed.currentPackage)
            addProperty("isWeChat", observed.isWeChat)
            addProperty("contact", contact)
            addProperty("latestMessage", observed.latestMessage)
            addProperty("replyText", replyText)
            addProperty("autoSend", autoSend)
            addProperty("isGroupChat", observed.isGroupChat)
            addProperty("inputNodeId", observed.inputNodeId)
            addProperty("sendNodeId", observed.sendNodeId)
        }
    }

    private fun errorData(errorCode: String, message: String): JsonObject {
        return JsonObject().apply {
            addProperty("success", false)
            addProperty("mode", "wechat_auto_reply")
            addProperty("currentStep", "failed")
            addProperty("errorCode", errorCode)
            addProperty("message", message)
            addProperty("retryable", errorCode != "invalid_json")
        }
    }

    private fun response(success: Boolean, data: JsonObject): NanoHTTPD.Response {
        return LumiSecurityController.jsonElementResponse(NanoHTTPD.Response.Status.OK, success, data, if (success) null else data.stringOrEmpty("message"))
    }

    private fun tapNodeById(service: ClawAccessibilityService, tree: JsonObject, nodeId: String): Boolean {
        val node = tree.get("nodes")?.takeIf { it.isJsonArray }?.asJsonArray?.firstOrNull { element ->
            element.isJsonObject && element.asJsonObject.stringOrEmpty("id") == nodeId
        }?.asJsonObject ?: return false
        val bounds = node.get("bounds")?.takeIf { it.isJsonObject }?.asJsonObject ?: return false
        val x = bounds.intOrNull("centerX") ?: return false
        val y = bounds.intOrNull("centerY") ?: return false
        return service.performTap(x, y, 100L)
    }

    private fun event(type: String, message: String): JsonObject {
        return JsonObject().apply {
            addProperty("type", "wechat_auto_reply_$type")
            addProperty("time", System.currentTimeMillis())
            addProperty("message", message)
        }
    }

    private fun sleepQuietly(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private fun stringAny(json: JsonObject, vararg names: String): String {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            runCatching { value.asString.trim() }.getOrNull()
        }.orEmpty()
    }

    private fun boolAny(json: JsonObject, vararg names: String): Boolean? {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            runCatching { value.asBoolean }.getOrNull()
        }
    }

    private fun stringSetAny(json: JsonObject, vararg names: String): Set<String> {
        val value = names.firstNotNullOfOrNull { json.get(it) } ?: return emptySet()
        if (value.isJsonArray) {
            return value.asJsonArray.mapNotNull { item ->
                if (item.isJsonPrimitive) item.asString.trim().takeIf { it.isNotBlank() } else null
            }.toSet()
        }
        if (value.isJsonPrimitive) {
            return value.asString.split(",", "\n").map { it.trim() }.filter { it.isNotBlank() }.toSet()
        }
        return emptySet()
    }

    private fun JsonObject.stringOrEmpty(name: String): String {
        val value = get(name) ?: return ""
        if (value.isJsonNull) return ""
        return runCatching { value.asString.orEmpty() }.getOrDefault("")
    }

    private fun JsonObject.intOrNull(name: String): Int? {
        val value = get(name) ?: return null
        if (value.isJsonNull) return null
        return runCatching { value.asInt }.getOrNull()
    }
}
