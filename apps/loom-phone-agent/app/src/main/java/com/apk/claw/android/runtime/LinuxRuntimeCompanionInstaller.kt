package com.apk.claw.android.runtime

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.apk.claw.android.BuildConfig
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request

data class LinuxCompanionInstallResult(
    val success: Boolean,
    val code: String
)

object LinuxRuntimeCompanionInstaller {
    private const val APK_FILE_NAME = "LumiLinuxRuntime.apk"
    private const val MAX_APK_BYTES = 32L * 1024L * 1024L

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.MINUTES)
        .callTimeout(4, TimeUnit.MINUTES)
        .followRedirects(true)
        .build()

    fun configuredDistribution(): LinuxRuntimeDistribution? = LinuxRuntimeDistribution(
        downloadUrl = BuildConfig.LUMI_LINUX_COMPANION_URL,
        sha256 = BuildConfig.LUMI_LINUX_COMPANION_SHA256,
        packageName = LinuxRuntimeCompanionClient.COMPANION_PACKAGE,
        minVersionCode = BuildConfig.LUMI_LINUX_COMPANION_MIN_VERSION,
        signerSha256 = BuildConfig.LUMI_LINUX_COMPANION_SIGNER_SHA256
    ).takeIf { it.isValid() }

    fun isCompanionInstalled(
        context: Context,
        distribution: LinuxRuntimeDistribution? = configuredDistribution()
    ): Boolean {
        val expected = distribution ?: return false
        val info = runCatching {
            installedPackageInfo(context.packageManager, expected.packageName)
        }.getOrNull() ?: return false
        return verifyPackageInfo(context, info, expected)
    }

    fun downloadAndVerify(
        context: Context,
        distribution: LinuxRuntimeDistribution
    ): LinuxCompanionInstallResult {
        if (!distribution.isValid()) {
            return LinuxCompanionInstallResult(false, "companion_distribution_invalid")
        }
        val directory = cacheDirectory(context)
        if (!directory.exists() && !directory.mkdirs()) {
            return LinuxCompanionInstallResult(false, "companion_cache_unavailable")
        }
        val partial = File(directory, "$APK_FILE_NAME.part")
        val target = File(directory, APK_FILE_NAME)
        partial.delete()
        val request = Request.Builder()
            .url(distribution.downloadUrl)
            .header("Accept", "application/vnd.android.package-archive")
            .header("User-Agent", "LumiAgent/${BuildConfig.VERSION_NAME}")
            .get()
            .build()
        try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    return LinuxCompanionInstallResult(false, "companion_download_http_${response.code}")
                }
                if (!response.request.url.isHttps) {
                    return LinuxCompanionInstallResult(false, "companion_download_insecure_redirect")
                }
                val body = response.body
                    ?: return LinuxCompanionInstallResult(false, "companion_download_empty")
                val declaredLength = body.contentLength()
                if (declaredLength > MAX_APK_BYTES) {
                    return LinuxCompanionInstallResult(false, "companion_download_too_large")
                }
                val digest = MessageDigest.getInstance("SHA-256")
                var total = 0L
                body.byteStream().use { input ->
                    FileOutputStream(partial).use { output ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            total += read
                            if (total > MAX_APK_BYTES) {
                                throw CompanionInstallException("companion_download_too_large")
                            }
                            digest.update(buffer, 0, read)
                            output.write(buffer, 0, read)
                        }
                        output.fd.sync()
                    }
                }
                if (total <= 0L) {
                    return LinuxCompanionInstallResult(false, "companion_download_empty")
                }
                val actualHash = digest.digest().toHex()
                if (!actualHash.equals(distribution.sha256, ignoreCase = true)) {
                    return LinuxCompanionInstallResult(false, "companion_apk_hash_mismatch")
                }
            }
            if (!verifyArchive(context, partial, distribution)) {
                return LinuxCompanionInstallResult(false, "companion_apk_identity_mismatch")
            }
            target.delete()
            if (!partial.renameTo(target)) {
                return LinuxCompanionInstallResult(false, "companion_cache_commit_failed")
            }
            return LinuxCompanionInstallResult(true, "companion_download_ready")
        } catch (error: CompanionInstallException) {
            return LinuxCompanionInstallResult(false, error.code)
        } catch (_: Exception) {
            return LinuxCompanionInstallResult(false, "companion_download_failed")
        } finally {
            partial.delete()
        }
    }

    fun promptInstall(
        context: Context,
        distribution: LinuxRuntimeDistribution? = configuredDistribution()
    ): LinuxCompanionInstallResult {
        val expected = distribution
            ?: return LinuxCompanionInstallResult(false, "companion_distribution_missing")
        val apk = File(cacheDirectory(context), APK_FILE_NAME)
        if (!apk.isFile || !verifyArchive(context, apk, expected)) {
            return LinuxCompanionInstallResult(false, "companion_verified_apk_missing")
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !context.packageManager.canRequestPackageInstalls()
        ) {
            val settingsIntent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(settingsIntent)
            return LinuxCompanionInstallResult(true, "unknown_sources_permission_required")
        }
        val apkUri = FileProvider.getUriForFile(
            context,
            "${BuildConfig.APPLICATION_ID}.fileprovider",
            apk
        )
        val installIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(apkUri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (installIntent.resolveActivity(context.packageManager) == null) {
            return LinuxCompanionInstallResult(false, "package_installer_unavailable")
        }
        context.startActivity(installIntent)
        return LinuxCompanionInstallResult(true, "package_installer_launched")
    }

    fun hasVerifiedCachedPackage(
        context: Context,
        distribution: LinuxRuntimeDistribution? = configuredDistribution()
    ): Boolean {
        val expected = distribution ?: return false
        val apk = File(cacheDirectory(context), APK_FILE_NAME)
        return apk.isFile && verifyArchive(context, apk, expected)
    }

    private fun verifyArchive(
        context: Context,
        apk: File,
        distribution: LinuxRuntimeDistribution
    ): Boolean {
        val info = archivePackageInfo(context.packageManager, apk.absolutePath) ?: return false
        return verifyPackageInfo(context, info, distribution)
    }

    private fun verifyPackageInfo(
        context: Context,
        info: PackageInfo,
        distribution: LinuxRuntimeDistribution
    ): Boolean {
        if (info.packageName != LinuxRuntimeCompanionClient.COMPANION_PACKAGE ||
            info.packageName != distribution.packageName ||
            versionCode(info) < distribution.minVersionCode
        ) return false
        val companionSigners = signerDigests(info)
        val ownInfo = runCatching {
            installedPackageInfo(context.packageManager, context.packageName)
        }.getOrNull() ?: return false
        val ownSigners = signerDigests(ownInfo)
        val expected = distribution.signerSha256.uppercase()
        return expected in companionSigners && expected in ownSigners &&
            companionSigners.intersect(ownSigners).isNotEmpty()
    }

    @Suppress("DEPRECATION")
    private fun installedPackageInfo(manager: PackageManager, packageName: String): PackageInfo =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            manager.getPackageInfo(
                packageName,
                PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES.toLong())
            )
        } else {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                PackageManager.GET_SIGNING_CERTIFICATES
            } else {
                PackageManager.GET_SIGNATURES
            }
            manager.getPackageInfo(packageName, flags)
        }

    @Suppress("DEPRECATION")
    private fun archivePackageInfo(manager: PackageManager, path: String): PackageInfo? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            manager.getPackageArchiveInfo(
                path,
                PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES.toLong())
            )
        } else {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                PackageManager.GET_SIGNING_CERTIFICATES
            } else {
                PackageManager.GET_SIGNATURES
            }
            manager.getPackageArchiveInfo(path, flags)
        }

    @Suppress("DEPRECATION")
    private fun signerDigests(info: PackageInfo): Set<String> {
        val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.signingInfo?.apkContentsSigners?.toList().orEmpty()
        } else {
            info.signatures?.toList().orEmpty()
        }
        return signatures.mapTo(linkedSetOf()) { signature ->
            MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()).toHex()
        }
    }

    @Suppress("DEPRECATION")
    private fun versionCode(info: PackageInfo): Long =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()

    private fun cacheDirectory(context: Context): File = File(context.cacheDir, "linux-runtime")

    private fun ByteArray.toHex(): String = joinToString(separator = "") { byte -> "%02X".format(byte) }

    private class CompanionInstallException(val code: String) : RuntimeException(code)
}
