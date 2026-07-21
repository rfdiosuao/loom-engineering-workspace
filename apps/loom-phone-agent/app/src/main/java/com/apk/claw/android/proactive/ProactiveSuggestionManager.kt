package com.apk.claw.android.proactive

import com.apk.claw.android.scheduler.TaskScheduler
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * 主动建议管理器
 *
 * 基于用户行为模式，主动提出优化建议
 */
object ProactiveSuggestionManager {

    private const val TAG = "ProactiveSuggestion"
    private val GSON = Gson()

    // ==================== 数据结构 ====================

    /**
     * 建议类型
     */
    enum class SuggestionType {
        SCHEDULE_TASK,         // 建议创建定时任务
        SHORTCUT,              // 建议创建快捷方式
        BEHAVIOR_INSIGHT,      // 行为洞察
        EFFICIENCY_TIP         // 效率提示
    }

    /**
     * 建议状态
     */
    enum class SuggestionStatus {
        PENDING,               // 待处理
        ACCEPTED,              // 已接受
        DISMISSED,             // 已忽略
        EXPIRED                // 已过期
    }

    /**
     * 建议
     */
    data class Suggestion(
        val id: String,
        val type: SuggestionType,
        val title: String,
        val description: String,
        val actionData: Map<String, Any>,    // 执行动作所需的数据
        val createdAt: Long,
        val expiresAt: Long,
        var status: SuggestionStatus = SuggestionStatus.PENDING,
        val pattern: BehaviorRecorder.BehaviorPattern? = null
    )

    // ==================== 建议生成 ====================

    /**
     * 生成建议
     * 基于行为模式分析，返回可执行的建议列表
     */
    fun generateSuggestions(): List<Suggestion> {
        val patterns = BehaviorRecorder.analyzePatterns()
        val suggestions = mutableListOf<Suggestion>()
        val now = System.currentTimeMillis()

        for (pattern in patterns) {
            when (pattern.type) {
                BehaviorRecorder.PatternType.DAILY_APP_USAGE -> {
                    // 检查是否已有该时间的定时任务
                    if (!hasConflictingSchedule(pattern.content, pattern.hourOfDay!!)) {
                        suggestions.add(createScheduleSuggestion(pattern))
                    }
                }

                BehaviorRecorder.PatternType.FREQUENT_TASK -> {
                    // 建议创建快捷方式或定时任务
                    if (pattern.frequency >= 5 && pattern.confidence >= 0.4f) {
                        suggestions.add(createFrequentTaskSuggestion(pattern))
                    }
                }

                BehaviorRecorder.PatternType.TIME_BASED_ACTION -> {
                    suggestions.add(createInsightSuggestion(pattern))
                }

                else -> {}
            }
        }

        // 过滤已存在的建议
        val existingSuggestions = getPendingSuggestions()
        return suggestions.filter { newSuggestion ->
            existingSuggestions.none { existing ->
                existing.title == newSuggestion.title && existing.status == SuggestionStatus.PENDING
            }
        }.take(3) // 最多返回3条建议
    }

    /**
     * 创建定时任务建议
     */
    private fun createScheduleSuggestion(pattern: BehaviorRecorder.BehaviorPattern): Suggestion {
        val hour = pattern.hourOfDay!!
        val timeStr = String.format("%02d:00", hour)
        val appName = pattern.content

        return Suggestion(
            id = "schedule_${System.currentTimeMillis()}_${appName.hashCode()}",
            type = SuggestionType.SCHEDULE_TASK,
            title = "设置定时打开「$appName」",
            description = "我注意到您经常在 $timeStr 左右打开「$appName」，要不要设置一个定时任务自动执行？",
            actionData = mapOf(
                "hour" to hour,
                "minute" to 0,
                "appName" to appName,
                "prompt" to "打开$appName"
            ),
            createdAt = System.currentTimeMillis(),
            expiresAt = System.currentTimeMillis() + TimeUnit.DAYS.toMillis(7),
            pattern = pattern
        )
    }

    /**
     * 创建频繁任务建议
     */
    private fun createFrequentTaskSuggestion(pattern: BehaviorRecorder.BehaviorPattern): Suggestion {
        val taskDesc = pattern.content

        return Suggestion(
            id = "frequent_${System.currentTimeMillis()}_${taskDesc.hashCode()}",
            type = SuggestionType.SCHEDULE_TASK,
            title = "自动化常用任务",
            description = "您已经执行「$taskDesc」${pattern.frequency}次了，要创建定时任务自动执行吗？",
            actionData = mapOf(
                "prompt" to taskDesc
            ),
            createdAt = System.currentTimeMillis(),
            expiresAt = System.currentTimeMillis() + TimeUnit.DAYS.toMillis(3),
            pattern = pattern
        )
    }

