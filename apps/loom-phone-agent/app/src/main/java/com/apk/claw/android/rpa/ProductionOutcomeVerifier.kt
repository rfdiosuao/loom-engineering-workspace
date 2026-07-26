package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.DisplayTransformCheckpoint
import com.apk.claw.android.workflow.SemanticSelector
import com.apk.claw.android.workflow.StepCheckpoint

internal class ProductionOutcomeVerifier(
    private val evidenceSource: HybridEvidenceSource
) : OutcomeVerifier {
    override fun verify(action: PreparedAction, dispatchedAt: Long): VerificationResult {
        val payload = action.payload as? ProductionRuntimePayload
            ?: return unknown(ERROR_PAYLOAD_UNVERIFIABLE)
        if (dispatchedAt < 0L) return unknown(ERROR_EVIDENCE_NOT_FRESH)
        val evidence = try {
            evidenceSource.capture(FreshnessRequirement.AuthorizeAfter(dispatchedAt))
        } catch (_: Throwable) {
            return unknown(ERROR_EVIDENCE_CAPTURE_FAILED)
        }
        if (evidence.capturedAt <= dispatchedAt || !payload.sameServiceIdentity(evidence)) {
            return unknown(ERROR_EVIDENCE_NOT_FRESH)
        }
        if (evidence.serviceGeneration != action.serviceGeneration ||
            evidence.uiGeneration < action.uiGeneration
        ) return unknown(ERROR_GENERATION_UNPROVED)
        val observed = GenerationSnapshot(evidence.uiGeneration, evidence.serviceGeneration)
        val direct = payload as? DirectPayload
        val post = payload.postCheckpoint() ?: direct?.implicitPostCheckpoint()
        if (post == null) {
            return if (direct?.action in READ_ONLY_DIRECT_ACTIONS) {
                VerificationResult.EffectVerifiedAt(observed)
            } else {
                unknown(ERROR_POSTCONDITION_UNDECLARED)
            }
        }

        return when (evaluate(post, evidence, dispatchedAt)) {
            CheckpointState.HOLDS -> VerificationResult.EffectVerifiedAt(observed)
            CheckpointState.UNKNOWN -> unknown(ERROR_POSTCONDITION_UNPROVED)
            CheckpointState.FAILS -> {
                val pre = payload.preCheckpoint()
                if (pre != null && evaluate(pre, evidence, dispatchedAt) == CheckpointState.HOLDS) {
                    VerificationResult.NoEffectVerifiedAt(observed)
                } else {
                    unknown(ERROR_NO_EFFECT_UNPROVED)
                }
            }
        }
    }

    private fun evaluate(
        checkpoint: StepCheckpoint,
        evidence: UiEvidence,
        dispatchedAt: Long
    ): CheckpointState {
        val conditions = ArrayList<CheckpointState>(6)
        checkpoint.expectedPackage?.let { expected ->
            conditions += if (expected == evidence.packageName) CheckpointState.HOLDS else CheckpointState.FAILS
        }
        checkpoint.expectedWindowId?.let { expected ->
            conditions += if (expected == evidence.windowId) CheckpointState.HOLDS else CheckpointState.FAILS
        }
        checkpoint.expectedDisplayTransform?.let { expected ->
            conditions += if (expected.matches(evidence.transform)) CheckpointState.HOLDS else CheckpointState.FAILS
        }
        checkpoint.requiredSelector?.let { selector ->
            conditions += selectorState(selector, evidence, required = true)
        }
        checkpoint.forbiddenSelector?.let { selector ->
            conditions += selectorState(selector, evidence, required = false)
        }
        checkpoint.perceptualHash?.let { expected ->
            conditions += perceptualState(
                expected,
                checkpoint.maximumHammingDistance,
                evidence,
                dispatchedAt
            )
        }
        if (conditions.isEmpty()) return CheckpointState.UNKNOWN
        if (CheckpointState.FAILS in conditions) return CheckpointState.FAILS
        if (CheckpointState.UNKNOWN in conditions) return CheckpointState.UNKNOWN
        return CheckpointState.HOLDS
    }

    private fun selectorState(
        selector: SemanticSelector,
        evidence: UiEvidence,
        required: Boolean
    ): CheckpointState {
        if (selector.resourceId.isNullOrBlank() &&
            selector.contentDescription.isNullOrBlank() &&
            selector.text.isNullOrBlank()
        ) return CheckpointState.UNKNOWN
        val snapshot = evidence.compactTreeSnapshot() ?: return CheckpointState.UNKNOWN
        return when (SemanticResolver.resolve(snapshot, selector)) {
            is SemanticResolution.Unique -> if (required) CheckpointState.HOLDS else CheckpointState.FAILS
            is SemanticResolution.Missing -> CheckpointState.UNKNOWN
            is SemanticResolution.Ambiguous -> if (required) CheckpointState.HOLDS else CheckpointState.FAILS
        }
    }

    private fun perceptualState(
        expected: String,
        maximumDistance: Int,
        evidence: UiEvidence,
        dispatchedAt: Long
    ): CheckpointState {
        if (!PerceptualFingerprint.isValid(expected) || maximumDistance !in 0..MAX_FINGERPRINT_DISTANCE) {
            return CheckpointState.UNKNOWN
        }
        val frameCapturedAt = evidence.frameCapturedAt ?: return CheckpointState.UNKNOWN
        val frameAgeMs = evidence.frameAgeMs ?: return CheckpointState.UNKNOWN
        val plane = evidence.runtimeLumaPlane() ?: return CheckpointState.UNKNOWN
        if (evidence.frameSource != FRESH_FRAME_SOURCE || evidence.frameId.isNullOrBlank() ||
            frameCapturedAt <= dispatchedAt || frameCapturedAt > evidence.capturedAt ||
            frameAgeMs < 0L || frameAgeMs != evidence.capturedAt - frameCapturedAt ||
            plane.width != evidence.transform.screenshotWidthPx ||
            plane.height != evidence.transform.screenshotHeightPx
        ) return CheckpointState.UNKNOWN
        val actual = PerceptualFingerprint.compute(plane) ?: return CheckpointState.UNKNOWN
        val distance = PerceptualFingerprint.distance(expected, actual) ?: return CheckpointState.UNKNOWN
        return if (distance <= maximumDistance) CheckpointState.HOLDS else CheckpointState.FAILS
    }

    private fun DirectPayload.implicitPostCheckpoint(): StepCheckpoint? = when (action) {
        DirectAction.OPEN_APP, DirectAction.ASSERT_PACKAGE -> StepCheckpoint(expectedPackage = packageName)
        else -> null
    }

    private fun DisplayTransformCheckpoint.matches(actual: DisplayTransform): Boolean =
        displayId == actual.displayId &&
            widthPx == actual.widthPx &&
            heightPx == actual.heightPx &&
            screenshotWidthPx == actual.screenshotWidthPx &&
            screenshotHeightPx == actual.screenshotHeightPx &&
            rotation == actual.rotation &&
            densityDpi == actual.densityDpi &&
            insetLeft == actual.insetLeft &&
            insetTop == actual.insetTop &&
            insetRight == actual.insetRight &&
            insetBottom == actual.insetBottom

    private fun unknown(errorCode: String) = VerificationResult.Unknown(errorCode)

    private enum class CheckpointState { HOLDS, FAILS, UNKNOWN }

    companion object {
        const val ERROR_PAYLOAD_UNVERIFIABLE = "verification_payload_unverifiable"
        const val ERROR_EVIDENCE_CAPTURE_FAILED = "verification_capture_failed"
        const val ERROR_EVIDENCE_NOT_FRESH = "verification_evidence_not_fresh"
        const val ERROR_GENERATION_UNPROVED = "verification_generation_unproved"
        const val ERROR_POSTCONDITION_UNDECLARED = "postcondition_undeclared"
        const val ERROR_POSTCONDITION_UNPROVED = "postcondition_unproved"
        const val ERROR_NO_EFFECT_UNPROVED = "no_effect_unproved"

        private const val FRESH_FRAME_SOURCE = "fresh"
        private const val MAX_FINGERPRINT_DISTANCE = 64
        private val READ_ONLY_DIRECT_ACTIONS = setOf(
            DirectAction.WAIT,
            DirectAction.ASSERT_PACKAGE,
            DirectAction.FINISH
        )
    }
}
