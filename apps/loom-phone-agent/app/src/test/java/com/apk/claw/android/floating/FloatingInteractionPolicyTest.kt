package com.apk.claw.android.floating

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FloatingInteractionPolicyTest {

    @Test
    fun disabledClickModePassesTouchesThrough() {
        val mode = FloatingInteractionPolicy.resolve(clickEnabled = false)

        assertFalse(mode.clickEnabled)
        assertFalse(mode.dragEnabled)
        assertTrue(mode.touchPassthrough)
        assertEquals(0.72f, mode.windowAlpha, 0.001f)
    }

    @Test
    fun enabledClickModeMakesOverlayTouchable() {
        val mode = FloatingInteractionPolicy.resolve(clickEnabled = true)

        assertTrue(mode.clickEnabled)
        assertTrue(mode.dragEnabled)
        assertFalse(mode.touchPassthrough)
        assertEquals(1f, mode.windowAlpha, 0.001f)
    }
}
