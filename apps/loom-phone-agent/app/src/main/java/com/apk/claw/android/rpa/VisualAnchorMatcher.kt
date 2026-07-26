package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.NormalizedRect
import com.apk.claw.android.workflow.VisualAnchorSpec
import java.util.PriorityQueue
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt

sealed interface VisualMatch {
    data class Found(
        val left: Int,
        val top: Int,
        val width: Int,
        val height: Int,
        val scale: Float,
        val confidence: Float,
        val matchMs: Long
    ) : VisualMatch

    data class BelowThreshold(val confidence: Float, val matchMs: Long) : VisualMatch
    data class Invalid(val reason: String) : VisualMatch
}

object VisualAnchorMatcher {
    private const val COARSE_POSITION_STRIDE = 4
    private const val COARSE_SAMPLE_STRIDE = 4
    private const val REFINE_RADIUS = 6
    private const val MAX_COARSE_CANDIDATES = 8
    private const val MAX_SCALE_VARIANTS = 9
    private const val MAX_POSITION_EVALUATIONS = 1_000_000L
    private const val MAX_PIXEL_COMPARISONS = 100_000_000L
    private const val MAX_ANCHOR_PIXELS = 1_048_576L
    private const val MAX_SCALED_PLANE_PIXELS = 2_000_000L

    fun match(frame: LumaPlane, anchor: LumaPlane, spec: VisualAnchorSpec): VisualMatch {
        val started = System.nanoTime()
        val validation = validate(frame, anchor, spec)
        if (validation is Validation.Invalid) return VisualMatch.Invalid(validation.reason)
        validation as Validation.Valid

        val budget = WorkBudget(MAX_POSITION_EVALUATIONS, MAX_PIXEL_COMPARISONS)
        val coarse = PriorityQueue<Candidate>(MAX_COARSE_CANDIDATES, candidateComparator.reversed())
        for (descriptor in validation.scales) {
            val scaled = scale(anchor, descriptor)
            if (!coarseSearch(
                    frame,
                    scaled,
                    descriptor,
                    validation.region,
                    validation.expectedCenterX,
                    validation.expectedCenterY,
                    budget,
                    coarse
                )
            ) {
                return VisualMatch.Invalid("work_limit_exceeded")
            }
        }
        if (coarse.isEmpty()) return VisualMatch.Invalid("no_candidate")

        var fastBest: Candidate? = null
        val finalists = coarse.toList().sortedWith(candidateComparator)
        for (descriptor in validation.scales) {
            val candidates = finalists.filter { it.scale.order == descriptor.order }
            if (candidates.isEmpty()) continue
            val scaled = scale(anchor, descriptor)
            val refined = refine(
                frame,
                scaled,
                descriptor,
                validation.region,
                candidates,
                validation.expectedCenterX,
                validation.expectedCenterY,
                budget
            ) ?: return if (budget.exhausted) {
                VisualMatch.Invalid("work_limit_exceeded")
            } else {
                VisualMatch.Invalid("no_candidate")
            }
            if (fastBest == null || candidateComparator.compare(refined, fastBest) < 0) fastBest = refined
        }
        val bestFastCandidate = fastBest ?: return VisualMatch.Invalid("no_candidate")
        if (bestFastCandidate.error == 0L && isGloballyTieOptimal(bestFastCandidate, validation)) {
            return found(bestFastCandidate, 1f, started)
        }

        val exhaustivePositions = validation.scales.fold(0L) { total, descriptor ->
            saturatedAdd(total, exhaustivePositionCount(validation.region, descriptor))
        }
        val exhaustiveComparisons = validation.scales.fold(0L) { total, descriptor ->
            saturatedAdd(
                total,
                saturatedMultiply(
                    exhaustivePositionCount(validation.region, descriptor),
                    descriptor.width.toLong() * descriptor.height.toLong()
                )
            )
        }
        if (!budget.canConsume(exhaustivePositions, exhaustiveComparisons)) {
            return VisualMatch.Invalid("exhaustive_work_limit_exceeded")
        }

        var exactBest: Candidate? = null
        for (descriptor in validation.scales) {
            val scaled = scale(anchor, descriptor)
            val candidate = exhaustiveSearch(
                frame,
                scaled,
                descriptor,
                validation.region,
                validation.expectedCenterX,
                validation.expectedCenterY,
                budget
            ) ?: return VisualMatch.Invalid("exhaustive_work_limit_exceeded")
            if (exactBest == null || candidateComparator.compare(candidate, exactBest) < 0) exactBest = candidate
        }
        val completedBest = exactBest ?: return VisualMatch.Invalid("no_candidate")
        val completedConfidence = confidence(completedBest)
        return if (completedConfidence >= spec.minimumConfidence) {
            found(completedBest, completedConfidence, started)
        } else {
            VisualMatch.BelowThreshold(completedConfidence, elapsedMs(started))
        }
    }

