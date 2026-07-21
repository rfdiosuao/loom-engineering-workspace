package com.apk.claw.android.tool.impl

import com.apk.claw.android.proactive.BehaviorRecorder
import com.apk.claw.android.proactive.ProactiveSuggestionManager
import com.apk.claw.android.tool.BaseTool
import com.apk.claw.android.tool.ToolParameter
import com.apk.claw.android.tool.ToolResult

/**
 * 查看AI建议工具
 */
class ViewSuggestionsTool : BaseTool() {

    override fun getName(): String = "view_suggestions"

    override fun getParameters(): List<ToolParameter> = emptyList()

    override fun execute(params: Map<String, Any>): ToolResult {
        val suggestions = ProactiveSuggestionManager.getPendingSuggestions()

        return if (suggestions.isEmpty()) {
            ToolResult.success("暂无AI建议")
        } else {
            val sb = StringBuilder()
            sb.append("【AI建议列表】\n\n")
            suggestions.forEachIndexed { index, suggestion ->
                sb.append("${index + 1}. ${suggestion.title}\n")
                sb.append("   ${suggestion.description}\n\n")
            }
            ToolResult.success(sb.toString())
        }
    }

    override fun getDescriptionEN(): String = "View pending AI suggestions based on your behavior patterns."

    override fun getDescriptionCN(): String = "查看基于你行为模式的AI建议"
}

/**
 * 接受建议工具
 */
class AcceptSuggestionTool : BaseTool() {

    override fun getName(): String = "accept_suggestion"

    override fun getParameters(): List<ToolParameter> = listOf(
        ToolParameter("index", "integer", "建议序号（从 view_suggestions 获取）", true)
    )

    override fun execute(params: Map<String, Any>): ToolResult {
        val index = requireInt(params, "index")

        val suggestions = ProactiveSuggestionManager.getPendingSuggestions()
        if (index < 1 || index > suggestions.size) {
            return ToolResult.error("序号无效，当前有 ${suggestions.size} 条建议")
        }

        val suggestion = suggestions[index - 1]
        val success = ProactiveSuggestionManager.acceptSuggestion(suggestion.id)

        return if (success) {
            ToolResult.success("已接受建议: ${suggestion.title}\n相关操作已自动执行")
        } else {
            ToolResult.error("接受建议失败")
        }
    }

    override fun getDescriptionEN(): String = "Accept an AI suggestion by its index number."

    override fun getDescriptionCN(): String = "接受AI建议，自动执行相关操作"
}

/**
 * 忽略建议工具
 */
class DismissSuggestionTool : BaseTool() {

    override fun getName(): String = "dismiss_suggestion"

    override fun getParameters(): List<ToolParameter> = listOf(
        ToolParameter("index", "integer", "建议序号（从 view_suggestions 获取）", true)
    )

    override fun execute(params: Map<String, Any>): ToolResult {
        val index = requireInt(params, "index")

        val suggestions = ProactiveSuggestionManager.getPendingSuggestions()
        if (index < 1 || index > suggestions.size) {
            return ToolResult.error("序号无效，当前有 ${suggestions.size} 条建议")
        }

        val suggestion = suggestions[index - 1]
        val success = ProactiveSuggestionManager.dismissSuggestion(suggestion.id)

        return if (success) {
            ToolResult.success("已忽略建议: ${suggestion.title}")
        } else {
            ToolResult.error("忽略建议失败")
        }
    }

    override fun getDescriptionEN(): String = "Dismiss an AI suggestion by its index number."

    override fun getDescriptionCN(): String = "忽略AI建议"
}

/**
 * 查看行为统计工具
 */
class ViewBehaviorStatsTool : BaseTool() {

    override fun getName(): String = "view_behavior_stats"

    override fun getParameters(): List<ToolParameter> = emptyList()

    override fun execute(params: Map<String, Any>): ToolResult {
        val stats = BehaviorRecorder.getStatistics()

        val sb = StringBuilder()
        sb.append("【行为统计】\n\n")

        sb.append("总记录数: ${stats["totalEvents"]}\n")
        sb.append("任务执行次数: ${stats["taskCount"]}\n")

        val successRate = stats["successRate"] as? Float ?: 0f
        sb.append("任务成功率: ${"%.1f".format(successRate * 100)}%\n\n")

        @Suppress("UNCHECKED_CAST")
        val appUsage = stats["appUsage"] as? Map<String, Int> ?: emptyMap()
        if (appUsage.isNotEmpty()) {
            sb.append("常用App:\n")
            appUsage.entries.take(5).forEach { (app, count) ->
                sb.append("  - $app: ${count}次\n")
            }
        }

        return ToolResult.success(sb.toString())
    }

    override fun getDescriptionEN(): String = "View your behavior statistics and usage patterns."

    override fun getDescriptionCN(): String = "查看你的行为统计和使用模式"
}