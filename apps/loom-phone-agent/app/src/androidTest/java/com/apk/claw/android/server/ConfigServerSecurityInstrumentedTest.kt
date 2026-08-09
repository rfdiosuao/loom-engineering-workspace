package com.apk.claw.android.server

import android.content.Context
import android.system.Os
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.PhoneCredentialVault
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.File
import java.lang.reflect.Proxy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 24)
class ConfigServerSecurityInstrumentedTest {
    private lateinit var context: Context
    private lateinit var server: ConfigServer

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        KVUtils.init(context)
        KVUtils.clear()
        PhoneCredentialVault.clear()
        server = ConfigServer(context, 0)
        KVUtils.putString("KEY_API_TOKEN", ACTIVE_TOKEN)
    }

    @After
    fun tearDown() {
        KVUtils.clear()
        PhoneCredentialVault.clear()
    }

    @Test
    fun current_apk_protected_routes_reject_missing_and_wrong_tokens_and_accept_active_token() {
        val routes = listOf(
            NanoHTTPD.Method.GET to "/api/channels",
            NanoHTTPD.Method.POST to "/api/channels",
            NanoHTTPD.Method.GET to "/api/llm",
            NanoHTTPD.Method.POST to "/api/llm",
            NanoHTTPD.Method.GET to "/api/debug/tools",
            NanoHTTPD.Method.POST to "/api/debug/execute",
            NanoHTTPD.Method.GET to "/api/debug/screen-full",
            NanoHTTPD.Method.GET to "/api/debug/file",
        )

        routes.forEach { (method, uri) ->
            assertEquals(NanoHTTPD.Response.Status.UNAUTHORIZED, server.serve(session(method, uri)).status)
            assertEquals(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                server.serve(session(method, uri, "wrong-token")).status,
            )
            assertNotEquals(
                NanoHTTPD.Response.Status.UNAUTHORIZED,
                server.serve(session(method, uri, ACTIVE_TOKEN)).status,
            )
        }
    }

    @Test
    fun current_apk_channels_and_llm_never_echo_short_or_long_non_empty_secrets() {
        listOf(
            "s3K",
            "very-long-secret-value-1234",
            "***",
            "********",
            "*********",
            "###",
            "########",
            "*abcd",
            "****1234",
        ).forEach { secret ->
            KVUtils.setDingtalkAppSecret(secret)
            KVUtils.setFeishuAppSecret(secret)
            KVUtils.setQqAppSecret(secret)
            KVUtils.setDiscordBotToken(secret)
            KVUtils.setTelegramBotToken(secret)
            KVUtils.setLlmApiKey(secret)

            val channels = body(
                server.serve(session(NanoHTTPD.Method.GET, "/api/channels", ACTIVE_TOKEN)),
            )
            val llm = body(
                server.serve(session(NanoHTTPD.Method.GET, "/api/llm", ACTIVE_TOKEN)),
            )
            assertFalse(channels.contains("\"replaceSecrets\""))
            assertFalse(llm.contains("\"replaceSecrets\""))
            val channelData = com.google.gson.JsonParser.parseString(channels)
                .asJsonObject["data"].asJsonObject
            listOf(
                "dingtalkAppSecret",
                "feishuAppSecret",
                "qqAppSecret",
                "discordBotToken",
                "telegramBotToken",
            ).forEach { field ->
                val masked = channelData[field].asString
                assertNotEquals("$field echoed the original secret", secret, masked)
                assertFalse("$field still contains the complete original secret", masked.contains(secret))
            }
            val llmMasked = com.google.gson.JsonParser.parseString(llm)
                .asJsonObject["data"].asJsonObject["llmApiKeyMasked"].asString
            assertNotEquals("llmApiKeyMasked echoed the original secret", secret, llmMasked)
            assertFalse("llmApiKeyMasked still contains the complete original secret", llmMasked.contains(secret))
        }
    }

    @Test
    fun current_apk_post_preserves_only_the_exact_mask_of_each_current_secret() {
        val currentSecrets = listOf(
            "ordinary-secret" to "********",
            "********" to "########",
            "########" to "********",
            "*abcd" to "********",
        )
        val postedValues = listOf("*abcd", "***", "********", "########")

        currentSecrets.forEach { (currentSecret, expectedMarker) ->
            KVUtils.setDingtalkAppSecret(currentSecret)
            KVUtils.setLlmApiKey(currentSecret)
            val channels = body(
                server.serve(session(NanoHTTPD.Method.GET, "/api/channels", ACTIVE_TOKEN)),
            )
            val channelMarker = com.google.gson.JsonParser.parseString(channels)
                .asJsonObject["data"].asJsonObject["dingtalkAppSecret"].asString
            val llm = body(
                server.serve(session(NanoHTTPD.Method.GET, "/api/llm", ACTIVE_TOKEN)),
            )
            val llmMarker = com.google.gson.JsonParser.parseString(llm)
                .asJsonObject["data"].asJsonObject["llmApiKeyMasked"].asString
            assertEquals(expectedMarker, channelMarker)
            assertEquals(expectedMarker, llmMarker)
            assertNotEquals(currentSecret, channelMarker)
            assertNotEquals(currentSecret, llmMarker)
            assertFalse(channelMarker.contains(currentSecret))
            assertFalse(llmMarker.contains(currentSecret))

            postedValues.forEach { postedValue ->
                KVUtils.setDingtalkAppSecret(currentSecret)
                KVUtils.setLlmApiKey(currentSecret)
                assertEquals(
                    NanoHTTPD.Response.Status.OK,
                    server.serve(
                        session(
                            NanoHTTPD.Method.POST,
                            "/api/channels",
                            ACTIVE_TOKEN,
                            rawBody = """{"dingtalkAppSecret":"$postedValue"}""",
                        ),
                    ).status,
                )
                assertEquals(
                    NanoHTTPD.Response.Status.OK,
                    server.serve(
                        session(
                            NanoHTTPD.Method.POST,
                            "/api/llm",
                            ACTIVE_TOKEN,
                            rawBody = """{"llmApiKey":"$postedValue"}""",
                        ),
                    ).status,
                )
                val expectedStored = if (postedValue == expectedMarker) currentSecret else postedValue
                assertEquals(expectedStored, KVUtils.getDingtalkAppSecret())
                assertEquals(expectedStored, KVUtils.getLlmApiKey())
            }
        }
    }

    @Test
    fun current_apk_explicit_replace_secrets_writes_literal_markers_for_all_six_fields() {
        data class ChannelSecret(
            val field: String,
            val set: (String) -> Unit,
            val get: () -> String,
        )
        val channels = listOf(
            ChannelSecret("dingtalkAppSecret", KVUtils::setDingtalkAppSecret, KVUtils::getDingtalkAppSecret),
            ChannelSecret("feishuAppSecret", KVUtils::setFeishuAppSecret, KVUtils::getFeishuAppSecret),
            ChannelSecret("qqAppSecret", KVUtils::setQqAppSecret, KVUtils::getQqAppSecret),
            ChannelSecret("discordBotToken", KVUtils::setDiscordBotToken, KVUtils::getDiscordBotToken),
            ChannelSecret("telegramBotToken", KVUtils::setTelegramBotToken, KVUtils::getTelegramBotToken),
        )
        listOf("********", "########").forEach { literalMarker ->
            channels.forEach { secret ->
                secret.set("ordinary-current")
                val response = server.serve(
                    session(
                        NanoHTTPD.Method.POST,
                        "/api/channels",
                        ACTIVE_TOKEN,
                        rawBody =
                            """{"replaceSecrets":["${secret.field}"],"${secret.field}":"$literalMarker"}""",
                    ),
                )
                assertEquals(NanoHTTPD.Response.Status.OK, response.status)
                assertEquals(literalMarker, secret.get())
            }

            KVUtils.setLlmApiKey("ordinary-current")
            val llmResponse = server.serve(
                session(
                    NanoHTTPD.Method.POST,
                    "/api/llm",
                    ACTIVE_TOKEN,
                    rawBody = """{"replaceSecrets":["llmApiKey"],"llmApiKey":"$literalMarker"}""",
                ),
            )
            assertEquals(NanoHTTPD.Response.Status.OK, llmResponse.status)
            assertEquals(literalMarker, KVUtils.getLlmApiKey())
        }
    }

    @Test
    fun current_apk_malformed_replace_secrets_is_atomic_and_route_local() {
        val channelBodies = listOf(
            """{"dingtalkAppKey":"changed","feishuAppSecret":{}}""",
            """{"replaceSecrets":"dingtalkAppSecret","dingtalkAppSecret":"new","dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":[1],"dingtalkAppSecret":"new","dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":["llmApiKey"],"llmApiKey":"new","dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":["dingtalkAppSecret"],"dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":["dingtalkAppSecret"],"dingtalkAppSecret":1,"dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":["dingtalkAppSecret","dingtalkAppSecret"],"dingtalkAppSecret":"new","dingtalkAppKey":"changed"}""",
            """{"replaceSecrets":["dingtalkAppSecret"],"dingtalkAppSecret":"new","feishuAppSecret":{},"dingtalkAppKey":"changed"}""",
        )
        channelBodies.forEach { rawBody ->
            KVUtils.setDingtalkAppKey("original-key")
            KVUtils.setDingtalkAppSecret("original-secret")
            val response = server.serve(
                session(NanoHTTPD.Method.POST, "/api/channels", ACTIVE_TOKEN, rawBody = rawBody),
            )
            assertEquals(NanoHTTPD.Response.Status.BAD_REQUEST, response.status)
            assertEquals("original-key", KVUtils.getDingtalkAppKey())
            assertEquals("original-secret", KVUtils.getDingtalkAppSecret())
        }

        val llmBodies = listOf(
            """{"llmApiKey":"changed","llmBaseUrl":{}}""",
            """{"replaceSecrets":{},"llmApiKey":"new","llmBaseUrl":"changed"}""",
            """{"replaceSecrets":[1],"llmApiKey":"new","llmBaseUrl":"changed"}""",
            """{"replaceSecrets":["dingtalkAppSecret"],"dingtalkAppSecret":"new","llmBaseUrl":"changed"}""",
            """{"replaceSecrets":["llmApiKey"],"llmBaseUrl":"changed"}""",
            """{"replaceSecrets":["llmApiKey"],"llmApiKey":1,"llmBaseUrl":"changed"}""",
            """{"replaceSecrets":["llmApiKey","llmApiKey"],"llmApiKey":"new","llmBaseUrl":"changed"}""",
        )
        llmBodies.forEach { rawBody ->
            KVUtils.setLlmApiKey("original-secret")
            KVUtils.setLlmBaseUrl("original-url")
            val response = server.serve(
                session(NanoHTTPD.Method.POST, "/api/llm", ACTIVE_TOKEN, rawBody = rawBody),
            )
            assertEquals(NanoHTTPD.Response.Status.BAD_REQUEST, response.status)
            assertEquals("original-secret", KVUtils.getLlmApiKey())
            assertEquals("original-url", KVUtils.getLlmBaseUrl())
        }
    }

    @Test
    fun current_apk_token_rotation_accepts_unexpired_previous_and_rejects_it_after_expiry() {
        check(KVUtils.setLumiLauncherId("old-launcher"))
        check(KVUtils.setLumiLauncherSecret("old-launcher-secret"))
        val validUntil = System.currentTimeMillis() + 60_000L
        KVUtils.promotePhonePairingCredentials(
            phoneToken = ROTATED_TOKEN,
            launcherId = "new-launcher",
            launcherName = "Route Security",
            launcherSecret = "new-launcher-secret",
            pairedAt = System.currentTimeMillis(),
            previousValidUntil = validUntil,
        )

        assertNotEquals(
            NanoHTTPD.Response.Status.UNAUTHORIZED,
            server.serve(session(NanoHTTPD.Method.GET, "/api/channels", ROTATED_TOKEN)).status,
        )
        assertNotEquals(
            NanoHTTPD.Response.Status.UNAUTHORIZED,
            server.serve(session(NanoHTTPD.Method.GET, "/api/channels", ACTIVE_TOKEN)).status,
        )
        KVUtils.clearExpiredPreviousPhoneCredentials(now = validUntil + 1L)
        assertEquals(
            NanoHTTPD.Response.Status.UNAUTHORIZED,
            server.serve(session(NanoHTTPD.Method.GET, "/api/channels", ACTIVE_TOKEN)).status,
        )
    }

    @Test
    fun current_apk_debug_file_allows_cache_regular_file_and_denies_escape_and_directory() {
        val regular = File(context.cacheDir, "route-security-regular.txt").apply { writeText("allowed") }
        val outside = File(context.cacheDir.parentFile, "route-security-outside.txt").apply {
            writeText("outside")
        }
        val traversal = File(context.cacheDir, "sub/../../${outside.name}")
        val directory = File(context.cacheDir, "route-security-directory").apply { mkdirs() }
        try {
            assertEquals(NanoHTTPD.Response.Status.OK, serveFile(regular).status)
            assertEquals(NanoHTTPD.Response.Status.NOT_FOUND, serveFile(outside).status)
            assertEquals(NanoHTTPD.Response.Status.NOT_FOUND, serveFile(traversal).status)
            assertEquals(NanoHTTPD.Response.Status.NOT_FOUND, serveFile(directory).status)
        } finally {
            regular.delete()
            outside.delete()
            directory.delete()
        }
    }

    @Test
    fun current_apk_debug_file_denies_cache_symlink_to_outside_target_when_supported() {
        val outside = File(context.cacheDir.parentFile, "route-security-symlink-target.txt").apply {
            writeText("outside")
        }
        val link = File(context.cacheDir, "route-security-outside-link.txt")
        try {
            link.delete()
            Os.symlink(outside.absolutePath, link.absolutePath)
            assertEquals(NanoHTTPD.Response.Status.NOT_FOUND, serveFile(link).status)
        } finally {
            link.delete()
            outside.delete()
        }
    }

    private fun serveFile(file: File): NanoHTTPD.Response = server.serve(
        session(
            method = NanoHTTPD.Method.GET,
            uri = "/api/debug/file",
            token = ACTIVE_TOKEN,
            parameters = mapOf("path" to listOf(file.path)),
        ),
    )

    private fun body(response: NanoHTTPD.Response): String = response.use {
        it.data.bufferedReader(Charsets.UTF_8).readText()
    }

    private fun session(
        method: NanoHTTPD.Method,
        uri: String,
        token: String? = null,
        parameters: Map<String, List<String>> = emptyMap(),
        rawBody: String = "",
    ): NanoHTTPD.IHTTPSession {
        val bytes = rawBody.toByteArray(Charsets.UTF_8)
        val headers = mutableMapOf<String, String>()
        token?.let { headers["x-agent-phone-token"] = it }
        return Proxy.newProxyInstance(
            NanoHTTPD.IHTTPSession::class.java.classLoader,
            arrayOf(NanoHTTPD.IHTTPSession::class.java),
        ) { _, reflectedMethod, arguments ->
            when (reflectedMethod.name) {
                "getHeaders" -> headers
                "getInputStream" -> ByteArrayInputStream(bytes)
                "getMethod" -> method
                "getUri" -> uri
                "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
                "getParms" -> parameters.mapValues { it.value.firstOrNull().orEmpty() }.toMutableMap()
                "getParameters" -> parameters.mapValues { it.value.toMutableList() }.toMutableMap()
                "getQueryParameterString" -> ""
                "parseBody" -> {
                    @Suppress("UNCHECKED_CAST")
                    (arguments?.firstOrNull() as? MutableMap<String, String>)?.set("postData", rawBody)
                    Unit
                }
                "execute" -> Unit
                else -> null
            }
        } as NanoHTTPD.IHTTPSession
    }

    private companion object {
        const val ACTIVE_TOKEN = "instrumented-route-security-token"
        const val ROTATED_TOKEN = "instrumented-route-security-token-rotated"
    }
}
