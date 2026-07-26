package com.apk.claw.android.tool.impl

import com.apk.claw.android.comment.UiBounds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TargetedTextInputResolverTest {

    @Test
    fun resolves_exact_resource_id_instead_of_first_editable_node() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(
                packageName = "com.xingin.xhs",
                resourceId = "comment-input"
            ),
            listOf(
                node(index = 0, resourceId = "search-input"),
                node(index = 1, resourceId = "comment-input")
            )
        )

        assertEquals(1, (result as TextInputResolution.Unique).node.index)
    }

    @Test
    fun rejects_two_equally_ranked_editable_targets() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(packageName = "com.xingin.xhs"),
            listOf(node(index = 0), node(index = 1))
        )

        assertTrue(result is TextInputResolution.Ambiguous)
    }

    @Test
    fun package_mismatch_is_not_a_candidate() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(packageName = "com.xingin.xhs"),
            listOf(node(index = 0, packageName = "com.example.other"))
        )

        assertEquals(TextInputResolution.NotFound, result)
    }

    @Test
    fun missing_required_resource_id_does_not_fall_back_to_another_editor() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(
                packageName = "com.xingin.xhs",
                resourceId = "comment-input"
            ),
            listOf(node(index = 0, resourceId = "search-input"))
        )

        assertEquals(TextInputResolution.NotFound, result)
    }

    @Test
    fun require_focused_rejects_unfocused_candidate() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(packageName = "com.xingin.xhs", requireFocused = true),
            listOf(node(index = 0, focused = false))
        )

        assertEquals(TextInputResolution.NotFound, result)
    }

    @Test
    fun bounds_hint_breaks_an_otherwise_equal_tie() {
        val result = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(
                packageName = "com.xingin.xhs",
                boundsHint = UiBounds(0, 2000, 1080, 2300)
            ),
            listOf(
                node(index = 0, bounds = UiBounds(0, 100, 1080, 300)),
                node(index = 1, bounds = UiBounds(40, 2100, 900, 2250))
            )
        )

        assertEquals(1, (result as TextInputResolution.Unique).node.index)
    }

    private fun node(
        index: Int,
        packageName: String = "com.xingin.xhs",
        resourceId: String = "",
        focused: Boolean = false,
        bounds: UiBounds = UiBounds(0, 0, 100, 100)
    ) = TextInputNodeSnapshot(
        index = index,
        packageName = packageName,
        resourceId = resourceId,
        className = "android.widget.EditText",
        text = "",
        description = "",
        bounds = bounds,
        editable = true,
        focused = focused,
        visible = true,
        enabled = true
    )
}
