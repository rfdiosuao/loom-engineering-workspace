package com.apk.claw.android.workflow

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkflowTemplateManagerTest {
    @Test
    fun learning_does_not_credit_a_first_success() {
        val source = File("src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt").readText()
        val learningBody = source
            .substringAfter("fun learnFromExecution(")
            .substringBefore("fun resolveTemplateParams(")

        assertFalse(learningBody.contains("updateTemplateStats(template.id, true)"))
    }

    @Test
    fun automatic_matching_uses_only_active_templates_bound_to_requested_profile() {
        val matching = template(id = "matching", status = TemplateStatus.ACTIVE, profileId = "emulator")
        val wrongProfile = template(id = "wrong-profile", status = TemplateStatus.ACTIVE, profileId = "physical")
        val draft = template(id = "draft", status = TemplateStatus.DRAFT, profileId = "emulator")

        assertEquals(
            matching,
            WorkflowTemplateManager.selectActiveTemplateForPrompt(
                listOf(wrongProfile, draft, matching), "open settings", "emulator"
            )
        )
        assertNull(
            WorkflowTemplateManager.selectActiveTemplateForPrompt(
                listOf(wrongProfile, draft), "open settings", "emulator"
            )
        )
    }

    @Test
    fun automatic_matching_never_selects_an_empty_profile_template() {
        val emptyProfile = template(id = "empty-profile", status = TemplateStatus.ACTIVE, profileId = "")

        assertNull(WorkflowTemplateManager.matchTemplate("open settings"))
        assertNull(
            WorkflowTemplateManager.selectActiveTemplateForPrompt(
                listOf(emptyProfile), "open settings", ""
            )
        )
    }

    @Test
    fun automatic_matching_rejects_validation_from_another_revision() {
        val staleEvidence = template(
            id = "stale-evidence",
            status = TemplateStatus.ACTIVE,
            profileId = "emulator",
            revision = 2,
            validatedRevision = 1
        )

        assertNull(
            WorkflowTemplateManager.selectActiveTemplateForPrompt(
                listOf(staleEvidence), "open settings", "emulator"
            )
        )
    }

    @Test
    fun resolves_placeholders_without_android_regex_initializer_crash() {
        val template = WorkflowTemplate(
            id = "test-template",
            name = "Test Template",
            description = "Test placeholder extraction",
            taskPattern = "test",
            keywords = listOf("test"),
            appName = null,
            steps = listOf(
                WorkflowTemplate.WorkflowStep(
                    toolName = "input_text",
                    paramsTemplate = mapOf("text" to "hello ${'$'}{contact_name} ${'$'}{message}"),
                    description = "Input parameterized text",
                    waitFor = 0
                )
            ),
            createdAt = 0L,
            lastUsedAt = 0L,
            successCount = 1,
            failCount = 0
        )

        val resolved = WorkflowTemplateManager.resolveTemplateParams(
            template = template,
            userPrompt = "",
            providedParams = mapOf("contact_name" to "Alice")
        )

        assertEquals(listOf("message"), resolved.missingParams)
        assertEquals("Alice", resolved.params["contact_name"])
    }

    @Test
    fun disable_is_revision_safe_and_idempotent() {
        val active = template(
            id = "active",
            status = TemplateStatus.ACTIVE,
            profileId = "emulator",
            revision = 3
        )

        assertSame(active, WorkflowTemplateManager.applyRevisionBoundDisable(active, expectedRevision = 2))
        val disabled = WorkflowTemplateManager.applyRevisionBoundDisable(active, expectedRevision = 3)
        assertEquals(TemplateStatus.DISABLED, disabled.status)
        assertFalse(disabled.validationState.validatedResolvers.isNotEmpty())
        assertTrue(disabled.validationState.consecutiveSuccesses == 0)
        assertSame(disabled, WorkflowTemplateManager.applyRevisionBoundDisable(disabled, expectedRevision = 3))
    }

    @Test
    fun hybrid_workflow_carries_sanitized_lifecycle_snapshot_fields() {
        val active = template(
            id = "active",
            status = TemplateStatus.ACTIVE,
            profileId = "0123456789abcdef01234567",
            revision = 3
        ).copy(
            validationState = ValidationState(
                target = 3,
                profileId = "0123456789abcdef01234567",
                consecutiveSuccesses = 3,
                validatedRevision = 3
            ),
            targetProfileId = "0123456789abcdef01234567"
        )

        val workflow = WorkflowTemplateManager.toHybridWorkflow(active)

        assertEquals("active", workflow.templateStatus)
        assertEquals("3/3", workflow.validationProgress)
        assertTrue(workflow.promotionEligible)
        assertEquals("", workflow.promotionIneligibleReason)
    }

    @Test
    fun hybrid_runtime_failure_uses_task8_fresh_profile_degradation_gate() {
        val source = File("src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt").readText()
        val hybridExecution = source
            .substringAfter("private fun executeHybridTemplate(")
            .substringBefore("internal fun toHybridWorkflow(")

        assertTrue(hybridExecution.contains("recordTemplateRuntimeFailure("))
        assertTrue(hybridExecution.contains("DeviceProfileProvider.current()"))
    }

    @Test
    fun hybrid_execution_rejects_non_active_and_stale_revision_before_runner_or_stats() {
        val profile = "0123456789abcdef01234567"
        val blocked = listOf(
            TemplateStatus.DRAFT,
            TemplateStatus.VALIDATING,
            TemplateStatus.DEGRADED,
            TemplateStatus.DISABLED
        ).map { status -> template("blocked-$status", status, profile) } +
            template("stale-revision", TemplateStatus.ACTIVE, profile, revision = 2, validatedRevision = 1)

        blocked.forEach { candidate ->
            val result = WorkflowTemplateManager.executeTemplate(
                template = candidate,
                freshProfileProvider = { profile }
            )

            assertFalse(candidate.id, result.success)
            assertEquals(candidate.id, "template_status_invalid", result.errorCode)
            assertEquals(candidate.id, 0, result.stepsExecuted)
            assertEquals(candidate.id, "hybrid_rpa", result.mode)
        }
    }

    @Test
    fun hybrid_execution_rejects_missing_or_wrong_fresh_profile_and_accepts_exact_match() {
        val profile = "0123456789abcdef01234567"
        val active = template("active", TemplateStatus.ACTIVE, profile)

        listOf("", "fedcba9876543210fedcba98").forEach { freshProfile ->
            val result = WorkflowTemplateManager.executeTemplate(
                template = active,
                freshProfileProvider = { freshProfile }
            )
            assertFalse(result.success)
            assertEquals("profile_mismatch", result.errorCode)
            assertEquals(0, result.stepsExecuted)
        }
        assertNull(WorkflowTemplateManager.hybridExecutionPrecondition(active, profile))
    }

    private fun template(
        id: String,
        status: TemplateStatus,
        profileId: String,
        revision: Int = 1,
        validatedRevision: Int = revision
    ): WorkflowTemplate {
        return WorkflowTemplate(
            id = id,
            name = id,
            description = "test",
            taskPattern = "open settings",
            keywords = listOf("settings"),
            appName = null,
            steps = emptyList(),
            createdAt = 0L,
            lastUsedAt = 0L,
            successCount = 0,
            failCount = 0,
            status = status,
            validationState = ValidationState(profileId = profileId, validatedRevision = validatedRevision),
            revision = revision
        )
    }
}
