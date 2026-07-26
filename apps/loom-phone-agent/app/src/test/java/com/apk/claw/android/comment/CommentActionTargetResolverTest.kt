package com.apk.claw.android.comment

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentActionTargetResolverTest {
    @Test
    fun resolves_one_comment_control_on_a_video_page() {
        val result = CommentActionTargetResolver.resolve(
            CommentActionKind.OPEN_COMPOSER,
            listOf(node("like-count", "100"), node("comment-count", "123 comments"))
        )

        assertEquals("comment-count", (result as CommentActionTargetResolution.Unique).node.resourceId)
    }

    @Test
    fun refuses_two_equally_plausible_send_controls() {
        val result = CommentActionTargetResolver.resolve(
            CommentActionKind.SEND,
            listOf(node("send-top", "Send"), node("send-bottom", "Send"))
        )

        assertTrue(result is CommentActionTargetResolution.Ambiguous)
    }

    @Test
    fun comment_count_is_never_selected_as_the_send_control() {
        val result = CommentActionTargetResolver.resolve(
            CommentActionKind.SEND,
            listOf(node("comment-count", "123 comments"))
        )

        assertEquals(CommentActionTargetResolution.NotFound, result)
    }

    private fun node(resourceId: String, text: String) = CommentUiNode(
        resourceId = resourceId,
        className = "TextView",
        text = text,
        description = "",
        packageName = "com.xingin.xhs",
        bounds = UiBounds(0, 0, 100, 100),
        clickable = true,
        editable = false,
        focused = false,
        visible = true,
        enabled = true
    )
}
