package com.apk.claw.android.server

import com.apk.claw.android.rpa.RpaWorkflowRunner
import com.apk.claw.android.rpa.AgentHandoffContext
import com.apk.claw.android.rpa.HybridRunResult
import com.apk.claw.android.rpa.HybridWorkflowExecutor
import com.apk.claw.android.rpa.RpaWorkflow
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.lang.reflect.Proxy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RpaApiControllerTest {
    @After
    fun tearDown() {
        RpaWorkflowRunner.installHybridEngine(null)
    }

    @Test
    fun run_and_validate_reject_non_rfc_exact_hybrid_bodies_before_preprocessing() {
        malformedHybridBodies().forEach { raw ->
            listOf(
                RpaApiController.handleRun(session(raw), requireToken = false),
                RpaApiController.handleValidate(session(raw), requireToken = false)
            ).forEach { response ->
                val body = responseJson(response)
                assertFalse(body["success"].asBoolean)
                assertEquals("invalid_workflow", body["data"].asJsonObject["errorCode"].asString)
                assertEquals("rpa", body["data"].asJsonObject["mode"].asString)
            }
        }
    }

    @Test
    fun validate_accepts_valid_hybrid_and_quoted_infinity_while_run_reaches_normal_precheck() {
        val raw = hybridWorkflowJson(
            """{"id":"back","action":"back","params":{"nested":["Infinity"]},"resolverPolicy":"DIRECT","allowedResolvers":["DIRECT"],"validatedResolvers":["DIRECT"]}"""
        )

        val validation = responseJson(
            RpaApiController.handleValidate(session(raw), requireToken = false)
        )
        val run = responseJson(
            RpaApiController.handleRun(session(raw), requireToken = false)
        )

        assertTrue(validation["success"].asBoolean)
        assertTrue(validation["data"].asJsonObject["valid"].asBoolean)
        assertFalse(run["success"].asBoolean)
        assertEquals("hybrid_engine_unavailable", run["data"].asJsonObject["errorCode"].asString)
        assertNotEquals("invalid_workflow", run["data"].asJsonObject["errorCode"].asString)
    }

    @Test
    fun run_and_validate_keep_legacy_bare_infinity_compatibility() {
        val raw = """{"workflowId":"legacy","steps":[{"action":"wait","legacyValue":Infinity}]}"""

        val validation = responseJson(
            RpaApiController.handleValidate(session(raw), requireToken = false)
        )
        val run = responseJson(
            RpaApiController.handleRun(session(raw), requireToken = false)
        )

        assertTrue(validation["success"].asBoolean)
        assertTrue(validation["data"].asJsonObject["valid"].asBoolean)
        assertFalse(run["success"].asBoolean)
        assertEquals("accessibility_reenable_required", run["data"].asJsonObject["errorCode"].asString)
    }

    @Test
    fun validate_semantic_failure_preserves_summary_and_adds_full_failure_contract() {
        val raw = hybridWorkflowJson(
            """{"id":"bad","action":"unsupported","resolverPolicy":"DIRECT","allowedResolvers":["DIRECT"],"validatedResolvers":["DIRECT"]}"""
        )

        val body = responseJson(RpaApiController.handleValidate(session(raw), requireToken = false))
        val data = body["data"].asJsonObject

        assertFalse(body["success"].asBoolean)
        assertFalse(data["valid"].asBoolean)
        assertTrue(data.has("workflow"))
        assertTrue(data["errors"].asJsonArray.size() > 0)
        assertFalse(data["success"].asBoolean)
        assertEquals("invalid_workflow", data["errorCode"].asString)
        assertTrue(data["message"].asString.isNotBlank())
        assertEquals("validate", data["currentStep"].asString)
        assertEquals("rpa", data["mode"].asString)
        assertFalse(data["retryable"].asBoolean)
    }

    @Test
    fun capabilities_do_not_claim_runtime_ready_when_engine_is_installed_without_accessibility() {
        RpaWorkflowRunner.installHybridEngine(object : HybridWorkflowExecutor {
            override fun run(
                workflow: RpaWorkflow,
                runId: String,
                resumeFrom: AgentHandoffContext?,
                cancelled: () -> Boolean,
                deadlineAt: Long
            ): HybridRunResult = error("must not execute")
        })

        val body = responseJson(RpaApiController.handleCapabilities(session("{}"), requireToken = false))
        val data = body["data"].asJsonObject

        assertTrue(data["engineInstalled"].asBoolean)
        assertFalse(data["accessibilityReady"].asBoolean)
        assertFalse(data["hybridRuntimeReady"].asBoolean)
        assertEquals("accessibility_reenable_required", data["hybridRuntimeState"].asString)
    }

    private fun malformedHybridBodies(): List<String> = listOf(
        hybridWorkflowJson("""{"action":"back","params":{"nested":[Infinity]}}"""),
        hybridWorkflowJson("""{"action":"back","params":{"nested":[-Infinity]}}"""),
        hybridWorkflowJson("""{"action":"back","params":{"nested":[NaN]}}"""),
        hybridWorkflowJson("""{"action":"back","params":{/*comment*/"value":"ok"}}"""),
        hybridWorkflowJson("""{action:"back","params":{"value":"ok"}}"""),
        hybridWorkflowJson("""{"action":"back","params":{"value":1,"value":2}}"""),
        hybridWorkflowJson("""{"action":"back"}""") + " trailing"
    )

    private fun hybridWorkflowJson(step: String): String =
        """{"workflowId":"http-hybrid","executionMode":"hybrid_rpa","schemaVersion":2,"templateId":"template-1","templateRevision":1,"targetProfileId":"profile-1","steps":[$step]}"""

    private fun responseJson(response: NanoHTTPD.Response): JsonObject = response.use {
        JsonParser.parseString(it.data.bufferedReader(Charsets.UTF_8).readText()).asJsonObject
    }

    private fun session(raw: String): NanoHTTPD.IHTTPSession {
        val bytes = raw.toByteArray(Charsets.UTF_8)
        val headers = mutableMapOf(
            "content-length" to bytes.size.toString(),
            "Content-Length" to bytes.size.toString()
        )
        return Proxy.newProxyInstance(
            NanoHTTPD.IHTTPSession::class.java.classLoader,
            arrayOf(NanoHTTPD.IHTTPSession::class.java)
        ) { _, method, arguments ->
            when (method.name) {
                "getHeaders" -> headers
                "getInputStream" -> ByteArrayInputStream(bytes)
                "getMethod" -> NanoHTTPD.Method.POST
                "getUri" -> "/api/rpa"
                "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
                "getParms" -> mutableMapOf<String, String>()
                "getParameters" -> mutableMapOf<String, MutableList<String>>()
                "getQueryParameterString" -> ""
                "parseBody" -> {
                    @Suppress("UNCHECKED_CAST")
                    (arguments?.firstOrNull() as? MutableMap<String, String>)?.set("postData", raw)
                    Unit
                }
                "execute" -> Unit
                else -> null
            }
        } as NanoHTTPD.IHTTPSession
    }
}