    private fun validate(frame: LumaPlane, anchor: LumaPlane, spec: VisualAnchorSpec): Validation {
        if (!spec.minimumConfidence.isFinite() || spec.minimumConfidence !in 0f..1f) {
            return Validation.Invalid("minimum_confidence_invalid")
        }
        if (!spec.tapOffsetX.isFinite() || spec.tapOffsetX !in 0f..1f ||
            !spec.tapOffsetY.isFinite() || spec.tapOffsetY !in 0f..1f
        ) {
            return Validation.Invalid("tap_offset_invalid")
        }
        if (spec.scaleVariants.isEmpty() || spec.scaleVariants.size > MAX_SCALE_VARIANTS) {
            return Validation.Invalid("scale_variants_invalid")
        }
        if (spec.scaleVariants.any { !it.isFinite() || it !in 0.75f..1.25f }) {
            return Validation.Invalid("scale_variant_invalid")
        }
        if (anchor.width.toLong() * anchor.height.toLong() > MAX_ANCHOR_PIXELS) {
            return Validation.Invalid("anchor_too_large")
        }
        val region = pixelRegion(frame, spec.searchRegion)
            ?: return Validation.Invalid("search_region_invalid")
        val descriptors = spec.scaleVariants.mapIndexed { order, scale ->
            ScaleDescriptor(scale, order, scaledDimension(anchor.width, scale), scaledDimension(anchor.height, scale))
        }
        var coarsePositions = 0L
        var coarseComparisons = 0L
        for (descriptor in descriptors) {
            if (descriptor.width > region.width || descriptor.height > region.height) {
                return Validation.Invalid("anchor_outside_region")
            }
            val scaledPixels = descriptor.width.toLong() * descriptor.height.toLong()
            if (scaledPixels > MAX_SCALED_PLANE_PIXELS) return Validation.Invalid("scaled_anchor_too_large")
            val positions = coarsePositionCount(region, descriptor)
            val samples = ((descriptor.width + COARSE_SAMPLE_STRIDE - 1) / COARSE_SAMPLE_STRIDE).toLong() *
                ((descriptor.height + COARSE_SAMPLE_STRIDE - 1) / COARSE_SAMPLE_STRIDE).toLong()
            coarsePositions = saturatedAdd(coarsePositions, positions)
            coarseComparisons = saturatedAdd(coarseComparisons, saturatedMultiply(positions, samples))
        }
        if (coarsePositions > MAX_POSITION_EVALUATIONS || coarseComparisons > MAX_PIXEL_COMPARISONS) {
            return Validation.Invalid("work_limit_exceeded")
        }
        return Validation.Valid(
            region,
            descriptors,
            (region.left + region.right) / 2.0,
            (region.top + region.bottom) / 2.0
        )
    }

