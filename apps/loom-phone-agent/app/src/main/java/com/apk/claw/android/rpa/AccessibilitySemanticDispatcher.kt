package com.apk.claw.android.rpa

import android.view.accessibility.AccessibilityNodeInfo
import com.apk.claw.android.service.ClawAccessibilityService
import com.apk.claw.android.workflow.ResolverKind
import java.util.Collections
import java.util.IdentityHashMap

enum class DispatchOutcome { ACCEPTED, REJECTED, UNCERTAIN }

data class DispatchResult(
    val accepted: Boolean,
    val errorCode: String = "",
    val resolverUsed: ResolverKind? = null,
    val dispatchedAt: Long = 0L,
    val outcome: DispatchOutcome = if (accepted) DispatchOutcome.ACCEPTED else DispatchOutcome.REJECTED,
    val retryable: Boolean = false
)

interface LiveSemanticNode {
    val ownershipIdentity: Any get() = this
    val resourceId: String?
    val contentDescription: String?
    val text: String?
    val className: String
    val packageName: String
    val visible: Boolean
    val enabled: Boolean

    fun recycle()
}

data class LiveServiceState(
    val identity: Any,
    val generation: GenerationSnapshot
)

interface LiveSemanticNodeAccess {
    fun currentGeneration(): GenerationSnapshot
    fun currentServiceState(): LiveServiceState? = LiveServiceState(this, currentGeneration())
    fun findNodesById(resourceId: String): List<LiveSemanticNode>
    fun findNodesByDescription(description: String): List<LiveSemanticNode>
    fun findNodesByText(text: String): List<LiveSemanticNode>
    fun clickNode(node: LiveSemanticNode): Boolean

    fun findNodesById(resourceId: String, expectedState: LiveServiceState): List<LiveSemanticNode> =
        findNodesById(resourceId)

    fun findNodesByDescription(
        description: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = findNodesByDescription(description)

    fun findNodesByText(text: String, expectedState: LiveServiceState): List<LiveSemanticNode> =
        findNodesByText(text)

    fun clickNode(node: LiveSemanticNode, expectedState: LiveServiceState): Boolean = clickNode(node)
}

internal interface CurrentSemanticService {
    val identity: Any
    fun generationSnapshot(): GenerationSnapshot
    fun findNodesById(resourceId: String): List<LiveSemanticNode>
    fun findNodesByDescription(description: String): List<LiveSemanticNode>
    fun findNodesByText(text: String): List<LiveSemanticNode>
    fun clickNode(node: LiveSemanticNode): Boolean
}

object AccessibilitySemanticClickPolicy {
    @JvmStatic
    fun click(node: AccessibilityNodeInfo?, beforeAction: Runnable): Boolean = click(
        node = node,
        beforeAction = beforeAction,
        parentOf = { it.parent },
        performAction = { candidate, action -> candidate.performAction(action) }
    )

