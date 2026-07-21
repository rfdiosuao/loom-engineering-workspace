package com.apk.claw.android.server

import com.google.gson.JsonObject
import java.util.Locale

object VisionSafetyGuard {
    private val MUTATING_ACTIONS = setOf("tap", "long_press", "longpress", "swipe", "drag")

    private val BLOCKED_TARGET_KEYWORDS = listOf(
        "支付",
        "付款",
        "收银台",
        "下单",
        "提交订单",
        "确认订单",
        "购买",
        "立即购买",
        "充值",
        "开通",
        "订阅",
        "转账",
        "提现",
        "红包",
        "银行卡",
        "密码",
        "验证码",
        "登录",
        "微信登录",
        "qq登录",
        "QQ登录",
        "授权登录",
        "账号授权",
        "账号绑定",
        "绑定手机",
        "实名认证",
        "人脸识别",
        "同意协议",
        "隐私政策",
        "用户协议",
        "同意并继续",
        "删除",
        "清除数据",
        "清空",
        "清理缓存",
        "格式化",
        "恢复出厂",
        "卸载",
        "注销账号",
        "退出登录",
        "退出游戏",
        "上报日志",
        "上传日志",
        "clear cache",
        "delete",
        "uninstall",
        "factory reset",
        "payment",
        "pay now",
        "purchase",
        "buy now",
        "checkout",
        "recharge",
        "subscribe",
        "login",
        "sign in",
        "authorize",
        "authorization",
        "bind account",
        "real-name",
        "real name",
        "privacy policy",
        "terms of service",
        "clear data",
        "upload logs",
        "report logs",
        "log out",
        "exit game"
    )

    private val SENSITIVE_PACKAGES = listOf(
        "com.tencent.mm",
        "com.tencent.mobileqq",
        "com.eg.android.AlipayGphone",
        "com.unionpay",
        "com.android.contacts",
        "com.android.mms",
        "com.google.android.apps.messaging",
        "com.android.documentsui",
        "com.miui.gallery",
        "com.huawei.photos"
    )

    fun inspect(action: String, request: JsonObject, foregroundPackage: String?): Decision {
        val normalizedAction = action.lowercase(Locale.US)
        if (!MUTATING_ACTIONS.contains(normalizedAction)) {
            return Decision.allowed("non_mutating")
        }

        val metadata = collectMetadataText(request)
        val matchedKeyword = BLOCKED_TARGET_KEYWORDS.firstOrNull { keyword ->
            metadata.contains(keyword.lowercase(Locale.ROOT))
        }
        if (matchedKeyword != null) {
            return Decision.blocked(
                reason = "Vision safety guard blocked a sensitive target: $matchedKeyword",
                category = "sensitive_target",
                matched = matchedKeyword,
                metadata = metadata
            )
        }

        val allowSensitivePackage = getBooleanAny(request, "allowSensitive", "allow_sensitive") == true
        val packageName = foregroundPackage?.lowercase(Locale.US).orEmpty()
        val matchedPackage = SENSITIVE_PACKAGES.firstOrNull { packageName == it.lowercase(Locale.US) || packageName.startsWith("${it.lowercase(Locale.US)}.") }
        if (matchedPackage != null && !allowSensitivePackage) {
            return Decision.blocked(
                reason = "Vision safety guard blocked direct visual action in sensitive app: $matchedPackage",
                category = "sensitive_package",
                matched = matchedPackage,
                metadata = metadata
            )
        }

        return Decision.allowed(if (metadata.isBlank()) "unknown_target" else "labeled_target", metadata)
    }

    fun policyJson(): JsonObject {
        return JsonObject().apply {
            addProperty("policy", "lumi_vision_safety_v1")
            addProperty("defaultActionPath", "OpenClaw visual plan -> APKClaw Agent safe_action -> verify with next frame")
            addProperty("metadataRequiredByLauncher", true)
            addProperty("phoneBlocksSensitiveLabels", true)
            addProperty("phoneBlocksSensitivePackages", true)
            addProperty("blockedExamples", "login/payment/auth/purchase/delete/clear-cache/upload-logs/exit")
        }
    }

    private fun collectMetadataText(request: JsonObject): String {
        val keys = listOf(
            "targetLabel",
            "target_label",
            "label",
            "reason",
            "intent",
            "visualText",
            "visual_text",
            "ocrText",
            "ocr_text",
            "screenText",
            "screen_text",
            "description",
            "targetDescription",
            "target_description",
            "risk",
            "safetyNote",
            "safety_note"
        )
        return keys.mapNotNull { key -> getStringAny(request, key) }
            .joinToString(" ")
            .lowercase(Locale.ROOT)
    }

    private fun getStringAny(json: JsonObject, vararg names: String): String? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asString?.trim()?.takeIf { it.isNotBlank() }
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    private fun getBooleanAny(json: JsonObject, vararg names: String): Boolean? {
        for (name in names) {
            val value = json.get(name) ?: continue
            if (!value.isJsonPrimitive) continue
            return try {
                value.asBoolean
            } catch (_: Exception) {
                null
            }
        }
        return null
    }

    data class Decision(
        val allowed: Boolean,
        val reason: String,
        val category: String,
        val matched: String?,
        val metadata: String
    ) {
        fun toJson(): JsonObject {
            return JsonObject().apply {
                addProperty("policy", "lumi_vision_safety_v1")
                addProperty("allowed", allowed)
                addProperty("reason", reason)
                addProperty("category", category)
                if (!matched.isNullOrBlank()) addProperty("matched", matched)
                if (metadata.isNotBlank()) addProperty("metadata", metadata.take(500))
            }
        }

        companion object {
            fun allowed(category: String, metadata: String = ""): Decision =
                Decision(true, "allowed", category, null, metadata)

            fun blocked(reason: String, category: String, matched: String, metadata: String): Decision =
                Decision(false, reason, category, matched, metadata)
        }
    }
}
