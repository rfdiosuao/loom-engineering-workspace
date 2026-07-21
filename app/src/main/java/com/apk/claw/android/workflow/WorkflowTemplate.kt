package com.apk.claw.android.workflow

/**
 * 工作流模板
 * 记录一次成功执行的工具调用序列，可用于相似任务的快速执行
 */
data class WorkflowTemplate(
    val id: String,                          // 模板唯一ID
    val name: String,                        // 模板名称（用户可见）
    val description: String,                 // 模板描述
    val taskPattern: String,                 // 任务模式（用于匹配，如 "微信.*发消息"）
    val keywords: List<String>,              // 关键词列表（用于快速匹配）
    val appName: String?,                    // 目标应用名（可选）
    val steps: List<WorkflowStep>,           // 步骤序列
    val createdAt: Long,                     // 创建时间
    val lastUsedAt: Long,                    // 最后使用时间
    val successCount: Int,                   // 成功次数
    val failCount: Int                       // 失败次数
) {
    /**
     * 工作流步骤
     * 每个步骤代表一个工具调用
     */
    data class WorkflowStep(
        val toolName: String,                // 工具名
        val paramsTemplate: Map<String, Any>,// 参数模板（含占位符）
        val description: String,             // 步骤描述
        val waitFor: Int = 500,              // 执行后等待时间(ms)
        val isVerification: Boolean = false, // 是否为验证步骤
        val failureHandling: FailureHandling? = null // 失败处理策略
    )

    /**
     * 失败处理策略
     */
    data class FailureHandling(
        val maxRetries: Int = 3,             // 最大重试次数
        val retryDelay: Int = 1000,          // 重试延迟(ms)
        val fallbackSteps: List<WorkflowStep>? = null // 失败后备步骤
    )

    /**
     * 计算成功率
     */
    fun successRate(): Float {
        val total = successCount + failCount
        return if (total == 0) 0f else successCount.toFloat() / total
    }
}

/**
 * 模板执行结果
 */
data class TemplateExecutionResult(
    val success: Boolean,
    val templateId: String,
    val stepsExecuted: Int,
    val stepsTotal: Int,
    val errorMessage: String? = null,
    val executionTimeMs: Long = 0
)