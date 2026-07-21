package com.apk.claw.android.agent

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OpenAiLlmClientSourceContractTest {
    @Test
    fun openai_client_uses_android_safe_http_path() {
        val source = File("src/main/java/com/apk/claw/android/agent/llm/OpenAiLlmClient.kt").readText()

        assertFalse(source.contains("OpenAiChatModel"))
        assertFalse(source.contains("OpenAiStreamingChatModel"))
        assertFalse(source.contains("ChatRequest"))
        assertFalse(source.contains("ChatResponse"))
        assertTrue(source.contains("OkHttpClient"))
        assertTrue(source.contains("chat/completions"))

        val build = File("build.gradle.kts").readText()
        assertFalse(build.contains("libs.langchain4j.openai"))
    }
}
