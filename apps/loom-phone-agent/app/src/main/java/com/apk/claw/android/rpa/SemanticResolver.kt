package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector

sealed interface SemanticResolution {
    data class Unique(
        val node: CompactNode,
        val matchedBy: ResolverKind,
        val generation: Long,
        val serviceGeneration: String = "",
        val expectedClassName: String? = null
    ) : SemanticResolution

    data class Missing(val attempted: List<ResolverKind>) : SemanticResolution

    data class Ambiguous(val matchedBy: ResolverKind, val count: Int) : SemanticResolution
}

object SemanticResolver {
    fun resolve(snapshot: CompactTreeSnapshot, selector: SemanticSelector): SemanticResolution {
        val attempts = buildList<Pair<ResolverKind, (CompactNode) -> Boolean>> {
            selector.resourceId?.takeIf { it.isNotBlank() }?.let { resourceId ->
                add(ResolverKind.RESOURCE_ID to { node -> node.resourceId == resourceId })
            }
            selector.contentDescription?.takeIf { it.isNotBlank() }?.let { description ->
                add(ResolverKind.CONTENT_DESCRIPTION to { node -> node.description == description })
            }
            selector.text?.takeIf { it.isNotBlank() }?.let { text ->
                add(ResolverKind.TEXT_CLASS to { node -> node.text == text })
            }
        }

        for ((kind, semanticMatch) in attempts) {
            val matches = snapshot.nodes.filter { node ->
                node.visible &&
                    node.enabled &&
                    packageMatches(snapshot, selector, node) &&
                    classMatches(selector, node) &&
                    semanticMatch(node)
            }
            if (matches.size == 1) {
                return SemanticResolution.Unique(
                    node = matches.single(),
                    matchedBy = kind,
                    generation = snapshot.uiGeneration,
                    serviceGeneration = snapshot.serviceGeneration,
                    expectedClassName = selector.className?.takeIf { it.isNotBlank() }
                )
            }
            if (matches.size > 1) {
                return SemanticResolution.Ambiguous(kind, matches.size)
            }
        }
        return SemanticResolution.Missing(attempts.map { it.first })
    }

    private fun packageMatches(
        snapshot: CompactTreeSnapshot,
        selector: SemanticSelector,
        node: CompactNode
    ): Boolean {
        if (snapshot.packageName.isNotBlank() && node.packageName != snapshot.packageName) return false
        return selector.packageName?.takeIf { it.isNotBlank() }?.let { it == node.packageName } != false
    }

    private fun classMatches(selector: SemanticSelector, node: CompactNode): Boolean {
        return selector.className
            ?.takeIf { it.isNotBlank() }
            ?.let { semanticClassNamesMatch(it, node.className) } != false
    }
}

internal fun semanticClassNamesMatch(expected: String, actual: String): Boolean {
    if (expected.contains('.')) return expected == actual
    return expected == actual.substringAfterLast('.')
}
