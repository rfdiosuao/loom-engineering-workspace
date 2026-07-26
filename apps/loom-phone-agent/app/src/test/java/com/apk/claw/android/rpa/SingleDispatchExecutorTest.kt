package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicBoolean

class SingleDispatchExecutorTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun accepted_action_is_dispatched_once_when_verification_is_unknown() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, OutcomeVerifier { _, _ -> VerificationResult.Unknown("proof_missing") })

        val first = fixture.executor.execute(action())
        val repeated = fixture.executor.execute(action())

        assertEquals(1, dispatcher.calls.get())
        assertEquals(ActionOutcomeState.UNCERTAIN, first.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, repeated.state)
        assertEquals(ActionLedgerErrors.VERIFICATION_UNKNOWN, first.errorCode)
        assertTrue(first.dispatchInvoked)
        assertTrue(first.entry.dispatchInvoked)
    }

    @Test
    fun dispatcher_exception_becomes_durable_uncertain_and_is_not_replayed() {
        val calls = AtomicInteger()
        val fixture = fixture(
            ActionDispatcher {
                calls.incrementAndGet()
                throw IllegalStateException("sensitive detail")
            },
            verified()
        )

        val first = fixture.executor.execute(action())
        val repeated = fixture.executor.execute(action())

        assertEquals(1, calls.get())
        assertEquals(ActionOutcomeState.UNCERTAIN, first.state)
        assertEquals(ActionLedgerErrors.DISPATCH_EXCEPTION, first.errorCode)
        assertEquals(first, repeated)
    }

    @Test
    fun java_null_verifier_is_durable_uncertain_and_retry_never_dispatches_again() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, Task6TestInterop.nullVerifier(), generation = matchingGeneration())

        val first = fixture.executor.execute(action())
        val retried = fixture.executor.execute(action())

        assertEquals(1, dispatcher.calls.get())
        assertEquals(ActionOutcomeState.UNCERTAIN, first.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, retried.state)
        assertEquals(ActionLedgerState.UNCERTAIN, fixture.store.load(action().identity)?.state)
    }

    @Test
    fun java_null_dispatch_receipt_is_durable_uncertain_and_not_replayed() {
        val fixture = fixture(
            Task6TestInterop.nullDispatcher(),
            verified(),
            generation = matchingGeneration()
        )

        val first = fixture.executor.execute(action())
        val retried = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, first.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, retried.state)
        assertEquals(ActionLedgerState.UNCERTAIN, fixture.store.load(action().identity)?.state)
    }

    @Test
    fun task4_style_unknown_receipt_maps_to_uncertain_without_running_verifier() {
        val verifierCalls = AtomicInteger()
        val fixture = fixture(
            CountingDispatcher(
                DispatchReceipt(
                    outcome = DispatchOutcome.UNCERTAIN,
                    dispatchedAt = 1_100L,
                    errorCode = AccessibilitySemanticDispatcher.ERROR_ACTION_OUTCOME_UNKNOWN
                )
            ),
            OutcomeVerifier { _, _ ->
                verifierCalls.incrementAndGet()
                VerificationResult.EffectVerified
            }
        )

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(AccessibilitySemanticDispatcher.ERROR_ACTION_OUTCOME_UNKNOWN, result.errorCode)
        assertEquals(0, verifierCalls.get())
    }

    @Test
    fun verifier_exception_becomes_uncertain_without_second_dispatch() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, OutcomeVerifier { _, _ -> error("private verifier failure") })

        val result = fixture.executor.execute(action())
        fixture.executor.execute(action())

        assertEquals(1, dispatcher.calls.get())
        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.VERIFIER_EXCEPTION, result.errorCode)
    }

    @Test
    fun rejected_dispatch_is_failed_without_verification() {
        val verifierCalls = AtomicInteger()
        val dispatcher = CountingDispatcher(DispatchReceipt.rejected(1_100L, "action_click_rejected"))
        val fixture = fixture(dispatcher, OutcomeVerifier { _, _ ->
            verifierCalls.incrementAndGet()
            VerificationResult.EffectVerified
        })

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals("action_click_rejected", result.errorCode)
        assertEquals(0, verifierCalls.get())
    }

    @Test
    fun accepted_and_verified_action_reaches_verified_terminal_state() {
        val fixture = fixture(CountingDispatcher(DispatchReceipt.accepted(1_100L)), verified())

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.VERIFIED, result.state)
        assertEquals(ActionLedgerErrors.VERIFIED, result.errorCode)
        assertEquals(ActionLedgerState.VERIFIED, result.entry.state)
    }

    @Test
    fun independently_verified_no_effect_is_failed_no_effect() {
        val fixture = fixture(
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            OutcomeVerifier { _, _ -> VerificationResult.NoEffectVerified }
        )

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.FAILED_NO_EFFECT, result.state)
        assertEquals(ActionLedgerErrors.NO_EFFECT, result.errorCode)
    }

    @Test
    fun prepared_after_process_death_is_claimed_once_but_dispatching_is_never_replayed() {
        val root = temporaryFolder.newFolder("restart")
        val store = ActionLedgerStore(root, clock = { 2_000L })
        val preparedAction = action(stepId = "prepared")
        store.prepare(preparedAction.toLedgerEntry(1_000L))
        val dispatchingAction = action(stepId = "dispatching")
        store.prepare(dispatchingAction.toLedgerEntry(1_000L))
        assertThrows(IllegalStateException::class.java) {
            store.claimDispatch(dispatchingAction.identity.toOpaqueLedgerKey(), 1_100L) { claim ->
                claim.markDispatchInvoked(1_100L)
                throw IllegalStateException("simulated process death")
            }
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_200L))
        val executor = SingleDispatchExecutor(
            store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        assertEquals(ActionOutcomeState.VERIFIED, executor.execute(preparedAction).state)
        val recovered = executor.execute(dispatchingAction)

        assertEquals(1, dispatcher.calls.get())
        assertEquals(ActionOutcomeState.UNCERTAIN, recovered.state)
        assertEquals(ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH, recovered.errorCode)
    }

    @Test
    fun concurrent_executors_and_store_instances_make_exactly_one_dispatch_call() {
        val root = temporaryFolder.newFolder("concurrent")
        val calls = AtomicInteger()
        val dispatcher = ActionDispatcher {
            calls.incrementAndGet()
            Thread.sleep(20L)
            DispatchReceipt.accepted(1_100L)
        }
        val executors = listOf(
            SingleDispatchExecutor(
                ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
            ),
            SingleDispatchExecutor(
                ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
            )
        )
        val pool = Executors.newFixedThreadPool(8)
        val start = CountDownLatch(1)
        val futures = (0 until 64).map { index ->
            pool.submit<ActionOutcome> {
                start.await()
                executors[index % executors.size].execute(action())
            }
        }
        start.countDown()
        val results = futures.map { it.get(30, TimeUnit.SECONDS) }
        pool.shutdown()

        assertTrue(pool.awaitTermination(30, TimeUnit.SECONDS))
        assertEquals(1, calls.get())
        assertTrue(results.all { it.state == ActionOutcomeState.VERIFIED })
    }

    @Test
    fun release_fault_after_terminal_write_reloads_terminal_and_never_redispatches() {
        val root = temporaryFolder.newFolder("release-fault")
        val failOnce = AtomicBoolean(true)
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val store = ActionLedgerStore(
            root,
            claimLockRelease = { lock ->
                lock.release()
                if (failOnce.compareAndSet(true, false)) throw IllegalStateException("release fault")
            }
        )
        val executor = SingleDispatchExecutor(
            store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        val first = executor.execute(action())
        val retried = executor.execute(action())

        assertEquals(ActionOutcomeState.VERIFIED, first.state)
        assertEquals(ActionOutcomeState.VERIFIED, retried.state)
        assertEquals(1, dispatcher.calls.get())
    }

    @Test
    fun same_identity_reentrant_execute_fails_closed_without_deadlock_or_second_dispatch() {
        val root = temporaryFolder.newFolder("reentrant")
        val nested = AtomicReference<ActionOutcome>()
        val calls = AtomicInteger()
        lateinit var executor: SingleDispatchExecutor
        val dispatcher = ActionDispatcher {
            calls.incrementAndGet()
            nested.set(executor.execute(action()))
            DispatchReceipt.accepted(1_100L)
        }
        executor = SingleDispatchExecutor(
            ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        val outer = executor.execute(action())

        assertEquals(ActionOutcomeState.VERIFIED, outer.state)
        assertEquals(ActionOutcomeState.UNCERTAIN, nested.get().state)
        assertEquals(ActionLedgerErrors.REENTRANT_EXECUTE, nested.get().errorCode)
        assertEquals(1, calls.get())
    }

    @Test
    fun callback_can_wait_for_cross_thread_store_read() {
        val root = temporaryFolder.newFolder("callback-cross-thread")
        val store = ActionLedgerStore(root)
        val pool = Executors.newSingleThreadExecutor()
        val dispatcher = ActionDispatcher {
            val observed = pool.submit<ActionLedgerEntry?> { store.load(action().identity) }
                .get(2, TimeUnit.SECONDS)
            assertEquals(ActionLedgerState.DISPATCHING, observed?.state)
            DispatchReceipt.accepted(1_100L)
        }
        val executor = SingleDispatchExecutor(
            store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        assertEquals(ActionOutcomeState.VERIFIED, executor.execute(action()).state)
        pool.shutdownNow()
    }

    @Test
    fun concurrent_retry_attempt_is_claimed_exactly_once() {
        val root = temporaryFolder.newFolder("concurrent-retry")
        val calls = AtomicInteger()
        val dispatcher = ActionDispatcher { prepared ->
            calls.incrementAndGet()
            if (prepared.attempt == 1) DispatchReceipt.rejected(1_100L)
            else DispatchReceipt.accepted(2_100L)
        }
        val stores = listOf(ActionLedgerStore(root), ActionLedgerStore(root))
        val executors = stores.map { store ->
            SingleDispatchExecutor(store, dispatcher, verified(), clock = { 3_000L }, generation = matchingGeneration())
        }
        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, executors.first().execute(action(attempt = 1)).state)
        val pool = Executors.newFixedThreadPool(10)
        val start = CountDownLatch(1)
        val futures = (0 until 60).map { index ->
            pool.submit<ActionOutcome> {
                start.await()
                executors[index % 2].execute(action(attempt = 2))
            }
        }
        start.countDown()
        val results = futures.map { it.get(30, TimeUnit.SECONDS) }
        pool.shutdownNow()

        assertTrue(results.all { it.state == ActionOutcomeState.VERIFIED })
        assertEquals(2, calls.get())
    }

    @Test
    fun claim_lock_directory_alias_fails_closed_without_touching_target() {
        val root = temporaryFolder.newFolder("claim-alias")
        val outside = temporaryFolder.newFolder("claim-alias-outside")
        val alias = File(root, ".action-claims")
        try {
            Files.createSymbolicLink(alias.toPath(), outside.toPath())
        } catch (error: Exception) {
            assumeNoException(error)
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ActionLedgerErrors.CLAIM_DURABILITY_FAILURE, result.errorCode)
        assertEquals(0, dispatcher.calls.get())
        assertTrue(outside.listFiles().isNullOrEmpty())
    }

    @Test
    fun initialized_claim_shard_alias_fails_closed_without_recreation_or_target_access() {
        val root = temporaryFolder.newFolder("claim-shard-alias")
        val outside = temporaryFolder.newFile("claim-shard-outside").apply { writeText("untouched") }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )
        assertEquals(ActionOutcomeState.VERIFIED, executor.execute(action()).state)
        val shard = File(
            File(root, ".action-claims"),
            action(runId = "second-run").identity.toOpaqueLedgerKey().claimShardName()
        )
        assertTrue(shard.delete())
        try {
            Files.createSymbolicLink(shard.toPath(), outside.toPath())
        } catch (error: Exception) {
            assumeNoException(error)
        }

        val result = executor.execute(action(runId = "second-run"))

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(1, dispatcher.calls.get())
        assertTrue(Files.isSymbolicLink(shard.toPath()))
        assertEquals("untouched", outside.readText())
    }

    @Test
    fun subprocess_claim_file_lock_blocks_dispatch_until_released() {
        val root = temporaryFolder.newFolder("subprocess-lock")
        val store = ActionLedgerStore(root)
        val prepared = action()
        store.prepare(prepared.toLedgerEntry(1_000L))
        val claims = File(root, ".action-claims").apply { mkdirs() }
        val lockFile = File(claims, prepared.identity.toOpaqueLedgerKey().claimShardName())
        val ready = File(root, "child-ready")
        val release = File(root, "child-release")
        val classPath = (
            System.getProperty("java.class.path").orEmpty().split(File.pathSeparator) +
                File(Task6TestInterop::class.java.protectionDomain!!.codeSource.location.toURI()).path +
                File(ActionDispatcher::class.java.protectionDomain!!.codeSource.location.toURI()).path
            ).distinct().joinToString(File.pathSeparator)
        val java = File(System.getProperty("java.home"), "bin/java.exe")
            .takeIf { it.isFile } ?: File(System.getProperty("java.home"), "bin/java")
        val child = ProcessBuilder(
            java.absolutePath,
            "-cp",
            classPath,
            Task6TestInterop::class.java.name,
            lockFile.absolutePath,
            ready.absolutePath,
            release.absolutePath
        ).redirectErrorStream(true).start()
        val deadline = System.currentTimeMillis() + 5_000L
        while (!ready.exists() && child.isAlive && System.currentTimeMillis() < deadline) Thread.sleep(10L)
        if (!ready.exists()) {
            child.destroyForcibly()
            val output = child.inputStream.bufferedReader().readText()
            throw AssertionError("claim-lock child did not start: $output")
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )
        val pool = Executors.newSingleThreadExecutor()
        val future = pool.submit<ActionOutcome> { executor.execute(prepared) }
        try {
            Thread.sleep(200L)
            assertFalse(future.isDone)
            assertEquals(0, dispatcher.calls.get())
            assertTrue(release.createNewFile())
            assertEquals(ActionOutcomeState.VERIFIED, future.get(10, TimeUnit.SECONDS).state)
            assertEquals(0, child.waitFor())
        } finally {
            release.createNewFile()
            child.destroyForcibly()
            pool.shutdownNow()
        }
        assertEquals(1, dispatcher.calls.get())
    }

    @Test
    fun verified_or_uncertain_attempt_cannot_start_attempt_two() {
        listOf(
            verified() to ActionOutcomeState.VERIFIED,
            OutcomeVerifier { _, _ -> VerificationResult.Unknown("secret-token") } to ActionOutcomeState.UNCERTAIN
        ).forEachIndexed { index, (verifier, expected) ->
            val root = temporaryFolder.newFolder("blocked-attempt-$index")
            val calls = AtomicInteger()
            val dispatcher = ActionDispatcher {
                calls.incrementAndGet()
                DispatchReceipt.accepted(1_100L)
            }
            val first = SingleDispatchExecutor(
                ActionLedgerStore(root), dispatcher, verifier, clock = { 2_000L }, generation = matchingGeneration()
            ).execute(action(attempt = 1))
            val second = SingleDispatchExecutor(
                ActionLedgerStore(root), dispatcher, verified(), clock = { 3_000L }, generation = matchingGeneration()
            ).execute(action(attempt = 2))

            assertEquals(expected, first.state)
            assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, second.state)
            assertEquals(1, calls.get())
        }
    }

    @Test
    fun retryable_terminal_allows_exactly_one_next_attempt_without_gaps() {
        val root = temporaryFolder.newFolder("retry-attempt")
        val calls = AtomicInteger()
        val dispatcher = ActionDispatcher { prepared ->
            calls.incrementAndGet()
            if (prepared.attempt == 1) DispatchReceipt.rejected(1_100L)
            else DispatchReceipt.accepted(2_100L)
        }
        val executor = { SingleDispatchExecutor(
            ActionLedgerStore(root), dispatcher, verified(), clock = { 3_000L }, generation = matchingGeneration()
        ) }

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, executor().execute(action(attempt = 1)).state)
        assertEquals(ActionOutcomeState.VERIFIED, executor().execute(action(attempt = 2)).state)
        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, executor().execute(action(attempt = 3)).state)
        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, executor().execute(action(attempt = 5)).state)
        assertEquals(2, calls.get())
    }

    @Test
    fun service_generation_change_after_acceptance_is_uncertain() {
        val fixture = fixture(
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            generation = { GenerationSnapshot(8L, "service-2") }
        )

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.SERVICE_GENERATION_CHANGED, result.errorCode)
    }

    @Test
    fun equal_service_generation_with_stale_ui_generation_is_uncertain() {
        val fixture = fixture(
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            generation = { GenerationSnapshot(6L, "service-1") }
        )

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
    }

    @Test
    fun callback_can_read_same_store_and_write_unrelated_run_without_deadlock() {
        val root = temporaryFolder.newFolder("callback-store-access")
        val store = ActionLedgerStore(root)
        val callbackResult = AtomicReference<ActionLedgerEntry?>()
        val nestedAction = action(runId = "other-run", stepId = "other-step")
        val dispatcher = ActionDispatcher {
            callbackResult.set(store.load(action().identity))
            store.prepare(nestedAction.toLedgerEntry(1_500L))
            DispatchReceipt.accepted(1_100L)
        }
        val executor = SingleDispatchExecutor(
            store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(ActionOutcomeState.VERIFIED, result.state)
        assertEquals(ActionLedgerState.DISPATCHING, callbackResult.get()?.state)
        assertEquals(ActionLedgerState.PREPARED, store.load(nestedAction.identity)?.state)
    }

    @Test
    fun unrelated_run_progresses_while_first_dispatch_callback_is_blocked() {
        val root = temporaryFolder.newFolder("unrelated-progress")
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val first = SingleDispatchExecutor(
            ActionLedgerStore(root),
            ActionDispatcher {
                entered.countDown()
                release.await(10, TimeUnit.SECONDS)
                DispatchReceipt.accepted(1_100L)
            },
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )
        val second = SingleDispatchExecutor(
            ActionLedgerStore(root),
            CountingDispatcher(DispatchReceipt.accepted(1_200L)),
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )
        val pool = Executors.newFixedThreadPool(2)
        val firstFuture = pool.submit<ActionOutcome> { first.execute(action()) }
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        val secondFuture = pool.submit<ActionOutcome> {
            second.execute(action(runId = "run-2", stepId = "step-2"))
        }
        try {
            assertEquals(ActionOutcomeState.VERIFIED, secondFuture.get(2, TimeUnit.SECONDS).state)
        } finally {
            release.countDown()
        }
        assertEquals(ActionOutcomeState.VERIFIED, firstFuture.get(10, TimeUnit.SECONDS).state)
        pool.shutdownNow()
    }

    @Test
    fun missing_service_generation_proof_is_uncertain_when_provider_is_configured() {
        val fixture = fixture(
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            generation = { null }
        )

        val result = fixture.executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.VERIFICATION_UNKNOWN, result.errorCode)
    }

    @Test
    fun store_failure_before_durable_claim_causes_zero_dispatches() {
        val root = temporaryFolder.newFolder("claim-failure")
        var primaryWrites = 0
        val rename: (File, File) -> Boolean = { source, destination ->
            if (destination.name == "action-ledger.json") primaryWrites++
            if (destination.name == "action-ledger.json" && primaryWrites == 2) false
            else source.renameTo(destination)
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root, rename = rename),
            dispatcher,
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(0, dispatcher.calls.get())
        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ActionLedgerErrors.CLAIM_DURABILITY_FAILURE, result.errorCode)
        assertEquals(ActionLedgerState.PREPARED, ActionLedgerStore(root).load(action().identity)?.state)
    }

    @Test
    fun failed_verified_persistence_falls_back_to_durable_uncertain() {
        val root = temporaryFolder.newFolder("terminal-fallback")
        var primaryWrites = 0
        val rename: (File, File) -> Boolean = { source, destination ->
            if (destination.name == "action-ledger.json") primaryWrites++
            if (destination.name == "action-ledger.json" && primaryWrites == 4) false
            else source.renameTo(destination)
        }
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root, rename = rename),
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.TERMINAL_DURABILITY_FAILURE, result.errorCode)
        assertEquals(ActionLedgerState.UNCERTAIN, ActionLedgerStore(root).load(action().identity)?.state)
    }

    @Test
    fun persistent_terminal_storage_failure_never_claims_verified_and_recovers_uncertain() {
        val root = temporaryFolder.newFolder("terminal-unavailable")
        var committedWrites = 0
        val rename: (File, File) -> Boolean = { source, destination ->
            if (destination.name == "action-ledger.json" && source.name.contains(".tmp-")) {
                committedWrites++
                if (committedWrites >= 4) false else source.renameTo(destination)
            } else {
                source.renameTo(destination)
            }
        }
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root, rename = rename),
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.DURABILITY_UNAVAILABLE, result.errorCode)
        val recovered = ActionLedgerStore(root, clock = { 3_000L }).recoverIncompleteRuns().single()
        assertEquals(ActionLedgerState.UNCERTAIN, recovered.state)
        assertEquals(ActionLedgerErrors.PROCESS_DEATH_DURING_DISPATCH, recovered.errorCode)
    }

    @Test
    fun payload_is_dispatched_but_never_written_to_ledger() {
        val root = temporaryFolder.newFolder("payload")
        val secret = "selector=secret-token account=user@example.com"
        val action = action(payload = SecretPayload(secret))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root),
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )

        executor.execute(action)

        val run = File(root, "runs").listFiles()!!.single()
        assertTrue(File(run, "action-ledger.json").readText().contains("RESOURCE_ID"))
        assertTrue(!File(run, "action-ledger.json").readText().contains(secret))
    }

    @Test
    fun raw_identity_and_arbitrary_callback_error_are_absent_from_path_bytes_and_durable_entry() {
        val root = temporaryFolder.newFolder("opaque-identities")
        val rawRun = "account-token"
        val rawStep = "user-token"
        val rawError = "secret-token"
        val rawGeneration = "a".repeat(64)
        val prepared = action(
            runId = rawRun,
            stepId = rawStep,
            serviceGeneration = rawGeneration,
            payload = SecretPayload(rawError)
        )
        val result = SingleDispatchExecutor(
            ActionLedgerStore(root),
            CountingDispatcher(DispatchReceipt.accepted(1_100L)),
            OutcomeVerifier { _, _ -> VerificationResult.Unknown(rawError) },
            clock = { 2_000L },
            generation = { GenerationSnapshot(7L, rawGeneration) }
        ).execute(prepared)
        val runDirectory = File(root, "runs").listFiles()!!.single()
        val bytes = File(runDirectory, "action-ledger.json").readText()
        val probe = listOf(rawRun, rawStep, rawError, rawGeneration)

        probe.forEach { token ->
            assertTrue(!runDirectory.absolutePath.contains(token))
            assertTrue(!bytes.contains(token))
            assertTrue(!result.entry.toString().contains(token))
        }
        assertEquals(ActionLedgerErrors.VERIFICATION_UNKNOWN, result.errorCode)
    }

    @Test
    fun fixed_claim_shards_survive_more_than_three_hundred_pruned_identities() {
        val root = temporaryFolder.newFolder("claim-shard-lifetime")
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root),
            dispatcher,
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )
        repeat(4) { batch ->
            repeat(80) { offset ->
                val index = batch * 80 + offset
                assertEquals(
                    ActionOutcomeState.VERIFIED,
                    executor.execute(action(runId = "lifetime-run-$index", stepId = "step-$index")).state
                )
            }
            ActionLedgerStore(root).prune(now = 9L * 24L * 60L * 60L * 1_000L)
        }

        repeat(5) { offset ->
            val index = 320 + offset
            assertEquals(
                ActionOutcomeState.VERIFIED,
                executor.execute(action(runId = "lifetime-run-$index", stepId = "step-$index")).state
            )
        }

        val claimFiles = File(root, ".action-claims").listFiles().orEmpty()
        assertEquals(325, dispatcher.calls.get())
        assertEquals(64, claimFiles.count { it.extension == "lock" })
        assertEquals(65, claimFiles.size)
    }

    @Test
    fun storage_failure_before_prepare_returns_non_durable_uncertain_without_fabricating_terminal_entry() {
        val unavailableRoot = temporaryFolder.newFile("ledger-root-is-file")
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val result = SingleDispatchExecutor(
            ActionLedgerStore(unavailableRoot),
            dispatcher,
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        ).execute(action())

        assertEquals(ActionOutcomeState.UNCERTAIN, result.state)
        assertEquals(ActionLedgerErrors.DURABILITY_UNAVAILABLE, result.errorCode)
        assertFalse(result.durable)
        assertEquals(ActionLedgerState.PREPARED, result.entry.state)
        assertFalse(File(unavailableRoot, "runs").exists())
        assertEquals(0, dispatcher.calls.get())
    }

    @Test
    fun raw_sixty_four_hex_identity_lookup_hashes_across_reopen_and_retry_is_exactly_once() {
        val root = temporaryFolder.newFolder("raw-hex-identity")
        val rawRun = "a".repeat(64)
        val rawStep = "b".repeat(64)
        val prepared = action(runId = rawRun, stepId = rawStep)
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val first = SingleDispatchExecutor(
            ActionLedgerStore(root), dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
        ).execute(prepared)
        val reopened = ActionLedgerStore(root)
        val second = SingleDispatchExecutor(
            reopened, dispatcher, verified(), clock = { 3_000L }, generation = matchingGeneration()
        ).execute(prepared)

        assertEquals(ActionOutcomeState.VERIFIED, first.state)
        assertEquals(ActionOutcomeState.VERIFIED, second.state)
        assertEquals(ActionLedgerState.VERIFIED, reopened.load(ActionIdentity(rawRun, rawStep, 1))!!.state)
        assertEquals(1, dispatcher.calls.get())
    }

    @Test
    fun saturated_claim_lock_directory_fails_closed_without_dispatch() {
        val root = temporaryFolder.newFolder("claim-lock-limit")
        val claims = File(root, ".action-claims").apply { mkdirs() }
        repeat(ActionLedgerStore.MAX_DIRECTORY_FANOUT) { index ->
            File(claims, "unrelated-$index.lock").createNewFile()
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val executor = SingleDispatchExecutor(
            ActionLedgerStore(root),
            dispatcher,
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        )

        val result = executor.execute(action())

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ActionLedgerErrors.CLAIM_DURABILITY_FAILURE, result.errorCode)
        assertEquals(0, dispatcher.calls.get())
        assertEquals(ActionLedgerState.PREPARED, executorEntry(root).state)
    }

    @Test
    fun claimed_pre_dispatch_guard_rejection_is_durable_and_never_dispatches() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, verified())

        val result = fixture.executor.execute(
            action(
                preDispatchGuard = ClaimedPreDispatchGuard {
                    ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.GENERATION_CHANGED)
                }
            )
        )

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ClaimedPreDispatchFailure.GENERATION_CHANGED.code, result.errorCode)
        assertEquals(ClaimedPreDispatchFailure.GENERATION_CHANGED, result.preDispatchFailure)
        assertTrue(result.durable)
        assertEquals(ActionLedgerState.FAILED_NO_DISPATCH, result.entry.state)
        assertEquals(ActionLedgerErrors.PRE_DISPATCH_GENERATION_CHANGED, result.entry.errorCode)
        assertFalse(result.dispatchInvoked)
        assertFalse(result.entry.dispatchInvoked)
        assertEquals(0, dispatcher.calls.get())
    }

    @Test
    fun release_fault_after_terminal_guard_write_reconstructs_exact_reason_without_dispatch() {
        listOf(
            ClaimedPreDispatchFailure.CANCELLED,
            ClaimedPreDispatchFailure.GENERATION_CHANGED
        ).forEach { failure ->
            val root = temporaryFolder.newFolder("guard-release-${failure.name.lowercase()}")
            val failOnce = AtomicBoolean(true)
            val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
            val store = ActionLedgerStore(
                root,
                claimLockRelease = { lock ->
                    lock.release()
                    if (failOnce.compareAndSet(true, false)) throw IllegalStateException("release fault")
                }
            )
            val executor = SingleDispatchExecutor(
                store, dispatcher, verified(), clock = { 2_000L }, generation = matchingGeneration()
            )
            val guarded = action(
                preDispatchGuard = ClaimedPreDispatchGuard {
                    ClaimedPreDispatchDecision.Reject(failure)
                }
            )

            val first = executor.execute(guarded)
            val reopened = SingleDispatchExecutor(
                ActionLedgerStore(root), dispatcher, verified(), clock = { 3_000L }, generation = matchingGeneration()
            ).execute(guarded)

            listOf(first, reopened).forEach { result ->
                assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
                assertEquals(failure.code, result.errorCode)
                assertEquals(failure, result.preDispatchFailure)
                assertFalse(result.dispatchInvoked)
                assertFalse(result.entry.dispatchInvoked)
            }
            assertEquals(0, dispatcher.calls.get())
        }
    }

    @Test
    fun terminal_guard_write_fault_reconciles_exact_reason_without_dispatch() {
        val root = temporaryFolder.newFolder("guard-terminal-write")
        var primaryWrites = 0
        val rename: (File, File) -> Boolean = { source, destination ->
            if (destination.name == "action-ledger.json") primaryWrites++
            if (destination.name == "action-ledger.json" && primaryWrites == 3) false
            else source.renameTo(destination)
        }
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val result = SingleDispatchExecutor(
            ActionLedgerStore(root, rename = rename),
            dispatcher,
            verified(),
            clock = { 2_000L },
            generation = matchingGeneration()
        ).execute(
            action(
                preDispatchGuard = ClaimedPreDispatchGuard {
                    ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.GENERATION_CHANGED)
                }
            )
        )

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ActionLedgerErrors.PRE_DISPATCH_GENERATION_CHANGED, result.errorCode)
        assertEquals(ClaimedPreDispatchFailure.GENERATION_CHANGED, result.preDispatchFailure)
        assertTrue(result.durable)
        assertFalse(result.dispatchInvoked)
        assertEquals(0, dispatcher.calls.get())
    }

    @Test
    fun deadline_guard_reason_is_persisted_exactly_without_dispatch() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, verified())
        val result = fixture.executor.execute(
            action(
                preDispatchGuard = ClaimedPreDispatchGuard {
                    ClaimedPreDispatchDecision.Reject(ClaimedPreDispatchFailure.DEADLINE_EXCEEDED)
                }
            )
        )

        assertEquals(ActionLedgerErrors.PRE_DISPATCH_DEADLINE_EXCEEDED, result.entry.errorCode)
        assertEquals(ClaimedPreDispatchFailure.DEADLINE_EXCEEDED, result.preDispatchFailure)
        assertFalse(result.dispatchInvoked)
        assertEquals(0, dispatcher.calls.get())
    }

    @Test
    fun null_claimed_pre_dispatch_guard_result_fails_closed_without_dispatch() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, verified())

        val result = fixture.executor.execute(
            action(preDispatchGuard = ClaimedPreDispatchGuard { null })
        )

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ClaimedPreDispatchFailure.RESULT_MISSING.code, result.errorCode)
        assertEquals(ClaimedPreDispatchFailure.RESULT_MISSING, result.preDispatchFailure)
        assertFalse(result.dispatchInvoked)
        assertEquals(0, dispatcher.calls.get())
    }

    @Test
    fun throwing_claimed_pre_dispatch_guard_fails_closed_without_dispatch() {
        val dispatcher = CountingDispatcher(DispatchReceipt.accepted(1_100L))
        val fixture = fixture(dispatcher, verified())

        val result = fixture.executor.execute(
            action(
                preDispatchGuard = ClaimedPreDispatchGuard {
                    throw IllegalStateException("sensitive guard detail")
                }
            )
        )

        assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, result.state)
        assertEquals(ClaimedPreDispatchFailure.EXCEPTION.code, result.errorCode)
        assertEquals(ClaimedPreDispatchFailure.EXCEPTION, result.preDispatchFailure)
        assertFalse(result.dispatchInvoked)
        assertEquals(0, dispatcher.calls.get())
    }

    private fun fixture(
        dispatcher: ActionDispatcher,
        verifier: OutcomeVerifier,
        generation: () -> GenerationSnapshot? = matchingGeneration()
    ): Fixture {
        val root = temporaryFolder.newFolder()
        val store = ActionLedgerStore(root)
        return Fixture(
            store,
            SingleDispatchExecutor(store, dispatcher, verifier, clock = { 2_000L }, generation = generation)
        )
    }

    private fun action(
        runId: String = "run-1",
        stepId: String = "step-1",
        attempt: Int = 1,
        serviceGeneration: String = "service-1",
        payload: DispatchPayload = SecretPayload("ordinary"),
        preDispatchGuard: ClaimedPreDispatchGuard = ClaimedPreDispatchGuard.allow()
    ) = PreparedAction(
        runId = runId,
        stepId = stepId,
        attempt = attempt,
        uiGeneration = 7L,
        serviceGeneration = serviceGeneration,
        resolverUsed = ResolverKind.RESOURCE_ID,
        payload = payload,
        preDispatchGuard = preDispatchGuard
    )

    private fun verified() = OutcomeVerifier { _, _ -> VerificationResult.EffectVerified }

    private fun matchingGeneration() = { GenerationSnapshot(7L, "service-1") }

    private fun executorEntry(root: File): ActionLedgerEntry = ActionLedgerStore(root).load(action().identity)!!

    private data class Fixture(val store: ActionLedgerStore, val executor: SingleDispatchExecutor)

    private data class SecretPayload(val value: String) : DispatchPayload

    private class CountingDispatcher(private val receipt: DispatchReceipt) : ActionDispatcher {
        val calls = AtomicInteger()

        override fun dispatch(action: PreparedAction): DispatchReceipt {
            calls.incrementAndGet()
            return receipt
        }
    }
}
