package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SemanticResolverTest {
    @Test
    fun exact_resource_id_wins_and_requires_one_enabled_visible_match() {
        val snapshot = snapshot(
            node("a", resourceId = "demo:id/target"),
            node("b", text = "Target")
        )

        val result = SemanticResolver.resolve(
            snapshot,
            SemanticSelector(resourceId = "demo:id/target", text = "Target")
        )

        assertEquals(ResolverKind.RESOURCE_ID, (result as SemanticResolution.Unique).matchedBy)
        assertEquals(11L, result.generation)
        assertEquals("service-a", result.serviceGeneration)
    }

    @Test
    fun duplicate_text_is_ambiguous() {
        val result = SemanticResolver.resolve(
            snapshot(node("a", text = "Confirm"), node("b", text = "Confirm")),
            SemanticSelector(text = "Confirm")
        )

        assertTrue(result is SemanticResolution.Ambiguous)
        assertEquals(ResolverKind.TEXT_CLASS, (result as SemanticResolution.Ambiguous).matchedBy)
        assertEquals(2, result.count)
    }

    @Test
    fun higher_priority_ambiguity_does_not_fall_through_to_unique_text() {
        val result = SemanticResolver.resolve(
            snapshot(
                node("a", resourceId = "demo:id/target", text = "Other"),
                node("b", resourceId = "demo:id/target", text = "Confirm"),
            ),
            SemanticSelector(resourceId = "demo:id/target", text = "Confirm")
        )

        assertEquals(ResolverKind.RESOURCE_ID, (result as SemanticResolution.Ambiguous).matchedBy)
    }

    @Test
    fun hidden_disabled_wrong_package_and_wrong_class_nodes_are_not_matches() {
        val result = SemanticResolver.resolve(
            snapshot(
                node("hidden", text = "Confirm", visible = false),
                node("disabled", text = "Confirm", enabled = false),
                node("package", text = "Confirm", packageName = "other"),
                node("class", text = "Confirm", className = "android.widget.TextView"),
            ),
            SemanticSelector(
                text = "Confirm",
                className = "android.widget.Button",
                packageName = "demo"
            )
        )

        assertTrue(result is SemanticResolution.Missing)
        assertEquals(listOf(ResolverKind.TEXT_CLASS), (result as SemanticResolution.Missing).attempted)
    }

    @Test
    fun fully_qualified_selector_class_does_not_match_task_3_simple_class_name() {
        val result = SemanticResolver.resolve(
            snapshot(node("target", text = "Confirm", className = "Button")),
            SemanticSelector(text = "Confirm", className = "android.widget.Button")
        )

        assertTrue(result is SemanticResolution.Missing)
    }

    @Test
    fun fully_qualified_selector_class_is_preserved_on_exact_resolution() {
        val result = SemanticResolver.resolve(
            snapshot(node("target", text = "Confirm", className = "com.safe.PrimaryButton")),
            SemanticSelector(text = "Confirm", className = "com.safe.PrimaryButton")
        )

        assertEquals(
            "com.safe.PrimaryButton",
            (result as SemanticResolution.Unique).expectedClassName
        )
    }

    @Test
    fun qualified_safe_class_cannot_resolve_other_qualified_class_with_same_suffix() {
        val result = SemanticResolver.resolve(
            snapshot(node("target", text = "Confirm", className = "com.other.PrimaryButton")),
            SemanticSelector(text = "Confirm", className = "com.safe.PrimaryButton")
        )

        assertTrue(result is SemanticResolution.Missing)
    }

    @Test
    fun compact_tree_parser_reads_bounded_key_nodes_and_preserves_evidence_generations() {
        val evidence = evidence(compactTree(nodeCount = 1))

        val parsed = CompactTreeSnapshot.from(evidence)

        assertEquals(11L, parsed?.uiGeneration)
        assertEquals("service-a", parsed?.serviceGeneration)
        assertEquals("demo", parsed?.packageName)
        assertEquals(7, parsed?.windowId)
        assertEquals("demo:id/target", parsed?.nodes?.single()?.resourceId)
    }

    @Test
    fun compact_tree_parser_fails_closed_for_generation_mismatch() {
        val tree = compactTree(nodeCount = 1).apply {
            getAsJsonObject("metrics").addProperty("uiGeneration", 12L)
        }

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    @Test
    fun compact_tree_parser_fails_closed_when_node_limit_is_exceeded() {
        val tree = compactTree(nodeCount = CompactTreeSnapshot.MAX_NODES + 1)

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    @Test
    fun compact_tree_parser_fails_closed_for_malformed_bounds() {
        val tree = compactTree(nodeCount = 1).apply {
            getAsJsonArray("keyNodes").single().asJsonObject.add("bounds", JsonObject())
        }

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    @Test
    fun compact_tree_parser_fails_closed_for_malformed_selector_field() {
        val tree = compactTree(nodeCount = 1).apply {
            getAsJsonArray("keyNodes").single().asJsonObject.addProperty("resourceId", 42)
        }

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    @Test
    fun compact_tree_parser_fails_closed_when_enabled_is_missing() {
        val tree = compactTree(nodeCount = 1).apply {
            getAsJsonArray("keyNodes").single().asJsonObject.remove("enabled")
        }

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    @Test
    fun compact_tree_parser_fails_closed_when_enabled_is_not_boolean() {
        val tree = compactTree(nodeCount = 1).apply {
            getAsJsonArray("keyNodes").single().asJsonObject.addProperty("enabled", "true")
        }

        assertNull(CompactTreeSnapshot.from(evidence(tree)))
    }

    private fun snapshot(vararg nodes: CompactNode) = CompactTreeSnapshot(
        uiGeneration = 11L,
        serviceGeneration = "service-a",
        packageName = "demo",
        windowId = 7,
        nodes = nodes.toList()
    )

    private fun node(
        ref: String,
        resourceId: String? = null,
        description: String? = null,
        text: String? = null,
        className: String = "android.widget.Button",
        packageName: String = "demo",
        visible: Boolean = true,
        enabled: Boolean = true,
    ) = CompactNode(
        ref = ref,
        resourceId = resourceId,
        description = description,
        text = text,
        className = className,
        packageName = packageName,
        visible = visible,
        enabled = enabled,
        clickable = true,
        bounds = IntRect(0, 0, 100, 100)
    )

    private fun evidence(tree: JsonObject) = UiEvidence(
        uiGeneration = 11L,
        serviceGeneration = "service-a",
        packageName = "demo",
        windowId = 7,
        capturedAt = 1_000L,
        transform = DisplayTransform(0, 100, 100, 100, 100, 0, 320, 0, 0, 0, 0),
        compactTree = tree
    )

    private fun compactTree(nodeCount: Int) = JsonObject().apply {
        addProperty("currentPackage", "demo")
        add("metrics", JsonObject().apply {
            addProperty("uiGeneration", 11L)
            addProperty("serviceGeneration", "service-a")
        })
        add("keyNodes", JsonArray().apply {
            repeat(nodeCount) { index ->
                add(JsonObject().apply {
                    addProperty("ref", "ref-$index")
                    addProperty("resourceId", "demo:id/target")
                    addProperty("description", "Confirm")
                    addProperty("text", "Confirm")
                    addProperty("className", "android.widget.Button")
                    addProperty("packageName", "demo")
                    addProperty("clickable", true)
                    addProperty("enabled", true)
                    add("bounds", JsonObject().apply {
                        addProperty("left", 0)
                        addProperty("top", 0)
                        addProperty("right", 100)
                        addProperty("bottom", 100)
                    })
                })
            }
        })
    }
}
