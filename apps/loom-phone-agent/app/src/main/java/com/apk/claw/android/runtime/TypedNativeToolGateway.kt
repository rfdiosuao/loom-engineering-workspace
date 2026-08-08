package com.apk.claw.android.runtime

import java.security.MessageDigest
import java.util.LinkedHashMap
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutionException

enum class NativeArgumentType {
    STRING,
    INTEGER,
    BOOLEAN,
    STRING_LIST
}

data class NativeArgumentSpec(
    val type: NativeArgumentType,
    val required: Boolean = false,
    val maxLength: Int = 1_024,
    val maxItems: Int = 64
) {
    init {
        require(maxLength in 1..65_536) { "Invalid argument length limit" }
        require(maxItems in 1..1_024) { "Invalid argument item limit" }
    }
}

data class NativeToolSpec(
    val capability: MobileRuntimeCapability,
    val arguments: Map<String, NativeArgumentSpec>
) {
    init {
        require(arguments.keys.all { SAFE_NATIVE_ARGUMENT.matches(it) }) { "Invalid native argument name" }
    }
}

data class NativeToolRequest(
    val scope: MobileRuntimeScope,
    val capability: MobileRuntimeCapability,
    val approvalId: String,
    val idempotencyKey: String,
    val arguments: Map<String, Any?>
)

data class AuthorizedNativeToolCall(
    val scope: MobileRuntimeScope,
    val capability: MobileRuntimeCapability,
    val idempotencyKey: String,
    val arguments: Map<String, Any?>
)

fun interface NativeToolExecutor {
    fun execute(call: AuthorizedNativeToolCall): Map<String, Any?>
}

data class NativeToolRegistration(
    val spec: NativeToolSpec,
    val executor: NativeToolExecutor
)

enum class NativeToolStatus {
    SUCCEEDED,
    DENIED,
    FAILED
}

data class NativeToolResult(
    val status: NativeToolStatus,
    val code: String,
    val output: Map<String, Any?> = emptyMap(),
    val replayed: Boolean = false,
    val retryable: Boolean = false
)

data class NativeToolAuditRecord(
    val capability: String,
    val status: String,
    val code: String,
    val durationMs: Long,
    val scopeDigest: String,
    val approvalDigest: String,
    val idempotencyDigest: String,
    val replayed: Boolean
)

fun interface NativeToolAuditSink {
    fun record(record: NativeToolAuditRecord)
}

