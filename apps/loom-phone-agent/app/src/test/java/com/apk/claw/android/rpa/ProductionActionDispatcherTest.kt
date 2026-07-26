package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.ResolverKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProductionActionDispatcherTest {
    @Test
    fun semantic_tap_uses_live_reacquisition_adapter_once() {
        val service = FakePlatformService()
        var providerCalls = 0
        val dispatcher = ProductionActionDispatcher(
            ProductionPlatformServiceProvider { providerCalls += 1; service }
        )

        val receipt = dispatcher.dispatch(prepared(semanticPayload(service.identity), ResolverKind.RESOURCE_ID))

        assertEquals(DispatchOutcome.ACCEPTED, receipt.outcome)
        assertEquals(88L, receipt.dispatchedAt)
        assertEquals(1, providerCalls)
        assertEquals(1, service.semanticCalls)
        assertEquals(0, service.coordinateCalls)
    }

    @Test
    fun semantic_rebound_after_outer_boundary_never_clicks_authorized_or_replacement_service() {
        lateinit var holder: CurrentServiceHolder
        val replacement = BoundSemanticService(identity = Any())
        val original = BoundSemanticService(identity = Any())
        holder = CurrentServiceHolder(original)
        original.afterFind = { holder.current = replacement }
        val platform = FakePlatformService(
            identity = original.identity,
            semanticDispatch = { resolution, expectedGeneration ->
                AccessibilitySemanticDispatcher.exactInstance(original) { holder.current }
                    .dispatch(resolution, expectedGeneration)
            }
        )
        val dispatcher = ProductionActionDispatcher(ProductionPlatformServiceProvider { platform })

        val receipt = dispatcher.dispatch(
            prepared(semanticPayload(original.identity), ResolverKind.RESOURCE_ID)
        )

        assertEquals(DispatchOutcome.REJECTED, receipt.outcome)
        assertEquals(1, original.queries)
        assertEquals(0, original.clicks)
        assertEquals(0, replacement.queries)
        assertEquals(0, replacement.clicks)
    }

    @Test
    fun service_replacement_or_generation_change_is_rejected_before_platform_call() {
        val originalIdentity = Any()
        val payload = visualPayload(originalIdentity)
        val replacement = FakePlatformService(identity = Any())
        val changedGeneration = FakePlatformService(
            identity = originalIdentity,
            generation = GenerationSnapshot(8L, "service-1")
        )

        val replaced = ProductionActionDispatcher(ProductionPlatformServiceProvider { replacement })
            .dispatch(prepared(payload))
        val stale = ProductionActionDispatcher(ProductionPlatformServiceProvider { changedGeneration })
            .dispatch(prepared(payload))

        assertEquals(DispatchOutcome.REJECTED, replaced.outcome)
        assertEquals(ProductionActionDispatcher.ERROR_SERVICE_INSTANCE_CHANGED, replaced.errorCode)
        assertEquals(DispatchOutcome.REJECTED, stale.outcome)
        assertEquals(ProductionActionDispatcher.ERROR_GENERATION_CHANGED, stale.errorCode)
        assertEquals(0, replacement.platformCalls)
        assertEquals(0, changedGeneration.platformCalls)
    }

    @Test
    fun visual_tap_and_long_press_use_only_bounded_match_and_declared_offsets() {
        val service = FakePlatformService()
        val dispatcher = ProductionActionDispatcher(ProductionPlatformServiceProvider { service }, clock = { 100L })

        val tap = dispatcher.dispatch(prepared(visualPayload(service.identity)))
        val longPress = dispatcher.dispatch(
            prepared(
                visualPayload(
                    service.identity,
                    action = VisualPlatformAction.LONG_PRESS,
                    durationMs = 900L
                ),
                attempt = 2
            )
        )

        assertEquals(DispatchOutcome.ACCEPTED, tap.outcome)
        assertEquals(DispatchOutcome.ACCEPTED, longPress.outcome)
        assertEquals(listOf(35 to 57), service.taps)
        assertEquals(listOf(Triple(35, 57, 900L)), service.longPresses)
    }

    @Test
    fun direct_allowlist_uses_only_sanitized_bounded_parameters() {
        val service = FakePlatformService(currentPackage = "demo.app")
        val sleeps = mutableListOf<Long>()
        val dispatcher = ProductionActionDispatcher(
            ProductionPlatformServiceProvider { service },
            sleeper = { value -> sleeps += value }
        )

        val receipts = listOf(
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.OPEN_APP, "demo.app"), ResolverKind.DIRECT, 1)),
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.ASSERT_PACKAGE, "demo.app"), ResolverKind.DIRECT, 2)),
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.WAIT, waitMs = 25L), ResolverKind.DIRECT, 3)),
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.BACK), ResolverKind.DIRECT, 4)),
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.HOME), ResolverKind.DIRECT, 5)),
            dispatcher.dispatch(prepared(directPayload(service.identity, DirectAction.FINISH), ResolverKind.DIRECT, 6))
        )

        assertTrue(receipts.all(DispatchReceipt::accepted))
        assertEquals(listOf("demo.app"), service.openedPackages)
        assertEquals(listOf(25L), sleeps)
        assertEquals(1, service.backCalls)
        assertEquals(1, service.homeCalls)
    }

    @Test
    fun unsupported_input_coordinate_swipe_and_drag_payloads_dispatch_zero_platform_calls() {
        val service = FakePlatformService()
        val sleeps = mutableListOf<Long>()
        val dispatcher = ProductionActionDispatcher(
            ProductionPlatformServiceProvider { service },
            sleeper = { value -> sleeps += value }
        )
        val unsupported = listOf("input_text", "normalized_coordinate", "swipe", "drag").mapIndexed { index, name ->
            dispatcher.dispatch(prepared(UnsupportedPayload(name), attempt = index + 1))
        } + dispatcher.dispatch(
            prepared(
                directPayload(service.identity, DirectAction.WAIT_STABLE, waitMs = 25L),
                ResolverKind.DIRECT,
                5
            )
        )

        unsupported.forEach { receipt ->
            assertEquals(DispatchOutcome.REJECTED, receipt.outcome)
            assertEquals(ProductionActionDispatcher.ERROR_ACTION_ADAPTER_UNAVAILABLE, receipt.errorCode)
        }
        assertEquals(0, service.platformCalls)
        assertTrue(sleeps.isEmpty())
    }

    @Test
    fun platform_false_exception_and_uncertain_semantic_callback_are_uncertain() {
        val identity = Any()
        val falseService = FakePlatformService(identity = identity, gestureAccepted = false)
        val throwingService = FakePlatformService(identity = identity, throwPlatform = true)
        val semanticService = FakePlatformService(
            identity = identity,
            semanticResult = DispatchResult(
                accepted = false,
                outcome = DispatchOutcome.UNCERTAIN,
                errorCode = AccessibilitySemanticDispatcher.ERROR_ACTION_OUTCOME_UNKNOWN,
                dispatchedAt = 77L
            )
        )

        val callbackUnknown = ProductionActionDispatcher(ProductionPlatformServiceProvider { falseService })
            .dispatch(prepared(visualPayload(identity)))
        val exception = ProductionActionDispatcher(ProductionPlatformServiceProvider { throwingService })
            .dispatch(prepared(visualPayload(identity)))
        val semanticUnknown = ProductionActionDispatcher(ProductionPlatformServiceProvider { semanticService })
            .dispatch(prepared(semanticPayload(identity), ResolverKind.RESOURCE_ID))

        assertEquals(DispatchOutcome.UNCERTAIN, callbackUnknown.outcome)
        assertEquals(DispatchOutcome.UNCERTAIN, exception.outcome)
        assertEquals(DispatchOutcome.UNCERTAIN, semanticUnknown.outcome)
        assertFalse(callbackUnknown.accepted)
    }

    private fun prepared(
        payload: DispatchPayload,
        resolver: ResolverKind = ResolverKind.VISUAL_ANCHOR,
        attempt: Int = 1
    ) = PreparedAction(
        runId = "run-1",
        stepId = "step-1",
        attempt = attempt,
        uiGeneration = 7L,
        serviceGeneration = "service-1",
        resolverUsed = resolver,
        payload = payload
    )

    private fun semanticPayload(identity: Any): SemanticDispatchPayload {
        val node = CompactNode(
            ref = "node-1",
            resourceId = "demo:id/target",
            className = "android.widget.Button",
            packageName = "demo.app",
            bounds = IntRect(10, 20, 110, 70)
        )
        return SemanticDispatchPayload(
            SemanticResolution.Unique(node, ResolverKind.RESOURCE_ID, 7L, "service-1"),
            node.bounds,
            evidence(identity)
        )
    }

    private fun visualPayload(
        identity: Any,
        action: VisualPlatformAction = VisualPlatformAction.TAP,
        durationMs: Long = 100L
    ) = VisualDispatchPayload(
        bounds = IntRect(10, 20, 110, 70),
        tapOffsetX = 0.25f,
        tapOffsetY = 0.75f,
        action = action,
        durationMs = durationMs,
        evidence = evidence(identity)
    )

    private fun directPayload(
        identity: Any,
        action: DirectAction,
        packageName: String? = null,
        waitMs: Long = 0L
    ) = DirectPayload(action, packageName, waitMs, evidence(identity))

    private fun evidence(identity: Any) = UiEvidence(
        uiGeneration = 7L,
        serviceGeneration = "service-1",
        packageName = "demo.app",
        windowId = 3,
        capturedAt = 50L,
        transform = DisplayTransform(0, 200, 300, 200, 300, 0, 420, 0, 0, 0, 0),
        compactTree = null,
        runtimeServiceIdentity = identity
    )

    private data class UnsupportedPayload(val name: String) : DispatchPayload

    private class FakePlatformService(
        override val identity: Any = Any(),
        var generation: GenerationSnapshot = GenerationSnapshot(7L, "service-1"),
        var currentPackage: String = "demo.app",
        private val gestureAccepted: Boolean = true,
        private val throwPlatform: Boolean = false,
        private val semanticDispatch: ((SemanticResolution.Unique, Long) -> DispatchResult)? = null,
        private val semanticResult: DispatchResult = DispatchResult(
            true,
            resolverUsed = ResolverKind.RESOURCE_ID,
            dispatchedAt = 88L
        )
    ) : ProductionPlatformService {
        var semanticCalls = 0
        var coordinateCalls = 0
        var platformCalls = 0
        var backCalls = 0
        var homeCalls = 0
        val taps = mutableListOf<Pair<Int, Int>>()
        val longPresses = mutableListOf<Triple<Int, Int, Long>>()
        val openedPackages = mutableListOf<String>()

        override fun generationSnapshot(): GenerationSnapshot = generation
        override fun capture(requirement: FreshnessRequirement): UiEvidence = error("not used")

        override fun dispatchSemantic(
            resolution: SemanticResolution.Unique,
            expectedGeneration: Long
        ): DispatchResult {
            semanticCalls += 1
            return semanticDispatch?.invoke(resolution, expectedGeneration) ?: semanticResult
        }

        override fun performTap(x: Int, y: Int): Boolean {
            beforePlatform()
            coordinateCalls += 1
            taps += x to y
            return gestureAccepted
        }

        override fun performLongPress(x: Int, y: Int, durationMs: Long): Boolean {
            beforePlatform()
            coordinateCalls += 1
            longPresses += Triple(x, y, durationMs)
            return gestureAccepted
        }

        override fun openApp(packageName: String): Boolean {
            beforePlatform()
            openedPackages += packageName
            return true
        }

        override fun pressBack(): Boolean {
            beforePlatform()
            backCalls += 1
            return true
        }

        override fun pressHome(): Boolean {
            beforePlatform()
            homeCalls += 1
            return true
        }

        override fun currentPackageName(): String = currentPackage

        private fun beforePlatform() {
            platformCalls += 1
            if (throwPlatform) throw IllegalStateException("platform")
        }
    }

    private class CurrentServiceHolder(var current: CurrentSemanticService?)

    private class BoundSemanticService(
        override val identity: Any,
        private val node: LiveSemanticNode = BoundSemanticNode()
    ) : CurrentSemanticService {
        var queries = 0
        var clicks = 0
        var afterFind: (() -> Unit)? = null

        override fun generationSnapshot(): GenerationSnapshot = GenerationSnapshot(7L, "service-1")

        override fun findNodesById(resourceId: String): List<LiveSemanticNode> = found()

        override fun findNodesByDescription(description: String): List<LiveSemanticNode> = found()

        override fun findNodesByText(text: String): List<LiveSemanticNode> = found()

        override fun clickNode(node: LiveSemanticNode): Boolean {
            clicks += 1
            return true
        }

        private fun found(): List<LiveSemanticNode> {
            queries += 1
            afterFind?.invoke()
            return listOf(node)
        }
    }

    private class BoundSemanticNode : LiveSemanticNode {
        override val resourceId: String = "demo:id/target"
        override val contentDescription: String? = null
        override val text: String? = null
        override val className: String = "android.widget.Button"
        override val packageName: String = "demo.app"
        override val visible: Boolean = true
        override val enabled: Boolean = true

        override fun recycle() = Unit
    }
}
