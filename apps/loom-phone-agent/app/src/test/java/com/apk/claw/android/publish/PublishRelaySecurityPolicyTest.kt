package com.apk.claw.android.publish

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PublishRelaySecurityPolicyTest {

    @Test
    fun formalPublishRequiresHttpsForRemoteRelay() {
        assertFalse(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "http://relay.example.com",
                draftOnly = false,
            )
        )
        assertTrue(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "https://relay.example.com",
                draftOnly = false,
            )
        )
    }

    @Test
    fun draftAndLoopbackWorkflowsMayUseHttp() {
        assertTrue(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "http://relay.example.com",
                draftOnly = true,
            )
        )
        assertTrue(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "http://127.0.0.1:18790",
                draftOnly = false,
            )
        )
        assertTrue(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "http://localhost:18790",
                draftOnly = false,
            )
        )
    }

    @Test
    fun malformedRelayUrlsFailClosedForFormalPublish() {
        assertFalse(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "relay.example.com",
                draftOnly = false,
            )
        )
        assertFalse(
            PublishRelaySecurityPolicy.mayExecute(
                relayBaseUrl = "",
                draftOnly = false,
            )
        )
    }
}
