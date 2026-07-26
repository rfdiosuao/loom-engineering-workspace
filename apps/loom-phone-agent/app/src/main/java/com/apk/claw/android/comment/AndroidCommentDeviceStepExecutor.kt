package com.apk.claw.android.comment

import android.content.Context
import android.content.Intent
import android.graphics.Rect
import android.net.Uri
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.tool.ToolRegistry
import com.apk.claw.android.tool.impl.TextInputNodeSnapshot
import com.apk.claw.android.tool.impl.TextInputResolution
import com.apk.claw.android.tool.impl.TextInputTargetSpec
import com.apk.claw.android.tool.impl.TargetedTextInputResolver
import java.util.Locale

class AndroidCommentDeviceStepExecutor(
    private val context: Context,
    private val classifier: XiaohongshuCommentPageClassifier = XiaohongshuCommentPageClassifier(),
    private val sleep: (Long) -> Unit = SystemClock::sleep
) : CommentDeviceStepExecutor {
    override fun execute(
        plan: CommentDeviceStepPlan,
        campaign: CommentCampaign,
        item: CommentCampaignItem
    ): CommentDeviceStepResult {
        val service = ClawAccessibilityService.getInstance()
            ?: return needsAccessibility()
        return try {
            when (plan.action) {
                "begin_navigation" ->
                    CommentDeviceStepResult.Advance(CommentItemState.NAVIGATING, "navigation_checkpoint")
                "navigate_video" -> navigateVideo(service, item)
                "open_comment_composer" -> openComposer(service)
                "focus_comment_input" -> focusInput(service)
                "input_and_verify_text" -> inputAndVerify(service, item)
                "send_and_verify" -> sendAndVerify(service, item)
                else -> CommentDeviceStepResult.Failed(
                    "unsupported_comment_action",
                    "Unsupported deterministic comment action: ${plan.action}"
                )
            }
        } catch (error: Exception) {
            if (plan.action == "send_and_verify") {
                CommentDeviceStepResult.SendUncertain("driver_exception:${error.javaClass.simpleName}")
            } else {
                CommentDeviceStepResult.Failed(
                    "comment_driver_exception",
                    "Android comment driver failed before send",
                    "driver_exception:${error.javaClass.simpleName}"
                )
            }
        }
    }

    private fun navigateVideo(
        service: ClawAccessibilityService,
        item: CommentCampaignItem
    ): CommentDeviceStepResult {
        val initial = observe(service) ?: return treeUnavailable()
        when (classifier.classify(initial.observation)) {
            CommentPageState.VIDEO ->
                return CommentDeviceStepResult.Advance(CommentItemState.VIDEO_VERIFIED, "video_already_foreground")
            CommentPageState.BLOCKED -> return blocked()
            else -> Unit
        }

        val uri = approvedVideoUri(item.videoId)
            ?: return CommentDeviceStepResult.NeedsHuman(
                "video_deep_link_required",
                "Prepared target must contain an approved Xiaohongshu note URL or note id"
            )
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            setPackage(XHS_PACKAGE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        runCatching { context.startActivity(intent) }.getOrElse {
            return CommentDeviceStepResult.NeedsHuman(
                "video_target_unreachable",
                "Xiaohongshu could not open the prepared video target"
            )
        }

        return when (waitForState(service, setOf(CommentPageState.VIDEO, CommentPageState.BLOCKED))) {
            CommentPageState.VIDEO ->
                CommentDeviceStepResult.Advance(CommentItemState.VIDEO_VERIFIED, "video_opened_and_verified")
            CommentPageState.BLOCKED -> blocked()
            else -> CommentDeviceStepResult.Retry(
                "video_transition_pending",
                "Prepared video did not reach a stable video page"
            )
        }
    }

    private fun openComposer(service: ClawAccessibilityService): CommentDeviceStepResult {
        val frame = observe(service) ?: return treeUnavailable()
        when (classifier.classify(frame.observation)) {
            CommentPageState.COMMENT_SHEET,
            CommentPageState.INPUT_FOCUSED ->
                return CommentDeviceStepResult.Advance(CommentItemState.COMPOSER_OPEN, "comment_sheet_already_open")
            CommentPageState.BLOCKED -> return blocked()
            CommentPageState.OTHER_APP -> return wrongApp()
            CommentPageState.UNKNOWN -> return CommentDeviceStepResult.Retry(
                "video_page_unstable",
                "Video page is not stable enough to open comments"
            )
            CommentPageState.VIDEO -> Unit
        }

        val target = when (
            val resolution = CommentActionTargetResolver.resolve(
                CommentActionKind.OPEN_COMPOSER,
                frame.observation.nodes
            )
        ) {
            is CommentActionTargetResolution.Unique -> resolution.node
            is CommentActionTargetResolution.Ambiguous -> return CommentDeviceStepResult.Retry(
                "comment_control_ambiguous",
                "Multiple comment controls matched"
            )
            CommentActionTargetResolution.NotFound -> return CommentDeviceStepResult.Retry(
                "comment_control_unreachable",
                "No unique comment control was found"
            )
        }
        if (!clickTreeNode(service, target)) {
            return CommentDeviceStepResult.Retry(
                "comment_control_click_failed",
                "The unique comment control could not be clicked"
            )
        }
        return when (
            waitForState(
                service,
                setOf(CommentPageState.COMMENT_SHEET, CommentPageState.INPUT_FOCUSED, CommentPageState.BLOCKED)
            )
        ) {
            CommentPageState.COMMENT_SHEET,
            CommentPageState.INPUT_FOCUSED ->
                CommentDeviceStepResult.Advance(CommentItemState.COMPOSER_OPEN, "comment_sheet_open_verified")
            CommentPageState.BLOCKED -> blocked()
            else -> CommentDeviceStepResult.Retry(
                "comment_sheet_transition_pending",
                "Comment sheet did not become stable after the click"
            )
        }
    }

    private fun focusInput(service: ClawAccessibilityService): CommentDeviceStepResult {
        val frame = observe(service) ?: return treeUnavailable()
        when (classifier.classify(frame.observation)) {
            CommentPageState.INPUT_FOCUSED ->
                return CommentDeviceStepResult.Advance(CommentItemState.INPUT_FOCUSED, "input_already_focused")
            CommentPageState.BLOCKED -> return blocked()
            CommentPageState.OTHER_APP -> return wrongApp()
            CommentPageState.COMMENT_SHEET -> Unit
            else -> return CommentDeviceStepResult.Retry(
                "comment_composer_unreachable",
                "Comment composer is not open"
            )
        }
        val editor = resolveEditor(frame.observation)
            ?: return CommentDeviceStepResult.Retry(
                "comment_composer_ambiguous",
                "No unique editable comment composer was found"
            )
        if (!clickTreeNode(service, editor)) {
            return CommentDeviceStepResult.Retry(
                "comment_composer_focus_failed",
                "Comment composer could not be focused"
            )
        }
        return when (waitForState(service, setOf(CommentPageState.INPUT_FOCUSED, CommentPageState.BLOCKED))) {
            CommentPageState.INPUT_FOCUSED ->
                CommentDeviceStepResult.Advance(CommentItemState.INPUT_FOCUSED, "input_focus_verified")
            CommentPageState.BLOCKED -> blocked()
            else -> CommentDeviceStepResult.Retry(
                "comment_composer_focus_pending",
                "Comment composer focus was not observable"
            )
        }
    }

    private fun inputAndVerify(
        service: ClawAccessibilityService,
        item: CommentCampaignItem
    ): CommentDeviceStepResult {
        val frame = observe(service) ?: return treeUnavailable()
        when (classifier.classify(frame.observation)) {
            CommentPageState.BLOCKED -> return blocked()
            CommentPageState.OTHER_APP -> return wrongApp()
            CommentPageState.INPUT_FOCUSED -> Unit
            else -> return CommentDeviceStepResult.Retry(
                "comment_composer_not_focused",
                "Comment composer must be uniquely focused before input"
            )
        }
        val editor = resolveEditor(frame.observation)
            ?: return CommentDeviceStepResult.Retry(
                "comment_composer_ambiguous",
                "No unique focused comment composer was found"
            )
        val params = mutableMapOf<String, Any>(
            "text" to item.commentText,
            "clear_first" to true,
            "package_name" to XHS_PACKAGE,
            "bounds_hint" to editor.bounds.toMap(),
            "require_focused" to true
        )
        if (editor.resourceId.isNotBlank()) params["resource_id"] = editor.resourceId
        val hint = editor.text.ifBlank { editor.description }
        if (hint.isNotBlank()) params["text_hint"] = hint

        val toolResult = ToolRegistry.getInstance().executeTool("input_text", params)
        if (!toolResult.isSuccess) {
            val code = when {
                toolResult.error.orEmpty().contains("ambiguous") -> "comment_composer_ambiguous"
                else -> "comment_composer_unreachable"
            }
            return CommentDeviceStepResult.Retry(code, toolResult.error ?: "Comment input failed")
        }
        val verified = waitForObservation(service) { observation ->
            observation.nodes.any { node ->
                node.visible && node.enabled && node.editable && normalize(node.text) == normalize(item.commentText)
            }
        }
        return if (verified != null) {
            CommentDeviceStepResult.Advance(CommentItemState.TEXT_VERIFIED, "comment_text_exact_match")
        } else {
            CommentDeviceStepResult.Retry(
                "comment_text_not_verified",
                "Input completed but the exact comment text was not observable"
            )
        }
    }

    private fun sendAndVerify(
        service: ClawAccessibilityService,
        item: CommentCampaignItem
    ): CommentDeviceStepResult {
        val frame = observe(service) ?: return CommentDeviceStepResult.SendUncertain("screen_tree_unavailable_before_send")
        if (classifier.classify(frame.observation) == CommentPageState.BLOCKED) {
            return blocked()
        }
        val exactTextReady = frame.observation.nodes.any { node ->
            node.visible && node.enabled && node.editable && normalize(node.text) == normalize(item.commentText)
        }
        if (!exactTextReady) {
            return CommentDeviceStepResult.Failed(
                "comment_text_changed_before_send",
                "Exact comment text precondition failed before send"
            )
        }
        val sendTarget = when (
            val resolution = CommentActionTargetResolver.resolve(
                CommentActionKind.SEND,
                frame.observation.nodes
            )
        ) {
            is CommentActionTargetResolution.Unique -> resolution.node
            is CommentActionTargetResolution.Ambiguous -> return CommentDeviceStepResult.Failed(
                "comment_send_ambiguous",
                "Multiple send controls matched"
            )
            CommentActionTargetResolution.NotFound -> return CommentDeviceStepResult.Failed(
                "comment_send_unreachable",
                "No unique send control was found"
            )
        }
        if (!clickTreeNode(service, sendTarget)) {
            return CommentDeviceStepResult.SendUncertain("send_click_dispatch_unconfirmed")
        }

        val evidence = waitForObservation(service, timeoutMs = SEND_VERIFY_TIMEOUT_MS) { observation ->
            observation.nodes.any { node ->
                node.visible && !node.editable && normalize(node.text) == normalize(item.commentText)
            }
        }
        return if (evidence != null) {
            CommentDeviceStepResult.SendVerified("exact_comment_visible_after_send")
        } else {
            CommentDeviceStepResult.SendUncertain("exact_comment_not_observed_after_send")
        }
    }

    private fun observe(service: ClawAccessibilityService): ObservedFrame? {
        val tree = service.screenTreeJson ?: return null
        return ObservedFrame(tree.toString(), CommentTreeObservationMapper.map(tree))
    }

    private fun waitForState(
        service: ClawAccessibilityService,
        expected: Set<CommentPageState>,
        timeoutMs: Long = STATE_TIMEOUT_MS
    ): CommentPageState? {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        do {
            val state = observe(service)?.observation?.let(classifier::classify)
            if (state in expected) return state
            sleep(POLL_MS)
        } while (SystemClock.elapsedRealtime() < deadline)
        return observe(service)?.observation?.let(classifier::classify)
    }

    private fun waitForObservation(
        service: ClawAccessibilityService,
        timeoutMs: Long = STATE_TIMEOUT_MS,
        predicate: (CommentPageObservation) -> Boolean
    ): CommentPageObservation? {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        do {
            val observation = observe(service)?.observation
            if (observation != null && predicate(observation)) return observation
            sleep(POLL_MS)
        } while (SystemClock.elapsedRealtime() < deadline)
        return observe(service)?.observation?.takeIf(predicate)
    }

    private fun resolveEditor(observation: CommentPageObservation): CommentUiNode? {
        val editors = observation.nodes.filter { it.visible && it.enabled && it.editable }
        val preferred = editors.filter { node ->
            val value = "${node.resourceId} ${node.text} ${node.description}".lowercase(Locale.ROOT)
            EDITOR_TERMS.any(value::contains)
        }
        val candidates = preferred.ifEmpty { editors }
        if (candidates.size != 1) return null

        val snapshots = candidates.mapIndexed { index, node ->
            TextInputNodeSnapshot(
                index,
                node.packageName,
                node.resourceId,
                node.className,
                node.text,
                node.description,
                node.bounds,
                node.editable,
                node.focused,
                node.visible,
                node.enabled
            )
        }
        val candidate = candidates.single()
        val resolution = TargetedTextInputResolver.resolve(
            TextInputTargetSpec(
                packageName = XHS_PACKAGE,
                resourceId = candidate.resourceId,
                boundsHint = candidate.bounds,
                requireFocused = false
            ),
            snapshots
        )
        return (resolution as? TextInputResolution.Unique)?.node?.index?.let(candidates::getOrNull)
    }

    private fun clickTreeNode(
        service: ClawAccessibilityService,
        target: CommentUiNode
    ): Boolean {
        val nodes = when {
            target.resourceId.isNotBlank() -> service.findNodesById(target.resourceId)
            target.text.isNotBlank() -> service.findNodesByText(target.text)
            target.description.isNotBlank() -> service.findNodesByDescription(target.description)
            else -> emptyList()
        }
        if (nodes.isEmpty()) return false
        return try {
            val ranked = nodes
                .filter { it.isVisibleToUser && it.isEnabled }
                .map { node -> node to distanceSquared(node, target.bounds) }
                .sortedBy { it.second }
            if (ranked.isEmpty()) return false
            if (ranked.size > 1 && ranked[0].second == ranked[1].second) return false
            service.clickNodeSemantically(ranked.first().first)
        } finally {
            ClawAccessibilityService.recycleNodes(nodes)
        }
    }

    private fun distanceSquared(node: AccessibilityNodeInfo, target: UiBounds): Long {
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        val dx = bounds.centerX().toLong() - (target.left + target.right).toLong() / 2L
        val dy = bounds.centerY().toLong() - (target.top + target.bottom).toLong() / 2L
        return dx * dx + dy * dy
    }

    private fun approvedVideoUri(videoId: String): Uri? {
        val value = videoId.trim()
        if (NOTE_ID.matches(value)) return Uri.parse("xhsdiscover://item/$value")
        val uri = runCatching { Uri.parse(value) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase(Locale.ROOT).orEmpty()
        if (scheme in XHS_SCHEMES) return uri
        if (scheme != "https") return null
        val host = uri.host?.lowercase(Locale.ROOT).orEmpty()
        return uri.takeIf { allowedHosts.any { allowed -> host == allowed || host.endsWith(".$allowed") } }
    }

    private fun UiBounds.toMap(): Map<String, Int> = mapOf(
        "left" to left,
        "top" to top,
        "right" to right,
        "bottom" to bottom
    )

    private fun normalize(value: String): String =
        value.trim().replace(Regex("\\s+"), " ")

    private fun needsAccessibility() = CommentDeviceStepResult.NeedsHuman(
        "accessibility_reenable_required",
        "Enable and rebind APKClaw accessibility service before resuming"
    )

    private fun treeUnavailable() = CommentDeviceStepResult.Retry(
        "screen_tree_unavailable",
        "Accessibility tree is temporarily unavailable"
    )

    private fun blocked() = CommentDeviceStepResult.NeedsHuman(
        "platform_verification_required",
        "Xiaohongshu requires login, verification, or risk-control handling"
    )

    private fun wrongApp() = CommentDeviceStepResult.Retry(
        "foreground_app_changed",
        "Xiaohongshu is no longer in the foreground"
    )

    private data class ObservedFrame(
        val rawTreeFingerprintSource: String,
        val observation: CommentPageObservation
    )

    private companion object {
        const val XHS_PACKAGE = "com.xingin.xhs"
        const val STATE_TIMEOUT_MS = 3_000L
        const val SEND_VERIFY_TIMEOUT_MS = 5_000L
        const val POLL_MS = 180L
        val NOTE_ID = Regex("^[0-9a-fA-F]{24}$")
        val XHS_SCHEMES = setOf("xhsdiscover", "xiaohongshu")
        val allowedHosts = setOf("xiaohongshu.com", "xhslink.com")
        val EDITOR_TERMS = listOf(
            "comment", "reply", "say something",
            "\u8bc4\u8bba", "\u56de\u590d", "\u8bf4\u70b9\u4ec0\u4e48"
        )
    }
}
