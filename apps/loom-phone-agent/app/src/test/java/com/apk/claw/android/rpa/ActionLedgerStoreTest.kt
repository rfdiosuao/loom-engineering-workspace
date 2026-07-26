package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.google.gson.Gson
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest

class ActionLedgerStoreTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun prepare_load_and_compare_transition_are_monotonic() {
        val store = store("monotonic")
        val prepared = entry()

        assertEquals(prepared, store.prepare(prepared))
        assertEquals(prepared, store.load(prepared.key))
        val dispatching = prepared.copy(state = ActionLedgerState.DISPATCHING, dispatchedAt = 1_100L)
        assertEquals(
            ActionLedgerTransition.UPDATED,
            store.compareAndTransition(prepared.key, ActionLedgerState.PREPARED, dispatching).status
        )
        val verified = dispatching.copy(
            state = ActionLedgerState.VERIFIED,
            finishedAt = 1_200L,
            errorCode = ActionLedgerErrors.VERIFIED
        )
        assertEquals(
            ActionLedgerTransition.UPDATED,
            store.compareAndTransition(prepared.key, ActionLedgerState.DISPATCHING, verified).status
        )

        val rollback = assertThrows(IllegalStateException::class.java) {
            store.compareAndTransition(prepared.key, ActionLedgerState.VERIFIED, prepared)
        }
        assertEquals("ledger_terminal_immutable", rollback.message)
        assertEquals(verified, store.load(prepared.key))
    }

    @Test
    fun same_identity_cannot_overwrite_newer_metadata_or_terminal_state() {
        val store = store("identity-conflict")
        val original = entry()
        store.prepare(original)

        val conflict = assertThrows(IllegalStateException::class.java) {
            store.prepare(original.copy(uiGeneration = original.uiGeneration + 1L))
        }
        assertEquals("ledger_attempt_duplicate", conflict.message)

        val terminal = original.copy(
            state = ActionLedgerState.FAILED_NO_DISPATCH,
            dispatchedAt = 1_100L,
            finishedAt = 1_200L,
            errorCode = "dispatch_rejected"
        )
        store.compareAndTransition(original.key, ActionLedgerState.PREPARED, terminal)
        assertThrows(IllegalStateException::class.java) {
            store.compareAndTransition(
                original.key,
                ActionLedgerState.FAILED_NO_DISPATCH,
                terminal.copy(errorCode = ActionLedgerErrors.NO_EFFECT)
            )
        }
    }

    @Test
    fun transition_cannot_rewrite_the_original_prepared_timestamp() {
        val store = store("prepared-time-immutable")
        val original = entry()
        store.prepare(original)
        val rewritten = original.copy(
            state = ActionLedgerState.DISPATCHING,
            preparedAt = original.preparedAt - 1L,
            dispatchedAt = original.preparedAt + 100L
        )

        val error = assertThrows(IllegalStateException::class.java) {
            store.compareAndTransition(original.key, ActionLedgerState.PREPARED, rewritten)
        }

        assertEquals("ledger_identity_conflict", error.message)
        assertEquals(original, store.load(original.key))
    }

    @Test
    fun attempts_reject_duplicates_gaps_lower_values_and_non_retryable_predecessors() {
        val store = store("attempt-order")
        val first = entry(attempt = 1)
        store.prepare(first)

        assertThrows(IllegalStateException::class.java) { store.prepare(first) }
        assertThrows(IllegalStateException::class.java) { store.prepare(entry(attempt = 3)) }
        assertThrows(IllegalStateException::class.java) { store.prepare(entry(attempt = 2)) }

        val dispatching = first.copy(state = ActionLedgerState.DISPATCHING, dispatchedAt = 1_100L)
        store.compareAndTransition(first.key, ActionLedgerState.PREPARED, dispatching)
        val retryable = dispatching.copy(
            state = ActionLedgerState.FAILED_NO_EFFECT,
            finishedAt = 1_200L,
            errorCode = ActionLedgerErrors.NO_EFFECT
        )
        store.compareAndTransition(first.key, ActionLedgerState.DISPATCHING, retryable)
        assertEquals(entry(attempt = 2), store.prepare(entry(attempt = 2)))
        assertThrows(IllegalStateException::class.java) { store.prepare(entry(attempt = 1)) }
        assertThrows(IllegalStateException::class.java) { store.prepare(entry(attempt = 4)) }
    }

    @Test
    fun missing_identity_cannot_be_synthesized_as_terminal_and_no_public_write_exists() {
        val store = store("no-terminal-backdoor")
        val terminal = terminal("missing", ActionLedgerState.VERIFIED, 2_000L)

        assertThrows(IllegalStateException::class.java) {
            store.compareAndTransition(terminal.key, ActionLedgerState.DISPATCHING, terminal)
        }
        assertFalse(ActionLedgerStore::class.java.methods.any { it.name == "write" })
        assertTrue(store.loadAll().isEmpty())
    }

    @Test
    fun dispatching_entry_recovers_as_uncertain_while_prepared_remains_resumable() {
        val store = store("process-death", clock = { 5_000L })
        val dispatching = entry(stepId = "dispatching")
        val prepared = entry(stepId = "prepared")
        store.prepare(dispatching)
        assertThrows(IllegalStateException::class.java) {
            store.claimDispatch(dispatching.key, 1_100L) { claim ->
                claim.markDispatchInvoked(1_100L)
                throw IllegalStateException("simulated process death")
            }
        }
        store.prepare(prepared)

        val first = store.recoverIncompleteRuns()
        val second = store.recoverIncompleteRuns()

        assertEquals(first, second)
        assertEquals(ActionLedgerState.UNCERTAIN, store.load(dispatching.key)?.state)
        assertEquals(5_000L, store.load(dispatching.key)?.finishedAt)
        assertEquals(ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH, store.load(dispatching.key)?.errorCode)
        assertEquals(ActionLedgerState.PREPARED, store.load(prepared.key)?.state)
    }

    @Test
    fun checksum_corruption_is_quarantined_and_valid_backup_is_recovered() {
        val root = temporaryFolder.newFolder("backup-recovery")
        val store = ActionLedgerStore(root)
        store.prepare(entry())
        val run = File(root, "runs").listFiles()!!.single()
        val primary = File(run, "action-ledger.json")
        primary.copyTo(File(run, "action-ledger.json.bak-test"))
        primary.writeText(primary.readText().replace("RESOURCE_ID", "TEXT_CLASS"))

        assertEquals(ResolverKind.RESOURCE_ID, store.load(entry().key)?.resolverUsed)
        assertFalse(File(run, "action-ledger.json.bak-test").exists())

        primary.writeText(
            primary.readText().replace(Regex("(?<=\\\"checksum\\\":\\\")[0-9a-f]{64}"), "0".repeat(64))
        )
        val prune = store.prune(now = 10_000L)
        assertFalse(prune.capMet)
        assertTrue(prune.quarantineReasons.contains("ledger_checksum_mismatch"))
        assertTrue(primary.exists())
    }

    @Test
    fun serialization_never_contains_dispatch_payload_or_sensitive_fields() {
        val root = temporaryFolder.newFolder("sanitized")
        val store = ActionLedgerStore(root)
        store.prepare(entry())
        val run = File(root, "runs").listFiles()!!.single()
        val text = File(run, "action-ledger.json").readText()

        listOf("payload", "selector", "screenshot", "rawParams", "account", "secret-token").forEach {
            assertFalse("unexpected persisted field: $it", text.contains(it, ignoreCase = true))
        }
        assertTrue(text.contains("\"checksum\""))
    }

    @Test
    fun schema_v1_ledgers_remain_readable_with_conservative_dispatch_evidence() {
        val root = temporaryFolder.newFolder("schema-v1")
        val store = ActionLedgerStore(root)
        val original = entry()
        store.prepare(original)
        store.claimDispatch(original.key, 1_100L) { claim ->
            claim.markDispatchInvoked(1_100L)
            claim.finish(
                ActionLedgerState.FAILED_NO_DISPATCH,
                1_200L,
                ActionLedgerErrors.DISPATCH_REJECTED
            )
        }
        val ledgerFile = File(File(root, "runs").listFiles()!!.single(), "action-ledger.json")
        val rootJson = JsonParser.parseString(ledgerFile.readText()).asJsonObject
        rootJson.addProperty("schemaVersion", 1)
        rootJson.getAsJsonArray("entries").forEach { entryJson ->
            entryJson.asJsonObject.remove("dispatchInvoked")
        }
        rootJson.remove("checksum")
        val body = Gson().toJson(rootJson)
        val checksum = MessageDigest.getInstance("SHA-256")
            .digest(body.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
        rootJson.addProperty("checksum", checksum)
        ledgerFile.writeText(Gson().toJson(rootJson))

        val migrated = ActionLedgerStore(root).load(original.key)!!

        assertEquals(ActionLedgerState.FAILED_NO_DISPATCH, migrated.state)
        assertTrue(migrated.dispatchInvoked)
        assertEquals(ActionLedgerErrors.DISPATCH_REJECTED, migrated.errorCode)
    }

    @Test
    fun unsafe_ids_and_invalid_numeric_fields_are_rejected() {
        val store = store("validation")
        listOf("../run", "run/child", "", "a".repeat(129)).forEach { runId ->
            assertThrows(IllegalArgumentException::class.java) { store.prepare(entry(runId = runId)) }
        }
        assertThrows(IllegalArgumentException::class.java) { store.prepare(entry(attempt = 0)) }
        assertThrows(IllegalArgumentException::class.java) { store.prepare(entry(uiGeneration = -1L)) }
        assertThrows(IllegalArgumentException::class.java) { store.prepare(entry(preparedAt = -1L)) }
    }

    @Test
    fun canonical_alias_and_symlink_run_directories_are_never_followed_or_deleted() {
        val root = temporaryFolder.newFolder("aliases")
        val runs = File(root, "runs").apply { mkdirs() }
        val outside = temporaryFolder.newFolder("outside-ledger")
        val alias = File(runs, entry().runId)
        try {
            Files.createSymbolicLink(alias.toPath(), outside.toPath())
        } catch (error: Exception) {
            assumeNoException(error)
        }
        val store = ActionLedgerStore(root)

        assertThrows(IllegalArgumentException::class.java) { store.prepare(entry()) }
        assertTrue(outside.exists())
        assertFalse(store.prune(now = 100_000L).capMet)
        assertTrue(outside.exists())
    }

    @Test
    fun mixed_run_pruning_compacts_only_expired_terminal_entries() {
        val day = 24L * 60L * 60L * 1_000L
        val now = 40L * day
        val store = store("mixed-retention")
        persistTerminal(store, terminal("old-complete", ActionLedgerState.VERIFIED, now - 8L * day))
        persistTerminal(store, terminal("young-complete", ActionLedgerState.VERIFIED, now - day))
        persistTerminal(store, terminal("old-uncertain", ActionLedgerState.UNCERTAIN, now - 8L * day))
        store.prepare(entry(stepId = "prepared", preparedAt = 0L))

        store.prune(now = now)

        assertNull(store.load(ActionIdentity("run-1", "old-complete", 1)))
        assertEquals(3, store.loadAll().size)
        assertEquals(ActionLedgerState.UNCERTAIN, store.load(ActionIdentity("run-1", "old-uncertain", 1))?.state)
        assertEquals(ActionLedgerState.PREPARED, store.load(ActionIdentity("run-1", "prepared", 1))?.state)
        assertEquals(ActionLedgerState.VERIFIED, store.load(ActionIdentity("run-1", "young-complete", 1))?.state)
    }

    @Test
    fun uncertain_entries_expire_after_thirty_days_and_empty_run_directory_is_removed() {
        val day = 24L * 60L * 60L * 1_000L
        val now = 40L * day
        val root = temporaryFolder.newFolder("uncertain-retention")
        val store = ActionLedgerStore(root)
        persistTerminal(store, terminal("uncertain", ActionLedgerState.UNCERTAIN, now - 31L * day))

        val result = store.prune(now = now)

        assertTrue(result.deleted.any { it.stepId == entry(stepId = "uncertain").stepId })
        assertTrue(File(root, "runs").listFiles().isNullOrEmpty())
    }

    @Test
    fun future_timestamps_do_not_expire_when_wall_clock_moves_backward() {
        val day = 24L * 60L * 60L * 1_000L
        val store = store("clock-rollback")
        val future = terminal("future", ActionLedgerState.VERIFIED, 50L * day)
        persistTerminal(store, future)

        store.prune(now = 40L * day)

        assertEquals(future, store.load(future.key))
    }

    @Test
    fun shared_cap_counts_assets_but_never_deletes_them_and_reports_impossible_cap() {
        val day = 24L * 60L * 60L * 1_000L
        val now = 40L * day
        val root = temporaryFolder.newFolder("shared-cap")
        val asset = File(root, "assets/template/r1/anchor.webp")
        asset.parentFile!!.mkdirs()
        asset.writeBytes(ByteArray(512))
        val store = ActionLedgerStore(root)
        persistTerminal(store, terminal("expired", ActionLedgerState.VERIFIED, now - 8L * day))

        val result = store.prune(maxBytes = 128L, now = now)

        assertFalse(result.capMet)
        assertEquals("protected_or_other_bytes_exceed_cap", result.reason)
        assertTrue(asset.exists())
        assertTrue(result.bytesAfter >= 512L)
    }

    @Test
    fun shared_cap_prunes_only_expired_run_entry_before_reporting_asset_and_young_bytes() {
        val day = 24L * 60L * 60L * 1_000L
        val now = 40L * day
        val root = temporaryFolder.newFolder("combined-cap-order")
        val asset = File(root, "assets/template/r1/anchor.webp")
        asset.parentFile!!.mkdirs()
        asset.writeBytes(ByteArray(512))
        val store = ActionLedgerStore(root)
        persistTerminal(store, terminal("expired", ActionLedgerState.VERIFIED, now - 8L * day))
        persistTerminal(store, terminal("young", ActionLedgerState.VERIFIED, now - day))

        val result = store.prune(maxBytes = 128L, now = now)

        assertNull(store.load(ActionIdentity("run-1", "expired", 1)))
        assertEquals(ActionLedgerState.VERIFIED, store.load(ActionIdentity("run-1", "young", 1))?.state)
        assertTrue(asset.exists())
        assertFalse(result.capMet)
        assertEquals("protected_or_other_bytes_exceed_cap", result.reason)
    }

    @Test
    fun high_fanout_scan_fails_closed_without_deleting_runs() {
        val root = temporaryFolder.newFolder("fanout")
        val runs = File(root, "runs").apply { mkdirs() }
        repeat(ActionLedgerStore.MAX_DIRECTORY_FANOUT + 1) { index ->
            File(runs, "run-$index").mkdir()
        }
        val result = ActionLedgerStore(root).prune(now = 10_000L)

        assertFalse(result.capMet)
        assertEquals("scan_limit_exceeded", result.reason)
        assertEquals(ActionLedgerStore.MAX_DIRECTORY_FANOUT + 1, runs.listFiles()?.size)
    }

    private fun store(name: String, clock: () -> Long = { 10_000L }): ActionLedgerStore =
        ActionLedgerStore(temporaryFolder.newFolder(name), clock = clock)

    private fun entry(
        runId: String = "run-1",
        stepId: String = "step-1",
        attempt: Int = 1,
        uiGeneration: Long = 7L,
        preparedAt: Long = 1_000L
    ): ActionLedgerEntry {
        val key = ActionIdentity(runId, stepId, attempt).toOpaqueLedgerKey()
        return ActionLedgerEntry(
        runId = key.runKey,
        stepId = key.stepKey,
        attempt = attempt,
        state = ActionLedgerState.PREPARED,
        preparedAt = preparedAt,
        uiGeneration = uiGeneration,
        serviceGeneration = opaqueLedgerValue("service", "service-1"),
        resolverUsed = ResolverKind.RESOURCE_ID
        )
    }

    private fun terminal(stepId: String, state: ActionLedgerState, finishedAt: Long): ActionLedgerEntry =
        entry(stepId = stepId, preparedAt = (finishedAt - 200L).coerceAtLeast(0L)).copy(
            state = state,
            dispatchedAt = (finishedAt - 100L).coerceAtLeast(0L),
            finishedAt = finishedAt,
            errorCode = when (state) {
                ActionLedgerState.VERIFIED -> ActionLedgerErrors.VERIFIED
                ActionLedgerState.UNCERTAIN -> "verification_unknown"
                ActionLedgerState.FAILED_NO_DISPATCH -> "dispatch_rejected"
                ActionLedgerState.FAILED_NO_EFFECT -> "no_effect"
                else -> error("terminal state required")
            }
        )

    private fun persistTerminal(store: ActionLedgerStore, terminal: ActionLedgerEntry) {
        val prepared = terminal.copy(
            state = ActionLedgerState.PREPARED,
            dispatchedAt = 0L,
            finishedAt = 0L,
            errorCode = ""
        )
        store.prepare(prepared)
        val dispatching = prepared.copy(
            state = ActionLedgerState.DISPATCHING,
            dispatchedAt = terminal.dispatchedAt
        )
        store.compareAndTransition(prepared.key, ActionLedgerState.PREPARED, dispatching)
        store.compareAndTransition(prepared.key, ActionLedgerState.DISPATCHING, terminal)
    }
}