    fun click(
        node: AccessibilityNodeInfo?,
        beforeAction: Runnable,
        parentOf: (AccessibilityNodeInfo) -> AccessibilityNodeInfo?,
        performAction: (AccessibilityNodeInfo, Int) -> Boolean
    ): Boolean {
        if (node == null) return false
        if (node.isClickable) {
            beforeAction.run()
            return performAction(node, AccessibilityNodeInfo.ACTION_CLICK)
        }
        var parent = parentOf(node)
        while (parent != null) {
            var next: AccessibilityNodeInfo? = null
            try {
                if (parent.isClickable) {
                    beforeAction.run()
                    return performAction(parent, AccessibilityNodeInfo.ACTION_CLICK)
                }
                next = parentOf(parent)
            } finally {
                parent.recycle()
            }
            parent = next
        }
        return false
    }
}

class AccessibilitySemanticDispatcher(
    private val access: LiveSemanticNodeAccess,
    private val clock: () -> Long = System::currentTimeMillis
) {
    constructor(service: ClawAccessibilityService) : this(
        ServiceSemanticNodeAccess {
            ClawAccessibilityService.getInstance()?.let(::AndroidCurrentSemanticService)
        }
    )

    fun dispatch(resolution: SemanticResolution, expectedGeneration: Long): DispatchResult {
        val unique = when (resolution) {
            is SemanticResolution.Unique -> resolution
            is SemanticResolution.Missing -> return rejected(ERROR_SEMANTIC_TARGET_MISSING)
            is SemanticResolution.Ambiguous -> return rejected(ERROR_SEMANTIC_TARGET_AMBIGUOUS)
        }
        if (unique.generation != expectedGeneration) return rejected(ERROR_STALE_TREE_GENERATION)

        val beforeQuery = currentServiceStateOrNull() ?: return rejected(ERROR_SERVICE_UNAVAILABLE)
        generationError(unique, expectedGeneration, beforeQuery.generation)?.let { return rejected(it) }

        val nodes = try {
            reacquire(unique, beforeQuery)
        } catch (error: ServiceStateException) {
            return rejected(error.errorCode)
        } catch (_: Throwable) {
            return rejected(ERROR_LIVE_REACQUISITION_FAILED)
        }
        val ownedNodes = distinctByOwnership(nodes)
        try {
            val candidates = ownedNodes.filter { live -> live.matches(unique) }
            if (candidates.isEmpty()) return rejected(ERROR_LIVE_TARGET_MISSING)
            if (candidates.size > 1) return rejected(ERROR_LIVE_TARGET_AMBIGUOUS)

            val beforeClick = currentServiceStateOrNull() ?: return rejected(ERROR_SERVICE_UNAVAILABLE)
            if (beforeClick.identity !== beforeQuery.identity) {
                return rejected(ERROR_SERVICE_INSTANCE_CHANGED)
            }
            generationError(unique, expectedGeneration, beforeClick.generation)?.let { return rejected(it) }

            val accepted = try {
                access.clickNode(candidates.single(), beforeClick)
            } catch (error: ServiceStateException) {
                return rejected(error.errorCode)
            } catch (_: Throwable) {
                return uncertain(unique.matchedBy)
            }
            return if (accepted) {
                DispatchResult(
                    accepted = true,
                    resolverUsed = unique.matchedBy,
                    dispatchedAt = clock(),
                    outcome = DispatchOutcome.ACCEPTED
                )
            } else {
                rejected(ERROR_ACTION_CLICK_REJECTED, unique.matchedBy)
            }
        } finally {
            ownedNodes.forEach { node -> runCatching { node.recycle() } }
        }
    }

    private fun reacquire(
        unique: SemanticResolution.Unique,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> {
        return when (unique.matchedBy) {
            ResolverKind.RESOURCE_ID -> unique.node.resourceId
                ?.takeIf { it.isNotBlank() }
                ?.let { access.findNodesById(it, expectedState) }
            ResolverKind.CONTENT_DESCRIPTION -> unique.node.description
                ?.takeIf { it.isNotBlank() }
                ?.let { access.findNodesByDescription(it, expectedState) }
            ResolverKind.TEXT_CLASS -> unique.node.text
                ?.takeIf { it.isNotBlank() }
                ?.let { access.findNodesByText(it, expectedState) }
            else -> null
        } ?: emptyList()
    }

    private fun distinctByOwnership(nodes: List<LiveSemanticNode>): List<LiveSemanticNode> {
        val identities = Collections.newSetFromMap(IdentityHashMap<Any, Boolean>())
        return nodes.filter { identities.add(it.ownershipIdentity) }
    }

    private fun LiveSemanticNode.matches(unique: SemanticResolution.Unique): Boolean {
        if (!visible || !enabled) return false
        if (unique.node.packageName.isNotBlank() && packageName != unique.node.packageName) return false
        val expectedClassName = unique.expectedClassName ?: unique.node.className
        if (expectedClassName.isNotBlank() &&
            !semanticClassNamesMatch(expectedClassName, className)
        ) return false
        return when (unique.matchedBy) {
            ResolverKind.RESOURCE_ID -> resourceId == unique.node.resourceId
            ResolverKind.CONTENT_DESCRIPTION -> contentDescription == unique.node.description
            ResolverKind.TEXT_CLASS -> text == unique.node.text
            else -> false
        }
    }

    private fun currentServiceStateOrNull(): LiveServiceState? =
        runCatching { access.currentServiceState() }.getOrNull()

    private fun generationError(
        unique: SemanticResolution.Unique,
        expectedGeneration: Long,
        current: GenerationSnapshot
    ): String? {
        if (current.serviceGeneration != unique.serviceGeneration) return ERROR_SERVICE_GENERATION_CHANGED
        if (current.uiGeneration != expectedGeneration) return ERROR_STALE_TREE_GENERATION
        return null
    }

    private fun rejected(errorCode: String, resolver: ResolverKind? = null) = DispatchResult(
        accepted = false,
        errorCode = errorCode,
        resolverUsed = resolver,
        outcome = DispatchOutcome.REJECTED
    )

    private fun uncertain(resolver: ResolverKind) = DispatchResult(
        accepted = false,
        errorCode = ERROR_ACTION_OUTCOME_UNKNOWN,
        resolverUsed = resolver,
        dispatchedAt = clock(),
        outcome = DispatchOutcome.UNCERTAIN,
        retryable = false
    )

    companion object {
        internal fun exactInstance(
            service: CurrentSemanticService,
            currentService: () -> CurrentSemanticService?
        ): AccessibilitySemanticDispatcher = AccessibilitySemanticDispatcher(
            ExactInstanceSemanticNodeAccess(service, currentService)
        )

        internal fun exactInstance(service: ClawAccessibilityService): AccessibilitySemanticDispatcher {
            val boundService = AndroidCurrentSemanticService(service)
            return exactInstance(boundService) {
                ClawAccessibilityService.getInstance()?.let(::AndroidCurrentSemanticService)
            }
        }

        const val ERROR_STALE_TREE_GENERATION = "stale_tree_generation"
        const val ERROR_SERVICE_GENERATION_CHANGED = "service_generation_changed"
        const val ERROR_SERVICE_INSTANCE_CHANGED = "service_instance_changed"
        const val ERROR_SEMANTIC_TARGET_MISSING = "semantic_target_missing"
        const val ERROR_SEMANTIC_TARGET_AMBIGUOUS = "semantic_target_ambiguous"
        const val ERROR_LIVE_TARGET_MISSING = "live_target_missing"
        const val ERROR_LIVE_TARGET_AMBIGUOUS = "live_target_ambiguous"
        const val ERROR_LIVE_REACQUISITION_FAILED = "live_reacquisition_failed"
        const val ERROR_SERVICE_UNAVAILABLE = "accessibility_service_unavailable"
        const val ERROR_ACTION_CLICK_REJECTED = "action_click_rejected"
        const val ERROR_ACTION_OUTCOME_UNKNOWN = "action_outcome_unknown"
    }
}

private class ServiceStateException(val errorCode: String) : IllegalStateException(errorCode)

internal class ServiceSemanticNodeAccess(
    private val currentService: () -> CurrentSemanticService?
) : LiveSemanticNodeAccess {
    override fun currentGeneration(): GenerationSnapshot = currentServiceState()?.generation
        ?: throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)

    override fun currentServiceState(): LiveServiceState? {
        val service = currentService() ?: return null
        return LiveServiceState(service.identity, service.generationSnapshot())
    }

    override fun findNodesById(resourceId: String): List<LiveSemanticNode> =
        withCurrentState { service, state -> findNodesById(resourceId, state) }

    override fun findNodesByDescription(description: String): List<LiveSemanticNode> =
        withCurrentState { service, state -> findNodesByDescription(description, state) }

    override fun findNodesByText(text: String): List<LiveSemanticNode> =
        withCurrentState { service, state -> findNodesByText(text, state) }

    override fun clickNode(node: LiveSemanticNode): Boolean {
        return withCurrentState { service, state -> clickNode(node, state) }
    }

    override fun findNodesById(
        resourceId: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireCurrent(expectedState).findNodesById(resourceId)

    override fun findNodesByDescription(
        description: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireCurrent(expectedState).findNodesByDescription(description)

    override fun findNodesByText(
        text: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireCurrent(expectedState).findNodesByText(text)

    override fun clickNode(node: LiveSemanticNode, expectedState: LiveServiceState): Boolean =
        requireCurrent(expectedState).clickNode(node)

    private fun requireCurrent(expectedState: LiveServiceState): CurrentSemanticService {
        val service = runCatching { currentService() }.getOrNull()
            ?: throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)
        if (service.identity !== expectedState.identity) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_INSTANCE_CHANGED)
        }
        val generation = runCatching { service.generationSnapshot() }.getOrNull()
            ?: throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)
        if (generation.serviceGeneration != expectedState.generation.serviceGeneration) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_GENERATION_CHANGED)
        }
        if (generation.uiGeneration != expectedState.generation.uiGeneration) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_STALE_TREE_GENERATION)
        }
        return service
    }

    private inline fun <T> withCurrentState(
        action: (CurrentSemanticService, LiveServiceState) -> T
    ): T {
        val service = currentService()
            ?: throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)
        val state = LiveServiceState(service.identity, service.generationSnapshot())
        return action(service, state)
    }
}

