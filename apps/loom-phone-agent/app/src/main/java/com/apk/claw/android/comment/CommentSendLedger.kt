package com.apk.claw.android.comment

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken
import java.io.File
import java.util.concurrent.ConcurrentHashMap

enum class SendDisposition {
    SENT_VERIFIED,
    SEND_UNCERTAIN
}

enum class SendPermission {
    ALLOW,
    BLOCK_ALREADY_SENT,
    BLOCK_UNCERTAIN
}

data class CommentSendRecord(
    val idempotencyKey: String,
    val disposition: SendDisposition,
    val evidence: String,
    val updatedAt: Long
)

class CommentSendLedger(
    directory: File,
    private val gson: Gson = GsonBuilder().setPrettyPrinting().create()
) {
    private val root = directory.canonicalFile
    private val snapshot = AtomicJsonSnapshot(root, FILE_NAME)
    private val lock = locks.computeIfAbsent(root.path) { Any() }

    fun maySend(idempotencyKey: String): SendPermission = synchronized(lock) {
        when (loadLocked()[idempotencyKey]?.disposition) {
            SendDisposition.SENT_VERIFIED -> SendPermission.BLOCK_ALREADY_SENT
            SendDisposition.SEND_UNCERTAIN -> SendPermission.BLOCK_UNCERTAIN
            null -> SendPermission.ALLOW
        }
    }

    fun markSent(
        idempotencyKey: String,
        evidence: String,
        now: Long = System.currentTimeMillis()
    ) = synchronized(lock) {
        val records = loadLocked().toMutableMap()
        if (records[idempotencyKey]?.disposition == SendDisposition.SEND_UNCERTAIN) return@synchronized
        records[idempotencyKey] = CommentSendRecord(
            idempotencyKey,
            SendDisposition.SENT_VERIFIED,
            evidence,
            now
        )
        saveLocked(records)
    }

    fun markUncertain(
        idempotencyKey: String,
        evidence: String,
        now: Long = System.currentTimeMillis()
    ) = synchronized(lock) {
        val records = loadLocked().toMutableMap()
        if (records[idempotencyKey]?.disposition == SendDisposition.SENT_VERIFIED) return@synchronized
        records[idempotencyKey] = CommentSendRecord(
            idempotencyKey,
            SendDisposition.SEND_UNCERTAIN,
            evidence,
            now
        )
        saveLocked(records)
    }

    fun resolveUncertainAsSent(
        idempotencyKey: String,
        evidence: String,
        now: Long = System.currentTimeMillis()
    ) = synchronized(lock) {
        val records = loadLocked().toMutableMap()
        require(records[idempotencyKey]?.disposition == SendDisposition.SEND_UNCERTAIN) {
            "send_is_not_uncertain"
        }
        records[idempotencyKey] = CommentSendRecord(
            idempotencyKey,
            SendDisposition.SENT_VERIFIED,
            evidence,
            now
        )
        saveLocked(records)
    }

    fun get(idempotencyKey: String): CommentSendRecord? = synchronized(lock) {
        loadLocked()[idempotencyKey]
    }

    private fun loadLocked(): Map<String, CommentSendRecord> {
        val read = snapshot.read(::parse) ?: return emptyMap()
        return read.value.associateBy { it.idempotencyKey }
    }

    private fun parse(json: String): List<CommentSendRecord> {
        val type = object : TypeToken<List<CommentSendRecord>>() {}.type
        val records: List<CommentSendRecord> = gson.fromJson(json, type)
            ?: throw IllegalStateException("comment_send_ledger_empty")
        require(records.all { it.idempotencyKey.isNotBlank() }) { "invalid_send_record" }
        require(records.map { it.idempotencyKey }.distinct().size == records.size) {
            "duplicate_send_record"
        }
        return records
    }

    private fun saveLocked(records: Map<String, CommentSendRecord>) {
        snapshot.write(gson.toJson(records.values.sortedBy { it.idempotencyKey }))
    }

    companion object {
        private const val FILE_NAME = "comment_send_ledger.json"
        private val locks = ConcurrentHashMap<String, Any>()
    }
}
