package com.apk.claw.android.publish

import com.google.gson.JsonObject
import java.util.Locale

data class PublishCommitDecision(
    val token: String,
    val expiresAtMs: Long,
)

data class PublishTargetInspection(
    val observable: Boolean,
    val finalTarget: Boolean,
    val label: String = "",
)

data class PublishOutcomeInspection(
    val verified: Boolean,
    val evidence: String = "",
)

object PublishOutcomePolicy {
    private val successLabels = setOf(
        "发布成功",
        "发表成功",
        "提交成功",
        "发布完成",
        "已发布",
        "作品审核中",
        "正在审核",
        "审核中",
        "已提交审核",
        "提交审核成功",
    )

    private val failureFragments = setOf(
        "发布失败",
        "发表失败",
        "提交失败",
        "上传失败",
        "发布未成功",
        "网络异常",
        "请重试",
        "内容违规",
        "审核不通过",
    )

    fun inspect(tree: JsonObject?): PublishOutcomeInspection {
        val labels = tree
            ?.getAsJsonArray("nodes")
            ?.mapNotNull { element ->
                if (!element.isJsonObject) return@mapNotNull null
                val node = element.asJsonObject
                listOf("text", "description", "contentDescription")
                    .asSequence()
                    .mapNotNull { key ->
                        node.get(key)
                            ?.takeIf { it.isJsonPrimitive }
                            ?.asString
                            ?.trim()
                            ?.takeIf { it.isNotBlank() }
                    }
                    .firstOrNull()
            }
            .orEmpty()

        labels.firstOrNull(::isFailureEvidence)?.let { evidence ->
            return PublishOutcomeInspection(verified = false, evidence = evidence)
        }
        labels.firstOrNull(::isSuccessEvidence)?.let { evidence ->
            return PublishOutcomeInspection(verified = true, evidence = evidence)
        }
        return PublishOutcomeInspection(verified = false)
    }

    private fun isFailureEvidence(value: String): Boolean {
        val normalized = normalize(value)
        return failureFragments.any(normalized::contains)
    }

    private fun isSuccessEvidence(value: String): Boolean {
        return normalize(value) in successLabels
    }

    private fun normalize(value: String): String {
        return value
            .trim()
            .lowercase(Locale.ROOT)
            .replace(Regex("\\s+"), "")
            .trim('。', '！', '!', '.', '，', ',')
    }
}

object PublishCompletionPolicy {
    fun inspect(
        draftOnly: Boolean,
        executionSucceeded: Boolean,
        commitAuthorized: Boolean,
        tree: JsonObject?,
    ): PublishOutcomeInspection {
        if (!executionSucceeded) return PublishOutcomeInspection(verified = false)
        if (draftOnly) return PublishOutcomeInspection(verified = true)
        if (!commitAuthorized) return PublishOutcomeInspection(verified = false)
        return PublishOutcomePolicy.inspect(tree)
    }
}

object PublishCommitTargetPolicy {
    private const val MIN_GESTURE_DISPLACEMENT_PX = 24

    private val exactFinalLabels = setOf(
        "发布",
        "发表",
        "发帖",
        "立即发布",
        "确认发布",
        "提交发布",
        "发布作品",
        "发布内容",
        "发布图文",
        "发布照片",
        "发布动态",
        "发布笔记",
        "发布视频",
        "publish",
        "post",
        "share",
        "submit",
    )

    fun inspectTap(
        tree: JsonObject?,
        params: Map<String, Any>,
    ): PublishTargetInspection {
        val x = numberParam(params["x"])
            ?: return PublishTargetInspection(observable = true, finalTarget = false)
        val y = numberParam(params["y"])
            ?: return PublishTargetInspection(observable = true, finalTarget = false)
        return inspectPoint(tree, x, y)
    }

    fun inspectGesture(
        tree: JsonObject?,
        params: Map<String, Any>,
    ): Pair<PublishTargetInspection, String?> {
        val startX = numberParam(params["start_x"])
        val startY = numberParam(params["start_y"])
        val endX = numberParam(params["end_x"])
        val endY = numberParam(params["end_y"])
        if (startX == null || startY == null || endX == null || endY == null) {
            return PublishTargetInspection(observable = true, finalTarget = false) to null
        }
        val deltaX = endX - startX
        val deltaY = endY - startY
        if (
            deltaX.toLong() * deltaX.toLong() + deltaY.toLong() * deltaY.toLong() <
            MIN_GESTURE_DISPLACEMENT_PX.toLong() * MIN_GESTURE_DISPLACEMENT_PX.toLong()
        ) {
            return PublishTargetInspection(observable = true, finalTarget = false) to
                "Publish safety requires a minimum displacement for swipe and drag gestures"
        }
        val start = inspectPoint(tree, startX, startY)
        if (!start.observable || start.finalTarget) return start to null
        return inspectPoint(tree, endX, endY) to null
    }

