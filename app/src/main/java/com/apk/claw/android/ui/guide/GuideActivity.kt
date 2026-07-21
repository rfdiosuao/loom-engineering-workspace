package com.apk.claw.android.ui.guide

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.core.net.toUri
import com.apk.claw.android.R
import com.apk.claw.android.base.BaseActivity
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.service.ForegroundService
import com.apk.claw.android.utils.KVUtils

class GuideActivity : BaseActivity() {

    private data class Section(
        val view: View,
        val baseDesc: String,
        val isGranted: () -> Boolean,
    )

    private val sections = mutableListOf<Section>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_guide)

        bindSection(
            R.id.guideAccessibility, R.drawable.ic_accessibility,
            R.string.guide_title_accessibility, R.string.guide_desc_accessibility,
            isGranted = { ClawAccessibilityService.isRunning() },
            onClick = { openAccessibility() },
        )
        bindSection(
            R.id.guideNotification, R.drawable.ic_notification,
            R.string.guide_title_notification, R.string.guide_desc_notification,
            isGranted = { ForegroundService.isRunning() },
            onClick = { openAppDetails() },
        )
        bindSection(
            R.id.guideOverlay, R.drawable.ic_window,
            R.string.guide_title_overlay, R.string.guide_desc_overlay,
            isGranted = { Settings.canDrawOverlays(this) },
            onClick = { startSafely(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, "package:$packageName".toUri())) },
        )
        bindSection(
            R.id.guideBattery, R.drawable.ic_battery,
            R.string.guide_title_battery, R.string.guide_desc_battery,
            isGranted = { (getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName) },
            onClick = { startSafely(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, "package:$packageName".toUri())) },
        )
        bindSection(
            R.id.guideStorage, R.drawable.ic_storage,
            R.string.guide_title_storage, R.string.guide_desc_storage,
            isGranted = { isStorageGranted() },
            onClick = { openStorage() },
        )

        findViewById<View>(R.id.btnStart).setOnClickListener { finishGuide() }
        findViewById<View>(R.id.tvSkip).setOnClickListener { finishGuide() }
    }

    override fun onResume() {
        super.onResume()
        refreshStatuses()
    }

    private fun bindSection(
        sectionId: Int,
        iconRes: Int,
        titleRes: Int,
        descRes: Int,
        isGranted: () -> Boolean,
        onClick: () -> Unit,
    ) {
        val view = findViewById<View>(sectionId)
        view.findViewById<ImageView>(R.id.ivIcon).setImageResource(iconRes)
        view.findViewById<TextView>(R.id.tvTitle).setText(titleRes)
        val baseDesc = getString(descRes)
        view.findViewById<TextView>(R.id.tvDescription).text = baseDesc
        view.isClickable = true
        view.setOnClickListener { onClick() }
        sections.add(Section(view, baseDesc, isGranted))
    }

    private fun refreshStatuses() {
        for (section in sections) {
            val granted = runCatching { section.isGranted() }.getOrDefault(false)
            val status = if (granted) "✅ 已开启" else "⚠ 未开启 · 点这里去开启"
            section.view.findViewById<TextView>(R.id.tvDescription).text = "${section.baseDesc}\n$status"
        }
    }

    private fun openAccessibility() {
        startSafely(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        if (!ClawAccessibilityService.isRunning()) {
            Toast.makeText(
                this,
                "若开关是灰色：返回 → 应用信息 → 右上角 ⋮ → 允许受限的设置，再来开启（无需电脑）",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    private fun openAppDetails() {
        startSafely(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, "package:$packageName".toUri()))
    }

    private fun openStorage() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startSafely(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, "package:$packageName".toUri()))
        } else {
            openAppDetails()
        }
    }

    private fun isStorageGranted(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            true
        }
    }

    private fun startSafely(intent: Intent) {
        runCatching { startActivity(intent) }
    }

    private fun finishGuide() {
        KVUtils.setGuideShown(true)
        finish()
    }
}
