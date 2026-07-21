package com.apk.claw.android.service

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.IBinder
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationCompat
import com.apk.claw.android.R
import com.apk.claw.android.server.ConfigServerManager
import com.apk.claw.android.ui.home.HomeActivity
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog

/**
 * 前台服务 - 常驻通知
 */
class ForegroundService : Service() {

    companion object {
        private const val TAG = "ForegroundService"
        const val CHANNEL_ID = "AgentPhone_foreground_channel"
        const val NOTIFICATION_ID = 1001

        @Volatile
        private var _isRunning = false
        @Volatile
        private var explicitUserStop = false

        /**
         * 检查前台服务是否正在运行
         */
        fun isRunning(): Boolean = _isRunning

        /**
         * 启动前台服务
         *
         * Android 13+ notification denial must not disable process liveness.
         * Foreground services are still allowed to run; the notification may be
         * hidden from the drawer by the OS permission policy.
         */
        fun start(context: Context): Boolean {
            val notificationPermissionGranted =
                Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                    ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
                    PackageManager.PERMISSION_GRANTED
            if (!ForegroundServiceStartPolicy.shouldAttemptStart(Build.VERSION.SDK_INT, notificationPermissionGranted)) {
                return false
            }
            explicitUserStop = false
            return try {
                val intent = Intent(context, ForegroundService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
                true
            } catch (e: Exception) {
                XLog.e(TAG, "ForegroundService start failed: ${e.message}")
                false
            }
        }

        fun stop(context: Context) {
            explicitUserStop = true
            val intent = Intent(context, ForegroundService::class.java)
            context.stopService(intent)
        }
    }

    override fun onCreate() {
        super.onCreate()
        _isRunning = true
        createNotificationChannel()
    }

    override fun onDestroy() {
        super.onDestroy()
        _isRunning = false
        if (ForegroundServiceStartPolicy.shouldStopConfigServerOnDestroy(explicitUserStop, KVUtils.isConfigServerEnabled())) {
            ConfigServerManager.stop()
        } else {
            XLog.i(TAG, "Keep ConfigServer alive while ForegroundService is being restored")
        }
        if (ForegroundServiceStartPolicy.shouldRestartAfterServiceDestroyed(explicitUserStop)) {
            scheduleRestart(0)
        }
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        scheduleRestart(1)
    }

    private fun scheduleRestart(requestCode: Int) {
        val restartIntent = Intent(applicationContext, ForegroundService::class.java)
        val flags = PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
        val pendingRestart = if (ForegroundServiceStartPolicy.shouldUseForegroundServicePendingIntent(Build.VERSION.SDK_INT)) {
            PendingIntent.getForegroundService(applicationContext, requestCode, restartIntent, flags)
        } else {
            PendingIntent.getService(applicationContext, requestCode, restartIntent, flags)
        }
        val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarmManager.set(AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + 3000, pendingRestart)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        explicitUserStop = false
        val notification = createNotification()
        startForeground(NOTIFICATION_ID, notification)
        KeepAliveJobService.schedule(applicationContext)
        ConfigServerManager.autoStartIfNeeded(applicationContext)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = getString(R.string.notification_channel_description)
                setShowBadge(false)
            }
            val notificationManager = getSystemService(NotificationManager::class.java)
            notificationManager.createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification {
        val intent = Intent(this, HomeActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_content_title))
            .setContentText(getString(R.string.notification_content_text))
            .setSmallIcon(R.drawable.ic_lumi_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setAutoCancel(false)
            .build()
    }
}
