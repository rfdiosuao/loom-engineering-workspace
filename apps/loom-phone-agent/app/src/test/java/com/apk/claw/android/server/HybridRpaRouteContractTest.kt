package com.apk.claw.android.server

import com.google.gson.JsonParser
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.File
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HybridRpaRouteContractTest {
    @Test
    fun token_and_lumi_template_lifecycle_routes_are_additive() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

        assertTrue(source.contains("/api/workflow/template/validate"))
        assertTrue(source.contains("/api/workflow/template/disable"))
        assertTrue(source.contains("/api/lumi/rpa/template/validate"))
        assertTrue(source.contains("/api/lumi/rpa/template/disable"))
        assertTrue(source.contains("handleLumiJson(session)"))
        assertTrue(source.contains("requireToken = false"))
        assertTrue(source.contains("/api/workflow/templates"))
        assertTrue(source.contains("/api/rpa/run"))
    }

    @Test
    fun lifecycle_controller_rejects_failed_token_validation_with_structured_json() {
        val response = WorkflowApiController.authorizeLifecycle(
            session = session(),
            requireToken = true,
            validator = { false }
        )

        val body = response!!.use {
            JsonParser.parseString(it.data.bufferedReader(Charsets.UTF_8).readText()).asJsonObject
        }
        assertEquals(NanoHTTPD.Response.Status.UNAUTHORIZED.requestStatus, response.status.requestStatus)
        assertFalse(body["success"].asBoolean)
        assertEquals("unauthorized", body["data"].asJsonObject["errorCode"].asString)
        assertEquals("workflow", body["data"].asJsonObject["mode"].asString)
        assertEquals("authorize", body["data"].asJsonObject["currentStep"].asString)
        assertFalse(body["data"].asJsonObject["retryable"].asBoolean)
    }

    private fun session(): NanoHTTPD.IHTTPSession = Proxy.newProxyInstance(
        NanoHTTPD.IHTTPSession::class.java.classLoader,
        arrayOf(NanoHTTPD.IHTTPSession::class.java)
    ) { _, method, _ ->
        when (method.name) {
            "getHeaders" -> mutableMapOf<String, String>()
            "getInputStream" -> ByteArrayInputStream(ByteArray(0))
            "getMethod" -> NanoHTTPD.Method.POST
            "getUri" -> "/api/workflow/template/validate"
            "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
            "getParms" -> mutableMapOf<String, String>()
            "getParameters" -> mutableMapOf<String, MutableList<String>>()
            "getQueryParameterString" -> ""
            "execute" -> Unit
            else -> null
        }
    } as NanoHTTPD.IHTTPSession
}
