package com.apk.claw.android.workflow

import java.util.UUID

sealed interface CompileResult {
    data class Compiled(val template: WorkflowTemplate) : CompileResult
    data class Ineligible(val reason: String) : CompileResult
}

object HybridTemplateCompiler {
    private val observationTools = setOf("get_screen_info", "take_screenshot", "finish")
    private val directTools = setOf("open_app", "wait")

    fun compile(
        prompt: String,
        appName: String?,
        actions: List<TrajectoryAction>,
        profileId: String
    ): CompileResult {
        if (profileId.isBlank()) return CompileResult.Ineligible("blank_profile_id")
        if (!TrajectoryBoundaryValidator.isValidCompileMetadata(prompt, appName, profileId)) {
            return CompileResult.Ineligible("invalid_compile_metadata")
        }
        if (actions.isEmpty()) return CompileResult.Ineligible("empty_trajectory")
        val actionIdReason = actionIdReason(actions)
        if (actionIdReason != null) return CompileResult.Ineligible(actionIdReason)
        val sanitizedActions = mutableListOf<TrajectoryAction>()
        for (action in actions) {
            if (!TrajectoryBoundaryValidator.isValidPersistedActionMetadata(action)) {
                return CompileResult.Ineligible("invalid_action_metadata")
            }
            if (!TrajectoryBoundaryValidator.isValidCheckpoint(action.preCheckpoint) ||
                !TrajectoryBoundaryValidator.isValidCheckpoint(action.postCheckpoint)
            ) {
                return CompileResult.Ineligible("invalid_checkpoint")
            }
            if (action.semanticSelector != null && !TrajectoryBoundaryValidator.isUsableSelector(action.semanticSelector)) {
                return CompileResult.Ineligible("invalid_semantic_selector")
            }
            if (action.visualAnchor != null && !TrajectoryBoundaryValidator.isUsableAnchor(action.visualAnchor)) {
                return CompileResult.Ineligible("invalid_visual_anchor")
            }
            val normalizedParams = normalizeToolParamAliases(action.toolName, action.params)
            val sanitizedParams = sanitizeTrajectoryParams(action.toolName, normalizedParams)
            if (sanitizedParams !is TrajectoryParamsSanitization.Safe) {
                return CompileResult.Ineligible("unsafe_parameter_value")
            }
            if (!validateToolParams(action.toolName, sanitizedParams.params)) {
                return CompileResult.Ineligible("invalid_tool_params")
            }
            sanitizedActions += action.copy(params = projectTrajectoryParams(action.toolName, sanitizedParams.params))
        }
        val executableActions = sanitizedActions.filterNot { it.toolName in observationTools }
        if (executableActions.isEmpty()) return CompileResult.Ineligible("no_executable_actions")
        val eligibility = TemplateEligibilityPolicy.evaluate(sanitizedActions)
        if (!eligibility.eligible) return CompileResult.Ineligible(eligibility.reason)
        if (executableActions.any { !hasProductionAdapter(it) }) {
            return CompileResult.Ineligible("production_adapter_unavailable")
        }

        val steps = mutableListOf<WorkflowTemplate.WorkflowStep>()
        for (action in executableActions) {
            val selector = action.semanticSelector
            val anchor = action.visualAnchor
            val policy = when {
                action.toolName in directTools -> ResolverPolicy.DIRECT
                action.toolName == "long_press" && anchor != null -> ResolverPolicy.VISION_REQUIRED
                selector != null -> ResolverPolicy.TREE_PREFERRED
                anchor != null -> ResolverPolicy.VISION_REQUIRED
                else -> return CompileResult.Ineligible("missing_required_evidence")
            }
            val allowedResolvers = resolverKinds(policy, selector, anchor)
            if (policy == ResolverPolicy.TREE_PREFERRED && allowedResolvers.none { it.isTreeCapable() }) {
                return CompileResult.Ineligible("empty_tree_resolver_set")
            }
            steps += WorkflowTemplate.WorkflowStep(
                toolName = action.toolName,
                paramsTemplate = paramsForTemplate(action.params),
                description = action.description,
                waitFor = 0,
                resolverPolicy = policy,
                allowedResolvers = allowedResolvers,
                validatedResolvers = emptySet(),
                semanticSelector = selector,
                visualAnchor = anchor,
                preCheckpoint = action.preCheckpoint,
                postCheckpoint = action.postCheckpoint
            )
        }

        return CompileResult.Compiled(newDraft(prompt, appName, profileId, eligibility.risk, steps))
    }

    private fun actionIdReason(actions: List<TrajectoryAction>): String? {
        val usedIds = mutableSetOf<String>()
        for (action in actions) {
            if (action.toolId.isBlank()) return "blank_tool_id"
            if (!Regex("^[A-Za-z0-9._-]{1,64}$").matches(action.toolId)) return "invalid_action_metadata"
            if (!usedIds.add(action.toolId)) return "duplicate_tool_id"
        }
        return null
    }

    private fun paramsForTemplate(params: Map<String, Any?>): Map<String, Any> = params.mapNotNull { (key, value) ->
        value?.let { key to it }
    }.toMap()

    private fun resolverKinds(
        policy: ResolverPolicy,
        selector: SemanticSelector?,
        anchor: VisualAnchorSpec?
    ): Set<ResolverKind> = when (policy) {
        ResolverPolicy.DIRECT -> setOf(ResolverKind.DIRECT)
        ResolverPolicy.TREE_PREFERRED -> buildSet {
            if (!selector?.resourceId.isNullOrBlank()) add(ResolverKind.RESOURCE_ID)
            if (!selector?.contentDescription.isNullOrBlank()) add(ResolverKind.CONTENT_DESCRIPTION)
            if (!selector?.text.isNullOrBlank()) add(ResolverKind.TEXT_CLASS)
            if (anchor != null) add(ResolverKind.VISUAL_ANCHOR)
        }
        ResolverPolicy.VISION_REQUIRED -> setOf(ResolverKind.VISUAL_ANCHOR)
        ResolverPolicy.DUAL_CONFIRM -> setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
    }

    private fun ResolverKind.isTreeCapable(): Boolean = this in setOf(
        ResolverKind.RESOURCE_ID,
        ResolverKind.CONTENT_DESCRIPTION,
        ResolverKind.TEXT_CLASS
    )

    private fun hasProductionAdapter(action: TrajectoryAction): Boolean = when (action.toolName) {
        "open_app", "wait" -> true
        "tap" -> action.semanticSelector != null || action.visualAnchor != null
        "long_press" -> action.visualAnchor != null
        else -> false
    }

    private fun newDraft(
        prompt: String,
        appName: String?,
        profileId: String,
        risk: TemplateRiskLevel,
        steps: List<WorkflowTemplate.WorkflowStep>
    ): WorkflowTemplate = WorkflowTemplate(
        id = UUID.randomUUID().toString(),
        name = prompt.take(40),
        description = "Agent trajectory draft",
        taskPattern = Regex.escape(prompt),
        keywords = prompt.split(Regex("\\s+")).filter { it.isNotBlank() }.take(8),
        appName = appName,
        steps = steps,
        createdAt = System.currentTimeMillis(),
        lastUsedAt = 0L,
        successCount = 0,
        failCount = 0,
        schemaVersion = 2,
        status = TemplateStatus.DRAFT,
        executionMode = "hybrid_rpa",
        riskLevel = risk,
        validationState = ValidationState(profileId = profileId)
    )
}
