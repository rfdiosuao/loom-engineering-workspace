package com.apk.claw.android.rpa

import com.apk.claw.android.service.ClawAccessibilityService

internal fun interface ProductionPlatformServiceProvider {
    fun current(): ProductionPlatformService?
}

internal interface ProductionPlatformService {
    val identity: Any
    fun generationSnapshot(): GenerationSnapshot
    fun capture(requirement: FreshnessRequirement): UiEvidence
    fun dispatchSemantic(
        resolution: SemanticResolution.Unique,
        expectedGeneration: Long
    ): DispatchResult
    fun performTap(x: Int, y: Int): Boolean
    fun performLongPress(x: Int, y: Int, durationMs: Long): Boolean
    fun openApp(packageName: String): Boolean
    fun pressBack(): Boolean
    fun pressHome(): Boolean
    fun currentPackageName(): String
}

internal object CurrentClawPlatformServiceProvider : ProductionPlatformServiceProvider {
    override fun current(): ProductionPlatformService? =
        ClawAccessibilityService.getInstance()?.let(::AndroidProductionPlatformService)
}

internal class ProductionActionDispatcher(
    private val serviceProvider: ProductionPlatformServiceProvider = CurrentClawPlatformServiceProvider,
    private val sleeper: (Long) -> Unit = Thread::sleep,
    private val clock: () -> Long = System::currentTimeMillis
) : ActionDispatcher {
    override fun dispatch(action: PreparedAction): DispatchReceipt = when (val payload = action.payload) {
        is SemanticDispatchPayload -> dispatchSemantic(action, payload)
        is VisualDispatchPayload -> dispatchVisual(action, payload)
        is DirectPayload -> dispatchDirect(action, payload)
        else -> rejected(ERROR_ACTION_ADAPTER_UNAVAILABLE)
    }

    private fun dispatchSemantic(
        action: PreparedAction,
        payload: SemanticDispatchPayload
    ): DispatchReceipt = atPlatformBoundary(action, payload) { service ->
        val resolution = payload.resolutionForDispatch(service.identity)
            ?: return@atPlatformBoundary rejected(ERROR_SERVICE_INSTANCE_CHANGED)
        val result: DispatchResult? = service.dispatchSemantic(resolution, action.uiGeneration)
        result?.toDispatchReceipt() ?: uncertain(ERROR_PLATFORM_RESULT_UNCERTAIN)
    }

    private fun dispatchVisual(
        action: PreparedAction,
        payload: VisualDispatchPayload
    ): DispatchReceipt {
        val target = targetPoint(payload) ?: return rejected(ERROR_VISUAL_TARGET_INVALID)
        if (payload.action == VisualPlatformAction.LONG_PRESS &&
            payload.durationMs !in MIN_LONG_PRESS_MS..MAX_LONG_PRESS_MS
        ) return rejected(ERROR_VISUAL_TARGET_INVALID)
        return atPlatformBoundary(action, payload) { service ->
            val platformAccepted = when (payload.action) {
                VisualPlatformAction.TAP -> service.performTap(target.first, target.second)
                VisualPlatformAction.LONG_PRESS ->
                    service.performLongPress(target.first, target.second, payload.durationMs)
            }
            if (platformAccepted) accepted() else uncertain(ERROR_PLATFORM_RESULT_UNCERTAIN)
        }
    }

    private fun dispatchDirect(
        action: PreparedAction,
        payload: DirectPayload
    ): DispatchReceipt = atPlatformBoundary(action, payload) { service ->
        when (payload.action) {
            DirectAction.OPEN_APP ->
                if (service.openApp(payload.packageName!!)) accepted()
                else uncertain(ERROR_PLATFORM_RESULT_UNCERTAIN)
            DirectAction.WAIT -> {
                sleeper(payload.waitMs)
                accepted()
            }
            DirectAction.WAIT_STABLE -> rejected(ERROR_ACTION_ADAPTER_UNAVAILABLE)
            DirectAction.ASSERT_PACKAGE ->
                if (service.currentPackageName() == payload.packageName) accepted()
                else rejected(ERROR_PACKAGE_ASSERTION_FAILED)
            DirectAction.BACK ->
                if (service.pressBack()) accepted() else uncertain(ERROR_PLATFORM_RESULT_UNCERTAIN)
            DirectAction.HOME ->
                if (service.pressHome()) accepted() else uncertain(ERROR_PLATFORM_RESULT_UNCERTAIN)
            DirectAction.FINISH -> accepted()
        }
    }

    private inline fun atPlatformBoundary(
        action: PreparedAction,
        payload: ProductionRuntimePayload,
        platformCall: (ProductionPlatformService) -> DispatchReceipt
    ): DispatchReceipt {
        val service = try {
            serviceProvider.current()
        } catch (_: Throwable) {
            null
        } ?: return rejected(ERROR_SERVICE_UNAVAILABLE)
        if (!payload.sameServiceIdentity(service.identity)) {
            return rejected(ERROR_SERVICE_INSTANCE_CHANGED)
        }
        val generation = try {
            service.generationSnapshot()
        } catch (_: Throwable) {
            return rejected(ERROR_SERVICE_UNAVAILABLE)
        }
        if (generation.uiGeneration != action.uiGeneration ||
            generation.serviceGeneration != action.serviceGeneration
        ) return rejected(ERROR_GENERATION_CHANGED)
        return try {
            platformCall(service)
        } catch (_: Throwable) {
            uncertain(ERROR_PLATFORM_EXCEPTION)
        }
    }

    private fun targetPoint(payload: VisualDispatchPayload): Pair<Int, Int>? {
        val bounds = payload.bounds
        if (bounds.left < 0 || bounds.top < 0 || bounds.right <= bounds.left || bounds.bottom <= bounds.top) {
            return null
        }
        if (!payload.tapOffsetX.isFinite() || !payload.tapOffsetY.isFinite() ||
            payload.tapOffsetX !in 0f..1f || payload.tapOffsetY !in 0f..1f
        ) return null
        val width = bounds.right.toLong() - bounds.left.toLong()
        val height = bounds.bottom.toLong() - bounds.top.toLong()
        val x = (bounds.left.toLong() + (width.toDouble() * payload.tapOffsetX).toLong())
            .coerceIn(bounds.left.toLong(), bounds.right.toLong() - 1L)
        val y = (bounds.top.toLong() + (height.toDouble() * payload.tapOffsetY).toLong())
            .coerceIn(bounds.top.toLong(), bounds.bottom.toLong() - 1L)
        if (x !in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong() ||
            y !in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong()
        ) return null
        return x.toInt() to y.toInt()
    }

    private fun accepted(): DispatchReceipt = DispatchReceipt.accepted(safeNow())

    private fun rejected(errorCode: String): DispatchReceipt = DispatchReceipt.rejected(0L, errorCode)

    private fun uncertain(errorCode: String): DispatchReceipt =
        DispatchReceipt.outcomeUnknown(safeNow(), errorCode)

    private fun safeNow(): Long = runCatching(clock).getOrDefault(0L).coerceAtLeast(0L)

    companion object {
        const val ERROR_SERVICE_UNAVAILABLE = "accessibility_service_unavailable"
        const val ERROR_SERVICE_INSTANCE_CHANGED = "service_instance_changed"
        const val ERROR_GENERATION_CHANGED = "pre_action_generation_changed"
        const val ERROR_ACTION_ADAPTER_UNAVAILABLE = "action_adapter_unavailable"
        const val ERROR_VISUAL_TARGET_INVALID = "visual_target_invalid"
        const val ERROR_PACKAGE_ASSERTION_FAILED = "package_assertion_failed"
        const val ERROR_PLATFORM_RESULT_UNCERTAIN = "platform_result_uncertain"
        const val ERROR_PLATFORM_EXCEPTION = "platform_exception"

        private const val MIN_LONG_PRESS_MS = 500L
        private const val MAX_LONG_PRESS_MS = 5_000L
    }
}

private class AndroidProductionPlatformService(
    private val service: ClawAccessibilityService
) : ProductionPlatformService {
    override val identity: Any get() = service

    override fun generationSnapshot(): GenerationSnapshot = service.generationSnapshot

    override fun capture(requirement: FreshnessRequirement): UiEvidence =
        UiEvidenceProvider(service).capture(requirement)

    override fun dispatchSemantic(
        resolution: SemanticResolution.Unique,
        expectedGeneration: Long
    ): DispatchResult = AccessibilitySemanticDispatcher.exactInstance(service)
        .dispatch(resolution, expectedGeneration)

    override fun performTap(x: Int, y: Int): Boolean = service.performTap(x, y)

    override fun performLongPress(x: Int, y: Int, durationMs: Long): Boolean =
        service.performLongPress(x, y, durationMs)

    override fun openApp(packageName: String): Boolean = service.openApp(packageName)

    override fun pressBack(): Boolean = service.pressBack()

    override fun pressHome(): Boolean = service.pressHome()

    override fun currentPackageName(): String = service.currentPackageName.orEmpty()
}
