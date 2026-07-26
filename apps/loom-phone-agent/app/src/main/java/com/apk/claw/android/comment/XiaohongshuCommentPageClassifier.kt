package com.apk.claw.android.comment

import java.util.Locale

class XiaohongshuCommentPageClassifier {
    fun classify(observation: CommentPageObservation): CommentPageState {
        if (!isXiaohongshuPackage(observation.packageName)) {
            return CommentPageState.OTHER_APP
        }

        val usableNodes = observation.nodes.filter { it.visible && it.enabled }
        if (usableNodes.any(::isBlockedNode)) {
            return CommentPageState.BLOCKED
        }

        val hasPanel = usableNodes.any(::isCommentPanel)
        val hasEditor = usableNodes.any(::isCommentEditor)
        val hasSend = usableNodes.any(::isSendControl)
        val hasSheetMarker = usableNodes.any(::isBottomSheetMarker)
        val evidenceCount = listOf(hasPanel, hasEditor, hasSend, hasSheetMarker).count { it }

        if (evidenceCount >= MIN_COMMENT_SHEET_EVIDENCE) {
            if (usableNodes.any { it.focused && isCommentEditor(it) }) {
                return CommentPageState.INPUT_FOCUSED
            }
            return CommentPageState.COMMENT_SHEET
        }

        val hasVideoSurface = usableNodes.any(::isVideoSurface)
        val videoControlCount = usableNodes.count(::isVideoControl)
        return if (
            (hasVideoSurface && videoControlCount >= MIN_VIDEO_CONTROLS_WITH_SURFACE) ||
            videoControlCount >= MIN_VIDEO_CONTROLS_WITHOUT_SURFACE
        ) {
            CommentPageState.VIDEO
        } else {
            CommentPageState.UNKNOWN
        }
    }

    private fun isXiaohongshuPackage(packageName: String): Boolean {
        val normalized = packageName.lowercase(Locale.ROOT)
        return normalized == XHS_PACKAGE || normalized.startsWith("com.xingin.")
    }

    private fun isBlockedNode(node: CommentUiNode): Boolean {
        val value = node.searchableText()
        return BLOCKED_TERMS.any(value::contains)
    }

    private fun isCommentPanel(node: CommentUiNode): Boolean {
        val value = node.searchableText()
        return PANEL_TERMS.any(value::contains)
    }

    private fun isCommentEditor(node: CommentUiNode): Boolean {
        if (!node.editable) return false
        val value = node.searchableText()
        return EDITOR_TERMS.any(value::contains) ||
            node.className.lowercase(Locale.ROOT).contains("edittext")
    }

    private fun isSendControl(node: CommentUiNode): Boolean {
        if (!node.clickable) return false
        val value = node.searchableText()
        return SEND_TERMS.any(value::contains)
    }

    private fun isBottomSheetMarker(node: CommentUiNode): Boolean {
        val value = node.searchableText()
        return SHEET_TERMS.any(value::contains)
    }

    private fun isVideoSurface(node: CommentUiNode): Boolean {
        val value = node.searchableText()
        return VIDEO_TERMS.any(value::contains)
    }

    private fun isVideoControl(node: CommentUiNode): Boolean {
        if (!node.clickable) return false
        val value = node.searchableText()
        return VIDEO_CONTROL_TERMS.any(value::contains)
    }

    private fun CommentUiNode.searchableText(): String =
        "$resourceId $className $text $description".lowercase(Locale.ROOT)

    private companion object {
        const val XHS_PACKAGE = "com.xingin.xhs"
        const val MIN_COMMENT_SHEET_EVIDENCE = 2
        const val MIN_VIDEO_CONTROLS_WITH_SURFACE = 2
        const val MIN_VIDEO_CONTROLS_WITHOUT_SURFACE = 3

        val BLOCKED_TERMS = listOf(
            "log in", "login", "verification", "captcha",
            "\u767b\u5f55", "\u9a8c\u8bc1\u7801", "\u5b89\u5168\u9a8c\u8bc1", "\u4eba\u673a\u9a8c\u8bc1"
        )
        val PANEL_TERMS = listOf("comment-panel", "comment_panel", "comments-panel", "comment-list")
        val EDITOR_TERMS = listOf(
            "comment-input", "comment_input", "say something", "add comment", "reply",
            "\u8bf4\u70b9\u4ec0\u4e48", "\u5199\u8bc4\u8bba", "\u56de\u590d"
        )
        val SEND_TERMS = listOf("comment-send", "comment_send", "send", "publish", "\u53d1\u9001")
        val SHEET_TERMS = listOf("bottom-sheet", "bottom_sheet", "comment-sheet", "comment_sheet")
        val VIDEO_TERMS = listOf("video-player", "video_player", "player", "video-surface")
        val VIDEO_CONTROL_TERMS = listOf(
            "like", "comment-count", "comments", "share",
            "\u70b9\u8d5e", "\u8bc4\u8bba", "\u5206\u4eab"
        )
    }
}
