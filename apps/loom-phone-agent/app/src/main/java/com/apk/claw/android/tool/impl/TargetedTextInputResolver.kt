package com.apk.claw.android.tool.impl

import com.apk.claw.android.comment.UiBounds
import java.util.Locale

data class TextInputTargetSpec(
    val packageName: String = "",
    val resourceId: String = "",
    val textHint: String = "",
    val boundsHint: UiBounds? = null,
    val requireFocused: Boolean = false,
    val expectedExistingText: String? = null
)

data class TextInputNodeSnapshot(
    val index: Int,
    val packageName: String,
    val resourceId: String,
    val className: String,
    val text: String,
    val description: String,
    val bounds: UiBounds,
    val editable: Boolean,
    val focused: Boolean,
    val visible: Boolean,
    val enabled: Boolean
)

sealed interface TextInputResolution {
    data class Unique(val node: TextInputNodeSnapshot) : TextInputResolution
    data class Ambiguous(val candidates: List<TextInputNodeSnapshot>) : TextInputResolution
    data object NotFound : TextInputResolution
}

object TargetedTextInputResolver {
    fun resolve(
        spec: TextInputTargetSpec,
        nodes: List<TextInputNodeSnapshot>
    ): TextInputResolution {
        val candidates = nodes
            .asSequence()
            .filter { it.visible && it.enabled && it.editable }
            .filter { isEditableClass(it.className) }
            .filter { spec.packageName.isBlank() || it.packageName == spec.packageName }
            .filter { spec.resourceId.isBlank() || it.resourceId == spec.resourceId }
            .filter { !spec.requireFocused || it.focused }
            .filter { spec.expectedExistingText == null || it.text == spec.expectedExistingText }
            .map { ScoredNode(it, score(spec, it)) }
            .sortedByDescending { it.score }
            .toList()

        if (candidates.isEmpty()) return TextInputResolution.NotFound

        val best = candidates.first()
        val equallyRanked = candidates.takeWhile { it.score == best.score }
        if (equallyRanked.size != 1) {
            return TextInputResolution.Ambiguous(equallyRanked.map { it.node })
        }
        return TextInputResolution.Unique(best.node)
    }

    private fun isEditableClass(className: String): Boolean {
        val normalized = className.lowercase(Locale.ROOT)
        return normalized.isBlank() ||
            normalized.contains("edittext") ||
            normalized.contains("textfield") ||
            normalized.contains("textinput")
    }

    private fun score(spec: TextInputTargetSpec, node: TextInputNodeSnapshot): Int {
        var score = 0
        if (node.focused) score += FOCUSED_SCORE
        if (spec.resourceId.isNotBlank() && node.resourceId == spec.resourceId) {
            score += RESOURCE_ID_SCORE
        }
        if (spec.textHint.isNotBlank() && node.searchableText().contains(spec.textHint.lowercase(Locale.ROOT))) {
            score += TEXT_HINT_SCORE
        }
        val boundsHint = spec.boundsHint
        if (boundsHint != null && node.bounds.intersectionArea(boundsHint) > 0L) {
            score += BOUNDS_SCORE
        }
        return score
    }

    private fun TextInputNodeSnapshot.searchableText(): String =
        "$text $description $resourceId".lowercase(Locale.ROOT)

    private data class ScoredNode(val node: TextInputNodeSnapshot, val score: Int)

    private const val RESOURCE_ID_SCORE = 100
    private const val TEXT_HINT_SCORE = 40
    private const val BOUNDS_SCORE = 20
    private const val FOCUSED_SCORE = 10
}
