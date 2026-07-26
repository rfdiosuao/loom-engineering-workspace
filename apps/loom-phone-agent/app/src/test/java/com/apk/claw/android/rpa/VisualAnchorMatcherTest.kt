package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.VisualAnchorSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class VisualAnchorMatcherTest {
    @Test
    fun finds_translated_anchor_inside_bounded_region() {
        val anchor = pattern()
        val frame = blank(120, 120).draw(62, 48, anchor)

        val result = VisualAnchorMatcher.match(
            frame,
            anchor,
            spec(region = NormalizedRect(0.4f, 0.3f, 0.9f, 0.8f))
        )

        assertTrue(result is VisualMatch.Found)
        result as VisualMatch.Found
        assertEquals(62, result.left)
        assertEquals(48, result.top)
        assertEquals(1f, result.scale)
        assertEquals(1f, result.confidence, 0f)
    }

    @Test
    fun finds_supported_scaled_anchor() {
        val anchor = pattern()
        val scaled = nearestNeighbor(anchor, 1.25f)
        val frame = blank(80, 80).draw(31, 27, scaled)

        val result = VisualAnchorMatcher.match(
            frame,
            anchor,
            spec(scales = listOf(1.25f))
        ) as VisualMatch.Found

        assertEquals(31, result.left)
        assertEquals(27, result.top)
        assertEquals(scaled.width, result.width)
        assertEquals(scaled.height, result.height)
        assertEquals(1.25f, result.scale)
    }

    @Test
    fun confidence_below_threshold_never_returns_target() {
        val result = VisualAnchorMatcher.match(
            blank(64, 64, value = 127),
            pattern(),
            spec(minimumConfidence = 0.99f)
        )

        assertTrue(result is VisualMatch.BelowThreshold)
        assertTrue((result as VisualMatch.BelowThreshold).confidence < 0.99f)
    }

    @Test
    fun clamped_search_region_excludes_identical_anchor_outside_it() {
        val anchor = pattern()
        val frame = blank(100, 100).draw(4, 4, anchor)

        val result = VisualAnchorMatcher.match(
            frame,
            anchor,
            spec(region = NormalizedRect(0.50f, 0.50f, 1.5f, 1.5f), minimumConfidence = 0.99f)
        )

        assertTrue(result is VisualMatch.BelowThreshold)
    }

    @Test
    fun equal_matches_prefer_expected_region_center_then_stable_coordinates() {
        val anchor = pattern()
        val centeredRight = blank(100, 40).draw(10, 16, anchor).draw(70, 16, anchor)
        val rightResult = VisualAnchorMatcher.match(
            centeredRight,
            anchor,
            spec(region = NormalizedRect(0f, 0f, 1f, 1f))
        ) as VisualMatch.Found
        assertEquals(70, rightResult.left)

        val symmetric = blank(100, 40).draw(26, 16, anchor).draw(66, 16, anchor)
        val stableResult = VisualAnchorMatcher.match(
            symmetric,
            anchor,
            spec(region = NormalizedRect(0f, 0f, 1f, 1f))
        ) as VisualMatch.Found
        assertEquals(26, stableResult.left)
    }

    @Test
    fun invalid_non_finite_or_out_of_range_spec_fails_closed() {
        val frame = blank(40, 40)
        val anchor = pattern()

        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(minimumConfidence = Float.NaN)))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(scales = listOf(Float.POSITIVE_INFINITY))))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(scales = listOf(0.74f))))
        assertInvalid(
            VisualAnchorMatcher.match(
                frame,
                anchor,
                spec(region = NormalizedRect(Float.NaN, 0f, 1f, 1f))
            )
        )
        assertInvalid(
            VisualAnchorMatcher.match(
                frame,
                anchor,
                spec(region = NormalizedRect(0.5f, 0.5f, 0.5f, 1f))
            )
        )
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetX = -0.01f)))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetX = 1.01f)))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetY = -0.01f)))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetY = 1.01f)))
        assertInvalid(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetX = Float.NaN)))
    }

    @Test
    fun inclusive_tap_offset_boundaries_are_valid() {
        val anchor = pattern()
        val frame = blank(24, 24).draw(8, 8, anchor)

        assertTrue(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetX = 0f, tapOffsetY = 0f)) is VisualMatch.Found)
        assertTrue(VisualAnchorMatcher.match(frame, anchor, spec(tapOffsetX = 1f, tapOffsetY = 1f)) is VisualMatch.Found)
    }

    @Test
    fun exhaustive_fallback_finds_exact_anchor_hidden_from_coarse_top_eight() {
        val anchor = pattern()
        var frame = blank(180, 180)
        val decoys = listOf(
            20 to 20, 40 to 20, 60 to 20, 80 to 20, 100 to 20,
            20 to 40, 40 to 40, 60 to 40, 80 to 40, 100 to 40
        )
        decoys.forEach { (left, top) -> frame = frame.drawCoarseDecoy(left, top, anchor) }
        frame = frame.draw(150, 150, anchor)

        val result = VisualAnchorMatcher.match(frame, anchor, spec(minimumConfidence = 0.40f))

        assertTrue(result is VisualMatch.Found)
        result as VisualMatch.Found
        assertEquals(150, result.left)
        assertEquals(150, result.top)
        assertEquals(1f, result.confidence, 0f)
    }

    @Test
    fun global_zero_error_tie_break_prefers_exact_anchor_nearest_region_center() {
        val anchor = pattern()
        var frame = blank(64, 64).draw(4, 4, anchor).draw(46, 46, anchor)
        listOf(12 to 4, 20 to 4, 28 to 4, 36 to 4, 4 to 12, 4 to 20, 4 to 28).forEach { (left, top) ->
            frame = frame.drawCoarseDecoy(left, top, anchor)
        }

        val result = VisualAnchorMatcher.match(frame, anchor, spec(minimumConfidence = 1f))

        assertTrue(result is VisualMatch.Found)
        result as VisualMatch.Found
        assertEquals(46, result.left)
        assertEquals(46, result.top)
    }

    @Test
    fun incomplete_exhaustive_fallback_reports_explicit_work_limit() {
        val result = VisualAnchorMatcher.match(
            blank(400, 400, value = 127),
            LumaPlane(32, 32, IntArray(32 * 32) { (it * 37) and 0xff }),
            spec(minimumConfidence = 1f)
        )

        assertTrue(result is VisualMatch.Invalid)
        assertEquals("exhaustive_work_limit_exceeded", (result as VisualMatch.Invalid).reason)
    }

    @Test
    fun oversized_search_is_stopped_by_explicit_work_limit() {
        val frame = blank(1_600, 1_600)
        val anchor = LumaPlane(1, 1, intArrayOf(0))
        val result = VisualAnchorMatcher.match(
            frame,
            anchor,
            spec(scales = List(9) { 1f }, minimumConfidence = 0f)
        )

        assertTrue(result is VisualMatch.Invalid)
        assertEquals("work_limit_exceeded", (result as VisualMatch.Invalid).reason)
    }

    @Test
    fun luma_plane_rejects_invalid_dimensions_lengths_overflow_and_values() {
        assertThrows(IllegalArgumentException::class.java) { LumaPlane(0, 1, intArrayOf()) }
        assertThrows(IllegalArgumentException::class.java) { LumaPlane(Int.MAX_VALUE, 2, intArrayOf()) }
        assertThrows(IllegalArgumentException::class.java) { LumaPlane(2, 2, intArrayOf(0, 0, 0)) }
        assertThrows(IllegalArgumentException::class.java) { LumaPlane(1, 1, intArrayOf(256)) }
        assertThrows(IndexOutOfBoundsException::class.java) { LumaPlane(1, 1, intArrayOf(0))[1, 0] }
    }

    @Test
    fun luma_plane_rejects_impossible_shape_before_source_copy_or_luma_scan() {
        val source = intArrayOf(Int.MIN_VALUE)

        val error = assertThrows(IllegalArgumentException::class.java) {
            LumaPlane(Int.MAX_VALUE, Int.MAX_VALUE, source)
        }

        assertEquals("luma_dimensions_too_large", error.message)
    }

    @Test
    fun luma_plane_owns_public_input_even_during_concurrent_source_mutation() {
        val source = IntArray(4_096) { 42 }
        val plane = LumaPlane(64, 64, source)
        source[0] = Int.MIN_VALUE
        assertEquals(42, plane[0, 0])

        val executor = Executors.newFixedThreadPool(4)
        val futures = (0 until 4).map { worker ->
            executor.submit {
                repeat(10_000) { iteration ->
                    source[(iteration + worker) % source.size] = if (iteration and 1 == 0) Int.MIN_VALUE else Int.MAX_VALUE
                    assertEquals(42, plane[(iteration + worker) % 64, ((iteration + worker) / 64) % 64])
                }
            }
        }
        executor.shutdown()
        assertTrue(executor.awaitTermination(10, TimeUnit.SECONDS))
        futures.forEach { it.get() }
        assertEquals(42, plane[63, 63])
    }

    private fun assertInvalid(result: VisualMatch) = assertTrue(result is VisualMatch.Invalid)

    private fun spec(
        region: NormalizedRect = NormalizedRect(0f, 0f, 1f, 1f),
        minimumConfidence: Float = 0.90f,
        scales: List<Float> = listOf(1f),
        tapOffsetX: Float = 0.5f,
        tapOffsetY: Float = 0.5f
    ) = VisualAnchorSpec(
        assetName = "anchor.webp",
        searchRegion = region,
        tapOffsetX = tapOffsetX,
        tapOffsetY = tapOffsetY,
        minimumConfidence = minimumConfidence,
        scaleVariants = scales
    )

    private fun pattern(): LumaPlane {
        val pixels = IntArray(8 * 8) { index ->
            val x = index % 8
            val y = index / 8
            (x * 29 + y * 47 + x * y * 3) and 0xff
        }
        return LumaPlane(8, 8, pixels)
    }

    private fun blank(width: Int, height: Int, value: Int = 0) =
        LumaPlane(width, height, IntArray(width * height) { value })

    private fun LumaPlane.draw(left: Int, top: Int, source: LumaPlane): LumaPlane {
        val next = toIntArray()
        for (y in 0 until source.height) {
            for (x in 0 until source.width) {
                next[(top + y) * width + left + x] = source[x, y]
            }
        }
        return LumaPlane(width, height, next)
    }

    private fun LumaPlane.drawCoarseDecoy(left: Int, top: Int, source: LumaPlane): LumaPlane {
        val next = toIntArray()
        var y = 0
        while (y < source.height) {
            var x = 0
            while (x < source.width) {
                next[(top + y) * width + left + x] = source[x, y]
                x += 4
            }
            y += 4
        }
        return LumaPlane(width, height, next)
    }

    private fun nearestNeighbor(source: LumaPlane, scale: Float): LumaPlane {
        val width = (source.width * scale).toInt()
        val height = (source.height * scale).toInt()
        return LumaPlane(width, height, IntArray(width * height) { index ->
            val x = index % width
            val y = index / width
            source[x * source.width / width, y * source.height / height]
        })
    }
}
