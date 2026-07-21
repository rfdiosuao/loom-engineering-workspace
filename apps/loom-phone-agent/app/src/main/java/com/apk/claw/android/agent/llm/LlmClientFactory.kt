package com.apk.claw.android.agent.llm

import com.apk.claw.android.agent.AgentConfig
import com.apk.claw.android.agent.LlmProvider

object LlmClientFactory {

    fun create(config: AgentConfig): LlmClient {
        return when (config.provider) {
            LlmProvider.OPENAI -> OpenAiLlmClient(config)
            LlmProvider.ANTHROPIC -> AnthropicLlmClient(config)
        }
    }
}
