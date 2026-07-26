package com.apk.claw.android.tool.impl

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class InputTextToolSourceContractTest {
    private val source = sequenceOf(
        File("app/src/main/java/com/apk/claw/android/tool/impl/InputTextTool.java"),
        File("src/main/java/com/apk/claw/android/tool/impl/InputTextTool.java")
    ).firstOrNull { it.isFile }?.readText() ?: error("InputTextTool.java not found")

    @Test
    fun targeted_parameters_are_optional_for_legacy_callers() {
        listOf(
            "package_name",
            "resource_id",
            "text_hint",
            "bounds_hint",
            "require_focused",
            "expected_existing_text"
        ).forEach { parameter ->
            assertTrue("missing optional parameter $parameter", source.contains("\"$parameter\""))
        }
        assertTrue(source.contains("findFocusedEditText"))
    }

    @Test
    fun targeted_mode_resolves_a_unique_node_before_any_text_action() {
        assertTrue(source.contains("boolean targetedMode ="))
        assertTrue(source.contains("TargetedTextInputResolver.INSTANCE.resolve"))
        assertTrue(source.contains("comment_composer_unreachable"))
        assertTrue(source.contains("comment_composer_ambiguous"))
        assertTrue(
            source.indexOf("TargetedTextInputResolver.INSTANCE.resolve") <
                source.indexOf("targetNode.performAction")
        )
    }
}
