package com.apk.claw.android.privilege

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import rikka.shizuku.Shizuku
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Optional Shizuku/Sui capability detector and permission controller.
 *
 * It exposes no process, shell, binder-wrapper, command-string, or remote execution API.
 * Privileged actions must pass [PrivilegedActionPolicy] and a separately reviewed typed executor.
 */
object ShizukuPrivilegeBackend : PrivilegeBackendController {
    private const val MANAGER_PACKAGE = "moe.shizuku.privileged.api"
    private const val DOWNLOAD_URL = "https://shizuku.rikka.app/download/"
    private const val PREFS_NAME = "lumi_privilege_preferences"
    private const val KEY_USER_ENABLED = "shizuku_enhanced_enabled"
    private const val REQUEST_CODE = 0x4c55

    private val initialized = AtomicBoolean(false)
    private lateinit var appContext: Context
    private val _status = MutableStateFlow(
        PrivilegeBackendStatus(
            probe = PrivilegeProbe(shizukuInstalled = false),
            selection = PrivilegeBackendSelector.select(PrivilegeProbe(shizukuInstalled = false))
        )
    )
    val status: StateFlow<PrivilegeBackendStatus> = _status.asStateFlow()

    private val binderReceivedListener = Shizuku.OnBinderReceivedListener { refresh() }
    private val binderDeadListener = Shizuku.OnBinderDeadListener { refresh() }
    private val permissionResultListener = Shizuku.OnRequestPermissionResultListener { requestCode, _ ->
        if (requestCode == REQUEST_CODE) refresh()
    }

    fun initialize(context: Context) {
        if (!initialized.compareAndSet(false, true)) return
        appContext = context.applicationContext
        Shizuku.addBinderReceivedListener(binderReceivedListener)
        Shizuku.addBinderDeadListener(binderDeadListener)
        Shizuku.addRequestPermissionResultListener(permissionResultListener)
        refresh()
    }

    override fun current(): PrivilegeBackendSelection = _status.value.selection

    override fun setUserEnabled(enabled: Boolean) {
        if (!initialized.get()) return
        preferences().edit().putBoolean(KEY_USER_ENABLED, enabled).apply()
        refresh()
    }

    override fun requestAuthorization(): Boolean {
        if (!initialized.get()) return false
        val state = _status.value
        if (!state.probe.binderAlive || !state.selection.shouldRequestPermission) return false
        return runCatching {
            Shizuku.requestPermission(REQUEST_CODE)
            true
        }.getOrDefault(false)
    }

    override fun refresh() {
        if (!initialized.get()) return
        val installed = isManagerInstalled()
        val enabled = preferences().getBoolean(KEY_USER_ENABLED, false)
        val binderAlive = runCatching { Shizuku.pingBinder() }.getOrDefault(false)
        val permissionGranted = binderAlive && runCatching {
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        }.getOrDefault(false)
        val permanentlyDenied = binderAlive && !permissionGranted && runCatching {
            Shizuku.shouldShowRequestPermissionRationale()
        }.getOrDefault(false)
        val identityUid = if (binderAlive) runCatching { Shizuku.getUid() }.getOrNull() else null
        val probe = PrivilegeProbe(
            shizukuInstalled = installed,
            userEnabled = enabled,
            binderAlive = binderAlive,
            permissionGranted = permissionGranted,
            permissionPermanentlyDenied = permanentlyDenied,
            identityUid = identityUid,
            // Root/Sui is a separate product and legal gate. There is no UI switch in 2.4.2.
            allowSui = false
        )
        _status.value = PrivilegeBackendStatus(probe, PrivilegeBackendSelector.select(probe))
    }

    fun openManagerOrDownload(context: Context): Boolean {
        val managerIntent = context.packageManager.getLaunchIntentForPackage(MANAGER_PACKAGE)
        val intent = managerIntent ?: Intent(Intent.ACTION_VIEW, Uri.parse(DOWNLOAD_URL))
        return runCatching {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        }.getOrDefault(false)
    }

    private fun preferences() = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun isManagerInstalled(): Boolean = runCatching {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            appContext.packageManager.getPackageInfo(
                MANAGER_PACKAGE,
                PackageManager.PackageInfoFlags.of(0)
            )
        } else {
            @Suppress("DEPRECATION")
            appContext.packageManager.getPackageInfo(MANAGER_PACKAGE, 0)
        }
        true
    }.getOrDefault(false)
}
