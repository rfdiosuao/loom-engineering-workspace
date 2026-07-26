package com.apk.claw.android.server

import com.apk.claw.android.agent.AgentReplaySafetyPolicy
import com.apk.claw.android.rpa.AgentHandoffContext
import com.apk.claw.android.rpa.HybridCompletedStepEvidence
import com.apk.claw.android.rpa.HybridFailedStepContext
import com.apk.claw.android.rpa.HybridLedgerProof
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentReconciliationTest {
    @Test
    fun uncertain_handoff_context_is_sanitized_and_forbids_blind_replay() {
        val context = AgentReconciliationContextBuilder.build(
            originalGoal = "open settings",
            handoff = handoff()
        )
        val serialized = context.prompt

        assertFalse(context.allowReplayFailedStep)
        assertTrue(serialized.contains("UNCERTAIN"))
        assertTrue(serialized.contains("verification_unknown"))
        listOf(
            "rawScreenshot", "rawTree", "selector", "params", "token", "secret-value",
            "private-screen-text", "ledgerProof", "run-secret", "step-secret"
        ).forEach { assertFalse("leaked $it", serialized.contains(it, ignoreCase = true)) }
    }

    @Test
    fun replay_remains_blocked_until_old_postcondition_absence_is_proven() {
        assertFalse(AgentReplaySafetyPolicy.mayDispatchAction(false, false, "tap"))
        assertTrue(AgentReplaySafetyPolicy.mayDispatchAction(false, true, "tap"))
        assertTrue(AgentReplaySafetyPolicy.mayDispatchAction(false, false, "get_screen_info"))
    }

    private fun handoff() = AgentHandoffContext(
        templateId = "template-1",
        templateRevision = 2,
        targetProfileId = "0123456789abcdef01234567",
        workflowDigest = "a".repeat(64),
        opaqueRunKey = "run-secret",
        completedSteps = listOf(
            HybridCompletedStepEvidence(
                stepIndex = 1,
                stepId = "step-1",
                action = "open_app",
                resolverUsed = "DIRECT",
                uiGeneration = 4L,
                attempts = 1,
                ledgerProof = HybridLedgerProof("run-secret", "step-secret", 1)
            )
        ),
        failedStep = HybridFailedStepContext(
            stepIndex = 2,
            stepId = "step-2",
            action = "tap_semantic",
            errorCode = "verification_unknown",
            outcomeState = "uncertain"
        ),
        replayForbiddenUntilProof = true
    )
}
