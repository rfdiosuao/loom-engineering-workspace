package com.apk.claw.android.agent

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import java.security.MessageDigest
import java.util.Locale

object ScreenObservationBuilder {
    private const val MAX_KEY_NODES = 40
    private const val MAX_INPUT_NODES = 20
    private const val MAX_KEY_TEXTS = 60

    fun build(
        tree: JsonObject,
        capturedAt: Long = System.currentTimeMillis(),
        durationMs: Long = 0L
    ): JsonObject {
        val screen = tree.objectOrNull("screen") ?: JsonObject()
        val nodes = tree.arrayOrNull("nodes") ?: JsonArray()
        val currentPackage = firstNonBlank(
            screen.stringOrEmpty("currentPackage"),
            nodes.asSequence()
                .mapNotNull { it.asObjectOrNull()?.stringOrEmpty("packageName") }
                .firstOrNull { it.isNotBlank() }
        )
        val currentApp = screen.stringOrEmpty("currentApp")
        val keyNodes = JsonArray()
        val inputNodes = JsonArray()
        val keyTexts = JsonArray()
        val selectors = JsonArray()
        val seenTexts = linkedSetOf<String>()
        val hashParts = mutableListOf<String>()
        var totalVisibleNodes = 0

        nodes.forEach { element ->
            val node = element.asObjectOrNull() ?: return@forEach
            if (!node.booleanOrDefault("visible", true)) return@forEach
            totalVisibleNodes += 1
            if (!isDecisionNode(node)) return@forEach

            val compact = compactNode(node)
            val actionBody = actionBodyFor(node)
            if (actionBody != null) compact.add("actionBody", actionBody.deepCopy())
            if (keyNodes.size() < MAX_KEY_NODES) keyNodes.add(compact)
            if (node.booleanOrDefault("editable", false) && inputNodes.size() < MAX_INPUT_NODES) {
                inputNodes.add(compact.deepCopy())
            }
            if (actionBody != null && selectors.size() < MAX_KEY_NODES) {
                selectors.add(selectorFor(node, actionBody))
            }
            val label = nodeLabel(node)
            if (label.isNotBlank() && seenTexts.add(label) && keyTexts.size() < MAX_KEY_TEXTS) {
                keyTexts.add(label)
            }
            hashParts.add(
                listOf(
                    node.stringOrEmpty("resourceId"),
                    node.stringOrEmpty("className"),
                    label,
                    node.objectOrNull("bounds")?.stringForHash().orEmpty()
                ).joinToString("|")
            )
        }

        val summaryTexts = seenTexts.take(8)
        val summary = buildString {
            if (currentApp.isNotBlank()) append(currentApp) else if (currentPackage.isNotBlank()) append(currentPackage) else append("unknown app")
            append(": ")
            append(keyNodes.size()).append(" key nodes")
            if (summaryTexts.isNotEmpty()) {
                append("; visible: ").append(summaryTexts.joinToString(" / "))
            }
        }
        val screenHash = stableHash(listOf(currentPackage, currentApp, hashParts.joinToString("\n")).joinToString("\n"))

        return JsonObject().apply {
            addProperty("mode", "observe_fast")
            addProperty("currentPackage", currentPackage)
            addProperty("currentApp", currentApp)
            add("screen", screen.deepCopy())
            addProperty("summary", summary)
            add("keyNodes", keyNodes)
            add("inputNodes", inputNodes)
            add("keyTexts", keyTexts)
            add("selectors", selectors)
            addProperty("nodeCount", nodes.size())
            addProperty("visibleNodeCount", totalVisibleNodes)
            addProperty("screenHash", screenHash)
            addProperty("capturedAt", capturedAt)
            addProperty("durationMs", durationMs)
            add("metrics", JsonObject().apply {
                addProperty("totalMs", durationMs)
                addProperty("precheckMs", 0)
                addProperty("screenTreeMs", durationMs)
                addProperty("screenshotMs", 0)
                addProperty("llmRoundMs", 0)
                addProperty("toolCallMs", 0)
                addProperty("actionVerifyMs", 0)
                addProperty("cacheHit", false)
                addProperty("rounds", 0)
                addProperty("mode", "observe_fast")
            })
        }
    }

    fun compactIfUnchanged(
        observation: JsonObject,
        knownHash: String?,
        debug: Boolean = false
    ): JsonObject {
        val data = observation.deepCopy()
        val currentHash = data.stringOrEmpty("screenHash")
        val unchanged = knownHash?.trim()?.takeIf { it.isNotBlank() }?.equals(currentHash, ignoreCase = true) == true
        data.addProperty("unchanged", unchanged)
        data.addProperty("cacheHit", unchanged)
        val metrics = data.objectOrNull("metrics") ?: JsonObject().also { data.add("metrics", it) }
        metrics.addProperty("cacheHit", unchanged)
        if (unchanged && !debug) {
            data.add("keyNodes", JsonArray())
            data.add("inputNodes", JsonArray())
            data.add("keyTexts", JsonArray())
            data.add("selectors", JsonArray())
        }
        return data
    }

    fun stableRefForNode(node: JsonObject): String {
        val refParts = listOf(
            node.stringOrEmpty("packageName").lowercase(Locale.US),
            node.stringOrEmpty("resourceId").lowercase(Locale.US),
            node.stringOrEmpty("className").lowercase(Locale.US),
            nodeLabel(node).lowercase(Locale.US),
            node.objectOrNull("bounds")?.stringForHash().orEmpty()
        ).joinToString("|")
        return "ref_${stableHash(refParts)}"
    }

