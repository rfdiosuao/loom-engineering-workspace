package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ProductionPostDispatchGenerationPolicyTest {
    @get:Rule
    val temporary = TemporaryFolder()

    @Test
    fun production_policy_accepts_only_monotonic_ui_with_identical_service_generation() {
        val policy = ProductionPostDispatchGenerationPolicy

        assertTrue(policy.accepts(action(), GenerationSnapshot(8L, "service-1")))
        assertTrue(policy.accepts(action(), GenerationSnapshot(7L, "service-1")))
        assertFalse(policy.accepts(action(), GenerationSnapshot(6L, "service-1")))
        assertFalse(policy.accepts(action(), GenerationSnapshot(8L, "service-2")))
    }

    @Test
    fun executor_accepts_monotonic_preverify_generation_only_with_exact_after_proof_snapshot() {
        var verifierCalls = 0
        val observed = GenerationSnapshot(8L, "service-1")
        val executor = executor(
            "exact-proof",
            generation = snapshots(observed, observed),
            verifier = OutcomeVerifier { _, _ ->
                verifierCalls += 1
                VerificationResult.EffectVerifiedAt(observed)
            }
        )

        val outcome = executor.execute(action())

        assertEquals(ActionOutcomeState.VERIFIED, outcome.state)
        assertEquals(1, verifierCalls)
    }

    @Test
    fun generation_change_after_verified_observation_is_uncertain() {
        val observed = GenerationSnapshot(8L, "service-1")
        val executor = executor(
            "moved-after-proof",
            generation = snapshots(observed, GenerationSnapshot(9L, "service-1")),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerifiedAt(observed) }
        )

        assertEquals(ActionOutcomeState.UNCERTAIN, executor.execute(action()).state)
    }

    @Test
    fun exact_no_effect_proof_is_retryable_but_unstamped_legacy_success_is_not_monotonic_success() {
        val observed = GenerationSnapshot(8L, "service-1")
        val noEffect = executor(
            "no-effect-proof",
            generation = snapshots(observed, observed),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.NoEffectVerifiedAt(observed) }
        ).execute(action())
        val legacy = executor(
            "legacy-proof",
            generation = snapshots(observed, observed),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerified }
        ).execute(action())

        assertEquals(ActionOutcomeState.FAILED_NO_EFFECT, noEffect.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, legacy.state)
    }

    @Test
    fun production_policy_rejects_bare_effect_and_no_effect_at_exact_prepared_snapshot() {
        val prepared = GenerationSnapshot(7L, "service-1")
        val bareEffect = executor(
            "bare-effect-exact",
            generation = snapshots(prepared, prepared),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerified }
        ).execute(action())
        val bareNoEffect = executor(
            "bare-no-effect-exact",
            generation = snapshots(prepared, prepared),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.NoEffectVerified }
        ).execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, bareEffect.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, bareNoEffect.state)
    }

    @Test
    fun stamped_proof_rejects_observed_regression_and_service_change() {
        val regressed = GenerationSnapshot(6L, "service-1")
        val regression = executor(
            "proof-regression",
            generation = snapshots(GenerationSnapshot(7L, "service-1"), regressed),
            verifier = OutcomeVerifier { _, _ -> VerificationResult.EffectVerifiedAt(regressed) }
        ).execute(action())
        var verifierCalls = 0
        val serviceChanged = executor(
            "proof-service-change",
            generation = snapshots(GenerationSnapshot(8L, "service-2")),
            verifier = OutcomeVerifier { _, _ ->
                verifierCalls += 1
                VerificationResult.EffectVerifiedAt(GenerationSnapshot(8L, "service-2"))
            }
        ).execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, regression.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, serviceChanged.state)
        assertEquals(0, verifierCalls)
    }

    @Test
    fun legacy_exact_policy_rejects_stamped_results_newer_than_prepared_snapshot() {
        val prepared = GenerationSnapshot(7L, "service-1")
        val observed = GenerationSnapshot(8L, "service-1")
        val states = listOf<VerificationResult>(
            VerificationResult.EffectVerifiedAt(observed),
            VerificationResult.NoEffectVerifiedAt(observed)
        ).mapIndexed { index, verification ->
            SingleDispatchExecutor(
                store = ActionLedgerStore(temporary.newFolder("legacy-exact-stamped-$index")),
                dispatcher = ActionDispatcher { DispatchReceipt.accepted(100L) },
                verifier = OutcomeVerifier { _, _ -> verification },
                clock = { 100L },
                generation = snapshots(prepared, observed)
            ).execute(action()).state
        }

        assertEquals(
            listOf(ActionOutcomeState.UNCERTAIN, ActionOutcomeState.UNCERTAIN),
            states
        )
    }

    private fun executor(
        name: String,
        generation: () -> GenerationSnapshot?,
        verifier: OutcomeVerifier
    ) = SingleDispatchExecutor(
        store = ActionLedgerStore(temporary.newFolder(name)),
        dispatcher = ActionDispatcher { DispatchReceipt.accepted(100L) },
        verifier = verifier,
        clock = { 100L },
        generation = generation,
        postDispatchGenerationPolicy = ProductionPostDispatchGenerationPolicy
    )

    private fun action(): PreparedAction {
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
            "run-1",
            "step-1",
            1,
            7L,
            "service-1",
            ResolverKind.DIRECT,
            DirectPayload(DirectAction.BACK, evidence = evidence)
        )
    }

    private fun snapshots(vararg values: GenerationSnapshot): () -> GenerationSnapshot? {
        val iterator = values.iterator()
        return { if (iterator.hasNext()) iterator.next() else values.lastOrNull() }
    }
}
