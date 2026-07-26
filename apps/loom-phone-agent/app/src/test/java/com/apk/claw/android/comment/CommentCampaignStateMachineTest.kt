package com.apk.claw.android.comment

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentCampaignStateMachineTest {

    @Test
    fun cannot_send_before_text_is_verified() {
        val item = item(CommentItemState.COMPOSER_OPEN)

        val result = CommentCampaignStateMachine.transition(item, CommentItemState.SENDING)

        assertFalse(result.accepted)
        assertEquals("invalid_comment_state_transition", result.errorCode)
        assertEquals(CommentItemState.COMPOSER_OPEN, result.item.state)
    }

    @Test
    fun verified_text_must_be_authorized_before_sending() {
        val verified = item(CommentItemState.TEXT_VERIFIED)
        val authorization = CommentCampaignStateMachine.transition(
            verified,
            CommentItemState.SEND_AUTHORIZED
        )
        val sending = CommentCampaignStateMachine.transition(
            authorization.item,
            CommentItemState.SENDING
        )

        assertTrue(authorization.accepted)
        assertTrue(sending.accepted)
        assertEquals(CommentItemState.SENDING, sending.item.state)
    }

    @Test
    fun uncertain_send_is_terminal_until_explicit_reconciliation() {
        val uncertain = CommentCampaignStateMachine.transition(
            item(CommentItemState.SENDING),
            CommentItemState.SEND_UNCERTAIN
        )

        assertTrue(uncertain.accepted)
        assertFalse(
            CommentCampaignStateMachine.transition(
                uncertain.item,
                CommentItemState.SENDING
            ).accepted
        )
    }

    @Test
    fun completed_campaign_with_one_failed_target_keeps_partial_result() {
        val campaign = campaign(
            listOf(
                item(CommentItemState.SENT_VERIFIED, "item-1"),
                item(CommentItemState.FAILED, "item-2"),
                item(CommentItemState.SKIPPED, "item-3")
            )
        )

        assertEquals(
            CommentCampaignState.COMPLETED_WITH_ERRORS,
            CommentCampaignStateMachine.deriveCampaignState(campaign)
        )
    }

    @Test
    fun campaign_with_uncertain_send_pauses_instead_of_completing() {
        val campaign = campaign(
            listOf(
                item(CommentItemState.SENT_VERIFIED, "item-1"),
                item(CommentItemState.SEND_UNCERTAIN, "item-2")
            )
        )

        assertEquals(
            CommentCampaignState.PAUSED,
            CommentCampaignStateMachine.deriveCampaignState(campaign)
        )
    }

    private fun item(
        state: CommentItemState,
        itemId: String = "item-1"
    ) = CommentCampaignItem(
        itemId = itemId,
        creatorId = "creator-$itemId",
        creatorLabel = "creator $itemId",
        videoId = "video-$itemId",
        videoLabel = "first video",
        commentText = "20-year Tesla price?",
        state = state
    )

    private fun campaign(items: List<CommentCampaignItem>) = CommentCampaign(
        campaignId = "campaign-1",
        platform = "xiaohongshu",
        accountId = "account-1",
        query = "automotive creators",
        targetCount = items.size,
        state = CommentCampaignState.RUNNING,
        items = items
    )
}