    private fun isDecisionNode(node: JsonObject): Boolean {
        return nodeLabel(node).isNotBlank() ||
            node.booleanOrDefault("clickable", false) ||
            node.booleanOrDefault("longClickable", false) ||
            node.booleanOrDefault("scrollable", false) ||
            node.booleanOrDefault("editable", false) ||
            node.booleanOrDefault("checkable", false) ||
            node.booleanOrDefault("loading", false) ||
            node.booleanOrDefault("slider", false)
    }

    private fun compactNode(node: JsonObject): JsonObject {
        return JsonObject().apply {
            addProperty("ref", stableRefForNode(node))
            addProperty("id", node.stringOrEmpty("id"))
            addProperty("className", node.stringOrEmpty("className"))
            addProperty("text", node.stringOrEmpty("text").take(120))
            addProperty("description", node.stringOrEmpty("description").take(120))
            addProperty("resourceId", node.stringOrEmpty("resourceId"))
            addProperty("packageName", node.stringOrEmpty("packageName"))
            addProperty("clickable", node.booleanOrDefault("clickable", false))
            addProperty("longClickable", node.booleanOrDefault("longClickable", false))
            addProperty("scrollable", node.booleanOrDefault("scrollable", false))
            addProperty("editable", node.booleanOrDefault("editable", false))
            addProperty("checkable", node.booleanOrDefault("checkable", false))
            addProperty("checked", node.booleanOrDefault("checked", false))
            addProperty("enabled", node.booleanOrDefault("enabled", true))
            addProperty("focused", node.booleanOrDefault("focused", false))
            val bounds = node.objectOrNull("bounds")
            add("bounds", bounds?.deepCopy() ?: JsonNull.INSTANCE)
        }
    }

    private fun selectorFor(node: JsonObject, actionBody: JsonObject): JsonObject {
        return JsonObject().apply {
            addProperty("ref", stableRefForNode(node))
            addProperty("nodeId", node.stringOrEmpty("id"))
            addProperty("label", nodeLabel(node).take(120))
            addProperty("className", node.stringOrEmpty("className"))
            addProperty("resourceId", node.stringOrEmpty("resourceId"))
            add("bounds", node.objectOrNull("bounds")?.deepCopy() ?: JsonNull.INSTANCE)
            add("actionBody", actionBody.deepCopy())
        }
    }

    private fun actionBodyFor(node: JsonObject): JsonObject? {
        val actionable = node.booleanOrDefault("clickable", false) ||
            node.booleanOrDefault("longClickable", false) ||
            node.booleanOrDefault("checkable", false) ||
            node.booleanOrDefault("editable", false)
        if (!actionable || !node.booleanOrDefault("enabled", true)) return null
        val ref = stableRefForNode(node)
        val text = node.stringOrEmpty("text").replace("\\s+".toRegex(), " ").trim()
        if (text.isNotBlank()) {
            return JsonObject().apply {
                addProperty("action", "click_text")
                addProperty("ref", ref)
                addProperty("text", text.take(120))
            }
        }
        val description = node.stringOrEmpty("description").replace("\\s+".toRegex(), " ").trim()
        if (description.isNotBlank()) {
            return JsonObject().apply {
                addProperty("action", "click_description")
                addProperty("ref", ref)
                addProperty("contentDescription", description.take(120))
            }
        }
        val resourceId = node.stringOrEmpty("resourceId").trim()
        if (resourceId.isNotBlank()) {
            return JsonObject().apply {
                addProperty("action", "click_element")
                addProperty("ref", ref)
                addProperty("resourceId", resourceId)
            }
        }
        val nodeId = node.stringOrEmpty("id").trim()
        if (nodeId.isNotBlank()) {
            return JsonObject().apply {
                addProperty("action", "click_node")
                addProperty("ref", ref)
                addProperty("nodeId", nodeId)
            }
        }
        return JsonObject().apply {
            addProperty("action", "click_ref")
            addProperty("ref", ref)
        }
    }

    private fun nodeLabel(node: JsonObject): String {
        return firstNonBlank(
            node.stringOrEmpty("text"),
            node.stringOrEmpty("description"),
            node.stringOrEmpty("resourceId")
        ).replace("\\s+".toRegex(), " ").trim()
    }

    private fun stableHash(value: String): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }.take(16)
    }

    private fun firstNonBlank(vararg values: String?): String {
        return values.firstOrNull { !it.isNullOrBlank() }.orEmpty()
    }

    private fun JsonElement.asObjectOrNull(): JsonObject? {
        return if (isJsonObject) asJsonObject else null
    }

    private fun JsonObject.objectOrNull(name: String): JsonObject? {
        val value = get(name) ?: return null
        return if (value.isJsonObject) value.asJsonObject else null
    }

    private fun JsonObject.arrayOrNull(name: String): JsonArray? {
        val value = get(name) ?: return null
        return if (value.isJsonArray) value.asJsonArray else null
    }

    private fun JsonObject.stringOrEmpty(name: String): String {
        val value = get(name) ?: return ""
        if (value.isJsonNull) return ""
        return try {
            value.asString.orEmpty()
        } catch (_: Exception) {
            ""
        }
    }

    private fun JsonObject.booleanOrDefault(name: String, default: Boolean): Boolean {
        val value = get(name) ?: return default
        if (value.isJsonNull) return default
        return try {
            value.asBoolean
        } catch (_: Exception) {
            default
        }
    }

    private fun JsonObject.stringForHash(): String {
        return entrySet()
            .sortedBy { it.key.lowercase(Locale.US) }
            .joinToString(",") { (key, value) -> "$key=${value.asStringOrRaw()}" }
    }

    private fun JsonElement.asStringOrRaw(): String {
        return try {
            if (isJsonPrimitive) asString else toString()
        } catch (_: Exception) {
            toString()
        }
    }
}
