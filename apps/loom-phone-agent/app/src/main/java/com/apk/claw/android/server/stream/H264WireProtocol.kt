package com.apk.claw.android.server.stream

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Length-delimited H.264 access units; control JSON is intentionally kept off this channel. */
object H264WireProtocol {
    const val MAGIC: Int = 0x4c554d49 // LUMI
    const val VERSION: Byte = 1
    const val FLAG_KEY_FRAME: Byte = 1
    const val HEADER_SIZE: Int = 24

    fun packet(
        payload: ByteArray,
        presentationTimeUs: Long,
        keyFrame: Boolean,
        sequence: Int
    ): ByteArray {
        require(payload.isNotEmpty()) { "H.264 payload must not be empty" }
        return ByteBuffer.allocate(HEADER_SIZE + payload.size)
            .order(ByteOrder.BIG_ENDIAN)
            .putInt(MAGIC)
            .put(VERSION)
            .put(if (keyFrame) FLAG_KEY_FRAME else 0)
            .putShort(HEADER_SIZE.toShort())
            .putLong(presentationTimeUs.coerceAtLeast(0L))
            .putInt(payload.size)
            .putInt(sequence)
            .put(payload)
            .array()
    }
}