class TypedNativeToolGateway(
    registrations: List<NativeToolRegistration>,
    private val clockMs: () -> Long = System::currentTimeMillis,
    private val auditSink: NativeToolAuditSink = NativeToolAuditSink { }
) {
    companion object {
        private const val MAX_IDEMPOTENCY_RECORDS = 256
    }

    private data class CachedResult(val inputDigest: String, val result: NativeToolResult)

    private val tools = registrations.associateBy { it.spec.capability }.also {
        require(it.size == registrations.size) { "Duplicate native capability registration" }
    }
    private val resultLock = Any()
    private val inFlight = ConcurrentHashMap<String, CompletableFuture<CachedResult>>()
    private val completed = object : LinkedHashMap<String, CachedResult>(MAX_IDEMPOTENCY_RECORDS + 1, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, CachedResult>?): Boolean =
            size > MAX_IDEMPOTENCY_RECORDS
    }

    fun execute(request: NativeToolRequest, grant: MobileRuntimeGrant): NativeToolResult {
        val startedAt = clockMs()
        val result = evaluate(request, grant)
        auditSink.record(
            NativeToolAuditRecord(
                capability = request.capability.toolId,
                status = result.status.name.lowercase(),
                code = result.code,
                durationMs = (clockMs() - startedAt).coerceAtLeast(0),
                scopeDigest = digest(request.scope.canonical()),
                approvalDigest = digest(request.approvalId),
                idempotencyDigest = digest(request.idempotencyKey),
                replayed = result.replayed
            )
        )
        return result
    }

    private fun evaluate(request: NativeToolRequest, grant: MobileRuntimeGrant): NativeToolResult {
        if (!grant.enabled) return denied("grant_disabled")
        if (request.scope != grant.scope) return denied("scope_mismatch")
        if (request.approvalId != grant.approvalId) return denied("approval_mismatch")
        if (grant.expiresAtEpochMs <= clockMs()) return denied("grant_expired")
        if (request.capability !in grant.allowedCapabilities) return denied("capability_not_granted")
        if (!SAFE_RUNTIME_TOKEN.matches(request.idempotencyKey)) return denied("idempotency_key_invalid")
        val registration = tools[request.capability] ?: return denied("capability_not_registered")
        validateArguments(request.arguments, registration.spec.arguments)?.let { return denied(it) }

        val cacheKey = digest("${request.scope.canonical()}\u0000${request.capability.toolId}\u0000${request.idempotencyKey}")
        val inputDigest = digest(canonicalArguments(request.arguments))
        synchronized(resultLock) {
            completed[cacheKey]?.let { cached ->
                if (cached.inputDigest != inputDigest) return denied("idempotency_conflict")
                return cached.result.copy(replayed = true)
            }
        }

        val ownerFuture = CompletableFuture<CachedResult>()
        val running = inFlight.putIfAbsent(cacheKey, ownerFuture)
        if (running != null) {
            val cached = try {
                running.get()
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return NativeToolResult(NativeToolStatus.FAILED, "native_tool_interrupted", retryable = false)
            } catch (_: ExecutionException) {
                return NativeToolResult(NativeToolStatus.FAILED, "native_tool_failed", retryable = false)
            }
            if (cached.inputDigest != inputDigest) return denied("idempotency_conflict")
            return cached.result.copy(replayed = true)
        }

        try {
            val result = try {
                val output = registration.executor.execute(
                    AuthorizedNativeToolCall(
                        scope = request.scope,
                        capability = request.capability,
                        idempotencyKey = request.idempotencyKey,
                        arguments = request.arguments.toMap()
                    )
                )
                NativeToolResult(NativeToolStatus.SUCCEEDED, "ok", output.toMap())
            } catch (_: Exception) {
                NativeToolResult(NativeToolStatus.FAILED, "native_tool_failed", retryable = false)
            }
            val cached = CachedResult(inputDigest, result)
            synchronized(resultLock) {
                completed[cacheKey] = cached
            }
            ownerFuture.complete(cached)
            return result
        } catch (fatal: Throwable) {
            ownerFuture.completeExceptionally(fatal)
            throw fatal
        } finally {
            inFlight.remove(cacheKey, ownerFuture)
        }
    }

    private fun validateArguments(
        values: Map<String, Any?>,
        schema: Map<String, NativeArgumentSpec>
    ): String? {
        if (values.keys.any { it !in schema }) return "argument_not_declared"
        if (schema.any { (key, spec) -> spec.required && key !in values }) return "argument_required"
        for ((key, value) in values) {
            val spec = schema.getValue(key)
            val valid = when (spec.type) {
                NativeArgumentType.STRING -> value is String && value.length <= spec.maxLength
                NativeArgumentType.INTEGER -> value is Byte || value is Short || value is Int || value is Long
                NativeArgumentType.BOOLEAN -> value is Boolean
                NativeArgumentType.STRING_LIST -> value is List<*> &&
                    value.size <= spec.maxItems &&
                    value.all { it is String && it.length <= spec.maxLength }
            }
            if (!valid) return "argument_type_invalid"
        }
        return null
    }

    private fun denied(code: String): NativeToolResult = NativeToolResult(NativeToolStatus.DENIED, code)
}

data class SafeMobileRuntimeTrace(
    val headers: Map<String, String>,
    val responseExcerpt: String,
    val responseTruncated: Boolean
)

object MobileRuntimeTraceSanitizer {
    private val secretHeaders = setOf(
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie"
    )

    fun sanitize(
        headers: Map<String, String>,
        responseBody: String,
        maxResponseChars: Int = 2_048
    ): SafeMobileRuntimeTrace {
        require(maxResponseChars in 1..16_384) { "Invalid trace response limit" }
        val safeHeaders = headers.mapValues { (name, value) ->
            if (name.lowercase() in secretHeaders) "[redacted]" else value.take(512)
        }
        return SafeMobileRuntimeTrace(
            headers = safeHeaders,
            responseExcerpt = responseBody.take(maxResponseChars),
            responseTruncated = responseBody.length > maxResponseChars
        )
    }
}

private val SAFE_NATIVE_ARGUMENT = Regex("^[A-Za-z][A-Za-z0-9_]{0,63}$")
private val SAFE_RUNTIME_TOKEN = Regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

private fun canonicalArguments(arguments: Map<String, Any?>): String = buildString {
    arguments.toSortedMap().forEach { (key, item) ->
        append(key.length).append(':').append(key)
        when (item) {
            null -> append("=n;")
            is String -> append("=s").append(item.length).append(':').append(item).append(';')
            is Boolean -> append("=b").append(if (item) '1' else '0').append(';')
            is Number -> {
                val value = item.toString()
                append("=i").append(value.length).append(':').append(value).append(';')
            }
            is List<*> -> {
                append("=l").append(item.size).append(':')
                item.forEach { element ->
                    val value = element.toString()
                    append(value.length).append(':').append(value)
                }
                append(';')
            }
            else -> append("=u;")
        }
    }
}

private fun digest(value: String): String {
    val bytes = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
    return "sha256:" + bytes.joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
