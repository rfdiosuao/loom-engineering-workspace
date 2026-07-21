package com.apk.claw.android.server

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigServerCompatibilitySourceContractTest {
    @Test
    fun legacy_agent_routes_still_dispatch_to_token_authenticated_handlers() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

        assertTrue(source.contains("uri == \"/api/agent/execute_task\" && method == Method.POST -> AgentApiController.handleExecuteTask(session)"))
        assertTrue(source.contains("uri == \"/api/agent/cancel_task\" && method == Method.POST -> AgentApiController.handleCancelTask(session)"))
        assertFalse(source.contains("legacyAgentEndpointRemovedResponse()"))
    }

    @Test
    fun llm_config_get_does_not_return_plaintext_api_key() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

        assertTrue(source.contains("addProperty(\"llmApiKeyMasked\""))
        assertFalse(source.contains("addProperty(\"llmApiKey\", apiKey)"))
    }
}
