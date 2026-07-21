package com.apk.claw.android.media

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import com.apk.claw.android.utils.XLog

class ScreenCapturePermissionActivity : Activity() {

    companion object {
        private const val TAG = "ScreenCapturePermission"
        private const val REQUEST_CAPTURE = 8417
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            startActivityForResult(ScreenRecordManager.buildCaptureIntent(this), REQUEST_CAPTURE)
        } catch (e: Exception) {
            XLog.e(TAG, "Failed to request screen capture permission: ${e.message}")
            ScreenRecordManager.onRecordingError("Failed to request screen capture permission: ${e.message}")
            finish()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CAPTURE) {
            ScreenRecordManager.onPermissionResult(applicationContext, resultCode, data)
            finish()
            return
        }
        finish()
    }
}
