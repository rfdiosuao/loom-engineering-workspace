package com.apk.claw.android.server

import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import fi.iki.elonen.NanoHTTPD

/**
 * API Token 验证器
 * 用于验证外部 HTTP API 请求的身份
 */
object TokenValidator {

    private const val TAG = "TokenValidator"

    /**
     * Token header 名称（NanoHTTPD 会将 header 名称转为小写）
     */
    private const val HEADER_NAME_LOWER = "x-agent-phone-token"
    private const val LEGACY_HEADER_NAME_LOWER = "x-apkclaw-token"

    /**
     * 验证请求中的 Token
     * @param session HTTP 请求会话
     * @return true 表示验证通过
     */
    fun validate(session: NanoHTTPD.IHTTPSession): Boolean {
        // NanoHTTPD headers map 的 key 是小写的
        val storedToken = KVUtils.getApiToken()
        val agentPhoneToken = session.headers[HEADER_NAME_LOWER]?.trim()
        val legacyToken = session.headers[LEGACY_HEADER_NAME_LOWER]?.trim()

        XLog.d(
            TAG,
            "Token validation: agent=${maskToken(agentPhoneToken)}, legacy=${maskToken(legacyToken)}, stored=${maskToken(storedToken)}"
        )

        // 如果没有设置 Token，拒绝所有请求（安全默认）
        if (storedToken.isEmpty()) {
            XLog.w(TAG, "No API token configured, rejecting request")
            return false
        }

        val candidates = listOfNotNull(agentPhoneToken, legacyToken).filter { it.isNotEmpty() }
        if (candidates.isEmpty()) {
            XLog.w(TAG, "Missing API token header")
            return false
        }

        // 迁移期：新旧 header 中任意一个正确即可通过；稳定期可收紧为新 header 优先且必须正确。
        val matched = candidates.any { it == storedToken }
        if (!matched) {
            XLog.w(
                TAG,
                "Invalid API token provided: agent=${maskToken(agentPhoneToken)}, legacy=${maskToken(legacyToken)}"
            )
            return false
        }

        val source = when {
            agentPhoneToken == storedToken -> HEADER_NAME_LOWER
            legacyToken == storedToken -> LEGACY_HEADER_NAME_LOWER
            else -> "unknown"
        }
        XLog.i(TAG, "Token validation successful via $source")
        return true
    }

    /**
     * 检查是否已配置 Token
     */
    fun isTokenConfigured(): Boolean {
        return KVUtils.getApiToken().isNotEmpty()
    }

    /**
     * 设置新的 API Token
     */
    fun setToken(token: String) {
        KVUtils.setApiToken(token)
        XLog.i(TAG, "API token updated: ${getMaskedToken()}")
    }

    /**
     * 获取当前 Token（用于显示，已脱敏）
     */
    fun getMaskedToken(): String {
        return maskToken(KVUtils.getApiToken())
    }

    /**
     * 清除 Token
     */
    fun clearToken() {
        KVUtils.setApiToken("")
        XLog.i(TAG, "API token cleared")
    }

    private fun maskToken(token: String?): String {
        val text = token?.trim().orEmpty()
        if (text.isEmpty()) return ""
        if (text.length <= 4) return "****"
        return "*".repeat(text.length - 4) + text.takeLast(4)
    }
}
