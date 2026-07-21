package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolApiControllerSourceContractTest {
    @Test
    fun tool_execution_failures_use_structured_error_payloads() {
        val source = File("src/main/java/com/apk/claw/android/server/ToolApiController.kt").readText()

        assertTrue(source.contains("structuredToolError("))
        assertFalse(source.contains("return jsonResponse(NanoHTTPD.Response.Status.OK, false, null, result.error)"))
    }
}
