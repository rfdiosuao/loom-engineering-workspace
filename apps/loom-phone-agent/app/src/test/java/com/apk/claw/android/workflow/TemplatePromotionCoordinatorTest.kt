package com.apk.claw.android.workflow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class TemplatePromotionCoordinatorTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    private val coordinator = coordinatorFor(PROFILE_ID)

    @Test
    fun activation_requires_three_successes_two_resets_and_all_resolvers() {
        var template = draft(
            required = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
        )

        template = coordinator.recordValidation(
            template,
            success("reset-a", setOf(ResolverKind.RESOURCE_ID))
        )
        template = coordinator.recordValidation(
            template,
            success("reset-b", setOf(ResolverKind.VISUAL_ANCHOR))
        )
        assertEquals(TemplateStatus.VALIDATING, template.status)
        assertEquals(2, template.validationState.consecutiveSuccesses)

        template = coordinator.recordValidation(
            template,
            success("reset-a", setOf(ResolverKind.RESOURCE_ID))
        )

        assertEquals(TemplateStatus.ACTIVE, template.status)
        assertEquals(3, template.validationState.consecutiveSuccesses)
        assertEquals(setOf("reset-a", "reset-b"), template.validationState.validatedResetIds)
        assertEquals(8_000L, template.activatedAt)
        assertEquals(template.revision, template.validationState.validatedRevision)
        assertEquals(
            setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR),
            template.steps.single().validatedResolvers
        )
    }

    @Test
    fun success_count_stays_at_three_until_missing_resolver_coverage_is_complete() {
        var template = draft(setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR))
        template = coordinator.recordValidation(template, success("reset-a", setOf(ResolverKind.RESOURCE_ID)))
        template = coordinator.recordValidation(template, success("reset-b", setOf(ResolverKind.RESOURCE_ID)))
        template = coordinator.recordValidation(template, success("reset-a", setOf(ResolverKind.RESOURCE_ID)))

        assertEquals(TemplateStatus.VALIDATING, template.status)
        assertEquals(3, template.validationState.consecutiveSuccesses)

        template = coordinator.recordValidation(template, success("reset-b", setOf(ResolverKind.VISUAL_ANCHOR)))

        assertEquals(TemplateStatus.ACTIVE, template.status)
        assertEquals(3, template.validationState.consecutiveSuccesses)
    }

    @Test
    fun every_unverified_run_condition_counts_as_a_failure() {
        val invalidResults = listOf(
            success("reset-x").copy(success = false),
            success("reset-x").copy(allOutcomesVerified = false),
            success("reset-x").copy(usedStaleFrame = true),
            success("reset-x").copy(serviceRebound = true),
            success("reset-x").copy(retriedAfterDispatch = true),
            success("reset-x").copy(unresolvedWindows = true)
        )

        invalidResults.forEach { invalid ->
            val progressed = coordinator.recordValidation(draft().withTwoSuccesses(), invalid)
            assertEquals(TemplateStatus.VALIDATING, progressed.status)
            assertEquals(0, progressed.validationState.consecutiveSuccesses)
            assertEquals(1, progressed.validationState.failures)
            assertTrue(progressed.validationState.validatedResetIds.isEmpty())
            assertTrue(progressed.validationState.validatedResolvers.isEmpty())
        }
    }

    @Test
    fun reset_and_resolver_evidence_must_belong_to_the_current_success_streak() {
        var template = draft(setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR))
        template = coordinator.recordValidation(template, success("old-a", setOf(ResolverKind.RESOURCE_ID)))
        template = coordinator.recordValidation(template, success("old-b", setOf(ResolverKind.VISUAL_ANCHOR)))
        template = coordinator.recordValidation(template, success("failed").copy(success = false))
        template = coordinator.recordValidation(template, success("new-a", emptySet()))
        template = coordinator.recordValidation(template, success("new-a", emptySet()))
        template = coordinator.recordValidation(template, success("new-a", emptySet()))

        assertEquals(TemplateStatus.VALIDATING, template.status)
        assertEquals(setOf("new-a"), template.validationState.validatedResetIds)
        assertTrue(template.validationState.validatedResolvers.isEmpty())
    }

    @Test
    fun profile_or_revision_mismatch_bypasses_without_mutating_template() {
        val template = active()

        assertEquals(MatchDecision.PROFILE_MISMATCH, coordinator.match(template, OTHER_PROFILE_ID))
        assertSame(template, coordinator.recordValidation(template, success("reset-x")))
        val validating = template.copy(status = TemplateStatus.VALIDATING)
        assertSame(
            validating,
            coordinator.recordValidation(validating, success("reset-x").copy(profileId = OTHER_PROFILE_ID))
        )
        assertSame(
            validating,
            coordinator.recordValidation(validating, success("reset-x").copy(templateRevision = 2))
        )
        assertSame(
            validating,
            coordinator.recordValidation(validating, success("reset-x").copy(templateRevision = 0))
        )
        assertSame(
            validating,
            coordinator.recordValidation(validating, success("reset-x").copy(templateRevision = -1))
        )
        assertEquals(MatchDecision.MATCH, coordinator.match(template, PROFILE_ID))
    }

    @Test
    fun stored_and_reported_profiles_cannot_self_attest_without_a_live_profile() {
        listOf("person@example.com", STALE_PROFILE_ID).forEach { untrustedProfile ->
            val template = draft().copy(
                status = TemplateStatus.VALIDATING,
                targetProfileId = untrustedProfile,
                validationState = ValidationState(
                    profileId = untrustedProfile,
                    consecutiveSuccesses = 2,
                    validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
                    validatedResetIds = setOf("reset-a", "reset-b"),
                    validatedRevision = 1
                )
            )
            val echoedResult = success("reset-c").copy(profileId = untrustedProfile)

            assertSame(template, coordinator.recordValidation(template, echoedResult))
        }
    }

    @Test
    fun validation_bypasses_when_the_live_profile_is_unavailable_or_mismatched() {
        val template = draft().withTwoSuccesses()

        listOf("", OTHER_PROFILE_ID).forEach { liveProfile ->
            assertSame(
                template,
                coordinatorFor(liveProfile).recordValidation(template, success("reset-c"))
            )
        }
    }

    @Test
    fun matching_fresh_foreground_profile_advances_validation() {
        val freshForegroundProfile: () -> String = { PROFILE_ID }
        val foregroundCoordinator = TemplatePromotionCoordinator(
            clock = { 8_000L },
            liveProfileProvider = freshForegroundProfile
        )

        val updated = foregroundCoordinator.recordValidation(draft(), success("reset-a"))

        assertEquals(1, updated.validationState.consecutiveSuccesses)
        assertEquals(TemplateStatus.VALIDATING, updated.status)
    }

    @Test
    fun manager_lifecycle_updates_require_an_exact_positive_revision() {
        val current = draft()
        val mutation: (WorkflowTemplate) -> WorkflowTemplate = { template ->
            template.copy(status = TemplateStatus.DEGRADED)
        }

        listOf(0, -1, 2).forEach { revision ->
            assertSame(
                current,
                WorkflowTemplateManager.applyRevisionBoundLifecycleUpdate(
                    current,
                    revision,
                    mutation
                )
            )
        }
        assertEquals(
            TemplateStatus.DEGRADED,
            WorkflowTemplateManager.applyRevisionBoundLifecycleUpdate(current, 1, mutation).status
        )
    }

    @Test
    fun manager_runtime_failure_contract_requires_reported_profile_without_an_overload() {
        val signatures = WorkflowTemplateManager::class.java.declaredMethods
            .filter { it.name == "recordTemplateRuntimeFailure" }
            .map { it.parameterCount }

        assertEquals(listOf(4), signatures)
    }

    @Test
    fun blank_reset_id_is_a_counted_failure_instead_of_an_exception() {
        val updated = coordinator.recordValidation(draft().withTwoSuccesses(), success(""))

        assertEquals(0, updated.validationState.consecutiveSuccesses)
        assertEquals(1, updated.validationState.failures)
        assertTrue(updated.validationState.validatedResetIds.isEmpty())
    }

    @Test
    fun manager_selection_rejects_conflicting_target_profile_without_mutation() {
        val active = active().copy(targetProfileId = OTHER_PROFILE_ID)

        assertNull(
            WorkflowTemplateManager.selectActiveTemplateForPrompt(
                listOf(active),
                "test",
                PROFILE_ID
            )
        )
        assertEquals(TemplateStatus.ACTIVE, active.status)
        assertEquals(1, active.revision)
    }

    @Test
    fun activated_revision_and_resolver_coverage_survive_store_round_trip() {
        var template = draft(setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR))
        template = coordinator.recordValidation(template, success("reset-a", setOf(ResolverKind.RESOURCE_ID)))
        template = coordinator.recordValidation(template, success("reset-b", setOf(ResolverKind.VISUAL_ANCHOR)))
        template = coordinator.recordValidation(template, success("reset-a", setOf(ResolverKind.RESOURCE_ID)))
        val store = WorkflowTemplateStore(temporaryFolder.newFolder("templates"))

        store.save(listOf(template))
        val reloaded = store.load().single()

        assertEquals(TemplateStatus.ACTIVE, reloaded.status)
        assertEquals(template.validationState, reloaded.validationState)
        assertEquals(template.steps.single().validatedResolvers, reloaded.steps.single().validatedResolvers)
        assertEquals(PROFILE_ID, reloaded.targetProfileId)
    }

    @Test
    fun structural_freshness_and_app_version_failures_degrade_same_revision() {
        val active = active()
        listOf("structural_mismatch", "freshness_violation", "app_version_mismatch").forEach { code ->
            val degraded = coordinator.recordRuntimeFailure(active, PROFILE_ID, active.revision, code)
            assertEquals(TemplateStatus.DEGRADED, degraded.status)
            assertEquals(code, degraded.degradedReason)
            assertEquals(8_000L, degraded.degradedAt)
            assertEquals(active.revision, degraded.revision)
        }

        assertSame(active, coordinator.recordRuntimeFailure(active, PROFILE_ID, active.revision, "profile_mismatch"))
        assertSame(active, coordinator.recordRuntimeFailure(active, PROFILE_ID, active.revision, "cancelled"))
    }

    @Test
    fun runtime_failure_requires_exact_live_reported_profile_and_positive_revision() {
        val active = active()

        listOf(0, -1, 2).forEach { revision ->
            assertSame(
                active,
                coordinator.recordRuntimeFailure(active, PROFILE_ID, revision, "structural_mismatch")
            )
        }
        assertSame(
            active,
            coordinator.recordRuntimeFailure(active, OTHER_PROFILE_ID, active.revision, "structural_mismatch")
        )
        assertSame(
            active,
            coordinatorFor(OTHER_PROFILE_ID).recordRuntimeFailure(
                active,
                PROFILE_ID,
                active.revision,
                "structural_mismatch"
            )
        )
        assertSame(
            active,
            TemplatePromotionCoordinator(clock = { 8_000L }).recordRuntimeFailure(
                active,
                PROFILE_ID,
                active.revision,
                "structural_mismatch"
            )
        )
    }

    @Test
    fun degraded_revision_requires_a_fresh_three_run_streak_before_reactivation() {
        var template = coordinator.recordRuntimeFailure(active(), PROFILE_ID, 1, "structural_mismatch")

        template = coordinator.recordValidation(template, success("new-a"))
        assertEquals(TemplateStatus.VALIDATING, template.status)
        assertEquals(1, template.validationState.consecutiveSuccesses)
        assertEquals(setOf("new-a"), template.validationState.validatedResetIds)

        template = coordinator.recordValidation(template, success("new-b"))
        assertEquals(TemplateStatus.VALIDATING, template.status)
        assertEquals(2, template.validationState.consecutiveSuccesses)

        template = coordinator.recordValidation(template, success("new-a"))
        assertEquals(TemplateStatus.ACTIVE, template.status)
        assertEquals(3, template.validationState.consecutiveSuccesses)
    }

    private fun WorkflowTemplate.withTwoSuccesses(): WorkflowTemplate = copy(
        status = TemplateStatus.VALIDATING,
        validationState = validationState.copy(
            consecutiveSuccesses = 2,
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
            validatedResetIds = setOf("reset-a", "reset-b")
        )
    )

    private fun active() = draft().copy(
        status = TemplateStatus.ACTIVE,
        activatedAt = 7_000L,
        validationState = ValidationState(
            profileId = PROFILE_ID,
            consecutiveSuccesses = 3,
            validatedResolvers = setOf(ResolverKind.RESOURCE_ID),
            validatedResetIds = setOf("reset-a", "reset-b"),
            validatedRevision = 1
        )
    )

    private fun draft(required: Set<ResolverKind> = setOf(ResolverKind.RESOURCE_ID)) = WorkflowTemplate(
        id = "template-1",
        name = "test",
        description = "test",
        taskPattern = "test",
        keywords = listOf("test"),
        appName = null,
        steps = listOf(
            WorkflowTemplate.WorkflowStep(
                toolName = "tap_semantic",
                paramsTemplate = emptyMap(),
                description = "tap",
                allowedResolvers = required
            )
        ),
        createdAt = 0L,
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        status = TemplateStatus.DRAFT,
        riskLevel = TemplateRiskLevel.READ_ONLY,
        validationState = ValidationState(profileId = PROFILE_ID, validatedRevision = 1),
        revision = 1,
        targetPackage = "com.example.target",
        targetVersionCode = 42L,
        targetProfileId = PROFILE_ID
    )

    private fun success(
        resetId: String,
        covered: Set<ResolverKind> = setOf(ResolverKind.RESOURCE_ID)
    ) = ValidationResult(
        profileId = PROFILE_ID,
        resetId = resetId,
        success = true,
        coveredResolvers = covered,
        allOutcomesVerified = true,
        usedStaleFrame = false,
        serviceRebound = false,
        retriedAfterDispatch = false,
        unresolvedWindows = false,
        templateRevision = 1
    )

    private fun coordinatorFor(liveProfile: String): TemplatePromotionCoordinator {
        val freshForegroundProfile: () -> String = { liveProfile }
        return TemplatePromotionCoordinator(
            clock = { 8_000L },
            liveProfileProvider = freshForegroundProfile
        )
    }

    companion object {
        private const val PROFILE_ID = "0123456789abcdef01234567"
        private const val OTHER_PROFILE_ID = "89abcdef0123456701234567"
        private const val STALE_PROFILE_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
    }
}
