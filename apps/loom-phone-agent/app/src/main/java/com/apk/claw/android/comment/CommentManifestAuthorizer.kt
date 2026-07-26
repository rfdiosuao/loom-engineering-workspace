package com.apk.claw.android.comment

import java.security.MessageDigest
import java.text.Normalizer
import java.util.Locale

object CommentManifestAuthorizer {
    private const val MAX_TARGETS = 5
    const val MODE_WEAK = "weak"
    const val MODE_STRICT = "strict"

    fun seal(manifest: CommentManifest): CommentManifest {
        require(manifest.targetCount in 1..MAX_TARGETS) { "target_count_out_of_range" }
        require(manifest.items.size == manifest.targetCount) { "target_count_mismatch" }
        require(manifest.campaignId.isNotBlank()) { "campaign_id_required" }
        require(manifest.platform.isNotBlank()) { "platform_required" }
        require(manifest.accountId.isNotBlank()) { "account_id_required" }
        require(manifest.commentText.isNotBlank()) { "comment_text_required" }
        val confirmationMode = normalizeConfirmationMode(manifest.confirmationMode)

        val targetKeys = manifest.items.map { item ->
            listOf(normalizeId(item.creatorId), normalizeId(item.videoId)).joinToString("|")
        }
        require(targetKeys.distinct().size == targetKeys.size) { "duplicate_comment_target" }

        val normalizedComment = normalizeText(manifest.commentText)
        val sealedItems = manifest.items.map { item ->
            require(item.itemId.isNotBlank()) { "item_id_required" }
            require(item.creatorId.isNotBlank()) { "creator_id_required" }
            require(item.videoId.isNotBlank()) { "video_id_required" }
            require(normalizeText(item.commentText) == normalizedComment) { "item_comment_mismatch" }
            val idempotencyKey = hash(
                listOf(
                    normalizeId(manifest.accountId),
                    normalizeId(manifest.platform),
                    normalizeId(item.creatorId),
                    normalizeId(item.videoId),
                    normalizedComment
                ).joinToString("\n")
            )
            val itemHash = hash(
                listOf(
                    normalizeId(item.itemId),
                    normalizeId(item.creatorId),
                    normalizeText(item.creatorLabel),
                    normalizeId(item.videoId),
                    normalizeText(item.videoLabel),
                    normalizedComment,
                    idempotencyKey
                ).joinToString("\n")
            )
            item.copy(
                commentText = normalizedComment,
                itemHash = itemHash,
                idempotencyKey = idempotencyKey
            )
        }.sortedBy { normalizeId(it.itemId) }

        require(sealedItems.map { it.itemHash }.distinct().size == sealedItems.size) {
            "duplicate_comment_item"
        }

        val manifestHash = hash(
            listOf(
                normalizeId(manifest.campaignId),
                normalizeId(manifest.platform),
                normalizeId(manifest.accountId),
                normalizeText(manifest.query),
                manifest.targetCount.toString(),
                normalizedComment,
                confirmationMode,
                sealedItems.joinToString("\n") { it.itemHash }
            ).joinToString("\n")
        )
        return manifest.copy(
            platform = normalizeId(manifest.platform),
            accountId = normalizeId(manifest.accountId),
            query = normalizeText(manifest.query),
            commentText = normalizedComment,
            items = sealedItems,
            manifestHash = manifestHash,
            confirmationMode = confirmationMode
        )
    }

    fun confirm(
        manifest: CommentManifest,
        itemHashes: Collection<String>?,
        now: Long = System.currentTimeMillis()
    ): CommentManifestApproval {
        val sealed = seal(manifest)
        require(manifest.manifestHash == sealed.manifestHash) { "manifest_not_sealed" }
        val expected = sealed.items.map { it.itemHash }.toSet()
        val supplied = itemHashes.orEmpty()
        val requested = supplied.map(String::trim).filter(String::isNotBlank).toSet()
        val requiresExactItems = sealed.confirmationMode == MODE_STRICT || supplied.isNotEmpty()
        if (requiresExactItems) {
            require(requested == expected && supplied.size == expected.size) {
                "confirmation_must_cover_exact_manifest"
            }
        }
        return CommentManifestApproval(
            manifestHash = sealed.manifestHash,
            itemHashes = expected,
            confirmedAt = now,
            confirmationMode = sealed.confirmationMode
        )
    }

    fun isAuthorized(manifest: CommentManifest, approval: CommentManifestApproval?): Boolean {
        if (approval == null) return false
        val sealed = runCatching { seal(manifest) }.getOrNull() ?: return false
        val expected = sealed.items.map { it.itemHash }.toSet()
        return manifest.manifestHash == sealed.manifestHash &&
            approval.manifestHash == sealed.manifestHash &&
            approval.itemHashes == expected &&
            normalizeConfirmationMode(approval.confirmationMode) == sealed.confirmationMode
    }

    fun normalizeConfirmationMode(value: String?): String = when (value?.trim()?.lowercase(Locale.US)) {
        null, "", MODE_STRICT -> MODE_STRICT
        MODE_WEAK -> MODE_WEAK
        else -> throw IllegalArgumentException("invalid_confirmation_mode")
    }

    private fun normalizeId(value: String): String =
        normalizeText(value).lowercase(Locale.US)

    private fun normalizeText(value: String): String =
        Normalizer.normalize(value, Normalizer.Form.NFKC)
            .trim()
            .replace(Regex("\\s+"), " ")

    private fun hash(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(Locale.US, it.toInt() and 0xff) }
}
