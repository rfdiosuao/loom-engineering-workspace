package com.apk.claw.android.comment

import com.google.gson.JsonElement
import com.google.gson.JsonObject

object CommentTreeObservationMapper {
    fun map(tree: JsonObject): CommentPageObservation {
        val screen = tree.objectOrNull("screen")
        val nodes = tree.arrayOrNull("nodes")?.mapNotNull { element ->
            element.objectOrNull()?.let(::mapNode)
        }.orEmpty()
        val packageName = screen?.stringOrEmpty("currentPackage")
            ?.takeIf { it.isNotBlank() }
            ?: nodes.firstOrNull { it.packageName.isNotBlank() }?.packageName.orEmpty()
        return CommentPageObservation(packageName, nodes)
    }

    private fun mapNode(node: JsonObject): CommentUiNode {
        val bounds = node.objectOrNull("bounds")
        return CommentUiNode(
            resourceId = node.stringOrEmpty("resourceId"),
            className = node.stringOrEmpty("className"),
            text = node.stringOrEmpty("text"),
            description = node.stringOrEmpty("description"),
            packageName = node.stringOrEmpty("packageName"),
            bounds = UiBounds(
                bounds?.intOrZero("left") ?: 0,
                bounds?.intOrZero("top") ?: 0,
                bounds?.intOrZero("right") ?: 0,
                bounds?.intOrZero("bottom") ?: 0
            ),
            clickable = node.booleanOrDefault("clickable", false),
            editable = node.booleanOrDefault("editable", false),
            focused = node.booleanOrDefault("focused", false),
            visible = node.booleanOrDefault("visible", true),
            enabled = node.booleanOrDefault("enabled", true)
        )
    }

    private fun JsonElement.objectOrNull(): JsonObject? =
        if (isJsonObject) asJsonObject else null

    private fun JsonObject.objectOrNull(name: String): JsonObject? =
        get(name)?.takeIf { it.isJsonObject }?.asJsonObject

    private fun JsonObject.arrayOrNull(name: String) =
        get(name)?.takeIf { it.isJsonArray }?.asJsonArray

    private fun JsonObject.stringOrEmpty(name: String): String = runCatching {
        get(name)?.takeUnless { it.isJsonNull }?.asString.orEmpty()
    }.getOrDefault("")

    private fun JsonObject.intOrZero(name: String): Int = runCatching {
        get(name)?.takeUnless { it.isJsonNull }?.asInt ?: 0
    }.getOrDefault(0)

    private fun JsonObject.booleanOrDefault(name: String, default: Boolean): Boolean = runCatching {
        get(name)?.takeUnless { it.isJsonNull }?.asBoolean ?: default
    }.getOrDefault(default)
}
