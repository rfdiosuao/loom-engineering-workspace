package com.apk.claw.android.comment

enum class CommentCampaignState {
    DRAFT,
    DISCOVERING,
    AWAITING_CONFIRMATION,
    RUNNING,
    PAUSED,
    COMPLETED,
    COMPLETED_WITH_ERRORS,
    FAILED,
    CANCELLED
}

enum class CommentItemState {
    DISCOVERED,
    NAVIGATING,
    VIDEO_VERIFIED,
    COMPOSER_OPEN,
    INPUT_FOCUSED,
    TEXT_VERIFIED,
    SEND_AUTHORIZED,
    SENDING,
    SENT_VERIFIED,
    SEND_UNCERTAIN,
    FAILED,
    SKIPPED
}

data class CommentManifestItem(
    val itemId: String,
    val creatorId: String,
    val creatorLabel: String,
    val videoId: String,
    val videoLabel: String,
    val commentText: String,
    val itemHash: String = "",
    val idempotencyKey: String = ""
)

data class CommentManifest(
    val campaignId: String,
    val platform: String,
    val accountId: String,
    val query: String,
    val targetCount: Int,
    val commentText: String,
    val items: List<CommentManifestItem>,
    val manifestHash: String = "",
    val createdAt: Long = 0L,
    val confirmationMode: String? = null
)

data class CommentManifestApproval(
    val manifestHash: String,
    val itemHashes: Set<String>,
    val confirmedAt: Long,
    val confirmationMode: String? = null
)

data class CommentCampaignItem(
    val itemId: String,
    val creatorId: String,
    val creatorLabel: String,
    val videoId: String,
    val videoLabel: String,
    val commentText: String,
    val state: CommentItemState = CommentItemState.DISCOVERED,
    val itemHash: String = "",
    val idempotencyKey: String = "",
    val attempts: Int = 0,
    val errorCode: String = "",
    val message: String = "",
    val updatedAt: Long = 0L
)

data class CommentCampaign(
    val campaignId: String,
    val platform: String,
    val accountId: String,
    val query: String,
    val targetCount: Int,
    val state: CommentCampaignState,
    val items: List<CommentCampaignItem>,
    val manifestHash: String = "",
    val approval: CommentManifestApproval? = null,
    val currentTargetIndex: Int = 0,
    val errorCode: String = "",
    val message: String = "",
    val createdAt: Long = 0L,
    val updatedAt: Long = 0L,
    val confirmationMode: String? = null
)

data class CommentTransitionResult(
    val accepted: Boolean,
    val item: CommentCampaignItem,
    val errorCode: String = "",
    val message: String = ""
)
