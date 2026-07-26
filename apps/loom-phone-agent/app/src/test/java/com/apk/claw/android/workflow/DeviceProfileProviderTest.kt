package com.apk.claw.android.workflow

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceProfileProviderTest {
    @Test
    fun same_inputs_produce_same_profile_without_raw_environment_values() {
        val inputs = profileInputs()

        val first = DeviceProfileProvider.fingerprint(inputs)
        val second = DeviceProfileProvider.fingerprint(inputs)

        assertEquals(first, second)
        assertTrue(first.matches(Regex("[0-9a-f]{24}")))
        assertFalse(first.contains(inputs.packageName))
        assertFalse(first.contains(inputs.localeTag))
        assertFalse(first.contains(inputs.oemFamily))
    }

    @Test
    fun every_compatibility_dimension_changes_the_profile() {
        val baseline = profileInputs()
        val variants = listOf(
            baseline.copy(packageName = "com.example.other"),
            baseline.copy(appVersionCode = 43L),
            baseline.copy(apiLevel = 25),
            baseline.copy(oemFamily = "other"),
            baseline.copy(widthClass = 5),
            baseline.copy(heightClass = 9),
            baseline.copy(densityDpi = 420),
            baseline.copy(fontScaleBucket = 21),
            baseline.copy(localeTag = "zh-CN"),
            baseline.copy(nightMode = true),
            baseline.copy(navigationMode = "three_button"),
            baseline.copy(orientationPolicy = "landscape"),
            baseline.copy(webViewMajor = 125)
        )

        val fingerprint = DeviceProfileProvider.fingerprint(baseline)
        variants.forEach { variant ->
            assertNotEquals(fingerprint, DeviceProfileProvider.fingerprint(variant))
        }
    }

    @Test
    fun profile_schema_has_no_personal_account_or_network_identifier_slots() {
        val fieldNames = DeviceProfileInputs::class.java.declaredFields
            .map { it.name.lowercase() }
            .joinToString("|")
        val forbidden = listOf(
            "androidid", "serial", "phone", "account", "email", "ssid", "bssid",
            "mac", "imei", "subscriber", "token", "credential", "clipboard", "content"
        )

        forbidden.forEach { name -> assertFalse("forbidden profile field: $name", fieldNames.contains(name)) }
    }

    @Test
    fun current_without_an_accessibility_observation_returns_unavailable_without_throwing() {
        assertEquals("", DeviceProfileProvider.current())
        val source = productionSource("DeviceProfileProvider.kt")

        assertTrue(source.contains("ClawAccessibilityService.getInstance()"))
        assertFalse(source.contains("error(\"target_package_required\")"))
    }

    @Test
    fun explicit_target_gate_rejects_blank_and_apkclaw_self_packages() {
        val applicationPackage = "com.apk.claw.android"

        assertFalse(DeviceProfileProvider.isTargetPackageAllowed("", applicationPackage))
        assertFalse(DeviceProfileProvider.isTargetPackageAllowed(applicationPackage, applicationPackage))
        assertTrue(DeviceProfileProvider.isTargetPackageAllowed("com.example.foreground", applicationPackage))
    }

    @Test
    fun observed_target_requires_a_current_non_self_foreground_package() {
        val now = 100_000L
        val maxAgeMs = 5_000L
        val applicationPackage = "com.apk.claw.android"

        assertEquals(
            "com.example.foreground",
            DeviceProfileProvider.freshObservedTarget(
                "com.example.foreground",
                now - maxAgeMs,
                now,
                maxAgeMs,
                applicationPackage
            )
        )
        assertNull(
            DeviceProfileProvider.freshObservedTarget(
                "com.example.foreground",
                now - maxAgeMs - 1L,
                now,
                maxAgeMs,
                applicationPackage
            )
        )
        assertNull(
            DeviceProfileProvider.freshObservedTarget(
                "com.example.foreground",
                now + 1L,
                now,
                maxAgeMs,
                applicationPackage
            )
        )
        assertNull(DeviceProfileProvider.freshObservedTarget(null, now, now, maxAgeMs, applicationPackage))
        assertNull(DeviceProfileProvider.freshObservedTarget(" ", now, now, maxAgeMs, applicationPackage))
        assertNull(DeviceProfileProvider.freshObservedTarget(applicationPackage, now, now, maxAgeMs, applicationPackage))
        assertNull(DeviceProfileProvider.freshObservedTarget("com.example.foreground", 0L, now, maxAgeMs, applicationPackage))
    }

    @Test
    fun unresolved_or_invalid_target_versions_are_unavailable() {
        assertFalse(DeviceProfileProvider.isResolvedVersionUsable(null))
        assertFalse(DeviceProfileProvider.isResolvedVersionUsable(-1L))
        assertFalse(DeviceProfileProvider.isResolvedVersionUsable(0L))
        assertTrue(DeviceProfileProvider.isResolvedVersionUsable(1L))

        val source = productionSource("DeviceProfileProvider.kt")
        assertFalse(source.contains("getOrDefault(0L)"))
    }

    @Test
    fun only_canonical_fingerprints_are_trusted_profile_ids() {
        assertTrue(DeviceProfileProvider.isTrustedProfileId("0123456789abcdef01234567"))
        assertFalse(DeviceProfileProvider.isTrustedProfileId(""))
        assertFalse(DeviceProfileProvider.isTrustedProfileId("person@example.com"))
        assertFalse(DeviceProfileProvider.isTrustedProfileId("0123456789ABCDEF01234567"))
        assertFalse(DeviceProfileProvider.isTrustedProfileId("0123456789abcdef0123456"))
    }

    private fun productionSource(fileName: String): String =
        generateSequence(File(System.getProperty("user.dir").orEmpty())) { it.parentFile }
            .map { directory ->
                File(directory, "app/src/main/java/com/apk/claw/android/workflow/$fileName")
            }
            .first { it.isFile }
            .readText()

    private fun profileInputs() = DeviceProfileInputs(
        packageName = "com.example.target",
        appVersionCode = 42L,
        apiLevel = 24,
        oemFamily = "generic",
        widthClass = 4,
        heightClass = 8,
        densityDpi = 320,
        fontScaleBucket = 20,
        localeTag = "en-US",
        nightMode = false,
        navigationMode = "gesture",
        orientationPolicy = "portrait",
        webViewMajor = 124
    )
}
