package com.apk.claw.android.service

import org.junit.Assert.assertEquals
import org.junit.Test

class NodeAwareTapSelectorTest {

    @Test
    fun selectsSmallestLiveClickableTargetContainingTap() {
        val candidates = listOf(
            candidate(index = 0, left = 0, top = 0, right = 1080, bottom = 2400, depth = 0),
            candidate(index = 1, left = 40, top = 400, right = 1040, bottom = 560, depth = 3),
            candidate(index = 2, left = 160, top = 420, right = 720, bottom = 540, depth = 5)
        )

        assertEquals(2, NodeAwareTapSelector.selectIndex(candidates, 500, 480, 1080L * 2400L))
    }

    @Test
    fun ignoresUnlabelledFullscreenClickableSurface() {
        val candidates = listOf(
            candidate(index = 0, left = 0, top = 0, right = 1080, bottom = 2400, depth = 0)
        )

        assertEquals(-1, NodeAwareTapSelector.selectIndex(candidates, 500, 1200, 1080L * 2400L))
    }

    @Test
    fun allowsLargeTargetWhenItHasSemanticIdentity() {
        val candidates = listOf(
            candidate(
                index = 4,
                left = 0,
                top = 100,
                right = 1080,
                bottom = 2000,
                depth = 2,
                semantic = true
            )
        )

        assertEquals(4, NodeAwareTapSelector.selectIndex(candidates, 500, 1000, 1080L * 2400L))
    }

    @Test
    fun ignoresDisabledInvisibleAndOutOfBoundsTargets() {
        val candidates = listOf(
            candidate(index = 1, left = 100, top = 100, right = 300, bottom = 300, depth = 4, enabled = false),
            candidate(index = 2, left = 100, top = 100, right = 300, bottom = 300, depth = 5, visible = false),
            candidate(index = 3, left = 500, top = 500, right = 700, bottom = 700, depth = 6)
        )

        assertEquals(-1, NodeAwareTapSelector.selectIndex(candidates, 200, 200, 1080L * 2400L))
    }

    private fun candidate(
        index: Int,
        left: Int,
        top: Int,
        right: Int,
        bottom: Int,
        depth: Int,
        enabled: Boolean = true,
        visible: Boolean = true,
        semantic: Boolean = false
    ) = NodeAwareTapSelector.Candidate(
        index = index,
        left = left,
        top = top,
        right = right,
        bottom = bottom,
        depth = depth,
        enabled = enabled,
        visible = visible,
        semantic = semantic
    )
}
