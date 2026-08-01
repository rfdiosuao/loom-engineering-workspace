package com.apk.claw.android.server.stream

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import com.apk.claw.android.utils.XLog

class PhoneStreamPermissionActivity : Activity() {
    companion object {
        private const val TAG = "PhoneStreamPermission"
        private const val REQUEST_CAPTURE = 8421
    }

    private var sessionId: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sessionId = intent.getStringExtra(PhoneStreamService.EXTRA_SESSION_ID).orEmpty()
        if (sessionId.isBlank() || !PhoneStreamRuntime.sessions.isCurrent(sessionId)) {
            finish()
            return
        }
        try {
            startActivityForResult(PhoneStreamManager.buildCaptureIntent(this), REQUEST_CAPTURE)
        } catch (error: Exception) {
            XLog.e(TAG, "Failed to request stream capture permission: ${error.message}")
            PhoneStreamRuntime.sessions.markError(sessionId, "无法请求屏幕共享授权")
            finish()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CAPTURE) {
            PhoneStreamManager.onPermissionResult(applicationContext, sessionId, resultCode, data)
        }
        finish()
    }
}
