package com.apk.claw.android.comment

import java.io.File
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentCampaignPressureTest {
    @Test
    fun one_hundred_five_target_campaigns_preserve_send_and_checkpoint_invariants() {
        repeat(100) { seed ->
            val directory = Files.createTempDirectory("comment-pressure-$seed").toFile()
            try {
                val driver = PressureDriver()
                val store = CommentCampaignStore(directory)
                val coordinator = CommentCampaignCoordinator(store, CommentSendLedger(directory), driver)
                val manifest = manifest(seed)
                val prepared = coordinator.prepare(manifest)
                coordinator.confirm(prepared.campaignId, prepared.manifestHash, prepared.items.map { it.itemHash })

                val result = coordinator.run(prepared.campaignId)
                val restored = CommentCampaignStore(directory).load(prepared.campaignId)

                assertTrue("seed=$seed", result.success)
                assertEquals("seed=$seed", 5, driver.sendAttempts)
                assertEquals("seed=$seed", 5, driver.sendKeys.size)
                assertEquals("seed=$seed", CommentCampaignState.COMPLETED, restored!!.state)
                assertTrue("seed=$seed", restored.items.all { it.state == CommentItemState.SENT_VERIFIED })
            } finally {
                directory.deleteRecursively()
            }
        }
    }

    private class PressureDriver : CommentDeviceDriver {
        var sendAttempts = 0
        val sendKeys = mutableSetOf<String>()

        override fun plan(campaign: CommentCampaign, item: CommentCampaignItem): CommentDeviceStepPlan =
            when (item.state) {
                CommentItemState.DISCOVERED -> CommentDeviceStepPlan("discovered", "begin_navigation", item.itemId)
                CommentItemState.NAVIGATING -> CommentDeviceStepPlan("navigation", "navigate_video", item.videoId)
                CommentItemState.VIDEO_VERIFIED -> CommentDeviceStepPlan("video", "open_comment_composer", "comment")
                CommentItemState.COMPOSER_OPEN -> CommentDeviceStepPlan("comment_sheet", "focus_comment_input", item.itemId)
                CommentItemState.INPUT_FOCUSED -> CommentDeviceStepPlan("input_focused", "input_and_verify_text", item.itemId)
                CommentItemState.SENDING -> CommentDeviceStepPlan("text_verified", "send_and_verify", item.itemId)
                else -> error("No plan for ${item.state}")
            }

        override fun execute(
            plan: CommentDeviceStepPlan,
            campaign: CommentCampaign,
            item: CommentCampaignItem
        ): CommentDeviceStepResult = when (plan.action) {
            "begin_navigation" -> CommentDeviceStepResult.Advance(CommentItemState.NAVIGATING, "ok")
            "navigate_video" -> CommentDeviceStepResult.Advance(CommentItemState.VIDEO_VERIFIED, "ok")
            "open_comment_composer" -> CommentDeviceStepResult.Advance(CommentItemState.COMPOSER_OPEN, "ok")
            "focus_comment_input" -> CommentDeviceStepResult.Advance(CommentItemState.INPUT_FOCUSED, "ok")
            "input_and_verify_text" -> CommentDeviceStepResult.Advance(CommentItemState.TEXT_VERIFIED, "ok")
            "send_and_verify" -> {
                sendAttempts += 1
                sendKeys += item.idempotencyKey
                CommentDeviceStepResult.SendVerified("visible")
            }
            else -> CommentDeviceStepResult.Failed("unexpected_action", plan.action)
        }
    }

    private fun manifest(seed: Int): CommentManifest {
        val comment = "20-year Tesla price?"
        return CommentManifestAuthorizer.seal(
            CommentManifest(
                campaignId = "campaign-$seed",
                platform = "xiaohongshu",
                accountId = "account-$seed",
                query = "automotive creators",
                targetCount = 5,
                commentText = comment,
                items = (1..5).map { index ->
                    CommentManifestItem(
                        itemId = "item-$index",
                        creatorId = "creator-$index",
                        creatorLabel = "Creator $index",
                        videoId = "video-$seed-$index",
                        videoLabel = "First video",
                        commentText = comment
                    )
                }
            )
        )
    }
}
