package com.apk.claw.android.rpa

import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 24)
class AccessibilitySemanticNodeApi24Test {
    @Suppress("DEPRECATION")
    @Test
    fun real_clickable_ancestor_is_clicked_once_and_recycled_while_target_stays_caller_owned() {
        val target = AccessibilityNodeInfo.obtain().apply {
            className = "android.widget.TextView"
            packageName = "demo"
            isClickable = false
        }
        val clickableAncestor = AccessibilityNodeInfo.obtain().apply {
            className = "android.widget.Button"
            packageName = "demo"
            isClickable = true
        }
        var beforeActionCalls = 0
        var actionCalls = 0

        val accepted = AccessibilitySemanticClickPolicy.click(
            node = target,
            beforeAction = Runnable { beforeActionCalls += 1 },
            parentOf = { node -> if (node === target) clickableAncestor else null },
            performAction = { node, action ->
                assertSame(clickableAncestor, node)
                assertEquals(AccessibilityNodeInfo.ACTION_CLICK, action)
                actionCalls += 1
                true
            }
        )

        assertTrue(accepted)
        assertEquals(1, beforeActionCalls)
        assertEquals(1, actionCalls)

        target.contentDescription = "still caller owned"
        assertEquals("still caller owned", target.contentDescription.toString())
        target.recycle()

        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) {
            var alreadyRecycled = false
            try {
                clickableAncestor.recycle()
            } catch (_: IllegalStateException) {
                alreadyRecycled = true
            }
            assertTrue("clickable ancestor was not recycled by the policy", alreadyRecycled)
        }
    }
}
