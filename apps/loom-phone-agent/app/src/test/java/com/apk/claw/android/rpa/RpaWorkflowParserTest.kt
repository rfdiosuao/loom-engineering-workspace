package com.apk.claw.android.rpa

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RpaWorkflowParserTest {
    @Test
    fun parses_workflow_and_resolves_params() {
        val json = JsonParser.parseString(
            """
            {
              "params": {
                "pkg": "com.example.app",
                "title": "hello"
              },
              "workflow": {
                "workflowId": "demo",
                "name": "Demo RPA",
                "steps": [
                  {
                    "id": "open",
                    "action": "open_app",
                    "package": "${'$'}{pkg}",
                    "guard": {
                      "expectedPackage": "${'$'}{pkg}"
                    }
                  },
                  {
                    "id": "tap",
                    "action": "click_text",
                    "text": "${'$'}{title}",
                    "maxRetries": 2
                  }
                ]
              }
            }
            """.trimIndent()
        ).asJsonObject

        val result = RpaWorkflowParser.parseRunRequest(json)

        assertEquals("demo", result.workflow.id)
        assertEquals("Demo RPA", result.workflow.name)
        assertEquals(2, result.workflow.steps.size)
        assertEquals("open_app", result.workflow.steps[0].action)
        assertEquals("com.example.app", result.workflow.steps[0].params["package"])
        assertEquals("com.example.app", result.workflow.steps[0].guard.expectedPackage)
        assertEquals("tap_text", result.workflow.steps[1].action)
        assertEquals("hello", result.workflow.steps[1].params["text"])
        assertEquals(2, result.workflow.steps[1].maxRetries)
        assertTrue(RpaWorkflowParser.validate(result.workflow).isEmpty())
    }

    @Test
    fun validation_rejects_unsupported_actions_and_unresolved_params() {
        val json = JsonParser.parseString(
            """
            {
              "workflowId": "bad",
              "steps": [
                {"action": "fly", "text": "${'$'}{missing}"}
              ]
            }
            """.trimIndent()
        ).asJsonObject

        val workflow = RpaWorkflowParser.parseWorkflow(json)
        val errors = RpaWorkflowParser.validate(workflow)

        assertTrue(errors.any { it.contains("unsupported action") })
        assertTrue(errors.any { it.contains("unresolved param: missing") })
    }
}
