package com.apk.claw.android.comment

import com.apk.claw.android.agent.AgentActionSignature
import com.apk.claw.android.agent.AgentOscillationGuard
import com.apk.claw.android.agent.OscillationDecision
import java.util.concurrent.locks.ReentrantLock

data class CommentCampaignRunResult(
    val success: Boolean,
    val campaign: CommentCampaign?,
    val errorCode: String = "",
    val message: String = "",
    val retryable: Boolean = false,
    val evidence: List<String> = emptyList()
)

class CommentCampaignCoordinator(
    private val store: CommentCampaignStore,
    private val ledger: CommentSendLedger,
    private val driver: CommentDeviceDriver,
    private val now: () -> Long = System::currentTimeMillis,
    private val maxStepsPerItem: Int = 64
) {
    private val runLock = ReentrantLock()

    fun prepare(manifest: CommentManifest): CommentCampaign {
        val sealed = CommentManifestAuthorizer.seal(manifest)
        val timestamp = now()
        val campaign = CommentCampaign(
            campaignId = sealed.campaignId,
            platform = sealed.platform,
            accountId = sealed.accountId,
            query = sealed.query,
            targetCount = sealed.targetCount,
            state = CommentCampaignState.AWAITING_CONFIRMATION,
            items = sealed.items.map { item ->
                CommentCampaignItem(
                    itemId = item.itemId,
                    creatorId = item.creatorId,
                    creatorLabel = item.creatorLabel,
                    videoId = item.videoId,
                    videoLabel = item.videoLabel,
                    commentText = item.commentText,
                    itemHash = item.itemHash,
                    idempotencyKey = item.idempotencyKey,
                    updatedAt = timestamp
                )
            },
            manifestHash = sealed.manifestHash,
            createdAt = sealed.createdAt.takeIf { it > 0L } ?: timestamp,
            updatedAt = timestamp,
            confirmationMode = sealed.confirmationMode
        )
        store.save(campaign)
        return campaign
    }

    fun confirm(
        campaignId: String,
        manifestHash: String,
        itemHashes: Collection<String>?
    ): CommentCampaign {
        val campaign = requireNotNull(store.load(campaignId)) { "campaign_not_found" }
        require(campaign.state == CommentCampaignState.AWAITING_CONFIRMATION) {
            "campaign_not_awaiting_confirmation"
        }
        require(campaign.manifestHash == manifestHash) { "manifest_changed" }
        val manifest = campaign.toManifest()
        val approval = CommentManifestAuthorizer.confirm(manifest, itemHashes, now())
        val confirmed = campaign.copy(
            state = CommentCampaignState.RUNNING,
            approval = approval,
            errorCode = "",
            message = if (approval.confirmationMode == CommentManifestAuthorizer.MODE_WEAK) {
                "Campaign authorized once for sealed manifest"
            } else {
                "Campaign authorized for exact manifest and item hashes"
            },
            updatedAt = now()
        )
        store.save(confirmed)
        return confirmed
    }

    fun snapshot(campaignId: String): CommentCampaign? = store.load(campaignId)

    fun cancel(campaignId: String): CommentCampaignRunResult {
        val campaign = store.load(campaignId)
            ?: return failure(null, "campaign_not_found", "Comment campaign was not found", false)
        if (campaign.state in TERMINAL_CAMPAIGN_STATES) {
            return failure(campaign, "campaign_already_terminal", "Campaign is already terminal", false)
        }
        val cancelled = campaign.copy(
            state = CommentCampaignState.CANCELLED,
            errorCode = "campaign_cancelled",
            message = "Campaign cancelled",
            updatedAt = now()
        )
        store.save(cancelled)
        return CommentCampaignRunResult(true, cancelled, evidence = listOf("campaign_cancelled"))
    }

    fun resume(campaignId: String): CommentCampaignRunResult {
        val campaign = store.load(campaignId)
            ?: return failure(null, "campaign_not_found", "Comment campaign was not found", false)
        if (campaign.items.any { it.state == CommentItemState.SEND_UNCERTAIN }) {
            return failure(
                campaign,
                "send_reconciliation_required",
                "A send result is uncertain and requires explicit human reconciliation",
                false
            )
        }
        if (campaign.state == CommentCampaignState.PAUSED) {
            store.save(
                campaign.copy(
                    state = CommentCampaignState.RUNNING,
                    errorCode = "",
                    message = "Campaign resumed",
                    updatedAt = now()
                )
            )
        }
        return run(campaignId)
    }

    fun run(campaignId: String): CommentCampaignRunResult {
        if (!runLock.tryLock()) {
            return failure(store.load(campaignId), "task_busy", "Another comment campaign is running", true)
        }
        try {
            return runLocked(campaignId)
        } finally {
            runLock.unlock()
        }
    }

    private fun runLocked(campaignId: String): CommentCampaignRunResult {
        var campaign = store.load(campaignId)
            ?: return failure(null, "campaign_not_found", "Comment campaign was not found", false)
        if (campaign.state == CommentCampaignState.AWAITING_CONFIRMATION) {
            return failure(campaign, "confirmation_required", "Confirm the exact manifest before running", false)
        }
        if (campaign.state == CommentCampaignState.CANCELLED) {
            return failure(campaign, "campaign_cancelled", "Campaign is cancelled", false)
        }
        if (campaign.state in setOf(CommentCampaignState.COMPLETED, CommentCampaignState.COMPLETED_WITH_ERRORS)) {
            return CommentCampaignRunResult(true, campaign, evidence = listOf("campaign_already_complete"))
        }
        if (!CommentManifestAuthorizer.isAuthorized(campaign.toManifest(), campaign.approval)) {
            return failure(campaign, "manifest_changed", "Stored campaign no longer matches its approval", false)
        }
        if (campaign.items.any { it.state == CommentItemState.SEND_UNCERTAIN }) {
            return failure(campaign, "send_reconciliation_required", "Uncertain send requires human reconciliation", false)
        }

        val evidence = mutableListOf<String>()
        for (index in campaign.items.indices) {
            campaign = requireNotNull(store.load(campaignId))
            var item = campaign.items[index]
            if (item.state in TERMINAL_ITEM_STATES) continue

            if (item.state == CommentItemState.SENDING) {
                return recoverInterruptedSend(campaign, index, item, evidence)
            }

            val guard = AgentOscillationGuard()
            var steps = 0
            while (item.state !in TERMINAL_ITEM_STATES) {
                if (++steps > maxStepsPerItem) {
                    return failItem(
                        campaign,
                        index,
                        item,
                        "comment_step_limit_exceeded",
                        "Comment target exceeded the deterministic step limit",
                        evidence
                    )
                }

                if (item.state == CommentItemState.TEXT_VERIFIED) {
                    val authorized = authorizeItem(campaign, index, item)
                    if (!authorized.success) return authorized
                    campaign = requireNotNull(authorized.campaign)
                    item = campaign.items[index]
                    evidence += "${item.itemId}:send_authorized"
                    continue
                }

                if (item.state == CommentItemState.SEND_AUTHORIZED) {
                    val sent = sendAuthorized(campaign, index, item, guard, evidence)
                    if (!sent.success) return sent
                    campaign = requireNotNull(sent.campaign)
                    item = campaign.items[index]
                    continue
                }

                val plan = driver.plan(campaign, item)
                val signature = AgentActionSignature(plan.pageState, plan.action, plan.target)
                when (val decision = guard.evaluateNext(signature)) {
                    is OscillationDecision.Blocked -> {
                        return failItem(
                            campaign,
                            index,
                            item,
                            "ui_oscillation_detected",
                            "Blocked repeating UI action cycle with period ${decision.period}",
                            evidence
                        )
                    }
                    OscillationDecision.Continue -> Unit
                }

                guard.recordDispatched(signature)
                val result = try {
                    driver.execute(plan, campaign, item)
                } catch (error: Exception) {
                    return failItem(
                        campaign,
                        index,
                        item,
                        "comment_driver_exception",
                        "Comment device driver failed before send",
                        evidence + "driver_exception:${error.javaClass.simpleName}"
                    )
                }
                val processed = processDeviceResult(campaign, index, item, result, evidence)
                if (!processed.success) return processed
                campaign = requireNotNull(processed.campaign)
                item = campaign.items[index]
            }
        }

        campaign = requireNotNull(store.load(campaignId))
        val finalState = CommentCampaignStateMachine.deriveCampaignState(campaign)
        val completed = campaign.copy(
            state = finalState,
            currentTargetIndex = campaign.items.size,
            errorCode = "",
            message = "Comment campaign completed",
            updatedAt = now()
        )
        store.save(completed)
        return CommentCampaignRunResult(
            success = finalState == CommentCampaignState.COMPLETED,
            campaign = completed,
            errorCode = if (finalState == CommentCampaignState.COMPLETED_WITH_ERRORS) "completed_with_errors" else "",
            message = completed.message,
            evidence = evidence
        )
    }

    private fun authorizeItem(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem
    ): CommentCampaignRunResult {
        if (!CommentManifestAuthorizer.isAuthorized(campaign.toManifest(), campaign.approval) ||
            item.itemHash !in campaign.approval.orEmptyHashes()
        ) {
            return failure(campaign, "manifest_changed", "Item is not covered by the exact approval", false)
        }
        return when (ledger.maySend(item.idempotencyKey)) {
            SendPermission.BLOCK_ALREADY_SENT -> {
                val transitioned = transitionItem(campaign, index, item, CommentItemState.SEND_AUTHORIZED)
                if (transitioned == null) {
                    failure(campaign, "invalid_comment_state_transition", "Cannot authorize item", false)
                } else {
                    val sending = transitionItem(transitioned, index, transitioned.items[index], CommentItemState.SENDING)
                    val sent = sending?.let {
                        transitionItem(it, index, it.items[index], CommentItemState.SENT_VERIFIED)
                    }
                    if (sent == null) failure(campaign, "invalid_comment_state_transition", "Cannot restore sent item", false)
                    else CommentCampaignRunResult(true, sent, evidence = listOf("send_already_verified"))
                }
            }
            SendPermission.BLOCK_UNCERTAIN ->
                failure(campaign, "send_reconciliation_required", "Send ledger is uncertain", false)
            SendPermission.ALLOW -> {
                val updated = transitionItem(campaign, index, item, CommentItemState.SEND_AUTHORIZED)
                    ?: return failure(campaign, "invalid_comment_state_transition", "Cannot authorize item", false)
                CommentCampaignRunResult(true, updated)
            }
        }
    }

    private fun sendAuthorized(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        guard: AgentOscillationGuard,
        evidence: MutableList<String>
    ): CommentCampaignRunResult {
        if (!CommentManifestAuthorizer.isAuthorized(campaign.toManifest(), campaign.approval) ||
            item.itemHash !in campaign.approval.orEmptyHashes()
        ) {
            return failure(campaign, "manifest_changed", "Approval changed before send", false)
        }
        when (ledger.maySend(item.idempotencyKey)) {
            SendPermission.BLOCK_ALREADY_SENT -> {
                val sending = transitionItem(campaign, index, item, CommentItemState.SENDING)
                    ?: return failure(campaign, "invalid_comment_state_transition", "Cannot restore sent item", false)
                val sent = transitionItem(sending, index, sending.items[index], CommentItemState.SENT_VERIFIED)
                    ?: return failure(campaign, "invalid_comment_state_transition", "Cannot restore sent item", false)
                evidence += "${item.itemId}:send_already_verified"
                return CommentCampaignRunResult(true, sent, evidence = evidence)
            }
            SendPermission.BLOCK_UNCERTAIN ->
                return failure(campaign, "send_reconciliation_required", "Send ledger is uncertain", false)
            SendPermission.ALLOW -> Unit
        }

        val sending = transitionItem(campaign, index, item, CommentItemState.SENDING)
            ?: return failure(campaign, "invalid_comment_state_transition", "Cannot enter sending state", false)
        val sendingItem = sending.items[index]
        val plan = driver.plan(sending, sendingItem)
        val signature = AgentActionSignature(plan.pageState, plan.action, plan.target)
        if (guard.evaluateNext(signature) is OscillationDecision.Blocked) {
            return failItem(
                sending,
                index,
                sendingItem,
                "ui_oscillation_detected",
                "Blocked repeating send action",
                evidence
            )
        }
        guard.recordDispatched(signature)
        val result = try {
            driver.execute(plan, sending, sendingItem)
        } catch (error: Exception) {
            val exceptionEvidence = "driver_exception:${error.javaClass.simpleName}"
            ledger.markUncertain(sendingItem.idempotencyKey, exceptionEvidence, now())
            val uncertain = transitionItem(
                sending,
                index,
                sendingItem,
                CommentItemState.SEND_UNCERTAIN,
                "send_uncertain",
                "Comment driver failed after send started",
                CommentCampaignState.PAUSED
            ) ?: sending
            return failure(
                uncertain,
                "send_uncertain",
                "Send result is uncertain; automatic replay is blocked",
                false,
                evidence + exceptionEvidence
            )
        }
        return when (result) {
            is CommentDeviceStepResult.SendVerified -> {
                ledger.markSent(sendingItem.idempotencyKey, result.evidence, now())
                val sent = transitionItem(sending, index, sendingItem, CommentItemState.SENT_VERIFIED)
                    ?: return failure(sending, "invalid_comment_state_transition", "Cannot verify sent state", false)
                evidence += "${sendingItem.itemId}:sent_verified"
                CommentCampaignRunResult(true, sent, evidence = evidence)
            }
            is CommentDeviceStepResult.SendUncertain -> {
                ledger.markUncertain(sendingItem.idempotencyKey, result.evidence, now())
                val uncertain = transitionItem(
                    sending,
                    index,
                    sendingItem,
                    CommentItemState.SEND_UNCERTAIN,
                    "send_uncertain",
                    result.evidence,
                    CommentCampaignState.PAUSED
                ) ?: sending
                failure(uncertain, "send_uncertain", "Send result is uncertain; automatic replay is blocked", false, evidence)
            }
            is CommentDeviceStepResult.Retry -> {
                ledger.markUncertain(sendingItem.idempotencyKey, result.evidence.ifBlank { result.message }, now())
                val uncertain = transitionItem(
                    sending,
                    index,
                    sendingItem,
                    CommentItemState.SEND_UNCERTAIN,
                    "send_uncertain",
                    result.message,
                    CommentCampaignState.PAUSED
                ) ?: sending
                failure(uncertain, "send_uncertain", "Send outcome timed out; automatic replay is blocked", false, evidence)
            }
            is CommentDeviceStepResult.NeedsHuman -> pauseCampaign(sending, index, sendingItem, result.errorCode, result.message, evidence)
            is CommentDeviceStepResult.Failed -> failItem(sending, index, sendingItem, result.errorCode, result.message, evidence)
            is CommentDeviceStepResult.Advance -> failItem(
                sending,
                index,
                sendingItem,
                "invalid_send_result",
                "Send action did not return send verification evidence",
                evidence
            )
        }
    }

    private fun processDeviceResult(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        result: CommentDeviceStepResult,
        evidence: MutableList<String>
    ): CommentCampaignRunResult = when (result) {
        is CommentDeviceStepResult.Advance -> {
            val updated = transitionItem(campaign, index, item, result.nextState)
                ?: return failure(
                    campaign,
                    "invalid_comment_state_transition",
                    "Driver attempted invalid transition ${item.state} to ${result.nextState}",
                    false,
                    evidence
                )
            evidence += "${item.itemId}:${result.nextState.name.lowercase()}"
            CommentCampaignRunResult(true, updated, evidence = evidence)
        }
        is CommentDeviceStepResult.Retry -> {
            val retried = updateItem(
                campaign,
                index,
                item.copy(
                    attempts = item.attempts + 1,
                    errorCode = result.errorCode,
                    message = result.message,
                    updatedAt = now()
                )
            )
            if (result.evidence.isNotBlank()) evidence += result.evidence
            CommentCampaignRunResult(true, retried, evidence = evidence)
        }
        is CommentDeviceStepResult.NeedsHuman ->
            pauseCampaign(campaign, index, item, result.errorCode, result.message, evidence)
        is CommentDeviceStepResult.Failed ->
            failItem(campaign, index, item, result.errorCode, result.message, evidence)
        is CommentDeviceStepResult.SendVerified,
        is CommentDeviceStepResult.SendUncertain ->
            failure(campaign, "invalid_send_state", "Send result returned before SENDING state", false, evidence)
    }

    private fun recoverInterruptedSend(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        evidence: MutableList<String>
    ): CommentCampaignRunResult {
        return when (ledger.maySend(item.idempotencyKey)) {
            SendPermission.BLOCK_ALREADY_SENT -> {
                val sent = transitionItem(campaign, index, item, CommentItemState.SENT_VERIFIED)
                    ?: return failure(campaign, "invalid_comment_state_transition", "Cannot restore verified send", false)
                evidence += "${item.itemId}:send_recovered_verified"
                CommentCampaignRunResult(true, sent, evidence = evidence)
            }
            SendPermission.BLOCK_UNCERTAIN -> {
                val uncertain = transitionItem(
                    campaign,
                    index,
                    item,
                    CommentItemState.SEND_UNCERTAIN,
                    "send_uncertain",
                    "Recovered an uncertain send checkpoint",
                    CommentCampaignState.PAUSED
                ) ?: campaign
                failure(uncertain, "send_reconciliation_required", "Uncertain send requires reconciliation", false, evidence)
            }
            SendPermission.ALLOW -> {
                ledger.markUncertain(item.idempotencyKey, "process_restarted_while_sending", now())
                val uncertain = transitionItem(
                    campaign,
                    index,
                    item,
                    CommentItemState.SEND_UNCERTAIN,
                    "send_uncertain",
                    "Process restarted while send outcome was unknown",
                    CommentCampaignState.PAUSED
                ) ?: campaign
                failure(uncertain, "send_reconciliation_required", "Send outcome is unknown after restart", false, evidence)
            }
        }
    }

    private fun transitionItem(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        next: CommentItemState,
        errorCode: String = "",
        message: String = "",
        campaignState: CommentCampaignState = CommentCampaignState.RUNNING
    ): CommentCampaign? {
        val transition = CommentCampaignStateMachine.transition(
            item.copy(attempts = item.attempts + 1),
            next,
            now(),
            errorCode,
            message
        )
        if (!transition.accepted) return null
        return updateItem(campaign.copy(state = campaignState), index, transition.item)
    }

    private fun updateItem(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem
    ): CommentCampaign {
        val items = campaign.items.toMutableList()
        items[index] = item
        val updated = campaign.copy(
            items = items,
            currentTargetIndex = index,
            updatedAt = now()
        )
        store.save(updated)
        return updated
    }

    private fun pauseCampaign(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        errorCode: String,
        message: String,
        evidence: List<String>
    ): CommentCampaignRunResult {
        val paused = updateItem(
            campaign.copy(state = CommentCampaignState.PAUSED, errorCode = errorCode, message = message),
            index,
            item.copy(errorCode = errorCode, message = message, updatedAt = now())
        )
        return failure(paused, errorCode, message, false, evidence)
    }

    private fun failItem(
        campaign: CommentCampaign,
        index: Int,
        item: CommentCampaignItem,
        errorCode: String,
        message: String,
        evidence: List<String>
    ): CommentCampaignRunResult {
        val transition = CommentCampaignStateMachine.transition(
            item.copy(attempts = item.attempts + 1),
            CommentItemState.FAILED,
            now(),
            errorCode,
            message
        )
        val failedItem = if (transition.accepted) transition.item else item.copy(
            errorCode = errorCode,
            message = message,
            updatedAt = now()
        )
        val failed = updateItem(
            campaign.copy(state = CommentCampaignState.FAILED, errorCode = errorCode, message = message),
            index,
            failedItem
        )
        return failure(failed, errorCode, message, false, evidence)
    }

    private fun failure(
        campaign: CommentCampaign?,
        errorCode: String,
        message: String,
        retryable: Boolean,
        evidence: List<String> = emptyList()
    ) = CommentCampaignRunResult(
        success = false,
        campaign = campaign,
        errorCode = errorCode,
        message = message,
        retryable = retryable,
        evidence = evidence
    )

    private fun CommentCampaign.toManifest(): CommentManifest = CommentManifest(
        campaignId = campaignId,
        platform = platform,
        accountId = accountId,
        query = query,
        targetCount = targetCount,
        commentText = items.firstOrNull()?.commentText.orEmpty(),
        items = items.map { item ->
            CommentManifestItem(
                itemId = item.itemId,
                creatorId = item.creatorId,
                creatorLabel = item.creatorLabel,
                videoId = item.videoId,
                videoLabel = item.videoLabel,
                commentText = item.commentText,
                itemHash = item.itemHash,
                idempotencyKey = item.idempotencyKey
            )
        },
        manifestHash = manifestHash,
        createdAt = createdAt,
        confirmationMode = confirmationMode
    )

    private fun CommentManifestApproval?.orEmptyHashes(): Set<String> = this?.itemHashes.orEmpty()

    private companion object {
        val TERMINAL_ITEM_STATES = setOf(
            CommentItemState.SENT_VERIFIED,
            CommentItemState.FAILED,
            CommentItemState.SKIPPED,
            CommentItemState.SEND_UNCERTAIN
        )
        val TERMINAL_CAMPAIGN_STATES = setOf(
            CommentCampaignState.COMPLETED,
            CommentCampaignState.COMPLETED_WITH_ERRORS,
            CommentCampaignState.FAILED,
            CommentCampaignState.CANCELLED
        )
    }
}
