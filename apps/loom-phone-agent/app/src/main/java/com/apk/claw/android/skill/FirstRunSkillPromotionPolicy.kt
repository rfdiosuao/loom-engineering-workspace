package com.apk.claw.android.skill

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy
import com.apk.claw.android.workflow.TemplateRiskLevel
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.ValidationState
import com.apk.claw.android.workflow.WorkflowTemplate

/**
 * Makes only a successful, deterministic, read-only source trajectory callable on its second run.
 * Any selector/vision workflow and every side-effecting workflow keeps the existing multi-reset gate.
 */
object FirstRunSkillPromotionPolicy {
    private const val SOURCE_EXECUTION_EVIDENCE = "source-execution"

    fun isEligible(template: WorkflowTemplate): Boolean =
        template.status == TemplateStatus.DRAFT &&
            template.riskLevel == TemplateRiskLevel.READ_ONLY &&
            template.targetPackage.isNotBlank() &&
            template.targetProfileId.isNotBlank() &&
            template.steps.isNotEmpty() &&
            template.steps.all { step ->
                step.resolverPolicy == ResolverPolicy.DIRECT &&
                    step.allowedResolvers == setOf(ResolverKind.DIRECT) &&
                    step.toolName in setOf("open_app", "wait")
            }

    fun promoteIfEligible(template: WorkflowTemplate): WorkflowTemplate {
        if (!isEligible(template)) return template
        return template.copy(
            status = TemplateStatus.ACTIVE,
            activatedAt = System.currentTimeMillis(),
            steps = template.steps.map { step ->
                step.copy(validatedResolvers = setOf(ResolverKind.DIRECT))
            },
            validationState = ValidationState(
                target = 1,
                profileId = template.targetProfileId,
                consecutiveSuccesses = 1,
                validatedResolvers = setOf(ResolverKind.DIRECT),
                validatedResetIds = setOf(SOURCE_EXECUTION_EVIDENCE),
                lastValidationAt = System.currentTimeMillis(),
                validatedRevision = template.revision
            )
        )
    }
}
