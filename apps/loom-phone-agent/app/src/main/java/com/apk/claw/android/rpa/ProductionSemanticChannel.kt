package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector

class ProductionSemanticChannel(
    private val clock: () -> Long = System::currentTimeMillis
) : SemanticChannel {
    override fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution {
        if (kind == ResolverKind.STRUCTURAL) {
            return Resolution.Handoff(ERROR_STRUCTURAL_PATH_UNVERIFIABLE)
        }
        if (kind !in SUPPORTED_RESOLVERS) {
            return Resolution.Handoff(ERROR_SEMANTIC_RESOLVER_UNAVAILABLE)
        }
        if (step.action != SUPPORTED_ACTION) {
            return Resolution.Handoff(ERROR_ACTION_ADAPTER_UNAVAILABLE)
        }
        if (!evidence.hasRuntimeServiceIdentity() || evidence.windowId < 0) {
            return Resolution.Handoff(ERROR_COMPACT_TREE_INVALID)
        }
        val selector = step.semanticSelector ?: return Resolution.Handoff(ERROR_COMPACT_TREE_INVALID)
        val snapshot = CompactTreeSnapshot.from(evidence)
            ?: return Resolution.Handoff(ERROR_COMPACT_TREE_INVALID)
        if (snapshot.uiGeneration != evidence.uiGeneration ||
            snapshot.serviceGeneration != evidence.serviceGeneration ||
            snapshot.packageName != evidence.packageName ||
            snapshot.windowId != evidence.windowId
        ) {
            return Resolution.Handoff(ERROR_COMPACT_TREE_INVALID)
        }

        val startedAt = safeNow()
        val resolution = SemanticResolver.resolve(snapshot, selector.forResolver(kind))
        val lookupMs = elapsed(startedAt, safeNow())
        return when (resolution) {
            is SemanticResolution.Unique -> {
                if (resolution.matchedBy != kind || !isBounded(resolution.node.bounds, evidence.transform)) {
                    Resolution.Handoff(ERROR_SEMANTIC_BOUNDS_INVALID)
                } else {
                    Resolution.Ready(
                        payload = SemanticDispatchPayload(
                            resolution = resolution,
                            bounds = resolution.node.bounds,
                            evidence = evidence,
                            preCheckpoint = step.preCheckpoint,
                            postCheckpoint = step.postCheckpoint
                        ),
                        resolverUsed = kind,
                        evidence = ResolutionEvidence.from(evidence),
                        metrics = ResolutionMetrics(
                            treeSnapshotMs = evidence.treeSnapshotMs,
                            treeLookupMs = lookupMs,
                            nodesVisited = snapshot.nodes.size
                        )
                    )
                }
            }
            is SemanticResolution.Missing -> Resolution.Missing(kind)
            is SemanticResolution.Ambiguous -> Resolution.Ambiguous(kind, resolution.count)
        }
    }

    private fun SemanticSelector.forResolver(kind: ResolverKind): SemanticSelector = when (kind) {
        ResolverKind.RESOURCE_ID -> copy(
            contentDescription = null,
            text = null,
            structuralPath = emptyList()
        )
        ResolverKind.CONTENT_DESCRIPTION -> copy(
            resourceId = null,
            text = null,
            structuralPath = emptyList()
        )
        ResolverKind.TEXT_CLASS -> copy(
            resourceId = null,
            contentDescription = null,
            structuralPath = emptyList()
        )
        else -> this
    }

    private fun isBounded(bounds: IntRect, transform: DisplayTransform): Boolean =
        transform.widthPx > 0 && transform.heightPx > 0 &&
            bounds.left >= 0 && bounds.top >= 0 &&
            bounds.right > bounds.left && bounds.bottom > bounds.top &&
            bounds.right <= transform.widthPx && bounds.bottom <= transform.heightPx

    private fun safeNow(): Long = runCatching(clock).getOrDefault(0L).coerceAtLeast(0L)

    private fun elapsed(startedAt: Long, finishedAt: Long): Long = when {
        finishedAt <= startedAt -> 0L
        finishedAt - startedAt < 0L -> Long.MAX_VALUE
        else -> finishedAt - startedAt
    }

    companion object {
        const val ERROR_COMPACT_TREE_INVALID = "compact_tree_invalid"
        const val ERROR_STRUCTURAL_PATH_UNVERIFIABLE = "structural_path_unverifiable"
        const val ERROR_SEMANTIC_RESOLVER_UNAVAILABLE = "semantic_resolver_unavailable"
        const val ERROR_SEMANTIC_BOUNDS_INVALID = "semantic_bounds_invalid"
        const val ERROR_ACTION_ADAPTER_UNAVAILABLE = "action_adapter_unavailable"

        private const val SUPPORTED_ACTION = "tap_semantic"
        private val SUPPORTED_RESOLVERS = setOf(
            ResolverKind.RESOURCE_ID,
            ResolverKind.CONTENT_DESCRIPTION,
            ResolverKind.TEXT_CLASS
        )
    }
}
