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

    @Test
    fun usb_identity_challenge_is_available_before_bearer_authentication() {
        val serverSource = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()
        val securitySource = File("src/main/java/com/apk/claw/android/server/LumiSecurityController.kt").readText()
        val handler = securitySource.substringAfter("fun handleIdentityChallenge")
            .substringBefore("fun handlePair")

        assertTrue(serverSource.contains("/api/lumi/security/identity-challenge"))
        assertTrue(handler.contains("UsbIdentityChallenge.isLoopbackPeer("))
        assertTrue(handler.contains("UsbIdentityChallenge.proof("))
        assertTrue(handler.contains("addProperty(\"listeningPort\", listeningPort)"))
        assertFalse(handler.contains("ToolApiController.checkAuth("))
    }

    @Test
    fun legacy_pairing_is_usb_only_and_disabled_after_secure_bootstrap() {
        val source = File("src/main/java/com/apk/claw/android/server/LumiSecurityController.kt").readText()
        val handler = source.substringAfter("fun handlePair")
            .substringBefore("fun handleStatus")

        assertTrue(handler.contains("UsbIdentityChallenge.isLoopbackPeer(session.remoteIpAddress)"))
        assertTrue(handler.contains("KVUtils.isSecurePhonePairingEstablished()"))
        assertTrue(handler.contains("phone_legacy_pairing_usb_required"))
        assertTrue(handler.contains("phone_secure_pairing_required"))
    }

    @Test
    fun config_server_remains_available_for_usb_without_a_lan_address() {
        val source = File("src/main/java/com/apk/claw/android/server/ConfigServerManager.kt").readText()
        val startHandler = source.substringAfter("fun start(context: Context)")
            .substringBefore("fun stop()")
        val onLostHandler = source.substringAfter("override fun onLost(network: Network)")
            .substringBefore("override fun onAvailable(network: Network)")

        assertFalse(startHandler.contains("if (!hasLanAddress(ctx))"))
        assertFalse(onLostHandler.contains("server?.stop()"))
        assertTrue(onLostHandler.contains("keeping ConfigServer available for USB loopback"))
    }
}