    private fun inspectPoint(
        tree: JsonObject?,
        x: Int,
        y: Int,
    ): PublishTargetInspection {
        if (tree == null) return PublishTargetInspection(observable = false, finalTarget = false)
        val nodes = tree.getAsJsonArray("nodes")
            ?: return PublishTargetInspection(observable = false, finalTarget = false)

        var matchedLabel = ""
        var matchedArea = Long.MAX_VALUE
        for (element in nodes) {
            if (!element.isJsonObject) continue
            val node = element.asJsonObject
            val bounds = node.getAsJsonObject("bounds") ?: continue
            val left = jsonInt(bounds, "left") ?: continue
            val top = jsonInt(bounds, "top") ?: continue
            val right = jsonInt(bounds, "right") ?: continue
            val bottom = jsonInt(bounds, "bottom") ?: continue
            if (x !in left..right || y !in top..bottom) continue

            val labels = listOf(
                jsonString(node, "text"),
                jsonString(node, "description"),
                jsonString(node, "contentDescription"),
            ).filter { it.isNotBlank() }
            val finalLabel = labels.firstOrNull(::isFinalPublishLabel) ?: continue
            val area = (right - left).coerceAtLeast(1).toLong() *
                (bottom - top).coerceAtLeast(1).toLong()
            if (area < matchedArea) {
                matchedArea = area
                matchedLabel = finalLabel
            }
        }
        return PublishTargetInspection(
            observable = true,
            finalTarget = matchedLabel.isNotBlank(),
            label = matchedLabel,
        )
    }

    fun isFinalPublishLabel(value: String): Boolean {
        val normalized = value
            .trim()
            .lowercase(Locale.ROOT)
            .replace(Regex("\\s+"), "")
            .replace('（', '(')
            .replace('）', ')')
        if (normalized in exactFinalLabels) return true
        return Regex("^发布\\(?\\d+\\)?$").matches(normalized) ||
            Regex("^发布\\d+个(作品|内容|视频|图文|笔记)$").matches(normalized)
    }

    private fun numberParam(value: Any?): Int? = when (value) {
        is Number -> value.toInt()
        null -> null
        else -> value.toString().toDoubleOrNull()?.toInt()
    }

    private fun jsonString(obj: JsonObject, key: String): String {
        val element = obj.get(key) ?: return ""
        return if (element.isJsonPrimitive) element.asString.trim() else ""
    }

    private fun jsonInt(obj: JsonObject, key: String): Int? {
        val element = obj.get(key) ?: return null
        return if (element.isJsonPrimitive) runCatching { element.asInt }.getOrNull() else null
    }
}

object PublishRequestPolicy {
    fun mayExecute(draftOnly: Boolean, trustedCommitGate: Boolean): Boolean {
        return draftOnly || trustedCommitGate
    }
}

class PublishCommitGuard(
    private val draftOnly: Boolean,
    private val screenTree: () -> JsonObject?,
    private val authorizeCommit: () -> PublishCommitDecision,
    private val nowMs: () -> Long = System::currentTimeMillis,
) {
    @Volatile
    var commitToken: String = ""
        private set

    @Volatile
    var commitAuthorized: Boolean = false
        private set

    fun beforeToolDispatch(toolName: String, params: Map<String, Any>): String? {
        if (commitAuthorized && toolName in postCommitMutationTools) {
            return "Publish safety blocked a repeated action after commit authorization"
        }
        if (toolName == "system_key" && params["key"]?.toString()?.trim()?.equals("enter", true) == true) {
            return "Publish safety blocked Enter because it can activate a focused final publish target"
        }
        val currentTree = if (toolName in observablePointerTools) screenTree() else null
        if (toolName in setOf("swipe", "drag")) {
            val (inspection, gestureError) = PublishCommitTargetPolicy.inspectGesture(currentTree, params)
            if (gestureError != null) return gestureError
            if (!inspection.observable) {
                return "Publish safety could not inspect the current screen; observe the screen before acting"
            }
            if (inspection.finalTarget) {
                return "Publish safety blocked a gesture on final publish target '${inspection.label}'"
            }
            return null
        }
        if (toolName !in setOf("tap", "long_press")) return null
        val inspection = PublishCommitTargetPolicy.inspectTap(currentTree, params)
        if (!inspection.observable) {
            return "Publish safety could not inspect the current screen; observe the screen before acting"
        }
        if (!inspection.finalTarget) return null
        if (toolName == "long_press") {
            return "Publish safety blocked long press on final publish target '${inspection.label}'"
        }
        if (draftOnly) {
            return "Draft-only task blocked final publish target '${inspection.label}'"
        }
        if (commitAuthorized) {
            return "Publish safety blocked a repeated final publish action"
        }

        return try {
            val decision = authorizeCommit()
            if (decision.token.length < 32 || decision.expiresAtMs <= nowMs()) {
                "Publish commit authorization was invalid or expired"
            } else {
                commitToken = decision.token
                commitAuthorized = true
                null
            }
        } catch (error: Exception) {
            val detail = error.message?.take(160).orEmpty()
            "Publish commit authorization failed${if (detail.isBlank()) "" else ": $detail"}"
        }
    }

    private companion object {
        val observablePointerTools = setOf("tap", "long_press", "swipe", "drag")
        val postCommitMutationTools = setOf(
            "open_app",
            "tap",
            "long_press",
            "swipe",
            "drag",
            "scroll_to_find",
            "collect_list_items",
            "input_text",
            "system_key",
        )
    }
}
