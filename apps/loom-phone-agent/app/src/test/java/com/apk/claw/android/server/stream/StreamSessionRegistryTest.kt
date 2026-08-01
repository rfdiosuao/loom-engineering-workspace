package com.apk.claw.android.server.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class StreamSessionRegistryTest {

    @Test
    fun `session is bound to launcher client id and short token`() {
        var now = 1_000L
        val registry = StreamSessionRegistry(
            clockMs = { now },
            tokenFactory = { "short-token-1234567890" }
        )
        val options = PhoneStreamOptions(fps = 15, maxLongSide = 1280, bitRate = 2_400_000)
        val first = registry.createOrReuse("focus-1", "launcher-a", options)
        val reused = registry.createOrReuse("focus-1", "launcher-a", options)

        assertEquals(first.sessionId, reused.sessionId)
        assertEquals(first.streamToken, reused.streamToken)
        assertNull(registry.open(first.sessionId, first.streamToken, "launcher-b"))

        now += StreamSessionRegistry.TOKEN_TTL_MS + 1
        assertNull(registry.open(first.sessionId, first.streamToken, "launcher-a"))
    }

    @Test
    fun `new focused client retires previous stream session`() {
        val registry = StreamSessionRegistry(tokenFactory = { "token-${System.nanoTime()}" })
        val first = registry.createOrReuse("focus-1", "launcher-a", PhoneStreamOptions())
        val second = registry.createOrReuse("focus-2", "launcher-a", PhoneStreamOptions())

        assertFalse(registry.isCurrent(first.sessionId))
        assertTrue(registry.isCurrent(second.sessionId))
        assertNull(registry.open(first.sessionId, first.streamToken, "launcher-a"))
    }

    @Test
    fun `binary access unit keeps frame boundary timestamp and key flag`() {
        val registry = StreamSessionRegistry(tokenFactory = { "short-token-1234567890" })
        val grant = registry.createOrReuse("focus-1", "launcher-a", PhoneStreamOptions())
        registry.markActive(grant.sessionId, width = 720, height = 1280, codec = "avc1.42E01E")
        val stream = registry.open(grant.sessionId, grant.streamToken, "launcher-a")
        assertNotNull(stream)

        val payload = byteArrayOf(0, 0, 0, 1, 0x65, 1, 2, 3)
        registry.publish(grant.sessionId, payload, presentationTimeUs = 88_000L, keyFrame = true)
        val packet = ByteArray(H264WireProtocol.HEADER_SIZE + payload.size)
        var offset = 0
        while (offset < packet.size) {
            val count = stream!!.read(packet, offset, packet.size - offset)
            assertTrue(count > 0)
            offset += count
        }
        val header = ByteBuffer.wrap(packet).order(ByteOrder.BIG_ENDIAN)
        assertEquals(H264WireProtocol.MAGIC, header.int)
        assertEquals(H264WireProtocol.VERSION, header.get())
        assertEquals(H264WireProtocol.FLAG_KEY_FRAME, header.get())
        assertEquals(H264WireProtocol.HEADER_SIZE, header.short.toInt())
        assertEquals(88_000L, header.long)
        assertEquals(payload.size, header.int)
        assertEquals(1, header.int)
        assertArrayEquals(payload, packet.copyOfRange(H264WireProtocol.HEADER_SIZE, packet.size))
        stream!!.close()
    }
}
