package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverPolicy

enum class EvidenceCaptureMode {
    TREE_ONLY,
    FULL_FRAME
}

internal data class PostEvidencePlan(
    val initial: FreshnessRequirement,
    val allowFrameEscalation: Boolean
)

internal object HybridEvidencePolicy {
    fun preResolution(
        step: RpaStep,
        lightTreeAuthorized: Boolean,
        capturedAfter: Long
    ): FreshnessRequirement {
        val frameRequired = !lightTreeAuthorized ||
            step.resolverPolicy == ResolverPolicy.DIRECT ||
            step.resolverPolicy in setOf(ResolverPolicy.VISION_REQUIRED, ResolverPolicy.DUAL_CONFIRM) ||
            step.preCheckpoint?.perceptualHash != null ||
            step.preCheckpoint?.expectedDisplayTransform != null
        return if (frameRequired) {
            FreshnessRequirement.AuthorizeAfter(capturedAfter)
        } else {
            FreshnessRequirement.TreeRead
        }
    }

    fun postVerification(
        payload: ProductionRuntimePayload,
        dispatchedAt: Long,
        lightTreeAuthorized: Boolean
    ): PostEvidencePlan {
        val checkpoint = payload.postCheckpoint()
        val frameRequired = !lightTreeAuthorized ||
            payload is VisualDispatchPayload ||
            checkpoint?.perceptualHash != null ||
            checkpoint?.expectedDisplayTransform != null
        return if (frameRequired) {
            PostEvidencePlan(FreshnessRequirement.AuthorizeAfter(dispatchedAt), false)
        } else {
            PostEvidencePlan(FreshnessRequirement.TreeAfter(dispatchedAt), true)
        }
    }
}
