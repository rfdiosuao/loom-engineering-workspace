package com.apk.claw.android.rpa

import com.google.gson.JsonObject

sealed interface FreshnessRequirement {
    val captureMode: EvidenceCaptureMode

    data object ReadOnly : FreshnessRequirement {
        override val captureMode: EvidenceCaptureMode = EvidenceCaptureMode.FULL_FRAME
    }

    data class AuthorizeAfter(val capturedAfter: Long) : FreshnessRequirement {
        override val captureMode: EvidenceCaptureMode = EvidenceCaptureMode.FULL_FRAME
    }

    data object TreeRead : FreshnessRequirement {
        override val captureMode: EvidenceCaptureMode = EvidenceCaptureMode.TREE_ONLY
    }

    data class TreeAfter(val capturedAfter: Long) : FreshnessRequirement {
        override val captureMode: EvidenceCaptureMode = EvidenceCaptureMode.TREE_ONLY
    }
}

data class DisplayTransform(
    val displayId: Int,
    val widthPx: Int,
    val heightPx: Int,
    val screenshotWidthPx: Int,
    val screenshotHeightPx: Int,
    val rotation: Int,
    val densityDpi: Int,
    val insetLeft: Int,
    val insetTop: Int,
    val insetRight: Int,
    val insetBottom: Int
)

class UiEvidence(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val packageName: String,
    val windowId: Int,
    val capturedAt: Long,
    val transform: DisplayTransform,
    compactTree: JsonObject?,
    val frameId: String? = null,
    val frameSource: String? = null,
    val frameCapturedAt: Long? = null,
    val frameAgeMs: Long? = null,
    lumaPlane: LumaPlane? = null,
    runtimeServiceIdentity: Any? = null,
    val treeSnapshotMs: Long = 0L
) {
    @Transient
    private val compactTree: JsonObject? = compactTree

    @Transient
    private val lumaPlane: LumaPlane? = lumaPlane

    @Transient
    private val runtimeServiceIdentity: Any? = runtimeServiceIdentity

    internal fun compactTreeSnapshot(): CompactTreeSnapshot? =
        CompactTreeSnapshot.parse(this, compactTree)

    internal fun runtimeLumaPlane(): LumaPlane? = lumaPlane

    internal fun hasRuntimeServiceIdentity(): Boolean = runtimeServiceIdentity != null

    internal fun captureServiceIdentity(): ServiceIdentityBinding? =
        ServiceIdentityBinding.capture(runtimeServiceIdentity)

    internal fun sameServiceIdentity(expected: ServiceIdentityBinding?): Boolean =
        expected?.matches(runtimeServiceIdentity) == true
}

internal class ServiceIdentityBinding private constructor(
    @Transient private val serviceIdentity: Any
) {
    internal fun matches(candidate: Any?): Boolean = serviceIdentity === candidate

    internal fun sameService(other: ServiceIdentityBinding?): Boolean =
        other != null && serviceIdentity === other.serviceIdentity

    companion object {
        internal fun capture(serviceIdentity: Any?): ServiceIdentityBinding? =
            serviceIdentity?.let(::ServiceIdentityBinding)
    }
}

object ScreenshotFreshnessPolicy {
    private val readOnlySources = setOf("fresh", "cache", "stale_fallback")

    fun accepts(evidence: UiEvidence, requirement: FreshnessRequirement): Boolean {
        if (requirement.captureMode != EvidenceCaptureMode.FULL_FRAME) return false
        val source = evidence.frameSource ?: return false
        val capturedAt = evidence.frameCapturedAt ?: return false
        return when (requirement) {
            FreshnessRequirement.TreeRead,
            is FreshnessRequirement.TreeAfter -> false
            FreshnessRequirement.ReadOnly -> source in readOnlySources
            is FreshnessRequirement.AuthorizeAfter ->
                source == "fresh" && capturedAt > requirement.capturedAfter
        }
    }
}
