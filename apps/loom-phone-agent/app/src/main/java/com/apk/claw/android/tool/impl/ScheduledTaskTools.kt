package com.apk.claw.android.tool.impl

import com.apk.claw.android.scheduler.TaskScheduler
import com.apk.claw.android.tool.BaseTool
import com.apk.claw.android.tool.ToolParameter
import com.apk.claw.android.tool.ToolResult

/**
 * 创建定时任务工具
 */
class ScheduleTaskTool : BaseTool() {

    override fun getName(): String = "schedule_task"

    override fun getParameters(): List<ToolParameter> = listOf(
        ToolParameter("time", "string", "执行时间，格式 HH:mm，如 07:00、19:30", true),
        ToolParameter("prompt", "string", "要执行的任务描述，如 '播放音乐'、'打开新闻App'", true),
        ToolParameter("repeat", "boolean", "是否每天重复执行，默认 false（仅执行一次）", false)
    )

    override fun execute(params: Map<String, Any>): ToolResult {
        val timeStr = requireString(params, "time")
        val prompt = requireString(params, "prompt")
        val repeat = optionalBoolean(params, "repeat", false)

        // 解析时间
        val (hour, minute) = TaskScheduler.parseTime(timeStr)
            ?: return ToolResult.error("时间格式错误，请使用 HH:mm 格式，如 07:00")

        // 创建任务
        val task = TaskScheduler.addTask(
            prompt = prompt,
            hour = hour,
            minute = minute,
            repeat = repeat
        )

        val repeatStr = if (repeat) "每天" else "一次"
        val nextTime = task.getNextExecutionTime()
        val sdf = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.getDefault())
        val nextTimeStr = sdf.format(java.util.Date(nextTime))

        return ToolResult.success(
            "已创建定时任务: $repeatStr ${task.getTimeString()} 执行 \"$prompt\"\n" +
            "下次执行时间: $nextTimeStr"
        )
    }

    override fun getDescriptionEN(): String = "Schedule a task to run at a specific time. Time format: HH:mm (24-hour). Set repeat=true for daily tasks."

    override fun getDescriptionCN(): String = "创建定时任务。时间格式 HH:mm（24小时制）。repeat=true 表示每天重复执行。"
}

/**
 * 列出定时任务工具
 */
class ListScheduledTasksTool : BaseTool() {

    override fun getName(): String = "list_scheduled_tasks"

    override fun getParameters(): List<ToolParameter> = emptyList()

    override fun execute(params: Map<String, Any>): ToolResult {
        val taskList = TaskScheduler.formatTaskList()
        return ToolResult.success(taskList)
    }

    override fun getDescriptionEN(): String = "List all scheduled tasks."

    override fun getDescriptionCN(): String = "列出所有定时任务"
}

/**
 * 取消定时任务工具
 */
class CancelScheduledTaskTool : BaseTool() {

    override fun getName(): String = "cancel_scheduled_task"

    override fun getParameters(): List<ToolParameter> = listOf(
        ToolParameter("index", "integer", "任务序号（从 list_scheduled_tasks 获取），从1开始", true)
    )

    override fun execute(params: Map<String, Any>): ToolResult {
        val index = requireInt(params, "index")

        if (index < 1) {
            return ToolResult.error("任务序号必须大于0")
        }

        val tasks = TaskScheduler.getAllTasks()
        if (index > tasks.size) {
            return ToolResult.error("任务序号超出范围，当前共有 ${tasks.size} 个任务")
        }

        val task = tasks[index - 1]
        val success = TaskScheduler.deleteTask(task.id)

        return if (success) {
            ToolResult.success("已取消定时任务: ${task.getTimeString()} - ${task.prompt}")
        } else {
            ToolResult.error("取消任务失败")
        }
    }

    override fun getDescriptionEN(): String = "Cancel a scheduled task by its index number (get index from list_scheduled_tasks)."

    override fun getDescriptionCN(): String = "取消定时任务。需要先调用 list_scheduled_tasks 获取任务序号，index 从1开始。"
}