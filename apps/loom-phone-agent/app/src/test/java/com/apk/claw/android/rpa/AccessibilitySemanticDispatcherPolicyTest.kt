package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import com.apk.claw.android.workflow.SemanticSelector
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilitySemanticDispatcherPolicyTest {
    @Test
    fun generation_change_before_dispatch_rejects_target() {
        val access = FakeAccess(GenerationSnapshot(12L, "service-a"))
        val result = dispatcher(access).dispatch(uniqueResolution(generation = 11L), expectedGeneration = 11L)

        assertEquals("stale_tree_generation", result.errorCode)
        assertFalse(result.accepted)
        assertEquals(0, access.clicks)
        assertEquals(0, access.queryCount)
    }

    @Test
    fun service_generation_change_rejects_target_before_reacquisition() {
        val access = FakeAccess(GenerationSnapshot(11L, "service-b"))
        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertEquals("service_generation_changed", result.errorCode)
        assertFalse(result.accepted)
        assertEquals(0, access.clicks)
        assertEquals(0, access.queryCount)
    }

    @Test
    fun unique_live_candidate_is_revalidated_clicked_once_and_recycled() {
        val live = FakeNode()
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertTrue(result.accepted)
        assertEquals(ResolverKind.RESOURCE_ID, result.resolverUsed)
        assertEquals(1234L, result.dispatchedAt)
        assertEquals(1, access.clicks)
        assertEquals(1, live.recycles)
        assertEquals(listOf(ResolverKind.RESOURCE_ID), access.queries)
    }

    @Test
    fun description_candidate_is_reacquired_and_dispatched_once() {
        val live = FakeNode(resourceId = null, contentDescription = "Confirm")
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(
            uniqueResolution(
                matchedBy = ResolverKind.CONTENT_DESCRIPTION,
                resourceId = null,
                description = "Confirm"
            ),
            expectedGeneration = 11L
        )

        assertTrue(result.accepted)
        assertEquals(ResolverKind.CONTENT_DESCRIPTION, result.resolverUsed)
        assertEquals(listOf(ResolverKind.CONTENT_DESCRIPTION), access.queries)
        assertEquals(1, access.acceptedActions)
        assertEquals(1, live.recycles)
    }

    @Test
    fun description_resolution_flows_from_semantic_resolver_into_live_dispatch() {
        val resolution = SemanticResolver.resolve(
            CompactTreeSnapshot(
                uiGeneration = 11L,
                serviceGeneration = "service-a",
                packageName = "demo",
                windowId = 7,
                nodes = listOf(
                    CompactNode(
                        ref = "immutable-only-ref",
                        description = "Confirm",
                        className = "android.widget.Button",
                        packageName = "demo",
                        bounds = IntRect(0, 0, 100, 100)
                    )
                )
            ),
            SemanticSelector(contentDescription = "Confirm")
        )
        val live = FakeNode(resourceId = null, contentDescription = "Confirm")
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(resolution, expectedGeneration = 11L)

        assertTrue(result.accepted)
        assertEquals(ResolverKind.CONTENT_DESCRIPTION, result.resolverUsed)
        assertEquals(listOf(ResolverKind.CONTENT_DESCRIPTION), access.queries)
        assertEquals(1, access.acceptedActions)
    }

    @Test
    fun text_class_candidate_is_reacquired_and_dispatched_once() {
        val live = FakeNode(resourceId = null, text = "Confirm")
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(
            uniqueResolution(
                matchedBy = ResolverKind.TEXT_CLASS,
                resourceId = null,
                text = "Confirm"
            ),
            expectedGeneration = 11L
        )

        assertTrue(result.accepted)
        assertEquals(ResolverKind.TEXT_CLASS, result.resolverUsed)
        assertEquals(listOf(ResolverKind.TEXT_CLASS), access.queries)
        assertEquals(1, access.acceptedActions)
        assertEquals(1, live.recycles)
    }

    @Test
    fun ambiguous_live_candidates_dispatch_zero_clicks_and_recycle_all_nodes() {
        val first = FakeNode()
        val second = FakeNode()
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(first, second)
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("live_target_ambiguous", result.errorCode)
        assertEquals(0, access.clicks)
        assertEquals(1, first.recycles)
        assertEquals(1, second.recycles)
    }

    @Test
    fun duplicate_live_object_identity_is_one_candidate_and_recycled_once() {
        val duplicate = FakeNode()
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(duplicate, duplicate)
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertTrue(result.accepted)
        assertEquals(1, access.clicks)
        assertEquals(1, duplicate.recycles)
    }

    @Test
    fun production_adapter_wrappers_with_same_underlying_node_dispatch_and_recycle_once() {
        val underlying = UnderlyingNode()
        val first = AdapterWrappedNode(underlying)
        val second = AdapterWrappedNode(underlying)
        val service = FakeCurrentSemanticService(nodes = listOf(first, second))
        val holder = CurrentServiceHolder(service)
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access) { 1234L }
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertTrue(result.accepted)
        assertEquals(1, service.clicks)
        assertEquals(1, underlying.recycles)
    }

    @Test
    fun missing_or_invalid_live_candidate_dispatches_zero_clicks_and_recycles_returned_nodes() {
        val invalid = FakeNode(enabled = false)
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(invalid)
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("live_target_missing", result.errorCode)
        assertEquals(0, access.clicks)
        assertEquals(1, invalid.recycles)
    }

    @Test
    fun generation_is_checked_again_immediately_before_click() {
        val live = FakeNode()
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(live),
            afterFind = { it.generation = GenerationSnapshot(12L, "service-a") }
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("stale_tree_generation", result.errorCode)
        assertEquals(0, access.clicks)
        assertEquals(1, live.recycles)
        assertEquals(2, access.generationReads)
    }

    @Test
    fun package_class_visibility_and_enabled_state_are_exact_live_filters() {
        val wrongPackage = FakeNode(packageName = "other")
        val wrongClass = FakeNode(className = "android.widget.TextView")
        val hidden = FakeNode(visible = false)
        val disabled = FakeNode(enabled = false)
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(wrongPackage, wrongClass, hidden, disabled)
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertEquals("live_target_missing", result.errorCode)
        assertEquals(0, access.clicks)
        assertTrue(access.nodes.all { it.recycles == 1 })
    }

    @Test
    fun task_3_simple_class_name_matches_the_equivalent_live_qualified_class() {
        val live = FakeNode(className = "android.widget.Button")
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(
            uniqueResolution(className = "Button"),
            expectedGeneration = 11L
        )

        assertTrue(result.accepted)
        assertEquals(1, access.clicks)
        assertEquals(1, live.recycles)
    }

    @Test
    fun qualified_safe_class_cannot_dispatch_to_other_qualified_class_with_same_suffix() {
        val live = FakeNode(className = "com.other.PrimaryButton")
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"), nodes = listOf(live))

        val result = dispatcher(access).dispatch(
            uniqueResolution(
                className = "PrimaryButton",
                expectedClassName = "com.safe.PrimaryButton"
            ),
            expectedGeneration = 11L
        )

        assertFalse(result.accepted)
        assertEquals("live_target_missing", result.errorCode)
        assertEquals(0, access.clicks)
        assertEquals(0, access.acceptedActions)
        assertEquals(1, live.recycles)
    }

    @Test
    fun accessibility_service_unavailable_dispatches_zero_actions() {
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            generationFailureAtRead = 1
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("accessibility_service_unavailable", result.errorCode)
        assertEquals(0, access.queryCount)
        assertEquals(0, access.clicks)
        assertEquals(0, access.acceptedActions)
    }

    @Test
    fun production_current_service_clear_before_query_is_fail_closed() {
        lateinit var holder: CurrentServiceHolder
        val service = FakeCurrentSemanticService()
        holder = CurrentServiceHolder(service)
        service.afterGenerationRead = {
            if (service.generationReads == 1) holder.current = null
        }
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("accessibility_service_unavailable", result.errorCode)
        assertEquals(0, service.queries)
        assertEquals(0, service.clicks)
    }

    @Test
    fun production_current_service_replacement_before_click_is_fail_closed() {
        lateinit var holder: CurrentServiceHolder
        val replacement = FakeCurrentSemanticService(identity = Any())
        val original = FakeCurrentSemanticService(identity = Any())
        holder = CurrentServiceHolder(original)
        original.afterFind = { holder.current = replacement }
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("service_instance_changed", result.errorCode)
        assertEquals(1, original.queries)
        assertEquals(0, original.clicks)
        assertEquals(0, replacement.clicks)
        assertEquals(1, (original.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun exact_instance_dispatcher_rejects_global_replacement_before_reacquisition() {
        lateinit var holder: CurrentServiceHolder
        val replacement = FakeCurrentSemanticService(identity = Any())
        val original = FakeCurrentSemanticService(identity = Any())
        holder = CurrentServiceHolder(original)
        original.afterGenerationRead = {
            if (original.generationReads == 1) holder.current = replacement
        }
        val dispatcher = AccessibilitySemanticDispatcher.exactInstance(original) { holder.current }

        val result = dispatcher.dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals(DispatchOutcome.REJECTED, result.outcome)
        assertEquals(0, original.queries)
        assertEquals(0, original.clicks)
        assertEquals(0, replacement.queries)
        assertEquals(0, replacement.clicks)
    }

    @Test
    fun exact_instance_dispatcher_rejects_global_replacement_before_bound_click() {
        lateinit var holder: CurrentServiceHolder
        val replacement = FakeCurrentSemanticService(identity = Any())
        val original = FakeCurrentSemanticService(identity = Any())
        holder = CurrentServiceHolder(original)
        original.afterFind = { holder.current = replacement }
        val dispatcher = AccessibilitySemanticDispatcher.exactInstance(original) { holder.current }

        val result = dispatcher.dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals(DispatchOutcome.REJECTED, result.outcome)
        assertEquals(1, original.queries)
        assertEquals(0, original.clicks)
        assertEquals(0, replacement.queries)
        assertEquals(0, replacement.clicks)
        assertEquals(1, (original.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun production_replacement_after_preclick_snapshot_is_caught_before_action() {
        lateinit var holder: CurrentServiceHolder
        val replacement = FakeCurrentSemanticService(identity = Any())
        val original = FakeCurrentSemanticService(identity = Any())
        holder = CurrentServiceHolder(original)
        original.afterGenerationRead = {
            if (original.generationReads == 3) holder.current = replacement
        }
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("service_instance_changed", result.errorCode)
        assertEquals(1, original.queries)
        assertEquals(0, original.clicks)
        assertEquals(0, replacement.clicks)
        assertEquals(1, (original.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun production_generation_change_after_preclick_snapshot_is_caught_before_action() {
        val service = FakeCurrentSemanticService()
        val holder = CurrentServiceHolder(service)
        service.afterGenerationRead = {
            if (service.generationReads == 3) {
                service.generation = GenerationSnapshot(12L, "service-a")
            }
        }
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("stale_tree_generation", result.errorCode)
        assertEquals(1, service.queries)
        assertEquals(0, service.clicks)
        assertEquals(1, (service.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun production_service_generation_change_after_preclick_snapshot_is_caught_before_action() {
        val service = FakeCurrentSemanticService()
        val holder = CurrentServiceHolder(service)
        service.afterGenerationRead = {
            if (service.generationReads == 3) {
                service.generation = GenerationSnapshot(11L, "service-b")
            }
        }
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("service_generation_changed", result.errorCode)
        assertEquals(1, service.queries)
        assertEquals(0, service.clicks)
        assertEquals(1, (service.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun production_generation_read_failure_in_final_recheck_is_definite_unavailable() {
        val service = FakeCurrentSemanticService(generationFailureAtRead = 4)
        val holder = CurrentServiceHolder(service)
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("accessibility_service_unavailable", result.errorCode)
        assertEquals(DispatchOutcome.REJECTED, result.outcome)
        assertEquals(1, service.queries)
        assertEquals(0, service.clicks)
        assertEquals(1, (service.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun live_reacquisition_failure_dispatches_zero_actions() {
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            findFailure = IllegalStateException("injected find failure")
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("live_reacquisition_failed", result.errorCode)
        assertEquals(1, access.queryCount)
        assertEquals(0, access.clicks)
        assertEquals(0, access.acceptedActions)
    }

    @Test
    fun rejected_action_click_dispatches_zero_accepted_actions_and_recycles_node() {
        val live = FakeNode()
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(live),
            clickResult = false
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("action_click_rejected", result.errorCode)
        assertEquals(DispatchOutcome.REJECTED, result.outcome)
        assertEquals(1, access.clicks)
        assertEquals(0, access.acceptedActions)
        assertEquals(1, live.recycles)
    }

    @Test
    fun action_click_exception_is_non_retryable_uncertain_not_definite_rejection() {
        val live = FakeNode()
        val access = FakeAccess(
            GenerationSnapshot(11L, "service-a"),
            nodes = listOf(live),
            clickFailure = IllegalStateException("injected performAction failure")
        )

        val result = dispatcher(access).dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("action_outcome_unknown", result.errorCode)
        assertEquals(DispatchOutcome.UNCERTAIN, result.outcome)
        assertFalse(result.retryable)
        assertEquals(1, access.clicks)
        assertEquals(0, access.acceptedActions)
        assertEquals(1, live.recycles)
    }

    @Test
    fun production_service_click_exception_is_non_retryable_uncertain() {
        val service = FakeCurrentSemanticService(
            clickFailure = IllegalStateException("injected service click failure")
        )
        val holder = CurrentServiceHolder(service)
        val access = ServiceSemanticNodeAccess { holder.current }

        val result = AccessibilitySemanticDispatcher(access)
            .dispatch(uniqueResolution(), expectedGeneration = 11L)

        assertFalse(result.accepted)
        assertEquals("action_outcome_unknown", result.errorCode)
        assertEquals(DispatchOutcome.UNCERTAIN, result.outcome)
        assertFalse(result.retryable)
        assertEquals(1, service.clicks)
        assertEquals(1, (service.nodes.single() as FakeNode).recycles)
    }

    @Test
    fun production_constructor_uses_current_singleton_provider_not_captured_service() {
        val dispatcherSource = source("rpa/AccessibilitySemanticDispatcher.kt")
        val constructor = dispatcherSource
            .substringAfter("constructor(service: ClawAccessibilityService)")
            .substringBefore("fun dispatch")

        assertTrue(constructor.contains("ClawAccessibilityService.getInstance"))
        assertFalse(constructor.contains("ServiceSemanticNodeAccess(service)"))
    }

    @Test
    fun unresolved_immutable_result_never_queries_or_clicks() {
        val access = FakeAccess(GenerationSnapshot(11L, "service-a"))

        val missing = dispatcher(access).dispatch(
            SemanticResolution.Missing(listOf(ResolverKind.RESOURCE_ID)),
            expectedGeneration = 11L
        )
        val ambiguous = dispatcher(access).dispatch(
            SemanticResolution.Ambiguous(ResolverKind.RESOURCE_ID, 2),
            expectedGeneration = 11L
        )

        assertEquals("semantic_target_missing", missing.errorCode)
        assertEquals("semantic_target_ambiguous", ambiguous.errorCode)
        assertEquals(0, access.queryCount)
        assertEquals(0, access.clicks)
    }

    @Test
    fun semantic_service_click_path_has_no_coordinate_fallback() {
        val service = source("service/ClawAccessibilityService.java")
        val method = service.substringAfter("public boolean clickNodeSemantically(AccessibilityNodeInfo node)")
            .substringBefore("public boolean setNodeText")
        val policy = source("rpa/AccessibilitySemanticDispatcher.kt")
            .substringAfter("object AccessibilitySemanticClickPolicy")
            .substringBefore("class AccessibilitySemanticDispatcher")

        assertTrue(method.contains("AccessibilitySemanticClickPolicy.click"))
        assertTrue(policy.contains("AccessibilityNodeInfo.ACTION_CLICK"))
        assertFalse(method.contains("performTap"))
        assertFalse(policy.contains("performTap"))
    }

    private fun dispatcher(access: FakeAccess) = AccessibilitySemanticDispatcher(access) { 1234L }

    private fun uniqueResolution(
        generation: Long = 11L,
        className: String = "android.widget.Button",
        expectedClassName: String? = null,
        matchedBy: ResolverKind = ResolverKind.RESOURCE_ID,
        resourceId: String? = "demo:id/target",
        description: String? = null,
        text: String? = null,
    ) = SemanticResolution.Unique(
        node = CompactNode(
            ref = "ephemeral-ref-is-not-used",
            resourceId = resourceId,
            description = description,
            text = text,
            className = className,
            packageName = "demo",
            bounds = IntRect(0, 0, 100, 100)
        ),
        matchedBy = matchedBy,
        generation = generation,
        serviceGeneration = "service-a",
        expectedClassName = expectedClassName
    )

    private class FakeAccess(
        var generation: GenerationSnapshot,
        val nodes: List<FakeNode> = emptyList(),
        private val afterFind: ((FakeAccess) -> Unit)? = null,
        private val generationFailureAtRead: Int? = null,
        private val findFailure: Throwable? = null,
        private val clickResult: Boolean = true,
        private val clickFailure: Throwable? = null,
    ) : LiveSemanticNodeAccess {
        var clicks = 0
        var acceptedActions = 0
        var queryCount = 0
        var generationReads = 0
        val queries = mutableListOf<ResolverKind>()

        override fun currentGeneration(): GenerationSnapshot {
            generationReads += 1
            if (generationReads == generationFailureAtRead) {
                throw IllegalStateException("injected generation failure")
            }
            return generation
        }

        override fun findNodesById(resourceId: String): List<LiveSemanticNode> = found(ResolverKind.RESOURCE_ID)

        override fun findNodesByDescription(description: String): List<LiveSemanticNode> =
            found(ResolverKind.CONTENT_DESCRIPTION)

        override fun findNodesByText(text: String): List<LiveSemanticNode> = found(ResolverKind.TEXT_CLASS)

        override fun clickNode(node: LiveSemanticNode): Boolean {
            clicks += 1
            clickFailure?.let { throw it }
            if (clickResult) acceptedActions += 1
            return clickResult
        }

        private fun found(kind: ResolverKind): List<LiveSemanticNode> {
            queryCount += 1
            queries += kind
            findFailure?.let { throw it }
            afterFind?.invoke(this)
            return nodes
        }
    }

    private class FakeNode(
        override val resourceId: String? = "demo:id/target",
        override val contentDescription: String? = null,
        override val text: String? = null,
        override val className: String = "android.widget.Button",
        override val packageName: String = "demo",
        override val visible: Boolean = true,
        override val enabled: Boolean = true,
    ) : LiveSemanticNode {
        var recycles = 0

        override fun recycle() {
            recycles += 1
        }
    }

    private class CurrentServiceHolder(var current: CurrentSemanticService?)

    private class FakeCurrentSemanticService(
        override val identity: Any = Any(),
        val nodes: List<LiveSemanticNode> = listOf(FakeNode()),
        private val generationFailureAtRead: Int? = null,
        private val clickFailure: Throwable? = null,
    ) : CurrentSemanticService {
        var generation = GenerationSnapshot(11L, "service-a")
        var generationReads = 0
        var queries = 0
        var clicks = 0
        var afterGenerationRead: (() -> Unit)? = null
        var afterFind: (() -> Unit)? = null

        override fun generationSnapshot(): GenerationSnapshot {
            generationReads += 1
            if (generationReads == generationFailureAtRead) {
                throw IllegalStateException("injected generation read failure")
            }
            val snapshot = generation
            afterGenerationRead?.invoke()
            return snapshot
        }

        override fun findNodesById(resourceId: String): List<LiveSemanticNode> = found()

        override fun findNodesByDescription(description: String): List<LiveSemanticNode> = found()

        override fun findNodesByText(text: String): List<LiveSemanticNode> = found()

        override fun clickNode(node: LiveSemanticNode): Boolean {
            clicks += 1
            clickFailure?.let { throw it }
            return true
        }

        private fun found(): List<LiveSemanticNode> {
            queries += 1
            afterFind?.invoke()
            return nodes
        }
    }

    private class UnderlyingNode {
        var recycles = 0
    }

    private class AdapterWrappedNode(
        private val underlying: UnderlyingNode
    ) : LiveSemanticNode {
        override val ownershipIdentity: Any get() = underlying
        override val resourceId: String = "demo:id/target"
        override val contentDescription: String? = null
        override val text: String? = null
        override val className: String = "android.widget.Button"
        override val packageName: String = "demo"
        override val visible: Boolean = true
        override val enabled: Boolean = true

        override fun recycle() {
            underlying.recycles += 1
        }
    }

    private fun source(relativePath: String): String {
        return sequenceOf(
            File("app/src/main/java/com/apk/claw/android/$relativePath"),
            File("src/main/java/com/apk/claw/android/$relativePath")
        ).firstOrNull { it.isFile }?.readText() ?: error("Source not found: $relativePath")
    }
}
