package com.apk.claw.android.service

object NodeAwareTapSelector {
    private const val MAX_UNLABELLED_AREA_PERCENT = 60L

    data class Candidate(
        val index: Int,
        val left: Int,
        val top: Int,
        val right: Int,
        val bottom: Int,
        val depth: Int,
        val enabled: Boolean,
        val visible: Boolean,
        val semantic: Boolean
    )

    @JvmStatic
    fun selectIndex(candidates: List<Candidate>, x: Int, y: Int, rootArea: Long): Int {
        var bestIndex = -1
        var bestArea = Long.MAX_VALUE
        var bestDepth = Int.MIN_VALUE

        for (candidate in candidates) {
            if (!candidate.enabled || !candidate.visible) continue
            if (candidate.right <= candidate.left || candidate.bottom <= candidate.top) continue
            if (x < candidate.left || x >= candidate.right || y < candidate.top || y >= candidate.bottom) continue

            val area = (candidate.right - candidate.left).toLong() *
                (candidate.bottom - candidate.top).toLong()
            val tooBroad = rootArea > 0L &&
                area * 100L > rootArea * MAX_UNLABELLED_AREA_PERCENT
            if (tooBroad && !candidate.semantic) continue

            if (area < bestArea || (area == bestArea && candidate.depth > bestDepth)) {
                bestIndex = candidate.index
                bestArea = area
                bestDepth = candidate.depth
            }
        }
        return bestIndex
    }
}
