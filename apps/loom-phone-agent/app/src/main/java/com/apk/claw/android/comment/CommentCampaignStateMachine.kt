package com.apk.claw.android.comment

object CommentCampaignStateMachine {
    private val allowedTransitions = mapOf(
        CommentItemState.DISCOVERED to setOf(CommentItemState.NAVIGATING, CommentItemState.SKIPPED, CommentItemState.FAILED),
        CommentItemState.NAVIGATING to setOf(CommentItemState.VIDEO_VERIFIED, CommentItemState.FAILED),
        CommentItemState.VIDEO_VERIFIED to setOf(CommentItemState.COMPOSER_OPEN, CommentItemState.FAILED),
        CommentItemState.COMPOSER_OPEN to setOf(CommentItemState.INPUT_FOCUSED, CommentItemState.FAILED),
        CommentItemState.INPUT_FOCUSED to setOf(CommentItemState.TEXT_VERIFIED, CommentItemState.FAILED),
        CommentItemState.TEXT_VERIFIED to setOf(CommentItemState.SEND_AUTHORIZED, CommentItemState.FAILED),
        CommentItemState.SEND_AUTHORIZED to setOf(CommentItemState.SENDING, CommentItemState.FAILED),
        CommentItemState.SENDING to setOf(
            CommentItemState.SENT_VERIFIED,
            CommentItemState.SEND_UNCERTAIN,
            CommentItemState.FAILED
        )
    )

    fun canTransition(item: CommentCampaignItem, next: CommentItemState): Boolean =
        next in allowedTransitions[item.state].orEmpty()

    fun transition(
        item: CommentCampaignItem,
        next: CommentItemState,
        now: Long = System.currentTimeMillis(),
        errorCode: String = "",
        message: String = ""
    ): CommentTransitionResult {
        if (!canTransition(item, next)) {
            return CommentTransitionResult(
                accepted = false,
                item = item,
                errorCode = "invalid_comment_state_transition",
                message = "Cannot transition comment item from ${item.state} to $next"
            )
        }
        return CommentTransitionResult(
            accepted = true,
            item = item.copy(
                state = next,
                errorCode = errorCode,
                message = message,
                updatedAt = now
            )
        )
    }

    fun deriveCampaignState(campaign: CommentCampaign): CommentCampaignState {
        if (campaign.state == CommentCampaignState.CANCELLED) return CommentCampaignState.CANCELLED
        if (campaign.items.any { it.state == CommentItemState.SEND_UNCERTAIN }) {
            return CommentCampaignState.PAUSED
        }
        if (campaign.items.isEmpty()) return campaign.state
        val terminalStates = setOf(
            CommentItemState.SENT_VERIFIED,
            CommentItemState.FAILED,
            CommentItemState.SKIPPED
        )
        if (campaign.items.all { it.state in terminalStates }) {
            return if (campaign.items.any { it.state == CommentItemState.FAILED }) {
                CommentCampaignState.COMPLETED_WITH_ERRORS
            } else {
                CommentCampaignState.COMPLETED
            }
        }
        return if (campaign.state == CommentCampaignState.AWAITING_CONFIRMATION) {
            CommentCampaignState.AWAITING_CONFIRMATION
        } else {
            CommentCampaignState.RUNNING
        }
    }
}
