package com.apk.claw.android.rpa

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenshotFreshnessPolicyTest {
    @Test
    fun cached_or_stale_frame_cannot_authorize_action() {
        val requirement = FreshnessRequirement.AuthorizeAfter(1_000L)

        assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "cache", capturedAt = 1_100L), requirement))
        assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "stale_fallback", capturedAt = 1_100L), requirement))
        assertTrue(ScreenshotFreshnessPolicy.accepts(frame(source = "fresh", capturedAt = 1_100L), requirement))
    }

    @Test
    fun authorization_requires_capture_strictly_after_timestamp() {
        val requirement = FreshnessRequirement.AuthorizeAfter(1_000L)

        assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "fresh", capturedAt = 999L), requirement))
        assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "fresh", capturedAt = 1_000L), requirement))
        assertTrue(ScreenshotFreshnessPolicy.accepts(frame(source = "fresh", capturedAt = 1_001L), requirement))
    }

    @Test
    fun read_only_observation_may_use_reported_cache_sources() {
        assertTrue(ScreenshotFreshnessPolicy.accepts(frame(source = "cache", capturedAt = 900L), FreshnessRequirement.ReadOnly))
        assertTrue(ScreenshotFreshnessPolicy.accepts(frame(source = "stale_fallback", capturedAt = 900L), FreshnessRequirement.ReadOnly))
        assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = null, capturedAt = null), FreshnessRequirement.ReadOnly))
    }

    @Test
    fun frame_age_is_computed_at_final_evidence_publication() {
        assertEquals(250L, frameAgeMs(evidenceCapturedAt = 1_250L, frameCapturedAt = 1_000L))
        assertEquals(0L, frameAgeMs(evidenceCapturedAt = 999L, frameCapturedAt = 1_000L))
    }

    private fun frame(source: String?, capturedAt: Long?): UiEvidence {
        return UiEvidence(
            uiGeneration = 7L,
            serviceGeneration = "service-a",
            packageName = "com.example",
            windowId = 3,
            capturedAt = 1_200L,
            transform = DisplayTransform(
                displayId = 0,
                widthPx = 1080,
                heightPx = 2400,
                screenshotWidthPx = 1080,
                screenshotHeightPx = 2400,
                rotation = 0,
                densityDpi = 420,
                insetLeft = 0,
                insetTop = 0,
                insetRight = 0,
                insetBottom = 0
            ),
            compactTree = JsonObject(),
            frameId = source?.let { "service-a:1:derived" },
            frameSource = source,
            frameCapturedAt = capturedAt,
            frameAgeMs = capturedAt?.let { 1_200L - it }
        )
    }
}
