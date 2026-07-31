package com.apk.claw.android.publish

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PublishCommitGuardTest {
    private val finalTree = treeWithNode("立即发布")
    private val navigationTree = treeWithNode("下一步")

    @Test
    fun `draft task blocks the final publish target without requesting authorization`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = true,
            screenTree = { finalTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
            nowMs = { 10_000 },
        )

        val blocked = guard.beforeToolDispatch("tap", tapParams())

        assertNotNull(blocked)
        assertTrue(blocked!!.contains("Draft-only"))
        assertEquals(0, authorizationCalls)
        assertFalse(guard.commitAuthorized)
    }

    @Test
    fun `formal task authorizes exactly one final publish tap`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { finalTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("commit-token-".padEnd(40, 'x'), 20_000)
            },
            nowMs = { 10_000 },
        )

        assertNull(guard.beforeToolDispatch("tap", tapParams()))
        assertTrue(guard.commitAuthorized)
        assertEquals(1, authorizationCalls)
        assertTrue(guard.commitToken.startsWith("commit-token-"))

        val repeated = guard.beforeToolDispatch("tap", tapParams())
        assertNotNull(repeated)
        assertTrue(repeated!!.contains("repeated"))
        assertEquals(1, authorizationCalls)
    }

    @Test
    fun `ordinary navigation taps do not consume commit authorization`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { navigationTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )

        assertNull(guard.beforeToolDispatch("tap", tapParams()))
        assertEquals(0, authorizationCalls)
        assertFalse(guard.commitAuthorized)
    }

    @Test
    fun `missing screen evidence fails closed before any tap`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { null },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )

        val blocked = guard.beforeToolDispatch("tap", tapParams())

        assertNotNull(blocked)
        assertTrue(blocked!!.contains("could not inspect"))
        assertEquals(0, authorizationCalls)
    }

    @Test
    fun `long press cannot authorize or trigger a final publish target`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { finalTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )

        val blocked = guard.beforeToolDispatch("long_press", tapParams())

        assertNotNull(blocked)
        assertTrue(blocked!!.contains("long press", ignoreCase = true))
        assertEquals(0, authorizationCalls)
        assertFalse(guard.commitAuthorized)
    }

    @Test
    fun `enter key is blocked because it can activate a focused publish target`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { finalTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )

        val blocked = guard.beforeToolDispatch("system_key", mapOf("key" to "enter"))

        assertNotNull(blocked)
        assertTrue(blocked!!.contains("Enter"))
        assertEquals(0, authorizationCalls)
        assertFalse(guard.commitAuthorized)
    }

    @Test
    fun `non activating system keys remain available during publish navigation`() {
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { navigationTree },
            authorizeCommit = {
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )

        assertNull(guard.beforeToolDispatch("system_key", mapOf("key" to "back")))
        assertNull(guard.beforeToolDispatch("system_key", mapOf("key" to "home")))
    }

    @Test
    fun `similarly worded content is not mistaken for final publish button`() {
        assertFalse(PublishCommitTargetPolicy.isFinalPublishLabel("发布设置"))
        assertFalse(PublishCommitTargetPolicy.isFinalPublishLabel("发布攻略"))
        assertTrue(PublishCommitTargetPolicy.isFinalPublishLabel("发布"))
        assertTrue(PublishCommitTargetPolicy.isFinalPublishLabel("确认发布"))
        assertTrue(PublishCommitTargetPolicy.isFinalPublishLabel("发布(1)"))
        assertTrue(PublishCommitTargetPolicy.isFinalPublishLabel("发布 3 个作品"))
        assertTrue(PublishCommitTargetPolicy.isFinalPublishLabel("发帖"))
    }

    @Test
    fun `formal packet cannot use the direct publish endpoint without a trusted gate`() {
        assertFalse(PublishRequestPolicy.mayExecute(draftOnly = false, trustedCommitGate = false))
        assertTrue(PublishRequestPolicy.mayExecute(draftOnly = false, trustedCommitGate = true))
        assertTrue(PublishRequestPolicy.mayExecute(draftOnly = true, trustedCommitGate = false))
    }

    @Test
    fun `authorization permits one dispatch and blocks every later mutating action`() {
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { finalTree },
            authorizeCommit = {
                PublishCommitDecision("x".repeat(40), 20_000)
            },
            nowMs = { 10_000 },
        )

        assertNull(guard.beforeToolDispatch("tap", tapParams()))

        val confirm = guard.beforeToolDispatch("tap", tapParams())
        val retry = guard.beforeToolDispatch(
            "swipe",
            mapOf("start_x" to 100, "start_y" to 500, "end_x" to 100, "end_y" to 100),
        )
        assertNotNull(confirm)
        assertTrue(confirm!!.contains("repeated", ignoreCase = true))
        assertNotNull(retry)
        assertTrue(retry!!.contains("repeated", ignoreCase = true))
    }

    @Test
    fun `near zero swipe and drag cannot impersonate a tap`() {
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { navigationTree },
            authorizeCommit = {
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )
        val nearZeroSwipe = mapOf(
            "start_x" to 150,
            "start_y" to 80,
            "end_x" to 153,
            "end_y" to 83,
        )
        val nearZeroDrag = mapOf(
            "start_x" to 150,
            "start_y" to 80,
            "end_x" to 155,
            "end_y" to 80,
        )

        assertTrue(
            guard.beforeToolDispatch("swipe", nearZeroSwipe)
                ?.contains("minimum displacement", ignoreCase = true) == true
        )
        assertTrue(
            guard.beforeToolDispatch("drag", nearZeroDrag)
                ?.contains("minimum displacement", ignoreCase = true) == true
        )
    }

    @Test
    fun `gesture ending on a final publish target is never accepted as commit`() {
        var authorizationCalls = 0
        val guard = PublishCommitGuard(
            draftOnly = false,
            screenTree = { finalTree },
            authorizeCommit = {
                authorizationCalls += 1
                PublishCommitDecision("x".repeat(40), 20_000)
            },
        )
        val swipeToPublish = mapOf(
            "start_x" to 150,
            "start_y" to 500,
            "end_x" to 150,
            "end_y" to 80,
        )

        val blocked = guard.beforeToolDispatch("swipe", swipeToPublish)

        assertNotNull(blocked)
        assertTrue(blocked!!.contains("gesture", ignoreCase = true))
        assertEquals(0, authorizationCalls)
    }

    @Test
    fun `formal publish completion requires observable platform success evidence`() {
        val published = treeWithNode("发布成功")
        val reviewing = treeWithNode("作品审核中")

        assertTrue(PublishOutcomePolicy.inspect(published).verified)
        assertTrue(PublishOutcomePolicy.inspect(reviewing).verified)
        assertEquals("发布成功", PublishOutcomePolicy.inspect(published).evidence)
        assertEquals("作品审核中", PublishOutcomePolicy.inspect(reviewing).evidence)
    }

    @Test
    fun `formal publish completion fails closed without postcondition evidence`() {
        assertFalse(PublishOutcomePolicy.inspect(treeWithNode("发布")).verified)
        assertFalse(PublishOutcomePolicy.inspect(treeWithNode("返回首页")).verified)
        assertFalse(PublishOutcomePolicy.inspect(null).verified)
    }

    @Test
    fun `failure evidence takes precedence over incidental success wording`() {
        val tree = JsonParser.parseString(
            """
            {
              "nodes": [
                {"text": "发布成功案例", "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 40}},
                {"text": "发布失败，请重试", "bounds": {"left": 0, "top": 50, "right": 180, "bottom": 100}}
              ]
            }
            """.trimIndent()
        ).asJsonObject

        val outcome = PublishOutcomePolicy.inspect(tree)

        assertFalse(outcome.verified)
        assertEquals("发布失败，请重试", outcome.evidence)
    }

    @Test
    fun `formal publish is only reportable after commit and verified platform outcome`() {
        val published = treeWithNode("发布成功")

        assertFalse(
            PublishCompletionPolicy.inspect(
                draftOnly = false,
                executionSucceeded = true,
                commitAuthorized = false,
                tree = published,
            ).verified
        )
        assertFalse(
            PublishCompletionPolicy.inspect(
                draftOnly = false,
                executionSucceeded = true,
                commitAuthorized = true,
                tree = null,
            ).verified
        )
        assertTrue(
            PublishCompletionPolicy.inspect(
                draftOnly = false,
                executionSucceeded = true,
                commitAuthorized = true,
                tree = published,
            ).verified
        )
    }

    @Test
    fun `formal completion rejects success evidence that predates the commit`() {
        val published = treeWithNode("发布成功")

        val unchangedObservation = PublishCompletionPolicy.inspect(
            draftOnly = false,
            executionSucceeded = true,
            commitAuthorized = true,
            tree = published,
            commitExpiresAtMs = 20_000,
            nowMs = 10_000,
            baselineEvidence = "",
            observationAdvanced = false,
        )
        val repeatedBaselineEvidence = PublishCompletionPolicy.inspect(
            draftOnly = false,
            executionSucceeded = true,
            commitAuthorized = true,
            tree = published,
            commitExpiresAtMs = 20_000,
            nowMs = 10_000,
            baselineEvidence = "发布成功",
            observationAdvanced = true,
        )

        assertFalse(unchangedObservation.verified)
        assertTrue(unchangedObservation.evidence.contains("fresh", ignoreCase = true))
        assertFalse(repeatedBaselineEvidence.verified)
        assertTrue(repeatedBaselineEvidence.evidence.contains("predates", ignoreCase = true))
    }

    @Test
    fun `formal completion revalidates commit token expiry`() {
        val outcome = PublishCompletionPolicy.inspect(
            draftOnly = false,
            executionSucceeded = true,
            commitAuthorized = true,
            tree = treeWithNode("发布成功"),
            commitExpiresAtMs = 10_000,
            nowMs = 10_001,
            baselineEvidence = "",
            observationAdvanced = true,
        )

        assertFalse(outcome.verified)
        assertTrue(outcome.evidence.contains("expired", ignoreCase = true))
    }

    @Test
    fun `draft-only completion depends on execution result without publish postcondition`() {
        assertTrue(
            PublishCompletionPolicy.inspect(
                draftOnly = true,
                executionSucceeded = true,
                commitAuthorized = false,
                tree = null,
            ).verified
        )
        assertFalse(
            PublishCompletionPolicy.inspect(
                draftOnly = true,
                executionSucceeded = false,
                commitAuthorized = false,
                tree = null,
            ).verified
        )
    }

    private fun tapParams(): Map<String, Any> = mapOf("x" to 150, "y" to 80)

    private fun treeWithNode(label: String): JsonObject {
        return JsonParser.parseString(
            """
            {
              "nodes": [
                {
                  "text": "$label",
                  "description": "",
                  "bounds": {"left": 100, "top": 40, "right": 220, "bottom": 120}
                }
              ]
            }
            """.trimIndent()
        ).asJsonObject
    }
}
