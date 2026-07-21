package com.apk.claw.android.ui.home

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.os.Build
import android.Manifest
import android.graphics.drawable.GradientDrawable
import android.os.Environment
import android.widget.Toast
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import com.apk.claw.android.BuildConfig
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.service.ForegroundService
import androidx.core.content.ContextCompat
import android.view.View
import com.apk.claw.android.R
import com.apk.claw.android.appViewModel
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.rpa.RpaRunStatus
import com.apk.claw.android.rpa.RpaWorkflowRunner
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.service.AccessibilityStateInspector
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.ui.guide.GuideActivity
import com.apk.claw.android.ui.settings.SettingsActivity
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.widget.CommonToolbar
import com.apk.claw.android.widget.PermissionCardView
import com.apk.claw.android.widget.KButton
import androidx.core.net.toUri
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 首页 - 权限管理
 */
class HomeActivity : BaseActivity() {

    companion object {
        private const val TAG = "HomeActivity"
    }

    private lateinit var cardAccessibility: PermissionCardView
    private lateinit var cardNotification: PermissionCardView
    private lateinit var cardSystemWindow: PermissionCardView
    private lateinit var cardBattery: PermissionCardView
    private lateinit var cardStorage: PermissionCardView
    private lateinit var btnCancelTask: KButton
    private lateinit var tvReadinessBadge: TextView
    private lateinit var tvReadinessTitle: TextView
    private lateinit var tvReadinessSubtitle: TextView
    private lateinit var tvReadinessMeta: TextView
    private lateinit var tvControlPlaneHttp: TextView
    private lateinit var tvControlPlaneLumi: TextView
    private lateinit var tvControlPlaneModel: TextView
    private lateinit var tvControlPlaneRpa: TextView
    private lateinit var tvTaskConsoleBody: TextView

    private val timeFormat by lazy { SimpleDateFormat("HH:mm:ss", Locale.getDefault()) }

    private val handler = Handler(Looper.getMainLooper())
    private val checkRunnable = object : Runnable {
        override fun run() {
            updateAllPermissionStatus()
            handler.postDelayed(this, 1000)
        }
    }

