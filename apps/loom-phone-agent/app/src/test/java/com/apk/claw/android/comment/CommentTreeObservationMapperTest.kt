package com.apk.claw.android.comment

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CommentTreeObservationMapperTest {
    @Test
    fun maps_structured_tree_without_losing_targeting_fields() {
        val tree = JsonParser.parseString(
            """{
              "screen":{"currentPackage":"com.xingin.xhs"},
              "nodes":[{
                "resourceId":"com.xingin.xhs:id/comment_input",
                "className":"EditText",
                "text":"Say something",
                "description":"comment composer",
                "packageName":"com.xingin.xhs",
                "clickable":true,
                "editable":true,
                "focused":true,
                "visible":true,
                "enabled":true,
                "bounds":{"left":40,"top":2100,"right":900,"bottom":2250}
              }]
            }""".trimIndent()
        ).asJsonObject

        val observation = CommentTreeObservationMapper.map(tree)
        val node = observation.nodes.single()

        assertEquals("com.xingin.xhs", observation.packageName)
        assertEquals("com.xingin.xhs:id/comment_input", node.resourceId)
        assertEquals(UiBounds(40, 2100, 900, 2250), node.bounds)
        assertTrue(node.editable)
        assertTrue(node.focused)
    }
}
