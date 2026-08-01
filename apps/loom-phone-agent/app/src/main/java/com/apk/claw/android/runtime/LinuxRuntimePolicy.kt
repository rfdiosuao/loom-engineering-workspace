package com.apk.claw.android.runtime

import java.security.MessageDigest

/**
 * Clean-room policy and routing boundary for an optional Linux companion.
 *
 * This API intentionally models closed entrypoint identifiers only. It has no executable path,
 * argument vector, process builder, command string, host socket, Shizuku binder, or shell surface.
 */
enum class LinuxRuntimeEntrypoint(val wireName: String) {
    WORKSPACE_TEXT_BATCH("workspace.text.batch"),
    WORKSPACE_JSONL_TRANSFORM("workspace.jsonl.transform"),
    AGENT_CLI_BATCH("agent.cli.batch")
}

enum class LinuxRuntimeState(val wireName: String) {
    MISSING("missing"),
    READY("ready"),
    DAMAGED("damaged"),
    DISABLED("disabled"),
    OUT_OF_SPACE("out_of_space"),
    OOM("oom"),
    TIMED_OUT("timed_out"),
    STOPPED("stopped"),
    UNHEALTHY("unhealthy")
}

data class LinuxRuntimeResourceBudget(
    val memoryMiB: Int,
    val storageMiB: Int,
    val maxProcesses: Int,
    val maxInputBytes: Long,
    val maxOutputBytes: Long,
    val taskTimeoutMs: Long
) {
    init {
        require(memoryMiB in 64..4_096) { "Invalid Linux runtime memory budget" }
        require(storageMiB in 64..16_384) { "Invalid Linux runtime storage budget" }
        require(maxProcesses in 1..64) { "Invalid Linux runtime process budget" }
        require(maxInputBytes in 1..1_073_741_824L) { "Invalid Linux runtime input budget" }
        require(maxOutputBytes in 1..1_073_741_824L) { "Invalid Linux runtime output budget" }
        require(taskTimeoutMs in 1_000..600_000) { "Invalid Linux runtime timeout budget" }
    }
}

data class LinuxRuntimeDescriptor(
    val componentId: String,
    val state: LinuxRuntimeState,
    val userEnabled: Boolean,
    val artifactVerified: Boolean,
    val sbomVerified: Boolean,
    val resourceBudget: LinuxRuntimeResourceBudget
) {
    init {
        require(LINUX_SAFE_ID.matches(componentId)) { "Invalid Linux runtime component id" }
    }
}

data class LinuxRuntimeWorkspacePolicy(
    val readOnlyInputs: Boolean,
    val separateOutput: Boolean,
    val credentialHandlesOnly: Boolean,
    val allowAppPrivateData: Boolean,
    val allowSystemPaths: Boolean,
    val allowOtherAccountWorkspaces: Boolean,
    val allowHostSockets: Boolean
) {
    fun isSecure(): Boolean =
        readOnlyInputs &&
            separateOutput &&
            credentialHandlesOnly &&
            !allowAppPrivateData &&
            !allowSystemPaths &&
            !allowOtherAccountWorkspaces &&
            !allowHostSockets

    companion object {
        fun secureDefault() = LinuxRuntimeWorkspacePolicy(
            readOnlyInputs = true,
            separateOutput = true,
            credentialHandlesOnly = true,
            allowAppPrivateData = false,
            allowSystemPaths = false,
            allowOtherAccountWorkspaces = false,
            allowHostSockets = false
        )
    }
}

data class LinuxRuntimeNetworkPolicy(
    val defaultDeny: Boolean,
    val allowedProviderDomains: Set<String>,
    val credentialHandlesOnly: Boolean
) {
    init {
        require(allowedProviderDomains.size <= 64) { "Too many Linux runtime provider domains" }
        require(allowedProviderDomains.all(LINUX_PROVIDER_DOMAIN::matches)) {
            "Invalid Linux runtime provider domain"
        }
    }

    fun isSecure(): Boolean = defaultDeny && credentialHandlesOnly
}

data class LinuxRuntimeRequest(
    val scope: MobileRuntimeScope,
    val entrypoint: LinuxRuntimeEntrypoint,
    val approvalId: String,
    val idempotencyKey: String,
    val requestedDomains: Set<String>,
    val inputBytes: Long,
    val outputBytesLimit: Long,
    val timeoutMs: Long,
    val credentialHandle: String?
) {
    init {
        require(inputBytes >= 0) { "Invalid Linux runtime input size" }
        require(outputBytesLimit > 0) { "Invalid Linux runtime output limit" }
        require(timeoutMs > 0) { "Invalid Linux runtime timeout" }
        require(requestedDomains.size <= 64) { "Too many requested provider domains" }
    }
}

