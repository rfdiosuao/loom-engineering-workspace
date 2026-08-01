package com.apk.claw.android.privilege

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrivilegedActionPolicyTest {
    private val selection = PrivilegeBackendSelection(
        backend = PrivilegeBackendKind.SHIZUKU,
        reasonCode = "shizuku_ready",
        standardCapabilitiesAvailable = true,
        enhancedActionsAvailable = true,
        shouldRequestPermission = false
    )
    private val authorization = PrivilegedActionAuthorization(
        accountId = "account-a",
        deviceId = "phone-a",
        approvalId = "approval-a",
        allowedActions = setOf(PrivilegedAction.FORCE_STOP_TARGET_APP),
        allowedTargetPackages = setOf("com.example.target"),
        expiresAtEpochMs = 2_000L
    )
    private val request = PrivilegedActionRequest(
        action = PrivilegedAction.FORCE_STOP_TARGET_APP,
        accountId = "account-a",
        deviceId = "phone-a",
        approvalId = "approval-a",
        idempotencyKey = "idem-a",
        targetPackage = "com.example.target"
    )
    private val context = PrivilegedActionContext(
        backend = selection,
        nowEpochMs = 1_000L,
        userEnabled = true,
        userAuthorized = true,
        deviceOnline = true,
        deviceUnlocked = true,
        selfPackage = "com.apk.claw.android"
    )

    @Test
    fun `approved allowlisted typed action is accepted`() {
        val decision = PrivilegedActionPolicy.evaluate(request, authorization, context)

        assertTrue(decision.allowed)
        assertEquals("approved", decision.code)
    }

    @Test
    fun `account device approval expiry backend and target all fail closed`() {
        assertEquals(
            "account_mismatch",
            PrivilegedActionPolicy.evaluate(request.copy(accountId = "account-b"), authorization, context).code
        )
        assertEquals(
            "device_mismatch",
            PrivilegedActionPolicy.evaluate(request.copy(deviceId = "phone-b"), authorization, context).code
        )
        assertEquals(
            "approval_mismatch",
            PrivilegedActionPolicy.evaluate(request.copy(approvalId = "approval-b"), authorization, context).code
        )
        assertEquals(
            "approval_expired",
            PrivilegedActionPolicy.evaluate(request, authorization, context.copy(nowEpochMs = 2_000L)).code
        )
        assertEquals(
            "enhanced_backend_unavailable",
            PrivilegedActionPolicy.evaluate(
                request,
                authorization,
                context.copy(backend = selection.copy(backend = PrivilegeBackendKind.STANDARD, enhancedActionsAvailable = false))
            ).code
        )
        assertEquals(
            "target_not_allowlisted",
            PrivilegedActionPolicy.evaluate(request.copy(targetPackage = "com.example.other"), authorization, context).code
        )
    }

    @Test
    fun `system self Shizuku and locked-device targets are always denied`() {
        for (target in listOf("android", "com.android.systemui", "com.apk.claw.android", "moe.shizuku.privileged.api")) {
            val expanded = authorization.copy(allowedTargetPackages = authorization.allowedTargetPackages + target)
            assertEquals(
                "protected_target",
                PrivilegedActionPolicy.evaluate(request.copy(targetPackage = target), expanded, context).code
            )
        }
        assertEquals(
            "device_locked",
            PrivilegedActionPolicy.evaluate(request, authorization, context.copy(deviceUnlocked = false)).code
        )
    }

    @Test
    fun `privileged contract exposes no shell or arbitrary command action`() {
        assertFalse(
            PrivilegedAction.entries.any {
                it.wireName.contains("shell", ignoreCase = true) ||
                    it.wireName.contains("command", ignoreCase = true)
            }
        )
    }

    @Test
    fun `audit record retains only action result latency and opaque digests`() {
        val record = PrivilegedActionAuditRecord.create(
            request = request,
            resultCode = "approved",
            durationMs = 81L
        )
        val serialized = record.toString()

        assertEquals("force_stop_target_app", record.action)
        assertEquals(81L, record.durationMs)
        assertTrue(record.deviceDigest.startsWith("sha256:"))
        for (secret in listOf("account-a", "phone-a", "approval-a", "idem-a", "com.example.target")) {
            assertFalse(serialized.contains(secret))
        }
    }
}
