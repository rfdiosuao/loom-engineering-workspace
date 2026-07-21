package com.apk.claw.android.agent.llm

import com.apk.claw.android.agent.AgentConfig
import dev.langchain4j.data.message.SystemMessage
import dev.langchain4j.data.message.UserMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AnthropicLlmClientTest {
    @Test
    fun builds_anthropic_messages_request_without_real_secrets() {
        val client = AnthropicLlmClient(
            AgentConfig(
                apiKey = "test-key",
                baseUrl = "https://example.test",
                modelName = "claude-test"
            )
        )

        val body = client.buildRequestBody(
            listOf(SystemMessage.from("system"), UserMessage.from("hello")),
            emptyList()
        )

        assertEquals("https://example.test/v1/messages", client.messagesUrl())
        assertEquals("claude-test", body.get("model").asString)
        assertEquals("system", body.get("system").asString)
        assertEquals("user", body.getAsJsonArray("messages")[0].asJsonObject.get("role").asString)
    }

    @Test
    fun parses_text_tool_calls_and_token_usage() {
        val client = AnthropicLlmClient(
            AgentConfig(
                apiKey = "test-key",
                baseUrl = "https://example.test",
                modelName = "claude-test"
            )
        )

        val response = client.parseResponse(
            """
            {
              "content": [
                {"type": "text", "text": "Need to tap."},
                {"type": "tool_use", "id": "toolu_123", "name": "tap", "input": {"x": 10, "y": 20}}
              ],
              "usage": {
                "input_tokens": 12,
                "output_tokens": 8
              }
            }
            """.trimIndent()
        )

        assertEquals("Need to tap.", response.text)
        assertEquals(1, response.toolExecutionRequests.size)
        assertEquals("toolu_123", response.toolExecutionRequests[0].id())
        assertEquals("tap", response.toolExecutionRequests[0].name())
        assertTrue(response.toolExecutionRequests[0].arguments().contains("\"x\":10"))
        assertEquals(20, response.tokenUsage?.totalTokenCount())
    }
}
