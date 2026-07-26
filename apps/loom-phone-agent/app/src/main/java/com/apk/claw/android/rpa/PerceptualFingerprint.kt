package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import java.security.MessageDigest
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt
import kotlin.math.sqrt

object PerceptualFingerprint {
    private const val GRID_SIZE = 8
    private const val BIT_COUNT = GRID_SIZE * GRID_SIZE
    private const val MAX_MASKS = 32
    private const val PREFIX = "pf2"
    private val encodedPattern = Regex("^pf2:([0-9a-f]{64}):([0-9a-f]{2}):([0-9a-f]{2}):([0-9a-f]{16})$")

    fun compute(frame: LumaPlane, masks: List<NormalizedRect> = emptyList()): String? {
        val pixelMasks = normalizeMasks(frame, masks) ?: return null
        val masked = BooleanArray(frame.width * frame.height)
        for (mask in pixelMasks) {
            for (y in mask.top until mask.bottom) {
                val row = y * frame.width
                for (x in mask.left until mask.right) masked[row + x] = true
            }
        }

        val supportDigest = MessageDigest.getInstance("SHA-256")
        updateInt(supportDigest, frame.width)
        updateInt(supportDigest, frame.height)
        val supportBuffer = ByteArray(SUPPORT_BUFFER_SIZE)
        var supportBufferSize = 0
        val sums = LongArray(BIT_COUNT)
        val counts = IntArray(BIT_COUNT)
        var totalSum = 0L
        var totalSquares = 0L
        var totalCount = 0L
        for (y in 0 until frame.height) {
            val cellY = y * GRID_SIZE / frame.height
            val row = y * frame.width
            for (x in 0 until frame.width) {
                val supported = !masked[row + x]
                supportBuffer[supportBufferSize++] = if (supported) 1 else 0
                if (supportBufferSize == supportBuffer.size) {
                    supportDigest.update(supportBuffer)
                    supportBufferSize = 0
                }
                if (!supported) continue
                val cellX = x * GRID_SIZE / frame.width
                val cell = cellY * GRID_SIZE + cellX
                val value = frame.pixelAt(row + x)
                sums[cell] += value.toLong()
                counts[cell]++
                totalSum += value.toLong()
                totalSquares += value.toLong() * value.toLong()
                totalCount++
            }
        }
        if (supportBufferSize > 0) supportDigest.update(supportBuffer, 0, supportBufferSize)
        if (totalCount == 0L) return null

        var bits = 0L
        for (cell in 0 until BIT_COUNT) {
            val count = counts[cell]
            if (count == 0) continue
            if (sums[cell] * totalCount >= totalSum * count.toLong()) {
                bits = bits or (1L shl cell)
            }
        }
        val mean = (totalSum.toDouble() / totalCount.toDouble()).roundToInt().coerceIn(0, 255)
        val meanExact = totalSum.toDouble() / totalCount.toDouble()
        val variance = (totalSquares.toDouble() / totalCount.toDouble() - meanExact * meanExact).coerceAtLeast(0.0)
        val standardDeviationExact = sqrt(variance)
        if (!standardDeviationExact.isFinite() || standardDeviationExact <= MIN_EXACT_STANDARD_DEVIATION) return null
        val standardDeviation = standardDeviationExact.roundToInt().coerceIn(0, 255)
        if (standardDeviation < MIN_ENCODED_STANDARD_DEVIATION) return null
        return "$PREFIX:${hex(supportDigest.digest())}:${hexByte(mean)}:${hexByte(standardDeviation)}:${hex64(bits)}"
    }

    fun isValid(encoded: String): Boolean = parse(encoded) != null

    fun distance(first: String, second: String): Int? {
        val left = parse(first) ?: return null
        val right = parse(second) ?: return null
        if (left.support != right.support) return null
        return java.lang.Long.bitCount(left.bits xor right.bits) +
            magnitudePenalty(left.mean, right.mean, MEAN_DISTANCE_QUANTUM) +
            magnitudePenalty(left.standardDeviation, right.standardDeviation, DEVIATION_DISTANCE_QUANTUM)
    }

    private fun normalizeMasks(frame: LumaPlane, masks: List<NormalizedRect>): List<PixelMask>? {
        if (masks.size > MAX_MASKS) return null
        val normalized = ArrayList<PixelMask>(masks.size)
        for (mask in masks) {
            val values = listOf(mask.left, mask.top, mask.right, mask.bottom)
            if (values.any { !it.isFinite() }) return null
            if (mask.right <= mask.left || mask.bottom <= mask.top) return null
            val left = floor(mask.left.coerceIn(0f, 1f) * frame.width).toInt()
            val top = floor(mask.top.coerceIn(0f, 1f) * frame.height).toInt()
            val right = ceil(mask.right.coerceIn(0f, 1f) * frame.width).toInt()
            val bottom = ceil(mask.bottom.coerceIn(0f, 1f) * frame.height).toInt()
            if (right > left && bottom > top) normalized += PixelMask(left, top, right, bottom)
        }
        return normalized
    }

    private fun parse(encoded: String): ParsedFingerprint? {
        val match = encodedPattern.matchEntire(encoded) ?: return null
        val mean = match.groupValues[2].toIntOrNull(16) ?: return null
        val standardDeviation = match.groupValues[3].toIntOrNull(16) ?: return null
        if (standardDeviation < MIN_ENCODED_STANDARD_DEVIATION) return null
        val bits = parseHex64(match.groupValues[4]) ?: return null
        return ParsedFingerprint(match.groupValues[1], mean, standardDeviation, bits)
    }

    private fun parseHex64(value: String): Long? {
        if (value.length != 16) return null
        var result = 0L
        for (character in value) {
            val digit = character.digitToIntOrNull(16) ?: return null
            result = (result shl 4) or digit.toLong()
        }
        return result
    }

    private fun updateInt(digest: MessageDigest, value: Int) {
        digest.update((value ushr 24).toByte())
        digest.update((value ushr 16).toByte())
        digest.update((value ushr 8).toByte())
        digest.update(value.toByte())
    }

    private fun magnitudePenalty(first: Int, second: Int, quantum: Int): Int {
        val difference = kotlin.math.abs(first - second)
        return (difference + quantum - 1) / quantum
    }

    private fun hexByte(value: Int): String = HEX[value ushr 4].toString() + HEX[value and 0x0f]
    private fun hex64(value: Long): String = java.lang.Long.toHexString(value).padStart(16, '0')

    private fun hex(bytes: ByteArray): String {
        val encoded = CharArray(bytes.size * 2)
        for (index in bytes.indices) {
            val value = bytes[index].toInt() and 0xff
            encoded[index * 2] = HEX[value ushr 4]
            encoded[index * 2 + 1] = HEX[value and 0x0f]
        }
        return String(encoded)
    }

    private data class PixelMask(val left: Int, val top: Int, val right: Int, val bottom: Int)

    private data class ParsedFingerprint(
        val support: String,
        val mean: Int,
        val standardDeviation: Int,
        val bits: Long
    )

    private const val SUPPORT_BUFFER_SIZE = 8_192
    private const val MIN_EXACT_STANDARD_DEVIATION = 4.0
    private const val MIN_ENCODED_STANDARD_DEVIATION = 5
    private const val MEAN_DISTANCE_QUANTUM = 16
    private const val DEVIATION_DISTANCE_QUANTUM = 8
    private val HEX = "0123456789abcdef".toCharArray()
}
