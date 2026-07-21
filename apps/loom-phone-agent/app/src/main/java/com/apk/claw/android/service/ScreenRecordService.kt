package com.apk.claw.android.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.apk.claw.android.R
import com.apk.claw.android.media.ScreenRecordManager
import com.apk.claw.android.ui.home.HomeActivity
import com.apk.claw.android.utils.XLog
import java.io.File
import kotlin.math.roundToInt

class ScreenRecordService : Service() {

    companion object {
        private const val TAG = "ScreenRecordService"
        private const val CHANNEL_ID = "AgentPhone_screen_record_channel"
        private const val NOTIFICATION_ID = 1401

        const val ACTION_START = "com.apk.claw.android.action.START_SCREEN_RECORD"
        const val ACTION_STOP = "com.apk.claw.android.action.STOP_SCREEN_RECORD"

        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_WIDTH = "width"
        const val EXTRA_HEIGHT = "height"
        const val EXTRA_FPS = "fps"
        const val EXTRA_BIT_RATE = "bit_rate"
        const val EXTRA_MAX_SECONDS = "max_seconds"
        const val EXTRA_FILENAME = "filename"
    }

    private val handler = Handler(Looper.getMainLooper())
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null
    private var stopPosted = false

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            stopRecording("projection_stopped")
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording(intent)
            ACTION_STOP -> stopRecording("api_stop")
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopRecording("service_destroyed")
        super.onDestroy()
    }

    private fun startRecording(intent: Intent) {
        if (recorder != null) {
            return
        }

        try {
            startAsForeground()

            val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
            val resultData = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(EXTRA_RESULT_DATA)
            } ?: throw IllegalStateException("Missing MediaProjection permission data")

            val projectionManager = getSystemService(MediaProjectionManager::class.java)
            projection = projectionManager.getMediaProjection(resultCode, resultData)
                ?: throw IllegalStateException("MediaProjection unavailable")
            projection?.registerCallback(projectionCallback, handler)

            val size = resolveVideoSize(
                intent.getIntExtra(EXTRA_WIDTH, 0),
                intent.getIntExtra(EXTRA_HEIGHT, 0)
            )
            val fps = intent.getIntExtra(EXTRA_FPS, 30).coerceIn(10, 60)
            val bitRate = intent.getIntExtra(EXTRA_BIT_RATE, 4_000_000).coerceIn(800_000, 20_000_000)
            val maxSeconds = intent.getIntExtra(EXTRA_MAX_SECONDS, 180).coerceIn(1, 600)
            val filename = intent.getStringExtra(EXTRA_FILENAME)

            outputFile = ScreenRecordManager.createOutputFile(this, filename)
            recorder = createRecorder(outputFile!!, size.first, size.second, fps, bitRate, maxSeconds)

            val density = resources.displayMetrics.densityDpi
            virtualDisplay = projection?.createVirtualDisplay(
                "APKClawScreenRecord",
                size.first,
                size.second,
                density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                recorder?.surface,
                null,
                handler
            )
            recorder?.start()
            ScreenRecordManager.onRecordingStarted(outputFile!!, size.first, size.second)

            handler.postDelayed({ stopRecording("max_duration_reached") }, maxSeconds * 1000L)
            XLog.i(TAG, "Screen recording started: ${outputFile?.absolutePath}")
        } catch (e: Exception) {
            XLog.e(TAG, "Screen recording start failed: ${e.message}")
            cleanup(deleteBrokenFile = true)
            ScreenRecordManager.onRecordingError("Screen recording start failed: ${e.message}")
            stopSelf()
        }
    }

    private fun stopRecording(reason: String) {
        if (stopPosted) return
        stopPosted = true
        val file = outputFile
        try {
            recorder?.stop()
            XLog.i(TAG, "Screen recording stopped ($reason): ${file?.absolutePath}")
            ScreenRecordManager.onRecordingStopped(file)
        } catch (e: Exception) {
            XLog.e(TAG, "Screen recording stop failed: ${e.message}")
            ScreenRecordManager.onRecordingError("Screen recording stop failed: ${e.message}")
            try {
                file?.delete()
            } catch (_: Exception) {
            }
        } finally {
            cleanup(deleteBrokenFile = false)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun cleanup(deleteBrokenFile: Boolean) {
        handler.removeCallbacksAndMessages(null)
        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }
        try {
            recorder?.reset()
            recorder?.release()
        } catch (_: Exception) {
        }
        try {
            projection?.unregisterCallback(projectionCallback)
            projection?.stop()
        } catch (_: Exception) {
        }
        if (deleteBrokenFile) {
            try {
                outputFile?.delete()
            } catch (_: Exception) {
            }
        }
        virtualDisplay = null
        recorder = null
        projection = null
        outputFile = null
        stopPosted = false
    }

    private fun createRecorder(
        file: File,
        width: Int,
        height: Int,
        fps: Int,
        bitRate: Int,
        maxSeconds: Int
    ): MediaRecorder {
        val mediaRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(this)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
        mediaRecorder.setVideoSource(MediaRecorder.VideoSource.SURFACE)
        mediaRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        mediaRecorder.setOutputFile(file.absolutePath)
        mediaRecorder.setVideoEncoder(MediaRecorder.VideoEncoder.H264)
        mediaRecorder.setVideoSize(width, height)
        mediaRecorder.setVideoFrameRate(fps)
        mediaRecorder.setVideoEncodingBitRate(bitRate)
        mediaRecorder.setMaxDuration(maxSeconds * 1000)
        mediaRecorder.setOnInfoListener { _, what, _ ->
            if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) {
                stopRecording("max_duration_reached")
            }
        }
        mediaRecorder.prepare()
        return mediaRecorder
    }

    private fun resolveVideoSize(requestWidth: Int, requestHeight: Int): Pair<Int, Int> {
        val bounds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            getSystemService(WindowManager::class.java).currentWindowMetrics.bounds
        } else {
            @Suppress("DEPRECATION")
            android.graphics.Rect().also {
                getSystemService(WindowManager::class.java).defaultDisplay.getRectSize(it)
            }
        }
        var width = if (requestWidth > 0) requestWidth else bounds.width()
        var height = if (requestHeight > 0) requestHeight else bounds.height()
        if (width <= 0 || height <= 0) {
            width = resources.displayMetrics.widthPixels
            height = resources.displayMetrics.heightPixels
        }

        val maxEdge = maxOf(width, height)
        if (maxEdge > 1920) {
            val scale = 1920f / maxEdge.toFloat()
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
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "APKClaw Screen Recording",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Records the phone screen for AI demonstration material collection"
                setShowBadge(false)
            }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
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
            Intent(this, ScreenRecordService::class.java).apply { action = ACTION_STOP },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_lumi_notification)
            .setContentTitle("APKClaw recording")
            .setContentText("Screen recording is active")
            .setContentIntent(contentIntent)
            .addAction(R.drawable.ic_lumi_notification, "Stop", stopIntent)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }
}
