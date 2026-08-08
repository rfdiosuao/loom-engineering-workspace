package com.apk.claw.android.server

import android.content.ContextWrapper
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.File
import java.lang.reflect.Field
import java.lang.reflect.Proxy
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import sun.misc.Unsafe

class ConfigServerSecurityTest {
    @Test
    fun protected_routes_bind_to_phone_token_gate_and_token_contract_covers_active_previous_and_expired() {
        val source = configServerSource()
        val protectedRoutes = listOf(
            "uri == \"/api/channels\" && method == Method.GET -> withPhoneToken(session)",
            "uri == \"/api/channels\" && method == Method.POST -> withPhoneToken(session)",
            "uri == \"/api/llm\" && method == Method.GET -> withPhoneToken(session)",
            "uri == \"/api/llm\" && method == Method.POST -> withPhoneToken(session)",
            "uri == \"/api/debug/tools\" && method == Method.GET && BuildConfig.DEBUG -> withPhoneToken(session)",
            "uri == \"/api/debug/execute\" && method == Method.POST && BuildConfig.DEBUG -> withPhoneToken(session)",
            "uri == \"/api/debug/screen-full\" && method == Method.GET && BuildConfig.DEBUG -> withPhoneToken(session)",
            "uri.startsWith(\"/api/debug/file\") && method == Method.GET && BuildConfig.DEBUG -> withPhoneToken(session)",
        )

        protectedRoutes.forEach { binding ->
            assertTrue("route is not bound to withPhoneToken: $binding", source.contains(binding))
        }
        assertFalse("anonymous token must fail", TokenValidator.matchesPresentedToken("", ACTIVE_TOKEN))
        assertFalse("wrong token must fail", TokenValidator.matchesPresentedToken("wrong-token", ACTIVE_TOKEN))
        assertTrue("active token must pass", TokenValidator.matchesPresentedToken(ACTIVE_TOKEN, ACTIVE_TOKEN))
        assertTrue(
            "unexpired previous token must pass migration contract",
            TokenValidator.matchesPresentedToken(PREVIOUS_TOKEN, ACTIVE_TOKEN, PREVIOUS_TOKEN),
        )
        assertFalse(
            "expired previous token must be removed before matching",
            TokenValidator.matchesPresentedToken(PREVIOUS_TOKEN, ACTIVE_TOKEN, previousToken = ""),
        )

        val validator = File("src/main/java/com/apk/claw/android/server/TokenValidator.kt").readText()
        assertTrue(validator.contains("KVUtils.clearExpiredPreviousPhoneCredentials()"))
        assertTrue(validator.contains("KVUtils.getPreviousPhoneCredentialValidUntil() > System.currentTimeMillis()"))
    }

    @Test
    fun every_non_empty_secret_maps_to_a_distinct_redacted_value() {
        val server = allocateConfigServerWithoutAndroidRuntime()
        val candidates = listOf(
            "",
            "a",
            "ab",
            "abc",
            "abcd",
            "very-long-secret-value-1234",
            "***",
            "********",
            "*********",
            "###",
            "########",
            "*abcd",
            "****1234",
        )
        candidates.forEach { secret ->
            val masked = invokeMaskSecret(server, secret)
            if (secret.isEmpty()) {
                assertEquals("", masked)
            } else {
                assertNotEquals("secret '$secret' was returned verbatim", secret, masked)
                assertFalse("masked value '$masked' still contains secret '$secret'", masked.contains(secret))
                assertTrue(
                    "mask must remain recognizable as redacted",
                    masked.all { it == '*' || it == '#' },
                )
            }
        }
    }

    @Test
    fun only_the_exact_mask_of_the_current_secret_is_preserved() {
        val server = allocateConfigServerWithoutAndroidRuntime()
        val cases = listOf(
            Triple("ordinary-secret", "********", true),
            Triple("ordinary-secret", "########", false),
            Triple("ordinary-secret", "*abcd", false),
            Triple("ordinary-secret", "***", false),
            Triple("********", "########", true),
            Triple("********", "********", false),
            Triple("********", "*abcd", false),
            Triple("********", "***", false),
            Triple("########", "********", true),
            Triple("########", "########", false),
            Triple("########", "*abcd", false),
            Triple("########", "***", false),
            Triple("*abcd", "********", true),
            Triple("*abcd", "########", false),
            Triple("*abcd", "*abcd", false),
            Triple("*abcd", "***", false),
        )
        cases.forEach { (currentSecret, postedValue, expectedPreserve) ->
            assertEquals(
                "current='$currentSecret' posted='$postedValue'",
                expectedPreserve,
                invokeIsMaskedValue(server, postedValue, currentSecret),
            )
        }
    }

    @Test
    fun every_secret_post_field_compares_against_its_corresponding_current_value() {
        val source = configServerSource()
        listOf(
            "KVUtils.getDingtalkAppSecret()",
            "KVUtils.getFeishuAppSecret()",
            "KVUtils.getQqAppSecret()",
            "KVUtils.getDiscordBotToken()",
            "KVUtils.getTelegramBotToken()",
            "KVUtils.getLlmApiKey()",
        ).forEach { currentGetter ->
            assertTrue(
                "$currentGetter is not bound to contextual marker validation",
                source.contains("if (!isMaskedValue(value, $currentGetter))"),
            )
        }
    }

