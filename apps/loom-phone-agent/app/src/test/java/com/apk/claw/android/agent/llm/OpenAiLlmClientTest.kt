package com.apk.claw.android.agent.llm

import com.apk.claw.android.agent.AgentConfig
import dev.langchain4j.data.message.SystemMessage
import dev.langchain4j.data.message.UserMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OpenAiLlmClientTest {
    @Test
    fun builds_openai_compatible_request_without_real_secrets() {
        val client = OpenAiLlmClient(
            AgentConfig(
                apiKey = "test-key",
                baseUrl = "https://example.test/v1",
                modelName = "test-model"
            )
        )

        val body = client.buildRequestBody(
            listOf(SystemMessage.from("system"), UserMessage.from("hello")),
            emptyList()
        )

        assertEquals("https://example.test/v1/chat/completions", client.chatCompletionsUrl())
        assertEquals("test-model", body.get("model").asString)
        assertEquals(false, body.get("stream").asBoolean)
        assertEquals(2, body.getAsJsonArray("messages").size())
    }

    @Test
    fun parses_tool_calls_and_token_usage() {
        val client = OpenAiLlmClient(
            AgentConfig(
                apiKey = "test-key",
                baseUrl = "https://example.test/v1",
                modelName = "test-model"
            )
        )

        val response = client.parseResponse(
            """
            {
              "choices": [
                {
                  "message": {
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [
                      {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                          "name": "tap",
                          "arguments": "{\"x\":10,\"y\":20}"
                        }
                      }
                    ]
                  }
                }
              ],
              "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18
              }
            }
            """.trimIndent()
        )

        assertEquals(null, response.text)
        assertEquals(1, response.toolExecutionRequests.size)
        assertEquals("call_123", response.toolExecutionRequests[0].id())
        assertEquals("tap", response.toolExecutionRequests[0].name())
        assertTrue(response.toolExecutionRequests[0].arguments().contains("\"x\":10"))
        assertEquals(18, response.tokenUsage?.totalTokenCount())
    }
}
