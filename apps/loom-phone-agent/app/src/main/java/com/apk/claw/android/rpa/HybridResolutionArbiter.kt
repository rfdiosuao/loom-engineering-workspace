package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.ResolverPolicy

fun interface SemanticChannel {
    fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution
}

fun interface VisualChannel {
    fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution
}

class ResolutionEvidence private constructor(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val packageName: String,
    val windowId: Int,
    val frameId: String? = null,
    val frameSource: String? = null,
    val frameAgeMs: Long? = null,
    @Transient private val expectedServiceIdentity: ServiceIdentityBinding?
) {
    internal fun matches(current: UiEvidence): Boolean =
        uiGeneration == current.uiGeneration &&
            serviceGeneration == current.serviceGeneration &&
            packageName == current.packageName &&
            windowId == current.windowId &&
            current.sameServiceIdentity(expectedServiceIdentity)

    internal fun sameRuntimeBoundary(other: ResolutionEvidence): Boolean =
        uiGeneration == other.uiGeneration &&
            serviceGeneration == other.serviceGeneration &&
            packageName == other.packageName &&
            windowId == other.windowId &&
            expectedServiceIdentity?.sameService(other.expectedServiceIdentity) == true

    companion object {
        internal fun from(evidence: UiEvidence): ResolutionEvidence = ResolutionEvidence(
            uiGeneration = evidence.uiGeneration,
            serviceGeneration = evidence.serviceGeneration,
            packageName = evidence.packageName,
            windowId = evidence.windowId,
            frameId = evidence.frameId,
            frameSource = evidence.frameSource,
            frameAgeMs = evidence.frameAgeMs,
            expectedServiceIdentity = evidence.captureServiceIdentity()
        )
    }
}

data class CoordinateCheckpointProof(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val frameId: String,
    val frameSource: String,
    val frameAgeMs: Long,
    val packageName: String,
    val windowId: Int,
    val transform: DisplayTransform,
    val expectedFingerprint: String,
    val actualFingerprint: String
)

data class ResolutionMetrics(
    val treeSnapshotMs: Long = 0L,
    val treeLookupMs: Long = 0L,
    val nodesVisited: Int = 0,
    val captureMs: Long = 0L,
    val matchMs: Long = 0L
) {
    fun nonnegative(): ResolutionMetrics = copy(
        treeSnapshotMs = treeSnapshotMs.coerceAtLeast(0L),
        treeLookupMs = treeLookupMs.coerceAtLeast(0L),
        nodesVisited = nodesVisited.coerceAtLeast(0),
        captureMs = captureMs.coerceAtLeast(0L),
        matchMs = matchMs.coerceAtLeast(0L)
    )
}

sealed interface Resolution {
    data class Ready(
        val payload: DispatchPayload,
        val resolverUsed: ResolverKind,
        val evidence: ResolutionEvidence,
        val confidence: Float = 1f,
        val metrics: ResolutionMetrics = ResolutionMetrics(),
        val coordinateProof: CoordinateCheckpointProof? = null
    ) : Resolution

    data class Missing(val resolver: ResolverKind) : Resolution
    data class Ambiguous(val resolver: ResolverKind, val count: Int) : Resolution
    data class Blocked(val errorCode: String) : Resolution
    data class Unsafe(val errorCode: String) : Resolution
    data class Handoff(val errorCode: String) : Resolution
}

enum class DirectAction(val wireName: String) {
    OPEN_APP("open_app"),
    WAIT_STABLE("wait_stable"),
    ASSERT_PACKAGE("assert_package"),
    BACK("back"),
    HOME("home"),
    WAIT("wait"),
    FINISH("finish");

    companion object {
        fun fromWireName(value: String): DirectAction? = entries.firstOrNull { it.wireName == value }
    }
}

interface BoundedDispatchPayload : DispatchPayload {
    val bounds: IntRect
}

