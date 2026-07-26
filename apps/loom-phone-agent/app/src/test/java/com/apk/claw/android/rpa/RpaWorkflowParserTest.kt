package com.apk.claw.android.rpa

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
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
        assertEquals("rpa", result.workflow.executionMode)
        assertEquals(1, result.workflow.schemaVersion)
        assertEquals(com.apk.claw.android.workflow.ResolverPolicy.DIRECT, result.workflow.steps[0].resolverPolicy)
        assertTrue(result.workflow.steps[0].allowedResolvers.isEmpty())
        assertTrue(result.workflow.steps[0].validatedResolvers.isEmpty())
        assertNull(result.workflow.steps[0].semanticSelector)
        assertNull(result.workflow.steps[0].visualAnchor)
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

    @Test
    fun parses_explicit_valid_hybrid_workflow_without_leaking_control_fields_into_params() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            JsonParser.parseString(
                """
                {
                  "workflowId": "hybrid-demo",
                  "name": "Hybrid demo",
                  "schemaVersion": 2,
                  "executionMode": "hybrid_rpa",
                  "templateId": "template-1",
                  "templateRevision": 3,
                  "targetProfileId": "profile-1",
                  "templateStatus": "active",
                  "validationProgress": "3/3",
                  "promotionEligible": true,
                  "promotionIneligibleReason": "",
                  "steps": [{
                    "id": "tap-target",
                    "action": "tap_semantic",
                    "resolverPolicy": "TREE_PREFERRED",
                    "allowedResolvers": ["RESOURCE_ID", "VISUAL_ANCHOR"],
                    "validatedResolvers": ["RESOURCE_ID", "VISUAL_ANCHOR"],
                    "semanticSelector": {
                      "resourceId": "com.example:id/target",
                      "className": "Button",
                      "packageName": "com.example"
                    },
                    "visualAnchor": {
                      "assetName": "step-01-anchor.webp",
                      "searchRegion": {"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.8},
                      "tapOffsetX": 0.5,
                      "tapOffsetY": 0.5,
                      "minimumConfidence": 0.9,
                      "scaleVariants": [0.9, 1.0, 1.1]
                    }
                  }]
                }
                """.trimIndent()
            ).asJsonObject
        )

        assertEquals("hybrid_rpa", workflow.executionMode)
        assertEquals(2, workflow.schemaVersion)
        assertEquals("template-1", workflow.templateId)
        assertEquals(3, workflow.templateRevision)
        assertEquals("profile-1", workflow.targetProfileId)
        assertEquals("active", workflow.templateStatus)
        assertEquals("3/3", workflow.validationProgress)
        assertTrue(workflow.promotionEligible)
        assertEquals("", workflow.promotionIneligibleReason)
        assertEquals(com.apk.claw.android.workflow.ResolverPolicy.TREE_PREFERRED, workflow.steps.single().resolverPolicy)
        assertEquals(
            setOf(
                com.apk.claw.android.workflow.ResolverKind.RESOURCE_ID,
                com.apk.claw.android.workflow.ResolverKind.VISUAL_ANCHOR
            ),
            workflow.steps.single().allowedResolvers
        )
        assertFalse(workflow.steps.single().params.containsKey("resolverPolicy"))
        assertFalse(workflow.steps.single().params.containsKey("semanticSelector"))
        assertTrue(RpaWorkflowParser.validate(workflow).isEmpty())
    }

    @Test
    fun rejects_malformed_present_hybrid_fields_instead_of_defaulting() {
        val malformedSteps = listOf(
            """{"action":"back","params":7}""",
            """{"action":"back","guard":[]}""",
            """{"action":"back","timeoutMs":"5000"}""",
            """{"action":"back","timeoutMs":99}""",
            """{"action":"back","maxRetries":11}""",
            """{"action":"back","retryDelayMs":30001}""",
            """{"action":"back","resolverPolicy":"tree_preferred"}""",
            """{"action":"back","allowedResolvers":"DIRECT"}""",
            """{"action":"back","validatedResolvers":["NOT_A_RESOLVER"]}""",
            """{"action":"tap_semantic","semanticSelector":{"resourceId":9}}""",
            """{"action":"tap_anchor","visualAnchor":{"assetName":"a","searchRegion":{}}}"""
        )

        malformedSteps.forEach { step ->
            val json = hybridWorkflowJson(step)
            try {
                RpaWorkflowParser.parseWorkflow(JsonParser.parseString(json).asJsonObject)
                fail("Expected malformed hybrid field to be rejected: $json")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }

        val malformedWorkflowFields = listOf(
            hybridWorkflowJson("""{"action":"back"}""").replace("\"schemaVersion\":2", "\"schemaVersion\":\"two\""),
            hybridWorkflowJson("""{"action":"back"}""").replace("\"templateId\":\"template-1\"", "\"templateId\":7"),
            hybridWorkflowJson("""{"action":"back"}""").replace("\"templateRevision\":1", "\"templateRevision\":0"),
            hybridWorkflowJson("""{"action":"back"}""").replace("\"targetProfileId\":\"profile-1\"", "\"targetProfileId\":[]"),
            hybridWorkflowJson("""{"action":"back"}""").replace("\"steps\":", "\"promotionEligible\":\"yes\",\"steps\":")
        )
        malformedWorkflowFields.forEach { json ->
            try {
                RpaWorkflowParser.parseWorkflow(JsonParser.parseString(json).asJsonObject)
                fail("Expected malformed present workflow field to be rejected")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }
    }

    @Test
    fun legacy_mode_preserves_hybrid_named_inline_params_and_lenient_control_parsing() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            JsonParser.parseString(
                """
                {
                  "workflowId": "legacy-hybrid-keys",
                  "executionMode": 7,
                  "schemaVersion": "not-control-in-legacy",
                  "steps": [{
                    "action": "back",
                    "resolverPolicy": 17,
                    "allowedResolvers": "caller-data",
                    "semanticSelector": {"nested": true},
                    "timeoutMs": "bad-but-legacy-defaults"
                  }]
                }
                """.trimIndent()
            ).asJsonObject
        )

        val step = workflow.steps.single()
        assertEquals("rpa", workflow.executionMode)
        assertEquals(5_000L, step.timeoutMs)
        assertEquals(17, step.params["resolverPolicy"])
        assertEquals("caller-data", step.params["allowedResolvers"])
        assertEquals(mapOf("nested" to true), step.params["semanticSelector"])
        assertEquals(com.apk.claw.android.workflow.ResolverPolicy.DIRECT, step.resolverPolicy)
    }

    @Test
    fun exact_hybrid_mode_rejects_oversized_or_deep_input_and_large_structural_paths() {
        val tooDeep = (1..10).fold("true") { value, index -> "{\"n$index\":$value}" }
        val structuralPath = (0..32).joinToString(",")
        val malformed = listOf(
            hybridWorkflowJson("""{"action":"back","params":$tooDeep}"""),
            hybridWorkflowJson(
                """{"action":"tap_semantic","resolverPolicy":"TREE_PREFERRED","allowedResolvers":["STRUCTURAL"],"validatedResolvers":["STRUCTURAL"],"semanticSelector":{"structuralPath":[$structuralPath]}}"""
            ),
            hybridWorkflowJson(
                """{"action":"tap_normalized","resolverPolicy":"TREE_PREFERRED","allowedResolvers":["RESOURCE_ID","NORMALIZED_COORDINATE"],"validatedResolvers":["RESOURCE_ID","NORMALIZED_COORDINATE"],"semanticSelector":{"resourceId":"id"},"preCheckpoint":{"perceptualHash":"pf2:0000000000000000:00:00:0000000000000000","maximumHammingDistance":256}}"""
            )
        )

        malformed.forEach { json ->
            try {
                RpaWorkflowParser.parseWorkflow(JsonParser.parseString(json).asJsonObject)
                fail("Expected bounded hybrid input to be rejected")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }
    }

    @Test
    fun parses_bounded_persisted_coordinate_context() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            JsonParser.parseString(
                hybridWorkflowJson(
                    """{
                      "id":"coordinate",
                      "action":"tap_normalized",
                      "resolverPolicy":"TREE_PREFERRED",
                      "allowedResolvers":["RESOURCE_ID","NORMALIZED_COORDINATE"],
                      "validatedResolvers":["RESOURCE_ID","NORMALIZED_COORDINATE"],
                      "semanticSelector":{"resourceId":"com.example:id/missing"},
                      "preCheckpoint":{
                        "expectedPackage":"com.example",
                        "expectedWindowId":7,
                        "expectedDisplayTransform":{
                          "displayId":0,"widthPx":1080,"heightPx":1920,
                          "screenshotWidthPx":1080,"screenshotHeightPx":1920,
                          "rotation":0,"densityDpi":420,
                          "insetLeft":0,"insetTop":24,"insetRight":0,"insetBottom":48
                        },
                        "perceptualHash":"pf2:${"0".repeat(64)}:80:10:0000000000000000",
                        "maximumHammingDistance":8
                      }
                    }"""
                )
            ).asJsonObject
        )

        val checkpoint = workflow.steps.single().preCheckpoint!!
        assertEquals("com.example", checkpoint.expectedPackage)
        assertEquals(7, checkpoint.expectedWindowId)
        assertEquals(24, checkpoint.expectedDisplayTransform!!.insetTop)
        assertTrue(RpaWorkflowParser.validate(workflow).isEmpty())
    }

    @Test
    fun exact_hybrid_rejects_nonfinite_and_out_of_domain_numbers_recursively() {
        val malformed = listOf(
            hybridWorkflowJson("""{"action":"back","params":{"nested":[1e100000]}}"""),
            hybridWorkflowJson("""{"action":"back","params":{"nested":{"value":-1e100000}}}"""),
            hybridWorkflowJson("""{"action":"back","params":{"nested":[{"value":1e20}]}}""")
        )

        malformed.forEach { json ->
            try {
                RpaWorkflowParser.parseWorkflow(JsonParser.parseString(json).asJsonObject)
                fail("Expected non-finite or out-of-domain nested number to be rejected")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }

        val programmatic = RpaWorkflow(
            id = "programmatic",
            name = "Programmatic",
            steps = listOf(
                RpaStep(
                    id = "back",
                    action = "back",
                    params = mapOf("nested" to listOf(mapOf("value" to Double.POSITIVE_INFINITY))),
                    resolverPolicy = com.apk.claw.android.workflow.ResolverPolicy.DIRECT,
                    allowedResolvers = setOf(com.apk.claw.android.workflow.ResolverKind.DIRECT),
                    validatedResolvers = setOf(com.apk.claw.android.workflow.ResolverKind.DIRECT),
                    resolverPolicyExplicit = true
                )
            ),
            schemaVersion = 2,
            executionMode = "hybrid_rpa",
            templateId = "template-1",
            templateRevision = 1,
            targetProfileId = "profile-1"
        )
        assertTrue(RpaWorkflowParser.validate(programmatic).any { it.contains("numeric") })
    }

    @Test
    fun exact_hybrid_raw_json_rejects_non_rfc_syntax_duplicate_keys_and_trailing_data() {
        val malformed = listOf(
            hybridWorkflowJson("""{"action":"back","params":{"nested":[Infinity]}}"""),
            hybridWorkflowJson("""{"action":"back","params":{"nested":[-Infinity]}}"""),
            hybridWorkflowJson("""{"action":"back","params":{"nested":[NaN]}}"""),
            hybridWorkflowJson("""{"action":"back","params":{/*comment*/"value":"ok"}}"""),
            hybridWorkflowJson("""{action:"back","params":{"value":"ok"}}"""),
            hybridWorkflowJson("""{"action":"back","params":{"value":1,"value":2}}"""),
            hybridWorkflowJson("""{"action":"back"}""") + " trailing"
        )

        malformed.forEach { raw ->
            try {
                RpaWorkflowParser.parseWorkflow(raw)
                fail("Expected strict hybrid raw JSON rejection")
            } catch (_: IllegalArgumentException) {
                // Expected.
            }
        }
    }

    @Test
    fun exact_valid_hybrid_raw_json_parses_and_quoted_infinity_remains_a_string() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            hybridWorkflowJson("""{"action":"back","params":{"nested":["Infinity"]},"resolverPolicy":"DIRECT","allowedResolvers":["DIRECT"],"validatedResolvers":["DIRECT"]}""")
        )

        assertEquals("Infinity", (workflow.steps.single().params["nested"] as List<*>).single())
        assertTrue(RpaWorkflowParser.validate(workflow).isEmpty())
    }

    @Test
    fun legacy_raw_json_keeps_existing_lenient_unknown_inline_parameter_behavior() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            """{"workflowId":"legacy","steps":[{"action":"wait","legacyValue":Infinity}]}"""
        )

        assertEquals("rpa", workflow.executionMode)
        assertEquals("Infinity", workflow.steps.single().params["legacyValue"])
    }

    @Test
    fun rejects_hybrid_mode_without_schema_template_profile_and_explicit_step_policy() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            JsonParser.parseString(
                """
                {
                  "workflowId": "incomplete",
                  "executionMode": "hybrid_rpa",
                  "steps": [{"id": "back", "action": "back"}]
                }
                """.trimIndent()
            ).asJsonObject
        )

        val errors = RpaWorkflowParser.validate(workflow)

        assertTrue(errors.any { it.contains("schemaVersion") })
        assertTrue(errors.any { it.contains("templateId") })
        assertTrue(errors.any { it.contains("templateRevision") })
        assertTrue(errors.any { it.contains("targetProfileId") })
        assertTrue(errors.any { it.contains("resolverPolicy") })
        assertTrue(errors.any { it.contains("allowedResolvers") })
        assertTrue(errors.any { it.contains("validatedResolvers") })
    }

    @Test
    fun rejects_hybrid_validated_resolvers_outside_allowed_set() {
        val workflow = RpaWorkflowParser.parseWorkflow(
            JsonParser.parseString(
                """
                {
                  "workflowId": "bad-sets",
                  "schemaVersion": 2,
                  "executionMode": "hybrid_rpa",
                  "templateId": "template-1",
                  "templateRevision": 1,
                  "targetProfileId": "profile-1",
                  "steps": [{
                    "action": "tap_semantic",
                    "resolverPolicy": "TREE_PREFERRED",
                    "allowedResolvers": ["RESOURCE_ID"],
                    "validatedResolvers": ["VISUAL_ANCHOR"],
                    "semanticSelector": {"resourceId": "com.example:id/target"}
                  }]
                }
                """.trimIndent()
            ).asJsonObject
        )

        assertTrue(RpaWorkflowParser.validate(workflow).any { it.contains("validatedResolvers") })
    }

    private fun hybridWorkflowJson(step: String): String =
        """{"workflowId":"bad","executionMode":"hybrid_rpa","schemaVersion":2,"templateId":"template-1","templateRevision":1,"targetProfileId":"profile-1","steps":[$step]}"""
}
