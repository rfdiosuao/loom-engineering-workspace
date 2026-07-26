package com.apk.claw.android.comment

import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class CommentCampaignStoreTest {
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("comment-campaign-store").toFile()
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    @Test
    fun reload_resumes_the_last_verified_item_state() {
        val store = CommentCampaignStore(tempDir)
        store.save(campaign(CommentItemState.TEXT_VERIFIED))

        val restored = CommentCampaignStore(tempDir).load("campaign-1")

        assertEquals(CommentItemState.TEXT_VERIFIED, restored!!.items.single().state)
    }

    @Test
    fun saving_one_campaign_preserves_other_campaigns() {
        val store = CommentCampaignStore(tempDir)
        store.save(campaign(CommentItemState.NAVIGATING, "campaign-1"))
        store.save(campaign(CommentItemState.COMPOSER_OPEN, "campaign-2"))

        assertEquals(2, store.list().size)
        assertEquals(CommentItemState.NAVIGATING, store.load("campaign-1")!!.items.single().state)
    }

    @Test
    fun corrupt_primary_recovers_the_latest_synced_backup() {
        val store = CommentCampaignStore(tempDir)
        store.save(campaign(CommentItemState.TEXT_VERIFIED))
        File(tempDir, "comment_campaigns.json").writeText("{broken")

        val recoveredStore = CommentCampaignStore(tempDir)
        val restored = recoveredStore.load("campaign-1")

        assertEquals(CommentItemState.TEXT_VERIFIED, restored!!.items.single().state)
        assertEquals("checkpoint_recovered_from_backup", recoveredStore.lastRecoveryCode)
        assertTrue(File(tempDir, "comment_campaigns.json.corrupt").exists())
    }

    private fun campaign(
        state: CommentItemState,
        campaignId: String = "campaign-1"
    ) = CommentCampaign(
        campaignId = campaignId,
        platform = "xiaohongshu",
        accountId = "account-1",
        query = "automotive creators",
        targetCount = 1,
        state = CommentCampaignState.RUNNING,
        items = listOf(
            CommentCampaignItem(
                itemId = "item-1",
                creatorId = "creator-1",
                creatorLabel = "creator 1",
                videoId = "video-1",
                videoLabel = "first video",
                commentText = "20-year Tesla price?",
                state = state
            )
        )
    )
}