data class LinuxRuntimeGrant(
    val scope: MobileRuntimeScope,
    val approvalId: String,
    val allowedEntrypoints: Set<LinuxRuntimeEntrypoint>,
    val allowedProviderDomains: Set<String>,
    val expiresAtEpochMs: Long,
    val enabled: Boolean = true
) {
    init {
        require(LINUX_SAFE_TOKEN.matches(approvalId)) { "Invalid Linux runtime approval id" }
        require(allowedEntrypoints.isNotEmpty()) { "Linux runtime grant needs an entrypoint" }
        require(allowedProviderDomains.size <= 64) { "Too many granted provider domains" }
        require(allowedProviderDomains.all(LINUX_PROVIDER_DOMAIN::matches)) {
            "Invalid granted provider domain"
        }
    }
}

data class LinuxRuntimeContext(
    val descriptor: LinuxRuntimeDescriptor,
    val nowEpochMs: Long,
    val workspacePolicy: LinuxRuntimeWorkspacePolicy,
    val networkPolicy: LinuxRuntimeNetworkPolicy
)

data class LinuxRuntimeDecision(
    val allowed: Boolean,
    val code: String,
    val standardCapabilitiesAvailable: Boolean
)

object LinuxRuntimePolicy {
    fun evaluate(
        request: LinuxRuntimeRequest,
        grant: LinuxRuntimeGrant,
        context: LinuxRuntimeContext
    ): LinuxRuntimeDecision {
        val descriptor = context.descriptor
        if (descriptor.state != LinuxRuntimeState.READY) {
            return deny("runtime_${descriptor.state.wireName}")
        }
        if (!descriptor.userEnabled) return deny("runtime_disabled_by_user")
        if (!descriptor.artifactVerified) return deny("runtime_artifact_unverified")
        if (!descriptor.sbomVerified) return deny("runtime_sbom_unverified")
        if (!context.workspacePolicy.isSecure()) return deny("workspace_policy_unsafe")
        if (!context.networkPolicy.isSecure()) return deny("network_policy_unsafe")
        if (!grant.enabled) return deny("grant_disabled")
        if (request.scope != grant.scope) return deny("scope_mismatch")
        if (request.approvalId != grant.approvalId) return deny("approval_mismatch")
        if (!LINUX_SAFE_TOKEN.matches(request.approvalId) || !LINUX_SAFE_TOKEN.matches(request.idempotencyKey)) {
            return deny("authorization_invalid")
        }
        if (grant.expiresAtEpochMs <= context.nowEpochMs) return deny("approval_expired")
        if (request.entrypoint !in grant.allowedEntrypoints) return deny("entrypoint_not_allowlisted")
        if (request.inputBytes > descriptor.resourceBudget.maxInputBytes) return deny("input_budget_exceeded")
        if (request.outputBytesLimit > descriptor.resourceBudget.maxOutputBytes) return deny("output_budget_exceeded")
        if (request.timeoutMs > descriptor.resourceBudget.taskTimeoutMs) return deny("timeout_budget_exceeded")
        if (request.requestedDomains.any { !LINUX_PROVIDER_DOMAIN.matches(it) }) {
            return deny("network_domain_invalid")
        }
        if (!grant.allowedProviderDomains.containsAll(request.requestedDomains) ||
            !context.networkPolicy.allowedProviderDomains.containsAll(request.requestedDomains)
        ) {
            return deny("network_domain_not_allowlisted")
        }
        if (request.credentialHandle != null && !LINUX_VAULT_HANDLE.matches(request.credentialHandle)) {
            return deny("credential_handle_invalid")
        }
        return LinuxRuntimeDecision(true, "approved", standardCapabilitiesAvailable = true)
    }

    private fun deny(code: String) = LinuxRuntimeDecision(false, code, standardCapabilitiesAvailable = true)
}

enum class LinuxExecutionBackend {
    ANDROID_NATIVE,
    OPTIONAL_LINUX,
    REMOTE_APPROVED,
    UNAVAILABLE
}

data class LinuxRuntimeRoute(
    val backend: LinuxExecutionBackend,
    val reasonCode: String,
    val fallbackUsed: Boolean,
    val standardCapabilitiesAvailable: Boolean
)