    private fun pixelRegion(frame: LumaPlane, normalized: NormalizedRect): PixelRegion? {
        val values = listOf(normalized.left, normalized.top, normalized.right, normalized.bottom)
        if (values.any { !it.isFinite() }) return null
        if (normalized.right <= normalized.left || normalized.bottom <= normalized.top) return null
        val left = floor(normalized.left.coerceIn(0f, 1f) * frame.width).toInt()
        val top = floor(normalized.top.coerceIn(0f, 1f) * frame.height).toInt()
        val right = ceil(normalized.right.coerceIn(0f, 1f) * frame.width).toInt()
        val bottom = ceil(normalized.bottom.coerceIn(0f, 1f) * frame.height).toInt()
        if (right <= left || bottom <= top) return null
        return PixelRegion(left, top, right, bottom)
    }

    private fun scaledDimension(source: Int, scale: Float): Int =
        (source.toDouble() * scale.toDouble()).roundToInt().coerceAtLeast(1)

    private fun scale(source: LumaPlane, descriptor: ScaleDescriptor): LumaPlane {
        if (descriptor.width == source.width && descriptor.height == source.height) return source
        val pixels = IntArray(descriptor.width * descriptor.height)
        for (y in 0 until descriptor.height) {
            val sourceY = y * source.height / descriptor.height
            for (x in 0 until descriptor.width) {
                val sourceX = x * source.width / descriptor.width
                pixels[y * descriptor.width + x] = source.pixelAt(sourceY * source.width + sourceX)
            }
        }
        return LumaPlane.owned(descriptor.width, descriptor.height, pixels)
    }

    private fun coarsePositionCount(region: PixelRegion, scale: ScaleDescriptor): Long {
        val horizontal = ((region.width - scale.width) / COARSE_POSITION_STRIDE + 1).toLong()
        val vertical = ((region.height - scale.height) / COARSE_POSITION_STRIDE + 1).toLong()
        return horizontal * vertical
    }

    private fun exhaustivePositionCount(region: PixelRegion, scale: ScaleDescriptor): Long =
        (region.width - scale.width + 1).toLong() * (region.height - scale.height + 1).toLong()

    private fun coarseSearch(
        frame: LumaPlane,
        anchor: LumaPlane,
        descriptor: ScaleDescriptor,
        region: PixelRegion,
        expectedCenterX: Double,
        expectedCenterY: Double,
        budget: WorkBudget,
        output: PriorityQueue<Candidate>
    ): Boolean {
        val maxLeft = region.right - anchor.width
        val maxTop = region.bottom - anchor.height
        val sampleColumns = (anchor.width + COARSE_SAMPLE_STRIDE - 1) / COARSE_SAMPLE_STRIDE
        val sampleRows = (anchor.height + COARSE_SAMPLE_STRIDE - 1) / COARSE_SAMPLE_STRIDE
        val sampleCount = sampleColumns * sampleRows
        var top = region.top
        while (top <= maxTop) {
            var left = region.left
            while (left <= maxLeft) {
                if (!budget.consume(1L, sampleCount.toLong())) return false
                var error = 0L
                var y = 0
                while (y < anchor.height) {
                    val frameRow = (top + y) * frame.width + left
                    val anchorRow = y * anchor.width
                    var x = 0
                    while (x < anchor.width) {
                        error += abs(frame.pixelAt(frameRow + x) - anchor.pixelAt(anchorRow + x)).toLong()
                        x += COARSE_SAMPLE_STRIDE
                    }
                    y += COARSE_SAMPLE_STRIDE
                }
                offerCandidate(
                    output,
                    candidate(left, top, descriptor, error, sampleCount, expectedCenterX, expectedCenterY)
                )
                left += COARSE_POSITION_STRIDE
            }
            top += COARSE_POSITION_STRIDE
        }
        return true
    }

