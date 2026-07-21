package com.apk.claw.android.workflow

import org.junit.Assert.assertEquals
import org.junit.Test

class WorkflowTemplateManagerTest {
    @Test
    fun resolves_placeholders_without_android_regex_initializer_crash() {
        val template = WorkflowTemplate(
            id = "test-template",
            name = "Test Template",
            description = "Test placeholder extraction",
            taskPattern = "test",
            keywords = listOf("test"),
            appName = null,
            steps = listOf(
                WorkflowTemplate.WorkflowStep(
                    toolName = "input_text",
                    paramsTemplate = mapOf("text" to "hello ${'$'}{contact_name} ${'$'}{message}"),
                    description = "Input parameterized text",
                    waitFor = 0
                )
            ),
            createdAt = 0L,
            lastUsedAt = 0L,
            successCount = 1,
            failCount = 0
        )

        val resolved = WorkflowTemplateManager.resolveTemplateParams(
            template = template,
            userPrompt = "",
            providedParams = mapOf("contact_name" to "Alice")
        )

        assertEquals(listOf("message"), resolved.missingParams)
        assertEquals("Alice", resolved.params["contact_name"])
    }
}
