package com.apk.claw.android.server

import com.apk.claw.android.workflow.ValidationSkipReason
import com.apk.claw.android.workflow.TemplateStatus
import com.apk.claw.android.workflow.ValidationState
import com.apk.claw.android.workflow.WorkflowTemplate
import com.apk.claw.android.workflow.WorkflowTemplateManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkflowTemplateLifecycleControllerTest {
    @Test
    fun scheduler_busy_accessibility_profile_and_risk_failures_are_structured() {
        val expected = mapOf(
            ValidationSkipReason.TASK_QUEUE_BUSY to Triple("task_busy", true, "precheck"),
            ValidationSkipReason.RPA_BUSY to Triple("rpa_busy", true, "precheck"),
            ValidationSkipReason.ACCESSIBILITY_UNHEALTHY to Triple("accessibility_unavailable", true, "precheck"),
            ValidationSkipReason.PROFILE_MISMATCH to Triple("profile_mismatch", false, "profile"),
            ValidationSkipReason.RISK_NOT_ALLOWED to Triple("risk_not_allowed", false, "risk")
        )

        expected.forEach { (reason, contract) ->
            val payload = WorkflowApiController.validationFailure(reason)
            assertFalse(payload["success"].asBoolean)
            assertEquals(contract.first, payload["errorCode"].asString)
            assertEquals(contract.second, payload["retryable"].asBoolean)
            assertEquals(contract.third, payload["currentStep"].asString)
            assertEquals("hybrid_rpa", payload["mode"].asString)
            assertTrue(payload["message"].asString.isNotBlank())
        }
    }

    @Test
    fun workflow_execute_serializes_hybrid_status_and_profile_failures_with_full_contract() {
        val profile = "0123456789abcdef01234567"
        val cases = listOf(
            Triple(template("draft", TemplateStatus.DRAFT, profile), profile, "template_status_invalid"),
            Triple(template("validating", TemplateStatus.VALIDATING, profile), profile, "template_status_invalid"),
            Triple(template("degraded", TemplateStatus.DEGRADED, profile), profile, "template_status_invalid"),
            Triple(template("disabled", TemplateStatus.DISABLED, profile), profile, "template_status_invalid"),
            Triple(template("stale", TemplateStatus.ACTIVE, profile, revision = 2, validatedRevision = 1), profile, "template_status_invalid"),
            Triple(template("wrong-profile", TemplateStatus.ACTIVE, profile), "fedcba9876543210fedcba98", "profile_mismatch")
        )

        cases.forEach { (template, freshProfile, errorCode) ->
            val result = WorkflowTemplateManager.executeTemplate(template, freshProfileProvider = { freshProfile })

            val payload = WorkflowApiController.templateExecutionJson(template, result)

            assertFalse(payload["success"].asBoolean)
            assertEquals(errorCode, payload["errorCode"].asString)
            assertTrue(payload["message"].asString.isNotBlank())
            assertEquals("authorize", payload["currentStep"].asString)
            assertEquals("hybrid_rpa", payload["mode"].asString)
            assertFalse(payload["retryable"].asBoolean)
        }
    }

    private fun template(
        id: String,
        status: TemplateStatus,
        profile: String,
        revision: Int = 1,
        validatedRevision: Int = revision
    ) = WorkflowTemplate(
        id = id,
        name = id,
        description = "test",
        taskPattern = "test",
        keywords = emptyList(),
        appName = null,
        steps = emptyList(),
        createdAt = 0L,
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        status = status,
        validationState = ValidationState(profileId = profile, validatedRevision = validatedRevision),
        revision = revision,
        targetProfileId = profile
    )
}