    private fun refine(
        frame: LumaPlane,
        anchor: LumaPlane,
        descriptor: ScaleDescriptor,
        region: PixelRegion,
        coarse: List<Candidate>,
        expectedCenterX: Double,
        expectedCenterY: Double,
        budget: WorkBudget
    ): Candidate? {
        var best: Candidate? = null
        val visited = HashSet<Coordinate>()
        for (candidate in coarse) {
            val minLeft = maxOf(region.left, candidate.left - REFINE_RADIUS)
            val maxLeft = minOf(region.right - anchor.width, candidate.left + REFINE_RADIUS)
            val minTop = maxOf(region.top, candidate.top - REFINE_RADIUS)
            val maxTop = minOf(region.bottom - anchor.height, candidate.top + REFINE_RADIUS)
            for (top in minTop..maxTop) {
                for (left in minLeft..maxLeft) {
                    if (!visited.add(Coordinate(left, top))) continue
                    val comparisons = anchor.width.toLong() * anchor.height.toLong()
                    if (!budget.consume(1L, comparisons)) return null
                    val refined = candidate(
                        left,
                        top,
                        descriptor,
                        fullError(frame, anchor, left, top),
                        anchor.width * anchor.height,
                        expectedCenterX,
                        expectedCenterY
                    )
                    if (best == null || candidateComparator.compare(refined, best) < 0) best = refined
                }
            }
        }
        return best
    }

    private fun exhaustiveSearch(
        frame: LumaPlane,
        anchor: LumaPlane,
        descriptor: ScaleDescriptor,
        region: PixelRegion,
        expectedCenterX: Double,
        expectedCenterY: Double,
        budget: WorkBudget
    ): Candidate? {
        var best: Candidate? = null
        val comparisons = anchor.width.toLong() * anchor.height.toLong()
        for (top in region.top..region.bottom - anchor.height) {
            for (left in region.left..region.right - anchor.width) {
                if (!budget.consume(1L, comparisons)) return null
                val candidate = candidate(
                    left,
                    top,
                    descriptor,
                    fullError(frame, anchor, left, top),
                    anchor.width * anchor.height,
                    expectedCenterX,
                    expectedCenterY
                )
                if (best == null || candidateComparator.compare(candidate, best) < 0) best = candidate
            }
        }
        return best
    }

    private fun fullError(frame: LumaPlane, anchor: LumaPlane, left: Int, top: Int): Long {
        var error = 0L
        for (y in 0 until anchor.height) {
            val frameRow = (top + y) * frame.width + left
            val anchorRow = y * anchor.width
            for (x in 0 until anchor.width) {
                error += abs(frame.pixelAt(frameRow + x) - anchor.pixelAt(anchorRow + x)).toLong()
            }
        }
        return error
    }

    private fun candidate(
        left: Int,
        top: Int,
        scale: ScaleDescriptor,
        error: Long,
        sampleCount: Int,
        expectedCenterX: Double,
        expectedCenterY: Double
    ): Candidate = Candidate(
        left,
        top,
        scale,
        error,
        sampleCount,
        centerDistanceSquared(left, top, scale.width, scale.height, expectedCenterX, expectedCenterY)
    )

    private fun offerCandidate(output: PriorityQueue<Candidate>, candidate: Candidate) {
        if (output.size < MAX_COARSE_CANDIDATES) {
            output += candidate
        } else if (candidateComparator.compare(candidate, output.peek()) < 0) {
            output.poll()
            output += candidate
        }
    }

    private fun centerDistanceSquared(
        left: Int,
        top: Int,
        width: Int,
        height: Int,
        expectedCenterX: Double,
        expectedCenterY: Double
    ): Double {
        val dx = left + width / 2.0 - expectedCenterX
        val dy = top + height / 2.0 - expectedCenterY
        return dx * dx + dy * dy
    }

    private fun isGloballyTieOptimal(candidate: Candidate, validation: Validation.Valid): Boolean {
        var geometricBest: Candidate? = null
        for (descriptor in validation.scales) {
            val lefts = nearestCoordinates(
                validation.expectedCenterX - descriptor.width / 2.0,
                validation.region.left,
                validation.region.right - descriptor.width
            )
            val tops = nearestCoordinates(
                validation.expectedCenterY - descriptor.height / 2.0,
                validation.region.top,
                validation.region.bottom - descriptor.height
            )
            for (top in tops) {
                for (left in lefts) {
                    val contender = candidate(
                        left,
                        top,
                        descriptor,
                        0L,
                        descriptor.width * descriptor.height,
                        validation.expectedCenterX,
                        validation.expectedCenterY
                    )
                    if (geometricBest == null || candidateComparator.compare(contender, geometricBest) < 0) {
                        geometricBest = contender
                    }
                }
            }
        }
        return geometricBest != null && candidateComparator.compare(candidate, geometricBest) == 0
    }

