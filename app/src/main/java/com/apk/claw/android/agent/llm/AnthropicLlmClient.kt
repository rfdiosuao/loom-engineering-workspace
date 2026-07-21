package com.apk.claw.android.agent.llm

import com.apk.claw.android.agent.AgentConfig
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.langchain4j.agent.tool.ToolExecutionRequest
import dev.langchain4j.agent.tool.ToolSpecification
import dev.langchain4j.data.message.AiMessage
import dev.langchain4j.data.message.ChatMessage
import dev.langchain4j.data.message.SystemMessage
import dev.langchain4j.data.message.ToolExecutionResultMessage
import dev.langchain4j.data.message.UserMessage
import dev.langchain4j.model.chat.request.json.JsonArraySchema
import dev.langchain4j.model.chat.request.json.JsonBooleanSchema
import dev.langchain4j.model.chat.request.json.JsonEnumSchema
import dev.langchain4j.model.chat.request.json.JsonIntegerSchema
import dev.langchain4j.model.chat.request.json.JsonNumberSchema
import dev.langchain4j.model.chat.request.json.JsonObjectSchema
import dev.langchain4j.model.chat.request.json.JsonSchemaElement
import dev.langchain4j.model.chat.request.json.JsonStringSchema
import dev.langchain4j.model.output.TokenUsage
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class AnthropicLlmClient(
    private val config: AgentConfig
) : LlmClient {

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(300, TimeUnit.SECONDS)
        .writeTimeout(300, TimeUnit.SECONDS)
        .build()

    override fun chat(messages: List<ChatMessage>, toolSpecs: List<ToolSpecification>): LlmResponse {
        val body = buildRequestBody(messages, toolSpecs).toString()
        val request = Request.Builder()
            .url(messagesUrl())
            .addHeader("x-api-key", config.apiKey)
            .addHeader("anthropic-version", ANTHROPIC_VERSION)
            .addHeader("Content-Type", JSON_MEDIA_TYPE.toString())
            .post(body.toRequestBody(JSON_MEDIA_TYPE))
            .build()

        httpClient.newCall(request).execute().use { response ->
            val responseBody = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IOException("Anthropic HTTP ${response.code}: ${extractErrorMessage(responseBody)}")
            }
            if (responseBody.isBlank()) {
                throw IOException("Anthropic HTTP ${response.code}: empty response body")
            }
            return parseResponse(responseBody)
        }
    }

    override fun chatStreaming(
        messages: List<ChatMessage>,
        toolSpecs: List<ToolSpecification>,
        listener: StreamingListener
    ): LlmResponse {
        val response = chat(messages, toolSpecs)
        response.text?.takeIf { it.isNotEmpty() }?.let(listener::onPartialText)
        listener.onComplete(response)
        return response
    }

    internal fun buildRequestBody(messages: List<ChatMessage>, toolSpecs: List<ToolSpecification>): JsonObject {
        val systemParts = mutableListOf<String>()
        val anthropicMessages = JsonArray()
        messages.forEach { message ->
            when (message) {
                is SystemMessage -> systemParts += message.text()
                is UserMessage -> anthropicMessages.add(textMessage("user", userText(message)))
                is AiMessage -> anthropicMessages.add(assistantMessage(message))
                is ToolExecutionResultMessage -> anthropicMessages.add(toolResultMessage(message))
                else -> anthropicMessages.add(textMessage("user", message.toString()))
            }
        }

        return JsonObject().apply {
            addProperty("model", config.modelName)
            addProperty("max_tokens", DEFAULT_MAX_TOKENS)
            addProperty("temperature", config.temperature)
            if (systemParts.isNotEmpty()) addProperty("system", systemParts.joinToString("\n"))
            add("messages", anthropicMessages)
            if (toolSpecs.isNotEmpty()) add("tools", buildTools(toolSpecs))
        }
    }

    private fun textMessage(role: String, content: String): JsonObject {
        return JsonObject().apply {
            addProperty("role", role)
            addProperty("content", content)
        }
    }

    private fun userText(message: UserMessage): String {
        return if (message.hasSingleText()) {
            message.singleText()
        } else {
            message.contents().joinToString("\n") { it.toString() }
        }
    }

    private fun assistantMessage(message: AiMessage): JsonObject {
        val requests = message.toolExecutionRequests().orEmpty()
        if (requests.isEmpty()) {
            return textMessage("assistant", message.text().orEmpty())
        }

        val content = JsonArray()
        message.text()?.takeIf { it.isNotBlank() }?.let { text ->
            content.add(JsonObject().apply {
                addProperty("type", "text")
                addProperty("text", text)
            })
        }
        requests.forEach { request ->
            content.add(JsonObject().apply {
                addProperty("type", "tool_use")
                addProperty("id", request.id().ifNullOrBlank { newToolUseId() })
                addProperty("name", request.name().orEmpty())
                add("input", parseToolInput(request.arguments()))
            })
        }

        return JsonObject().apply {
            addProperty("role", "assistant")
            add("content", content)
        }
    }

    private fun toolResultMessage(message: ToolExecutionResultMessage): JsonObject {
        val content = JsonArray().apply {
            add(JsonObject().apply {
                addProperty("type", "tool_result")
                addProperty("tool_use_id", message.id())
                addProperty("content", message.text())
            })
        }
        return JsonObject().apply {
            addProperty("role", "user")
            add("content", content)
        }
    }

    private fun parseToolInput(arguments: String?): JsonObject {
        val text = arguments.orEmpty().ifBlank { "{}" }
        return runCatching { JsonParser.parseString(text) }
            .getOrNull()
            ?.takeIf { it.isJsonObject }
            ?.asJsonObject
            ?: JsonObject()
    }

    private fun buildTools(toolSpecs: List<ToolSpecification>): JsonArray {
        val tools = JsonArray()
        toolSpecs.forEach { spec ->
            tools.add(JsonObject().apply {
                addProperty("name", spec.name())
                addProperty("description", spec.description().orEmpty())
                add("input_schema", schemaToJson(spec.parameters()))
            })
        }
        return tools
    }

    private fun schemaToJson(schema: JsonSchemaElement?): JsonObject {
        val json = JsonObject()
        if (schema?.description().isNullOrBlank().not()) {
            json.addProperty("description", schema?.description())
        }

        when (schema) {
            is JsonObjectSchema -> {
                json.addProperty("type", "object")
                val properties = JsonObject()
                schema.properties().orEmpty().forEach { (name, child) ->
                    properties.add(name, schemaToJson(child))
                }
                json.add("properties", properties)
                if (!schema.required().isNullOrEmpty()) {
                    val required = JsonArray()
                    schema.required().forEach(required::add)
                    json.add("required", required)
                }
                schema.additionalProperties()?.let { json.addProperty("additionalProperties", it) }
                if (!schema.definitions().isNullOrEmpty()) {
                    val definitions = JsonObject()
                    schema.definitions().forEach { (name, child) ->
                        definitions.add(name, schemaToJson(child))
                    }
                    json.add("definitions", definitions)
                }
            }
            is JsonStringSchema -> json.addProperty("type", "string")
            is JsonIntegerSchema -> json.addProperty("type", "integer")
            is JsonNumberSchema -> json.addProperty("type", "number")
            is JsonBooleanSchema -> json.addProperty("type", "boolean")
            is JsonEnumSchema -> {
                json.addProperty("type", "string")
                val enumValues = JsonArray()
                schema.enumValues().orEmpty().forEach(enumValues::add)
                json.add("enum", enumValues)
            }
            is JsonArraySchema -> {
                json.addProperty("type", "array")
                json.add("items", schemaToJson(schema.items()))
            }
            else -> json.addProperty("type", "object")
        }
        return json
    }

    internal fun parseResponse(responseBody: String): LlmResponse {
        val root = JsonParser.parseString(responseBody).asJsonObject
        val texts = mutableListOf<String>()
        val toolRequests = mutableListOf<ToolExecutionRequest>()

        root.getAsJsonArrayOrNull("content")?.forEachIndexed { index, element ->
            if (!element.isJsonObject) return@forEachIndexed
            val item = element.asJsonObject
            when (item.stringOrNull("type")) {
                "text" -> item.stringOrNull("text")?.takeIf { it.isNotBlank() }?.let(texts::add)
                "tool_use" -> {
                    val name = item.stringOrNull("name").orEmpty()
                    if (name.isNotBlank()) {
                        toolRequests += ToolExecutionRequest.builder()
                            .id(item.stringOrNull("id").ifNullOrBlank { "toolu_${index}_${System.nanoTime()}" })
                            .name(name)
                            .arguments(item.get("input")?.takeUnless { it.isJsonNull }?.toString() ?: "{}")
                            .build()
                    }
                }
            }
        }

        return LlmResponse(
            text = texts.joinToString("\n").ifBlank { null },
            toolExecutionRequests = toolRequests,
            tokenUsage = parseTokenUsage(root.getAsJsonObjectOrNull("usage"))
        )
    }

    private fun parseTokenUsage(usage: JsonObject?): TokenUsage? {
        if (usage == null) return null
        val input = usage.intOrNull("input_tokens")
        val output = usage.intOrNull("output_tokens")
        val total = if (input != null || output != null) (input ?: 0) + (output ?: 0) else null
        return TokenUsage(input, output, total)
    }

    internal fun messagesUrl(): String {
        val baseUrl = config.baseUrl.trim().ifEmpty { DEFAULT_BASE_URL }.trimEnd('/')
        return when {
            baseUrl.endsWith("/v1/messages", ignoreCase = true) -> baseUrl
            baseUrl.endsWith("/v1", ignoreCase = true) -> "$baseUrl/messages"
            else -> "$baseUrl/v1/messages"
        }
    }

    private fun extractErrorMessage(body: String): String {
        if (body.isBlank()) return "empty error body"
        return try {
            JsonParser.parseString(body)
                .asJsonObject
                .getAsJsonObjectOrNull("error")
                ?.stringOrNull("message")
                ?: body.take(MAX_ERROR_BODY_CHARS)
        } catch (_: Exception) {
            body.take(MAX_ERROR_BODY_CHARS)
        }
    }

    private fun JsonObject.getAsJsonObjectOrNull(key: String): JsonObject? {
        return get(key)?.takeIf { it.isJsonObject }?.asJsonObject
    }

    private fun JsonObject.getAsJsonArrayOrNull(key: String): JsonArray? {
        return get(key)?.takeIf { it.isJsonArray }?.asJsonArray
    }

    private fun JsonObject.stringOrNull(key: String): String? {
        val value: JsonElement = get(key) ?: return null
        if (value.isJsonNull) return null
        return runCatching { value.asString }.getOrNull()
    }

    private fun JsonObject.intOrNull(key: String): Int? {
        val value: JsonElement = get(key) ?: return null
        if (value.isJsonNull) return null
        return runCatching { value.asInt }.getOrNull()
    }

    private fun String?.ifNullOrBlank(fallback: () -> String): String {
        return if (this.isNullOrBlank()) fallback() else this
    }

    private fun newToolUseId(): String = "toolu_${System.nanoTime()}"

    private companion object {
        private const val DEFAULT_BASE_URL = "https://api.anthropic.com"
        private const val ANTHROPIC_VERSION = "2023-06-01"
        private const val DEFAULT_MAX_TOKENS = 4096
        private const val MAX_ERROR_BODY_CHARS = 1000
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