internal class ExactInstanceSemanticNodeAccess(
    private val boundService: CurrentSemanticService,
    private val currentService: () -> CurrentSemanticService?
) : LiveSemanticNodeAccess {
    override fun currentGeneration(): GenerationSnapshot = currentBoundState().generation

    override fun currentServiceState(): LiveServiceState = currentBoundState()

    override fun findNodesById(resourceId: String): List<LiveSemanticNode> {
        val state = currentBoundState()
        return findNodesById(resourceId, state)
    }

    override fun findNodesByDescription(description: String): List<LiveSemanticNode> {
        val state = currentBoundState()
        return findNodesByDescription(description, state)
    }

    override fun findNodesByText(text: String): List<LiveSemanticNode> {
        val state = currentBoundState()
        return findNodesByText(text, state)
    }

    override fun clickNode(node: LiveSemanticNode): Boolean {
        val state = currentBoundState()
        return clickNode(node, state)
    }

    override fun findNodesById(
        resourceId: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireBound(expectedState).findNodesById(resourceId)

    override fun findNodesByDescription(
        description: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireBound(expectedState).findNodesByDescription(description)

    override fun findNodesByText(
        text: String,
        expectedState: LiveServiceState
    ): List<LiveSemanticNode> = requireBound(expectedState).findNodesByText(text)

    override fun clickNode(node: LiveSemanticNode, expectedState: LiveServiceState): Boolean =
        requireBound(expectedState).clickNode(node)

    private fun currentBoundState(): LiveServiceState {
        requireCurrentIdentity()
        return LiveServiceState(boundService.identity, boundGeneration())
    }

    private fun requireBound(expectedState: LiveServiceState): CurrentSemanticService {
        requireCurrentIdentity()
        if (expectedState.identity !== boundService.identity) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_INSTANCE_CHANGED)
        }
        val generation = boundGeneration()
        if (generation.serviceGeneration != expectedState.generation.serviceGeneration) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_GENERATION_CHANGED)
        }
        if (generation.uiGeneration != expectedState.generation.uiGeneration) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_STALE_TREE_GENERATION)
        }
        return boundService
    }

    private fun requireCurrentIdentity() {
        val current = try {
            currentService()
        } catch (_: Throwable) {
            null
        } ?: throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)
        if (current.identity !== boundService.identity) {
            throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_INSTANCE_CHANGED)
        }
    }

    private fun boundGeneration(): GenerationSnapshot = try {
        boundService.generationSnapshot()
    } catch (_: Throwable) {
        throw ServiceStateException(AccessibilitySemanticDispatcher.ERROR_SERVICE_UNAVAILABLE)
    }
}

