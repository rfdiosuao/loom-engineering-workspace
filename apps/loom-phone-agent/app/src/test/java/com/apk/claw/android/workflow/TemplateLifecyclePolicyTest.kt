package com.apk.claw.android.workflow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TemplateLifecyclePolicyTest {
    @Test
    fun three_consecutive_successes_activate_only_matching_profile() {
        var state = ValidationState(target = 3, profileId = "emulator-profile")

        state = TemplateLifecyclePolicy.recordValidation(
            state, "emulator-profile", "reset-a", true, setOf(ResolverKind.RESOURCE_ID)
        )
        state = TemplateLifecyclePolicy.recordValidation(
            state, "emulator-profile", "reset-b", true, setOf(ResolverKind.RESOURCE_ID)
        )

        assertEquals(2, state.consecutiveSuccesses)
        assertFalse(TemplateLifecyclePolicy.canActivate(state, setOf(ResolverKind.RESOURCE_ID)))

        state = TemplateLifecyclePolicy.recordValidation(
            state, "emulator-profile", "reset-a", true, setOf(ResolverKind.RESOURCE_ID)
        )

        assertTrue(TemplateLifecyclePolicy.canActivate(state, setOf(ResolverKind.RESOURCE_ID)))
        assertFalse(TemplateLifecyclePolicy.matchesProfile(state, "physical-profile"))
    }

    @Test
    fun failure_resets_consecutive_successes() {
        val initial = ValidationState(target = 3, profileId = "p", consecutiveSuccesses = 2)

        val failed = TemplateLifecyclePolicy.recordValidation(initial, "p", "reset-a", false, emptySet())

        assertEquals(0, failed.consecutiveSuccesses)
        assertEquals(1, failed.failures)
    }

    @Test
    fun activation_requires_exactly_three_successes_even_when_target_is_persisted_incorrectly() {
        var state = ValidationState(target = 1, profileId = "p")

        state = TemplateLifecyclePolicy.recordValidation(state, "p", "reset-a", true, emptySet())
        assertEquals(3, state.target)
        assertFalse(TemplateLifecyclePolicy.canActivate(state, emptySet()))

        state = TemplateLifecyclePolicy.recordValidation(state, "p", "reset-b", true, emptySet())
        assertFalse(TemplateLifecyclePolicy.canActivate(state, emptySet()))

        state = TemplateLifecyclePolicy.recordValidation(state, "p", "reset-a", true, emptySet())
        assertTrue(TemplateLifecyclePolicy.canActivate(state, emptySet()))
    }

    @Test
    fun profile_switch_preserves_validation_revision() {
        val initial = ValidationState(profileId = "old-profile", validatedRevision = 2)

        val switched = TemplateLifecyclePolicy.recordValidation(
            initial,
            "new-profile",
            "reset-a",
            true,
            setOf(ResolverKind.RESOURCE_ID)
        )

        assertEquals(2, switched.validatedRevision)
        assertEquals("new-profile", switched.profileId)
    }
}
