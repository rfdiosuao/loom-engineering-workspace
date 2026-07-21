package com.apk.claw.android.floating

internal data class FloatingInteractionMode(
    val clickEnabled: Boolean,
    val dragEnabled: Boolean,
    val touchPassthrough: Boolean,
    val windowAlpha: Float
)

internal object FloatingInteractionPolicy {
    private const val PASSTHROUGH_WINDOW_ALPHA = 0.72f

    fun resolve(clickEnabled: Boolean): FloatingInteractionMode {
        return FloatingInteractionMode(
            clickEnabled = clickEnabled,
            dragEnabled = clickEnabled,
            touchPassthrough = !clickEnabled,
            windowAlpha = if (clickEnabled) 1f else PASSTHROUGH_WINDOW_ALPHA
        )
    }
}
