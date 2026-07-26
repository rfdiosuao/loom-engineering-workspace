package com.apk.claw.android.comment

data class UiBounds(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int
) {
    val area: Long
        get() = (right - left).coerceAtLeast(0).toLong() *
            (bottom - top).coerceAtLeast(0).toLong()

    fun intersectionArea(other: UiBounds): Long {
        val width = (minOf(right, other.right) - maxOf(left, other.left)).coerceAtLeast(0)
        val height = (minOf(bottom, other.bottom) - maxOf(top, other.top)).coerceAtLeast(0)
        return width.toLong() * height.toLong()
    }
}

data class CommentUiNode(
    val resourceId: String,
    val className: String,
    val text: String,
    val description: String,
    val packageName: String,
    val bounds: UiBounds,
    val clickable: Boolean,
    val editable: Boolean,
    val focused: Boolean,
    val visible: Boolean,
    val enabled: Boolean
)

data class CommentPageObservation(
    val packageName: String,
    val nodes: List<CommentUiNode>
)

enum class CommentPageState {
    VIDEO,
    COMMENT_SHEET,
    INPUT_FOCUSED,
    BLOCKED,
    OTHER_APP,
    UNKNOWN
}
