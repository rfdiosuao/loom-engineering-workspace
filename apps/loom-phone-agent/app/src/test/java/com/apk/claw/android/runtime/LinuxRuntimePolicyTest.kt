package com.apk.claw.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LinuxRuntimePolicyTest {
    private val scope = MobileRuntimeScope("account-a", "customer-a", "workspace-a")
    private val now = 1_785_600_000_000L

    @Test
    fun `ready verified companion accepts a closed approved entrypoint`() {
        val decision = LinuxRuntimePolicy.evaluate(
            request = request(),
            grant = grant(),
            context = context()
        )

        assertTrue(decision.allowed)
        assertEquals("approved", decision.code)
        assertTrue(decision.standardCapabilitiesAvailable)
    }

    @Test
    fun `runtime is optional and every unhealthy state fails closed`() {
        val unavailableStates = LinuxRuntimeState.entries.filter { it != LinuxRuntimeState.READY }

        unavailableStates.forEach { state ->
            val decision = LinuxRuntimePolicy.evaluate(
                request = request(),
                grant = grant(),
                context = context(descriptor = descriptor(state = state))
            )
            assertFalse("state=$state", decision.allowed)
            assertEquals("state=$state", "runtime_${state.wireName}", decision.code)
            assertTrue("state=$state", decision.standardCapabilitiesAvailable)
        }
    }

    @Test
    fun `scope approval expiry and entrypoint are all enforced`() {
        val otherScope = MobileRuntimeScope("account-b", "customer-a", "workspace-a")

        assertEquals(
            "scope_mismatch",
            LinuxRuntimePolicy.evaluate(request(scope = otherScope), grant(), context()).code
        )
        assertEquals(
            "approval_mismatch",
            LinuxRuntimePolicy.evaluate(request(approvalId = "approval-b"), grant(), context()).code
        )
        assertEquals(
            "approval_expired",
            LinuxRuntimePolicy.evaluate(request(), grant(expiresAt = now), context()).code
        )
        assertEquals(
            "entrypoint_not_allowlisted",
            LinuxRuntimePolicy.evaluate(
                request(entrypoint = LinuxRuntimeEntrypoint.AGENT_CLI_BATCH),
                grant(),
                context()
            ).code
        )
    }

    @Test
    fun `workspace and network policies cannot be broadened by a task`() {
        val insecureWorkspace = LinuxRuntimeWorkspacePolicy(
            readOnlyInputs = false,
            separateOutput = true,
            credentialHandlesOnly = true,
            allowAppPrivateData = false,
            allowSystemPaths = false,
            allowOtherAccountWorkspaces = false,
            allowHostSockets = false
        )
        assertEquals(
            "workspace_policy_unsafe",
            LinuxRuntimePolicy.evaluate(request(), grant(), context(workspace = insecureWorkspace)).code
        )

        assertEquals(
            "network_domain_not_allowlisted",
            LinuxRuntimePolicy.evaluate(
                request = request(requestedDomains = setOf("unapproved.example")),
                grant = grant(),
                context = context()
            ).code
        )

        val openNetwork = LinuxRuntimeNetworkPolicy(
            defaultDeny = false,
            allowedProviderDomains = setOf("api.example.com"),
            credentialHandlesOnly = true
        )
        assertEquals(
            "network_policy_unsafe",
            LinuxRuntimePolicy.evaluate(request(), grant(), context(network = openNetwork)).code
        )
    }

    @Test
    fun `resource budgets and opaque credential handles are enforced`() {
        assertEquals(
            "input_budget_exceeded",
            LinuxRuntimePolicy.evaluate(
                request(maxInputBytes = 5_000_000),
                grant(),
                context()
            ).code
        )
        assertEquals(
            "timeout_budget_exceeded",
            LinuxRuntimePolicy.evaluate(
                request(timeoutMs = 90_000),
                grant(),
                context()
            ).code
        )
        assertEquals(
            "credential_handle_invalid",
            LinuxRuntimePolicy.evaluate(
                request(credentialHandle = "sk-plaintext-secret"),
                grant(),
                context()
            ).code
        )
    }

    @Test
    fun `artifact and sbom verification are mandatory before readiness`() {
        assertEquals(
            "runtime_artifact_unverified",
            LinuxRuntimePolicy.evaluate(
                request(),
                grant(),
                context(descriptor = descriptor(artifactVerified = false))
            ).code
        )
        assertEquals(
            "runtime_sbom_unverified",
            LinuxRuntimePolicy.evaluate(
                request(),
                grant(),
                context(descriptor = descriptor(sbomVerified = false))
            ).code
        )
    }

    private fun request(
        scope: MobileRuntimeScope = this.scope,
        entrypoint: LinuxRuntimeEntrypoint = LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH,
        approvalId: String = "approval-a",
        requestedDomains: Set<String> = setOf("api.example.com"),
        maxInputBytes: Long = 128_000,
        timeoutMs: Long = 20_000,
        credentialHandle: String? = "vault:runtime.opaque-001"
    ) = LinuxRuntimeRequest(
        scope = scope,
        entrypoint = entrypoint,
        approvalId = approvalId,
        idempotencyKey = "runtime-call-001",
        requestedDomains = requestedDomains,
        inputBytes = maxInputBytes,
        outputBytesLimit = 256_000,
        timeoutMs = timeoutMs,
        credentialHandle = credentialHandle
    )

    private fun grant(expiresAt: Long = now + 60_000) = LinuxRuntimeGrant(
        scope = scope,
        approvalId = "approval-a",
        allowedEntrypoints = setOf(LinuxRuntimeEntrypoint.WORKSPACE_TEXT_BATCH),
        allowedProviderDomains = setOf("api.example.com"),
        expiresAtEpochMs = expiresAt
    )

    private fun descriptor(
        state: LinuxRuntimeState = LinuxRuntimeState.READY,
        artifactVerified: Boolean = true,
        sbomVerified: Boolean = true
    ) = LinuxRuntimeDescriptor(
        componentId = "lumi-linux-companion",
        state = state,
        userEnabled = true,
        artifactVerified = artifactVerified,
        sbomVerified = sbomVerified,
        resourceBudget = LinuxRuntimeResourceBudget(
            memoryMiB = 384,
            storageMiB = 1_024,
            maxProcesses = 8,
            maxInputBytes = 1_000_000,
            maxOutputBytes = 2_000_000,
            taskTimeoutMs = 60_000
        )
    )

    private fun context(
        descriptor: LinuxRuntimeDescriptor = descriptor(),
        workspace: LinuxRuntimeWorkspacePolicy = LinuxRuntimeWorkspacePolicy.secureDefault(),
        network: LinuxRuntimeNetworkPolicy = LinuxRuntimeNetworkPolicy(
            defaultDeny = true,
            allowedProviderDomains = setOf("api.example.com"),
            credentialHandlesOnly = true
        )
    ) = LinuxRuntimeContext(
        descriptor = descriptor,
        nowEpochMs = now,
        workspacePolicy = workspace,
        networkPolicy = network
    )
}
