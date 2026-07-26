package com.apk.claw.android.comment

data class CommentDeviceStepPlan(
    val pageState: String,
    val action: String,
    val target: String
)

sealed interface CommentDeviceStepResult {
    data class Advance(
        val nextState: CommentItemState,
        val evidence: String
    ) : CommentDeviceStepResult

    data class Retry(
        val errorCode: String,
        val message: String,
        val evidence: String = ""
    ) : CommentDeviceStepResult

    data class NeedsHuman(
        val errorCode: String,
        val message: String,
        val evidence: String = ""
    ) : CommentDeviceStepResult

    data class Failed(
        val errorCode: String,
        val message: String,
        val evidence: String = ""
    ) : CommentDeviceStepResult

    data class SendVerified(val evidence: String) : CommentDeviceStepResult
    data class SendUncertain(val evidence: String) : CommentDeviceStepResult
}

interface CommentDeviceDriver {
    fun plan(campaign: CommentCampaign, item: CommentCampaignItem): CommentDeviceStepPlan

    fun execute(
        plan: CommentDeviceStepPlan,
        campaign: CommentCampaign,
        item: CommentCampaignItem
    ): CommentDeviceStepResult
}
