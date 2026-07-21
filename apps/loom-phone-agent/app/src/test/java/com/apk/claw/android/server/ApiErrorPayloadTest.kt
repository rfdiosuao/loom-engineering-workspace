package com.apk.claw.android.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiErrorPayloadTest {
    @Test
    fun builds_structured_retryable_json_error_for_fast_paths() {
        val payload = ApiErrorPayload.build(
            errorCode = "screenshot_failed",
            message = "Failed to take screenshot",
            mode = "screenshot",
            currentStep = "failed",
            retryable = true
        )

        assertFalse(payload["success"].asBoolean)
        assertEquals("screenshot_failed", payload["errorCode"].asString)
        assertEquals("Failed to take screenshot", payload["message"].asString)
        assertEquals("Failed to take screenshot", payload["error"].asString)
        assertEquals("failed", payload["currentStep"].asString)
        assertEquals("screenshot", payload["mode"].asString)
        assertTrue(payload["retryable"].asBoolean)
    }
}
