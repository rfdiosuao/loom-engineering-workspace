package com.apk.claw.android.rpa

import com.google.gson.JsonElement
import com.google.gson.JsonObject

data class IntRect(val left: Int, val top: Int, val right: Int, val bottom: Int)

data class CompactNode(
    val ref: String,
    val resourceId: String? = null,
    val description: String? = null,
    val text: String? = null,
    val className: String = "",
    val packageName: String = "",
    val visible: Boolean = true,
    val enabled: Boolean = true,
    val clickable: Boolean = false,
    val bounds: IntRect
)

data class CompactTreeSnapshot(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val packageName: String,
    val windowId: Int,
    val nodes: List<CompactNode>
) {
    companion object {
        const val MAX_NODES = 40
        private const val MAX_REF_LENGTH = 128
        private const val MAX_SELECTOR_LENGTH = 256

        internal fun from(evidence: UiEvidence): CompactTreeSnapshot? =
            evidence.compactTreeSnapshot()

        internal fun parse(evidence: UiEvidence, tree: JsonObject?): CompactTreeSnapshot? {
            tree ?: return null
            if (evidence.serviceGeneration.isBlank() || evidence.packageName.isBlank()) return null
            return runCatching {
                val metrics = tree.objectValue("metrics") ?: return null
                if (metrics.longValue("uiGeneration") != evidence.uiGeneration) return null
                if (metrics.stringValue("serviceGeneration", MAX_SELECTOR_LENGTH) != evidence.serviceGeneration) {
                    return null
                }
                val treePackage = tree.stringValue("currentPackage", MAX_SELECTOR_LENGTH) ?: return null
                if (treePackage != evidence.packageName) return null
                val keyNodes = tree.get("keyNodes")?.takeIf { it.isJsonArray }?.asJsonArray ?: return null
                if (keyNodes.size() > MAX_NODES) return null
                val nodes = ArrayList<CompactNode>(keyNodes.size())
                keyNodes.forEach { element ->
                    val node = element.takeIf { it.isJsonObject }?.asJsonObject ?: return null
                    nodes += parseNode(node) ?: return null
                }
                CompactTreeSnapshot(
                    uiGeneration = evidence.uiGeneration,
                    serviceGeneration = evidence.serviceGeneration,
                    packageName = evidence.packageName,
                    windowId = evidence.windowId,
                    nodes = nodes.toList()
                )
            }.getOrNull()
        }

        private fun parseNode(node: JsonObject): CompactNode? {
            val ref = node.stringValue("ref", MAX_REF_LENGTH)?.takeIf { it.isNotBlank() } ?: return null
            val resourceId = node.stringValue("resourceId", MAX_SELECTOR_LENGTH) ?: return null
            val description = node.stringValue("description", MAX_SELECTOR_LENGTH) ?: return null
            val text = node.stringValue("text", MAX_SELECTOR_LENGTH) ?: return null
            val boundsObject = node.objectValue("bounds") ?: return null
            val bounds = IntRect(
                left = boundsObject.intValue("left") ?: return null,
                top = boundsObject.intValue("top") ?: return null,
                right = boundsObject.intValue("right") ?: return null,
                bottom = boundsObject.intValue("bottom") ?: return null
            )
            if (bounds.right < bounds.left || bounds.bottom < bounds.top) return null
            return CompactNode(
                ref = ref,
                resourceId = resourceId.takeIf { it.isNotBlank() },
                description = description.takeIf { it.isNotBlank() },
                text = text.takeIf { it.isNotBlank() },
                className = node.stringValue("className", MAX_SELECTOR_LENGTH) ?: return null,
                packageName = node.stringValue("packageName", MAX_SELECTOR_LENGTH) ?: return null,
                visible = node.booleanValue("visible", default = true) ?: return null,
                enabled = node.requiredBooleanValue("enabled") ?: return null,
                clickable = node.booleanValue("clickable", default = false) ?: return null,
                bounds = bounds
            )
        }

        private fun JsonObject.objectValue(name: String): JsonObject? {
            val value = get(name) ?: return null
            return value.takeIf { it.isJsonObject }?.asJsonObject
        }

        private fun JsonObject.stringValue(name: String, maxLength: Int): String? {
            val value = get(name) ?: return null
            if (!value.isJsonPrimitive || !value.asJsonPrimitive.isString) return null
            return value.asString.takeIf { it.length <= maxLength }
        }

        private fun JsonObject.longValue(name: String): Long? {
            val value = get(name) ?: return null
            return value.integralString()?.toLongOrNull()
        }

        private fun JsonObject.intValue(name: String): Int? {
            val value = get(name) ?: return null
            return value.integralString()?.toIntOrNull()
        }

        private fun JsonElement.integralString(): String? {
            if (!isJsonPrimitive || !asJsonPrimitive.isNumber) return null
            return asString.takeIf { INTEGER_PATTERN.matches(it) }
        }

        private fun JsonObject.booleanValue(name: String, default: Boolean): Boolean? {
            val value = get(name) ?: return default
            if (!value.isJsonPrimitive || !value.asJsonPrimitive.isBoolean) return null
            return value.asBoolean
        }

        private fun JsonObject.requiredBooleanValue(name: String): Boolean? {
            val value = get(name) ?: return null
            if (!value.isJsonPrimitive || !value.asJsonPrimitive.isBoolean) return null
            return value.asBoolean
        }

        private val INTEGER_PATTERN = Regex("-?(?:0|[1-9][0-9]*)")
    }
}
