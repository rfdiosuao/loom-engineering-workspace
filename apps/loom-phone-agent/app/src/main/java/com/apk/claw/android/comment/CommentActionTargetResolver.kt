package com.apk.claw.android.comment

import java.util.Locale

enum class CommentActionKind {
    OPEN_COMPOSER,
    SEND
}

sealed interface CommentActionTargetResolution {
    data class Unique(val node: CommentUiNode) : CommentActionTargetResolution
    data class Ambiguous(val nodes: List<CommentUiNode>) : CommentActionTargetResolution
    data object NotFound : CommentActionTargetResolution
}

object CommentActionTargetResolver {
    fun resolve(
        kind: CommentActionKind,
        nodes: List<CommentUiNode>
    ): CommentActionTargetResolution {
        val candidates = nodes
            .asSequence()
            .filter { it.visible && it.enabled && it.clickable && !it.editable }
            .filter { node -> matches(kind, node) }
            .map { node -> Scored(node, score(kind, node)) }
            .sortedByDescending { it.score }
            .toList()
        if (candidates.isEmpty()) return CommentActionTargetResolution.NotFound
        val topScore = candidates.first().score
        val top = candidates.takeWhile { it.score == topScore }.map { it.node }
        return if (top.size == 1) {
            CommentActionTargetResolution.Unique(top.single())
        } else {
            CommentActionTargetResolution.Ambiguous(top)
        }
    }

    private fun matches(kind: CommentActionKind, node: CommentUiNode): Boolean {
        val value = node.searchableText()
        return when (kind) {
            CommentActionKind.OPEN_COMPOSER ->
                OPEN_TERMS.any(value::contains) && SEND_TERMS.none(value::contains)
            CommentActionKind.SEND ->
                SEND_RESOURCE_TERMS.any(value::contains) || exactLabel(node) in SEND_EXACT_LABELS
        }
    }

    private fun score(kind: CommentActionKind, node: CommentUiNode): Int {
        val resource = node.resourceId.lowercase(Locale.ROOT)
        val label = exactLabel(node)
        return when (kind) {
            CommentActionKind.OPEN_COMPOSER -> when {
                resource.contains("comment") -> 100
                label in OPEN_EXACT_LABELS -> 80
                else -> 60
            }
            CommentActionKind.SEND -> when {
                SEND_RESOURCE_TERMS.any(resource::contains) -> 100
                label in SEND_EXACT_LABELS -> 80
                else -> 0
            }
        }
    }

    private fun CommentUiNode.searchableText(): String =
        "$resourceId $text $description".lowercase(Locale.ROOT)

    private fun exactLabel(node: CommentUiNode): String =
        (node.text.ifBlank { node.description }).trim().lowercase(Locale.ROOT)

    private data class Scored(val node: CommentUiNode, val score: Int)

    private val OPEN_TERMS = listOf("comment", "\u8bc4\u8bba")
    private val OPEN_EXACT_LABELS = setOf("comment", "comments", "\u8bc4\u8bba")
    private val SEND_RESOURCE_TERMS = listOf("comment_send", "comment-send", "send_comment", "send-comment")
    private val SEND_TERMS = listOf("comment_send", "comment-send", "send", "publish", "\u53d1\u9001")
    private val SEND_EXACT_LABELS = setOf("send", "publish", "\u53d1\u9001")
}