private class AndroidCurrentSemanticService(
    private val service: ClawAccessibilityService
) : CurrentSemanticService {
    override val identity: Any get() = service
    override fun generationSnapshot(): GenerationSnapshot = service.generationSnapshot

    override fun findNodesById(resourceId: String): List<LiveSemanticNode> =
        service.findNodesById(resourceId).map(::AndroidLiveSemanticNode)

    override fun findNodesByDescription(description: String): List<LiveSemanticNode> =
        service.findNodesByDescription(description).map(::AndroidLiveSemanticNode)

    override fun findNodesByText(text: String): List<LiveSemanticNode> =
        service.findNodesByText(text).map(::AndroidLiveSemanticNode)

    override fun clickNode(node: LiveSemanticNode): Boolean {
        val androidNode = node as? AndroidLiveSemanticNode ?: return false
        return service.clickNodeSemantically(androidNode.node)
    }
}

private class AndroidLiveSemanticNode(
    val node: AccessibilityNodeInfo
) : LiveSemanticNode {
    override val ownershipIdentity: Any get() = node
    override val resourceId: String? get() = node.viewIdResourceName
    override val contentDescription: String? get() = node.contentDescription?.toString()
    override val text: String? get() = node.text?.toString()
    override val className: String get() = node.className?.toString().orEmpty()
    override val packageName: String get() = node.packageName?.toString().orEmpty()
    override val visible: Boolean get() = node.isVisibleToUser
    override val enabled: Boolean get() = node.isEnabled

    override fun recycle() {
        node.recycle()
    }
}
