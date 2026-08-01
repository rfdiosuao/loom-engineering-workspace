package com.apk.claw.android.server.stream

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import com.apk.claw.android.media.ScreenRecordManager
import com.apk.claw.android.utils.XLog

object PhoneStreamManager {
    private const val TAG = "PhoneStreamManager"

    @Volatile
    private var permissionSessionId: String = ""

    fun requestStart(
        context: Context,
        clientSessionId: String,
        launcherId: String,
        options: PhoneStreamOptions
    ): PhoneStreamGrant {
        val grant = PhoneStreamRuntime.sessions.createOrReuse(clientSessionId, launcherId, options)
        if (grant.state == "active") return grant
        if (grant.state == "error") return grant
        val recording = runCatching {
            ScreenRecordManager.status(context).get("recording")?.asBoolean == true
        }.getOrDefault(false)
        if (recording) {
            PhoneStreamRuntime.sessions.markError(grant.sessionId, "录屏正在运行，停止录屏后可启用低延迟画面")
            return PhoneStreamRuntime.sessions.currentGrant(grant.sessionId) ?: grant
        }
        synchronized(this) {
            if (permissionSessionId != grant.sessionId) {
                permissionSessionId = grant.sessionId
                PhoneStreamRuntime.sessions.markPermissionRequired(grant.sessionId)
                context.startActivity(Intent(context, PhoneStreamPermissionActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    putExtra(PhoneStreamService.EXTRA_SESSION_ID, grant.sessionId)
                })
            }
        }
        return PhoneStreamRuntime.sessions.currentGrant(grant.sessionId) ?: grant
    }

    fun buildCaptureIntent(activity: Activity): Intent =
        activity.getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent()

    fun onPermissionResult(context: Context, sessionId: String, resultCode: Int, data: Intent?) {
        synchronized(this) {
            if (permissionSessionId == sessionId) permissionSessionId = ""
        }
        val grant = PhoneStreamRuntime.sessions.currentGrant(sessionId) ?: return
        if (resultCode != Activity.RESULT_OK || data == null) {
            PhoneStreamRuntime.sessions.markError(sessionId, "屏幕共享授权被拒绝，矩阵继续使用截图")
            return
        }
        val intent = Intent(context, PhoneStreamService::class.java).apply {
            action = PhoneStreamService.ACTION_START
            putExtra(PhoneStreamService.EXTRA_SESSION_ID, sessionId)
            putExtra(PhoneStreamService.EXTRA_RESULT_CODE, resultCode)
            putExtra(PhoneStreamService.EXTRA_RESULT_DATA, data)
            putExtra(PhoneStreamService.EXTRA_FPS, grant.options.fps)
            putExtra(PhoneStreamService.EXTRA_MAX_LONG_SIDE, grant.options.maxLongSide)
            putExtra(PhoneStreamService.EXTRA_BIT_RATE, grant.options.bitRate)
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent)
            else context.startService(intent)
        } catch (error: Exception) {
            XLog.e(TAG, "Unable to start phone stream service: ${error.message}")
            PhoneStreamRuntime.sessions.markError(sessionId, "无法启动屏幕共享服务")
        }
    }

    fun stop(context: Context, sessionId: String, streamToken: String, launcherId: String): Boolean {
        val stopped = PhoneStreamRuntime.sessions.stop(sessionId, streamToken, launcherId)
        if (stopped) {
            context.startService(Intent(context, PhoneStreamService::class.java).apply {
                action = PhoneStreamService.ACTION_STOP
                putExtra(PhoneStreamService.EXTRA_SESSION_ID, sessionId)
            })
        }
        return stopped
    }
}
