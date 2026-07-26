package com.apk.claw.android.comment

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class CommentManifestAuthorizerTest {

    @Test
    fun exact_sealed_manifest_can_be_confirmed() {
        val manifest = CommentManifestAuthorizer.seal(manifest())

        val approval = CommentManifestAuthorizer.confirm(manifest, manifest.items.map { it.itemHash })

        assertTrue(CommentManifestAuthorizer.isAuthorized(manifest, approval))
    }

    @Test
    fun weak_manifest_can_be_confirmed_without_item_hashes() {
        val manifest = CommentManifestAuthorizer.seal(manifest().copy(confirmationMode = "weak"))

        val approval = CommentManifestAuthorizer.confirm(manifest, null)

        assertTrue(CommentManifestAuthorizer.isAuthorized(manifest, approval))
        assertTrue(approval.confirmationMode == "weak")
        assertTrue(approval.itemHashes == manifest.items.map { it.itemHash }.toSet())
    }

    @Test
    fun weak_manifest_rejects_incorrect_optional_item_hashes() {
        val manifest = CommentManifestAuthorizer.seal(manifest().copy(confirmationMode = "weak"))

        expectIllegalArgument("confirmation_must_cover_exact_manifest") {
            CommentManifestAuthorizer.confirm(manifest, listOf("changed-item"))
        }
    }

    @Test
    fun changed_comment_invalidates_confirmation() {
        val original = CommentManifestAuthorizer.seal(manifest(comment = "20-year Tesla price?"))
        val approval = CommentManifestAuthorizer.confirm(original, original.items.map { it.itemHash })
        val changed = CommentManifestAuthorizer.seal(manifest(comment = "How much is a 2020 Tesla?"))

        assertNotEquals(original.manifestHash, changed.manifestHash)
        assertFalse(CommentManifestAuthorizer.isAuthorized(changed, approval))
    }

    @Test
    fun partial_item_confirmation_is_rejected() {
        val manifest = CommentManifestAuthorizer.seal(manifest(targetCount = 2))

        expectIllegalArgument("confirmation_must_cover_exact_manifest") {
            CommentManifestAuthorizer.confirm(manifest, listOf(manifest.items.first().itemHash))
        }
    }

    @Test
    fun duplicate_targets_are_rejected() {
        val duplicate = item("item-1", "creator-1", "video-1")
        val manifest = manifest(targetCount = 2).copy(items = listOf(duplicate, duplicate.copy(itemId = "item-2")))

        expectIllegalArgument("duplicate_comment_target") {
            CommentManifestAuthorizer.seal(manifest)
        }
    }

    @Test
    fun more_than_five_targets_are_rejected() {
        val items = (1..6).map { index -> item("item-$index", "creator-$index", "video-$index") }

        expectIllegalArgument("target_count_out_of_range") {
            CommentManifestAuthorizer.seal(manifest(targetCount = 6).copy(items = items))
        }
    }

    @Test
    fun manifest_hash_is_independent_of_item_input_order() {
        val first = CommentManifestAuthorizer.seal(manifest(targetCount = 2))
        val second = CommentManifestAuthorizer.seal(manifest(targetCount = 2).copy(items = first.items.reversed()))

        assertTrue(first.manifestHash == second.manifestHash)
    }

    private fun manifest(
        comment: String = "20-year Tesla price?",
        targetCount: Int = 1
    ): CommentManifest {
        val items = (1..targetCount).map { index ->
            item("item-$index", "creator-$index", "video-$index", comment)
        }
        return CommentManifest(
            campaignId = "campaign-1",
            platform = "xiaohongshu",
            accountId = "account-1",
            query = "automotive creators",
            targetCount = targetCount,
            commentText = comment,
            items = items
        )
    }

    private fun item(
        itemId: String,
        creatorId: String,
        videoId: String,
        comment: String = "20-year Tesla price?"
    ) = CommentManifestItem(
        itemId = itemId,
        creatorId = creatorId,
        creatorLabel = creatorId,
        videoId = videoId,
        videoLabel = "first video",
        commentText = comment
    )

    private fun expectIllegalArgument(message: String, block: () -> Unit) {
        try {
            block()
            fail("Expected IllegalArgumentException: $message")
        } catch (error: IllegalArgumentException) {
            assertTrue(error.message.orEmpty().contains(message))
        }
    }
}
