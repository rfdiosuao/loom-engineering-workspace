package com.apk.claw.android.server

import com.apk.claw.android.rpa.HYBRID_EXECUTION_MODE
import com.apk.claw.android.rpa.RpaRunJson
import com.apk.claw.android.rpa.RpaRunSnapshot
import com.apk.claw.android.rpa.RpaRunStatus
import com.apk.claw.android.rpa.RpaStepRecord
import com.google.gson.JsonParser
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridRpaResponseTest {
    @Test
    fun capabilities_preserve_v1_schema_and_advertise_hybrid_v2() {
        val response = RpaApiController.handleCapabilities(session(), requireToken = false)
        val body = response.use {
            JsonParser.parseString(it.data.bufferedReader(Charsets.UTF_8).readText()).asJsonObject
        }
        val data = body["data"].asJsonObject

        assertEquals("apkclaw.rpa.v1", data["schema"].asString)
        assertEquals("apkclaw.hybrid-rpa.v2", data["hybridSchema"].asString)
        assertFalse(data["hybridRuntimeReady"].asBoolean)
        assertEquals("hybrid_engine_unavailable", data["hybridRuntimeState"].asString)
    }

    @Test
    fun hybrid_snapshot_contains_lifecycle_resolver_frame_outcome_and_tree_metrics_only() {
        val json = RpaRunJson.snapshot(hybridSnapshot())
        val serialized = json.toString()
        val step = json["steps"].asJsonArray[0].asJsonObject

        assertEquals(HYBRID_EXECUTION_MODE, json["mode"].asString)
        listOf(
            "templateStatus", "templateRevision", "validationProgress", "promotionEligible",
            "promotionIneligibleReason", "fallbackStepIndex", "outcomeState", "compactTreeReads",
            "fullTreeReads"
        ).forEach { assertTrue("missing run field $it", json.has(it)) }
        listOf(
            "resolverPolicy", "resolverUsed", "uiGeneration", "frameId", "frameSource", "frameAgeMs",
            "outcomeState", "treeSnapshotMs", "treeLookupMs", "treeCacheHit", "nodesVisited",
            "compactTreeReads", "fullTreeReads"
        ).forEach { assertTrue("missing step field $it", step.has(it)) }
        listOf(
            "selector", "params", "rawScreenshot", "rawTree", "token", "evidence", "ledgerProof",
            "secret-value", "private-screen-text"
        ).forEach { assertFalse("leaked $it", serialized.contains(it, ignoreCase = true)) }
    }

    @Test
    fun every_hybrid_failure_keeps_the_structured_error_contract() {
        val payload = ApiErrorPayload.build(
            errorCode = "profile_mismatch",
            message = "Fresh foreground profile does not match the template",
            mode = HYBRID_EXECUTION_MODE,
            currentStep = "validate",
            retryable = false
        )

        assertFalse(payload["success"].asBoolean)
        listOf("errorCode", "message", "currentStep", "mode", "retryable").forEach {
            assertTrue("missing failure field $it", payload.has(it))
        }
    }

    private fun hybridSnapshot() = RpaRunSnapshot(
        runId = "run-1",
        workflowId = "workflow-1",
        workflowName = "hybrid",
        status = RpaRunStatus.FAILED,
        currentStep = 1,
        totalSteps = 2,
        message = "uncertain",
        errorCode = "verification_unknown",
        startedAt = 10L,
        updatedAt = 30L,
        finishedAt = 30L,
        mode = HYBRID_EXECUTION_MODE,
        steps = listOf(
            RpaStepRecord(
                index = 1,
                stepId = "step-1",
                action = "tap_semantic",
                status = "failed",
                attempts = 1,
                actionMs = 8L,
                startedAt = 10L,
                finishedAt = 18L,
                resolverPolicy = "TREE_PREFERRED",
                resolverUsed = "RESOURCE_ID",
                treeSnapshotMs = 2L,
                treeLookupMs = 1L,
                treeCacheHit = true,
                nodesVisited = 4,
                frameId = "frame-1",
                frameSource = "fresh",
                frameAgeMs = 3L,
                uiGeneration = 7L,
                outcomeState = "uncertain",
                compactTreeReads = 1,
                fullTreeReads = 0,
                mode = HYBRID_EXECUTION_MODE
            )
        ),
        outcomeState = "uncertain",
        templateStatus = "degraded",
        templateRevision = 3,
        validationProgress = "3/3",
        promotionEligible = false,
        promotionIneligibleReason = "runtime_failure",
        fallbackStepIndex = 1,
        compactTreeReads = 1,
        fullTreeReads = 0
    )

    private fun session(): NanoHTTPD.IHTTPSession = Proxy.newProxyInstance(
        NanoHTTPD.IHTTPSession::class.java.classLoader,
        arrayOf(NanoHTTPD.IHTTPSession::class.java)
    ) { _, method, _ ->
        when (method.name) {
            "getHeaders" -> mutableMapOf<String, String>()
            "getInputStream" -> ByteArrayInputStream(ByteArray(0))
            "getMethod" -> NanoHTTPD.Method.GET
            "getUri" -> "/api/rpa/capabilities"
            "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
            "getParms" -> mutableMapOf<String, String>()
            "getParameters" -> mutableMapOf<String, MutableList<String>>()
            "getQueryParameterString" -> ""
            "execute" -> Unit
            else -> null
        }
    } as NanoHTTPD.IHTTPSession
}
