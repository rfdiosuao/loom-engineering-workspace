package com.apk.claw.android.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionFastTransitionPolicyTest {
    @Test
    fun waits_for_post_observe_after_system_navigation_keys() {
        assertTrue(ActionFastTransitionPolicy.requiresStablePostObserve("home"))
        assertTrue(ActionFastTransitionPolicy.requiresStablePostObserve("back"))
        assertFalse(ActionFastTransitionPolicy.requiresStablePostObserve("click_text"))
    }

    @Test
    fun pending_transition_keeps_action_success_but_marks_current_step_retryable() {
        val result = ActionFastTransitionPolicy.currentStepAfterAction(
            action = "home",
            actionSucceeded = true,
            transitionStable = false
        )

        assertEquals("transition_pending", result.currentStep)
        assertTrue(result.retryable)
    }

    @Test
    fun stable_transition_reports_complete() {
        val result = ActionFastTransitionPolicy.currentStepAfterAction(
            action = "home",
            actionSucceeded = true,
            transitionStable = true
        )

        assertEquals("complete", result.currentStep)
        assertFalse(result.retryable)
    }
}
