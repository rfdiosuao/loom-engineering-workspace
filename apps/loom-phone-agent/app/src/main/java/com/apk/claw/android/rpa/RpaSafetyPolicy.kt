package com.apk.claw.android.rpa

import java.util.Locale

object RpaSafetyPolicy {
    data class Decision(
        val allowed: Boolean,
        val errorCode: String = "",
        val message: String = ""
    )

    private val blockedActions = setOf(
        "pay",
        "purchase",
        "buy",
        "checkout",
        "transfer",
        "delete",
        "remove",
        "uninstall",
        "factory_reset",
        "clear_data",
        "login",
        "authorize",
        "grant_permission"
    )

    private val sensitiveTokens = listOf(
        "pay",
        "payment",
        "purchase",
        "buy now",
        "checkout",
        "transfer",
        "delete",
        "remove",
        "uninstall",
        "factory reset",
        "clear data",
        "password",
        "privacy",
        "authorize",
        "login",
        "sign in",
        "grant",
        "permission",
        "支付",
        "付款",
        "转账",
        "购买",
        "立即购买",
        "下单",
        "删除",
        "卸载",
        "密码",
        "隐私",
        "授权",
        "登录",
        "同意并继续"
    )

    fun inspect(step: RpaStep): Decision {
        val action = RpaActionNormalizer.normalize(step.action)
        if (action in blockedActions) {
            return Decision(false, "safety_blocked", "RPA dangerous action blocked: $action")
        }

        val targetText = buildTargetText(step).lowercase(Locale.US)
        val token = sensitiveTokens.firstOrNull { targetText.contains(it.lowercase(Locale.US)) }
        if (token != null) {
            return Decision(false, "safety_blocked", "RPA sensitive target blocked: $token")
        }

        return Decision(true)
    }

    private fun buildTargetText(step: RpaStep): String {
        val values = mutableListOf<String>()
        values += step.action
        values += step.description
        step.params.forEach { (key, value) ->
            val keyLower = key.lowercase(Locale.US)
            if (
                keyLower.contains("text") ||
                keyLower.contains("label") ||
                keyLower.contains("description") ||
                keyLower.contains("desc") ||
                keyLower.contains("resource") ||
                keyLower.contains("reason")
            ) {
                values += value.toString()
            }
        }
        return values.joinToString(" ")
    }
}
