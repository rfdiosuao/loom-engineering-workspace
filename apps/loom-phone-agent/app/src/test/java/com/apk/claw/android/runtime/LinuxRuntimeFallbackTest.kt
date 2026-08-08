package com.apk.claw.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LinuxRuntimeFallbackTest {
    private val scope = MobileRuntimeScope("account-a", "customer-a", "workspace-a")

    @Test
    fun `native implementation remains the fast path when available`() {
        val route = LinuxRuntimeRoutePlanner.route(
            request = request(),
            runtimeDecision = approved(),
            nativeEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH),
            remoteApprovedEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH)
        )

        assertEquals(LinuxExecutionBackend.ANDROID_NATIVE, route.backend)
        assertEquals("native_fast_path_selected", route.reasonCode)
        assertFalse(route.fallbackUsed)
    }

    @Test
    fun `compatible batch selects optional linux only when native has no equivalent`() {
        val route = LinuxRuntimeRoutePlanner.route(
            request = request(),
            runtimeDecision = approved(),
            nativeEntrypoints = emptySet(),
            remoteApprovedEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH)
        )

        assertEquals(LinuxExecutionBackend.OPTIONAL_LINUX, route.backend)
        assertEquals("linux_batch_selected", route.reasonCode)
        assertFalse(route.fallbackUsed)
    }

    @Test
    fun `missing or damaged runtime falls back without disabling standard capabilities`() {
        for (code in listOf("runtime_missing", "runtime_damaged", "runtime_out_of_space", "runtime_oom")) {
            val route = LinuxRuntimeRoutePlanner.route(
                request = request(),
                runtimeDecision = LinuxRuntimeDecision(false, code, standardCapabilitiesAvailable = true),
                nativeEntrypoints = emptySet(),
                remoteApprovedEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH)
            )
            assertEquals("code=$code", LinuxExecutionBackend.REMOTE_APPROVED, route.backend)
            assertEquals("code=$code", "remote_fallback_selected", route.reasonCode)
            assertTrue("code=$code", route.fallbackUsed)
            assertTrue("code=$code", route.standardCapabilitiesAvailable)
        }
    }

    @Test
    fun `missing runtime gives an explicit unavailable result when no fallback is approved`() {
        val route = LinuxRuntimeRoutePlanner.route(
            request = request(),
            runtimeDecision = LinuxRuntimeDecision(false, "runtime_missing", standardCapabilitiesAvailable = true),
            nativeEntrypoints = emptySet(),
            remoteApprovedEntrypoints = emptySet()
        )

        assertEquals(LinuxExecutionBackend.UNAVAILABLE, route.backend)
        assertEquals("runtime_missing", route.reasonCode)
        assertTrue(route.standardCapabilitiesAvailable)
    }

    @Test
    fun `failure before execution can fall back but started mutation is never replayed`() {
        val beforeStart = LinuxRuntimeFailureRecovery.decide(
            phase = LinuxRuntimeExecutionPhase.PREPARING,
            failureCode = "runtime_stopped",
            fallbackAvailable = true
        )
        assertEquals(LinuxRuntimeRecoveryAction.USE_APPROVED_FALLBACK, beforeStart.action)
        assertEquals("runtime_stopped", beforeStart.code)

        val afterStart = LinuxRuntimeFailureRecovery.decide(
            phase = LinuxRuntimeExecutionPhase.STARTED,
            failureCode = "runtime_oom",
            fallbackAvailable = true
        )
        assertEquals(LinuxRuntimeRecoveryAction.DO_NOT_REPLAY, afterStart.action)
        assertEquals("linux_outcome_indeterminate", afterStart.code)
        assertFalse(afterStart.retryable)
    }

    @Test
    fun `unapproved remote path is never selected`() {
        val route = LinuxRuntimeRoutePlanner.route(
            request = request(entrypoint = LinuxRuntimeEntrypoint.AGENT_CLI_BATCH),
            runtimeDecision = LinuxRuntimeDecision(false, "entrypoint_not_allowlisted", true),
            nativeEntrypoints = emptySet(),
            remoteApprovedEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH)
        )

        assertEquals(LinuxExecutionBackend.UNAVAILABLE, route.backend)
        assertEquals("entrypoint_not_allowlisted", route.reasonCode)
    }

    private fun request(
        entrypoint: LinuxRuntimeEntrypoint = LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH
    ) = LinuxRuntimeRequest(
        scope = scope,
        entrypoint = entrypoint,
        approvalId = "approval-a",
        idempotencyKey = "runtime-call-001",
        requestedDomains = emptySet(),
        inputBytes = 64,
        outputBytesLimit = 1_024,
        timeoutMs = 5_000,
        credentialHandle = null
    )

    private fun approved() = LinuxRuntimeDecision(true, "approved", standardCapabilitiesAvailable = true)
}
