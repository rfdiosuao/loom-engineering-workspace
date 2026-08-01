package com.apk.claw.android.privilege

import java.security.MessageDigest

enum class PrivilegedAction(val wireName: String) {
    /** Recover a stuck third-party automation target. No arbitrary process command is accepted. */
    FORCE_STOP_TARGET_APP("force_stop_target_app")
}

data class PrivilegedActionAuthorization(
    val accountId: String,
    val deviceId: String,
    val approvalId: String,
    val allowedActions: Set<PrivilegedAction>,
    val allowedTargetPackages: Set<String>,
    val expiresAtEpochMs: Long
)

data class PrivilegedActionRequest(
    val action: PrivilegedAction,
    val accountId: String,
    val deviceId: String,
    val approvalId: String,
    val idempotencyKey: String,
    val targetPackage: String
)

data class PrivilegedActionContext(
    val backend: PrivilegeBackendSelection,
    val nowEpochMs: Long,
    val userEnabled: Boolean,
    val userAuthorized: Boolean,
    val deviceOnline: Boolean,
    val deviceUnlocked: Boolean,
    val selfPackage: String
)

data class PrivilegedActionDecision(
    val allowed: Boolean,
    val code: String
)

object PrivilegedActionPolicy {
    private val safeId = Regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    private val packageName = Regex("""^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$""")
    private val fixedProtectedPackages = setOf(
        "android",
        "com.android.systemui",
        "com.android.settings",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "moe.shizuku.privileged.api"
    )

    fun evaluate(
        request: PrivilegedActionRequest,
        authorization: PrivilegedActionAuthorization,
        context: PrivilegedActionContext
    ): PrivilegedActionDecision {
        if (request.accountId != authorization.accountId) return deny("account_mismatch")
        if (request.deviceId != authorization.deviceId) return deny("device_mismatch")
        if (request.approvalId != authorization.approvalId) return deny("approval_mismatch")
        if (!safeId.matches(request.accountId) || !safeId.matches(request.deviceId)) return deny("scope_invalid")
        if (!safeId.matches(request.approvalId) || !safeId.matches(request.idempotencyKey)) return deny("authorization_invalid")
        if (authorization.expiresAtEpochMs <= context.nowEpochMs) return deny("approval_expired")
        if (request.action !in authorization.allowedActions) return deny("action_not_allowlisted")
        if (!context.userEnabled || !context.userAuthorized) return deny("user_authorization_required")
        if (!context.backend.enhancedActionsAvailable || context.backend.backend == PrivilegeBackendKind.STANDARD) {
            return deny("enhanced_backend_unavailable")
        }
        if (!context.deviceOnline) return deny("device_offline")
        if (!context.deviceUnlocked) return deny("device_locked")
        if (isProtectedTarget(request.targetPackage, context.selfPackage)) return deny("protected_target")
        if (!packageName.matches(request.targetPackage)) return deny("target_invalid")
        if (request.targetPackage !in authorization.allowedTargetPackages) return deny("target_not_allowlisted")
        return PrivilegedActionDecision(true, "approved")
    }

    private fun isProtectedTarget(target: String, selfPackage: String): Boolean =
        target == "android" ||
            target == selfPackage ||
            target in fixedProtectedPackages ||
            target.startsWith("com.android.")

    private fun deny(code: String) = PrivilegedActionDecision(false, code)
}

data class PrivilegedActionAuditRecord(
    val action: String,
    val resultCode: String,
    val durationMs: Long,
    val deviceDigest: String,
    val authorizationDigest: String
) {
    companion object {
        fun create(
            request: PrivilegedActionRequest,
            resultCode: String,
            durationMs: Long
        ): PrivilegedActionAuditRecord = PrivilegedActionAuditRecord(
            action = request.action.wireName,
            resultCode = resultCode.take(64),
            durationMs = durationMs.coerceAtLeast(0),
            deviceDigest = sha256("${request.accountId}\u0000${request.deviceId}"),
            authorizationDigest = sha256("${request.approvalId}\u0000${request.idempotencyKey}")
        )
    }
}

private fun sha256(value: String): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
    return "sha256:" + digest.joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
