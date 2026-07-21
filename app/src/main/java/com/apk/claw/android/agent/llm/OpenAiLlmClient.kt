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
import java.util.UUID
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class OpenAiLlmClient(
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
            .url(chatCompletionsUrl())
            .addHeader("Authorization", "Bearer ${config.apiKey}")
            .addHeader("Content-Type", JSON_MEDIA_TYPE.toString())
            .post(body.toRequestBody(JSON_MEDIA_TYPE))
            .build()

        httpClient.newCall(request).execute().use { response ->
            val responseBody = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IOException("LLM HTTP ${response.code}: ${extractErrorMessage(responseBody)}")
            }
            if (responseBody.isBlank()) {
                throw IOException("LLM HTTP ${response.code}: empty response body")
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
        return JsonObject().apply {
            addProperty("model", config.modelName)
            addProperty("temperature", config.temperature)
            addProperty("stream", false)
            add("messages", buildMessages(messages))
            if (toolSpecs.isNotEmpty()) {
                add("tools", buildTools(toolSpecs))
                addProperty("tool_choice", "auto")
            }
        }
    }

    private fun buildMessages(messages: List<ChatMessage>): JsonArray {
        val array = JsonArray()
        messages.forEach { message ->
            array.add(
                when (message) {
                    is SystemMessage -> textMessage("system", message.text())
                    is UserMessage -> textMessage("user", userText(message))
                    is AiMessage -> assistantMessage(message)
                    is ToolExecutionResultMessage -> toolResultMessage(message)
                    else -> textMessage("user", message.toString())
                }
            )
        }
        return array
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
        return JsonObject().apply {
            addProperty("role", "assistant")
            val text = message.text()
            if (text == null) {
                add("content", JsonNull.INSTANCE)
            } else {
                addProperty("content", text)
            }
            val requests = message.toolExecutionRequests().orEmpty()
            if (requests.isNotEmpty()) {
                val calls = JsonArray()
                requests.forEach { request ->
                    calls.add(JsonObject().apply {
                        addProperty("id", request.id().ifNullOrBlank { newToolCallId() })
                        addProperty("type", "function")
                        add("function", JsonObject().apply {
                            addProperty("name", request.name().orEmpty())
                            addProperty("arguments", request.arguments().ifNullOrBlank { "{}" })
                        })
                    })
                }
                add("tool_calls", calls)
            }
        }
    }

    private fun toolResultMessage(message: ToolExecutionResultMessage): JsonObject {
        return JsonObject().apply {
            addProperty("role", "tool")
            addProperty("tool_call_id", message.id())
            addProperty("name", message.toolName())
            addProperty("content", message.text())
        }
    }

    private fun buildTools(toolSpecs: List<ToolSpecification>): JsonArray {
        val tools = JsonArray()
        toolSpecs.forEach { spec ->
            tools.add(JsonObject().apply {
                addProperty("type", "function")
                add("function", JsonObject().apply {
                    addProperty("name", spec.name())
                    addProperty("description", spec.description().orEmpty())
                    add("parameters", schemaToJson(spec.parameters()))
                })
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
            else -> json.addProperty("type", "string")
        }
        return json
    }

    internal fun parseResponse(responseBody: String): LlmResponse {
        val root = JsonParser.parseString(responseBody).asJsonObject
        val choice = root.getAsJsonArray("choices")
            ?.firstOrNull()
            ?.takeIf { it.isJsonObject }
            ?.asJsonObject
            ?: throw IOException("LLM response has no choices")
        val message = choice.getAsJsonObjectOrNull("message")
        val text = message?.stringOrNull("content") ?: choice.stringOrNull("text")
        val toolRequests = parseToolCalls(message)
        val usage = parseTokenUsage(root.getAsJsonObjectOrNull("usage"))
        return LlmResponse(text, toolRequests, usage)
    }

    private fun parseToolCalls(message: JsonObject?): List<ToolExecutionRequest> {
        if (message == null) return emptyList()
        val calls = mutableListOf<ToolExecutionRequest>()
        message.getAsJsonArrayOrNull("tool_calls")?.forEachIndexed { index, element ->
            if (!element.isJsonObject) return@forEachIndexed
            val call = element.asJsonObject
            val function = call.getAsJsonObjectOrNull("function") ?: return@forEachIndexed
            val name = function.stringOrNull("name").orEmpty()
            if (name.isBlank()) return@forEachIndexed
            calls += ToolExecutionRequest.builder()
                .id(call.stringOrNull("id").ifNullOrBlank { "call_${index}_${UUID.randomUUID()}" })
                .name(name)
                .arguments(function.stringOrNull("arguments").ifNullOrBlank { "{}" })
                .build()
        }

        if (calls.isEmpty()) {
            message.getAsJsonObjectOrNull("function_call")?.let { function ->
                val name = function.stringOrNull("name").orEmpty()
                if (name.isNotBlank()) {
                    calls += ToolExecutionRequest.builder()
                        .id(newToolCallId())
                        .name(name)
                        .arguments(function.stringOrNull("arguments").ifNullOrBlank { "{}" })
                        .build()
                }
            }
        }
        return calls
    }

    private fun parseTokenUsage(usage: JsonObject?): TokenUsage? {
        if (usage == null) return null
        return TokenUsage(
            usage.intOrNull("prompt_tokens"),
            usage.intOrNull("completion_tokens"),
            usage.intOrNull("total_tokens")
        )
    }

    internal fun chatCompletionsUrl(): String {
        val baseUrl = config.baseUrl.trim().ifEmpty { DEFAULT_BASE_URL }.trimEnd('/')
        return if (baseUrl.endsWith("/chat/completions", ignoreCase = true)) {
            baseUrl
        } else {
            "$baseUrl/chat/completions"
        }
    }

    private fun extractErrorMessage(body: String): String {
        if (body.isBlank()) return "empty error body"
        return try {
            JsonParser.parseString(body)
                .asJsonObject
                .getAsJsonObjectOrNull("error")
                ?.stringOrNull("message")
                ?.takeIf { it.isNotBlank() }
                ?: body.take(MAX_ERROR_BODY_CHARS)
        } catch (_: Exception) {
            body.take(MAX_ERROR_BODY_CHARS)
        }
    }

    private fun newToolCallId(): String = "call_${UUID.randomUUID()}"

    private fun String?.ifNullOrBlank(fallback: () -> String): String {
        return if (this.isNullOrBlank()) fallback() else this
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

    private companion object {
        private const val DEFAULT_BASE_URL = "https://api.openai.com/v1"
        private const val MAX_ERROR_BODY_CHARS = 1000
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
