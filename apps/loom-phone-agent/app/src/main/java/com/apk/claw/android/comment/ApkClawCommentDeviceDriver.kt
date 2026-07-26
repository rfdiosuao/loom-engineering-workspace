package com.apk.claw.android.comment

fun interface CommentDeviceStepExecutor {
    fun execute(
        plan: CommentDeviceStepPlan,
        campaign: CommentCampaign,
        item: CommentCampaignItem
    ): CommentDeviceStepResult
}

class ApkClawCommentDeviceDriver(
    private val executor: CommentDeviceStepExecutor
) : CommentDeviceDriver {
    override fun plan(
        campaign: CommentCampaign,
        item: CommentCampaignItem
    ): CommentDeviceStepPlan = when (item.state) {
        CommentItemState.DISCOVERED ->
            CommentDeviceStepPlan("discovered", "begin_navigation", item.itemId)
        CommentItemState.NAVIGATING ->
            CommentDeviceStepPlan("navigation", "navigate_video", item.videoId)
        CommentItemState.VIDEO_VERIFIED ->
            CommentDeviceStepPlan("video", "open_comment_composer", "comment")
        CommentItemState.COMPOSER_OPEN ->
            CommentDeviceStepPlan("comment_sheet", "focus_comment_input", item.itemId)
        CommentItemState.INPUT_FOCUSED ->
            CommentDeviceStepPlan("input_focused", "input_and_verify_text", item.itemId)
        CommentItemState.SENDING ->
            CommentDeviceStepPlan("text_verified", "send_and_verify", item.itemId)
        else -> throw IllegalStateException("No device action for comment state ${item.state}")
    }

    override fun execute(
        plan: CommentDeviceStepPlan,
        campaign: CommentCampaign,
        item: CommentCampaignItem
    ): CommentDeviceStepResult = executor.execute(plan, campaign, item)
}
