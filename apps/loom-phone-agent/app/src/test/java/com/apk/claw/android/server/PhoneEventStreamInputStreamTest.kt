package com.apk.claw.android.server

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneEventStreamInputStreamTest {
    @Test
    fun generates_hello_and_snapshot_on_read_and_releases_lease_on_close() {
        val gate = PhoneEventStreamConnectionGate(maxActive = 1)
        val lease = checkNotNull(gate.tryAcquire())
        var nextId = 0L
        val stream = PhoneEventStreamInputStream(
            lease = lease,
            helloProvider = {
                JsonObject().apply {
                    addProperty("schema", "hello")
                }
            },
            snapshotProvider = {
                JsonObject().apply {
                    addProperty("schema", "snapshot")
                }
            },
            eventIdProvider = { ++nextId },
            snapshotIntervalMs = 0L,
            maxStreamMs = 10_000L
        )

        val first = readChunk(stream)
        val second = readChunk(stream)

        assertTrue(first.contains("event: hello"))
        assertTrue(first.contains("\"schema\":\"hello\""))
        assertTrue(second.contains("event: snapshot"))
        assertTrue(second.contains("\"schema\":\"snapshot\""))
        assertEquals(1, gate.activeCount())

        stream.close()

        assertEquals(0, gate.activeCount())
    }

    private fun readChunk(stream: PhoneEventStreamInputStream): String {
        val bytes = ByteArray(4096)
        val length = stream.read(bytes)
        assertTrue(length > 0)
        return bytes.decodeToString(endIndex = length)
    }
}
