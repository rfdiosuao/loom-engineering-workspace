package com.apk.claw.android.agent

import com.google.gson.JsonObject
import java.security.MessageDigest
import java.util.Locale

data class AgentActionSignature(
    val pageState: String,
    val action: String,
    val target: String
)

sealed interface OscillationDecision {
    data object Continue : OscillationDecision
    data class Blocked(val period: Int) : OscillationDecision
}

class AgentOscillationGuard(
    private val maxPeriod: Int = DEFAULT_MAX_PERIOD
) {
    private val history = ArrayDeque<AgentActionSignature>()

    init {
        require(maxPeriod > 0) { "maxPeriod must be positive" }
    }

    fun evaluateNext(candidate: AgentActionSignature): OscillationDecision {
        val prospective = (history.toList() + candidate).takeLast(maxPeriod * 2)
        for (period in 1..maxPeriod) {
            if (prospective.size < period * 2) continue
            val tail = prospective.takeLast(period * 2)
            if (tail.take(period) == tail.drop(period)) {
                return OscillationDecision.Blocked(period)
            }
        }
        return OscillationDecision.Continue
    }

    fun recordDispatched(action: AgentActionSignature) {
        history.addLast(action)
        while (history.size > maxPeriod * 2 - 1) {
            history.removeFirst()
        }
    }

    fun clear() {
        history.clear()
    }

    companion object {
        private const val DEFAULT_MAX_PERIOD = 3
    }
}

object AgentActionSignatureFactory {
    private val observationTools = setOf(
        "get_screen_info",
        "take_screenshot",
        "find_node_info",
        "get_installed_apps",
        "wait",
        "finish",
        "recall_memory",
        "list_scheduled_tasks",
        "view_suggestions",
        "view_behavior_stats"
    )
    private val nonTargetParameters = setOf("wait_after", "wait_after_ms", "duration_ms")

    fun create(
        pageState: String,
        toolName: String,
        params: Map<String, Any>
    ): AgentActionSignature? {
        val normalizedTool = toolName.trim().lowercase(Locale.US)
        if (normalizedTool.isBlank() || normalizedTool in observationTools) return null
        val canonicalParams = params.entries
            .asSequence()
            .filterNot { it.key.lowercase(Locale.US) in nonTargetParameters }
            .sortedBy { it.key }
            .joinToString("&") { (key, value) -> "$key=${canonicalValue(value)}" }
        return AgentActionSignature(
            pageState = pageState.ifBlank { "unknown" },
            action = normalizedTool,
            target = shortHash(canonicalParams)
        )
    }

    private fun canonicalValue(value: Any?): String = when (value) {
        null -> "null"
        is Map<*, *> -> value.entries
            .sortedBy { it.key.toString() }
            .joinToString(prefix = "{", postfix = "}") { "${it.key}:${canonicalValue(it.value)}" }
        is Iterable<*> -> value.joinToString(prefix = "[", postfix = "]") { canonicalValue(it) }
        is Array<*> -> value.joinToString(prefix = "[", postfix = "]") { canonicalValue(it) }
        else -> value.toString()
    }

    private fun shortHash(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .take(8)
        .joinToString("") { "%02x".format(Locale.US, it.toInt() and 0xff) }
}

object AgentPageStateFingerprint {
    fun fromTree(tree: JsonObject?): String {
        if (tree == null) return "unknown"
        val screen = tree.getAsJsonObject("screen")
        val currentPackage = screen?.string("currentPackage").orEmpty()
        val nodeParts = tree.getAsJsonArray("nodes")
            ?.asSequence()
            ?.mapNotNull { it.takeIf { element -> element.isJsonObject }?.asJsonObject }
            ?.filter { it.boolean("visible", true) }
            ?.map { node ->
                listOf(
                    node.string("resourceId"),
                    node.string("className"),
                    node.boolean("clickable", false),
                    node.boolean("editable", false),
                    node.boolean("scrollable", false),
                    node.getAsJsonObject("bounds")?.boundsKey().orEmpty()
                ).joinToString("|")
            }
            ?.toList()
            .orEmpty()
        val canonical = (listOf(currentPackage) + nodeParts).joinToString("\n")
        return MessageDigest.getInstance("SHA-256")
            .digest(canonical.toByteArray(Charsets.UTF_8))
            .take(8)
            .joinToString("") { "%02x".format(Locale.US, it.toInt() and 0xff) }
    }

    private fun JsonObject.string(name: String): String =
        get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString.orEmpty()

    private fun JsonObject.boolean(name: String, fallback: Boolean): Boolean =
        runCatching { get(name)?.takeIf { it.isJsonPrimitive }?.asBoolean }.getOrNull() ?: fallback

    private fun JsonObject.boundsKey(): String = listOf("left", "top", "right", "bottom")
        .joinToString(",") { name -> runCatching { get(name)?.asInt }.getOrNull()?.toString().orEmpty() }
}
