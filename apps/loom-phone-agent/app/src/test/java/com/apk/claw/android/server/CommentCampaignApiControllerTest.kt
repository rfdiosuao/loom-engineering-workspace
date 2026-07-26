package com.apk.claw.android.server

import com.apk.claw.android.comment.CommentCampaign
import com.apk.claw.android.comment.CommentCampaignCoordinator
import com.apk.claw.android.comment.CommentCampaignStore
import com.apk.claw.android.comment.CommentDeviceDriver
import com.apk.claw.android.comment.CommentDeviceStepPlan
import com.apk.claw.android.comment.CommentDeviceStepResult
import com.apk.claw.android.comment.CommentItemState
import com.apk.claw.android.comment.CommentSendLedger
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.File
import java.lang.reflect.Proxy
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class CommentCampaignApiControllerTest {
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("comment-api").toFile()
        CommentCampaignApiController.installCoordinatorForTests(
            CommentCampaignCoordinator(
                CommentCampaignStore(tempDir),
                CommentSendLedger(tempDir),
                ImmediateDriver(),
                now = { 1_700_000_000_000L }
            )
        )
    }

    @After
    fun tearDown() {
        CommentCampaignApiController.installCoordinatorForTests(null)
        tempDir.deleteRecursively()
    }

    @Test
    fun prepare_returns_exact_manifest_and_complete_progress_contract() {
        val body = responseJson(
            CommentCampaignApiController.handlePrepare(session(prepareJson()), requireToken = false)
        )
        val data = body["data"].asJsonObject

        assertTrue(body["success"].asBoolean)
        assertEquals("awaiting_confirmation", data["currentStep"].asString)
        assertTrue(data["manifestHash"].asString.isNotBlank())
        assertEquals(1, data["itemHashes"].asJsonArray.size())
        assertEquals("weak", data["safetyLevel"].asString)
        assertMetrics(data)
    }

    @Test
    fun changed_manifest_confirmation_is_structured_and_non_retryable() {
        val prepared = responseJson(
            CommentCampaignApiController.handlePrepare(session(prepareJson()), requireToken = false)
        )["data"].asJsonObject
        val confirm = """{
          "campaignId":"campaign-api-1",
          "manifestHash":"changed",
          "itemHashes":["changed-item"]
        }""".trimIndent()

        val body = responseJson(
            CommentCampaignApiController.handleConfirm(session(confirm), requireToken = false)
        )
        val data = body["data"].asJsonObject

        assertFalse(body["success"].asBoolean)
        assertEquals("manifest_changed", data["errorCode"].asString)
        assertEquals("awaiting_confirmation", data["currentStep"].asString)
        assertFalse(data["retryable"].asBoolean)
        assertMetrics(data)
        assertTrue(prepared["manifestHash"].asString != "changed")
    }

    @Test
    fun confirm_then_resume_completes_without_llm_rounds() {
        val prepared = responseJson(
            CommentCampaignApiController.handlePrepare(session(prepareJson()), requireToken = false)
        )["data"].asJsonObject
        val confirm = JsonObject().apply {
            addProperty("campaignId", "campaign-api-1")
            addProperty("manifestHash", prepared["manifestHash"].asString)
        }
        val confirmed = responseJson(
            CommentCampaignApiController.handleConfirm(session(confirm.toString()), requireToken = false)
        )
        val resumed = responseJson(
            CommentCampaignApiController.handleResume(
                session("""{"campaignId":"campaign-api-1"}"""),
                requireToken = false
            )
        )
        val data = resumed["data"].asJsonObject

        assertTrue(confirmed["success"].asBoolean)
        assertTrue(resumed["success"].asBoolean)
        assertEquals("completed", data["state"].asString)
        assertEquals(0, data["rounds"].asInt)
        assertEquals(0L, data["llmRoundMs"].asLong)
    }

    @Test
    fun strict_campaign_still_requires_exact_item_hashes() {
        val prepared = responseJson(
            CommentCampaignApiController.handlePrepare(
                session(prepareJson().replace("\"accountId\"", "\"safetyLevel\":\"strict\",\n      \"accountId\"")),
                requireToken = false
            )
        )["data"].asJsonObject
        val confirm = JsonObject().apply {
            addProperty("campaignId", "campaign-api-1")
            addProperty("manifestHash", prepared["manifestHash"].asString)
        }

        val body = responseJson(
            CommentCampaignApiController.handleConfirm(session(confirm.toString()), requireToken = false)
        )
        val data = body["data"].asJsonObject

        assertFalse(body["success"].asBoolean)
        assertEquals("confirmation_mismatch", data["errorCode"].asString)
        assertEquals("awaiting_confirmation", data["currentStep"].asString)
    }

    private fun assertMetrics(data: JsonObject) {
        listOf("totalMs", "screenTreeMs", "llmRoundMs", "toolCallMs", "rounds", "mode")
            .forEach { key -> assertTrue("missing $key", data.has(key)) }
        assertEquals("comment_campaign", data["mode"].asString)
    }

    private fun prepareJson(): String = """{
      "campaignId":"campaign-api-1",
      "platform":"xiaohongshu",
      "accountId":"account-1",
      "query":"automotive creators",
      "commentText":"20-year Tesla price?",
      "items":[{
        "itemId":"item-1",
        "creatorId":"creator-1",
        "creatorLabel":"Creator 1",
        "videoId":"video-1",
        "videoLabel":"First video"
      }]
    }""".trimIndent()

    private fun responseJson(response: NanoHTTPD.Response): JsonObject = response.use {
        JsonParser.parseString(it.data.bufferedReader(Charsets.UTF_8).readText()).asJsonObject
    }

    private fun session(raw: String): NanoHTTPD.IHTTPSession {
        val bytes = raw.toByteArray(Charsets.UTF_8)
        val input = ByteArrayInputStream(bytes)
        val headers = mutableMapOf(
            "content-length" to bytes.size.toString(),
            "Content-Length" to bytes.size.toString()
        )
        return Proxy.newProxyInstance(
            NanoHTTPD.IHTTPSession::class.java.classLoader,
            arrayOf(NanoHTTPD.IHTTPSession::class.java)
        ) { _, method, arguments ->
            when (method.name) {
                "getHeaders" -> headers
                "getInputStream" -> input
                "getMethod" -> NanoHTTPD.Method.POST
                "getUri" -> "/api/comment-campaign"
                "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
                "getParms" -> mutableMapOf<String, String>()
                "getParameters" -> mutableMapOf<String, MutableList<String>>()
                "getQueryParameterString" -> ""
                "parseBody" -> {
                    @Suppress("UNCHECKED_CAST")
                    (arguments?.firstOrNull() as? MutableMap<String, String>)?.set("postData", raw)
                    Unit
                }
                "execute" -> Unit
                else -> null
            }
        } as NanoHTTPD.IHTTPSession
    }

    private class ImmediateDriver : CommentDeviceDriver {
        override fun plan(campaign: CommentCampaign, item: com.apk.claw.android.comment.CommentCampaignItem) =
            when (item.state) {
                CommentItemState.DISCOVERED -> CommentDeviceStepPlan("discovered", "begin_navigation", item.itemId)
                CommentItemState.NAVIGATING -> CommentDeviceStepPlan("navigation", "navigate_video", item.videoId)
                CommentItemState.VIDEO_VERIFIED -> CommentDeviceStepPlan("video", "open_comment_composer", "comment")
                CommentItemState.COMPOSER_OPEN -> CommentDeviceStepPlan("comment_sheet", "focus_comment_input", item.itemId)
                CommentItemState.INPUT_FOCUSED -> CommentDeviceStepPlan("input_focused", "input_and_verify_text", item.itemId)
                CommentItemState.SENDING -> CommentDeviceStepPlan("text_verified", "send_and_verify", item.itemId)
                else -> error("unexpected state ${item.state}")
            }

        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: com.apk.claw.android.comment.CommentCampaignItem
        ): CommentDeviceStepResult = when (plan.action) {
            "begin_navigation" -> CommentDeviceStepResult.Advance(CommentItemState.NAVIGATING, "ok")
            "navigate_video" -> CommentDeviceStepResult.Advance(CommentItemState.VIDEO_VERIFIED, "ok")
            "open_comment_composer" -> CommentDeviceStepResult.Advance(CommentItemState.COMPOSER_OPEN, "ok")
            "focus_comment_input" -> CommentDeviceStepResult.Advance(CommentItemState.INPUT_FOCUSED, "ok")
            "input_and_verify_text" -> CommentDeviceStepResult.Advance(CommentItemState.TEXT_VERIFIED, "ok")
            "send_and_verify" -> CommentDeviceStepResult.SendVerified("visible")
            else -> CommentDeviceStepResult.Failed("unexpected_action", plan.action)
        }
    }
}
