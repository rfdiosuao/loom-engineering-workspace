package com.apk.claw.android.rpa

import android.system.Os
import android.system.OsConstants
import com.apk.claw.android.workflow.ResolverKind
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.channels.FileLock
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.locks.ReentrantLock

class ActionLedgerStore(
    rootDirectory: File,
    private val rename: (File, File) -> Boolean = { source, destination -> source.renameTo(destination) },
    private val canonicalize: (File) -> File = { file -> file.canonicalFile },
    private val clock: () -> Long = System::currentTimeMillis,
    private val claimLockRelease: (FileLock) -> Unit = { lock -> lock.release() }
) {
    private val root = canonicalize(rootDirectory).absoluteFile
    private val runsRoot = File(root, RUNS_DIRECTORY).absoluteFile
    private val lockFile = File(root, LOCK_FILE_NAME).absoluteFile
    private val claimsRoot = File(root, CLAIMS_DIRECTORY).absoluteFile
    private val processLock = processLockFor(pathIdentity(root))
    private val gson = Gson()

    init {
        require(isDescendant(runsRoot, root)) { "ledger_runs_root_invalid" }
    }

    fun prepare(entry: ActionLedgerEntry): ActionLedgerEntry = withStoreLock {
        prepareLocked(entry, allowExisting = false)
    }

    internal fun prepareForExecution(entry: ActionLedgerEntry): ActionLedgerEntry = withStoreLock {
        prepareLocked(entry, allowExisting = true)
    }

    private fun prepareLocked(entry: ActionLedgerEntry, allowExisting: Boolean): ActionLedgerEntry {
        entry.validateLedgerEntry()
        require(entry.state == ActionLedgerState.PREPARED) { "ledger_prepare_state_invalid" }
        val ledger = loadRunLedger(entry.runId, create = true).writableOrEmpty(entry.runId)
        val attempts = ledger.entries.filter { it.stepId == entry.stepId }.sortedBy { it.attempt }
        val existing = attempts.firstOrNull { it.attempt == entry.attempt }
        if (existing != null) {
            if (allowExisting && existing.samePreparedMetadata(entry)) return existing
            throw IllegalStateException("ledger_attempt_duplicate")
        }
        if (entry.attempt == 1) {
            if (attempts.isNotEmpty()) throw IllegalStateException("ledger_attempt_out_of_order")
        } else {
            val previous = attempts.lastOrNull()
            if (previous == null || previous.attempt != entry.attempt - 1) {
                throw IllegalStateException("ledger_attempt_out_of_order")
            }
            if (previous.state != ActionLedgerState.FAILED_NO_DISPATCH &&
                previous.state != ActionLedgerState.FAILED_NO_EFFECT
            ) {
                throw IllegalStateException("ledger_attempt_not_retryable")
            }
        }
        require(ledger.entries.size < MAX_ENTRIES_PER_RUN) { "ledger_entry_limit_exceeded" }
        saveLedger(ledger.copy(entries = ledger.entries + entry))
        return entry
    }

    fun load(identity: ActionIdentity): ActionLedgerEntry? = withStoreLock {
        loadOpaqueLocked(identity.toOpaqueLedgerKey())
    }

    internal fun load(key: OpaqueLedgerKey): ActionLedgerEntry? = withStoreLock {
        loadOpaqueLocked(key)
    }

    private fun loadOpaqueLocked(key: OpaqueLedgerKey): ActionLedgerEntry? {
        key.validateLedgerKey()
        return when (val state = loadRunLedger(key.runKey, create = false)) {
            is LedgerLoad.Valid -> state.ledger.entries.firstOrNull { it.key == key }
            LedgerLoad.Missing, is LedgerLoad.Corrupt -> null
        }
    }

    fun loadAll(): List<ActionLedgerEntry> = withStoreLock {
        when (val scan = scanRuns()) {
            is RunScan.Success -> scan.runs.flatMap { run ->
                when (run) {
                    is ScannedRun.Valid -> run.ledger.entries
                    is ScannedRun.Quarantined -> emptyList()
                }
            }.sortedWith(entryOrder)
            is RunScan.Failure -> emptyList()
        }
    }

    fun compareAndTransition(
        identity: ActionIdentity,
        expected: ActionLedgerState,
        updated: ActionLedgerEntry
    ): ActionLedgerTransitionResult = compareAndTransition(identity.toOpaqueLedgerKey(), expected, updated)

    internal fun compareAndTransition(
        key: OpaqueLedgerKey,
        expected: ActionLedgerState,
        updated: ActionLedgerEntry
    ): ActionLedgerTransitionResult = withStoreLock {
        key.validateLedgerKey()
        updated.validateLedgerEntry()
        require(key == updated.key) { "ledger_identity_conflict" }
        val ledger = loadRunLedger(key.runKey, create = false).requireWritable()
        val current = ledger.entries.firstOrNull { it.key == key }
            ?: throw IllegalStateException("ledger_entry_missing")
        if (current.state != expected) {
            return@withStoreLock ActionLedgerTransitionResult(ActionLedgerTransition.EXPECTATION_MISMATCH, current)
        }
        if (current == updated) {
            return@withStoreLock ActionLedgerTransitionResult(ActionLedgerTransition.UNCHANGED, current)
        }
        validateReplacement(current, updated)
        saveLedger(ledger.withEntry(updated))
        ActionLedgerTransitionResult(ActionLedgerTransition.UPDATED, updated)
    }

    fun recoverIncompleteRuns(): List<ActionLedgerEntry> {
        val scan = withStoreLock { scanRuns() }
        if (scan is RunScan.Failure) throw IllegalStateException(scan.reason)
        scan as RunScan.Success
        val dispatching = scan.runs.flatMap { run ->
            (run as? ScannedRun.Valid)?.ledger?.entries.orEmpty()
        }.filter { it.state == ActionLedgerState.DISPATCHING }.sortedWith(entryOrder)
        for (entry in dispatching) {
            val key = entry.key
            if (activeClaimKeys.get()!!.contains(activeClaimIdentity(key))) continue
            withClaimOwnership(key) {
                withStoreLock {
                    val ledger = loadRunLedger(key.runKey, create = false).requireWritable()
                    val current = ledger.entries.firstOrNull { it.key == key } ?: return@withStoreLock
                    if (current.state == ActionLedgerState.DISPATCHING) {
                        val recovered = current.copy(
                            state = if (current.dispatchInvoked) ActionLedgerState.UNCERTAIN
                            else ActionLedgerState.FAILED_NO_DISPATCH,
                            finishedAt = terminalTime(current, clock()),
                            errorCode = if (current.dispatchInvoked) {
                                ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH
                            } else {
                                ActionLedgerErrors.CLAIM_DURABILITY_FAILURE
                            }
                        )
                        saveLedger(ledger.withEntry(recovered))
                    }
                }
            }
        }
        return loadAll()
    }

    @JvmOverloads
    fun prune(
        maxBytes: Long = DEFAULT_MAX_BYTES,
        now: Long = System.currentTimeMillis()
    ): ActionLedgerPruneResult = withStoreLock {
        require(maxBytes >= 0L) { "ledger_cap_invalid" }
        require(now >= 0L) { "ledger_prune_time_invalid" }
        pruneLocked(maxBytes, now)
    }

    internal fun <T> claimDispatch(
        key: OpaqueLedgerKey,
        dispatchedAt: Long,
        block: (DispatchClaimScope) -> T
    ): DispatchClaimResult<T> {
        key.validateLedgerKey()
        require(dispatchedAt >= 0L) { "ledger_dispatched_at_invalid" }
        val activeClaimId = activeClaimIdentity(key)
        if (activeClaimKeys.get()!!.contains(activeClaimId)) {
            return DispatchClaimResult.Reentrant(load(key))
        }
        return withClaimOwnership(key) {
            val start = withStoreLock {
                val ledger = loadRunLedger(key.runKey, create = false).requireWritable()
                val current = ledger.entries.firstOrNull { it.key == key }
                    ?: throw IllegalStateException("ledger_entry_missing")
                when {
                    current.state.terminal -> ClaimStart.Existing(current)
                    current.state == ActionLedgerState.DISPATCHING -> {
                        val recovered = current.copy(
                            state = if (current.dispatchInvoked) ActionLedgerState.UNCERTAIN
                            else ActionLedgerState.FAILED_NO_DISPATCH,
                            finishedAt = terminalTime(current, clock()),
                            errorCode = if (current.dispatchInvoked) {
                                ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH
                            } else {
                                ActionLedgerErrors.CLAIM_DURABILITY_FAILURE
                            }
                        )
                        saveLedger(ledger.withEntry(recovered))
                        ClaimStart.Existing(recovered)
                    }
                    else -> {
                        val dispatching = current.copy(
                            state = ActionLedgerState.DISPATCHING,
                            dispatchedAt = maxOf(dispatchedAt, current.preparedAt),
                            dispatchInvoked = false,
                            finishedAt = 0L,
                            errorCode = ""
                        )
                        saveLedger(ledger.withEntry(dispatching))
                        ClaimStart.Owned(dispatching)
                    }
                }
            }
            when (start) {
                is ClaimStart.Existing -> DispatchClaimResult.Existing(start.entry)
                is ClaimStart.Owned -> {
                    val scope = DispatchClaimScope(start.entry) { terminal ->
                        withStoreLock {
                            terminal.validateLedgerEntry()
                            val ledger = loadRunLedger(key.runKey, create = false).requireWritable()
                            val current = ledger.entries.firstOrNull { it.key == key }
                                ?: throw IllegalStateException("ledger_entry_missing")
                            validateReplacement(current, terminal)
                            saveLedger(ledger.withEntry(terminal))
                            terminal
                        }
                    }
                    DispatchClaimResult.Claimed(block(scope))
                }
            }
        }
    }

    internal fun reconcileAfterFailure(
        key: OpaqueLedgerKey,
        finishedAt: Long,
        noDispatchErrorCode: String,
        uncertainErrorCode: String
    ): LedgerFailureResolution {
        require(noDispatchErrorCode in ActionLedgerErrors.persistent) { "ledger_error_code_invalid" }
        require(uncertainErrorCode in ActionLedgerErrors.persistent) { "ledger_error_code_invalid" }
        key.validateLedgerKey()
        val activeClaimId = activeClaimIdentity(key)
        if (activeClaimKeys.get()!!.contains(activeClaimId)) {
            return LedgerFailureResolution.Reentrant(load(key))
        }
        return withClaimOwnership(key) {
            withStoreLock {
                val ledger = when (val loaded = loadRunLedger(key.runKey, create = false)) {
                    is LedgerLoad.Valid -> loaded.ledger
                    LedgerLoad.Missing -> return@withStoreLock LedgerFailureResolution.Absent
                    is LedgerLoad.Corrupt -> throw IllegalStateException("ledger_quarantined:${loaded.reason}")
                }
                val current = ledger.entries.firstOrNull { it.key == key }
                    ?: return@withStoreLock LedgerFailureResolution.Absent
                when {
                    current.state.terminal || current.state == ActionLedgerState.PREPARED ->
                        LedgerFailureResolution.Entry(current)
                    else -> {
                        val reconciled = current.copy(
                            state = if (current.dispatchInvoked) ActionLedgerState.UNCERTAIN
                            else ActionLedgerState.FAILED_NO_DISPATCH,
                            finishedAt = terminalTime(current, finishedAt),
                            errorCode = if (current.dispatchInvoked) uncertainErrorCode else noDispatchErrorCode
                        )
                        saveLedger(ledger.withEntry(reconciled))
                        LedgerFailureResolution.Entry(reconciled)
                    }
                }
            }
        }
    }

    internal fun reconcileAfterOwnershipFailure(
        key: OpaqueLedgerKey,
        finishedAt: Long,
        noDispatchErrorCode: String,
        uncertainErrorCode: String
    ): LedgerFailureResolution = withStoreLock {
        require(noDispatchErrorCode in ActionLedgerErrors.persistent) { "ledger_error_code_invalid" }
        require(uncertainErrorCode in ActionLedgerErrors.persistent) { "ledger_error_code_invalid" }
        key.validateLedgerKey()
        val ledger = when (val loaded = loadRunLedger(key.runKey, create = false)) {
            is LedgerLoad.Valid -> loaded.ledger
            LedgerLoad.Missing -> return@withStoreLock LedgerFailureResolution.Absent
            is LedgerLoad.Corrupt -> throw IllegalStateException("ledger_quarantined:${loaded.reason}")
        }
        val current = ledger.entries.firstOrNull { it.key == key }
            ?: return@withStoreLock LedgerFailureResolution.Absent
        if (current.state.terminal || current.state == ActionLedgerState.PREPARED) {
            return@withStoreLock LedgerFailureResolution.Entry(current)
        }
        val reconciled = current.copy(
            state = if (current.dispatchInvoked) ActionLedgerState.UNCERTAIN
            else ActionLedgerState.FAILED_NO_DISPATCH,
            finishedAt = terminalTime(current, finishedAt),
            errorCode = if (current.dispatchInvoked) uncertainErrorCode else noDispatchErrorCode
        )
        saveLedger(ledger.withEntry(reconciled))
        LedgerFailureResolution.Entry(reconciled)
    }

    private fun pruneLocked(maxBytes: Long, now: Long): ActionLedgerPruneResult {
        val initialScan = scanRuns()
        if (initialScan is RunScan.Failure) return pruneFailure(initialScan.reason)
        initialScan as RunScan.Success
        val before = countSharedBytes()
        if (before is ByteCount.Failure) return pruneFailure(before.reason)
        before as ByteCount.Success
        val deleted = mutableListOf<ActionLedgerEntry>()
        val quarantineReasons = initialScan.runs.mapNotNull {
            (it as? ScannedRun.Quarantined)?.reason
        }.toSortedSet()

        for (run in initialScan.runs.sortedBy { it.runId }) {
            if (run !is ScannedRun.Valid) continue
            val expired = run.ledger.entries.filter { isExpired(it, now) }.toSet()
            if (expired.isEmpty()) continue
            val retained = run.ledger.entries.filterNot { it in expired }
            if (retained.isEmpty()) {
                if (deleteRunDirectory(run.directory)) deleted += expired
            } else {
                saveLedger(run.ledger.copy(entries = retained))
                deleted += expired
            }
        }

        val finalScan = scanRuns()
        if (finalScan is RunScan.Failure) return pruneFailure(finalScan.reason)
        finalScan as RunScan.Success
        val after = countSharedBytes()
        if (after is ByteCount.Failure) return pruneFailure(after.reason)
        after as ByteCount.Success
        val retained = finalScan.runs.flatMap {
            (it as? ScannedRun.Valid)?.ledger?.entries.orEmpty()
        }.sortedWith(entryOrder)
        val finalQuarantine = (quarantineReasons + finalScan.runs.mapNotNull {
            (it as? ScannedRun.Quarantined)?.reason
        }).toSortedSet()
        val capMet = after.bytes <= maxBytes && finalQuarantine.isEmpty()
        val reason = when {
            finalQuarantine.isNotEmpty() -> "quarantined_ledgers"
            after.bytes > maxBytes -> "protected_or_other_bytes_exceed_cap"
            else -> ""
        }
        return ActionLedgerPruneResult(
            retained = retained,
            deleted = deleted.sortedWith(entryOrder),
            bytesBefore = before.bytes,
            bytesAfter = after.bytes,
            capMet = capMet,
            reason = reason,
            quarantineReasons = finalQuarantine
        )
    }

    private fun pruneFailure(reason: String) = ActionLedgerPruneResult(
        retained = emptyList(),
        deleted = emptyList(),
        bytesBefore = 0L,
        bytesAfter = 0L,
        capMet = false,
        reason = reason,
        quarantineReasons = if (reason == "scan_limit_exceeded") emptySet() else setOf(reason)
    )

    private fun isExpired(entry: ActionLedgerEntry, now: Long): Boolean {
        if (!entry.state.terminal) return false
        val age = (now - entry.finishedAt).coerceAtLeast(0L)
        val retention = if (entry.state == ActionLedgerState.UNCERTAIN) UNCERTAIN_RETENTION_MS else COMPLETED_RETENTION_MS
        return age >= retention
    }

    private fun validateReplacement(current: ActionLedgerEntry, updated: ActionLedgerEntry) {
        if (!current.samePreparedMetadata(updated)) throw IllegalStateException("ledger_identity_conflict")
        if (current.preparedAt != updated.preparedAt) throw IllegalStateException("ledger_identity_conflict")
        if (current == updated) return
        if (current.state.terminal) throw IllegalStateException("ledger_terminal_immutable")
        val invocationMark = current.state == ActionLedgerState.DISPATCHING &&
            updated.state == ActionLedgerState.DISPATCHING &&
            !current.dispatchInvoked && updated.dispatchInvoked
        if (!invocationMark && !isAllowedLedgerTransition(current.state, updated.state)) {
            throw IllegalStateException("ledger_illegal_transition")
        }
        if (updated.dispatchedAt < current.dispatchedAt || updated.finishedAt < current.finishedAt) {
            throw IllegalStateException("ledger_time_rollback")
        }
        if (current.dispatchInvoked && !updated.dispatchInvoked) {
            throw IllegalStateException("ledger_dispatch_invocation_rollback")
        }
        if (!current.dispatchInvoked && updated.dispatchInvoked && !invocationMark) {
            throw IllegalStateException("ledger_dispatch_invocation_without_boundary")
        }
        if (current.state == updated.state && !invocationMark) {
            throw IllegalStateException("ledger_illegal_transition")
        }
    }

    private fun loadRunLedger(runId: String, create: Boolean): LedgerLoad {
        ActionIdentity(runId, "validation", 1).validateLedgerIdentity()
        val directory = runDirectory(runId, create)
        if (!directory.exists()) return LedgerLoad.Missing
        if (!directory.isDirectory) return LedgerLoad.Corrupt("ledger_run_unreadable")
        return loadLedger(directory, runId)
    }

    private fun loadLedger(directory: File, runId: String): LedgerLoad {
        val children = when (val result = boundedChildren(directory, MAX_RUN_DIRECTORY_FILES)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout -> return LedgerLoad.Corrupt("scan_limit_exceeded")
            ChildResult.Unreadable -> return LedgerLoad.Corrupt("ledger_run_unreadable")
        }
        val unexpected = children.firstOrNull { child ->
            child.name != LEDGER_NAME &&
                !child.name.startsWith("$LEDGER_NAME$BACKUP_PREFIX") &&
                !child.name.startsWith("$LEDGER_NAME$TEMP_PREFIX") &&
                child.name != "$LEDGER_NAME.bak"
        }
        if (unexpected != null) return LedgerLoad.Corrupt("ledger_unexpected_file")
        if (children.any { isAliasOrOutside(it, directory) }) return LedgerLoad.Corrupt("canonical_alias")
        val primary = safeFile(directory, LEDGER_NAME)
        val backups = children.filter {
            it.name == "$LEDGER_NAME.bak" || it.name.startsWith("$LEDGER_NAME$BACKUP_PREFIX")
        }.sortedBy { it.name }
        if (backups.size > MAX_RECOVERY_FILES) return LedgerLoad.Corrupt("scan_limit_exceeded")
        val candidates = mutableListOf<Pair<File, RunLedger>>()
        val primaryRead = readLedger(primary, runId)
        if (primaryRead is LedgerRead.Valid) candidates += primary to primaryRead.ledger
        backups.forEach { backup ->
            val read = readLedger(backup, runId)
            if (read is LedgerRead.Valid) candidates += backup to read.ledger
        }
        if (candidates.isEmpty()) {
            if (!primary.exists() && backups.isEmpty()) return LedgerLoad.Missing
            val reason = when (primaryRead) {
                is LedgerRead.Invalid -> primaryRead.reason
                LedgerRead.Missing -> "ledger_backup_unreadable"
                is LedgerRead.Valid -> error("candidate must exist")
            }
            return LedgerLoad.Corrupt(reason)
        }
        val selected = candidates.maxWithOrNull(
            compareBy<Pair<File, RunLedger>> { it.second.generation }
                .thenBy { it.second.entries.size }
                .thenBy { sha256(ledgerBodyBytes(it.second)) }
                .thenBy { it.first.name }
        ) ?: return LedgerLoad.Corrupt("ledger_unreadable")
        if (!samePath(selected.first, primary)) {
            deleteIfPresent(primary)
            if (!moveChecked(selected.first, primary)) return LedgerLoad.Corrupt("ledger_recovery_failed")
        }
        children.asSequence()
            .filterNot { samePath(it, primary) }
            .filter { it.name.startsWith("$LEDGER_NAME$BACKUP_PREFIX") || it.name.startsWith("$LEDGER_NAME$TEMP_PREFIX") || it.name == "$LEDGER_NAME.bak" }
            .sortedBy { it.name }
            .forEach(::deleteIfPresent)
        return LedgerLoad.Valid(selected.second)
    }

    private fun saveLedger(source: RunLedger): RunLedger {
        require(source.entries.isNotEmpty()) { "ledger_empty_write_invalid" }
        require(source.entries.size <= MAX_ENTRIES_PER_RUN) { "ledger_entry_limit_exceeded" }
        source.entries.forEach { entry ->
            entry.validateLedgerEntry()
            require(entry.runId == source.runId) { "ledger_run_mismatch" }
        }
        require(source.entries.map { it.key }.toSet().size == source.entries.size) { "ledger_duplicate_identity" }
        require(source.generation < Long.MAX_VALUE) { "ledger_generation_exhausted" }
        val ledger = source.copy(
            generation = source.generation + 1L,
            entries = source.entries.sortedWith(entryOrder)
        )
        val directory = runDirectory(ledger.runId, create = true)
        val bytes = encodedLedgerBytes(ledger)
        require(bytes.size <= MAX_LEDGER_BYTES) { "ledger_file_too_large" }
        val transactionId = UUID.randomUUID().toString()
        val primary = safeFile(directory, LEDGER_NAME)
        val temporary = safeFile(directory, "$LEDGER_NAME$TEMP_PREFIX$transactionId")
        val backup = safeFile(directory, "$LEDGER_NAME$BACKUP_PREFIX$transactionId")
        writeSynced(temporary, bytes)
        val hadPrimary = primary.exists()
        try {
            if (hadPrimary && !moveChecked(primary, backup)) throw IllegalStateException("ledger_backup_failed")
            if (!moveChecked(temporary, primary)) {
                if (hadPrimary) rollback(backup, primary)
                throw IllegalStateException("ledger_replace_failed")
            }
            deleteIfPresent(backup)
        } finally {
            deleteIfPresent(temporary)
        }
        return ledger
    }

    private fun rollback(backup: File, primary: File) {
        deleteIfPresent(primary)
        if (backup.exists() && !moveChecked(backup, primary)) throw IllegalStateException("ledger_rollback_failed")
    }

    private fun readLedger(file: File, expectedRunId: String): LedgerRead {
        if (!file.exists()) return LedgerRead.Missing
        val bytes = readBounded(file, MAX_LEDGER_BYTES) ?: return LedgerRead.Invalid("ledger_unreadable")
        return try {
            val root = JsonParser.parseString(String(bytes, Charsets.UTF_8)).asJsonObject
            requireExactKeys(root, LEDGER_KEYS)
            val schemaVersion = root.requiredInt("schemaVersion")
            require(schemaVersion in MIN_READABLE_SCHEMA_VERSION..SCHEMA_VERSION)
            require(root.requiredString("runId") == expectedRunId)
            val generation = root.requiredLong("generation")
            require(generation > 0L)
            val array = root.get("entries")
            require(array != null && array.isJsonArray && array.asJsonArray.size() in 1..MAX_ENTRIES_PER_RUN)
            val entries = array.asJsonArray.map { value ->
                parseEntry(value.asJsonObject, expectedRunId, schemaVersion)
            }
            require(entries.map { it.key }.toSet().size == entries.size)
            val ledger = RunLedger(expectedRunId, generation, entries.sortedWith(entryOrder))
            val expected = root.requiredString("checksum")
            require(SHA256_PATTERN.matches(expected))
            val body = root.deepCopy().also { it.remove("checksum") }
            val actual = sha256(gson.toJson(body).toByteArray(Charsets.UTF_8))
            if (!MessageDigest.isEqual(actual.toByteArray(Charsets.US_ASCII), expected.toByteArray(Charsets.US_ASCII))) {
                return LedgerRead.Invalid("ledger_checksum_mismatch")
            }
            LedgerRead.Valid(ledger)
        } catch (_: Throwable) {
            LedgerRead.Invalid("ledger_structure_invalid")
        }
    }

    private fun parseEntry(root: JsonObject, runId: String, schemaVersion: Int): ActionLedgerEntry {
        requireExactKeys(root, if (schemaVersion == 1) ENTRY_KEYS_V1 else ENTRY_KEYS)
        val state = root.requiredEnum<ActionLedgerState>("state")
        val entry = ActionLedgerEntry(
            runId = root.requiredString("runId"),
            stepId = root.requiredString("stepId"),
            attempt = root.requiredInt("attempt"),
            state = state,
            preparedAt = root.requiredLong("preparedAt"),
            dispatchedAt = root.requiredLong("dispatchedAt"),
            dispatchInvoked = if (schemaVersion >= 2) {
                root.requiredBoolean("dispatchInvoked")
            } else {
                state != ActionLedgerState.PREPARED
            },
            finishedAt = root.requiredLong("finishedAt"),
            uiGeneration = root.requiredLong("uiGeneration"),
            serviceGeneration = root.requiredString("serviceGeneration"),
            resolverUsed = root.requiredEnum<ResolverKind>("resolverUsed"),
            errorCode = root.requiredString("errorCode")
        )
        require(entry.runId == runId)
        entry.validateLedgerEntry()
        return entry
    }

    private fun encodedLedgerBytes(ledger: RunLedger): ByteArray {
        val body = ledgerBody(ledger)
        body.addProperty("checksum", sha256(gson.toJson(body).toByteArray(Charsets.UTF_8)))
        return gson.toJson(body).toByteArray(Charsets.UTF_8)
    }

    private fun ledgerBodyBytes(ledger: RunLedger): ByteArray =
        gson.toJson(ledgerBody(ledger)).toByteArray(Charsets.UTF_8)

    private fun ledgerBody(ledger: RunLedger): JsonObject = JsonObject().apply {
        addProperty("schemaVersion", SCHEMA_VERSION)
        addProperty("runId", ledger.runId)
        addProperty("generation", ledger.generation)
        add("entries", JsonArray().apply {
            ledger.entries.sortedWith(entryOrder).forEach { entry -> add(entry.toJson()) }
        })
    }

    private fun ActionLedgerEntry.toJson() = JsonObject().apply {
        addProperty("runId", runId)
        addProperty("stepId", stepId)
        addProperty("attempt", attempt)
        addProperty("state", state.name)
        addProperty("preparedAt", preparedAt)
        addProperty("dispatchedAt", dispatchedAt)
        addProperty("dispatchInvoked", dispatchInvoked)
        addProperty("finishedAt", finishedAt)
        addProperty("uiGeneration", uiGeneration)
        addProperty("serviceGeneration", serviceGeneration)
        addProperty("resolverUsed", resolverUsed.name)
        addProperty("errorCode", errorCode)
    }

    private fun scanRuns(): RunScan {
        if (!runsRoot.exists()) return RunScan.Success(emptyList())
        if (isAliasOrOutside(runsRoot, root)) return RunScan.Failure("canonical_alias")
        val children = when (val result = boundedChildren(runsRoot, MAX_DIRECTORY_FANOUT)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout -> return RunScan.Failure("scan_limit_exceeded")
            ChildResult.Unreadable -> return RunScan.Failure("scan_unreadable")
        }
        val runs = mutableListOf<ScannedRun>()
        for (child in children.sortedBy { it.name }) {
            if (isAliasOrOutside(child, runsRoot)) {
                runs += ScannedRun.Quarantined(child.name, child, "canonical_alias")
                continue
            }
            if (!RUN_ID_PATTERN.matches(child.name) || !child.isDirectory) {
                runs += ScannedRun.Quarantined(child.name, child, "ledger_run_unreadable")
                continue
            }
            when (val load = loadLedger(child, child.name)) {
                is LedgerLoad.Valid -> runs += ScannedRun.Valid(child.name, child, load.ledger)
                LedgerLoad.Missing -> runs += ScannedRun.Quarantined(child.name, child, "ledger_missing")
                is LedgerLoad.Corrupt -> runs += ScannedRun.Quarantined(child.name, child, load.reason)
            }
        }
        return RunScan.Success(runs)
    }

    private fun countSharedBytes(): ByteCount {
        var count = 0L
        var entries = 0
        for (base in listOf(File(root, ASSETS_DIRECTORY), runsRoot, claimsRoot)) {
            if (!base.exists()) continue
            val pending = ArrayDeque<Pair<File, Int>>()
            pending.add(base.absoluteFile to 0)
            while (pending.isNotEmpty()) {
                val (current, depth) = pending.removeLast()
                entries++
                if (entries > MAX_SHARED_TREE_ENTRIES || depth > MAX_SHARED_TREE_DEPTH) {
                    return ByteCount.Failure("scan_limit_exceeded")
                }
                if (isAliasOrOutside(current, root)) return ByteCount.Failure("canonical_alias")
                if (current.isDirectory) {
                    when (val children = boundedChildren(current, MAX_DIRECTORY_FANOUT)) {
                        ChildResult.HighFanout -> return ByteCount.Failure("scan_limit_exceeded")
                        ChildResult.Unreadable -> return ByteCount.Failure("scan_unreadable")
                        is ChildResult.Valid -> children.children.sortedByDescending { it.name }
                            .forEach { pending.add(it.absoluteFile to depth + 1) }
                    }
                } else if (current.isFile) {
                    val length = measuredLength(current) ?: return ByteCount.Failure("scan_unreadable")
                    count = saturatedAdd(count, length)
                } else {
                    return ByteCount.Failure("scan_unreadable")
                }
            }
        }
        return ByteCount.Success(count)
    }

    private fun deleteRunDirectory(directory: File): Boolean {
        if (isAliasOrOutside(directory, runsRoot)) return false
        val children = when (val result = boundedChildren(directory, MAX_RUN_DIRECTORY_FILES)) {
            is ChildResult.Valid -> result.children
            else -> return false
        }
        if (children.any { isAliasOrOutside(it, directory) }) return false
        for (child in children.sortedBy { it.name }) {
            if (child.isDirectory || (child.exists() && !child.delete())) return false
        }
        return !directory.exists() || directory.delete()
    }

    private fun runDirectory(runId: String, create: Boolean): File {
        if (create) {
            ensureDirectory(root, root)
            ensureDirectory(runsRoot, root)
        }
        val directory = safeFile(runsRoot, runId)
        if (create) ensureDirectory(directory, runsRoot)
        return directory
    }

    private fun ensureDirectory(directory: File, parent: File) {
        if (!directory.isDirectory && !directory.mkdirs()) throw IllegalStateException("ledger_directory_create_failed")
        require(!isAliasOrOutside(directory, parent)) { "ledger_directory_alias" }
    }

    private fun safeFile(parent: File, name: String): File {
        val child = File(parent.absoluteFile, name).absoluteFile
        require(isDescendant(child, parent.absoluteFile)) { "ledger_path_outside_root" }
        return validateFileIdentity(child)
    }

    private fun boundedChildren(directory: File, limit: Int): ChildResult {
        val children = directory.listFiles() ?: return ChildResult.Unreadable
        if (children.size > limit) return ChildResult.HighFanout
        return ChildResult.Valid(children.toList())
    }

    private fun writeSynced(file: File, bytes: ByteArray) {
        require(bytes.size <= MAX_LEDGER_BYTES) { "ledger_file_too_large" }
        val lexical = validateFileIdentity(file)
        FileOutputStream(lexical).use { output ->
            output.write(bytes)
            output.fd.sync()
        }
    }

    private fun readBounded(file: File, maxBytes: Int): ByteArray? {
        val lexical = runCatching { validateFileIdentity(file) }.getOrNull() ?: return null
        if (!lexical.isFile || lexical.length() !in 0L..maxBytes.toLong()) return null
        return runCatching {
            FileInputStream(validateFileIdentity(lexical)).use { input ->
                val output = ByteArrayOutputStream(minOf(lexical.length().toInt(), 8_192))
                val buffer = ByteArray(8_192)
                var total = 0
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    total += read
                    if (total > maxBytes) return null
                    output.write(buffer, 0, read)
                }
                output.toByteArray()
            }
        }.getOrNull()
    }

    private fun measuredLength(file: File): Long? = runCatching {
        val lexical = validateFileIdentity(file)
        RandomAccessFile(lexical, "r").use { handle ->
            validateFileIdentity(lexical)
            handle.length().takeIf { it >= 0L }
        }
    }.getOrNull()

    private fun moveChecked(source: File, destination: File): Boolean =
        rename(validateFileIdentity(source), validateFileIdentity(destination))

    private fun deleteIfPresent(file: File) {
        val lexical = validateFileIdentity(file)
        if (lexical.exists() && !lexical.delete()) throw IllegalStateException("ledger_cleanup_failed")
    }

    private fun validateFileIdentity(file: File): File {
        val lexical = file.absoluteFile
        require(isDescendant(lexical, root)) { "ledger_path_outside_root" }
        val canonical = canonicalize(lexical).absoluteFile
        require(isDescendant(canonical, root)) { "ledger_path_outside_root" }
        require(!isLexicalAlias(lexical, canonical)) { "ledger_path_alias" }
        return lexical
    }

    private fun isAliasOrOutside(file: File, parent: File): Boolean {
        val lexical = file.absoluteFile
        val canonical = runCatching { canonicalize(lexical).absoluteFile }.getOrNull() ?: return true
        return !isSameOrDescendant(lexical, parent) || !isSameOrDescendant(canonical, parent) ||
            isLexicalAlias(lexical, canonical)
    }

    private fun <T> withClaimOwnership(key: OpaqueLedgerKey, block: () -> T): T {
        key.validateLedgerKey()
        val claimFile = withStoreLock { claimShardFileLocked(key) }
        val activeClaimId = activeClaimIdentity(key)
        val inProcess = claimProcessLockFor(pathIdentity(claimFile))
        inProcess.lock()
        try {
            val handle = RandomAccessFile(validateFileIdentity(claimFile), "rw")
            val channel = handle.channel
            var fileLock: FileLock? = null
            var failure: Throwable? = null
            var result: Any? = null
            try {
                fileLock = channel.lock()
                validateFileIdentity(claimFile)
                activeClaimKeys.get()!!.add(activeClaimId)
                result = block()
            } catch (error: Throwable) {
                failure = error
            } finally {
                activeClaimKeys.get()!!.remove(activeClaimId)
                if (fileLock != null) {
                    try {
                        claimLockRelease(fileLock)
                    } catch (error: Throwable) {
                        if (failure == null) failure = error else failure.addSuppressed(error)
                        runCatching { if (fileLock.isValid) fileLock.release() }
                    }
                }
                try {
                    channel.close()
                } catch (error: Throwable) {
                    if (failure == null) failure = error else failure.addSuppressed(error)
                }
                try {
                    handle.close()
                } catch (error: Throwable) {
                    if (failure == null) failure = error else failure.addSuppressed(error)
                }
            }
            failure?.let { throw it }
            @Suppress("UNCHECKED_CAST")
            return result as T
        } finally {
            inProcess.unlock()
        }
    }

    private fun claimShardFileLocked(key: OpaqueLedgerKey): File {
        ensureDirectory(claimsRoot, root)
        val marker = safeFile(claimsRoot, CLAIM_SHARDS_MARKER)
        val children = when (val result = boundedChildren(claimsRoot, CLAIM_SHARD_COUNT + 1)) {
            is ChildResult.Valid -> result.children
            ChildResult.HighFanout -> throw IllegalStateException("ledger_claim_shard_set_invalid")
            ChildResult.Unreadable -> throw IllegalStateException("ledger_claim_directory_unreadable")
        }
        val expectedNames = CLAIM_SHARD_NAMES + CLAIM_SHARDS_MARKER
        if (marker.exists()) {
            require(children.map { it.name }.toSet() == expectedNames) { "ledger_claim_shard_set_invalid" }
        } else {
            require(children.all { it.name in CLAIM_SHARD_NAMES }) { "ledger_claim_shard_set_invalid" }
            for (name in CLAIM_SHARD_NAMES) {
                val shard = safeFile(claimsRoot, name)
                if (shard.exists()) {
                    require(shard.isFile) { "ledger_claim_shard_invalid" }
                } else {
                    RandomAccessFile(validateFileIdentity(shard), "rw").use { handle -> handle.fd.sync() }
                }
            }
            writeSynced(marker, CLAIM_SHARDS_VERSION)
        }
        for (name in CLAIM_SHARD_NAMES) {
            val shard = safeFile(claimsRoot, name)
            require(shard.isFile) { "ledger_claim_shard_invalid" }
        }
        require(marker.isFile) { "ledger_claim_shard_marker_invalid" }
        return safeFile(claimsRoot, key.claimShardName())
    }

    private fun activeClaimIdentity(key: OpaqueLedgerKey): String =
        "${pathIdentity(root)}:${key.claimShardName()}"

    private fun <T> withStoreLock(block: () -> T): T {
        processLock.lock()
        try {
            if (!root.isDirectory && !root.mkdirs()) throw IllegalStateException("ledger_root_create_failed")
            val lexicalLock = validateFileIdentity(lockFile)
            RandomAccessFile(lexicalLock, "rw").channel.use { channel ->
                validateFileIdentity(lexicalLock)
                val fileLock = channel.lock()
                try {
                    return block()
                } finally {
                    fileLock.release()
                }
            }
        } finally {
            processLock.unlock()
        }
    }

    private fun sha256(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val encoded = CharArray(digest.size * 2)
        for (index in digest.indices) {
            val value = digest[index].toInt() and 0xff
            encoded[index * 2] = HEX[value ushr 4]
            encoded[index * 2 + 1] = HEX[value and 0x0f]
        }
        return String(encoded)
    }

    private fun samePath(first: File, second: File): Boolean =
        first.absolutePath.equals(second.absolutePath, ignoreCase = File.separatorChar == '\\')

    private fun isLexicalAlias(lexical: File, canonical: File): Boolean {
        if (!samePath(lexical.absoluteFile, canonical.absoluteFile)) return true
        val androidSymlink = runCatching { OsConstants.S_ISLNK(Os.lstat(lexical.absolutePath).st_mode) }
            .getOrDefault(false)
        if (androidSymlink) return true
        return runCatching {
            val pathType = Class.forName("java.nio.file.Path")
            val path = File::class.java.getMethod("toPath").invoke(lexical)
            Class.forName("java.nio.file.Files").getMethod("isSymbolicLink", pathType).invoke(null, path) as Boolean
        }.getOrDefault(false)
    }

    private fun isSameOrDescendant(file: File, parent: File): Boolean = samePath(file, parent) || isDescendant(file, parent)

    private fun isDescendant(file: File, parent: File): Boolean {
        val prefix = parent.absolutePath.trimEnd(File.separatorChar) + File.separator
        return file.absolutePath.startsWith(prefix, ignoreCase = File.separatorChar == '\\')
    }

    private fun pathIdentity(file: File): String =
        if (File.separatorChar == '\\') file.absolutePath.lowercase() else file.absolutePath

    private fun saturatedAdd(first: Long, second: Long): Long =
        if (second < 0L || Long.MAX_VALUE - first < second) Long.MAX_VALUE else first + second

    private fun terminalTime(entry: ActionLedgerEntry, value: Long): Long =
        maxOf(value.coerceAtLeast(0L), entry.preparedAt, entry.dispatchedAt)

    private fun requireExactKeys(root: JsonObject, expected: Set<String>) {
        require(root.keySet() == expected)
    }

    private fun JsonObject.requiredString(name: String): String {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isString)
        return value.asString
    }

    private fun JsonObject.requiredInt(name: String): Int {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        return value.asString.toIntOrNull() ?: throw IllegalArgumentException("invalid_$name")
    }

    private fun JsonObject.requiredLong(name: String): Long {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        return value.asString.toLongOrNull() ?: throw IllegalArgumentException("invalid_$name")
    }

    private fun JsonObject.requiredBoolean(name: String): Boolean {
        val value = get(name)
        require(value != null && value.isJsonPrimitive && value.asJsonPrimitive.isBoolean)
        return value.asBoolean
    }

    private inline fun <reified T : Enum<T>> JsonObject.requiredEnum(name: String): T {
        val encoded = requiredString(name)
        return enumValues<T>().firstOrNull { it.name == encoded } ?: throw IllegalArgumentException("invalid_$name")
    }

    private fun LedgerLoad.requireWritable(): RunLedger = when (this) {
        is LedgerLoad.Valid -> ledger
        LedgerLoad.Missing -> throw IllegalStateException("ledger_entry_missing")
        is LedgerLoad.Corrupt -> throw IllegalStateException("ledger_quarantined:$reason")
    }

    private fun LedgerLoad.writableOrEmpty(runId: String): RunLedger = when (this) {
        is LedgerLoad.Valid -> ledger
        LedgerLoad.Missing -> RunLedger(runId, 0L, emptyList())
        is LedgerLoad.Corrupt -> throw IllegalStateException("ledger_quarantined:$reason")
    }

    private fun RunLedger.withEntry(entry: ActionLedgerEntry): RunLedger = copy(
        entries = entries.map { current -> if (current.key == entry.key) entry else current }
    )

    private data class RunLedger(
        val runId: String,
        val generation: Long,
        val entries: List<ActionLedgerEntry>
    )

    private sealed interface LedgerLoad {
        data class Valid(val ledger: RunLedger) : LedgerLoad
        data class Corrupt(val reason: String) : LedgerLoad
        data object Missing : LedgerLoad
    }

    private sealed interface LedgerRead {
        data class Valid(val ledger: RunLedger) : LedgerRead
        data class Invalid(val reason: String) : LedgerRead
        data object Missing : LedgerRead
    }

    private sealed interface ChildResult {
        data class Valid(val children: List<File>) : ChildResult
        data object HighFanout : ChildResult
        data object Unreadable : ChildResult
    }

    private sealed interface ScannedRun {
        val runId: String

        data class Valid(override val runId: String, val directory: File, val ledger: RunLedger) : ScannedRun
        data class Quarantined(override val runId: String, val directory: File, val reason: String) : ScannedRun
    }

    private sealed interface RunScan {
        data class Success(val runs: List<ScannedRun>) : RunScan
        data class Failure(val reason: String) : RunScan
    }

    private sealed interface ByteCount {
        data class Success(val bytes: Long) : ByteCount
        data class Failure(val reason: String) : ByteCount
    }

    companion object {
        const val DEFAULT_MAX_BYTES = 128L * 1024L * 1024L
        const val MAX_DIRECTORY_FANOUT = 256

        private const val RUNS_DIRECTORY = "runs"
        private const val ASSETS_DIRECTORY = "assets"
        private const val CLAIMS_DIRECTORY = ".action-claims"
        private const val LOCK_FILE_NAME = ".action-ledger.lock"
        private const val LEDGER_NAME = "action-ledger.json"
        private const val BACKUP_PREFIX = ".bak-"
        private const val TEMP_PREFIX = ".tmp-"
        private const val MIN_READABLE_SCHEMA_VERSION = 1
        private const val SCHEMA_VERSION = 2
        private const val MAX_LEDGER_BYTES = 1024 * 1024
        private const val MAX_ENTRIES_PER_RUN = 1024
        private const val MAX_RECOVERY_FILES = 8
        private const val MAX_RUN_DIRECTORY_FILES = 32
        private const val MAX_SHARED_TREE_ENTRIES = 65_536
        private const val MAX_SHARED_TREE_DEPTH = 8
        private const val DAY_MS = 24L * 60L * 60L * 1_000L
        private const val COMPLETED_RETENTION_MS = 7L * DAY_MS
        private const val UNCERTAIN_RETENTION_MS = 30L * DAY_MS
        private const val CLAIM_SHARDS_MARKER = ".initialized-v1"
        private val CLAIM_SHARDS_VERSION = byteArrayOf(1)

        private val RUN_ID_PATTERN = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
        private val SHA256_PATTERN = Regex("^[0-9a-f]{64}$")
        private val LEDGER_KEYS = setOf("schemaVersion", "runId", "generation", "entries", "checksum")
        private val ENTRY_KEYS_V1 = setOf(
            "runId", "stepId", "attempt", "state", "preparedAt", "dispatchedAt", "finishedAt",
            "uiGeneration", "serviceGeneration", "resolverUsed", "errorCode"
        )
        private val ENTRY_KEYS = ENTRY_KEYS_V1 + "dispatchInvoked"
        private val HEX = "0123456789abcdef".toCharArray()
        private val CLAIM_SHARD_NAMES = (0 until CLAIM_SHARD_COUNT).mapTo(sortedSetOf()) { index ->
            "claim-shard-${index.toString().padStart(2, '0')}.lock"
        }
        private val processLocks = HashMap<String, ReentrantLock>()
        private val claimProcessLocks = HashMap<String, ReentrantLock>()
        private val activeClaimKeys = ThreadLocal.withInitial { mutableSetOf<String>() }
        private val entryOrder = compareBy<ActionLedgerEntry> { it.runId }
            .thenBy { it.stepId }
            .thenBy { it.attempt }

        private fun processLockFor(path: String): ReentrantLock = synchronized(processLocks) {
            processLocks.getOrPut(path) { ReentrantLock(true) }
        }

        private fun claimProcessLockFor(path: String): ReentrantLock = synchronized(claimProcessLocks) {
            claimProcessLocks.getOrPut(path) { ReentrantLock(true) }
        }
    }
}

