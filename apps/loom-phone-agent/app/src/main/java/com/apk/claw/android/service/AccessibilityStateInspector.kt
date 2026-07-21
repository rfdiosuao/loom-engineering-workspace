package com.apk.claw.android.service

import android.content.Context
import android.provider.Settings

object AccessibilityStateInspector {
    data class State(
        val masterEnabled: Boolean,
        val listedInSettings: Boolean,
        val enabledInSettings: Boolean,
        val boundToProcess: Boolean
    ) {
        val healthy: Boolean
            get() = enabledInSettings && boundToProcess

        val staleEnabledNotBound: Boolean
            get() = enabledInSettings && !boundToProcess

        val machineState: String
            get() = when {
                healthy -> "healthy"
                staleEnabledNotBound -> "stale"
                boundToProcess && !enabledInSettings -> "bound_but_disabled_in_settings"
                !masterEnabled && !listedInSettings && !boundToProcess -> "disabled"
                else -> "reenable_required"
            }

        val legacyMachineState: String
            get() = when (machineState) {
                "stale" -> "stale_enabled_not_bound"
                else -> machineState
            }

        val errorCode: String
            get() = when (machineState) {
                "healthy" -> ""
                "stale" -> "accessibility_stale"
                "bound_but_disabled_in_settings" -> "accessibility_bound_but_disabled_in_settings"
                "reenable_required" -> "accessibility_reenable_required"
                else -> "accessibility_disabled"
            }

        val retryable: Boolean
            get() = machineState == "stale"

        val recoveryHint: String
            get() = when (machineState) {
                "healthy" -> ""
                "stale" -> "Accessibility is enabled in Android Settings but is not bound to APKClaw. Reopen APKClaw, allow background running, or toggle the APKClaw Accessibility service off/on."
                "bound_but_disabled_in_settings" -> "APKClaw has a stale bound Accessibility service while Android Settings reports it disabled. Open Android Settings > Accessibility, turn APKClaw off, then enable it again."
                "reenable_required" -> "Open Android Settings > Accessibility > APKClaw and enable the service again before sending control actions."
                else -> "Enable Android Accessibility and turn on the APKClaw Accessibility service before sending control actions."
            }
    }

    fun inspect(context: Context): State {
        val masterEnabled = isAccessibilityMasterEnabled(context)
        val listedInSettings = isListedInSettings(context)
        val boundToProcess = ClawAccessibilityService.getInstance() != null
        return State(
            masterEnabled = masterEnabled,
            listedInSettings = listedInSettings,
            enabledInSettings = masterEnabled && listedInSettings,
            boundToProcess = boundToProcess
        )
    }

    fun isEnabledInSettings(context: Context): Boolean {
        return isAccessibilityMasterEnabled(context) && isListedInSettings(context)
    }

    private fun isAccessibilityMasterEnabled(context: Context): Boolean {
        return Settings.Secure.getInt(
            context.contentResolver,
            Settings.Secure.ACCESSIBILITY_ENABLED,
            0
        ) == 1
    }

    private fun isListedInSettings(context: Context): Boolean {
        val settingValue = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        )
        return isListedInSettingValue(
            settingValue = settingValue,
            packageName = context.packageName,
            serviceClassName = ClawAccessibilityService::class.java.name
        )
    }

    fun isEnabledInSettingValue(
        settingValue: String?,
        packageName: String,
        serviceClassName: String,
        accessibilityMasterEnabled: Boolean = true
    ): Boolean {
        return accessibilityMasterEnabled && isListedInSettingValue(
            settingValue = settingValue,
            packageName = packageName,
            serviceClassName = serviceClassName
        )
    }

    fun isListedInSettingValue(
        settingValue: String?,
        packageName: String,
        serviceClassName: String
    ): Boolean {
        if (settingValue.isNullOrBlank() || packageName.isBlank() || serviceClassName.isBlank()) {
            return false
        }

        return settingValue
            .split(':')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .any { component ->
                val slashIndex = component.indexOf('/')
                if (slashIndex <= 0 || slashIndex == component.lastIndex) {
                    return@any false
                }
                val componentPackage = component.substring(0, slashIndex)
                if (componentPackage != packageName) {
                    return@any false
                }
                val componentClass = normalizeClassName(
                    packageName = packageName,
                    className = component.substring(slashIndex + 1)
                )
                componentClass == serviceClassName
            }
    }

    private fun normalizeClassName(packageName: String, className: String): String {
        val trimmed = className.trim()
        return when {
            trimmed.startsWith(".") -> packageName + trimmed
            "." !in trimmed -> "$packageName.$trimmed"
            else -> trimmed
        }
    }
}
