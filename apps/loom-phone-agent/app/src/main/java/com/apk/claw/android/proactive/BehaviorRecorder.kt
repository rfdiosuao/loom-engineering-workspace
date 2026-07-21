package com.apk.claw.android.proactive

import com.apk.claw.android.utils.KVUtils
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/**
 * 用户行为记录器
 *
 * 记录用户的行为模式，为AI主动建议提供数据基础
 */
object BehaviorRecorder {

    private const val TAG = "BehaviorRecorder"
    private val GSON = Gson()
    private val TIME_FORMAT = SimpleDateFormat("HH:mm", Locale.getDefault())
    private val DATE_FORMAT = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())

    // ==================== 数据结构 ====================

    /**
     * 行为记录
     */
    data class BehaviorEvent(
        val type: BehaviorType,           // 行为类型
        val content: String,              // 行为内容
        val timestamp: Long,              // 时间戳
        val hourOfDay: Int,               // 小时 (0-23)
        val dayOfWeek: Int,               // 星期 (1-7)
        val success: Boolean = true       // 是否成功
    )

    /**
     * 行为类型
     */
    enum class BehaviorType {
        APP_OPENED,          // 打开App
        TASK_EXECUTED,       // 执行任务
        SCHEDULE_CREATED,    // 创建定时任务
        MESSAGE_SENT,        // 发送消息
        SCREEN_ACTION        // 屏幕操作
    }

    /**
     * 行为模式（分析后的结果）
     */
    data class BehaviorPattern(
        val type: PatternType,
        val content: String,
        val hourOfDay: Int?,
        val dayOfWeek: Int?,           // null表示每天
        val frequency: Int,            // 出现次数
        val lastOccurrence: Long,
        val confidence: Float          // 置信度 0-1
    )

    /**
     * 模式类型
     */
    enum class PatternType {
        DAILY_APP_USAGE,      // 每天某时打开某App
        WEEKLY_APP_USAGE,     // 每周某天某时打开某App
        FREQUENT_TASK,        // 频繁执行的特定任务
        TIME_BASED_ACTION     // 基于时间的操作模式
    }

    // ==================== 行为记录 ====================

    /**
     * 记录行为
     */
    fun recordBehavior(
        type: BehaviorType,
        content: String,
        success: Boolean = true
    ) {
        val calendar = Calendar.getInstance()
        val event = BehaviorEvent(
            type = type,
            content = content,
            timestamp = System.currentTimeMillis(),
            hourOfDay = calendar.get(Calendar.HOUR_OF_DAY),
            dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK),
            success = success
        )

        val events = getRecentEvents().toMutableList()
        events.add(0, event)

        // 保留最近500条记录（约1-2个月的行为数据）
        while (events.size > 500) {
            events.removeAt(events.size - 1)
        }

        saveEvents(events)
    }

    /**
     * 记录打开App
     */
    fun recordAppOpened(appName: String) {
        recordBehavior(BehaviorType.APP_OPENED, appName)
    }

    /**
     * 记录执行任务
     */
    fun recordTaskExecuted(taskDescription: String, success: Boolean = true) {
        recordBehavior(BehaviorType.TASK_EXECUTED, taskDescription, success)
    }

    /**
     * 记录创建定时任务
     */
    fun recordScheduleCreated(scheduleDescription: String) {
        recordBehavior(BehaviorType.SCHEDULE_CREATED, scheduleDescription)
    }

    // ==================== 数据存取 ====================

    private fun getRecentEvents(): List<BehaviorEvent> {
        val json = KVUtils.getBehaviorEvents()
        return if (json.isNotEmpty()) {
            try { GSON.fromJson(json, object : TypeToken<List<BehaviorEvent>>() {}.type) }
            catch (_: Exception) { emptyList() }
        } else {
            emptyList()
        }
    }

    private fun saveEvents(events: List<BehaviorEvent>) {
        KVUtils.setBehaviorEvents(GSON.toJson(events))
    }

    // ==================== 模式分析 ====================

    /**
     * 分析行为模式
     * 返回检测到的模式列表
     */
    fun analyzePatterns(): List<BehaviorPattern> {
        val events = getRecentEvents()
        if (events.size < 5) return emptyList() // 数据太少不分析

        val patterns = mutableListOf<BehaviorPattern>()

        // 1. 分析每日App使用模式
        patterns.addAll(analyzeDailyAppUsage(events))

        // 2. 分析频繁任务
        patterns.addAll(analyzeFrequentTasks(events))

        // 3. 分析时间模式
        patterns.addAll(analyzeTimePatterns(events))

        return patterns.sortedByDescending { it.confidence }
    }

    /**
     * 分析每日App使用模式
     * 检测：连续多天在同一时间段打开同一App
     */
    private fun analyzeDailyAppUsage(events: List<BehaviorEvent>): List<BehaviorPattern> {
        val appEvents = events.filter { it.type == BehaviorType.APP_OPENED }
        if (appEvents.size < 3) return emptyList()

        val patterns = mutableListOf<BehaviorPattern>()

        // 按App分组
        val appGroups = appEvents.groupBy { it.content }

        for ((appName, appEventList) in appGroups) {
            if (appEventList.size < 3) continue

            // 按小时分组（允许±1小时误差）
            val hourGroups = mutableMapOf<Int, MutableList<BehaviorEvent>>()

            for (event in appEventList) {
                val hourKey = event.hourOfDay
                var matched = false

                // 查找相近的小时组
                for ((existingHour, existingList) in hourGroups) {
                    if (kotlin.math.abs(existingHour - hourKey) <= 1) {
                        existingList.add(event)
                        matched = true
                        break
                    }
                }

                if (!matched) {
                    hourGroups[hourKey] = mutableListOf(event)
                }
            }

            // 检测模式
            for ((hour, hourEventList) in hourGroups) {
                if (hourEventList.size >= 3) {
                    // 检查是否跨多天
                    val uniqueDays = hourEventList.map {
                        DATE_FORMAT.format(it.timestamp)
                    }.toSet().size

                    if (uniqueDays >= 3) {
                        val confidence = (hourEventList.size.toFloat() / appEventList.size).coerceAtMost(0.9f)
                        patterns.add(BehaviorPattern(
                            type = PatternType.DAILY_APP_USAGE,
                            content = appName,
                            hourOfDay = hour,
                            dayOfWeek = null,
                            frequency = hourEventList.size,
                            lastOccurrence = hourEventList.first().timestamp,
                            confidence = confidence
                        ))
                    }
                }
            }
        }

        return patterns
    }

    /**
     * 分析频繁任务
     * 检测：用户多次执行相似的任务描述
     */
    private fun analyzeFrequentTasks(events: List<BehaviorEvent>): List<BehaviorPattern> {
        val taskEvents = events.filter { it.type == BehaviorType.TASK_EXECUTED && it.success }
        if (taskEvents.size < 2) return emptyList()

        val patterns = mutableListOf<BehaviorPattern>()

        // 简单的关键词提取匹配
        val taskGroups = mutableMapOf<String, MutableList<BehaviorEvent>>()

        for (event in taskEvents) {
            val keywords = extractKeywords(event.content)
            val key = keywords.take(3).sorted().joinToString("_")

            if (!taskGroups.containsKey(key)) {
                taskGroups[key] = mutableListOf()
            }
            taskGroups[key]?.add(event)
        }

        for ((_, taskEventList) in taskGroups) {
            if (taskEventList.size >= 3) {
                // 取最常见的任务描述
                val mostCommon = taskEventList.groupBy { it.content }
                    .maxByOrNull { it.value.size }?.key ?: continue

                patterns.add(BehaviorPattern(
                    type = PatternType.FREQUENT_TASK,
                    content = mostCommon,
                    hourOfDay = null,
                    dayOfWeek = null,
                    frequency = taskEventList.size,
                    lastOccurrence = taskEventList.first().timestamp,
                    confidence = (taskEventList.size.toFloat() / taskEvents.size).coerceAtMost(0.8f)
                ))
            }
        }

        return patterns
    }

    /**
     * 分析时间模式
     * 检测：特定时间段的操作习惯
     */
    private fun analyzeTimePatterns(events: List<BehaviorEvent>): List<BehaviorPattern> {
        val patterns = mutableListOf<BehaviorPattern>()

        // 分析早间行为（6-9点）
        val morningEvents = events.filter { it.hourOfDay in 6..9 }
        if (morningEvents.size >= 5) {
            val morningApps = morningEvents
                .filter { it.type == BehaviorType.APP_OPENED }
                .groupBy { it.content }
                .filter { it.value.size >= 3 }

            if (morningApps.isNotEmpty()) {
                patterns.add(BehaviorPattern(
                    type = PatternType.TIME_BASED_ACTION,
                    content = "早间习惯: ${morningApps.keys.take(3).joinToString(", ")}",
                    hourOfDay = 7,
                    dayOfWeek = null,
                    frequency = morningEvents.size,
                    lastOccurrence = morningEvents.first().timestamp,
                    confidence = 0.6f
                ))
            }
        }

        // 分析晚间行为（21-23点）
        val eveningEvents = events.filter { it.hourOfDay in 21..23 }
        if (eveningEvents.size >= 5) {
            val eveningApps = eveningEvents
                .filter { it.type == BehaviorType.APP_OPENED }
                .groupBy { it.content }
                .filter { it.value.size >= 3 }

            if (eveningApps.isNotEmpty()) {
                patterns.add(BehaviorPattern(
                    type = PatternType.TIME_BASED_ACTION,
                    content = "晚间习惯: ${eveningApps.keys.take(3).joinToString(", ")}",
                    hourOfDay = 22,
                    dayOfWeek = null,
                    frequency = eveningEvents.size,
                    lastOccurrence = eveningEvents.first().timestamp,
                    confidence = 0.6f
                ))
            }
        }

        return patterns
    }

    /**
     * 提取关键词
     */
    private fun extractKeywords(text: String): List<String> {
        // 简单的关键词提取：分词后过滤停用词
        val stopWords = setOf("的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "打开", "帮我", "帮我点")

        return text.split(Regex("[\\s,，。！？、]+"))
            .filter { it.length >= 2 && it !in stopWords }
            .take(5)
    }

    // ==================== 统计信息 ====================

    /**
     * 获取行为统计
     */
    fun getStatistics(): Map<String, Any> {
        val events = getRecentEvents()

        val appUsage = events
            .filter { it.type == BehaviorType.APP_OPENED }
            .groupBy { it.content }
            .mapValues { it.value.size }
            .toList()
            .sortedByDescending { it.second }
            .take(10)
            .toMap()

        val hourlyDistribution = events
            .groupBy { it.hourOfDay }
            .mapValues { it.value.size }

        val taskCount = events.count { it.type == BehaviorType.TASK_EXECUTED }
        val successRate = events
            .filter { it.type == BehaviorType.TASK_EXECUTED }
            .let { taskEvents ->
                if (taskEvents.isEmpty()) 0f
                else taskEvents.count { it.success }.toFloat() / taskEvents.size
            }

        return mapOf(
            "totalEvents" to events.size,
            "appUsage" to appUsage,
            "hourlyDistribution" to hourlyDistribution,
            "taskCount" to taskCount,
            "successRate" to successRate
        )
    }

    /**
     * 清空所有行为记录
     */
    fun clearAll() {
        saveEvents(emptyList())
    }
}