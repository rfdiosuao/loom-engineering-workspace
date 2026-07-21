package com.apk.claw.android.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityStateInspectorTest {
    private val packageName = "com.apk.claw.android"
    private val serviceClassName = "com.apk.claw.android.service.ClawAccessibilityService"

    @Test
    fun matches_enabled_service_when_settings_contains_fully_qualified_component() {
        val settingValue = "com.example/.OtherService:$packageName/$serviceClassName"

        assertTrue(
            AccessibilityStateInspector.isEnabledInSettingValue(
                settingValue = settingValue,
                packageName = packageName,
                serviceClassName = serviceClassName
            )
        )
    }

    @Test
    fun matches_enabled_service_when_settings_contains_relative_component() {
        val settingValue = "$packageName/.service.ClawAccessibilityService"

        assertTrue(
            AccessibilityStateInspector.isEnabledInSettingValue(
                settingValue = settingValue,
                packageName = packageName,
                serviceClassName = serviceClassName
            )
        )
    }

    @Test
    fun rejects_components_from_other_packages_or_blank_settings() {
        assertFalse(
            AccessibilityStateInspector.isEnabledInSettingValue(
                settingValue = "com.other/$serviceClassName",
                packageName = packageName,
                serviceClassName = serviceClassName
            )
        )
        assertFalse(
            AccessibilityStateInspector.isEnabledInSettingValue(
                settingValue = null,
                packageName = packageName,
                serviceClassName = serviceClassName
            )
        )
    }

    @Test
    fun rejects_listed_service_when_accessibility_master_switch_is_disabled() {
        val settingValue = "$packageName/$serviceClassName"

        assertFalse(
            AccessibilityStateInspector.isEnabledInSettingValue(
                settingValue = settingValue,
                packageName = packageName,
                serviceClassName = serviceClassName,
                accessibilityMasterEnabled = false
            )
        )
    }
}
