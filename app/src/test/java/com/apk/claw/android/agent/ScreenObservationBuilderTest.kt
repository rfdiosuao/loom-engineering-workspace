package com.apk.claw.android.agent

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenObservationBuilderTest {
    @Test
    fun builds_compact_fast_observation_with_hash_and_metrics() {
        val tree = JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.example.app")
                addProperty("currentApp", "Example")
                addProperty("width", 1080)
                addProperty("height", 2400)
            })
            add("nodes", com.google.gson.JsonArray().apply {
                add(node("node-1", "Button", "提交", clickable = true))
                add(node("node-2", "EditText", "", editable = true))
                add(node("node-3", "TextView", "说明文字", clickable = false))
            })
        }

        val observed = ScreenObservationBuilder.build(tree, capturedAt = 1234L, durationMs = 17L)

        assertEquals("observe_fast", observed["mode"].asString)
        assertEquals("com.example.app", observed["currentPackage"].asString)
        assertEquals(1234L, observed["capturedAt"].asLong)
        assertEquals(17L, observed["durationMs"].asLong)
        assertTrue(observed["screenHash"].asString.length >= 12)
        assertTrue(observed["summary"].asString.contains("Example"))
        assertEquals(3, observed.getAsJsonArray("keyNodes").size())
        assertEquals(1, observed.getAsJsonArray("inputNodes").size())
        assertEquals("提交", observed.getAsJsonArray("keyTexts")[0].asString)
        assertEquals(17L, observed.getAsJsonObject("metrics")["screenTreeMs"].asLong)
    }

    @Test
    fun exposes_direct_action_selectors_for_key_nodes() {
        val tree = JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.example.app")
                addProperty("currentApp", "Example")
            })
            add("nodes", com.google.gson.JsonArray().apply {
                add(node("node-text", "Button", "Submit", clickable = true))
                add(node("node-desc", "ImageButton", "", description = "Search", clickable = true))
                add(node("node-id", "Button", "", resourceId = "com.example:id/done", clickable = true))
            })
        }

        val observed = ScreenObservationBuilder.build(tree)
        val keyNodes = observed.getAsJsonArray("keyNodes")
        val selectors = observed.getAsJsonArray("selectors")

        assertEquals(3, selectors.size())

        val textAction = keyNodes[0].asJsonObject.getAsJsonObject("actionBody")
        assertEquals("click_text", textAction["action"].asString)
        assertEquals("Submit", textAction["text"].asString)

        val descriptionAction = keyNodes[1].asJsonObject.getAsJsonObject("actionBody")
        assertEquals("click_description", descriptionAction["action"].asString)
        assertEquals("Search", descriptionAction["contentDescription"].asString)

        val resourceAction = keyNodes[2].asJsonObject.getAsJsonObject("actionBody")
        assertEquals("click_element", resourceAction["action"].asString)
        assertEquals("com.example:id/done", resourceAction["resourceId"].asString)
        assertEquals("click_element", selectors[2].asJsonObject.getAsJsonObject("actionBody")["action"].asString)
    }

    @Test
    fun emits_stable_refs_for_snapshot_act_contract() {
        val firstTree = JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.example.app")
                addProperty("currentApp", "Example")
            })
            add("nodes", com.google.gson.JsonArray().apply {
                add(node("runtime-node-a", "Button", "Continue", clickable = true))
            })
        }
        val secondTree = JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.example.app")
                addProperty("currentApp", "Example")
            })
            add("nodes", com.google.gson.JsonArray().apply {
                add(node("runtime-node-b", "Button", "Continue", clickable = true))
            })
        }

        val first = ScreenObservationBuilder.build(firstTree)
        val second = ScreenObservationBuilder.build(secondTree)
        val firstNode = first.getAsJsonArray("keyNodes")[0].asJsonObject
        val secondNode = second.getAsJsonArray("keyNodes")[0].asJsonObject
        val firstSelector = first.getAsJsonArray("selectors")[0].asJsonObject
        val ref = firstNode["ref"].asString

        assertTrue(ref.startsWith("ref_"))
        assertEquals(ref, secondNode["ref"].asString)
        assertEquals(ref, firstSelector["ref"].asString)
        assertEquals(ref, firstNode.getAsJsonObject("actionBody")["ref"].asString)
    }

    @Test
    fun strips_heavy_nodes_when_known_hash_is_unchanged_without_debug() {
        val tree = JsonObject().apply {
            add("screen", JsonObject().apply {
                addProperty("currentPackage", "com.example.app")
                addProperty("currentApp", "Example")
            })
            add("nodes", com.google.gson.JsonArray().apply {
                add(node("node-1", "Button", "Submit", clickable = true))
                add(node("node-2", "EditText", "", editable = true))
            })
        }
        val observed = ScreenObservationBuilder.build(tree, capturedAt = 1234L, durationMs = 17L)

        val incremental = ScreenObservationBuilder.compactIfUnchanged(
            observed,
            knownHash = observed["screenHash"].asString,
            debug = false
        )

        assertEquals(true, incremental["unchanged"].asBoolean)
        assertEquals(true, incremental["cacheHit"].asBoolean)
        assertEquals(observed["screenHash"].asString, incremental["screenHash"].asString)
        assertEquals(observed["summary"].asString, incremental["summary"].asString)
        assertEquals(0, incremental.getAsJsonArray("keyNodes").size())
        assertEquals(0, incremental.getAsJsonArray("inputNodes").size())
        assertEquals(0, incremental.getAsJsonArray("keyTexts").size())
        assertEquals(0, incremental.getAsJsonArray("selectors").size())
        assertEquals(true, incremental.getAsJsonObject("metrics")["cacheHit"].asBoolean)
    }

    private fun node(
        id: String,
        className: String,
        text: String,
        description: String = "",
        resourceId: String = "",
        clickable: Boolean = false,
        editable: Boolean = false
    ): JsonObject {
        return JsonObject().apply {
            addProperty("id", id)
            addProperty("className", className)
            addProperty("text", text)
            addProperty("description", description)
            addProperty("resourceId", resourceId)
            addProperty("packageName", "com.example.app")
            addProperty("visible", true)
            addProperty("clickable", clickable)
            addProperty("editable", editable)
            addProperty("scrollable", false)
            addProperty("enabled", true)
            add("bounds", JsonObject().apply {
                addProperty("left", 0)
                addProperty("top", 0)
                addProperty("right", 100)
                addProperty("bottom", 80)
                addProperty("centerX", 50)
                addProperty("centerY", 40)
            })
        }
    }
}
