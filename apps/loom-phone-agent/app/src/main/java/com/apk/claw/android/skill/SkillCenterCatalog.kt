package com.apk.claw.android.skill

import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.WorkflowTemplate

enum class SkillKind { LINUX, LEARNED }

enum class SkillUiStatus {
    READY,
    NEEDS_VALIDATION,
    DEGRADED,
    DISABLED,
    RUNTIME_REQUIRED
}

enum class LinuxSkillRuntimeState { MISSING, INSTALLING, READY, DAMAGED, DISABLED }

data class SkillCardModel(
    val id: String,
    val title: String,
    val description: String,
    val kind: SkillKind,
    val status: SkillUiStatus,
    val callable: Boolean,
    val successCount: Int = 0,
    val lastUsedAt: Long = 0L
)

object SkillCenterCatalog {
    fun build(
        learnedTemplates: List<WorkflowTemplate>,
        linuxRuntime: LinuxSkillRuntimeState
    ): List<SkillCardModel> {
        val linuxStatus = if (linuxRuntime == LinuxSkillRuntimeState.READY) {
            SkillUiStatus.READY
        } else {
            SkillUiStatus.RUNTIME_REQUIRED
        }
        val linuxCallable = linuxRuntime == LinuxSkillRuntimeState.READY
        val builtIn = listOf(
            SkillCardModel(
                id = "workspace.text.batch",
                title = "批量文本处理",
                description = "在隔离的 PRoot/Alpine 环境中进行去重、排序和空白清理。",
                kind = SkillKind.LINUX,
                status = linuxStatus,
                callable = linuxCallable
            ),
            SkillCardModel(
                id = "workspace.jsonl.transform",
                title = "JSONL 行处理",
                description = "在隔离环境中校验非空行并进行稳定排序；不开放任意脚本。",
                kind = SkillKind.LINUX,
                status = linuxStatus,
                callable = linuxCallable
            )
        )
        val learned = learnedTemplates
            .sortedWith(
                compareBy<WorkflowTemplate> { statusRank(it.status) }
                    .thenByDescending { it.lastUsedAt }
                    .thenBy { it.name }
            )
            .map { template ->
                val status = when (template.status) {
                    TemplateStatus.ACTIVE -> SkillUiStatus.READY
                    TemplateStatus.DRAFT, TemplateStatus.VALIDATING -> SkillUiStatus.NEEDS_VALIDATION
                    TemplateStatus.DEGRADED -> SkillUiStatus.DEGRADED
                    TemplateStatus.DISABLED -> SkillUiStatus.DISABLED
                }
                SkillCardModel(
                    id = template.id,
                    title = template.name.ifBlank { "未命名 Skill" },
                    description = template.description,
                    kind = SkillKind.LEARNED,
                    status = status,
                    callable = template.status == TemplateStatus.ACTIVE,
                    successCount = template.successCount,
                    lastUsedAt = template.lastUsedAt
                )
            }
        return builtIn + learned
    }

    private fun statusRank(status: TemplateStatus): Int = when (status) {
        TemplateStatus.ACTIVE -> 0
        TemplateStatus.VALIDATING -> 1
        TemplateStatus.DRAFT -> 2
        TemplateStatus.DEGRADED -> 3
        TemplateStatus.DISABLED -> 4
    }
}
