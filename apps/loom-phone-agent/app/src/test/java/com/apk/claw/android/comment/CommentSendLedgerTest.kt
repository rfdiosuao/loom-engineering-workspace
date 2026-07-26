package com.apk.claw.android.comment

import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class CommentSendLedgerTest {
    private lateinit var tempDir: File

    @Before
    fun setUp() {
        tempDir = Files.createTempDirectory("comment-send-ledger").toFile()
    }

    @After
    fun tearDown() {
        tempDir.deleteRecursively()
    }

    @Test
    fun verified_send_remains_blocked_after_restart() {
        CommentSendLedger(tempDir).markSent("idem-1", "visible comment")

        assertEquals(
            SendPermission.BLOCK_ALREADY_SENT,
            CommentSendLedger(tempDir).maySend("idem-1")
        )
    }

    @Test
    fun uncertain_send_is_never_automatically_replayed() {
        CommentSendLedger(tempDir).markUncertain("idem-1", "timeout")

        assertEquals(
            SendPermission.BLOCK_UNCERTAIN,
            CommentSendLedger(tempDir).maySend("idem-1")
        )
    }

    @Test
    fun verified_send_cannot_be_downgraded_to_uncertain() {
        val ledger = CommentSendLedger(tempDir)
        ledger.markSent("idem-1", "visible comment")
        ledger.markUncertain("idem-1", "late timeout")

        assertEquals(SendPermission.BLOCK_ALREADY_SENT, ledger.maySend("idem-1"))
    }

    @Test
    fun new_idempotency_key_is_allowed() {
        assertEquals(SendPermission.ALLOW, CommentSendLedger(tempDir).maySend("idem-new"))
    }
}
