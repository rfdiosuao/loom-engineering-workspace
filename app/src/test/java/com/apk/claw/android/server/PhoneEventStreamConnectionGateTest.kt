package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class PhoneEventStreamConnectionGateTest {
    @Test
    fun rejects_connections_after_limit_and_releases_slots() {
        val gate = PhoneEventStreamConnectionGate(maxActive = 2)

        val first = gate.tryAcquire()
        val second = gate.tryAcquire()
        val third = gate.tryAcquire()

        assertNotNull(first)
        assertNotNull(second)
        assertNull(third)
        assertEquals(2, gate.activeCount())

        first?.close()

        val replacement = gate.tryAcquire()
        assertNotNull(replacement)
        assertEquals(2, gate.activeCount())

        second?.close()
        replacement?.close()
        assertEquals(0, gate.activeCount())
    }
}
