package com.apk.claw.android.rpa

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UiGenerationTrackerTest {
    @Test
    fun action_and_content_events_invalidate_generation() {
        val tracker = UiGenerationTracker("service-a")
        val first = tracker.snapshot()

        tracker.markUiChanged()
        assertEquals(first.uiGeneration + 1, tracker.snapshot().uiGeneration)

        tracker.markActionDispatched()
        assertEquals(first.uiGeneration + 2, tracker.snapshot().uiGeneration)
    }

    @Test
    fun concurrent_updates_are_not_lost() {
        val tracker = UiGenerationTracker("service-a")
        val workers = 8
        val updatesPerWorker = 250
        val start = CountDownLatch(1)
        val done = CountDownLatch(workers)
        val executor = Executors.newFixedThreadPool(workers)

        repeat(workers) { worker ->
            executor.execute {
                start.await()
                repeat(updatesPerWorker) { update ->
                    if ((worker + update) % 2 == 0) tracker.markUiChanged()
                    else tracker.markActionDispatched()
                }
                done.countDown()
            }
        }

        start.countDown()
        try {
            if (!done.await(5, TimeUnit.SECONDS)) error("generation workers timed out")
        } finally {
            executor.shutdownNow()
        }

        assertEquals((workers * updatesPerWorker).toLong(), tracker.snapshot().uiGeneration)
        assertEquals("service-a", tracker.snapshot().serviceGeneration)
    }

    @Test
    fun evidence_transaction_discards_interleaved_frame_and_retries_whole_capture() {
        val tracker = UiGenerationTracker("service-a")
        val frames = mutableListOf<FakeFrame>()
        var attempt = 0
        val runner = GenerationBracketedCapture(
            maxAttempts = 3,
            snapshot = tracker::snapshot
        ) {
            attempt += 1
            val frame = FakeFrame("frame-$attempt").also(frames::add)
            if (attempt == 1) tracker.markUiChanged()
            GenerationCaptureCandidate(
                frame = frame,
                value = FakeEvidence(
                    generation = tracker.snapshot(),
                    frameId = frame.id,
                    treeValue = "tree-$attempt"
                )
            )
        }

        val evidence = runner.capture()

        assertEquals(2, attempt)
        assertEquals(1L, evidence.generation.uiGeneration)
        assertEquals("frame-2", evidence.frameId)
        assertEquals("tree-2", evidence.treeValue)
        assertTrue(frames[0].closed)
        assertTrue(frames[1].closed)
    }

    @Test
    fun evidence_transaction_never_publishes_after_bounded_generation_mismatches() {
        val tracker = UiGenerationTracker("service-a")
        val frames = mutableListOf<FakeFrame>()
        val runner = GenerationBracketedCapture(
            maxAttempts = 2,
            snapshot = tracker::snapshot
        ) {
            val frame = FakeFrame("frame-${frames.size + 1}").also(frames::add)
            tracker.markActionDispatched()
            GenerationCaptureCandidate(frame, frame)
        }

        val failure = runCatching { runner.capture() }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        assertEquals(2, frames.size)
        frames.forEach { assertTrue(it.closed) }
    }

    private data class FakeEvidence(
        val generation: GenerationSnapshot,
        val frameId: String,
        val treeValue: String
    )

    private class FakeFrame(val id: String) : AutoCloseable {
        var closed = false
            private set

        override fun close() {
            assertTrue("frame closed more than once", !closed)
            closed = true
        }
    }
}
