package com.apk.claw.android.skill

import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.ValidationState
import com.apk.claw.android.workflow.WorkflowTemplate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SkillCenterCatalogTest {
    @Test
    fun `catalog exposes fixed Linux skills and learned skills in one list`() {
        val cards = SkillCenterCatalog.build(
            learnedTemplates = listOf(template("active", TemplateStatus.ACTIVE), template("draft", TemplateStatus.DRAFT)),
            linuxRuntime = LinuxSkillRuntimeState.READY
        )

        assertEquals(
            listOf("workspace.text.batch", "workspace.jsonl.transform"),
            cards.filter { it.kind == SkillKind.LINUX }.map { it.id }
        )
        assertTrue(cards.first { it.id == "workspace.text.batch" }.callable)
        assertTrue(cards.first { it.id == "active" }.callable)
        assertFalse(cards.first { it.id == "draft" }.callable)
        assertEquals(SkillUiStatus.NEEDS_VALIDATION, cards.first { it.id == "draft" }.status)
    }

    @Test
    fun `Linux skills stay visible but unavailable when companion is missing`() {
        val cards = SkillCenterCatalog.build(emptyList(), LinuxSkillRuntimeState.MISSING)

        assertFalse(cards.first { it.id == "workspace.text.batch" }.callable)
        assertEquals(SkillUiStatus.RUNTIME_REQUIRED, cards.first { it.id == "workspace.text.batch" }.status)
        assertFalse(cards.any { it.id == "agent.cli.batch" })
    }

    private fun template(id: String, status: TemplateStatus) = WorkflowTemplate(
        id = id,
        name = "Skill $id",
        description = "learned",
        taskPattern = id,
        keywords = listOf(id),
        appName = null,
        steps = emptyList(),
        createdAt = 1L,
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        status = status,
        riskLevel = TemplateRiskLevel.READ_ONLY,
        validationState = ValidationState(profileId = "profile", validatedRevision = 1),
        targetProfileId = "profile"
    )
}
