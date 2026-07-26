package com.apk.claw.android.rpa

import com.apk.claw.android.workflow.StepCheckpoint

internal interface ProductionRuntimePayload : DispatchPayload {
    fun sameServiceIdentity(candidate: Any?): Boolean
    fun sameServiceIdentity(evidence: UiEvidence): Boolean
    fun preCheckpoint(): StepCheckpoint?
    fun postCheckpoint(): StepCheckpoint?
}

internal class SemanticDispatchPayload(
    resolution: SemanticResolution.Unique,
    override val bounds: IntRect,
    evidence: UiEvidence,
    preCheckpoint: StepCheckpoint? = null,
    postCheckpoint: StepCheckpoint? = null
) : BoundedDispatchPayload, ProductionRuntimePayload {
    @Transient
    private val resolution: SemanticResolution.Unique = resolution

    @Transient
    private val expectedServiceIdentity: ServiceIdentityBinding? = evidence.captureServiceIdentity()

    @Transient
    private val preCheckpoint: StepCheckpoint? = preCheckpoint

    @Transient
    private val postCheckpoint: StepCheckpoint? = postCheckpoint

    internal fun resolutionForDispatch(current: UiEvidence): SemanticResolution.Unique? =
        resolution.takeIf { current.sameServiceIdentity(expectedServiceIdentity) }

    internal fun resolutionForDispatch(serviceIdentity: Any?): SemanticResolution.Unique? =
        resolution.takeIf { expectedServiceIdentity?.matches(serviceIdentity) == true }

    override fun sameServiceIdentity(evidence: UiEvidence): Boolean =
        evidence.sameServiceIdentity(expectedServiceIdentity)

    override fun sameServiceIdentity(candidate: Any?): Boolean =
        expectedServiceIdentity?.matches(candidate) == true

    override fun preCheckpoint(): StepCheckpoint? = preCheckpoint

    override fun postCheckpoint(): StepCheckpoint? = postCheckpoint
}

internal enum class VisualPlatformAction { TAP, LONG_PRESS }

internal class VisualDispatchPayload(
    override val bounds: IntRect,
    val tapOffsetX: Float,
    val tapOffsetY: Float,
    val action: VisualPlatformAction,
    val durationMs: Long,
    evidence: UiEvidence,
    preCheckpoint: StepCheckpoint? = null,
    postCheckpoint: StepCheckpoint? = null
) : BoundedDispatchPayload, ProductionRuntimePayload {
    @Transient
    private val expectedServiceIdentity: ServiceIdentityBinding? = evidence.captureServiceIdentity()

    @Transient
    private val preCheckpoint: StepCheckpoint? = preCheckpoint

    @Transient
    private val postCheckpoint: StepCheckpoint? = postCheckpoint

    override fun sameServiceIdentity(evidence: UiEvidence): Boolean =
        evidence.sameServiceIdentity(expectedServiceIdentity)

    override fun sameServiceIdentity(candidate: Any?): Boolean =
        expectedServiceIdentity?.matches(candidate) == true

    override fun preCheckpoint(): StepCheckpoint? = preCheckpoint

    override fun postCheckpoint(): StepCheckpoint? = postCheckpoint
}

internal class DirectPayload(
    val action: DirectAction,
    val packageName: String? = null,
    val waitMs: Long = 0L,
    evidence: UiEvidence,
    preCheckpoint: StepCheckpoint? = null,
    postCheckpoint: StepCheckpoint? = null
) : ProductionRuntimePayload {
    @Transient
    private val expectedServiceIdentity: ServiceIdentityBinding? = evidence.captureServiceIdentity()

    @Transient
    private val preCheckpoint: StepCheckpoint? = preCheckpoint

    @Transient
    private val postCheckpoint: StepCheckpoint? = postCheckpoint

    init {
        when (action) {
            DirectAction.OPEN_APP, DirectAction.ASSERT_PACKAGE ->
                require(packageName != null && PACKAGE_NAME_PATTERN.matches(packageName)) {
                    "direct_package_invalid"
                }
            else -> require(packageName == null) { "direct_package_unexpected" }
        }
        when (action) {
            DirectAction.WAIT, DirectAction.WAIT_STABLE ->
                require(waitMs in 0L..MAX_WAIT_MS) { "direct_wait_invalid" }
            else -> require(waitMs == 0L) { "direct_wait_unexpected" }
        }
    }

    override fun sameServiceIdentity(candidate: Any?): Boolean =
        expectedServiceIdentity?.matches(candidate) == true

    override fun sameServiceIdentity(evidence: UiEvidence): Boolean =
        evidence.sameServiceIdentity(expectedServiceIdentity)

    override fun preCheckpoint(): StepCheckpoint? = preCheckpoint

    override fun postCheckpoint(): StepCheckpoint? = postCheckpoint

    companion object {
        internal const val MAX_WAIT_MS = 30_000L
        private val PACKAGE_NAME_PATTERN = Regex("^[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z0-9_]+)+$")

        internal fun from(step: RpaStep, evidence: UiEvidence, action: DirectAction): DirectPayload? =
            runCatching {
                val packageName = when (action) {
                    DirectAction.OPEN_APP, DirectAction.ASSERT_PACKAGE -> step.params.safePackageName()
                    else -> null
                }
                val waitMs = when (action) {
                    DirectAction.WAIT, DirectAction.WAIT_STABLE -> step.params.safeWaitMs()
                    else -> 0L
                }
                DirectPayload(
                    action = action,
                    packageName = packageName,
                    waitMs = waitMs,
                    evidence = evidence,
                    preCheckpoint = step.preCheckpoint,
                    postCheckpoint = step.postCheckpoint
                )
            }.getOrNull()

        private fun Map<String, Any>.safePackageName(): String? =
            listOf("package_name", "packageName", "package")
                .firstNotNullOfOrNull { key -> (get(key) as? String)?.trim() }
                ?.takeIf(PACKAGE_NAME_PATTERN::matches)

        private fun Map<String, Any>.safeWaitMs(): Long {
            val value = listOf("duration_ms", "durationMs", "wait_ms", "waitMs")
                .firstNotNullOfOrNull(::get) ?: 0L
            return value.integralLong()?.takeIf { it in 0L..MAX_WAIT_MS }
                ?: throw IllegalArgumentException("direct_wait_invalid")
        }

        private fun Any.integralLong(): Long? = when (this) {
            is Byte -> toLong()
            is Short -> toLong()
            is Int -> toLong()
            is Long -> this
            is Float -> takeIf { it.isFinite() && it % 1f == 0f }?.toLong()
            is Double -> takeIf { it.isFinite() && it % 1.0 == 0.0 }?.toLong()
            else -> null
        }
    }
}
