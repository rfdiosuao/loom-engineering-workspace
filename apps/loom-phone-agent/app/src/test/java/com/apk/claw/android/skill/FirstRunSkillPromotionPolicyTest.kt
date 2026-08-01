package com.apk.claw.android.skill

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.ValidationState
import com.apk.claw.android.workflow.WorkflowTemplate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstRunSkillPromotionPolicyTest {
    @Test
    fun `successful deterministic read only trajectory becomes callable for second run`() {
        val promoted = FirstRunSkillPromotionPolicy.promoteIfEligible(template(TemplateRiskLevel.READ_ONLY))

        assertEquals(TemplateStatus.ACTIVE, promoted.status)
        assertEquals(1, promoted.validationState.consecutiveSuccesses)
        assertEquals(1, promoted.validationState.target)
        assertTrue(promoted.steps.single().validatedResolvers.contains(ResolverKind.DIRECT))
    }

    @Test
    fun `side effects and non direct resolvers keep strict validation gate`() {
        assertFalse(FirstRunSkillPromotionPolicy.isEligible(template(TemplateRiskLevel.SIDE_EFFECT)))
        assertFalse(
            FirstRunSkillPromotionPolicy.isEligible(
                template(TemplateRiskLevel.READ_ONLY).copy(
                    steps = listOf(
                        template(TemplateRiskLevel.READ_ONLY).steps.single().copy(
                            resolverPolicy = ResolverPolicy.TREE_PREFERRED,
                            allowedResolvers = setOf(ResolverKind.TEXT_CLASS)
                        )
                    )
                )
            )
        )
    }

    private fun template(risk: TemplateRiskLevel) = WorkflowTemplate(
        id = "learned",
        name = "open settings",
        description = "learned",
        taskPattern = "open settings",
        keywords = listOf("settings"),
        appName = "Settings",
        steps = listOf(
            WorkflowTemplate.WorkflowStep(
                toolName = "open_app",
                paramsTemplate = mapOf("package_name" to "com.android.settings", "check_launch_dialog" to false),
                description = "Open settings",
                waitFor = 0,
                resolverPolicy = ResolverPolicy.DIRECT,
                allowedResolvers = setOf(ResolverKind.DIRECT)
            )
        ),
        createdAt = 1L,
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        status = TemplateStatus.DRAFT,
        riskLevel = risk,
        validationState = ValidationState(profileId = "profile-1", validatedRevision = 1),
        targetProfileId = "profile-1",
        targetPackage = "com.android.settings"
    )
}
