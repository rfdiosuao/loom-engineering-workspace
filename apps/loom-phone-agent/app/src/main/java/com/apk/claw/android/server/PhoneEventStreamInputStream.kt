package com.apk.claw.android.server

import com.google.gson.JsonObject
import java.io.InputStream

class PhoneEventStreamInputStream(
    private val lease: PhoneEventStreamConnectionGate.Lease,
    private val helloProvider: () -> JsonObject,
    private val snapshotProvider: () -> JsonObject,
    private val eventIdProvider: () -> Long,
    private val snapshotIntervalMs: Long,
    maxStreamMs: Long
) : InputStream() {
    private val deadlineMs = System.currentTimeMillis() + maxStreamMs.coerceAtLeast(1L)
    private var buffer = ByteArray(0)
    private var offset = 0
    private var first = true
    private var closed = false
    private var nextSnapshotAtMs = 0L

    override fun read(): Int {
        val one = ByteArray(1)
        val read = read(one, 0, 1)
        return if (read <= 0) -1 else one[0].toInt() and 0xff
    }

    override fun read(target: ByteArray, off: Int, len: Int): Int {
        if (closed) return -1
        if (len == 0) return 0
        if (offset >= buffer.size && !fillBuffer()) return -1
        val count = minOf(len, buffer.size - offset)
        buffer.copyInto(target, off, offset, offset + count)
        offset += count
        return count
    }

    override fun close() {
        if (!closed) {
            closed = true
            lease.close()
        }
    }

    private fun fillBuffer(): Boolean {
        if (System.currentTimeMillis() >= deadlineMs) {
            close()
            return false
        }
        val text = if (first) {
            first = false
            nextSnapshotAtMs = System.currentTimeMillis()
            PhoneEventStreamController.formatSse(
                event = "hello",
                data = helloProvider(),
                id = eventIdProvider(),
                retryMs = PhoneEventStreamController.RETRY_MS
            )
        } else {
            waitForNextSnapshot()
            if (closed || System.currentTimeMillis() >= deadlineMs) {
                close()
                return false
            }
            nextSnapshotAtMs = System.currentTimeMillis() + snapshotIntervalMs.coerceAtLeast(0L)
            PhoneEventStreamController.formatSse(
                event = "snapshot",
                data = snapshotProvider(),
                id = eventIdProvider()
            )
        }
        buffer = text.toByteArray(Charsets.UTF_8)
        offset = 0
        return buffer.isNotEmpty()
    }

    private fun waitForNextSnapshot() {
        while (!closed) {
            val now = System.currentTimeMillis()
            val waitMs = minOf(nextSnapshotAtMs - now, deadlineMs - now)
            if (waitMs <= 0) return
            try {
                Thread.sleep(minOf(waitMs, 250L))
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                close()
                return
            }
        }
    }
}
