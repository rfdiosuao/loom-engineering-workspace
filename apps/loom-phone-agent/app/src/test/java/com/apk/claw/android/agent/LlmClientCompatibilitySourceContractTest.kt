package com.apk.claw.android.agent

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LlmClientCompatibilitySourceContractTest {
    @Test
    fun anthropic_client_uses_android_safe_http_path() {
        val source = File("src/main/java/com/apk/claw/android/agent/llm/AnthropicLlmClient.kt").readText()
        val factory = File("src/main/java/com/apk/claw/android/agent/llm/LlmClientFactory.kt").readText()
        val build = File("build.gradle.kts").readText()

        assertFalse(source.contains("AnthropicChatModel"))
        assertFalse(source.contains("AnthropicStreamingChatModel"))
        assertFalse(source.contains("ChatRequest"))
        assertFalse(source.contains("ChatResponse"))
        assertFalse(factory.contains("OkHttpClientBuilderAdapter"))
        assertFalse(build.contains("libs.langchain4j.anthropic"))
        assertTrue(source.contains("OkHttpClient"))
        assertTrue(source.contains("/v1/messages"))
    }
}