    private fun nearestCoordinates(target: Double, minimum: Int, maximum: Int): IntArray {
        val lower = floor(target).toInt().coerceIn(minimum, maximum)
        val upper = ceil(target).toInt().coerceIn(minimum, maximum)
        return if (lower == upper) intArrayOf(lower) else intArrayOf(lower, upper)
    }

    private fun confidence(candidate: Candidate): Float =
        (1.0 - candidate.error.toDouble() / (candidate.sampleCount.toDouble() * 255.0))
            .coerceIn(0.0, 1.0)
            .toFloat()

    private fun found(candidate: Candidate, confidence: Float, started: Long): VisualMatch.Found =
        VisualMatch.Found(
            candidate.left,
            candidate.top,
            candidate.scale.width,
            candidate.scale.height,
            candidate.scale.scale,
            confidence,
            elapsedMs(started)
        )

    private val candidateComparator = Comparator<Candidate> { first, second ->
        compareNormalizedError(first, second)
            .takeIf { it != 0 }
            ?: first.centerDistanceSquared.compareTo(second.centerDistanceSquared).takeIf { it != 0 }
            ?: first.top.compareTo(second.top).takeIf { it != 0 }
            ?: first.left.compareTo(second.left).takeIf { it != 0 }
            ?: first.scale.scale.compareTo(second.scale.scale).takeIf { it != 0 }
            ?: first.scale.order.compareTo(second.scale.order)
    }

    private fun compareNormalizedError(first: Candidate, second: Candidate): Int =
        (first.error * second.sampleCount.toLong()).compareTo(second.error * first.sampleCount.toLong())

    private fun elapsedMs(started: Long): Long =
        ((System.nanoTime() - started).coerceAtLeast(0L)) / 1_000_000L

    private fun saturatedAdd(first: Long, second: Long): Long =
        if (first < 0L || second < 0L || Long.MAX_VALUE - first < second) Long.MAX_VALUE else first + second

    private fun saturatedMultiply(first: Long, second: Long): Long =
        if (first < 0L || second < 0L || (first != 0L && second > Long.MAX_VALUE / first)) {
            Long.MAX_VALUE
        } else {
            first * second
        }

    private sealed interface Validation {
        data class Valid(
            val region: PixelRegion,
            val scales: List<ScaleDescriptor>,
            val expectedCenterX: Double,
            val expectedCenterY: Double
        ) : Validation

        data class Invalid(val reason: String) : Validation
    }

    private data class PixelRegion(val left: Int, val top: Int, val right: Int, val bottom: Int) {
        val width: Int get() = right - left
        val height: Int get() = bottom - top
    }

    private data class ScaleDescriptor(
        val scale: Float,
        val order: Int,
        val width: Int,
        val height: Int
    )

    private data class Candidate(
        val left: Int,
        val top: Int,
        val scale: ScaleDescriptor,
        val error: Long,
        val sampleCount: Int,
        val centerDistanceSquared: Double
    )

    private data class Coordinate(val left: Int, val top: Int)

    private class WorkBudget(
        private var positionsRemaining: Long,
        private var comparisonsRemaining: Long
    ) {
        var exhausted: Boolean = false
            private set

        fun canConsume(positions: Long, comparisons: Long): Boolean =
            positions <= positionsRemaining && comparisons <= comparisonsRemaining

        fun consume(positions: Long, comparisons: Long): Boolean {
            if (!canConsume(positions, comparisons)) {
                exhausted = true
                return false
            }
            positionsRemaining -= positions
            comparisonsRemaining -= comparisons
            return true
        }
    }
}
