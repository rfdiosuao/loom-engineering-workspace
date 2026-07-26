package com.apk.claw.android.workflow

data class SemanticSelector(
    val resourceId: String? = null,
    val contentDescription: String? = null,
    val text: String? = null,
    val className: String? = null,
    val packageName: String? = null,
    val structuralPath: List<Int> = emptyList()
)

data class VisualAnchorSpec(
    val assetName: String,
    val searchRegion: NormalizedRect,
    val tapOffsetX: Float,
    val tapOffsetY: Float,
    val minimumConfidence: Float = 0.88f,
    val scaleVariants: List<Float> = listOf(0.90f, 1.00f, 1.10f)
)

data class NormalizedRect(val left: Float, val top: Float, val right: Float, val bottom: Float)

data class DisplayTransformCheckpoint(
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

data class StepCheckpoint(
    val expectedPackage: String? = null,
    val requiredSelector: SemanticSelector? = null,
    val forbiddenSelector: SemanticSelector? = null,
    val perceptualHash: String? = null,
    val maximumHammingDistance: Int = 8,
    val expectedWindowId: Int? = null,
    val expectedDisplayTransform: DisplayTransformCheckpoint? = null
)
