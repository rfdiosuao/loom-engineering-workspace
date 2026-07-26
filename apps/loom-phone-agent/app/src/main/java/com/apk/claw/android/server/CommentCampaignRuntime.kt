package com.apk.claw.android.server

import com.apk.claw.android.ClawApplication
import com.apk.claw.android.comment.AndroidCommentDeviceStepExecutor
import com.apk.claw.android.comment.ApkClawCommentDeviceDriver
import com.apk.claw.android.comment.CommentCampaignCoordinator
import com.apk.claw.android.comment.CommentCampaignStore
import com.apk.claw.android.comment.CommentSendLedger
import java.io.File

object CommentCampaignRuntime {
    @Volatile
    private var instance: CommentCampaignCoordinator? = null

    fun coordinator(): CommentCampaignCoordinator {
        instance?.let { return it }
        return synchronized(this) {
            instance ?: create().also { instance = it }
        }
    }

    private fun create(): CommentCampaignCoordinator {
        val root = File(ClawApplication.instance.filesDir, "comment_campaigns")
        val driver = ApkClawCommentDeviceDriver(
            AndroidCommentDeviceStepExecutor(ClawApplication.instance)
        )
        return CommentCampaignCoordinator(
            CommentCampaignStore(root),
            CommentSendLedger(root),
            driver
        )
    }
}