    @Test
    fun release_contract_keeps_every_debug_route_behind_build_config_debug() {
        val source = configServerSource()
        listOf(
            "\"/debug.html\"",
            "\"/api/debug/tools\"",
            "\"/api/debug/execute\"",
            "\"/api/debug/screen-full\"",
            "\"/api/debug/file\"",
        ).forEach { route ->
            val line = source.lineSequence().single { it.contains(route) }
            assertTrue("$route is not release-gated", line.contains("BuildConfig.DEBUG"))
        }
    }

    @Test
    fun debug_file_handler_rejects_explicit_traversal_and_non_regular_file() {
        val cacheDir = Files.createTempDirectory("config-server-cache").toFile()
        val outside = File(cacheDir.parentFile, "config-server-outside-${System.nanoTime()}.txt").apply {
            writeText("outside")
        }
        val traversal = File(cacheDir, "sub/../../${outside.name}")
        val directory = File(cacheDir, "not-a-regular-file").apply { mkdirs() }
        val server = configServerWithCacheDir(cacheDir)
        try {
            assertFileDenied(server, traversal)
            assertFileDenied(server, directory)
        } finally {
            outside.delete()
            directory.delete()
            cacheDir.delete()
        }
    }

    @Test
    fun debug_file_source_contract_canonicalizes_symlink_targets_before_containment_check() {
        val handler = configServerSource()
            .substringAfter("private fun handleServeFile")
            .substringBefore("private fun maskSecret")

        val canonicalization = handler.indexOf("java.io.File(path).canonicalFile")
        val containment = handler.indexOf("file.toPath().startsWith(cacheDir.toPath())")
        assertTrue("requested path must be canonicalized", canonicalization >= 0)
        assertTrue("canonicalization must precede containment", containment > canonicalization)
    }

    private fun invokeMaskSecret(server: ConfigServer, secret: String): String {
        val method = ConfigServer::class.java.getDeclaredMethod("maskSecret", String::class.java)
        method.isAccessible = true
        return method.invoke(server, secret) as String
    }

    private fun invokeIsMaskedValue(server: ConfigServer, value: String, currentSecret: String): Boolean {
        val method = try {
            ConfigServer::class.java.getDeclaredMethod(
                "isMaskedValue",
                String::class.java,
                String::class.java,
            )
        } catch (_: NoSuchMethodException) {
            fail("isMaskedValue must compare the posted value with the mask of the current stored secret")
            throw AssertionError("unreachable")
        }
        method.isAccessible = true
        return method.invoke(server, value, currentSecret) as Boolean
    }

    private fun allocateConfigServerWithoutAndroidRuntime(): ConfigServer {
        return unsafe().allocateInstance(ConfigServer::class.java) as ConfigServer
    }

    private fun configServerWithCacheDir(cacheDir: File): ConfigServer {
        val context = unsafe().allocateInstance(CacheDirContext::class.java) as CacheDirContext
        CacheDirContext::class.java.getDeclaredField("root").apply {
            isAccessible = true
            set(context, cacheDir)
        }
        return allocateConfigServerWithoutAndroidRuntime().also { server ->
            ConfigServer::class.java.getDeclaredField("context").apply {
                isAccessible = true
                set(server, context)
            }
        }
    }

    private fun assertFileDenied(server: ConfigServer, file: File) {
        val method = ConfigServer::class.java.getDeclaredMethod(
            "handleServeFile",
            NanoHTTPD.IHTTPSession::class.java,
        )
        method.isAccessible = true
        val response = method.invoke(server, fileSession(file)) as NanoHTTPD.Response
        assertEquals(NanoHTTPD.Response.Status.NOT_FOUND, response.status)
        val body = response.use { it.data.bufferedReader(Charsets.UTF_8).readText() }
        assertFalse("denial response leaked the requested path", body.contains(file.path))
    }

    private fun fileSession(file: File): NanoHTTPD.IHTTPSession = Proxy.newProxyInstance(
        NanoHTTPD.IHTTPSession::class.java.classLoader,
        arrayOf(NanoHTTPD.IHTTPSession::class.java),
    ) { _, method, _ ->
        when (method.name) {
            "getHeaders" -> mutableMapOf<String, String>()
            "getInputStream" -> ByteArrayInputStream(ByteArray(0))
            "getMethod" -> NanoHTTPD.Method.GET
            "getUri" -> "/api/debug/file"
            "getRemoteIpAddress", "getRemoteHostName" -> "127.0.0.1"
            "getParms" -> mutableMapOf("path" to file.path)
            "getParameters" -> mutableMapOf("path" to mutableListOf(file.path))
            "getQueryParameterString" -> "path=${file.path}"
            "execute" -> Unit
            else -> null
        }
    } as NanoHTTPD.IHTTPSession

    private fun unsafe(): Unsafe {
        val unsafeField: Field = Unsafe::class.java.getDeclaredField("theUnsafe")
        unsafeField.isAccessible = true
        return unsafeField.get(null) as Unsafe
    }

    private fun configServerSource(): String =
        File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()

    private companion object {
        const val ACTIVE_TOKEN = "route-security-contract-token"
        const val PREVIOUS_TOKEN = "route-security-previous-token"
    }

    private class CacheDirContext private constructor() : ContextWrapper(null) {
        private lateinit var root: File

        override fun getCacheDir(): File = root
    }
}
