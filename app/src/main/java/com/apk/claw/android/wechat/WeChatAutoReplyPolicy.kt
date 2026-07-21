package com.apk.claw.android.wechat

import java.util.Locale

object WeChatAutoReplyPolicy {
    data class Decision(
        val allowed: Boolean,
        val shouldSend: Boolean,
        val mode: String,
        val errorCode: String = "",
        val message: String = ""
    )

    private val sensitiveTokens = listOf(
        "验证码",
        "校验码",
        "动态码",
        "密码",
        "登录",
        "授权",
        "隐私",
        "身份证",
        "银行卡",
        "转账",
        "收款",
        "付款",
        "支付",
        "删除",
        "password",
        "code",
        "otp",
        "login",
        "authorize",
        "payment",
        "pay",
        "transfer",
        "bank",
        "privacy",
        "delete"
    )

    fun decide(
        contact: String,
        incomingText: String,
        replyText: String,
        autoSend: Boolean,
        whitelist: Set<String>,
        isGroupChat: Boolean = false,
        allowGroupChat: Boolean = false
    ): Decision {
        val normalizedContact = contact.trim()
        val normalizedReply = replyText.trim()
        if (normalizedReply.isBlank()) {
            return Decision(false, false, "blocked", "empty_reply", "Reply text is empty.")
        }
        if (isGroupChat && !allowGroupChat) {
            return Decision(false, false, "blocked", "group_chat_blocked", "Group chat auto reply is disabled by default.")
        }
        if (containsSensitive(incomingText) || containsSensitive(normalizedReply)) {
            return Decision(false, false, "blocked", "sensitive_content_blocked", "Sensitive content requires manual confirmation.")
        }
        if (!autoSend) {
            return Decision(true, false, "draft_only")
        }
        if (normalizedContact.isBlank() || whitelist.none { it.trim().equals(normalizedContact, ignoreCase = true) }) {
            return Decision(false, false, "blocked", "contact_not_whitelisted", "Auto send requires a whitelisted contact.")
        }
        return Decision(true, true, "auto_send")
    }

    private fun containsSensitive(value: String): Boolean {
        val text = value.lowercase(Locale.US)
        return sensitiveTokens.any { token -> text.contains(token.lowercase(Locale.US)) }
    }
}
