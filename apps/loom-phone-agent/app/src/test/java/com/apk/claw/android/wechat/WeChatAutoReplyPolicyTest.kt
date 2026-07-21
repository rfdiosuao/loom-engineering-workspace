package com.apk.claw.android.wechat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WeChatAutoReplyPolicyTest {
    @Test
    fun defaults_to_draft_mode_without_auto_send() {
        val decision = WeChatAutoReplyPolicy.decide(
            contact = "Alice",
            incomingText = "hello",
            replyText = "hi",
            autoSend = false,
            whitelist = emptySet()
        )

        assertTrue(decision.allowed)
        assertFalse(decision.shouldSend)
        assertEquals("draft_only", decision.mode)
    }

    @Test
    fun auto_send_requires_contact_whitelist() {
        val blocked = WeChatAutoReplyPolicy.decide(
            contact = "Alice",
            incomingText = "hello",
            replyText = "hi",
            autoSend = true,
            whitelist = setOf("Bob")
        )
        val allowed = WeChatAutoReplyPolicy.decide(
            contact = "Alice",
            incomingText = "hello",
            replyText = "hi",
            autoSend = true,
            whitelist = setOf("Alice")
        )

        assertFalse(blocked.allowed)
        assertEquals("contact_not_whitelisted", blocked.errorCode)
        assertTrue(allowed.allowed)
        assertTrue(allowed.shouldSend)
        assertEquals("auto_send", allowed.mode)
    }

    @Test
    fun group_chat_is_blocked_by_default() {
        val decision = WeChatAutoReplyPolicy.decide(
            contact = "Family Group",
            incomingText = "hello",
            replyText = "hi",
            autoSend = true,
            whitelist = setOf("Family Group"),
            isGroupChat = true
        )

        assertFalse(decision.allowed)
        assertEquals("group_chat_blocked", decision.errorCode)
    }

    @Test
    fun sensitive_content_is_never_auto_sent() {
        val decision = WeChatAutoReplyPolicy.decide(
            contact = "Alice",
            incomingText = "验证码 123456",
            replyText = "你的验证码是 123456",
            autoSend = true,
            whitelist = setOf("Alice")
        )

        assertFalse(decision.allowed)
        assertEquals("sensitive_content_blocked", decision.errorCode)
    }
}
