package com.apk.claw.android.server

import com.google.gson.JsonObject

object ApiErrorPayload {
    fun build(
        errorCode: String,
        message: String,
        mode: String,
        currentStep: String = "failed",
        retryable: Boolean = false
    ): JsonObject {
        return JsonObject().apply {
            addProperty("success", false)
            addProperty("mode", mode)
            addProperty("currentStep", currentStep)
            addProperty("errorCode", errorCode)
            addProperty("message", message)
            addProperty("error", message)
            addProperty("retryable", retryable)
        }
    }
}
