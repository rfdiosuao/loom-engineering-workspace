package com.apk.claw.android.rpa

import java.util.Locale

object RpaActionNormalizer {
    private val supported = setOf(
        "open_app",
        "wait_text",
        "assert_text",
        "assert_package",
        "tap_text",
        "tap_description",
        "tap_resource_id",
        "tap",
        "input_text",
        "swipe",
        "scroll",
        "back",
        "home",
        "wait",
        "screenshot",
        "observe"
    )

    fun normalize(action: String?): String {
        val value = action.orEmpty().trim().lowercase(Locale.US).replace("-", "_")
        return when (value) {
            "click_text", "tap_label", "click_label" -> "tap_text"
            "tap_desc", "click_desc", "click_description", "tap_content_description" -> "tap_description"
            "tap_id", "click_id", "tap_element", "click_element", "click_resource_id" -> "tap_resource_id"
            "type", "type_text", "set_text", "input" -> "input_text"
            "press_back", "system_back" -> "back"
            "press_home", "system_home" -> "home"
            "sleep" -> "wait"
            "read_screen", "screen_info", "observe_fast" -> "observe"
            "take_screenshot" -> "screenshot"
            "wait_for_text", "wait_until_text" -> "wait_text"
            else -> value
        }
    }

    fun isSupported(action: String): Boolean = normalize(action) in supported

    fun supportedActions(): List<String> = supported.sorted()
}
