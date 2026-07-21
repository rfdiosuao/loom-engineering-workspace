package com.apk.claw.android.scheduler

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.apk.claw.android.ClawApplication
import com.apk.claw.android.channel.Channel
import com.apk.claw.android.channel.ChannelManager
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.apk.claw.android.appViewModel
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.UUID

/**
 * 定时任务调度器
 *
 * 支持两种模式：
 * 1. 一次性任务 - 指定具体时间执行一次
 * 2. 重复任务 - 每天指定时间执行
 */
object TaskScheduler {

    private const val TAG = "TaskScheduler"
    private val GSON = Gson()
    private val TIME_FORMAT = SimpleDateFormat("HH:mm", Locale.getDefault())

    const val ACTION_EXECUTE_SCHEDULED_TASK = "com.apk.claw.android.SCHEDULED_TASK"
    const val EXTRA_TASK_ID = "task_id"

    // ==================== 数据结构 ====================

    /**
     * 定时任务
     */
    data class ScheduledTask(
        val id: String,                    // 唯一ID
        val prompt: String,                // 要执行的任务描述
        val hour: Int,                     // 小时 (0-23)
        val minute: Int,                   // 分钟 (0-59)
        val repeat: Boolean,               // 是否重复（每天）
        val channel: Channel?,             // 执行的渠道
        val targetUserId: String?,         // 目标用户ID
        val enabled: Boolean = true,       // 是否启用
        val createdAt: Long = System.currentTimeMillis()
    ) {
        fun getTimeString(): String = String.format("%02d:%02d", hour, minute)

        fun getNextExecutionTime(): Long {
            val calendar = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, hour)
                set(Calendar.MINUTE, minute)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }

            // 如果时间已过，设置到明天
            if (calendar.timeInMillis <= System.currentTimeMillis()) {
                calendar.add(Calendar.DAY_OF_MONTH, 1)
            }
            return calendar.timeInMillis
        }
    }

    // ==================== 任务管理 ====================

    /**
     * 获取所有定时任务
     */
    fun getAllTasks(): List<ScheduledTask> {
        val json = KVUtils.getScheduledTasks()
        return if (json.isNotEmpty()) {
            try { GSON.fromJson(json, object : TypeToken<List<ScheduledTask>>() {}.type) }
            catch (_: Exception) { emptyList() }
        } else {
            emptyList()
        }
    }

    /**
     * 保存所有任务
     */
    private fun saveTasks(tasks: List<ScheduledTask>) {
        KVUtils.setScheduledTasks(GSON.toJson(tasks))
    }

    /**
     * 添加定时任务
     */
    fun addTask(
        prompt: String,
        hour: Int,
        minute: Int,
        repeat: Boolean,
        channel: Channel? = null,
        targetUserId: String? = null
    ): ScheduledTask {
        val task = ScheduledTask(
            id = UUID.randomUUID().toString(),
            prompt = prompt,
            hour = hour,
            minute = minute,
            repeat = repeat,
            channel = channel,
            targetUserId = targetUserId
        )

        val tasks = getAllTasks().toMutableList()
        tasks.add(task)
        saveTasks(tasks)

        // 注册系统闹钟
        scheduleAlarm(task)

        XLog.i(TAG, "已添加定时任务: ${task.getTimeString()} - $prompt")
        return task
    }

    /**
     * 删除定时任务
     */
    fun deleteTask(taskId: String): Boolean {
        val tasks = getAllTasks().toMutableList()
        val task = tasks.find { it.id == taskId }

        if (task != null) {
            // 取消系统闹钟
            cancelAlarm(task)

            tasks.removeAll { it.id == taskId }
            saveTasks(tasks)
            XLog.i(TAG, "已删除定时任务: ${task.getTimeString()} - ${task.prompt}")
            return true
        }
        return false
    }

    /**
     * 启用/禁用任务
     */
    fun toggleTask(taskId: String, enabled: Boolean): Boolean {
        val tasks = getAllTasks().toMutableList()
        val index = tasks.indexOfFirst { it.id == taskId }

        if (index >= 0) {
            val task = tasks[index].copy(enabled = enabled)
            tasks[index] = task
            saveTasks(tasks)

            if (enabled) {
                scheduleAlarm(task)
            } else {
                cancelAlarm(task)
            }
            return true
        }
        return false
    }

    /**
     * 根据ID获取任务
     */
    fun getTaskById(taskId: String): ScheduledTask? {
        return getAllTasks().find { it.id == taskId }
    }

    // ==================== 闹钟调度 ====================

    /**
     * 注册系统闹钟
     */
    private fun scheduleAlarm(task: ScheduledTask) {
        if (!task.enabled) return

        val context = ClawApplication.instance
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

        val intent = Intent(context, ScheduledTaskReceiver::class.java).apply {
            action = ACTION_EXECUTE_SCHEDULED_TASK
            putExtra(EXTRA_TASK_ID, task.id)
        }

        val pendingIntent = PendingIntent.getBroadcast(
            context,
            task.id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val triggerTime = task.getNextExecutionTime()

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (alarmManager.canScheduleExactAlarms()) {
                    alarmManager.setExactAndAllowWhileIdle(
                        AlarmManager.RTC_WAKEUP,
                        triggerTime,
                        pendingIntent
                    )
                } else {
                    // 没有精确闹钟权限，使用非精确闹钟
                    alarmManager.setAndAllowWhileIdle(
                        AlarmManager.RTC_WAKEUP,
                        triggerTime,
                        pendingIntent
                    )
                }
            } else {
                alarmManager.setExactAndAllowWhileIdle(
                    AlarmManager.RTC_WAKEUP,
                    triggerTime,
                    pendingIntent
                )
            }

            val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(triggerTime)
            XLog.i(TAG, "已注册闹钟: $timeStr - ${task.prompt}")
        } catch (e: Exception) {
            XLog.e(TAG, "注册闹钟失败", e)
        }
    }

    /**
     * 取消系统闹钟
     */
    private fun cancelAlarm(task: ScheduledTask) {
        val context = ClawApplication.instance
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

        val intent = Intent(context, ScheduledTaskReceiver::class.java).apply {
            action = ACTION_EXECUTE_SCHEDULED_TASK
        }

        val pendingIntent = PendingIntent.getBroadcast(
            context,
            task.id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        alarmManager.cancel(pendingIntent)
        XLog.i(TAG, "已取消闹钟: ${task.getTimeString()} - ${task.prompt}")
    }

    /**
     * 重新调度所有任务（开机后调用）
     */
    fun rescheduleAllTasks() {
        val tasks = getAllTasks().filter { it.enabled }
        tasks.forEach { scheduleAlarm(it) }
        XLog.i(TAG, "已重新调度 ${tasks.size} 个定时任务")
    }

    // ==================== 任务执行 ====================

    /**
     * 执行定时任务（由 ScheduledTaskReceiver 调用）
     * 直接唤醒 Agent 执行任务
     */
    fun executeTask(taskId: String) {
        val task = getTaskById(taskId)
        if (task == null) {
            XLog.w(TAG, "任务不存在: $taskId")
            return
        }

        XLog.i(TAG, "⏰ 定时任务触发: ${task.prompt}")

        // 获取渠道信息
        val channel = task.channel
        val targetUserId = task.targetUserId

        // 恢复渠道上下文
        if (channel != null && targetUserId != null) {
            ChannelManager.restoreRoutingContext(channel, targetUserId)
        }

        // 发送通知消息
        if (channel != null && targetUserId != null) {
            ChannelManager.sendMessageToUser(channel, targetUserId, "⏰ 定时任务开始执行: ${task.prompt}")
        }

        // 直接唤醒 Agent 执行任务
        try {
            appViewModel.executeScheduledTask(task.prompt, channel, targetUserId)
            XLog.i(TAG, "Agent 已开始执行定时任务")
        } catch (e: Exception) {
            XLog.e(TAG, "Agent 执行失败", e)
            if (channel != null && targetUserId != null) {
                ChannelManager.sendMessageToUser(channel, targetUserId, "❌ 定时任务执行失败: ${e.message}")
            }
        }

        // 如果是重复任务，重新注册闹钟
        if (task.repeat) {
            scheduleAlarm(task)
        } else {
            // 一次性任务，执行后删除
            deleteTask(taskId)
        }
    }

    // ==================== 工具方法 ====================

    /**
     * 解析时间字符串 "HH:mm" 或 "H:mm"
     */
    fun parseTime(timeStr: String): Pair<Int, Int>? {
        return try {
            val parts = timeStr.split(":")
            if (parts.size == 2) {
                val hour = parts[0].toIntOrNull() ?: return null
                val minute = parts[1].toIntOrNull() ?: return null
                if (hour in 0..23 && minute in 0..59) {
                    Pair(hour, minute)
                } else null
            } else null
        } catch (_: Exception) { null }
    }

    /**
     * 格式化任务列表为字符串
     */
    fun formatTaskList(): String {
        val tasks = getAllTasks()
        if (tasks.isEmpty()) {
            return "暂无定时任务"
        }

        val sb = StringBuilder()
        sb.append("【定时任务列表】\n")
        tasks.forEachIndexed { index, task ->
            val status = if (task.enabled) "✓" else "✗"
            val repeatStr = if (task.repeat) "每天" else "一次"
            sb.append("${index + 1}. [$status] ${task.getTimeString()} ($repeatStr) - ${task.prompt}\n")
        }
        return sb.toString()
    }
}