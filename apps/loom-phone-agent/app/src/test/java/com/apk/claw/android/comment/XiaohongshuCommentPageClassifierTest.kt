package com.apk.claw.android.comment

import org.junit.Assert.assertEquals
import org.junit.Test

class XiaohongshuCommentPageClassifierTest {
    private val classifier = XiaohongshuCommentPageClassifier()

    @Test
    fun classifies_video_and_comment_sheet_as_distinct_states() {
        assertEquals(CommentPageState.VIDEO, classifier.classify(videoObservation()))
        assertEquals(CommentPageState.COMMENT_SHEET, classifier.classify(commentSheetObservation()))
    }

    @Test
    fun focused_comment_input_has_a_stronger_state_than_open_sheet() {
        val focused = commentSheetObservation().copy(
            nodes = commentSheetObservation().nodes.map { node ->
                if (node.resourceId == "comment-input") node.copy(focused = true) else node
            }
        )

        assertEquals(CommentPageState.INPUT_FOCUSED, classifier.classify(focused))
    }

    @Test
    fun one_comment_label_is_not_enough_to_invent_an_open_sheet() {
        val sparse = CommentPageObservation(
            packageName = "com.xingin.xhs",
            nodes = listOf(node(resourceId = "comment-count", text = "123 comments", clickable = true))
        )

        assertEquals(CommentPageState.UNKNOWN, classifier.classify(sparse))
    }

    @Test
    fun three_video_controls_are_enough_when_the_canvas_exposes_no_player_node() {
        val canvasVideo = CommentPageObservation(
            packageName = "com.xingin.xhs",
            nodes = listOf(
                node(resourceId = "like-count", text = "100", clickable = true),
                node(resourceId = "comment-count", text = "123 comments", clickable = true),
                node(resourceId = "share", text = "Share", clickable = true)
            )
        )

        assertEquals(CommentPageState.VIDEO, classifier.classify(canvasVideo))
    }

    @Test
    fun login_or_verification_wall_is_blocked() {
        val blocked = CommentPageObservation(
            packageName = "com.xingin.xhs",
            nodes = listOf(node(text = "Log in to continue"), node(text = "Verification code"))
        )

        assertEquals(CommentPageState.BLOCKED, classifier.classify(blocked))
    }

    @Test
    fun another_foreground_package_is_not_treated_as_xiaohongshu() {
        assertEquals(
            CommentPageState.OTHER_APP,
            classifier.classify(videoObservation().copy(packageName = "com.example.other"))
        )
    }

    private fun videoObservation() = CommentPageObservation(
        packageName = "com.xingin.xhs",
        nodes = listOf(
            node(resourceId = "video-player", className = "android.view.View"),
            node(resourceId = "like-count", text = "100", clickable = true),
            node(resourceId = "comment-count", text = "123 comments", clickable = true),
            node(resourceId = "share", text = "Share", clickable = true)
        )
    )

    private fun commentSheetObservation() = CommentPageObservation(
        packageName = "com.xingin.xhs",
        nodes = listOf(
            node(resourceId = "comment-panel", className = "android.widget.FrameLayout"),
            node(
                resourceId = "comment-input",
                className = "android.widget.EditText",
                text = "Say something",
                editable = true,
                clickable = true,
                bounds = UiBounds(40, 2100, 900, 2250)
            ),
            node(resourceId = "comment-send", text = "Send", clickable = true)
        )
    )

    private fun node(
        resourceId: String = "",
        className: String = "android.widget.TextView",
        text: String = "",
        clickable: Boolean = false,
        editable: Boolean = false,
        focused: Boolean = false,
        bounds: UiBounds = UiBounds(0, 0, 100, 100)
    ) = CommentUiNode(
        resourceId = resourceId,
        className = className,
        text = text,
        description = "",
        packageName = "com.xingin.xhs",
        bounds = bounds,
        clickable = clickable,
        editable = editable,
        focused = focused,
        visible = true,
        enabled = true
    )
}
