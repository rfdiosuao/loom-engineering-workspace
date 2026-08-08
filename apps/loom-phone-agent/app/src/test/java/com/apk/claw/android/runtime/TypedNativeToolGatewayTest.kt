package com.apk.claw.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class TypedNativeToolGatewayTest {
    private val scope = MobileRuntimeScope(
        accountId = "account-a",
        customerId = "customer-a",
        workspaceId = "workspace-a"
    )

    @Test
    fun `approved typed tool executes once and idempotent replay returns the same result`() {
        var calls = 0
        val audits = mutableListOf<NativeToolAuditRecord>()
        val gateway = TypedNativeToolGateway(
            registrations = listOf(
                NativeToolRegistration(
                    spec = NativeToolSpec(
                        capability = MobileRuntimeCapability.APP_OPEN,
                        arguments = mapOf(
                            "packageName" to NativeArgumentSpec(
                                type = NativeArgumentType.STRING,
                                required = true,
                                maxLength = 160
                            )
                        )
                    ),
                    executor = NativeToolExecutor { call ->
                        calls += 1
                        mapOf("opened" to true, "packageName" to call.arguments["packageName"])
                    }
                )
            ),
            clockMs = { 1_000L },
            auditSink = NativeToolAuditSink { audits += it }
        )
        val grant = MobileRuntimeGrant(
            scope = scope,
            allowedCapabilities = setOf(MobileRuntimeCapability.APP_OPEN),
            approvalId = "approval-a",
            expiresAtEpochMs = 2_000L
        )
        val request = NativeToolRequest(
            scope = scope,
            capability = MobileRuntimeCapability.APP_OPEN,
            approvalId = "approval-a",
            idempotencyKey = "idem-a",
            arguments = mapOf("packageName" to "com.example.safe")
        )

        val first = gateway.execute(request, grant)
        val replay = gateway.execute(request, grant)

        assertEquals(NativeToolStatus.SUCCEEDED, first.status)
        assertEquals(first.output, replay.output)
        assertFalse(first.replayed)
        assertTrue(replay.replayed)
        assertEquals(1, calls)
        assertEquals(2, audits.size)
        assertTrue(audits.all { it.scopeDigest.startsWith("sha256:") })
        assertTrue(audits.none { it.toString().contains("com.example.safe") })
    }

    @Test
    fun `concurrent duplicate idempotency keys serialize one native side effect`() {
        val calls = AtomicInteger(0)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val gateway = TypedNativeToolGateway(
            registrations = listOf(
                NativeToolRegistration(
                    spec = NativeToolSpec(MobileRuntimeCapability.SYSTEM_KEY, emptyMap()),
                    executor = NativeToolExecutor {
                        calls.incrementAndGet()
                        entered.countDown()
                        release.await(2, TimeUnit.SECONDS)
                        mapOf("sent" to true)
                    }
                )
            ),
            clockMs = { 1_000L }
        )
        val grant = MobileRuntimeGrant(
            scope,
            setOf(MobileRuntimeCapability.SYSTEM_KEY),
            "approval-key",
            2_000L
        )
        val request = NativeToolRequest(
            scope,
            MobileRuntimeCapability.SYSTEM_KEY,
            "approval-key",
            "idem-key",
            emptyMap()
        )
        val results = Collections.synchronizedList(mutableListOf<NativeToolResult>())
        val threads = List(2) {
            Thread { results += gateway.execute(request, grant) }.apply { start() }
        }
        assertTrue(entered.await(1, TimeUnit.SECONDS))
        release.countDown()
        threads.forEach { it.join(2_000) }

        assertEquals(1, calls.get())
        assertEquals(2, results.size)
        assertEquals(1, results.count { it.replayed })
    }

    @Test
    fun `scope expiry capability and argument schema fail closed before execution`() {
        var calls = 0
        val gateway = TypedNativeToolGateway(
            registrations = listOf(
                NativeToolRegistration(
                    spec = NativeToolSpec(
                        capability = MobileRuntimeCapability.WORKSPACE_WRITE,
                        arguments = mapOf(
                            "relativePath" to NativeArgumentSpec(NativeArgumentType.STRING, required = true, maxLength = 240),
                            "content" to NativeArgumentSpec(NativeArgumentType.STRING, required = true, maxLength = 4_096)
                        )
                    ),
                    executor = NativeToolExecutor { calls += 1; mapOf("written" to true) }
                )
            ),
            clockMs = { 5_000L }
        )
        val expired = MobileRuntimeGrant(
            scope = scope,
            allowedCapabilities = setOf(MobileRuntimeCapability.WORKSPACE_WRITE),
            approvalId = "approval-write",
            expiresAtEpochMs = 4_999L
        )
        val base = NativeToolRequest(
            scope = scope,
            capability = MobileRuntimeCapability.WORKSPACE_WRITE,
            approvalId = "approval-write",
            idempotencyKey = "idem-write",
            arguments = mapOf("relativePath" to "result.txt", "content" to "safe")
        )

        assertEquals("grant_expired", gateway.execute(base, expired).code)
        val wrongScope = expired.copy(
            scope = MobileRuntimeScope("account-b", "customer-a", "workspace-a"),
            expiresAtEpochMs = 6_000L
        )
        assertEquals("scope_mismatch", gateway.execute(base, wrongScope).code)
        val missingCapability = expired.copy(
            allowedCapabilities = setOf(MobileRuntimeCapability.SCREEN_OBSERVE),
            expiresAtEpochMs = 6_000L
        )
        assertEquals("capability_not_granted", gateway.execute(base, missingCapability).code)
        val valid = expired.copy(expiresAtEpochMs = 6_000L)
        assertEquals(
            "argument_not_declared",
            gateway.execute(base.copy(arguments = base.arguments + ("command" to "rm -rf")), valid).code
        )
        assertEquals(0, calls)
    }

    @Test
    fun `runtime selector deterministically falls back to healthy native backend`() {
        val selection = MobileRuntimeBackendSelector.select(
            capability = MobileRuntimeCapability.WORKSPACE_READ,
            preferredBackendId = "linux-optional",
            backends = listOf(
                MobileRuntimeBackendDescriptor(
                    id = "linux-optional",
                    kind = MobileRuntimeBackendKind.OPTIONAL_LINUX,
                    state = MobileRuntimeBackendState.UNHEALTHY,
                    capabilities = setOf(MobileRuntimeCapability.WORKSPACE_READ),
                    priority = 20
                ),
                MobileRuntimeBackendDescriptor(
                    id = "android-native",
                    kind = MobileRuntimeBackendKind.NATIVE,
                    state = MobileRuntimeBackendState.AVAILABLE,
                    capabilities = setOf(MobileRuntimeCapability.WORKSPACE_READ),
                    priority = 100
                )
            )
        )

        assertEquals("android-native", selection.selectedBackendId)
        assertTrue(selection.fallbackUsed)
        assertEquals("preferred_backend_unavailable", selection.reasonCode)
    }

    @Test
    fun `provider discovery exposes schema but enforces write only credentials`() {
        val schema = MobileProviderSchema(
            id = "openai-compatible",
            protocols = setOf("responses", "chat_completions"),
            fields = listOf(
                MobileProviderFieldSchema("baseUrl", MobileProviderFieldType.URL, required = true),
                MobileProviderFieldSchema(
                    "apiKey",
                    MobileProviderFieldType.SECRET,
                    required = true,
                    sensitive = true,
                    writeOnly = true
                )
            )
        )
        val discovered = MobileProviderSchemaRegistry(listOf(schema)).discover()

        assertEquals(listOf(schema), discovered)
        assertTrue(discovered.single().fields.single { it.id == "apiKey" }.writeOnly)
        try {
            MobileProviderSchema(
                id = "unsafe",
                protocols = setOf("chat_completions"),
                fields = listOf(
                    MobileProviderFieldSchema(
                        "apiKey",
                        MobileProviderFieldType.SECRET,
                        sensitive = true,
                        writeOnly = false
                    )
                )
            )
            fail("sensitive readable provider fields must be rejected")
        } catch (_: IllegalArgumentException) {
        }
    }

    @Test
    fun `provider probe failure rolls back staging and deletes newly written credential handles`() {
        val schema = MobileProviderSchema(
            id = "openai-compatible",
            protocols = setOf("responses"),
            fields = listOf(
                MobileProviderFieldSchema("baseUrl", MobileProviderFieldType.URL, required = true),
                MobileProviderFieldSchema(
                    "apiKey",
                    MobileProviderFieldType.SECRET,
                    required = true,
                    sensitive = true,
                    writeOnly = true
                )
            )
        )
        val deletedHandles = mutableListOf<String>()
        val vault = object : WriteOnlyProviderCredentialVault {
            override fun write(providerId: String, fieldId: String, value: CharArray): String {
                assertEquals("new-secret", value.concatToString())
                return "vault:$providerId.$fieldId.new-handle"
            }

            override fun delete(handle: String) {
                deletedHandles += handle
            }
        }
        var currentProvider = "old-provider"
        var rolledBack = false
        val store = object : MobileProviderConfigurationStore {
            override fun stage(configuration: MobileProviderConfiguration): String {
                assertEquals("old-provider", currentProvider)
                assertFalse(configuration.toString().contains("new-secret"))
                return "stage-provider-a"
            }

            override fun commit(stageId: String) {
                currentProvider = "provider-a"
            }

            override fun rollback(stageId: String) {
                rolledBack = true
            }
        }
        val coordinator = ProviderConfigurationCoordinator(
            schemas = MobileProviderSchemaRegistry(listOf(schema)),
            vault = vault,
            store = store,
            probe = MobileProviderCompatibilityProbe { false }
        )

        val result = coordinator.configure(
            providerId = "provider-a",
            schemaId = "openai-compatible",
            values = mapOf("baseUrl" to "https://relay.example.invalid/v1"),
            credentials = mapOf("apiKey" to "new-secret".toCharArray())
        )

        assertFalse(result.committed)
        assertEquals("provider_probe_failed", result.code)
        assertEquals("old-provider", currentProvider)
        assertTrue(rolledBack)
        assertEquals(listOf("vault:provider-a.apiKey.new-handle"), deletedHandles)
        assertFalse(result.toString().contains("new-secret"))
    }

    @Test
    fun `runtime trace removes credentials and bounds response text`() {
        val trace = MobileRuntimeTraceSanitizer.sanitize(
            headers = mapOf(
                "Authorization" to "Bearer top-secret",
                "x-api-key" to "api-secret",
                "Content-Type" to "application/json"
            ),
            responseBody = "x".repeat(80),
            maxResponseChars = 24
        )

        assertEquals("[redacted]", trace.headers["Authorization"])
        assertEquals("[redacted]", trace.headers["x-api-key"])
        assertEquals("application/json", trace.headers["Content-Type"])
        assertTrue(trace.responseExcerpt.length <= 24)
        assertTrue(trace.responseTruncated)
        assertFalse(trace.toString().contains("top-secret"))
        assertFalse(trace.toString().contains("api-secret"))
    }
}
