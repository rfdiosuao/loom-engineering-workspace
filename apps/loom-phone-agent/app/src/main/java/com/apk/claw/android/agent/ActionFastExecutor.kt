package com.apk.claw.android.agent

import com.google.gson.JsonObject
import java.util.Locale

object ActionFastExecutor {
    data class WaitTarget(
        val kind: String,
        val value: String
    )

    data class ClickTarget(
        val kind: String,
        val value: String
    )

    private val dangerousActions = setOf(
        "delete",
        "remove",
        "uninstall",
        "pay",
        "purchase",
        "buy",
        "login",
        "authorize",
        "grant",
        "clear_data"
    )

    private val sensitiveTargetTokens = listOf(
        "pay",
        "payment",
        "purchase",
        "transfer",
        "delete",
        "remove",
        "uninstall",
        "password",
        "privacy",
        "authorize",
        "permission",
        "login",
        "支付",
        "付款",
        "转账",
        "购买",
        "删除",
        "卸载",
        "密码",
        "隐私",
        "授权",
        "登录"
    )

    fun normalizeAction(value: String?): String {
        val action = value.orEmpty().trim().lowercase(Locale.US).replace("-", "_")
        return when (action) {
            "tap_text", "click_label", "tap_label", "text_click" -> "click_text"
            "tap_node", "node_click" -> "click_node"
            "tap_ref", "ref_click", "click_ref", "selector_click", "click_selector" -> "click_ref"
            "tap_description", "tap_desc", "click_desc", "click_content_description", "tap_content_description" -> "click_description"
            "tap_element", "click_element" -> "click_element"
            "input_text", "type", "type_text", "set_text" -> "input"
            "press_back", "system_back" -> "back"
            "press_home", "system_home" -> "home"
            "wait_for_text", "wait_until_text", "wait_element" -> "wait_text"
            "open_settings", "settings" -> "open_app"
            else -> action
        }
    }

    fun rejectDangerous(action: String?, text: String?): String? {
        val normalized = normalizeAction(action)
        if (normalized in dangerousActions) {
            return "dangerous action blocked: $normalized"
        }
        val target = text.orEmpty().lowercase(Locale.US)
        val sensitive = sensitiveTargetTokens.firstOrNull { token -> target.contains(token.lowercase(Locale.US)) }
        return if (sensitive != null) {
            "sensitive target blocked: $sensitive"
        } else {
            null
        }
    }

    fun safetyTextFrom(json: JsonObject): String {
        return listOfNotNull(
            firstString(json, "text", "targetText", "target_text"),
            firstString(json, "targetLabel", "target_label", "label"),
            firstString(json, "contentDescription", "content_description", "description", "desc", "targetDescription", "target_description"),
            firstString(json, "resourceId", "resource_id", "viewId", "view_id"),
            firstString(json, "reason")
        ).joinToString(" ")
    }

    fun waitTargetFrom(json: JsonObject): WaitTarget? {
        firstString(json, "text", "targetText", "target_text", "label")?.let { value ->
            return WaitTarget("text", value)
        }
        firstString(json, "resourceId", "resource_id", "viewId", "view_id")?.let { value ->
            return WaitTarget("resource_id", value)
        }
        firstString(json, "contentDescription", "content_description", "description", "desc", "targetDescription", "target_description")?.let { value ->
            return WaitTarget("description", value)
        }
        return null
    }

    fun refFrom(json: JsonObject): String? {
        return firstString(json, "ref", "targetRef", "target_ref", "selectorRef", "selector_ref", "snapshotRef", "snapshot_ref")
    }

    fun clickTargetFrom(json: JsonObject): ClickTarget? {
        firstString(json, "text", "targetText", "target_text", "label")?.let { value ->
            return ClickTarget("text", value)
        }
        firstString(json, "contentDescription", "content_description", "description", "desc", "targetDescription", "target_description")?.let { value ->
            return ClickTarget("description", value)
        }
        firstString(json, "resourceId", "resource_id", "viewId", "view_id")?.let { value ->
            return ClickTarget("resource_id", value)
        }
        return null
    }

    private fun firstString(json: JsonObject, vararg names: String): String? {
        return names.firstNotNullOfOrNull { name ->
            val value = json.get(name) ?: return@firstNotNullOfOrNull null
            if (value.isJsonNull) return@firstNotNullOfOrNull null
            value.asString?.trim()?.takeIf { it.isNotEmpty() }
        }
    }
}
