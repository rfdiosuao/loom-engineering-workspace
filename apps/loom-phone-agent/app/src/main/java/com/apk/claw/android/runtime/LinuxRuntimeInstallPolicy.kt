package com.apk.claw.android.runtime

import com.apk.claw.android.skill.LinuxSkillRuntimeState
import java.net.URI

data class LinuxRuntimeDistribution(
    val downloadUrl: String,
    val sha256: String,
    val packageName: String,
    val minVersionCode: Long,
    val signerSha256: String
) {
    fun isValid(): Boolean {
        val uri = runCatching { URI(downloadUrl) }.getOrNull() ?: return false
        return uri.scheme.equals("https", ignoreCase = true) &&
            !uri.host.isNullOrBlank() &&
            sha256.matches(Regex("^[A-Fa-f0-9]{64}$")) &&
            packageName == LinuxRuntimeCompanionClient.COMPANION_PACKAGE &&
            minVersionCode > 0L &&
            signerSha256.matches(Regex("^[A-Fa-f0-9]{64}$"))
    }
}

enum class LinuxRuntimeInstallAction {
    DOWNLOAD_COMPANION,
    INITIALIZE_RUNTIME,
    RECHECK_RUNTIME,
    BLOCKED
}

data class LinuxRuntimeInstallDecision(
    val action: LinuxRuntimeInstallAction,
    val code: String
)

object LinuxRuntimeInstallPolicy {
    fun decide(
        runtimeState: LinuxSkillRuntimeState,
        companionInstalled: Boolean,
        distribution: LinuxRuntimeDistribution?
    ): LinuxRuntimeInstallDecision = when {
        runtimeState == LinuxSkillRuntimeState.READY -> LinuxRuntimeInstallDecision(
            LinuxRuntimeInstallAction.RECHECK_RUNTIME,
            "runtime_recheck"
        )
        runtimeState == LinuxSkillRuntimeState.DISABLED -> LinuxRuntimeInstallDecision(
            LinuxRuntimeInstallAction.BLOCKED,
            "runtime_disabled"
        )
        companionInstalled -> LinuxRuntimeInstallDecision(
            LinuxRuntimeInstallAction.INITIALIZE_RUNTIME,
            "runtime_initialization_required"
        )
        distribution?.isValid() == true -> LinuxRuntimeInstallDecision(
            LinuxRuntimeInstallAction.DOWNLOAD_COMPANION,
            "companion_install_required"
        )
        else -> LinuxRuntimeInstallDecision(
            LinuxRuntimeInstallAction.BLOCKED,
            "companion_distribution_missing"
        )
    }
}
