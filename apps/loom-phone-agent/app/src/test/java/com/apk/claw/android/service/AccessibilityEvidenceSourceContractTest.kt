package com.apk.claw.android.service

import com.apk.claw.android.agent.ScreenObservationBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import java.io.File
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityEvidenceSourceContractTest {
    @Test
    fun old_bitmap_api_and_new_frame_api_coexist() {
        val service = source("service/ClawAccessibilityService.java")

        assertTrue(service.contains("public Bitmap takeScreenshot(long timeoutMs)"))
        assertTrue(service.contains("public ScreenshotFrame takeScreenshotFrame("))
        assertTrue(service.contains("frame.detachBitmap()"))
    }

    @Test
    fun callback_produced_timestamp_is_assigned_inside_success_callback() {
        val service = source("service/ClawAccessibilityService.java")
        val callback = service.substringAfter("public void onSuccess(ScreenshotResult result)")
            .substringBefore("public void onFailure(int errorCode)")

        assertTrue(callback.contains("System.currentTimeMillis()"))
        assertTrue(callback.contains("new CapturedBitmap"))
        assertTrue(service.contains("captured.capturedAt > freshAfterMs"))
    }

    @Test
    fun callback_arrival_timestamp_is_the_first_success_operation() {
        val service = source("service/ClawAccessibilityService.java")
        val callback = service.substringAfter("public void onSuccess(ScreenshotResult result) {")
            .substringBefore("Bitmap bmp")

        assertTrue(callback.trim().startsWith("long capturedAt = System.currentTimeMillis();"))
    }

    @Test
    fun frame_transfers_or_recycles_its_copied_argb_bitmap() {
        val frame = source("service/ScreenshotFrame.java")

        assertTrue(frame.contains("Bitmap.Config.ARGB_8888"))
        assertTrue(frame.contains("static ScreenshotFrame fresh"))
        assertTrue(frame.contains("static ScreenshotFrame cached"))
        assertTrue(frame.contains("static ScreenshotFrame stale"))
        assertTrue(frame.contains("synchronized Bitmap detachBitmap"))
        assertTrue(frame.contains("synchronized void close"))
        assertTrue(frame.contains("bitmap.recycle()"))
    }

    @Test
    fun accessibility_changes_and_injected_actions_invalidate_generation() {
        val service = source("service/ClawAccessibilityService.java")

        listOf(
            "TYPE_WINDOW_STATE_CHANGED",
            "TYPE_WINDOWS_CHANGED",
            "TYPE_WINDOW_CONTENT_CHANGED",
            "TYPE_VIEW_SCROLLED",
            "TYPE_VIEW_TEXT_CHANGED",
            "TYPE_VIEW_FOCUSED",
            "TYPE_VIEW_TEXT_SELECTION_CHANGED",
            "TYPE_VIEW_SELECTED"
        ).forEach { assertTrue("missing event invalidation for $it", service.contains(it)) }
        assertTrue(service.contains("onConfigurationChanged(Configuration newConfig)"))
        assertTrue(service.contains("generationTracker.markUiChanged()"))
        assertTrue(service.contains("generationTracker.markActionDispatched()"))
    }

    @Test
    fun observation_metrics_add_generation_and_frame_fields_without_losing_existing_metrics() {
        val observed = ScreenObservationBuilder.build(
            tree = JsonObject().apply {
                add("screen", JsonObject())
                add("nodes", JsonArray())
            },
            capturedAt = 1_200L,
            durationMs = 17L,
            uiGeneration = 9L,
            serviceGeneration = "service-a",
            frameSource = "fresh",
            frameId = "service-a:4:fresh",
            frameAgeMs = 3L
        )
        val metrics = observed.getAsJsonObject("metrics")

        assertEquals(17L, metrics["screenTreeMs"].asLong)
        assertEquals(9L, metrics["uiGeneration"].asLong)
        assertEquals("service-a", metrics["serviceGeneration"].asString)
        assertEquals("fresh", metrics["frameSource"].asString)
        assertEquals("service-a:4:fresh", metrics["frameId"].asString)
        assertEquals(3L, metrics["frameAgeMs"].asLong)
    }

    @Test
    fun capture_state_publishes_before_timeout_and_transfers_accepted_value_once() {
        val recycled = AtomicInteger()
        val state = ClawAccessibilityService.ScreenshotCaptureState<FakeCapture> { it.recycle() }
        val value = FakeCapture(recycled)

        assertTrue(state.publishOrDispose(value))
        assertSame(value, state.await(10L))
        assertNull(state.await(0L))
        value.recycle()

        assertEquals(1, recycled.get())
    }

    @Test
    fun capture_state_timeout_rejects_and_recycles_late_callback_once() {
        val recycled = AtomicInteger()
        val state = ClawAccessibilityService.ScreenshotCaptureState<FakeCapture> { it.recycle() }
        val value = FakeCapture(recycled)

        assertNull(state.await(0L))
        assertTrue(!state.publishOrDispose(value))

        assertEquals(1, recycled.get())
    }

    @Test
    fun capture_state_timeout_racing_publication_has_one_owner_and_one_recycle() {
        repeat(100) {
            val recycled = AtomicInteger()
            val state = ClawAccessibilityService.ScreenshotCaptureState<FakeCapture> { it.recycle() }
            val value = FakeCapture(recycled)
            val start = CountDownLatch(1)
            val results = Collections.synchronizedList(mutableListOf<FakeCapture?>())
            val executor = Executors.newFixedThreadPool(2)
            try {
                executor.execute {
                    start.await()
                    state.publishOrDispose(value)
                }
                executor.execute {
                    start.await()
                    results += state.await(0L)
                }
                start.countDown()
                executor.shutdown()
                assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS))
            } finally {
                executor.shutdownNow()
            }

            results.single()?.recycle()
            assertEquals(1, recycled.get())
        }
    }

    @Test
    fun legacy_attempt_policy_retries_once_with_minimum_five_second_timeout() {
        val timeouts = mutableListOf<Long>()
        val result = ClawAccessibilityService.ScreenshotAttemptPolicy.capture(
            750L,
            true,
            { timeout -> timeouts += timeout; if (timeouts.size == 2) "captured" else null },
            {}
        )

        assertEquals("captured", result)
        assertEquals(listOf(750L, 5_000L), timeouts)
    }

    @Test
    fun authorization_attempt_policy_never_retries() {
        val timeouts = mutableListOf<Long>()
        val result = ClawAccessibilityService.ScreenshotAttemptPolicy.capture<String>(
            750L,
            false,
            { timeout -> timeouts += timeout; null },
            {}
        )

        assertNull(result)
        assertEquals(listOf(750L), timeouts)
    }

    @Test
    fun screen_tree_json_recycles_its_root_and_callback_wait_uses_dedicated_executor() {
        val service = source("service/ClawAccessibilityService.java")
        val treeMethod = service.substringAfter("public JsonObject getScreenTreeJson()")
            .substringBefore("private String resolveAppLabel")

        assertTrue(treeMethod.contains("finally"))
        assertTrue(treeMethod.contains("root.recycle()"))
        assertTrue(service.contains("screenshotCallbackExecutor"))
        assertTrue(!service.contains("takeScreenshot(Display.DEFAULT_DISPLAY, getMainExecutor()"))
    }

    private class FakeCapture(private val recycled: AtomicInteger) {
        fun recycle() {
            assertEquals("capture recycled more than once", 0, recycled.getAndIncrement())
        }
    }

    private fun source(relativePath: String): String {
        return sequenceOf(
            File("app/src/main/java/com/apk/claw/android/$relativePath"),
            File("src/main/java/com/apk/claw/android/$relativePath")
        ).firstOrNull { it.isFile }?.readText() ?: error("Source not found: $relativePath")
    }
}