class HybridResolutionArbiter(
    private val semantic: SemanticChannel,
    private val visual: VisualChannel,
    private val apiLevel: Int
) {
    fun resolve(step: RpaStep, evidence: UiEvidence): Resolution {
        invalidEvidence(evidence)?.let { return it }
        return when (step.resolverPolicy) {
            ResolverPolicy.DUAL_CONFIRM -> resolveDual(step, evidence)
            else -> resolveOrdered(step, evidence)
        }
    }

    fun resolveTreeSemantic(step: RpaStep, evidence: UiEvidence): Resolution {
        invalidEvidence(evidence)?.let { return it }
        if (step.resolverPolicy != ResolverPolicy.TREE_PREFERRED) {
            return Resolution.Blocked("tree_semantic_policy_mismatch")
        }
        return resolveOrderedKinds(step, evidence, SEMANTIC_ORDER)
    }

    fun resolveTreeVisualFallback(step: RpaStep, evidence: UiEvidence): Resolution {
        invalidEvidence(evidence)?.let { return it }
        if (step.resolverPolicy != ResolverPolicy.TREE_PREFERRED) {
            return Resolution.Blocked("tree_visual_policy_mismatch")
        }
        return resolveOrderedKinds(step, evidence, TREE_VISUAL_ORDER)
    }

    private fun resolveOrdered(step: RpaStep, evidence: UiEvidence): Resolution {
        val ordered = when (step.resolverPolicy) {
            ResolverPolicy.DIRECT -> listOf(ResolverKind.DIRECT)
            ResolverPolicy.TREE_PREFERRED -> TREE_PREFERRED_ORDER
            ResolverPolicy.VISION_REQUIRED -> listOf(ResolverKind.VISUAL_ANCHOR)
            ResolverPolicy.DUAL_CONFIRM -> error("dual confirmation is resolved separately")
        }
        return resolveOrderedKinds(step, evidence, ordered)
    }

    private fun resolveOrderedKinds(
        step: RpaStep,
        evidence: UiEvidence,
        ordered: List<ResolverKind>
    ): Resolution {
        var lastMissing: Resolution.Missing? = null
        for (kind in ordered) {
            if (kind !in step.allowedResolvers) continue
            val candidate = resolveKind(kind, step, evidence)
            if (candidate is Resolution.Missing) {
                lastMissing = candidate
                continue
            }
            return authorize(kind, candidate, step, evidence)
        }
        return lastMissing ?: Resolution.Missing(ordered.first())
    }

    private fun invalidEvidence(evidence: UiEvidence): Resolution.Blocked? =
        if (evidence.uiGeneration < 0L || evidence.serviceGeneration.isBlank()) {
            Resolution.Blocked(ERROR_STALE_RESOLUTION_EVIDENCE)
        } else null

    private fun resolveDual(step: RpaStep, evidence: UiEvidence): Resolution {
        val declaredSemantic = SEMANTIC_ORDER.filter { it in step.allowedResolvers }
        if (declaredSemantic.isEmpty() || ResolverKind.VISUAL_ANCHOR !in step.allowedResolvers) {
            return Resolution.Handoff("dual_confirmation_not_declared")
        }
        if (ResolverKind.VISUAL_ANCHOR !in step.validatedResolvers ||
            declaredSemantic.none { it in step.validatedResolvers }
        ) {
            return Resolution.Blocked(ERROR_FALLBACK_NOT_VALIDATED)
        }

        var semanticReady: Resolution.Ready? = null
        for (kind in declaredSemantic) {
            val candidate = resolveKind(kind, step, evidence)
            if (candidate is Resolution.Missing) continue
            val authorized = authorize(kind, candidate, step, evidence)
            if (authorized !is Resolution.Ready) return authorized
            semanticReady = authorized
            break
        }
        val tree = semanticReady ?: return Resolution.Handoff("dual_confirmation_missing")
        val visualCandidate = resolveKind(ResolverKind.VISUAL_ANCHOR, step, evidence)
        if (visualCandidate is Resolution.Missing) return Resolution.Handoff("dual_confirmation_missing")
        val image = authorize(ResolverKind.VISUAL_ANCHOR, visualCandidate, step, evidence)
        if (image !is Resolution.Ready) return image
        if (!tree.evidence.sameRuntimeBoundary(image.evidence) ||
            tree.evidence.frameId != image.evidence.frameId ||
            tree.evidence.frameSource != image.evidence.frameSource ||
            tree.evidence.frameAgeMs != image.evidence.frameAgeMs ||
            image.evidence.frameSource != FRESH_FRAME_SOURCE ||
            image.evidence.frameId.isNullOrBlank() ||
            image.evidence.frameAgeMs == null || image.evidence.frameAgeMs < 0L
        ) {
            return Resolution.Blocked(ERROR_STALE_RESOLUTION_EVIDENCE)
        }
        if (!targetsOverlap(tree.payload, image.payload)) {
            return Resolution.Unsafe("resolver_disagreement")
        }
        return tree.copy(
            confidence = minOf(tree.confidence, image.confidence),
            metrics = combineMetrics(tree.metrics, image.metrics)
        )
    }

    private fun resolveKind(
        kind: ResolverKind,
        step: RpaStep,
        evidence: UiEvidence
    ): Resolution {
        if (kind == ResolverKind.EPHEMERAL_REF) {
            return Resolution.Blocked("ephemeral_ref_not_production_safe")
        }
        if (kind in VISUAL_RESOLVERS && apiLevel < 30) {
            return Resolution.Handoff("visual_capture_unsupported")
        }
        return when (kind) {
            ResolverKind.DIRECT -> {
                val action = DirectAction.fromWireName(step.action)
                    ?: return Resolution.Unsafe("direct_action_unsupported")
                val payload = DirectPayload.from(step, evidence, action)
                    ?: return Resolution.Handoff("direct_params_invalid")
                Resolution.Ready(
                    payload = payload,
                    resolverUsed = ResolverKind.DIRECT,
                    evidence = ResolutionEvidence.from(evidence)
                )
            }
            ResolverKind.EPHEMERAL_REF,
            ResolverKind.RESOURCE_ID,
            ResolverKind.CONTENT_DESCRIPTION,
            ResolverKind.TEXT_CLASS,
            ResolverKind.STRUCTURAL -> semantic.resolve(kind, step, evidence)
            ResolverKind.VISUAL_ANCHOR,
            ResolverKind.NORMALIZED_COORDINATE -> visual.resolve(kind, step, evidence)
        }
    }

    private fun authorize(
        kind: ResolverKind,
        candidate: Resolution,
        step: RpaStep,
        evidence: UiEvidence
    ): Resolution {
        if (candidate !is Resolution.Ready) return candidate
        if (candidate.resolverUsed != kind) return Resolution.Blocked("resolver_kind_mismatch")
        if (!matches(candidate.evidence, evidence)) {
            return Resolution.Blocked(ERROR_STALE_RESOLUTION_EVIDENCE)
        }
        if (kind !in step.validatedResolvers) {
            return Resolution.Blocked(ERROR_FALLBACK_NOT_VALIDATED)
        }
        if (kind in VISUAL_RESOLVERS &&
            ((candidate.payload as? BoundedDispatchPayload)?.bounds?.let(::safeArea) == null)
        ) {
            return Resolution.Blocked("resolver_bounds_invalid")
        }
        if (kind in VISUAL_RESOLVERS && !hasFreshVisualEvidence(candidate.evidence, evidence)) {
            return Resolution.Blocked("visual_evidence_not_fresh")
        }
        if (kind == ResolverKind.NORMALIZED_COORDINATE &&
            !hasMatchingCoordinateProof(candidate.coordinateProof, step, evidence)
        ) {
            return Resolution.Blocked("coordinate_checkpoint_unproved")
        }
        if (!candidate.confidence.isFinite() || candidate.confidence !in 0f..1f) {
            return Resolution.Blocked("resolver_confidence_invalid")
        }
        return candidate.copy(metrics = candidate.metrics.nonnegative())
    }

    private fun matches(resolved: ResolutionEvidence, current: UiEvidence): Boolean =
        resolved.matches(current)

    private fun hasFreshVisualEvidence(
        resolved: ResolutionEvidence,
        current: UiEvidence
    ): Boolean = resolved.frameSource == FRESH_FRAME_SOURCE &&
        !resolved.frameId.isNullOrBlank() &&
        resolved.frameAgeMs != null && resolved.frameAgeMs >= 0L &&
        resolved.frameId == current.frameId &&
        resolved.frameSource == current.frameSource &&
        resolved.frameAgeMs == current.frameAgeMs &&
        current.frameCapturedAt != null && current.frameCapturedAt <= current.capturedAt

    private fun hasMatchingCoordinateProof(
        proof: CoordinateCheckpointProof?,
        step: RpaStep,
        evidence: UiEvidence
    ): Boolean {
        val checkpoint = step.preCheckpoint ?: return false
        val expectedWindowId = checkpoint.expectedWindowId ?: return false
        val expectedTransform = checkpoint.expectedDisplayTransform ?: return false
        val maximumDistance = checkpoint.maximumHammingDistance
        if (proof == null || maximumDistance !in 0..MAX_COORDINATE_FINGERPRINT_DISTANCE) return false
        if (!PerceptualFingerprint.isValid(proof.expectedFingerprint) ||
            !PerceptualFingerprint.isValid(proof.actualFingerprint)
        ) return false
        val distance = PerceptualFingerprint.distance(proof.expectedFingerprint, proof.actualFingerprint)
            ?: return false
        return proof.uiGeneration == evidence.uiGeneration &&
            proof.serviceGeneration == evidence.serviceGeneration &&
            proof.frameId.isNotBlank() && proof.frameId == evidence.frameId &&
            proof.frameSource == FRESH_FRAME_SOURCE &&
            proof.frameSource == evidence.frameSource &&
            proof.frameAgeMs >= 0L && proof.frameAgeMs == evidence.frameAgeMs &&
            proof.packageName == evidence.packageName &&
            (checkpoint.expectedPackage == null ||
                checkpoint.expectedPackage == evidence.packageName &&
                checkpoint.expectedPackage == proof.packageName) &&
            proof.windowId == evidence.windowId &&
            proof.windowId == expectedWindowId &&
            proof.transform == evidence.transform &&
            expectedTransform.displayId == evidence.transform.displayId &&
            expectedTransform.widthPx == evidence.transform.widthPx &&
            expectedTransform.heightPx == evidence.transform.heightPx &&
            expectedTransform.screenshotWidthPx == evidence.transform.screenshotWidthPx &&
            expectedTransform.screenshotHeightPx == evidence.transform.screenshotHeightPx &&
            expectedTransform.rotation == evidence.transform.rotation &&
            expectedTransform.densityDpi == evidence.transform.densityDpi &&
            expectedTransform.insetLeft == evidence.transform.insetLeft &&
            expectedTransform.insetTop == evidence.transform.insetTop &&
            expectedTransform.insetRight == evidence.transform.insetRight &&
            expectedTransform.insetBottom == evidence.transform.insetBottom &&
            proof.expectedFingerprint == checkpoint.perceptualHash &&
            distance <= maximumDistance
    }

    companion object {
        const val ERROR_FALLBACK_NOT_VALIDATED = "fallback_not_validated"
        const val ERROR_STALE_RESOLUTION_EVIDENCE = "stale_resolution_evidence"

        private const val FRESH_FRAME_SOURCE = "fresh"
        private const val MAX_COORDINATE_FINGERPRINT_DISTANCE = 64
        private val SEMANTIC_ORDER = listOf(
            ResolverKind.EPHEMERAL_REF,
            ResolverKind.RESOURCE_ID,
            ResolverKind.CONTENT_DESCRIPTION,
            ResolverKind.TEXT_CLASS,
            ResolverKind.STRUCTURAL
        )
        private val TREE_PREFERRED_ORDER = SEMANTIC_ORDER + listOf(
            ResolverKind.VISUAL_ANCHOR,
            ResolverKind.NORMALIZED_COORDINATE
        )
        private val TREE_VISUAL_ORDER = listOf(
            ResolverKind.VISUAL_ANCHOR,
            ResolverKind.NORMALIZED_COORDINATE
        )
        private val VISUAL_RESOLVERS = setOf(
            ResolverKind.VISUAL_ANCHOR,
            ResolverKind.NORMALIZED_COORDINATE
        )
    }
}