internal class DispatchClaimScope(
    initialEntry: ActionLedgerEntry,
    private val persist: (ActionLedgerEntry) -> ActionLedgerEntry
) {
    var entry: ActionLedgerEntry = initialEntry
        private set

    fun markDispatchInvoked(invokedAt: Long): ActionLedgerEntry {
        require(entry.state == ActionLedgerState.DISPATCHING) { "ledger_dispatch_mark_state_invalid" }
        if (entry.dispatchInvoked) return entry
        val marked = entry.copy(
            dispatchedAt = maxOf(invokedAt.coerceAtLeast(0L), entry.dispatchedAt, entry.preparedAt),
            dispatchInvoked = true
        )
        entry = persist(marked)
        return entry
    }

    fun finish(state: ActionLedgerState, finishedAt: Long, errorCode: String): ActionLedgerEntry {
        require(state.terminal) { "ledger_terminal_state_required" }
        val terminal = entry.copy(
            state = state,
            finishedAt = maxOf(finishedAt.coerceAtLeast(0L), entry.preparedAt, entry.dispatchedAt),
            errorCode = errorCode
        )
        entry = persist(terminal)
        return entry
    }
}

internal sealed interface DispatchClaimResult<out T> {
    data class Claimed<T>(val value: T) : DispatchClaimResult<T>
    data class Existing(val entry: ActionLedgerEntry) : DispatchClaimResult<Nothing>
    data class Reentrant(val entry: ActionLedgerEntry?) : DispatchClaimResult<Nothing>
}

internal sealed interface LedgerFailureResolution {
    data class Entry(val entry: ActionLedgerEntry) : LedgerFailureResolution
    data class Reentrant(val entry: ActionLedgerEntry?) : LedgerFailureResolution
    data object Absent : LedgerFailureResolution
}

private sealed interface ClaimStart {
    data class Existing(val entry: ActionLedgerEntry) : ClaimStart
    data class Owned(val entry: ActionLedgerEntry) : ClaimStart
}
