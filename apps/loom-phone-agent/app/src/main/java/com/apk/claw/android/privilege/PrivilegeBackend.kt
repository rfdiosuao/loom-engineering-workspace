package com.apk.claw.android.privilege

enum class PrivilegeBackendKind {
    STANDARD,
    SHIZUKU,
    SUI
}

data class PrivilegeProbe(
    val shizukuInstalled: Boolean,
    val userEnabled: Boolean = false,
    val binderAlive: Boolean = false,
    val permissionGranted: Boolean = false,
    val permissionPermanentlyDenied: Boolean = false,
    val identityUid: Int? = null,
    val allowSui: Boolean = false
)

data class PrivilegeBackendSelection(
    val backend: PrivilegeBackendKind,
    val reasonCode: String,
    val standardCapabilitiesAvailable: Boolean,
    val enhancedActionsAvailable: Boolean,
    val shouldRequestPermission: Boolean
)

data class PrivilegeBackendStatus(
    val probe: PrivilegeProbe,
    val selection: PrivilegeBackendSelection
)

object PrivilegeBackendSelector {
    fun select(probe: PrivilegeProbe): PrivilegeBackendSelection {
        if (!probe.shizukuInstalled) return standard("shizuku_not_installed")
        if (!probe.userEnabled) return standard("enhanced_mode_disabled")
        if (!probe.binderAlive) {
            return standard(if (probe.permissionGranted) "shizuku_binder_dead" else "shizuku_service_stopped")
        }
        if (!probe.permissionGranted) {
            return standard(
                reasonCode = if (probe.permissionPermanentlyDenied) {
                    "shizuku_permission_denied"
                } else {
                    "shizuku_permission_required"
                },
                shouldRequestPermission = !probe.permissionPermanentlyDenied
            )
        }
        if (probe.identityUid == 0) {
            return if (probe.allowSui) {
                enhanced(PrivilegeBackendKind.SUI, "sui_ready")
            } else {
                standard("sui_root_disabled")
            }
        }
        return enhanced(PrivilegeBackendKind.SHIZUKU, "shizuku_ready")
    }

    private fun standard(
        reasonCode: String,
        shouldRequestPermission: Boolean = false
    ) = PrivilegeBackendSelection(
        backend = PrivilegeBackendKind.STANDARD,
        reasonCode = reasonCode,
        standardCapabilitiesAvailable = true,
        enhancedActionsAvailable = false,
        shouldRequestPermission = shouldRequestPermission
    )

    private fun enhanced(backend: PrivilegeBackendKind, reasonCode: String) = PrivilegeBackendSelection(
        backend = backend,
        reasonCode = reasonCode,
        standardCapabilitiesAvailable = true,
        enhancedActionsAvailable = true,
        shouldRequestPermission = false
    )
}

interface PrivilegeBackendController {
    fun current(): PrivilegeBackendSelection

    fun setUserEnabled(enabled: Boolean)

    fun requestAuthorization(): Boolean

    fun refresh()
}