fun targetsOverlap(first: DispatchPayload, second: DispatchPayload): Boolean {
    val firstBounds = (first as? BoundedDispatchPayload)?.bounds ?: return false
    val secondBounds = (second as? BoundedDispatchPayload)?.bounds ?: return false
    val firstArea = safeArea(firstBounds) ?: return false
    val secondArea = safeArea(secondBounds) ?: return false
    val overlapWidth = (
        minOf(firstBounds.right.toLong(), secondBounds.right.toLong()) -
            maxOf(firstBounds.left.toLong(), secondBounds.left.toLong())
        ).coerceAtLeast(0L)
    val overlapHeight = (
        minOf(firstBounds.bottom.toLong(), secondBounds.bottom.toLong()) -
            maxOf(firstBounds.top.toLong(), secondBounds.top.toLong())
        ).coerceAtLeast(0L)
    val overlapArea = Math.multiplyExact(overlapWidth, overlapHeight)
    val smallerArea = minOf(firstArea, secondArea)
    val halfRoundedUp = smallerArea / 2L + smallerArea % 2L
    return smallerArea > 0L && overlapArea >= halfRoundedUp
}

private fun safeArea(bounds: IntRect): Long? {
    if (bounds.left < 0 || bounds.top < 0 || bounds.right <= bounds.left || bounds.bottom <= bounds.top) {
        return null
    }
    val width = bounds.right.toLong() - bounds.left.toLong()
    val height = bounds.bottom.toLong() - bounds.top.toLong()
    return runCatching { Math.multiplyExact(width, height) }.getOrNull()
}

private fun combineMetrics(first: ResolutionMetrics, second: ResolutionMetrics): ResolutionMetrics = ResolutionMetrics(
    treeSnapshotMs = maxOf(first.treeSnapshotMs, second.treeSnapshotMs),
    treeLookupMs = saturatedMetricAdd(first.treeLookupMs, second.treeLookupMs),
    nodesVisited = saturatedMetricAdd(first.nodesVisited, second.nodesVisited),
    captureMs = maxOf(first.captureMs, second.captureMs),
    matchMs = saturatedMetricAdd(first.matchMs, second.matchMs)
).nonnegative()

private fun saturatedMetricAdd(first: Long, second: Long): Long = when {
    first < 0L || second < 0L -> 0L
    first > Long.MAX_VALUE - second -> Long.MAX_VALUE
    else -> first + second
}

private fun saturatedMetricAdd(first: Int, second: Int): Int = when {
    first < 0 || second < 0 -> 0
    first > Int.MAX_VALUE - second -> Int.MAX_VALUE
    else -> first + second
}
