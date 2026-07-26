package com.apk.claw.android.workflow

import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import androidx.core.content.pm.PackageInfoCompat
import androidx.core.os.ConfigurationCompat
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.service.ClawAccessibilityService
import java.security.MessageDigest
import kotlin.math.roundToInt

data class DeviceProfileInputs(
    val packageName: String,
    val appVersionCode: Long,
    val apiLevel: Int,
    val oemFamily: String,
    val widthClass: Int,
    val heightClass: Int,
    val densityDpi: Int,
    val fontScaleBucket: Int,
    val localeTag: String,
    val nightMode: Boolean,
    val navigationMode: String,
    val orientationPolicy: String,
    val webViewMajor: Int
)

object DeviceProfileProvider {
    private const val FINGERPRINT_HEX_LENGTH = 24
    private const val FOREGROUND_OBSERVATION_MAX_AGE_MS = 5_000L
    private const val UNKNOWN = "unknown"
    private val HEX = "0123456789abcdef".toCharArray()
    private val TRUSTED_PROFILE_PATTERN = Regex("[0-9a-f]{$FINGERPRINT_HEX_LENGTH}")

    fun current(): String = runCatching {
        val service = ClawAccessibilityService.getInstance() ?: return ""
        val observedPackage = service.currentPackageName
        val observedAt = service.currentPackageObservedAt
        val applicationPackage = ClawApplication.instance.packageName
        val targetPackage = freshObservedTarget(
            observedPackage = observedPackage,
            observedAt = observedAt,
            now = System.currentTimeMillis(),
            maxAgeMs = FOREGROUND_OBSERVATION_MAX_AGE_MS,
            applicationPackage = applicationPackage
        ) ?: return ""
        current(targetPackage)
    }.getOrDefault("")

    fun current(targetPackage: String): String = runCatching {
        val app = ClawApplication.instance
        if (!isTargetPackageAllowed(targetPackage, app.packageName)) return ""
        val resources = app.resources
        val configuration = resources.configuration
        val packageManager = app.packageManager
        val targetVersionCode = packageVersionCode(packageManager, targetPackage)
            ?.takeIf(::isResolvedVersionUsable)
            ?: return ""
        fingerprint(
            DeviceProfileInputs(
                packageName = targetPackage,
                appVersionCode = targetVersionCode,
                apiLevel = Build.VERSION.SDK_INT,
                oemFamily = boundedLabel(Build.MANUFACTURER),
                widthClass = displayClass(configuration.screenWidthDp),
                heightClass = displayClass(configuration.screenHeightDp),
                densityDpi = resources.displayMetrics.densityDpi.coerceAtLeast(0),
                fontScaleBucket = (configuration.fontScale.coerceIn(0.5f, 3f) * 20f).roundToInt(),
                localeTag = localeTag(configuration),
                nightMode = configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
                    Configuration.UI_MODE_NIGHT_YES,
                navigationMode = navigationMode(resources),
                orientationPolicy = orientationPolicy(configuration.orientation),
                webViewMajor = webViewMajor(packageManager)
            )
        )
    }.getOrDefault("")

    internal fun isTargetPackageAllowed(targetPackage: String, applicationPackage: String): Boolean =
        targetPackage.isNotBlank() &&
            applicationPackage.isNotBlank() &&
            targetPackage != applicationPackage

    internal fun freshObservedTarget(
        observedPackage: String?,
        observedAt: Long,
        now: Long,
        maxAgeMs: Long,
        applicationPackage: String
    ): String? {
        val targetPackage = observedPackage.orEmpty()
        if (!isTargetPackageAllowed(targetPackage, applicationPackage)) return null
        if (observedAt <= 0L || maxAgeMs < 0L || observedAt > now) return null
        return targetPackage.takeIf { now - observedAt <= maxAgeMs }
    }

    internal fun isResolvedVersionUsable(versionCode: Long?): Boolean =
        versionCode != null && versionCode > 0L

    internal fun isTrustedProfileId(profileId: String): Boolean =
        TRUSTED_PROFILE_PATTERN.matches(profileId)

    fun fingerprint(value: DeviceProfileInputs): String {
        val canonical = listOf(
            value.packageName,
            value.appVersionCode.toString(),
            value.apiLevel.toString(),
            value.oemFamily,
            value.widthClass.toString(),
            value.heightClass.toString(),
            value.densityDpi.toString(),
            value.fontScaleBucket.toString(),
            value.localeTag,
            value.nightMode.toString(),
            value.navigationMode,
            value.orientationPolicy,
            value.webViewMajor.toString()
        ).joinToString(separator = "|") { field -> "${field.length}:$field" }
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(canonical.toByteArray(Charsets.UTF_8))
        return buildString(FINGERPRINT_HEX_LENGTH) {
            for (index in 0 until FINGERPRINT_HEX_LENGTH / 2) {
                val byte = digest[index].toInt() and 0xff
                append(HEX[byte ushr 4])
                append(HEX[byte and 0x0f])
            }
        }
    }

    private fun packageVersionCode(packageManager: PackageManager, packageName: String): Long? =
        runCatching { PackageInfoCompat.getLongVersionCode(packageManager.getPackageInfo(packageName, 0)) }
            .getOrNull()

    private fun displayClass(dp: Int): Int = if (dp <= 0) 0 else (dp / 120).coerceIn(1, 32)

    private fun boundedLabel(value: String?): String {
        val normalized = value.orEmpty().lowercase().map { character ->
            if (character.isLetterOrDigit()) character else '-'
        }.joinToString("").trim('-').take(32)
        return normalized.ifBlank { UNKNOWN }
    }

    private fun navigationMode(resources: android.content.res.Resources): String {
        val id = resources.getIdentifier("config_navBarInteractionMode", "integer", "android")
        val mode = if (id == 0) -1 else runCatching { resources.getInteger(id) }.getOrDefault(-1)
        return when (mode) {
            0 -> "three_button"
            1 -> "two_button"
            2 -> "gesture"
            else -> UNKNOWN
        }
    }

    private fun orientationPolicy(orientation: Int): String = when (orientation) {
        Configuration.ORIENTATION_PORTRAIT -> "portrait"
        Configuration.ORIENTATION_LANDSCAPE -> "landscape"
        else -> UNKNOWN
    }

    private fun localeTag(configuration: Configuration): String {
        val locales = ConfigurationCompat.getLocales(configuration)
        return locales[0]?.toLanguageTag()?.ifBlank { UNKNOWN } ?: UNKNOWN
    }

    private fun webViewMajor(packageManager: PackageManager): Int {
        val providers = listOf("com.google.android.webview", "com.android.webview")
        return providers.firstNotNullOfOrNull { packageName ->
            runCatching {
                packageManager.getPackageInfo(packageName, 0).versionName
                    ?.substringBefore('.')
                    ?.toIntOrNull()
            }.getOrNull()
        }?.coerceAtLeast(0) ?: 0
    }
}
