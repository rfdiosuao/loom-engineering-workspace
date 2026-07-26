package com.apk.claw.android.workflow

import com.apk.claw.android.rpa.RpaWorkflowRunner
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class TemplateValidationSchedulerTest {
    @Test
    fun validation_runs_only_when_every_idle_and_restore_gate_is_ready() {
        val blockedStates = listOf(
            readiness().copy(taskQueueIdle = false) to ValidationSkipReason.TASK_QUEUE_BUSY,
            readiness().copy(deviceUnlocked = false) to ValidationSkipReason.DEVICE_LOCKED,
            readiness().copy(accessibilityHealthy = false) to ValidationSkipReason.ACCESSIBILITY_UNHEALTHY,
            readiness().copy(expectedPackageRestorable = false) to ValidationSkipReason.PACKAGE_NOT_RESTORABLE,
            readiness().copy(resetRestorable = false) to ValidationSkipReason.RESET_NOT_RESTORABLE,
            readiness().copy(profileId = OTHER_PROFILE_ID) to ValidationSkipReason.PROFILE_MISMATCH
        )

        blockedStates.forEach { (state, reason) ->
            val resetCalls = AtomicInteger()
            val stepCalls = AtomicInteger()
            val scheduler = scheduler(
                state = state,
                resetCalls = resetCalls,
                stepCalls = stepCalls
            )

            val result = scheduler.enqueue(template())

            assertEquals(reason, (result as ValidationScheduleResult.Skipped).reason)
            assertEquals(0, resetCalls.get())
            assertEquals(0, stepCalls.get())
        }
    }

    @Test
    fun rpa_busy_and_disallowed_risk_never_reset_or_execute() {
        val resetCalls = AtomicInteger()
        val stepCalls = AtomicInteger()
        val persisted = mutableListOf<WorkflowTemplate>()
        val normalLease = requireNotNull(RpaWorkflowRunner.tryAcquireExecutionLease())

        try {
            assertEquals(
                ValidationSkipReason.RPA_BUSY,
                (scheduler(readiness(), resetCalls, stepCalls, persisted).enqueue(template())
                    as ValidationScheduleResult.Skipped).reason
            )
        } finally {
            normalLease.close()
        }

        val allowedScheduler = scheduler(readiness(), resetCalls, stepCalls)
        listOf(
            TemplateRiskLevel.SIDE_EFFECT,
            TemplateRiskLevel.DANGEROUS,
            TemplateRiskLevel.UNKNOWN
        ).forEach { risk ->
            assertEquals(
                ValidationSkipReason.RISK_NOT_ALLOWED,
                (allowedScheduler.enqueue(template().copy(riskLevel = risk)) as ValidationScheduleResult.Skipped).reason
            )
        }
        assertEquals(0, resetCalls.get())
        assertEquals(0, stepCalls.get())
        assertTrue(persisted.isEmpty())
    }

    @Test
    fun read_only_and_resettable_reversible_templates_are_allowed() {
        listOf(TemplateRiskLevel.READ_ONLY, TemplateRiskLevel.REVERSIBLE).forEach { risk ->
            val persisted = mutableListOf<WorkflowTemplate>()
            val result = scheduler(readiness(), persisted = persisted).enqueue(template().copy(riskLevel = risk))

            assertTrue(result is ValidationScheduleResult.Completed)
            assertEquals(1, persisted.size)
            assertEquals(1, persisted.single().validationState.consecutiveSuccesses)
        }
    }

    @Test
    fun self_attested_profile_is_rejected_before_reset_execution_or_persistence() {
        val untrustedProfile = "person@example.com"
        val resetCalls = AtomicInteger()
        val stepCalls = AtomicInteger()
        val persisted = mutableListOf<WorkflowTemplate>()
        val untrustedTemplate = template().copy(
            targetProfileId = untrustedProfile,
            validationState = ValidationState(profileId = untrustedProfile, validatedRevision = 1)
        )
        val scheduler = TemplateValidationScheduler(
            readiness = { readiness().copy(profileId = untrustedProfile) },
            reset = {
                resetCalls.incrementAndGet()
                ValidationResetResult("reset-a", restored = true)
            },
            execute = { current, resetId ->
                stepCalls.incrementAndGet()
                successfulResult(current, resetId)
            },
            persist = { persisted += it }
        )

        val result = scheduler.enqueue(untrustedTemplate)

        assertEquals(
            ValidationSkipReason.PROFILE_MISMATCH,
            (result as ValidationScheduleResult.Skipped).reason
        )
        assertEquals(0, resetCalls.get())
        assertEquals(0, stepCalls.get())
        assertTrue(persisted.isEmpty())
    }

    @Test
    fun installed_target_profile_with_unavailable_or_different_foreground_skips_without_side_effects() {
        listOf("", OTHER_PROFILE_ID).forEach { liveProfile ->
            val resetCalls = AtomicInteger()
            val stepCalls = AtomicInteger()
            val persisted = mutableListOf<WorkflowTemplate>()
            val scheduler = scheduler(
                state = readiness(),
                resetCalls = resetCalls,
                stepCalls = stepCalls,
                persisted = persisted,
                liveProfile = liveProfile
            )

            val result = scheduler.enqueue(template())

            assertEquals(
                ValidationSkipReason.PROFILE_MISMATCH,
                (result as ValidationScheduleResult.Skipped).reason
            )
            assertEquals(0, resetCalls.get())
            assertEquals(0, stepCalls.get())
            assertTrue(persisted.isEmpty())
        }
    }

    @Test
    fun mismatched_execution_profile_bypasses_without_persisting_the_template() {
        val persisted = mutableListOf<WorkflowTemplate>()
        val scheduler = TemplateValidationScheduler(
            readiness = { readiness() },
            reset = { ValidationResetResult("reset-a", restored = true) },
            execute = { current, resetId ->
                successfulResult(current, resetId).copy(profileId = OTHER_PROFILE_ID)
            },
            persist = { persisted += it },
            coordinator = trustedCoordinator()
        )
        val template = template()

        val result = scheduler.enqueue(template) as ValidationScheduleResult.Completed

        assertEquals(template, result.template)
        assertTrue(result.resetSucceeded)
        assertTrue(result.stepsExecuted)
        assertTrue(persisted.isEmpty())
    }

    @Test
    fun reset_failure_counts_failure_without_executing_steps() {
        val stepCalls = AtomicInteger()
        val persisted = mutableListOf<WorkflowTemplate>()
        val scheduler = scheduler(
            state = readiness(),
            stepCalls = stepCalls,
            persisted = persisted,
            reset = { ValidationResetResult("reset-failed", restored = false) }
        )

        val result = scheduler.enqueue(template().copy(
            status = TemplateStatus.VALIDATING,
            validationState = ValidationState(
                profileId = PROFILE_ID,
                consecutiveSuccesses = 2,
                validatedResetIds = setOf("old-a", "old-b"),
                validatedResolvers = setOf(ResolverKind.RESOURCE_ID)
            )
        )) as ValidationScheduleResult.Completed

        assertFalse(result.resetSucceeded)
        assertFalse(result.stepsExecuted)
        assertEquals(0, stepCalls.get())
        assertEquals(1, persisted.single().validationState.failures)
        assertEquals(0, persisted.single().validationState.consecutiveSuccesses)
    }

    @Test
    fun one_validation_is_active_globally_even_across_scheduler_instances() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        val first = scheduler(
            state = readiness(),
            reset = {
                entered.countDown()
                release.await(5, TimeUnit.SECONDS)
                ValidationResetResult("reset-a", restored = true)
            }
        )
        val secondResetCalls = AtomicInteger()
        val second = scheduler(readiness(), resetCalls = secondResetCalls)

        val future = pool.submit<ValidationScheduleResult> { first.enqueue(template()) }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val concurrent = second.enqueue(template())
        release.countDown()

        assertEquals(
            ValidationSkipReason.RPA_BUSY,
            (concurrent as ValidationScheduleResult.Skipped).reason
        )
        assertEquals(0, secondResetCalls.get())
        assertTrue(future.get(5, TimeUnit.SECONDS) is ValidationScheduleResult.Completed)
        pool.shutdownNow()
    }

    @Test
    fun validation_lease_blocks_normal_rpa_claim_until_validation_releases() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        val scheduler = scheduler(
            state = readiness(),
            reset = {
                entered.countDown()
                release.await(5, TimeUnit.SECONDS)
                ValidationResetResult("reset-a", restored = true)
            }
        )

        val future = pool.submit<ValidationScheduleResult> { scheduler.enqueue(template()) }
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            assertNull(RpaWorkflowRunner.tryAcquireExecutionLease())
        } finally {
            release.countDown()
        }
        assertTrue(future.get(5, TimeUnit.SECONDS) is ValidationScheduleResult.Completed)
        val after = RpaWorkflowRunner.tryAcquireExecutionLease()
        assertNotNull(after)
        after?.close()
        pool.shutdownNow()
    }

    @Test
    fun readiness_is_rechecked_after_shared_lease_acquisition() {
        val readinessReads = AtomicInteger()
        val resetCalls = AtomicInteger()
        val persisted = mutableListOf<WorkflowTemplate>()
        val scheduler = TemplateValidationScheduler(
            readiness = {
                if (readinessReads.incrementAndGet() == 1) readiness()
                else readiness().copy(deviceUnlocked = false)
            },
            reset = {
                resetCalls.incrementAndGet()
                ValidationResetResult("reset-a", restored = true)
            },
            execute = { _, _ -> error("steps must not execute") },
            persist = { persisted += it },
            coordinator = trustedCoordinator()
        )

        val result = scheduler.enqueue(template()) as ValidationScheduleResult.Skipped

        assertEquals(ValidationSkipReason.DEVICE_LOCKED, result.reason)
        assertEquals(2, readinessReads.get())
        assertEquals(0, resetCalls.get())
        assertTrue(persisted.isEmpty())
        val lease = RpaWorkflowRunner.tryAcquireExecutionLease()
        assertNotNull(lease)
        lease?.close()
    }

    @Test
    fun validation_lease_releases_when_persistence_throws() {
        val scheduler = TemplateValidationScheduler(
            readiness = { readiness() },
            reset = { ValidationResetResult("reset-a", restored = true) },
            execute = { current, resetId -> successfulResult(current, resetId) },
            persist = { error("persist failed") },
            coordinator = trustedCoordinator()
        )

        assertThrows(IllegalStateException::class.java) { scheduler.enqueue(template()) }
        val lease = RpaWorkflowRunner.tryAcquireExecutionLease()
        assertNotNull(lease)
        lease?.close()
    }

    @Test
    fun stale_double_close_cannot_release_a_newer_runner_lease() {
        val first = requireNotNull(RpaWorkflowRunner.tryAcquireExecutionLease())
        first.close()
        val second = requireNotNull(RpaWorkflowRunner.tryAcquireExecutionLease())

        first.close()

        assertNull(RpaWorkflowRunner.tryAcquireValidationLease())
        second.close()
        val third = RpaWorkflowRunner.tryAcquireValidationLease()
        assertNotNull(third)
        third?.close()
    }

    private fun scheduler(
        state: ValidationReadiness,
        resetCalls: AtomicInteger = AtomicInteger(),
        stepCalls: AtomicInteger = AtomicInteger(),
        persisted: MutableList<WorkflowTemplate> = mutableListOf(),
        liveProfile: String = PROFILE_ID,
        reset: (WorkflowTemplate) -> ValidationResetResult = {
            resetCalls.incrementAndGet()
            ValidationResetResult("reset-a", restored = true)
        }
    ) = TemplateValidationScheduler(
        readiness = { state },
        reset = reset,
        execute = { template, resetId ->
            stepCalls.incrementAndGet()
            ValidationResult(
                profileId = state.profileId,
                resetId = resetId,
                success = true,
                coveredResolvers = template.steps.flatMap { it.allowedResolvers }.toSet(),
                allOutcomesVerified = true,
                usedStaleFrame = false,
                serviceRebound = false,
                retriedAfterDispatch = false,
                unresolvedWindows = false,
                templateRevision = template.revision
            )
        },
        persist = { persisted += it },
        coordinator = trustedCoordinator(liveProfile)
    )

    private fun successfulResult(template: WorkflowTemplate, resetId: String) = ValidationResult(
        profileId = template.targetProfileId,
        resetId = resetId,
        success = true,
        coveredResolvers = template.steps.flatMap { it.allowedResolvers }.toSet(),
        allOutcomesVerified = true,
        usedStaleFrame = false,
        serviceRebound = false,
        retriedAfterDispatch = false,
        unresolvedWindows = false,
        templateRevision = template.revision
    )

    private fun readiness() = ValidationReadiness(
        taskQueueIdle = true,
        deviceUnlocked = true,
        accessibilityHealthy = true,
        expectedPackageRestorable = true,
        resetRestorable = true,
        profileId = PROFILE_ID
    )

    private fun template() = WorkflowTemplate(
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
                allowedResolvers = setOf(ResolverKind.RESOURCE_ID)
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

    private fun trustedCoordinator(liveProfile: String = PROFILE_ID): TemplatePromotionCoordinator {
        val freshForegroundProfile: () -> String = { liveProfile }
        return TemplatePromotionCoordinator(
            clock = { 9_000L },
            liveProfileProvider = freshForegroundProfile
        )
    }

    companion object {
        private const val PROFILE_ID = "0123456789abcdef01234567"
        private const val OTHER_PROFILE_ID = "89abcdef0123456701234567"
    }
}
