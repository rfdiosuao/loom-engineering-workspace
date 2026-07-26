package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PerceptualFingerprintTest {
    @Test
    fun masked_clock_region_does_not_change_fingerprint() {
        val first = statusFrame(32)
        val second = statusFrame(224)
        val statusBarMask = listOf(NormalizedRect(0f, 0f, 1f, 0.25f))

        assertEquals(
            PerceptualFingerprint.compute(first, statusBarMask),
            PerceptualFingerprint.compute(second, statusBarMask)
        )
    }

    @Test
    fun masks_are_clamped_before_covering_dynamic_pixels() {
        val first = statusFrame(32)
        val second = statusFrame(224)
        val oversizedStatusMask = listOf(NormalizedRect(-2f, -1f, 2f, 0.25f))

        assertEquals(
            PerceptualFingerprint.compute(first, oversizedStatusMask),
            PerceptualFingerprint.compute(second, oversizedStatusMask)
        )
    }

    @Test
    fun all_masked_or_malformed_masks_fail_closed() {
        val frame = LumaPlane(16, 16, IntArray(256) { it and 0xff })

        assertNull(PerceptualFingerprint.compute(frame, listOf(NormalizedRect(0f, 0f, 1f, 1f))))
        assertNull(PerceptualFingerprint.compute(frame, listOf(NormalizedRect(Float.NaN, 0f, 1f, 1f))))
        assertNull(PerceptualFingerprint.compute(frame, listOf(NormalizedRect(0.8f, 0f, 0.2f, 1f))))
    }

    @Test
    fun hash_has_versioned_exact_support_content_statistics_and_64_bit_payload() {
        val textured = LumaPlane(8, 8, IntArray(64) { index -> (index * 31) and 0xff })

        val hash = PerceptualFingerprint.compute(textured)

        assertTrue(hash!!.matches(Regex("^pf2:[0-9a-f]{64}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{16}$")))
        assertTrue(PerceptualFingerprint.isValid(hash!!))
    }

    @Test
    fun low_information_pages_cannot_pass_default_checkpoint_acceptance() {
        val black = PerceptualFingerprint.compute(LumaPlane(8, 8, IntArray(64) { 0 }))
        val white = PerceptualFingerprint.compute(LumaPlane(8, 8, IntArray(64) { 255 }))
        val nearBlack = PerceptualFingerprint.compute(LumaPlane(8, 8, IntArray(64) { if (it == 0) 1 else 0 }))

        assertNull(black)
        assertNull(white)
        assertNull(nearBlack)
        assertTrue(!checkpointAccepts(black, white))
        assertTrue(!checkpointAccepts(black, black))

        val support = PerceptualFingerprint.compute(statusFrame(32))!!.split(':')[1]
        val legacyBlack = "pf2:$support:00:00:ffffffffffffffff"
        val legacyWhite = "pf2:$support:ff:00:ffffffffffffffff"
        assertTrue(!checkpointAccepts(legacyBlack, legacyWhite))
        assertTrue(!PerceptualFingerprint.isValid(legacyBlack))
    }

    @Test
    fun opposite_low_contrast_pages_cannot_pass_actual_default_checkpoint_threshold() {
        val darkLowInformation = alternatingFrame(0, 8)
        val lightLowInformation = alternatingFrame(247, 255)

        val darkLowHash = PerceptualFingerprint.compute(darkLowInformation)
        val lightLowHash = PerceptualFingerprint.compute(lightLowInformation)

        assertTrue(!checkpointAccepts(darkLowHash, lightLowHash, maximumDistance = 8))

        val darkUsable = PerceptualFingerprint.compute(alternatingFrame(0, 10))!!
        val lightUsable = PerceptualFingerprint.compute(alternatingFrame(245, 255))!!
        assertTrue(PerceptualFingerprint.distance(darkUsable, lightUsable)!! > 8)
        assertTrue(!checkpointAccepts(darkUsable, lightUsable, maximumDistance = 8))
    }

    @Test
    fun distance_rejects_mismatched_exact_support() {
        val textured = statusFrame(32)
        val baseline = PerceptualFingerprint.compute(textured)!!

        val firstSupport = PerceptualFingerprint.compute(textured, listOf(NormalizedRect(0f, 0f, 0.10f, 0.10f)))!!
        val secondSupport = PerceptualFingerprint.compute(textured, listOf(NormalizedRect(0f, 0f, 0.13f, 0.10f)))!!
        assertNull(PerceptualFingerprint.distance(firstSupport, secondSupport))
        assertNull(PerceptualFingerprint.distance(baseline, "not-a-fingerprint"))
    }

    @Test
    fun bitmap_adapter_uses_integer_bt601_vectors_without_alpha_influence() {
        assertEquals(0, BitmapLumaAdapter.bt601(0x00000000))
        assertEquals(76, BitmapLumaAdapter.bt601(0xffff0000.toInt()))
        assertEquals(150, BitmapLumaAdapter.bt601(0xff00ff00.toInt()))
        assertEquals(29, BitmapLumaAdapter.bt601(0xff0000ff.toInt()))
        assertEquals(255, BitmapLumaAdapter.bt601(0x00ffffff))
    }

    private fun statusFrame(statusValue: Int): LumaPlane = LumaPlane(
        16,
        16,
        IntArray(16 * 16) { index ->
            val x = index % 16
            val y = index / 16
            if (y < 4) statusValue else (x * 11 + y * 7) and 0xff
        }
    )

    private fun alternatingFrame(low: Int, high: Int): LumaPlane =
        LumaPlane(8, 8, IntArray(64) { index -> if (index and 1 == 0) low else high })

    private fun checkpointAccepts(expected: String?, current: String?, maximumDistance: Int = 8): Boolean =
        if (expected == null || current == null) false
        else PerceptualFingerprint.distance(expected, current)?.let { it <= maximumDistance } == true
}
