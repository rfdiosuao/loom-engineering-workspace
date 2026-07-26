package com.apk.claw.android.comment

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken
import java.io.File
import java.util.concurrent.ConcurrentHashMap

class CommentCampaignStore(
    directory: File,
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create()
) {
    private val root = directory.canonicalFile
    private val snapshot = AtomicJsonSnapshot(root, FILE_NAME)
    private val lock = locks.computeIfAbsent(root.path) { Any() }

    @Volatile
    var lastRecoveryCode: String = ""
        private set

    fun save(campaign: CommentCampaign) = synchronized(lock) {
        require(campaign.campaignId.isNotBlank()) { "campaign_id_required" }
        val campaigns = loadLocked().associateBy { it.campaignId }.toMutableMap()
        campaigns[campaign.campaignId] = campaign
        snapshot.write(gson.toJson(campaigns.values.sortedBy { it.campaignId }))
    }

    fun load(campaignId: String): CommentCampaign? = synchronized(lock) {
        loadLocked().firstOrNull { it.campaignId == campaignId }
    }

    fun list(): List<CommentCampaign> = synchronized(lock) {
        loadLocked()
    }

    private fun loadLocked(): List<CommentCampaign> {
        val read = snapshot.read(::parse) ?: return emptyList()
        lastRecoveryCode = if (read.recoveredFromBackup) {
            "checkpoint_recovered_from_backup"
        } else {
            ""
        }
        return read.value
    }

    private fun parse(json: String): List<CommentCampaign> {
        val type = object : TypeToken<List<CommentCampaign>>() {}.type
        val campaigns: List<CommentCampaign> = gson.fromJson(json, type)
            ?: throw IllegalStateException("comment_campaign_store_empty")
        require(campaigns.all { it.campaignId.isNotBlank() }) { "invalid_comment_campaign" }
        require(campaigns.map { it.campaignId }.distinct().size == campaigns.size) {
            "duplicate_comment_campaign"
        }
        return campaigns
    }

    companion object {
        private const val FILE_NAME = "comment_campaigns.json"
        private val locks = ConcurrentHashMap<String, Any>()
    }
}
