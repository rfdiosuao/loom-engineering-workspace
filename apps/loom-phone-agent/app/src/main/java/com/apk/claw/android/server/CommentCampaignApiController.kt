package com.apk.claw.android.server

import com.apk.claw.android.comment.CommentCampaign
import com.apk.claw.android.comment.CommentCampaignCoordinator
import com.apk.claw.android.comment.CommentCampaignRunResult
import com.apk.claw.android.comment.CommentManifest
import com.apk.claw.android.comment.CommentManifestAuthorizer
import com.apk.claw.android.comment.CommentManifestItem
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import fi.iki.elonen.NanoHTTPD

object CommentCampaignApiController {
    @Volatile
    private var testCoordinator: CommentCampaignCoordinator? = null

    fun installCoordinatorForTests(coordinator: CommentCampaignCoordinator?) {
        testCoordinator = coordinator
    }

    fun handlePrepare(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response = handleJson(session, requireToken, "prepare") { json, startedAt ->
        val manifest = parseManifest(json)
        val campaign = coordinator().prepare(manifest)
        response(
            NanoHTTPD.Response.Status.OK,
            success = true,
            data = campaignData(campaign, elapsedMs(startedAt), currentStep = "awaiting_confirmation"),
            error = null
        )
    }

    fun handleConfirm(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response = handleJson(session, requireToken, "confirm") { json, startedAt ->
        val campaignId = requiredString(json, "campaignId")
        val manifestHash = requiredString(json, "manifestHash")
        val itemHashes = json.getAsJsonArray("itemHashes")
            ?.map { it.asString }
        val campaign = coordinator().confirm(campaignId, manifestHash, itemHashes)
        response(
            NanoHTTPD.Response.Status.OK,
            success = true,
            data = campaignData(campaign, elapsedMs(startedAt), currentStep = "confirmed"),
            error = null
        )
    }

    fun handleStatus(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response = handleJson(session, requireToken, "status") { json, startedAt ->
        val campaignId = requiredString(json, "campaignId")
        val campaign = coordinator().snapshot(campaignId)
            ?: return@handleJson failureResponse(
                "campaign_not_found",
                "Comment campaign was not found",
                "status",
                retryable = false,
                startedAt = startedAt
            )
        response(
            NanoHTTPD.Response.Status.OK,
            success = true,
            data = campaignData(campaign, elapsedMs(startedAt)),
            error = null
        )
    }

    fun handleCancel(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response = handleJson(session, requireToken, "cancel") { json, startedAt ->
        val result = coordinator().cancel(requiredString(json, "campaignId"))
        runResultResponse(result, startedAt)
    }

    fun handleResume(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean = true
    ): NanoHTTPD.Response = handleJson(session, requireToken, "resume") { json, startedAt ->
        val result = coordinator().resume(requiredString(json, "campaignId"))
        runResultResponse(result, startedAt)
    }

    private inline fun handleJson(
        session: NanoHTTPD.IHTTPSession,
        requireToken: Boolean,
        step: String,
        block: (JsonObject, Long) -> NanoHTTPD.Response
    ): NanoHTTPD.Response {
        val startedAt = System.nanoTime()
        if (requireToken && !TokenValidator.validate(session)) {
            return failureResponse(
                "unauthorized",
                "Unauthorized: invalid or missing token",
                step,
                retryable = false,
                startedAt = startedAt,
                status = NanoHTTPD.Response.Status.UNAUTHORIZED
            )
        }
        val rawBody = ToolApiController.readJsonBodyUtf8(session)
        if (rawBody.isBlank()) {
            return failureResponse("invalid_json", "JSON body is required", step, false, startedAt)
        }
        return try {
            val element = JsonParser.parseString(rawBody)
            if (!element.isJsonObject) throw IllegalArgumentException("invalid_json")
            block(element.asJsonObject, startedAt)
        } catch (error: Exception) {
            val code = errorCode(error)
            failureResponse(
                code,
                errorMessage(code),
                stepForError(step, code),
                retryable = code in RETRYABLE_ERRORS,
                startedAt = startedAt,
                campaign = campaignFromRequest(rawBody)
            )
        }
    }

    private fun runResultResponse(
        result: CommentCampaignRunResult,
        startedAt: Long
    ): NanoHTTPD.Response {
        val data = if (result.campaign != null) {
            campaignData(
                result.campaign,
                elapsedMs(startedAt),
                errorCode = result.errorCode,
                message = result.message,
                retryable = result.retryable,
                evidence = result.evidence
            )
        } else {
            baseData(
                success = false,
                errorCode = result.errorCode,
                message = result.message,
                currentStep = "precheck",
                retryable = result.retryable,
                totalMs = elapsedMs(startedAt)
            )
        }
        return response(
            NanoHTTPD.Response.Status.OK,
            result.success,
            data,
            result.message.takeIf { !result.success }
        )
    }

    private fun parseManifest(json: JsonObject): CommentManifest {
        val commentText = requiredString(json, "commentText")
        val itemsJson = json.getAsJsonArray("items") ?: throw IllegalArgumentException("items_required")
        val items = itemsJson.mapIndexed { index, element ->
            if (!element.isJsonObject) throw IllegalArgumentException("invalid_comment_item")
            val item = element.asJsonObject
            CommentManifestItem(
                itemId = optionalString(item, "itemId").ifBlank { "item-${index + 1}" },
                creatorId = requiredString(item, "creatorId"),
                creatorLabel = optionalString(item, "creatorLabel"),
                videoId = requiredString(item, "videoId"),
                videoLabel = optionalString(item, "videoLabel"),
                commentText = optionalString(item, "commentText").ifBlank { commentText }
            )
        }
        return CommentManifest(
            campaignId = requiredString(json, "campaignId"),
            platform = optionalString(json, "platform").ifBlank { "xiaohongshu" },
            accountId = requiredString(json, "accountId"),
            query = optionalString(json, "query"),
            targetCount = optionalInt(json, "targetCount") ?: items.size,
            commentText = commentText,
            items = items,
            createdAt = System.currentTimeMillis(),
            confirmationMode = optionalString(json, "safetyLevel")
                .ifBlank { optionalString(json, "confirmationMode") }
                .ifBlank { CommentManifestAuthorizer.MODE_WEAK }
        )
    }

    private fun campaignData(
        campaign: CommentCampaign,
        totalMs: Long,
        currentStep: String = campaign.state.name.lowercase(),
        errorCode: String = campaign.errorCode,
        message: String = campaign.message,
        retryable: Boolean = false,
        evidence: List<String> = emptyList()
    ): JsonObject = baseData(
        success = errorCode.isBlank(),
        errorCode = errorCode,
        message = message,
        currentStep = currentStep,
        retryable = retryable,
        totalMs = totalMs
    ).apply {
        addProperty("schema", "apkclaw.comment-campaign.v1")
        addProperty("campaignId", campaign.campaignId)
        addProperty("state", campaign.state.name.lowercase())
        addProperty("manifestHash", campaign.manifestHash)
        addProperty("safetyLevel", campaign.confirmationMode ?: CommentManifestAuthorizer.MODE_STRICT)
        addProperty("confirmationMode", campaign.confirmationMode ?: CommentManifestAuthorizer.MODE_STRICT)
        add("itemHashes", JsonArray().apply { campaign.items.forEach { add(it.itemHash) } })
        addProperty("targetCount", campaign.targetCount)
        addProperty("currentTargetIndex", campaign.currentTargetIndex)
        addProperty("completedCount", campaign.items.count { it.state.name == "SENT_VERIFIED" })
        addProperty("failedCount", campaign.items.count { it.state.name == "FAILED" })
        campaign.items.getOrNull(campaign.currentTargetIndex)?.let { item ->
            addProperty("currentTargetId", item.itemId)
            addProperty("currentTargetState", item.state.name.lowercase())
        }
        add("evidence", JsonArray().apply { evidence.forEach(::add) })
    }

    private fun baseData(
        success: Boolean,
        errorCode: String,
        message: String,
        currentStep: String,
        retryable: Boolean,
        totalMs: Long
    ): JsonObject = JsonObject().apply {
        addProperty("success", success)
        addProperty("errorCode", errorCode)
        addProperty("message", message)
        addProperty("currentStep", currentStep)
        addProperty("retryable", retryable)
        addProperty("totalMs", totalMs)
        addProperty("screenTreeMs", 0L)
        addProperty("llmRoundMs", 0L)
        addProperty("toolCallMs", 0L)
        addProperty("rounds", 0)
        addProperty("mode", "comment_campaign")
    }

    private fun failureResponse(
        errorCode: String,
        message: String,
        currentStep: String,
        retryable: Boolean,
        startedAt: Long,
        campaign: CommentCampaign? = null,
        status: NanoHTTPD.Response.IStatus = NanoHTTPD.Response.Status.OK
    ): NanoHTTPD.Response {
        val data = if (campaign == null) {
            baseData(false, errorCode, message, currentStep, retryable, elapsedMs(startedAt))
        } else {
            campaignData(campaign, elapsedMs(startedAt), currentStep, errorCode, message, retryable)
        }
        return response(status, false, data, message)
    }

    private fun coordinator(): CommentCampaignCoordinator =
        testCoordinator ?: CommentCampaignRuntime.coordinator()

    private fun campaignFromRequest(rawBody: String): CommentCampaign? {
        val id = runCatching {
            JsonParser.parseString(rawBody).asJsonObject.get("campaignId")?.asString
        }.getOrNull()?.takeIf { it.isNotBlank() } ?: return null
        return runCatching { coordinator().snapshot(id) }.getOrNull()
    }

    private fun requiredString(json: JsonObject, name: String): String =
        optionalString(json, name).takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("${camelToSnake(name)}_required")

    private fun optionalString(json: JsonObject, name: String): String = runCatching {
        json.get(name)?.takeUnless { it.isJsonNull }?.asString?.trim().orEmpty()
    }.getOrDefault("")

    private fun optionalInt(json: JsonObject, name: String): Int? = runCatching {
        json.get(name)?.takeUnless { it.isJsonNull }?.asInt
    }.getOrNull()

    private fun errorCode(error: Exception): String {
        val raw = error.message.orEmpty().trim()
        return when {
            raw.startsWith("confirmation_must_cover_exact_manifest") -> "confirmation_mismatch"
            raw in KNOWN_ERRORS -> raw
            raw.contains("Expected", ignoreCase = true) || raw.contains("json", ignoreCase = true) -> "invalid_json"
            else -> "invalid_comment_campaign"
        }
    }

    private fun errorMessage(errorCode: String): String = when (errorCode) {
        "manifest_changed" -> "Manifest hash does not match the prepared campaign"
        "confirmation_mismatch", "confirmation_must_cover_exact_manifest" ->
            "Confirmation must include every exact prepared item hash"
        "campaign_not_found" -> "Comment campaign was not found"
        "invalid_json" -> "Invalid JSON body"
        else -> "Invalid comment campaign request: $errorCode"
    }

    private fun stepForError(defaultStep: String, errorCode: String): String = when (errorCode) {
        "manifest_changed", "confirmation_mismatch", "confirmation_must_cover_exact_manifest" ->
            "awaiting_confirmation"
        else -> defaultStep
    }

    private fun camelToSnake(value: String): String =
        value.replace(Regex("([a-z])([A-Z])"), "$1_$2").lowercase()

    private fun elapsedMs(startedAt: Long): Long =
        ((System.nanoTime() - startedAt) / 1_000_000L).coerceAtLeast(0L)

    private fun response(
        status: NanoHTTPD.Response.IStatus,
        success: Boolean,
        data: JsonObject,
        error: String?
    ): NanoHTTPD.Response = LumiSecurityController.jsonElementResponse(status, success, data, error)

    private val KNOWN_ERRORS = setOf(
        "campaign_not_found",
        "campaign_id_required",
        "campaign_not_awaiting_confirmation",
        "manifest_changed",
        "manifest_not_sealed",
        "invalid_confirmation_mode",
        "confirmation_must_cover_exact_manifest",
        "target_count_out_of_range",
        "target_count_mismatch",
        "duplicate_comment_target",
        "duplicate_comment_item",
        "platform_required",
        "account_id_required",
        "comment_text_required",
        "items_required",
        "invalid_comment_item",
        "creator_id_required",
        "video_id_required",
        "item_comment_mismatch"
    )
    private val RETRYABLE_ERRORS = setOf("task_busy", "comment_driver_exception")
}
