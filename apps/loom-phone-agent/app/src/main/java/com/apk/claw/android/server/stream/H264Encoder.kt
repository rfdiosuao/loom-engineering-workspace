package com.apk.claw.android.server.stream

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.view.Surface
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicBoolean

/** Surface-input AVC encoder that emits complete low-latency access units. */
class H264Encoder(
    private val width: Int,
    private val height: Int,
    private val fps: Int,
    private val bitRate: Int,
    private val onAccessUnit: (ByteArray, Long, Boolean) -> Unit,
    private val onError: (Throwable) -> Unit
) {
    private val running = AtomicBoolean(false)
    private var codec: MediaCodec? = null
    private var drainThread: Thread? = null
    private var codecConfig: ByteArray? = null

    fun start(): Surface {
        check(running.compareAndSet(false, true)) { "H264 encoder already started" }
        val encoder = MediaCodec.createEncoderByType(MIME)
        val format = MediaFormat.createVideoFormat(MIME, width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, bitRate)
            setInteger(MediaFormat.KEY_FRAME_RATE, fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR)
            setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline)
            setInteger(MediaFormat.KEY_LEVEL, MediaCodecInfo.CodecProfileLevel.AVCLevel31)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                setInteger(MediaFormat.KEY_PRIORITY, 0)
                setInteger(MediaFormat.KEY_OPERATING_RATE, fps)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                setInteger(MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES, 1)
            }
        }
        encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val surface = encoder.createInputSurface()
        encoder.start()
        codec = encoder
        drainThread = Thread({ drain(encoder) }, "lumi-phone-h264").apply {
            isDaemon = true
            start()
        }
        return surface
    }

    fun requestSyncFrame() {
        if (!running.get()) return
        try {
            codec?.setParameters(android.os.Bundle().apply {
                putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0)
            })
        } catch (_: Exception) {
        }
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        try {
            codec?.signalEndOfInputStream()
        } catch (_: Exception) {
        }
        try {
            drainThread?.join(1_000)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        drainThread = null
        val encoder = codec
        codec = null
        try {
            encoder?.stop()
        } catch (_: Exception) {
        }
        try {
            encoder?.release()
        } catch (_: Exception) {
        }
    }

    private fun drain(encoder: MediaCodec) {
        val info = MediaCodec.BufferInfo()
        try {
            while (running.get()) {
                when (val index = encoder.dequeueOutputBuffer(info, 10_000)) {
                    MediaCodec.INFO_TRY_AGAIN_LATER,
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> Unit
                    else -> if (index >= 0) {
                        val buffer = encoder.getOutputBuffer(index)
                        if (buffer != null && info.size > 0) {
                            buffer.position(info.offset)
                            buffer.limit(info.offset + info.size)
                            val bytes = ByteArray(info.size)
                            buffer.get(bytes)
                            val annexB = toAnnexB(bytes)
                            val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                            val isKey = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                            if (isConfig) {
                                codecConfig = annexB
                            } else {
                                val payload = if (isKey && codecConfig != null && !startsWithConfig(annexB)) {
                                    codecConfig!! + annexB
                                } else annexB
                                onAccessUnit(payload, info.presentationTimeUs, isKey)
                            }
                        }
                        encoder.releaseOutputBuffer(index, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }
                }
            }
        } catch (error: Throwable) {
            if (running.get()) onError(error)
        }
    }

    private fun startsWithConfig(bytes: ByteArray): Boolean {
        val nalIndex = when {
            bytes.size >= 5 && bytes[0] == 0.toByte() && bytes[1] == 0.toByte() && bytes[2] == 0.toByte() && bytes[3] == 1.toByte() -> 4
            bytes.size >= 4 && bytes[0] == 0.toByte() && bytes[1] == 0.toByte() && bytes[2] == 1.toByte() -> 3
            else -> return false
        }
        val nalType = bytes[nalIndex].toInt() and 0x1f
        return nalType == 7 || nalType == 8
    }

    private fun toAnnexB(bytes: ByteArray): ByteArray {
        if (
            bytes.size >= 4 && bytes[0] == 0.toByte() && bytes[1] == 0.toByte() &&
            (bytes[2] == 1.toByte() || (bytes[2] == 0.toByte() && bytes[3] == 1.toByte()))
        ) return bytes
        val output = ByteArrayOutputStream(bytes.size + 16)
        var offset = 0
        while (offset + 4 <= bytes.size) {
            val nalLength = ByteBuffer.wrap(bytes, offset, 4).int
            if (nalLength <= 0 || nalLength > bytes.size - offset - 4) {
                return byteArrayOf(0, 0, 0, 1) + bytes
            }
            output.write(byteArrayOf(0, 0, 0, 1))
            output.write(bytes, offset + 4, nalLength)
            offset += 4 + nalLength
        }
        return if (offset == bytes.size) output.toByteArray() else byteArrayOf(0, 0, 0, 1) + bytes
    }

    companion object {
        private const val MIME = "video/avc"
        const val CODEC = "avc1.42E01F"
    }
}
