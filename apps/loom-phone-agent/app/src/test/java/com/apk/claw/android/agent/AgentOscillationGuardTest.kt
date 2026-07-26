package com.apk.claw.android.agent

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentOscillationGuardTest {

    @Test
    fun blocks_identical_action_before_second_dispatch() {
        val guard = AgentOscillationGuard()
        val action = AgentActionSignature("video", "tap", "comment")

        assertEquals(OscillationDecision.Continue, guard.evaluateNext(action))
        guard.recordDispatched(action)

        assertEquals(OscillationDecision.Blocked(period = 1), guard.evaluateNext(action))
    }

    @Test
    fun blocks_video_comment_sheet_oscillation_before_second_back_dispatch() {
        val guard = AgentOscillationGuard()
        val actions = listOf(
            AgentActionSignature("video", "tap", "comment"),
            AgentActionSignature("comment_sheet", "system_key", "back"),
            AgentActionSignature("video", "tap", "comment"),
            AgentActionSignature("comment_sheet", "system_key", "back")
        )

        actions.dropLast(1).forEach { action ->
            assertEquals(OscillationDecision.Continue, guard.evaluateNext(action))
            guard.recordDispatched(action)
        }

        assertEquals(
            OscillationDecision.Blocked(period = 2),
            guard.evaluateNext(actions.last())
        )
    }

    @Test
    fun blocks_period_three_loop_before_repeated_sequence_completes() {
        val guard = AgentOscillationGuard()
        val actions = listOf(
            AgentActionSignature("search", "tap", "creator"),
            AgentActionSignature("profile", "tap", "first_video"),
            AgentActionSignature("video", "system_key", "back"),
            AgentActionSignature("search", "tap", "creator"),
            AgentActionSignature("profile", "tap", "first_video"),
            AgentActionSignature("video", "system_key", "back")
        )

        actions.dropLast(1).forEach { action ->
            assertEquals(OscillationDecision.Continue, guard.evaluateNext(action))
            guard.recordDispatched(action)
        }

        assertEquals(
            OscillationDecision.Blocked(period = 3),
            guard.evaluateNext(actions.last())
        )
    }

    @Test
    fun allows_distinct_forward_progress() {
        val guard = AgentOscillationGuard()
        val actions = listOf(
            AgentActionSignature("search", "input_text", "query"),
            AgentActionSignature("results", "tap", "creator"),
            AgentActionSignature("profile", "tap", "first_video"),
            AgentActionSignature("video", "tap", "comment"),
            AgentActionSignature("comment_sheet", "tap", "composer"),
            AgentActionSignature("input_focused", "input_text", "comment")
        )

        val decisions = actions.map { action ->
            guard.evaluateNext(action).also { guard.recordDispatched(action) }
        }

        assertTrue(decisions.all { it == OscillationDecision.Continue })
    }

    @Test
    fun clear_forgets_previous_recovery_branch() {
        val guard = AgentOscillationGuard()
        val action = AgentActionSignature("video", "tap", "comment")
        guard.recordDispatched(action)

        guard.clear()

        assertEquals(OscillationDecision.Continue, guard.evaluateNext(action))
    }

    @Test
    fun coarse_page_state_ignores_dynamic_visible_text() {
        val first = tree(text = "1234 comments", includeComposer = false)
        val second = tree(text = "1241 comments", includeComposer = false)

        assertEquals(
            AgentPageStateFingerprint.fromTree(first),
            AgentPageStateFingerprint.fromTree(second)
        )
    }

    @Test
    fun coarse_page_state_distinguishes_video_from_comment_composer() {
        val video = tree(text = "1234 comments", includeComposer = false)
        val commentSheet = tree(text = "1234 comments", includeComposer = true)

        assertNotEquals(
            AgentPageStateFingerprint.fromTree(video),
            AgentPageStateFingerprint.fromTree(commentSheet)
        )
    }

    @Test
    fun action_signature_redacts_input_text_and_ignores_observation_tools() {
        val comment = "20-year Tesla private quote"
        val signature = AgentActionSignatureFactory.create(
            pageState = "comment_sheet",
            toolName = "input_text",
            params = mapOf("text" to comment, "resource_id" to "comment-input")
        )

        assertTrue(signature != null)
        assertFalse(signature!!.target.contains(comment))
        assertNull(
            AgentActionSignatureFactory.create(
                pageState = "comment_sheet",
                toolName = "get_screen_info",
                params = emptyMap()
            )
        )
    }

    @Test
    fun action_signature_changes_when_tap_target_changes() {
        val first = AgentActionSignatureFactory.create("video", "tap", mapOf("x" to 900, "y" to 1200))
        val second = AgentActionSignatureFactory.create("video", "tap", mapOf("x" to 900, "y" to 1400))

        assertNotEquals(first, second)
    }

    private fun tree(text: String, includeComposer: Boolean) = JsonParser.parseString(
        """
        {
          "screen": {"currentPackage": "com.xingin.xhs"},
          "nodes": [
            {
              "resourceId": "video-comment-count",
              "className": "android.widget.TextView",
              "text": "$text",
              "clickable": true,
              "editable": false,
              "bounds": {"left": 900, "top": 1000, "right": 1080, "bottom": 1200}
            }
            ${if (includeComposer) "," else ""}
            ${if (includeComposer) """
            {
              "resourceId": "comment-input",
              "className": "android.widget.EditText",
              "text": "",
              "clickable": true,
              "editable": true,
              "bounds": {"left": 40, "top": 2100, "right": 900, "bottom": 2250}
            }
            """ else ""}
          ]
        }
        """.trimIndent()
    ).asJsonObject
}
