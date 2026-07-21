package com.apk.claw.android

import android.os.PowerManager
import androidx.lifecycle.ViewModel
import com.apk.claw.android.ClawApplication.Companion.appViewModelInstance
import com.apk.claw.android.agent.AgentConfig
import com.apk.claw.android.channel.Channel
import com.apk.claw.android.channel.ChannelManager
import com.apk.claw.android.channel.ChannelSetup
import com.apk.claw.android.service.ForegroundService
import com.apk.claw.android.floating.FloatingCircleManager
import com.apk.claw.android.publish.PublishRelayManager
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.service.KeepAliveJobService
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog

class AppViewModel : ViewModel() {

    companion object {
        private const val TAG = "AppViewModel"
    }

    private var wakeLock: PowerManager.WakeLock? = null

    private var _commonInitialized = false

    val taskOrchestrator = TaskOrchestrator(
        agentConfigProvider = { getAgentConfig() },
        onTaskFinished = { /* 刷新 */ }
    )

    private val channelSetup = ChannelSetup(taskOrchestrator = taskOrchestrator)

    val inProgressTaskMessageId: String get() = taskOrchestrator.inProgressTaskMessageId
    val inProgressTaskChannel: Channel? get() = taskOrchestrator.inProgressTaskChannel

    fun init() {
        initCommon()
        initAgent()
    }

    fun initCommon() {
        if (_commonInitialized) return
        _commonInitialized = true
    }

    fun initAgent() {
        if (!KVUtils.hasLlmConfig()) return
        taskOrchestrator.initAgent()
    }

    fun getAgentConfig(): AgentConfig {
        var baseUrl = KVUtils.getLlmBaseUrl().trim()
        if (baseUrl.isEmpty()) baseUrl = "https://api.openai.com/v1"
        return AgentConfig.Builder()
            .apiKey(KVUtils.getLlmApiKey())
            .baseUrl(baseUrl)
            .modelName(KVUtils.getLlmModelName())
            .temperature(0.1)
            .maxIterations(60)
            .build()
    }

    fun updateAgentConfig(): Boolean = taskOrchestrator.updateAgentConfig()

    fun ensureControlPlane() {
        if (!ForegroundService.isRunning()) {
            val started = ForegroundService.start(ClawApplication.instance)
            if (!started) {
                XLog.e(TAG, "ForegroundService start failed during control plane init")
            }
        }
        KeepAliveJobService.schedule(ClawApplication.instance)
        ConfigServerManager.autoStartIfNeeded(ClawApplication.instance)
    }

    fun afterInit() {
        ensureControlPlane()
        acquireScreenWakeLock()
        if (android.provider.Settings.canDrawOverlays(ClawApplication.instance)) {
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                appViewModelInstance.showFloatingCircle()
            }
        }
        channelSetup.setup()
        PublishRelayManager.syncFromStorage()
    }


    /**
     * 获取亮屏锁，防止息屏后无障碍服务无法操作
     */
    private fun acquireScreenWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = ClawApplication.instance.getSystemService(android.content.Context.POWER_SERVICE) as? PowerManager
            ?: return
        wakeLock = pm.newWakeLock(
            PowerManager.SCREEN_DIM_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "AgentPhone::ScreenWakeLock"
        ).apply {
            acquire()
        }
        XLog.i(TAG, "亮屏锁已获取")
    }

    /**
     * 释放亮屏锁
     */
    private fun releaseScreenWakeLock() {
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
                XLog.i(TAG, "亮屏锁已释放")
            }
        }
        wakeLock = null
    }

    /**
     * 显示圆形悬浮窗
     */
    fun showFloatingCircle() {
        try {
            FloatingCircleManager.show(ClawApplication.instance)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to show floating circle: ${e.message}")
        }
    }

    fun isTaskRunning(): Boolean = taskOrchestrator.isTaskRunning()

    fun cancelCurrentTask() = taskOrchestrator.cancelCurrentTask()

    fun startNewTask(channel: Channel, task: String, messageID: String) =
        taskOrchestrator.startNewTask(channel, task, messageID)

    /**
     * 执行定时任务（由 TaskScheduler 调用）
     * 直接唤醒 Agent 执行指定任务
     */
    fun executeScheduledTask(prompt: String, channel: Channel?, targetUserId: String?) {
        XLog.i(TAG, "执行定时任务: $prompt")

        // 如果没有正在运行的任务，直接启动
        if (!isTaskRunning()) {
            // 使用虚拟 messageID 启动任务
            val messageId = "scheduled_${System.currentTimeMillis()}"

            if (channel != null && targetUserId != null) {
                // 有渠道信息，正常启动
                startNewTask(channel, prompt, messageId)
            } else {
                XLog.w(TAG, "定时任务缺少渠道信息，无法返回结果")
            }
        } else {
            XLog.w(TAG, "有任务正在执行，跳过定时任务")
            // 通知用户
            if (channel != null && targetUserId != null) {
                ChannelManager.sendMessageToUser(channel, targetUserId, "⚠️ 当前有任务正在执行，定时任务已跳过")
            }
        }
    }

    private fun trySendScreenshot(channel: Channel, filePath: String, messageID: String) {
        try {
            val file = java.io.File(filePath)
            if (!file.exists()) {
                XLog.w(TAG, "截图文件不存在: $filePath")
                return
            }
            val imageBytes = file.readBytes()
            ChannelManager.sendImage(channel, imageBytes, messageID)
        } catch (e: Exception) {
            XLog.e(TAG, "发送截图失败", e)
        }
    }
}
