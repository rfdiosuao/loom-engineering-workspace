package com.apk.claw.android.comment

import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class CommentCampaignCoordinatorTest {
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("comment-coordinator").toFile()
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    @Test
    fun five_targets_complete_once_with_no_duplicate_send() {
        val driver = SuccessfulDriver()
        val coordinator = coordinator(driver)
        val prepared = coordinator.prepare(manifest(targetCount = 5))
        coordinator.confirm(
            prepared.campaignId,
            prepared.manifestHash,
            prepared.items.map { it.itemHash }
        )

        val result = coordinator.run(prepared.campaignId)

        assertTrue(result.success)
        assertEquals(CommentCampaignState.COMPLETED, result.campaign!!.state)
        assertEquals(5, driver.sendAttempts)
        assertEquals(5, driver.sendKeys.size)
    }

    @Test
    fun exact_confirmation_is_required_before_running() {
        val coordinator = coordinator(SuccessfulDriver())
        val prepared = coordinator.prepare(manifest(targetCount = 1))

        val result = coordinator.run(prepared.campaignId)

        assertFalse(result.success)
        assertEquals("confirmation_required", result.errorCode)
        assertEquals(CommentCampaignState.AWAITING_CONFIRMATION, result.campaign!!.state)
    }

    @Test
    fun open_back_oscillation_is_blocked_before_a_third_open() {
        val driver = OscillatingDriver()
        val coordinator = coordinator(driver)
        val prepared = coordinator.prepare(manifest(targetCount = 1))
        coordinator.confirm(prepared.campaignId, prepared.manifestHash, prepared.items.map { it.itemHash })

        val result = coordinator.run(prepared.campaignId)

        assertFalse(result.success)
        assertEquals("ui_oscillation_detected", result.errorCode)
        assertEquals(2, driver.openAttempts)
        assertEquals(1, driver.backAttempts)
    }

    @Test
    fun uncertain_send_is_not_replayed_after_coordinator_restart() {
        val firstDriver = UncertainSendDriver()
        val first = coordinator(firstDriver)
        val prepared = first.prepare(manifest(targetCount = 1))
        first.confirm(prepared.campaignId, prepared.manifestHash, prepared.items.map { it.itemHash })

        val firstResult = first.run(prepared.campaignId)
        val secondDriver = SuccessfulDriver()
        val resumed = coordinator(secondDriver).resume(prepared.campaignId)

        assertEquals(CommentCampaignState.PAUSED, firstResult.campaign!!.state)
        assertEquals("send_uncertain", firstResult.errorCode)
        assertEquals(1, firstDriver.sendAttempts)
        assertFalse(resumed.success)
        assertEquals("send_reconciliation_required", resumed.errorCode)
        assertEquals(0, secondDriver.sendAttempts)
    }

    @Test
    fun driver_exception_during_send_becomes_uncertain_instead_of_escaping_or_replaying() {
        val crashingDriver = CrashOnSendDriver()
        val first = coordinator(crashingDriver)
        val prepared = first.prepare(manifest(targetCount = 1))
        first.confirm(prepared.campaignId, prepared.manifestHash, prepared.items.map { it.itemHash })

        val firstResult = first.run(prepared.campaignId)
        val replayDriver = SuccessfulDriver()
        val resumed = coordinator(replayDriver).resume(prepared.campaignId)

        assertFalse(firstResult.success)
        assertEquals("send_uncertain", firstResult.errorCode)
        assertEquals(CommentItemState.SEND_UNCERTAIN, firstResult.campaign!!.items.single().state)
        assertEquals(1, crashingDriver.sendAttempts)
        assertEquals("send_reconciliation_required", resumed.errorCode)
        assertEquals(0, replayDriver.sendAttempts)
    }

    private fun coordinator(driver: CommentDeviceDriver) = CommentCampaignCoordinator(
        store = CommentCampaignStore(tempDir),
        ledger = CommentSendLedger(tempDir),
        driver = driver,
        now = { 1_700_000_000_000L }
    )

    private fun manifest(targetCount: Int): CommentManifest {
        val comment = "20-year Tesla price?"
        return CommentManifestAuthorizer.seal(
            CommentManifest(
                campaignId = "campaign-$targetCount",
                platform = "xiaohongshu",
                accountId = "account-1",
                query = "automotive creators",
                targetCount = targetCount,
                commentText = comment,
                items = (1..targetCount).map { index ->
                    CommentManifestItem(
                        itemId = "item-$index",
                        creatorId = "creator-$index",
                        creatorLabel = "Creator $index",
                        videoId = "video-$index",
                        videoLabel = "First video",
                        commentText = comment
                    )
                },
                createdAt = 1_700_000_000_000L
            )
        )
    }

    private open class SuccessfulDriver : CommentDeviceDriver {
        var sendAttempts = 0
        val sendKeys = mutableSetOf<String>()

        override fun plan(campaign: CommentCampaign, item: CommentCampaignItem): CommentDeviceStepPlan =
            standardPlan(item)

        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: CommentCampaignItem
        ): CommentDeviceStepResult = when (plan.action) {
            "begin_navigation" -> CommentDeviceStepResult.Advance(CommentItemState.NAVIGATING, "navigation started")
            "navigate_video" -> CommentDeviceStepResult.Advance(CommentItemState.VIDEO_VERIFIED, "video verified")
            "open_comment_composer" -> CommentDeviceStepResult.Advance(CommentItemState.COMPOSER_OPEN, "composer open")
            "focus_comment_input" -> CommentDeviceStepResult.Advance(CommentItemState.INPUT_FOCUSED, "input focused")
            "input_and_verify_text" -> CommentDeviceStepResult.Advance(CommentItemState.TEXT_VERIFIED, "text verified")
            "send_and_verify" -> {
                sendAttempts += 1
                sendKeys += item.idempotencyKey
                CommentDeviceStepResult.SendVerified("comment visible")
            }
            else -> CommentDeviceStepResult.Failed("unexpected_action", plan.action)
        }
    }

    private class UncertainSendDriver : SuccessfulDriver() {
        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: CommentCampaignItem
        ): CommentDeviceStepResult {
            if (plan.action != "send_and_verify") return super.execute(plan, campaign, item)
            sendAttempts += 1
            return CommentDeviceStepResult.SendUncertain("send result timed out")
        }
    }

    private class OscillatingDriver : CommentDeviceDriver {
        private val plans = listOf(
            CommentDeviceStepPlan("video", "open_comment_composer", "comment"),
            CommentDeviceStepPlan("comment_sheet", "system_key", "back"),
            CommentDeviceStepPlan("video", "open_comment_composer", "comment"),
            CommentDeviceStepPlan("comment_sheet", "system_key", "back")
        )
        private var index = 0
        var openAttempts = 0
        var backAttempts = 0

        override fun plan(campaign: CommentCampaign, item: CommentCampaignItem): CommentDeviceStepPlan =
            plans[index.coerceAtMost(plans.lastIndex)]

        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: CommentCampaignItem
        ): CommentDeviceStepResult {
            index += 1
            if (plan.action == "open_comment_composer") openAttempts += 1
            if (plan.action == "system_key") backAttempts += 1
            return CommentDeviceStepResult.Retry("page_transition_failed", "retry scripted transition")
        }
    }

    private class CrashOnSendDriver : SuccessfulDriver() {
        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: CommentCampaignItem
        ): CommentDeviceStepResult {
            if (plan.action != "send_and_verify") return super.execute(plan, campaign, item)
            sendAttempts += 1
            throw IllegalStateException("synthetic transport loss")
        }
    }

    companion object {
        private fun standardPlan(item: CommentCampaignItem): CommentDeviceStepPlan = when (item.state) {
            CommentItemState.DISCOVERED -> CommentDeviceStepPlan("discovered", "begin_navigation", item.itemId)
            CommentItemState.NAVIGATING -> CommentDeviceStepPlan("navigation", "navigate_video", item.videoId)
            CommentItemState.VIDEO_VERIFIED -> CommentDeviceStepPlan("video", "open_comment_composer", "comment")
            CommentItemState.COMPOSER_OPEN -> CommentDeviceStepPlan("comment_sheet", "focus_comment_input", item.itemId)
            CommentItemState.INPUT_FOCUSED -> CommentDeviceStepPlan("input_focused", "input_and_verify_text", item.itemId)
            CommentItemState.SENDING -> CommentDeviceStepPlan("text_verified", "send_and_verify", item.itemId)
            else -> error("No device action for ${item.state}")
        }
    }
}