    // Activity Result API - 存储权限请求 (Android 6~10)
    private val storagePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val allGranted = results.values.all { it }
        if (allGranted) {
            Toast.makeText(this, R.string.home_storage_enabled, Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, R.string.home_enable_storage, Toast.LENGTH_SHORT).show()
        }
        updateStorageStatus()
    }

    // Activity Result API - 通知权限请求
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            // 授权成功，启动前台服务
            startNotificationService()
        } else {
            Toast.makeText(this, R.string.home_need_notification_permission, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_home)

        initViews()
        showGuideIfNeeded()
    }

    override fun onDestroy() {
        super.onDestroy()
    }

    override fun onResume() {
        super.onResume()
        updateAllPermissionStatus()
        startStatusCheck()
    }

    override fun onPause() {
        super.onPause()
        stopStatusCheck()
    }

    private fun showGuideIfNeeded() {
        if (!KVUtils.isGuideShown()) {
            startActivity(Intent(this, GuideActivity::class.java))
        }
    }

    private fun initViews() {
        // Toolbar
        findViewById<CommonToolbar>(R.id.toolbar).apply {
            setTitleCentered(false)
            setTitle(getString(R.string.home_agent_status_title))
            setActionIcon(R.drawable.ic_settings) {
                startActivity(Intent(this@HomeActivity, SettingsActivity::class.java))
            }
        }

        // 卡片
        tvReadinessBadge = findViewById(R.id.tvReadinessBadge)
        tvReadinessTitle = findViewById(R.id.tvReadinessTitle)
        tvReadinessSubtitle = findViewById(R.id.tvReadinessSubtitle)
        tvReadinessMeta = findViewById(R.id.tvReadinessMeta)
        tvControlPlaneHttp = findViewById(R.id.tvControlPlaneHttp)
        tvControlPlaneLumi = findViewById(R.id.tvControlPlaneLumi)
        tvControlPlaneModel = findViewById(R.id.tvControlPlaneModel)
        tvControlPlaneRpa = findViewById(R.id.tvControlPlaneRpa)
        tvTaskConsoleBody = findViewById(R.id.tvTaskConsoleBody)

        cardAccessibility = findViewById(R.id.cardAccessibility)
        cardNotification = findViewById(R.id.cardNotification)
        cardSystemWindow = findViewById(R.id.cardSystemWindow)
        cardBattery = findViewById(R.id.cardBattery)
        cardStorage = findViewById(R.id.cardStorage)

        // 结束会话按钮
        btnCancelTask = findViewById(R.id.btnCancelTask)
        btnCancelTask.setOnClickListener {
            if (appViewModel.isTaskRunning()) {
                appViewModel.cancelCurrentTask()
                Toast.makeText(this, R.string.home_cancel_task_success, Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, R.string.home_no_task_running, Toast.LENGTH_SHORT).show()
            }
            updateCancelTaskVisibility()
        }

        // 点击卡片申请权限
        cardAccessibility.setOnClickListener { requestAccessibilityPermission() }
        cardNotification.setOnClickListener { requestNotificationPermission() }
        cardSystemWindow.setOnClickListener { requestSystemWindowPermission() }
        cardBattery.setOnClickListener { requestBatteryPermission() }
        cardStorage.setOnClickListener { requestStoragePermission() }
    }

    private fun updateAllPermissionStatus() {
        updateAccessibilityStatus()
        updateNotificationStatus()
        updateSystemWindowStatus()
        updateBatteryStatus()
        updateStorageStatus()
        updateReadinessStatus()
        updateControlConsoleStatus()
        updateCancelTaskVisibility()
    }

    private fun updateCancelTaskVisibility() {
        btnCancelTask.visibility = if (appViewModel.isTaskRunning()) View.VISIBLE else View.GONE
    }

    private fun updateAccessibilityStatus() {
        val state = AccessibilityStateInspector.inspect(this)
        when {
            state.healthy -> cardAccessibility.setPermissionEnabled(true)
            state.staleEnabledNotBound -> cardAccessibility.setPermissionWarning(
                getString(R.string.home_permission_rebind_required)
            )
            else -> cardAccessibility.setPermissionEnabled(false)
        }
    }

    private fun updateNotificationStatus() {
        cardNotification.setPermissionEnabled(ForegroundService.isRunning())
    }

    private fun updateSystemWindowStatus() {
        val enabled = Settings.canDrawOverlays(this)
        cardSystemWindow.setPermissionEnabled(enabled)
        if (enabled) {
            appViewModel.showFloatingCircle()
        }
    }

    private fun updateBatteryStatus() {
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        cardBattery.setPermissionEnabled(powerManager.isIgnoringBatteryOptimizations(packageName))
    }

    private fun updateStorageStatus() {
        cardStorage.setPermissionEnabled(isStoragePermissionGranted())
    }

    private fun updateReadinessStatus() {
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        val accessibilityState = AccessibilityStateInspector.inspect(this)
        val states = listOf(
            accessibilityState.healthy,
            ForegroundService.isRunning(),
            Settings.canDrawOverlays(this),
            powerManager.isIgnoringBatteryOptimizations(packageName),
            isStoragePermissionGranted()
        )
        val readyCount = states.count { it }
        val ready = readyCount == states.size

        tvReadinessTitle.text = getString(R.string.home_agent_status_title)
        tvReadinessSubtitle.text = getString(
            if (ready) R.string.home_agent_status_ready else R.string.home_agent_status_setup
        )
        tvReadinessMeta.text = getString(
            R.string.home_agent_status_meta,
            readyCount,
            controlPlaneAddressLabel(),
            BuildConfig.VERSION_NAME
        )
        tvReadinessBadge.text = getString(
            if (ready) R.string.home_agent_status_ready_badge else R.string.home_agent_status_setup_badge
        )
        val backgroundColor = if (ready) R.color.colorSuccessContainer else R.color.colorWarningContainer
        val borderColor = if (ready) R.color.colorSuccessPrimary else R.color.colorWarningPrimary
        val textColor = if (ready) R.color.colorSuccessOnContainer else R.color.colorWarningOnContainer
        tvReadinessBadge.background = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(999).toFloat()
            setColor(ContextCompat.getColor(this@HomeActivity, backgroundColor))
            setStroke(dp(1), ContextCompat.getColor(this@HomeActivity, borderColor))
        }
        tvReadinessBadge.setTextColor(ContextCompat.getColor(this, textColor))
    }

    private fun updateControlConsoleStatus() {
        val httpStatus = when {
            ConfigServerManager.isRunning() -> {
                val address = ConfigServerManager.getAddress()
                if (address.isNullOrBlank()) "online, resolving LAN address" else "online http://$address"
            }
            KVUtils.isConfigServerEnabled() -> "waiting for Wi-Fi, hotspot, or ADB reverse"
            else -> "stopped, open Settings > LAN Config if needed"
        }
        val lumiStatus = if (KVUtils.getLumiLauncherId().isNotBlank() && KVUtils.getLumiLauncherSecret().isNotBlank()) {
            val launcher = KVUtils.getLumiLauncherName().ifBlank { "paired launcher" }
            "paired with $launcher"
        } else {
            "not paired"
        }
        val modelStatus = if (KVUtils.hasLlmConfig()) {
            "configured ${KVUtils.getLlmModelName().ifBlank { "model" }}"
        } else {
            "not configured"
        }
        val latestRpa = RpaWorkflowRunner.list().firstOrNull()
        val rpaStatus = latestRpa?.let { run ->
            val step = if (run.totalSteps > 0) "${run.currentStep}/${run.totalSteps}" else "0/0"
            val action = run.currentAction.ifBlank { run.message.ifBlank { run.status.wireName } }
            "${run.status.wireName} step=$step action=${action.take(24)} totalMs=${run.totalMs}"
        } ?: "idle"

        tvControlPlaneHttp.text = "HTTP  $httpStatus"
        tvControlPlaneLumi.text = "Lumi  $lumiStatus"
        tvControlPlaneModel.text = "Model $modelStatus"
        tvControlPlaneRpa.text = "RPA   $rpaStatus"
        tvTaskConsoleBody.text = buildTaskConsoleText(latestRpa)
    }

    private fun buildTaskConsoleText(latestRpa: com.apk.claw.android.rpa.RpaRunSnapshot?): String {
        val now = timeFormat.format(Date())
        if (appViewModel.isTaskRunning()) {
            val messageId = appViewModel.inProgressTaskMessageId.ifBlank { "agent" }
            val channel = appViewModel.inProgressTaskChannel?.displayName ?: "API"
            return getString(R.string.home_task_console_agent_running, channel, messageId, now)
        }
        if (latestRpa != null) {
            val action = latestRpa.currentAction.ifBlank { latestRpa.message }
            return getString(
                R.string.home_task_console_rpa,
                rpaStatusLabel(latestRpa.status),
                latestRpa.workflowName.take(32),
                latestRpa.currentStep,
                latestRpa.totalSteps,
                readableRpaAction(action).take(32),
                latestRpa.totalMs,
                now
            )
        }
        FloatingCircleManager.getRecentLog(this)?.let { return it }
        return getString(R.string.home_task_console_idle)
    }

    private fun rpaStatusLabel(status: RpaRunStatus): String = getString(
        when (status) {
            RpaRunStatus.QUEUED -> R.string.home_task_console_rpa_queued
            RpaRunStatus.RUNNING -> R.string.home_task_console_rpa_running
            RpaRunStatus.SUCCEEDED -> R.string.home_task_console_rpa_succeeded
            RpaRunStatus.FAILED -> R.string.home_task_console_rpa_failed
            RpaRunStatus.CANCELLED -> R.string.home_task_console_rpa_cancelled
        }
    )

    private fun readableRpaAction(action: String): String = when (action.trim().lowercase(Locale.ROOT)) {
        "open_app" -> getString(R.string.floating_tool_open_app)
        "get_screen_info", "observe", "observe_fast" -> getString(R.string.floating_tool_read_screen)
        "tap", "click" -> getString(R.string.floating_tool_tap)
        "input_text", "type" -> getString(R.string.floating_tool_input_text)
        "swipe", "scroll" -> getString(R.string.floating_tool_swipe)
        "system_key", "back", "home" -> getString(R.string.floating_tool_system_key)
        "screenshot" -> getString(R.string.floating_tool_screenshot)
        "finish" -> getString(R.string.floating_tool_finish)
        "" -> getString(R.string.home_task_console_rpa_preparing)
        else -> action.replace('_', ' ').trim()
    }

    private fun controlPlaneAddressLabel(): String {
        if (!ConfigServerManager.isRunning()) {
            return "LAN stopped"
        }
        val address = ConfigServerManager.getAddress()
        return if (address.isNullOrBlank()) "LAN resolving" else "LAN $address"
    }

    private fun isStoragePermissionGranted(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) ==
                    android.content.pm.PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
                    android.content.pm.PackageManager.PERMISSION_GRANTED
        }
    }

    private fun checkAllPermissionsGranted(): Boolean {
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        return AccessibilityStateInspector.inspect(this).healthy &&
                ForegroundService.isRunning() &&
                Settings.canDrawOverlays(this) &&
                powerManager.isIgnoringBatteryOptimizations(packageName) &&
                isStoragePermissionGranted()
    }

    // ==================== 权限申请 ====================

    private fun requestAccessibilityPermission() {
        if (AccessibilityStateInspector.inspect(this).healthy) {
            Toast.makeText(this, R.string.home_accessibility_enabled, Toast.LENGTH_SHORT).show()
            return
        }
        // 无障碍是截屏/点击的核心。侧载安装在 Android 13+ 会被「受限设置」拦住，
        // 开关是灰的，必须先到「应用信息 → ⋮ → 允许受限的设置」。这里直接给指引和跳转，
        // 避免用户卡住、避免依赖 ADB。
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("开启无障碍服务")
            .setMessage(
                "无障碍服务用于截屏和模拟点击，是远程控制的核心。\n\n" +
                    "① 点「打开无障碍设置」，找到本应用并打开开关。\n\n" +
                    "如果开关是灰色，或提示「受限设置 / 出于安全暂时无法使用」" +
                    "（侧载安装的常见限制）：\n" +
                    "② 点「去应用信息」→ 右上角 ⋮ 菜单 → 「允许受限的设置」→ " +
                    "再回到第 ① 步开启。全程无需电脑/ADB。"
            )
            .setPositiveButton("打开无障碍设置") { _, _ ->
                runCatching { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
                Toast.makeText(this, R.string.home_enable_accessibility, Toast.LENGTH_LONG).show()
            }
            .setNeutralButton("去应用信息") { _, _ ->
                runCatching {
                    startActivity(
                        Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            "package:$packageName".toUri()
                        )
                    )
                }
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun requestNotificationPermission() {
        // Android 13+ 需要申请通知权限
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                // 使用 Activity Result API 请求权限
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                return
            }
        }

        startNotificationService()
    }

    private fun startNotificationService() {
        val started = ForegroundService.start(this)
        if (started) {
            cardNotification.setPermissionEnabled(true)
            Toast.makeText(this, R.string.home_notification_enabled, Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, R.string.home_need_notification_permission, Toast.LENGTH_SHORT).show()
            updateNotificationStatus()
        }
    }

    private fun requestSystemWindowPermission() {
        if (!Settings.canDrawOverlays(this)) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                "package:$packageName".toUri()
            )
            startActivity(intent)
        } else {
            Toast.makeText(this, R.string.home_overlay_enabled, Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestStoragePermission() {
        if (isStoragePermissionGranted()) {
            Toast.makeText(this, R.string.home_storage_enabled, Toast.LENGTH_SHORT).show()
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            // Android 11+: 跳转到「所有文件访问」设置页
            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.data = "package:$packageName".toUri()
            startActivity(intent)
            Toast.makeText(this, R.string.home_enable_storage, Toast.LENGTH_LONG).show()
        } else {
            // Android 6~10: 运行时请求读写权限
            storagePermissionLauncher.launch(
                arrayOf(
                    Manifest.permission.READ_EXTERNAL_STORAGE,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE
                )
            )
        }
    }

    private fun requestBatteryPermission() {
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = "package:$packageName".toUri()
            startActivity(intent)
        } else {
            Toast.makeText(this, R.string.home_battery_ignored, Toast.LENGTH_SHORT).show()
        }
    }

    private fun startStatusCheck() {
        stopStatusCheck();
        handler.postDelayed(checkRunnable, 1000)
    }

    private fun stopStatusCheck() {
        handler.removeCallbacks(checkRunnable)
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

}
