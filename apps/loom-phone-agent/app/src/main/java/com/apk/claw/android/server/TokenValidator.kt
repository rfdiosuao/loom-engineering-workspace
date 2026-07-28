package com.apk.claw.android.server

import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import fi.iki.elonen.NanoHTTPD
import java.security.MessageDigest

/**
 * 手机连接凭据验证器。KEY_API_TOKEN 仅作为升级兼容的内部存储键。
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
        KVUtils.clearExpiredPreviousPhoneCredentials()
        val storedToken = KVUtils.getApiToken()
        val previousToken = KVUtils.getPreviousApiToken()
            .takeIf { KVUtils.getPreviousPhoneCredentialValidUntil() > System.currentTimeMillis() }
            .orEmpty()
        val agentPhoneToken = session.headers[HEADER_NAME_LOWER]?.trim()
        val legacyToken = session.headers[LEGACY_HEADER_NAME_LOWER]?.trim()

        // 如果没有设置连接凭据，拒绝所有请求（安全默认）
        if (storedToken.isEmpty()) {
            XLog.w(TAG, "No phone credential configured, rejecting request")
            return false
        }

        val candidates = listOfNotNull(agentPhoneToken, legacyToken).filter { it.isNotEmpty() }
        if (candidates.isEmpty()) {
            XLog.w(TAG, "Missing phone credential header")
            return false
        }

        // 迁移期：新旧 header 中任意一个正确即可通过；稳定期可收紧为新 header 优先且必须正确。
        val matched = candidates.any { matchesPresentedToken(it, storedToken, previousToken) }
        if (!matched) {
            XLog.w(TAG, "Invalid phone credential provided")
            return false
        }

        val source = when {
            matchesPresentedToken(agentPhoneToken.orEmpty(), storedToken, previousToken) -> HEADER_NAME_LOWER
            matchesPresentedToken(legacyToken.orEmpty(), storedToken, previousToken) -> LEGACY_HEADER_NAME_LOWER
            else -> "unknown"
        }
        XLog.d(TAG, "Phone credential validation succeeded via $source")
        return true
    }

    /**
     * 检查是否已配置 Token
     */
    fun isTokenConfigured(): Boolean {
        return KVUtils.getApiToken().isNotEmpty()
    }

    /**
     * 设置新的内部手机连接凭据。
     */
    fun setToken(token: String) {
        KVUtils.setApiToken(token)
        XLog.i(TAG, "Phone credential updated")
    }

    /**
     * 兼容旧内部调用；不得用于用户界面或日志。
     */
    fun getMaskedToken(): String {
        return maskToken(KVUtils.getApiToken())
    }

    /**
     * 清除 Token
     */
    fun clearToken() {
        KVUtils.setApiToken("")
        XLog.i(TAG, "Phone credential cleared")
    }

    internal fun matchesPresentedToken(
        presented: String,
        activeToken: String,
        previousToken: String = ""
    ): Boolean {
        if (presented.isEmpty()) return false
        return constantTimeEquals(presented, activeToken) ||
            (previousToken.isNotEmpty() && constantTimeEquals(presented, previousToken))
    }

    private fun maskToken(token: String?): String {
        val text = token?.trim().orEmpty()
        if (text.isEmpty()) return ""
        if (text.length <= 4) return "****"
        return "*".repeat(text.length - 4) + text.takeLast(4)
    }

    private fun constantTimeEquals(left: String, right: String): Boolean {
        if (right.isEmpty()) return false
        return MessageDigest.isEqual(
            left.toByteArray(Charsets.UTF_8),
            right.toByteArray(Charsets.UTF_8)
        )
    }
}