    /**
     * 创建洞察建议
     */
    private fun createInsightSuggestion(pattern: BehaviorRecorder.BehaviorPattern): Suggestion {
        return Suggestion(
            id = "insight_${System.currentTimeMillis()}",
            type = SuggestionType.BEHAVIOR_INSIGHT,
            title = "行为洞察",
            description = "发现您的使用模式：${pattern.content}",
            actionData = emptyMap(),
            createdAt = System.currentTimeMillis(),
            expiresAt = System.currentTimeMillis() + TimeUnit.DAYS.toMillis(1),
            pattern = pattern
        )
    }

    // ==================== 建议管理 ====================

    /**
     * 获取待处理的建议
     */
    fun getPendingSuggestions(): List<Suggestion> {
        val json = KVUtils.getProactiveSuggestions()
        val suggestions: List<Suggestion> = if (json.isNotEmpty()) {
            try { GSON.fromJson(json, object : TypeToken<List<Suggestion>>() {}.type) }
            catch (_: Exception) { emptyList() }
        } else {
            emptyList()
        }

        // 过滤过期的建议
        val now = System.currentTimeMillis()
        return suggestions.filter { it.expiresAt > now && it.status == SuggestionStatus.PENDING }
    }

    /**
     * 保存建议
     */
    private fun saveSuggestions(suggestions: List<Suggestion>) {
        KVUtils.setProactiveSuggestions(GSON.toJson(suggestions))
    }

    /**
     * 添加建议
     */
    fun addSuggestion(suggestion: Suggestion) {
        val suggestions = getPendingSuggestions().toMutableList()
        suggestions.add(0, suggestion)
        saveSuggestions(suggestions)
    }

    /**
     * 接受建议
     * 执行建议对应的动作
     */
    fun acceptSuggestion(suggestionId: String): Boolean {
        val suggestions = getPendingSuggestions().toMutableList()
        val index = suggestions.indexOfFirst { it.id == suggestionId }

        if (index < 0) return false

        val suggestion = suggestions[index]
        suggestion.status = SuggestionStatus.ACCEPTED
        saveSuggestions(suggestions)

        // 执行建议动作
        return when (suggestion.type) {
            SuggestionType.SCHEDULE_TASK -> {
                executeScheduleSuggestion(suggestion)
            }
            else -> {
                XLog.i(TAG, "建议已接受: ${suggestion.title}")
                true
            }
        }
    }

    /**
     * 忽略建议
     */
    fun dismissSuggestion(suggestionId: String): Boolean {
        val suggestions = getPendingSuggestions().toMutableList()
        val index = suggestions.indexOfFirst { it.id == suggestionId }

        if (index < 0) return false

        suggestions[index].status = SuggestionStatus.DISMISSED
        saveSuggestions(suggestions)
        XLog.i(TAG, "建议已忽略: ${suggestions[index].title}")
        return true
    }

    /**
     * 执行定时任务建议
     */
    private fun executeScheduleSuggestion(suggestion: Suggestion): Boolean {
        val actionData = suggestion.actionData

        return try {
            val hour = (actionData["hour"] as? Number)?.toInt() ?: 9
            val minute = (actionData["minute"] as? Number)?.toInt() ?: 0
            val prompt = actionData["prompt"] as? String ?: ""

            if (prompt.isNotEmpty()) {
                TaskScheduler.addTask(
                    prompt = prompt,
                    hour = hour,
                    minute = minute,
                    repeat = true
                )
                XLog.i(TAG, "已创建定时任务: $prompt at ${String.format("%02d:%02d", hour, minute)}")
                true
            } else {
                false
            }
        } catch (e: Exception) {
            XLog.e(TAG, "执行建议失败", e)
            false
        }
    }

    // ==================== 工具方法 ====================

    /**
     * 检查是否已有冲突的定时任务
     */
    private fun hasConflictingSchedule(content: String, hour: Int): Boolean {
        val tasks = TaskScheduler.getAllTasks()
        return tasks.any { task ->
            task.hour == hour && task.prompt.contains(content, ignoreCase = true)
        }
    }

    /**
     * 格式化建议为可读文本
     */
    fun formatSuggestions(): String {
        val suggestions = getPendingSuggestions()
        if (suggestions.isEmpty()) {
            return "暂无待处理的建议"
        }

        val sb = StringBuilder()
        sb.append("【AI建议】\n\n")
        suggestions.forEachIndexed { index, suggestion ->
            sb.append("${index + 1}. ${suggestion.title}\n")
            sb.append("   ${suggestion.description}\n\n")
        }
        sb.append("回复序号接受建议，或回复\"忽略\"跳过")
        return sb.toString()
    }

    /**
     * 清空所有建议
     */
    fun clearAll() {
        saveSuggestions(emptyList())
    }
}