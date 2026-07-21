package com.apk.claw.android.scheduler

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.apk.claw.android.utils.XLog

/**
 * 定时任务执行接收器
 *
 * 当闹钟触发时，此接收器被唤醒，执行定时任务
 */
class ScheduledTaskReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "ScheduledTaskReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TaskScheduler.ACTION_EXECUTE_SCHEDULED_TASK) {
            val taskId = intent.getStringExtra(TaskScheduler.EXTRA_TASK_ID)
            if (taskId != null) {
                XLog.i(TAG, "收到定时任务广播: $taskId")
                TaskScheduler.executeTask(taskId)
            } else {
                XLog.w(TAG, "收到定时任务广播，但缺少任务ID")
            }
        }
    }
}