object LinuxRuntimeRoutePlanner {
    fun route(
        request: LinuxRuntimeRequest,
        runtimeDecision: LinuxRuntimeDecision,
        nativeEntrypoints: Set<LinuxRuntimeEntrypoint>,
        remoteApprovedEntrypoints: Set<LinuxRuntimeEntrypoint>
    ): LinuxRuntimeRoute {
        val operationalFailure = isOperationalFailure(runtimeDecision.code)
        if (request.entrypoint in nativeEntrypoints && (runtimeDecision.allowed || operationalFailure)) {
            return LinuxRuntimeRoute(
                backend = LinuxExecutionBackend.ANDROID_NATIVE,
                reasonCode = if (runtimeDecision.allowed) "native_fast_path_selected" else "native_fallback_selected",
                fallbackUsed = !runtimeDecision.allowed,
                standardCapabilitiesAvailable = true
            )
        }
        if (runtimeDecision.allowed) {
            return LinuxRuntimeRoute(
                backend = LinuxExecutionBackend.OPTIONAL_LINUX,
                reasonCode = "linux_batch_selected",
                fallbackUsed = false,
                standardCapabilitiesAvailable = true
            )
        }
        if (operationalFailure && request.entrypoint in remoteApprovedEntrypoints) {
            return LinuxRuntimeRoute(
                backend = LinuxExecutionBackend.REMOTE_APPROVED,
                reasonCode = "remote_fallback_selected",
                fallbackUsed = true,
                standardCapabilitiesAvailable = true
            )
        }
        return LinuxRuntimeRoute(
            backend = LinuxExecutionBackend.UNAVAILABLE,
            reasonCode = runtimeDecision.code,
            fallbackUsed = false,
            standardCapabilitiesAvailable = runtimeDecision.standardCapabilitiesAvailable
        )
    }

    private fun isOperationalFailure(code: String): Boolean = code in setOf(
        "runtime_missing",
        "runtime_damaged",
        "runtime_disabled",
        "runtime_disabled_by_user",
        "runtime_out_of_space",
        "runtime_oom",
        "runtime_timed_out",
        "runtime_stopped",
        "runtime_unhealthy",
        "runtime_artifact_unverified",
        "runtime_sbom_unverified"
    )
}

enum class LinuxRuntimeExecutionPhase {
    PREPARING,
    STARTED,
    COMPLETED
}

enum class LinuxRuntimeRecoveryAction {
    USE_APPROVED_FALLBACK,
    REPORT_UNAVAILABLE,
    DO_NOT_REPLAY,
    NONE
}

data class LinuxRuntimeRecoveryDecision(
    val action: LinuxRuntimeRecoveryAction,
    val code: String,
    val retryable: Boolean
)

object LinuxRuntimeFailureRecovery {
    fun decide(
        phase: LinuxRuntimeExecutionPhase,
        failureCode: String,
        fallbackAvailable: Boolean
    ): LinuxRuntimeRecoveryDecision = when (phase) {
        LinuxRuntimeExecutionPhase.PREPARING -> if (fallbackAvailable) {
            LinuxRuntimeRecoveryDecision(
                LinuxRuntimeRecoveryAction.USE_APPROVED_FALLBACK,
                failureCode.take(64),
                retryable = true
            )
        } else {
            LinuxRuntimeRecoveryDecision(
                LinuxRuntimeRecoveryAction.REPORT_UNAVAILABLE,
                failureCode.take(64),
                retryable = false
            )
        }
        LinuxRuntimeExecutionPhase.STARTED -> LinuxRuntimeRecoveryDecision(
            LinuxRuntimeRecoveryAction.DO_NOT_REPLAY,
            "linux_outcome_indeterminate",
            retryable = false
        )
        LinuxRuntimeExecutionPhase.COMPLETED -> LinuxRuntimeRecoveryDecision(
            LinuxRuntimeRecoveryAction.NONE,
            "completed",
            retryable = false
        )
    }
}

data class LinuxRuntimeAuditRecord(
    val entrypoint: String,
    val resultCode: String,
    val durationMs: Long,
    val scopeDigest: String,
    val approvalDigest: String,
    val idempotencyDigest: String
) {
    companion object {
        fun create(
            request: LinuxRuntimeRequest,
            resultCode: String,
            durationMs: Long
        ) = LinuxRuntimeAuditRecord(
            entrypoint = request.entrypoint.wireName,
            resultCode = resultCode.take(64),
            durationMs = durationMs.coerceAtLeast(0),
            scopeDigest = linuxDigest(request.scope.canonical()),
            approvalDigest = linuxDigest(request.approvalId),
            idempotencyDigest = linuxDigest(request.idempotencyKey)
        )
    }
}

private val LINUX_SAFE_ID = Regex("^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
private val LINUX_SAFE_TOKEN = Regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
private val LINUX_VAULT_HANDLE = Regex("^vault:[A-Za-z0-9_.:-]{8,160}$")
private val LINUX_PROVIDER_DOMAIN = Regex(
    "^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z][a-z0-9-]{1,62}$"
)

private fun linuxDigest(value: String): String {
    val bytes = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
    return "sha256:" + bytes.joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
