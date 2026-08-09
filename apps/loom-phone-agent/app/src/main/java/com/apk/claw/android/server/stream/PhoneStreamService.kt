package com.apk.claw.android.server.stream

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.apk.claw.android.R
import com.apk.claw.android.ui.home.HomeActivity
import com.apk.claw.android.utils.XLog
import kotlin.math.roundToInt

class PhoneStreamService : Service() {
    companion object {
        private const val TAG = "PhoneStreamService"
        private const val CHANNEL_ID = "luming_phone_stream"
        private const val NOTIFICATION_ID = 1402
        private const val MAX_SESSION_MS = 60 * 60 * 1000L

        const val ACTION_START = "com.apk.claw.android.action.START_PHONE_STREAM"
        const val ACTION_STOP = "com.apk.claw.android.action.STOP_PHONE_STREAM"
        const val EXTRA_SESSION_ID = "stream_session_id"
        const val EXTRA_RESULT_CODE = "stream_result_code"
        const val EXTRA_RESULT_DATA = "stream_result_data"
        const val EXTRA_FPS = "stream_fps"
        const val EXTRA_MAX_LONG_SIDE = "stream_max_long_side"
        const val EXTRA_BIT_RATE = "stream_bit_rate"
    }

    private val handler = Handler(Looper.getMainLooper())
    private var sessionId: String = ""
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var encoder: H264Encoder? = null
    private var stopping = false

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            stopStreaming("projection_stopped")
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startStreaming(intent)
            ACTION_STOP -> {
                val requested = intent.getStringExtra(EXTRA_SESSION_ID).orEmpty()
                if (requested.isBlank() || requested == sessionId) stopStreaming("api_stop")
            }
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopStreaming("service_destroyed")
        super.onDestroy()
    }

    private fun startStreaming(intent: Intent) {
        val requestedSessionId = intent.getStringExtra(EXTRA_SESSION_ID).orEmpty()
        if (requestedSessionId.isBlank() || !PhoneStreamRuntime.sessions.isCurrent(requestedSessionId)) {
            stopSelf()
            return
        }
        if (encoder != null && sessionId == requestedSessionId) return
        if (encoder != null) cleanup()
        sessionId = requestedSessionId
        stopping = false
        try {
            startAsForeground()
            val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
            val resultData = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(EXTRA_RESULT_DATA)
            } ?: error("Missing MediaProjection permission data")
            val projectionManager = getSystemService(MediaProjectionManager::class.java)
            projection = projectionManager.getMediaProjection(resultCode, resultData)
                ?: error("MediaProjection unavailable")
            projection?.registerCallback(projectionCallback, handler)

            val fps = intent.getIntExtra(EXTRA_FPS, 15).coerceIn(10, 20)
            val maxLongSide = intent.getIntExtra(EXTRA_MAX_LONG_SIDE, 1280).coerceIn(480, 1600)
            val bitRate = intent.getIntExtra(EXTRA_BIT_RATE, 2_400_000).coerceIn(600_000, 8_000_000)
            val size = resolveVideoSize(maxLongSide)
            val streamEncoder = H264Encoder(
                width = size.first,
                height = size.second,
                fps = fps,
                bitRate = bitRate,
                onAccessUnit = { bytes, presentationTimeUs, keyFrame ->
                    PhoneStreamRuntime.sessions.publish(
                        requestedSessionId,
                        bytes,
                        presentationTimeUs,
                        keyFrame
                    )
                },
                onError = { error ->
                    XLog.e(TAG, "H.264 encoder failed: ${error.message}")
                    PhoneStreamRuntime.sessions.markError(requestedSessionId, "H.264 编码器异常，矩阵已降级为截图")
                    handler.post { stopStreaming("encoder_error") }
                }
            )
            val surface = streamEncoder.start()
            encoder = streamEncoder
            virtualDisplay = projection?.createVirtualDisplay(
                "LumingPhoneFocusStream",
                size.first,
                size.second,
                resources.displayMetrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                surface,
                null,
                handler
            ) ?: error("Unable to create stream virtual display")
            PhoneStreamRuntime.sessions.markActive(
                requestedSessionId,
                width = size.first,
                height = size.second,
                codec = H264Encoder.CODEC
            )
            streamEncoder.requestSyncFrame()
            handler.postDelayed({ stopStreaming("session_limit") }, MAX_SESSION_MS)
            XLog.i(TAG, "Low-latency stream active session=$requestedSessionId ${size.first}x${size.second}@$fps")
        } catch (error: Exception) {
            XLog.e(TAG, "Phone stream start failed: ${error.message}")
            PhoneStreamRuntime.sessions.markError(requestedSessionId, "低延迟画面启动失败，矩阵已降级为截图")
            cleanup()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopStreaming(reason: String) {
        if (stopping) return
        stopping = true
        val closingSession = sessionId
        XLog.i(TAG, "Low-latency stream stopped ($reason) session=$closingSession")
        cleanup()
        if (closingSession.isNotBlank()) PhoneStreamRuntime.sessions.stopFromService(closingSession)
        sessionId = ""
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun cleanup() {
        handler.removeCallbacksAndMessages(null)
        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }
        virtualDisplay = null
        encoder?.stop()
        encoder = null
        try {
            projection?.unregisterCallback(projectionCallback)
            projection?.stop()
        } catch (_: Exception) {
        }
        projection = null
    }

    private fun resolveVideoSize(maxLongSide: Int): Pair<Int, Int> {
        val bounds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            getSystemService(WindowManager::class.java).currentWindowMetrics.bounds
        } else {
            @Suppress("DEPRECATION")
            Rect().also { getSystemService(WindowManager::class.java).defaultDisplay.getRectSize(it) }
        }
        var width = bounds.width().takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        var height = bounds.height().takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
        val longest = maxOf(width, height)
        if (longest > maxLongSide) {
            val scale = maxLongSide.toFloat() / longest.toFloat()
            width = (width * scale).roundToInt()
            height = (height * scale).roundToInt()
        }
        width = width.coerceAtLeast(320).makeEven()
        height = height.coerceAtLeast(320).makeEven()
        return width to height
    }

    private fun Int.makeEven(): Int = if (this % 2 == 0) this else this - 1

    private fun startAsForeground() {
        val notification = createNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "麓鸣低延迟画面",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "当前聚焦设备正在向已配对的麓鸣桌面传输画面"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun createNotification(): Notification {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, HomeActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, PhoneStreamService::class.java).apply {
                action = ACTION_STOP
                putExtra(EXTRA_SESSION_ID, sessionId)
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_lumi_notification)
            .setContentTitle("麓鸣正在传输聚焦画面")
            .setContentText("仅已配对桌面可访问；点击可返回应用")
            .setContentIntent(contentIntent)
            .addAction(R.drawable.ic_lumi_notification, "停止", stopIntent)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }
}
