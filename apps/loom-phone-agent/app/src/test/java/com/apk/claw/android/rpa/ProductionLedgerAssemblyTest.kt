package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ProductionLedgerAssemblyTest {
    @get:Rule
    val temporary = TemporaryFolder()

    @Test
    fun production_assembly_exposes_no_generation_policy_override() {
        val policyType = PostDispatchGenerationPolicy::class.java
        val bypasses = ProductionLedgerAssembly::class.java.declaredMethods.filter { method ->
            method.parameterTypes.any { it == policyType }
        }

        assertTrue("Production policy override methods: ${bypasses.map { it.name }}", bypasses.isEmpty())
    }

    @Test
    fun only_stamped_fresh_verification_creates_restart_proof_in_shared_store() {
        val filesDirectory = temporary.newFolder("files")
        val first = ProductionLedgerAssembly.create(filesDirectory, clock = { 100L })
        val bareExecutor = first.singleDispatchExecutor(
            dispatcher = ActionDispatcher { DispatchReceipt.accepted(100L) },
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerified },
            generation = { GenerationSnapshot(7L, "service-1") }
        )

        val bareOutcome = bareExecutor.execute(action("bare-run"))
        val bareProof = HybridLedgerProof(
            bareOutcome.entry.runId,
            bareOutcome.entry.stepId,
            bareOutcome.entry.attempt
        )

        assertEquals(ActionOutcomeState.UNCERTAIN, bareOutcome.state)
        assertEquals(null, first.resumeProofVerifier.verify(bareProof))

        val observed = GenerationSnapshot(7L, "service-1")
        val stampedExecutor = first.singleDispatchExecutor(
            dispatcher = ActionDispatcher { DispatchReceipt.accepted(100L) },
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerifiedAt(observed) },
            generation = { observed }
        )
        val stampedOutcome = stampedExecutor.execute(action("stamped-run"))

        assertEquals(ActionOutcomeState.VERIFIED, stampedOutcome.state)
        assertTrue(File(filesDirectory, "workflow_templates/runs").isDirectory)
        assertFalse(File(filesDirectory, "runs").exists())

        val reopened = ProductionLedgerAssembly.create(filesDirectory, clock = { 200L })
        val stampedProof = HybridLedgerProof(
            stampedOutcome.entry.runId,
            stampedOutcome.entry.stepId,
            stampedOutcome.entry.attempt
        )
        assertEquals(null, reopened.resumeProofVerifier.verify(bareProof))
        assertNotNull(reopened.resumeProofVerifier.verify(stampedProof))
    }

    private fun action(runId: String): PreparedAction {
        val identity = Any()
        val evidence = UiEvidence(
            7L,
            "service-1",
            "demo.app",
            3,
            50L,
            DisplayTransform(0, 100, 100, 100, 100, 0, 320, 0, 0, 0, 0),
            null,
            runtimeServiceIdentity = identity
        )
        return PreparedAction(
            runId,
            "step-1",
            1,
            7L,
            "service-1",
            ResolverKind.DIRECT,
            DirectPayload(DirectAction.BACK, evidence = evidence)
        )
    }
}
