# APKClaw Deterministic Hybrid RPA Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert eligible successful APKClaw Agent trajectories into device-profile-scoped hybrid RPA drafts that activate only after three consecutive validations and then execute locally with deterministic tree-first resolution, visual fallback, exactly-once action accounting, and Agent reconciliation.

**Architecture:** Keep legacy RPA and all existing HTTP/Lumi contracts intact. Add a second `hybrid_rpa` execution path whose immutable evidence provider feeds one resolver arbiter and one action executor; every dispatch is recorded durably before execution and verified afterward. Template lifecycle, eligibility, validation, and device-profile matching remain in the workflow domain, while compact-tree, fresh-frame, semantic, visual, and action-ledger mechanics remain in focused RPA modules.

**Tech Stack:** Kotlin and Java 17, Android AccessibilityService, Gson, NanoHTTPD, JUnit 4, Gradle Android plugin, Node.js built-in test runner, Python `unittest`, PowerShell, Android Emulator/ADB.

**Validated design:** `docs/superpowers/specs/2026-07-14-apkclaw-semi-automatic-visual-rpa-promotion-design.md`

## Global Constraints

- Preserve application id `com.apk.claw.android`, release signing semantics, `TokenValidator`, and Lumi HMAC semantics.
- Keep every existing HTTP endpoint and response field; all hybrid fields and routes are additive.
- Default resolver policy is `TREE_PREFERRED`; `VISION_REQUIRED`, `DUAL_CONFIRM`, and `DIRECT` are fixed per step and per revision.
- Compact accessibility trees remain available; automatic replay must keep `fullTreeReads=0` unless the caller explicitly selects `debug_full`.
- Only a callback-produced `fresh` frame captured after the required timestamp may authorize a visual action or verify its result.
- Text input, clipboard paste, password entry, payment, deletion, login authorization, account binding, privacy disclosure, publish/send/upload, and unknown-risk actions remain Agent-only.
- Automatic promotion is limited to `read_only` and proven-reset `reversible` trajectories.
- Exactly three consecutive successful validations are required; any failure resets the counter to zero.
- Every resolver branch capable of dispatching an action must pass targeted validation before activation.
- Emulator activation never activates an incompatible real-device profile.
- A process death or accessibility-generation change during dispatch produces `UNCERTAIN`; no automatic replay is allowed.
- Do not add OpenCV or another large native matcher dependency; use a small pure Kotlin coarse-to-fine matcher.
- On Android API levels below 30, keep semantic tree replay available but treat every required visual resolver as unavailable and hand off to Agent without dispatch.
- Do not hardcode tokens, API keys, accounts, private keys, emulator serials, or signing passwords.
- Cap hybrid template assets and ledgers at 128 MiB; prune orphan drafts after 7 days, old degraded revisions after 30 days while retaining the newest diagnostic revision, completed ledgers after 7 days, and uncertain ledgers after 30 days.
- Do not modify LOOM main UI, NewAPI login, installers, package name, or release workflow.
- Use test-first increments and commit only files owned by the current task after its focused tests pass.

## File Responsibility Map

**Workflow domain**

- Create `app/src/main/java/com/apk/claw/android/workflow/TemplateLifecycle.kt`: lifecycle, risk, resolver, validation, and profile data types plus pure transition rules.
- Create `app/src/main/java/com/apk/claw/android/workflow/TemplateResolution.kt`: persisted semantic selectors, visual anchor specifications, checkpoints, and allowed/validated resolver sets.
- Create `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateStore.kt`: crash-consistent schema-v2 load, migration, backup recovery, and atomic same-directory replacement.
- Create `app/src/main/java/com/apk/claw/android/workflow/TemplateEligibilityPolicy.kt`: conservative promotion eligibility and risk classification.
- Create `app/src/main/java/com/apk/claw/android/workflow/AgentTrajectoryRecorder.kt`: sanitized pre/post action boundaries.
- Create `app/src/main/java/com/apk/claw/android/workflow/HybridTemplateCompiler.kt`: eligible trajectory to draft template conversion.
- Create `app/src/main/java/com/apk/claw/android/workflow/DeviceProfileProvider.kt`: local profile fingerprint construction.
- Create `app/src/main/java/com/apk/claw/android/workflow/TemplatePromotionCoordinator.kt`: validation counters, branch coverage, activation, degradation, and revision creation.
- Modify `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplate.kt`: additive schema-v2 fields and step resolution metadata.
- Modify `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt`: store use, active-only/profile-aware matching, draft learning, hybrid execution, and lifecycle mutations.

**RPA runtime**

- Create `app/src/main/java/com/apk/claw/android/rpa/UiEvidence.kt`: immutable evidence metadata and display transform.
- Create `app/src/main/java/com/apk/claw/android/rpa/UiGenerationTracker.kt`: UI/service generation tracking.
- Create `app/src/main/java/com/apk/claw/android/rpa/UiEvidenceProvider.kt`: compact-tree plus optional fresh-frame acquisition.
- Create `app/src/main/java/com/apk/claw/android/rpa/CompactTreeSnapshot.kt`: JSON-to-immutable-node conversion.
- Create `app/src/main/java/com/apk/claw/android/rpa/SemanticResolver.kt`: unique semantic target resolution.
- Create `app/src/main/java/com/apk/claw/android/rpa/AccessibilitySemanticDispatcher.kt`: live-node reacquisition and one semantic dispatch.
- Create `app/src/main/java/com/apk/claw/android/rpa/LumaPlane.kt`: Android-independent grayscale plane.
- Create `app/src/main/java/com/apk/claw/android/rpa/VisualAnchorMatcher.kt`: bounded coarse-to-fine anchor matching.
- Create `app/src/main/java/com/apk/claw/android/rpa/PerceptualFingerprint.kt`: masked stable-region fingerprints.
- Create `app/src/main/java/com/apk/claw/android/rpa/BitmapLumaAdapter.kt`: Android Bitmap adapter.
- Create `app/src/main/java/com/apk/claw/android/rpa/VisualAssetStore.kt`: checksum-verified WebP assets by template revision.
- Create `app/src/main/java/com/apk/claw/android/rpa/ActionLedger.kt`: durable outcome states and entries.
- Create `app/src/main/java/com/apk/claw/android/rpa/ActionLedgerStore.kt`: atomic per-run persistence and restart recovery.
- Create `app/src/main/java/com/apk/claw/android/rpa/SingleDispatchExecutor.kt`: sole action dispatch owner.
- Create `app/src/main/java/com/apk/claw/android/rpa/HybridResolutionArbiter.kt`: fixed-policy resolver ordering without dispatch side effects.
- Create `app/src/main/java/com/apk/claw/android/rpa/HybridRpaEngine.kt`: step loop, verification, cancellation, fallback, and metrics.
- Create `app/src/main/java/com/apk/claw/android/service/ScreenshotFrame.java`: bitmap ownership plus `frameId/source/capturedAt/ageMs`.
- Modify `app/src/main/java/com/apk/claw/android/service/ClawAccessibilityService.java`: generation events, fresh-frame API, old screenshot compatibility, and live semantic dispatch support.
- Modify `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflow.kt`: additive hybrid metadata and outcome metrics with legacy defaults.
- Modify `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflowParser.kt`: parse new fields while preserving v1 input.
- Modify `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflowRunner.kt`: route only `hybrid_rpa` runs to the new engine and rehydrate incomplete ledgers.
- Modify `app/src/main/java/com/apk/claw/android/rpa/RpaRunJson.kt`: additive lifecycle, resolver, frame, tree, and outcome fields.

**API and integration**

- Modify `app/src/main/java/com/apk/claw/android/server/AgentApiController.kt`: trajectory capture, draft result fields, hybrid fast path, and structured Agent reconciliation.
- Modify `app/src/main/java/com/apk/claw/android/server/RpaApiController.kt`: lifecycle operations, capabilities, and structured hybrid results.
- Modify `app/src/main/java/com/apk/claw/android/server/WorkflowApiController.kt`: expose lifecycle/profile/validation fields and disable/validate operations.
- Modify `app/src/main/java/com/apk/claw/android/server/ConfigServer.kt`: additive token and Lumi routes only.
- Modify `D:/Axiangmu/AUSTART/openclaw_new_launcher/scripts/openclaw-phone-agent.mjs`: expose additive hybrid fields at the CLI top level.
- Test `D:/Axiangmu/AUSTART/openclaw_new_launcher/python/api/routes_phone.py` without changing it unless its contract test proves field loss.

---

### Task 1: Template Lifecycle, Schema Migration, And Atomic Store

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/workflow/TemplateLifecycle.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/TemplateResolution.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateStore.kt`
- Modify: `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplate.kt`
- Modify: `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/TemplateLifecyclePolicyTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/WorkflowTemplateStoreTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/WorkflowTemplateManagerTest.kt`

**Interfaces:**
- Produces: `TemplateStatus`, `TemplateRiskLevel`, `ResolverPolicy`, `ResolverKind`, `ValidationState`, `TemplateLifecyclePolicy.recordValidation(...)`, `WorkflowTemplateStore.load()`, and `WorkflowTemplateStore.save(...)`.
- Produces: schema-v2 `WorkflowTemplate` fields consumed by every later task.

- [ ] **Step 1: Write lifecycle and migration tests**

```kotlin
@Test fun three_consecutive_successes_activate_only_matching_profile() {
    var state = ValidationState(target = 3, profileId = "emulator-profile")
    state = TemplateLifecyclePolicy.recordValidation(state, "emulator-profile", "reset-a", true, setOf(ResolverKind.RESOURCE_ID))
    state = TemplateLifecyclePolicy.recordValidation(state, "emulator-profile", "reset-b", true, setOf(ResolverKind.RESOURCE_ID))
    assertEquals(2, state.consecutiveSuccesses)
    assertFalse(TemplateLifecyclePolicy.canActivate(state, setOf(ResolverKind.RESOURCE_ID)))
    state = TemplateLifecyclePolicy.recordValidation(state, "emulator-profile", "reset-a", true, setOf(ResolverKind.RESOURCE_ID))
    assertTrue(TemplateLifecyclePolicy.canActivate(state, setOf(ResolverKind.RESOURCE_ID)))
    assertFalse(TemplateLifecyclePolicy.matchesProfile(state, "physical-profile"))
}

@Test fun failure_resets_consecutive_successes() {
    val initial = ValidationState(target = 3, profileId = "p", consecutiveSuccesses = 2)
    val failed = TemplateLifecyclePolicy.recordValidation(initial, "p", "reset-a", false, emptySet())
    assertEquals(0, failed.consecutiveSuccesses)
    assertEquals(1, failed.failures)
}

@Test fun legacy_template_migrates_to_degraded_and_never_matches_active() {
    val store = WorkflowTemplateStore(tempDir)
    File(tempDir, "template_index.json").writeText(legacyJsonWithoutLifecycle)
    val template = store.load().single()
    assertEquals(2, template.schemaVersion)
    assertEquals(TemplateStatus.DEGRADED, template.status)
    assertEquals(0, template.validationState.consecutiveSuccesses)
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.TemplateLifecyclePolicyTest" --tests "com.apk.claw.android.workflow.WorkflowTemplateStoreTest"`

Expected: FAIL because the lifecycle types and store do not exist.

- [ ] **Step 3: Add the lifecycle and resolution types**

```kotlin
enum class TemplateStatus { DRAFT, VALIDATING, ACTIVE, DEGRADED, DISABLED }
enum class TemplateRiskLevel { READ_ONLY, REVERSIBLE, SIDE_EFFECT, DANGEROUS, UNKNOWN }
enum class ResolverPolicy { DIRECT, TREE_PREFERRED, VISION_REQUIRED, DUAL_CONFIRM }
enum class ResolverKind { DIRECT, EPHEMERAL_REF, RESOURCE_ID, CONTENT_DESCRIPTION, TEXT_CLASS, STRUCTURAL, VISUAL_ANCHOR, NORMALIZED_COORDINATE }

data class ValidationState(
    val target: Int = 3,
    val profileId: String = "",
    val consecutiveSuccesses: Int = 0,
    val failures: Int = 0,
    val validatedResolvers: Set<ResolverKind> = emptySet(),
    val validatedResetIds: Set<String> = emptySet(),
    val lastValidationAt: Long = 0L
)

object TemplateLifecyclePolicy {
    fun recordValidation(state: ValidationState, profileId: String, resetId: String, success: Boolean, covered: Set<ResolverKind>, now: Long = System.currentTimeMillis()): ValidationState {
        require(profileId.isNotBlank())
        require(resetId.isNotBlank())
        val sameProfile = state.profileId.isBlank() || state.profileId == profileId
        if (!sameProfile) return ValidationState(profileId = profileId, failures = if (success) 0 else 1, consecutiveSuccesses = if (success) 1 else 0, validatedResolvers = if (success) covered else emptySet(), validatedResetIds = if (success) setOf(resetId) else emptySet(), lastValidationAt = now)
        return state.copy(
            profileId = profileId,
            consecutiveSuccesses = if (success) state.consecutiveSuccesses + 1 else 0,
            failures = state.failures + if (success) 0 else 1,
            validatedResolvers = if (success) state.validatedResolvers + covered else state.validatedResolvers,
            validatedResetIds = if (success) state.validatedResetIds + resetId else state.validatedResetIds,
            lastValidationAt = now
        )
    }

    fun canActivate(state: ValidationState, required: Set<ResolverKind>): Boolean =
        state.consecutiveSuccesses >= state.target && state.validatedResetIds.size >= 2 && state.validatedResolvers.containsAll(required)

    fun matchesProfile(state: ValidationState, profileId: String): Boolean = state.profileId == profileId
}

data class SemanticSelector(
    val resourceId: String? = null,
    val contentDescription: String? = null,
    val text: String? = null,
    val className: String? = null,
    val packageName: String? = null,
    val structuralPath: List<Int> = emptyList()
)

data class VisualAnchorSpec(
    val assetName: String,
    val searchRegion: NormalizedRect,
    val tapOffsetX: Float,
    val tapOffsetY: Float,
    val minimumConfidence: Float = 0.88f,
    val scaleVariants: List<Float> = listOf(0.90f, 1.00f, 1.10f)
)

data class NormalizedRect(val left: Float, val top: Float, val right: Float, val bottom: Float)

data class StepCheckpoint(
    val expectedPackage: String? = null,
    val requiredSelector: SemanticSelector? = null,
    val forbiddenSelector: SemanticSelector? = null,
    val perceptualHash: String? = null,
    val maximumHammingDistance: Int = 8
)
```

Add these schema-v2 fields to the end of `WorkflowTemplate` with defaults:

```kotlin
val schemaVersion: Int = 2,
val status: TemplateStatus = TemplateStatus.DRAFT,
val executionMode: String = "hybrid_rpa",
val defaultResolverPolicy: ResolverPolicy = ResolverPolicy.TREE_PREFERRED,
val riskLevel: TemplateRiskLevel = TemplateRiskLevel.UNKNOWN,
val validationState: ValidationState = ValidationState(),
val revision: Int = 1,
val sourceAgentTaskId: String = "",
val targetPackage: String = "",
val targetVersionCode: Long = 0L,
val targetProfileId: String = "",
val activatedAt: Long = 0L,
val degradedAt: Long = 0L,
val degradedReason: String = "",
val visualAssetDirectory: String = ""
```

Add `resolverPolicy`, `allowedResolvers`, `validatedResolvers`, `semanticSelector`, `visualAnchor`, `preCheckpoint`, and `postCheckpoint` to `WorkflowStep`. Preserve every existing constructor call by using defaults at the end of each constructor.

- [ ] **Step 4: Implement crash-consistent store replacement and active-only matching**

```kotlin
class WorkflowTemplateStore(private val directory: File, private val gson: Gson = GsonBuilder().setPrettyPrinting().create()) {
    private val target = File(directory, "template_index.json")
    private val pending = File(directory, "template_index.json.tmp")
    private val backup = File(directory, "template_index.json.bak")

    fun save(templates: Collection<WorkflowTemplate>) {
        directory.mkdirs()
        pending.writeText(gson.toJson(templates.sortedBy { it.id }))
        if (backup.exists()) check(backup.delete())
        if (target.exists()) check(target.renameTo(backup))
        if (!pending.renameTo(target)) {
            if (!target.exists() && backup.exists()) backup.renameTo(target)
            error("template_index_replace_failed")
        }
        if (backup.exists()) backup.delete()
    }

    fun load(): List<WorkflowTemplate> {
        if (!target.exists() && backup.exists()) check(backup.renameTo(target))
        if (!target.exists()) return emptyList()
        return parseAndMigrate(target.readText())
    }
}
```

Change `WorkflowTemplateManager.matchTemplate(prompt, profileId)` so its candidate list begins with `templates.values.filter { it.status == TemplateStatus.ACTIVE && it.validationState.profileId == profileId }`. Remove the old `successRate() >= 0.5f` activation shortcut. Keep explicit template lookup available for inspection and manual validation.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.*"`

Expected: PASS, including legacy parsing and active-only matching.

```powershell
git add app/src/main/java/com/apk/claw/android/workflow app/src/test/java/com/apk/claw/android/workflow
git commit -m "feat: add hybrid template lifecycle and migration"
```

### Task 2: Eligibility, Sanitized Trajectories, And Draft Compilation

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/workflow/TemplateEligibilityPolicy.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/AgentTrajectoryRecorder.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/HybridTemplateCompiler.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/TemplateEligibilityPolicyTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/AgentTrajectoryRecorderTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/HybridTemplateCompilerTest.kt`

**Interfaces:**
- Consumes: schema-v2 workflow types from Task 1.
- Produces: `TrajectoryAction`, `TrajectoryEvidenceRef`, `EligibilityDecision`, and `HybridTemplateCompiler.compile(...)` for Agent integration in Task 9.

- [ ] **Step 1: Write policy and compiler tests**

```kotlin
@Test fun input_and_side_effect_trajectories_are_agent_only() {
    assertEquals("text_input_agent_only", TemplateEligibilityPolicy.evaluate(listOf(action("input_text"))).reason)
    assertEquals("side_effect_agent_only", TemplateEligibilityPolicy.evaluate(listOf(action("tap", label = "发布"))).reason)
}

@Test fun safe_navigation_compiles_to_draft_with_fixed_policy() {
    val result = HybridTemplateCompiler.compile(
        prompt = "打开设置并进入网络页面",
        appName = "设置",
        actions = listOf(successfulTap(resourceId = "android:id/title", label = "网络和互联网")),
        profileId = "emulator-profile"
    )
    assertTrue(result is CompileResult.Compiled)
    val template = (result as CompileResult.Compiled).template
    assertEquals(TemplateStatus.DRAFT, template.status)
    assertEquals(ResolverPolicy.TREE_PREFERRED, template.steps.single().resolverPolicy)
    assertFalse(template.steps.single().validatedResolvers.isNotEmpty())
}

@Test fun recorder_redacts_sensitive_parameters() {
    val recorder = AgentTrajectoryRecorder()
    recorder.beforeAction("tool-1", "tap", mapOf("token" to "secret", "x" to 10), evidence("before"))
    recorder.afterAction("tool-1", true, evidence("after"))
    assertFalse(recorder.completed().single().params.containsKey("token"))
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.TemplateEligibilityPolicyTest" --tests "com.apk.claw.android.workflow.AgentTrajectoryRecorderTest" --tests "com.apk.claw.android.workflow.HybridTemplateCompilerTest"`

Expected: FAIL because the recorder, policy, and compiler do not exist.

- [ ] **Step 3: Implement the conservative eligibility policy**

```kotlin
data class EligibilityDecision(val eligible: Boolean, val risk: TemplateRiskLevel, val reason: String = "")

object TemplateEligibilityPolicy {
    private val textTools = setOf("input_text", "clipboard")
    private val sideEffectWords = Regex("发布|发送|上传|关注|点赞|购买|支付|删除|授权|登录|绑定|send|publish|upload|follow|like|buy|pay|delete|authorize|login", RegexOption.IGNORE_CASE)
    private val safeTools = setOf("open_app", "tap", "swipe", "drag", "long_press", "system_key", "wait", "take_screenshot", "get_screen_info", "finish")

    fun evaluate(actions: List<TrajectoryAction>): EligibilityDecision {
        if (actions.any { it.toolName in textTools }) return EligibilityDecision(false, TemplateRiskLevel.SIDE_EFFECT, "text_input_agent_only")
        if (actions.any { it.toolName !in safeTools }) return EligibilityDecision(false, TemplateRiskLevel.UNKNOWN, "unsupported_or_unknown_tool")
        if (actions.any { sideEffectWords.containsMatchIn(it.safetyLabel) }) return EligibilityDecision(false, TemplateRiskLevel.SIDE_EFFECT, "side_effect_agent_only")
        if (actions.any { !it.success }) return EligibilityDecision(false, TemplateRiskLevel.UNKNOWN, "trajectory_contains_failed_action")
        return EligibilityDecision(true, TemplateRiskLevel.READ_ONLY)
    }
}
```

`AgentTrajectoryRecorder` must keep pending actions by `toolId`, remove keys matching `token|secret|key|password|clipboard|authorization` case-insensitively, cap retained labels at 200 characters, and store screenshot/tree references rather than raw images or raw trees.

- [ ] **Step 4: Implement fixed-policy draft compilation**

```kotlin
sealed interface CompileResult {
    data class Compiled(val template: WorkflowTemplate) : CompileResult
    data class Ineligible(val reason: String) : CompileResult
}

object HybridTemplateCompiler {
    fun compile(prompt: String, appName: String?, actions: List<TrajectoryAction>, profileId: String): CompileResult {
        val eligibility = TemplateEligibilityPolicy.evaluate(actions)
        if (!eligibility.eligible) return CompileResult.Ineligible(eligibility.reason)
        val steps = actions.filterNot { it.toolName in setOf("get_screen_info", "take_screenshot", "finish") }.map { action ->
            val selector = action.semanticSelector
            val anchor = action.visualAnchor
            val policy = when {
                action.toolName in setOf("open_app", "system_key", "wait") -> ResolverPolicy.DIRECT
                selector != null -> ResolverPolicy.TREE_PREFERRED
                anchor != null -> ResolverPolicy.VISION_REQUIRED
                else -> return CompileResult.Ineligible("missing_required_evidence")
            }
            WorkflowTemplate.WorkflowStep(
                toolName = action.toolName,
                paramsTemplate = action.params,
                description = action.description,
                waitFor = 0,
                resolverPolicy = policy,
                allowedResolvers = resolverKinds(policy, selector, anchor),
                validatedResolvers = emptySet(),
                semanticSelector = selector,
                visualAnchor = anchor,
                preCheckpoint = action.preCheckpoint,
                postCheckpoint = action.postCheckpoint
            )
        }
        return CompileResult.Compiled(newDraft(prompt, appName, profileId, eligibility.risk, steps))
    }

    private fun resolverKinds(policy: ResolverPolicy, selector: SemanticSelector?, anchor: VisualAnchorSpec?): Set<ResolverKind> = when (policy) {
        ResolverPolicy.DIRECT -> setOf(ResolverKind.DIRECT)
        ResolverPolicy.TREE_PREFERRED -> buildSet {
            if (selector?.resourceId != null) add(ResolverKind.RESOURCE_ID)
            if (selector?.contentDescription != null) add(ResolverKind.CONTENT_DESCRIPTION)
            if (selector?.text != null) add(ResolverKind.TEXT_CLASS)
            if (anchor != null) add(ResolverKind.VISUAL_ANCHOR)
        }
        ResolverPolicy.VISION_REQUIRED -> setOf(ResolverKind.VISUAL_ANCHOR)
        ResolverPolicy.DUAL_CONFIRM -> setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
    }

    private fun newDraft(prompt: String, appName: String?, profileId: String, risk: TemplateRiskLevel, steps: List<WorkflowTemplate.WorkflowStep>): WorkflowTemplate = WorkflowTemplate(
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
```

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.TemplateEligibilityPolicyTest" --tests "com.apk.claw.android.workflow.AgentTrajectoryRecorderTest" --tests "com.apk.claw.android.workflow.HybridTemplateCompilerTest"`

Expected: PASS with no sensitive parameter values in failure output.

```powershell
git add app/src/main/java/com/apk/claw/android/workflow app/src/test/java/com/apk/claw/android/workflow
git commit -m "feat: compile eligible agent trajectories into drafts"
```

### Task 3: Generation-Tagged Trees And Fresh Screenshot Frames

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/rpa/UiEvidence.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/UiGenerationTracker.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/UiEvidenceProvider.kt`
- Create: `app/src/main/java/com/apk/claw/android/service/ScreenshotFrame.java`
- Modify: `app/src/main/java/com/apk/claw/android/service/ClawAccessibilityService.java`
- Modify: `app/src/main/java/com/apk/claw/android/agent/ScreenObservationBuilder.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/UiGenerationTrackerTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/ScreenshotFreshnessPolicyTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/service/AccessibilityEvidenceSourceContractTest.kt`

**Interfaces:**
- Produces: `UiEvidenceProvider.capture(requirement)`, `FreshnessRequirement`, `UiEvidence`, `DisplayTransform`, and `ScreenshotFrame`.
- Preserves: existing `ClawAccessibilityService.takeScreenshot(timeoutMs): Bitmap?` behavior for old callers.

- [ ] **Step 1: Write generation and frame-source tests**

```kotlin
@Test fun action_and_content_events_invalidate_generation() {
    val tracker = UiGenerationTracker("service-a")
    val first = tracker.snapshot()
    tracker.markUiChanged()
    assertEquals(first.uiGeneration + 1, tracker.snapshot().uiGeneration)
    tracker.markActionDispatched()
    assertEquals(first.uiGeneration + 2, tracker.snapshot().uiGeneration)
}

@Test fun cached_or_stale_frame_cannot_authorize_action() {
    val requirement = FreshnessRequirement.AuthorizeAfter(1_000L)
    assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "cache", capturedAt = 1_100L), requirement))
    assertFalse(ScreenshotFreshnessPolicy.accepts(frame(source = "stale_fallback", capturedAt = 1_100L), requirement))
    assertTrue(ScreenshotFreshnessPolicy.accepts(frame(source = "fresh", capturedAt = 1_100L), requirement))
}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.UiGenerationTrackerTest" --tests "com.apk.claw.android.rpa.ScreenshotFreshnessPolicyTest" --tests "com.apk.claw.android.service.AccessibilityEvidenceSourceContractTest"`

Expected: FAIL because generation and frame metadata are absent.

- [ ] **Step 3: Add immutable evidence types and generation tracking**

```kotlin
sealed interface FreshnessRequirement {
    data object ReadOnly : FreshnessRequirement
    data class AuthorizeAfter(val capturedAfter: Long) : FreshnessRequirement
}

data class DisplayTransform(
    val displayId: Int,
    val widthPx: Int,
    val heightPx: Int,
    val screenshotWidthPx: Int,
    val screenshotHeightPx: Int,
    val rotation: Int,
    val densityDpi: Int,
    val insetLeft: Int,
    val insetTop: Int,
    val insetRight: Int,
    val insetBottom: Int
)

data class UiEvidence(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val packageName: String,
    val windowId: Int,
    val capturedAt: Long,
    val transform: DisplayTransform,
    val compactTree: JsonObject?,
    val frameId: String? = null,
    val frameSource: String? = null,
    val frameCapturedAt: Long? = null,
    val frameAgeMs: Long? = null
)

class UiGenerationTracker(private var serviceGeneration: String) {
    private val generation = AtomicLong(0L)
    fun markUiChanged() = generation.incrementAndGet()
    fun markActionDispatched() = generation.incrementAndGet()
    fun snapshot() = GenerationSnapshot(generation.get(), serviceGeneration)
}
```

- [ ] **Step 4: Add the fresh-frame API while retaining old screenshot behavior**

`ScreenshotFrame.java` must own a copied ARGB bitmap and expose `fresh`, `cache`, or `stale_fallback`. In `ClawAccessibilityService`, add:

```java
public ScreenshotFrame takeScreenshotFrame(long timeoutMs, long freshAfterMs, boolean allowCachedReadOnly) {
    synchronized (screenshotLock) {
        long now = System.currentTimeMillis();
        if (allowCachedReadOnly) {
            Bitmap cached = copyCachedScreenshot(now, SCREENSHOT_CACHE_TTL_MS);
            if (cached != null) return ScreenshotFrame.cached(nextFrameId(false), cached, lastScreenshotAt, now);
        }
        waitForScreenshotCooldown(now);
        CapturedBitmap captured = captureScreenshotOnceWithTimestamp(timeoutMs);
        if (captured != null && captured.capturedAt > freshAfterMs) {
            rememberScreenshot(captured.bitmap, captured.capturedAt);
            return ScreenshotFrame.fresh(nextFrameId(true), copyBitmap(captured.bitmap), captured.capturedAt, System.currentTimeMillis());
        }
        if (!allowCachedReadOnly) return null;
        Bitmap stale = copyCachedScreenshot(System.currentTimeMillis(), SCREENSHOT_STALE_FALLBACK_MS);
        return stale == null ? null : ScreenshotFrame.stale(nextFrameId(false), stale, lastScreenshotAt, System.currentTimeMillis());
    }
}

public Bitmap takeScreenshot(long timeoutMs) {
    ScreenshotFrame frame = takeScreenshotFrame(timeoutMs, 0L, true);
    return frame == null ? null : frame.detachBitmap();
}
```

Add `CapturedBitmap(Bitmap bitmap, long capturedAt)`, an `AtomicLong frameSequence`, and `nextFrameId(boolean callbackProduced)` returning `<serviceGeneration>:<sequence>:fresh|derived`. `captureScreenshotOnceWithTimestamp` must set `capturedAt` inside `onSuccess`, after the callback arrives. `ScreenshotFrame` must expose static factories `fresh`, `cached`, and `stale`, must recycle any still-owned bitmap in `close()`, and `detachBitmap()` must transfer ownership exactly once.

Increment `uiGeneration` for window/content/scroll/text/focus/selection/package/configuration changes and after every APKClaw-injected action. Add `uiGeneration`, `serviceGeneration`, `frameSource`, `frameId`, and `frameAgeMs` to observation metrics without removing old fields.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.*" --tests "com.apk.claw.android.service.AccessibilityEvidenceSourceContractTest"`

Expected: PASS; the source contract confirms old `takeScreenshot(long)` remains.

```powershell
git add app/src/main/java/com/apk/claw/android/rpa app/src/main/java/com/apk/claw/android/service app/src/main/java/com/apk/claw/android/agent app/src/test/java/com/apk/claw/android/rpa app/src/test/java/com/apk/claw/android/service
git commit -m "feat: add fresh generation-tagged UI evidence"
```

### Task 4: Unique Semantic Resolution And Live Reacquisition

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/rpa/CompactTreeSnapshot.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/SemanticResolver.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/AccessibilitySemanticDispatcher.kt`
- Modify: `app/src/main/java/com/apk/claw/android/service/ClawAccessibilityService.java`
- Test: `app/src/test/java/com/apk/claw/android/rpa/SemanticResolverTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/AccessibilitySemanticDispatcherPolicyTest.kt`

**Interfaces:**
- Consumes: `SemanticSelector`, `ResolverKind`, and `UiEvidence`.
- Produces: `SemanticResolver.resolve(snapshot, selector)` and `AccessibilitySemanticDispatcher.dispatch(resolution, expectedGeneration)`.

- [ ] **Step 1: Write exact, ambiguous, disabled, and stale tests**

```kotlin
@Test fun exact_resource_id_wins_and_requires_one_enabled_visible_match() {
    val snapshot = snapshot(node("a", resourceId = "demo:id/target"), node("b", text = "Target"))
    val result = SemanticResolver.resolve(snapshot, SemanticSelector(resourceId = "demo:id/target"))
    assertEquals(ResolverKind.RESOURCE_ID, (result as SemanticResolution.Unique).matchedBy)
}

@Test fun duplicate_text_is_ambiguous() {
    val result = SemanticResolver.resolve(snapshot(node("a", text = "确定"), node("b", text = "确定")), SemanticSelector(text = "确定"))
    assertTrue(result is SemanticResolution.Ambiguous)
}

@Test fun generation_change_before_dispatch_rejects_target() {
    val dispatcher = fakeDispatcher(currentGeneration = 12)
    val result = dispatcher.dispatch(uniqueResolution(generation = 11), expectedGeneration = 11)
    assertEquals("stale_tree_generation", result.errorCode)
    assertFalse(result.accepted)
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.SemanticResolverTest" --tests "com.apk.claw.android.rpa.AccessibilitySemanticDispatcherPolicyTest"`

Expected: FAIL because semantic resolution types are missing.

- [ ] **Step 3: Implement immutable compact-node resolution**

```kotlin
data class IntRect(val left: Int, val top: Int, val right: Int, val bottom: Int)

data class CompactNode(
    val ref: String,
    val resourceId: String? = null,
    val description: String? = null,
    val text: String? = null,
    val className: String = "",
    val packageName: String = "",
    val visible: Boolean = true,
    val enabled: Boolean = true,
    val clickable: Boolean = false,
    val bounds: IntRect
)

data class CompactTreeSnapshot(
    val uiGeneration: Long,
    val serviceGeneration: String,
    val packageName: String,
    val windowId: Int,
    val nodes: List<CompactNode>
)

sealed interface SemanticResolution {
    data class Unique(val node: CompactNode, val matchedBy: ResolverKind, val generation: Long) : SemanticResolution
    data class Missing(val attempted: List<ResolverKind>) : SemanticResolution
    data class Ambiguous(val matchedBy: ResolverKind, val count: Int) : SemanticResolution
}

object SemanticResolver {
    fun resolve(snapshot: CompactTreeSnapshot, selector: SemanticSelector): SemanticResolution {
        val attempts = listOfNotNull(
            selector.resourceId?.let { ResolverKind.RESOURCE_ID to { n: CompactNode -> n.resourceId == it } },
            selector.contentDescription?.let { ResolverKind.CONTENT_DESCRIPTION to { n: CompactNode -> n.description == it } },
            selector.text?.let { value -> ResolverKind.TEXT_CLASS to { n: CompactNode -> n.text == value && selector.className?.let { it == n.className } != false } }
        )
        for ((kind, predicate) in attempts) {
            val matches = snapshot.nodes.filter { it.visible && it.enabled && selector.packageName?.let { pkg -> pkg == it.packageName } != false && predicate(it) }
            if (matches.size == 1) return SemanticResolution.Unique(matches.single(), kind, snapshot.uiGeneration)
            if (matches.size > 1) return SemanticResolution.Ambiguous(kind, matches.size)
        }
        return SemanticResolution.Missing(attempts.map { it.first })
    }
}
```

- [ ] **Step 4: Reacquire the live node and dispatch once**

`AccessibilitySemanticDispatcher` must reacquire candidates with `findNodesById`, `findNodesByDescription`, or `findNodesByText`, filter by package/class/visibility/enabled state, confirm `service.uiGeneration == expectedGeneration`, require one candidate, call `clickNode` once, recycle every returned node, and return `accepted=false` on ambiguity. It must never log selector text and must never fall back to center coordinates after `ACTION_CLICK` is accepted.

```kotlin
data class DispatchResult(val accepted: Boolean, val errorCode: String = "", val resolverUsed: ResolverKind? = null, val dispatchedAt: Long = 0L)
```

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.SemanticResolverTest" --tests "com.apk.claw.android.rpa.AccessibilitySemanticDispatcherPolicyTest"`

Expected: PASS; ambiguous selectors dispatch zero clicks.

```powershell
git add app/src/main/java/com/apk/claw/android/rpa app/src/main/java/com/apk/claw/android/service app/src/test/java/com/apk/claw/android/rpa
git commit -m "feat: add unique semantic RPA resolution"
```

### Task 5: Lightweight Visual Matching And Fingerprints

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/rpa/LumaPlane.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/VisualAnchorMatcher.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/PerceptualFingerprint.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/BitmapLumaAdapter.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/VisualAssetStore.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/VisualAnchorMatcherTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/PerceptualFingerprintTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/VisualAssetStoreTest.kt`

**Interfaces:**
- Consumes: `VisualAnchorSpec`, `NormalizedRect`, and fresh-frame metadata.
- Produces: `VisualAnchorMatcher.match(frame, anchor, spec)`, `VisualMatch`, and `PerceptualFingerprint.compute(...)`.

- [ ] **Step 1: Write translation, scaling, confidence, mask, and checksum tests**

```kotlin
@Test fun finds_translated_anchor_inside_bounded_region() {
    val frame = plane(120, 120).drawPattern(62, 48, pattern)
    val result = VisualAnchorMatcher.match(frame, pattern, spec(region = rect(0.4f, 0.3f, 0.9f, 0.8f)))
    assertTrue(result is VisualMatch.Found)
    assertEquals(62, (result as VisualMatch.Found).left)
    assertEquals(48, result.top)
}

@Test fun confidence_below_threshold_never_returns_target() {
    val result = VisualAnchorMatcher.match(noisePlane(), pattern, spec(minimumConfidence = 0.92f))
    assertTrue(result is VisualMatch.BelowThreshold)
}

@Test fun masked_clock_region_does_not_change_fingerprint() {
    assertEquals(fingerprint(frameAt("10:01"), statusBarMask), fingerprint(frameAt("10:02"), statusBarMask))
}

@Test fun pruning_keeps_active_and_latest_diagnostic_revision() {
    val result = assetStoreWithExpiredRevisions().prune(maxBytes = 128L * 1024L * 1024L, now = fixedNow)
    assertTrue(result.retained.any { it.status == TemplateStatus.ACTIVE })
    assertTrue(result.retained.any { it.isLatestDiagnostic })
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.VisualAnchorMatcherTest" --tests "com.apk.claw.android.rpa.PerceptualFingerprintTest" --tests "com.apk.claw.android.rpa.VisualAssetStoreTest"`

Expected: FAIL because matcher and asset classes do not exist.

- [ ] **Step 3: Implement pure Kotlin planes and matching**

```kotlin
data class LumaPlane(val width: Int, val height: Int, val pixels: IntArray) {
    operator fun get(x: Int, y: Int): Int = pixels[y * width + x]
}

sealed interface VisualMatch {
    data class Found(val left: Int, val top: Int, val width: Int, val height: Int, val scale: Float, val confidence: Float, val matchMs: Long) : VisualMatch
    data class BelowThreshold(val confidence: Float, val matchMs: Long) : VisualMatch
    data class Invalid(val reason: String) : VisualMatch
}

object VisualAnchorMatcher {
    fun match(frame: LumaPlane, anchor: LumaPlane, spec: VisualAnchorSpec): VisualMatch {
        val started = System.nanoTime()
        val region = pixelRegion(frame, spec.searchRegion)
        val coarseCandidates = spec.scaleVariants.flatMap { scale -> coarseSearch(frame, scale(anchor, scale), region, stride = 4) }
            .sortedBy { it.error }.take(8)
        val best = refine(frame, anchor, coarseCandidates) ?: return VisualMatch.Invalid("no_candidate")
        val confidence = (1f - best.normalizedError).coerceIn(0f, 1f)
        val elapsed = (System.nanoTime() - started) / 1_000_000L
        return if (confidence >= spec.minimumConfidence) VisualMatch.Found(best.left, best.top, best.width, best.height, best.scale, confidence, elapsed)
        else VisualMatch.BelowThreshold(confidence, elapsed)
    }
}
```

Define `Candidate(left, top, width, height, scale, normalizedError)`. `pixelRegion` clamps normalized edges to the frame, rejects empty regions, and never searches outside them. `scale` uses nearest-neighbor sampling into a new `LumaPlane`. `coarseSearch` advances target positions by four pixels and samples both axes inside the anchor at stride four; its error is `sum(abs(frame-anchor)) / (sampleCount*255f)`. `refine` searches `left/top +/- 6` around each of the best eight candidates at full pixel stride, returns the minimum-error candidate, and resolves equal errors by smallest movement from the recorded normalized anchor center. Reject invalid regions, anchors larger than regions, and scale lists outside `0.75..1.25`.

- [ ] **Step 4: Add Android bitmap conversion and checksum-verified storage**

`BitmapLumaAdapter.fromBitmap(bitmap)` must copy pixels once into an `IntArray`, compute integer BT.601 luma, then release its temporary array. `VisualAssetStore` writes WebP to `assets/<template-id>/r<revision>/`, writes SHA-256 next to the asset metadata, and refuses assets whose checksum changes. Its `prune(maxBytes, now)` applies the global 7-day/30-day/128-MiB policy and always retains active assets plus the newest diagnostic revision.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.VisualAnchorMatcherTest" --tests "com.apk.claw.android.rpa.PerceptualFingerprintTest" --tests "com.apk.claw.android.rpa.VisualAssetStoreTest"`

Expected: PASS without adding a Gradle dependency.

```powershell
git add app/src/main/java/com/apk/claw/android/rpa app/src/test/java/com/apk/claw/android/rpa
git commit -m "feat: add lightweight visual RPA matching"
```

### Task 6: Durable Action Ledger And Exactly-Once Dispatch

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/rpa/ActionLedger.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/ActionLedgerStore.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/SingleDispatchExecutor.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/ActionLedgerStoreTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/SingleDispatchExecutorTest.kt`

**Interfaces:**
- Consumes: one resolved `PreparedAction`, one `ActionDispatcher`, and one `OutcomeVerifier`.
- Produces: durable `ActionLedgerEntry` states and `ActionOutcome`; Task 7 may call only `SingleDispatchExecutor.execute(...)` to perform an action.

- [ ] **Step 1: Write state transition, process-death, and no-duplicate tests**

```kotlin
@Test fun accepted_action_is_dispatched_once_when_verification_is_unknown() {
    val dispatcher = CountingDispatcher(accepted = true)
    val outcome = executor(dispatcher, verifier = UnknownVerifier()).execute(preparedAction())
    assertEquals(1, dispatcher.calls)
    assertEquals(ActionOutcomeState.UNCERTAIN, outcome.state)
}

@Test fun dispatching_entry_recovers_as_uncertain() {
    store.write(entry(state = ActionLedgerState.DISPATCHING))
    val recovered = store.recoverIncompleteRuns().single()
    assertEquals(ActionLedgerState.UNCERTAIN, recovered.state)
}

@Test fun rejected_dispatch_is_retryable_without_claiming_effect() {
    val outcome = executor(CountingDispatcher(false), verifier = VerifiedVerifier()).execute(preparedAction())
    assertEquals(ActionOutcomeState.FAILED_NO_DISPATCH, outcome.state)
}

@Test fun pruning_keeps_uncertain_ledgers_longer_than_completed_ledgers() {
    store.write(completedEntry(finishedDaysAgo = 8))
    store.write(uncertainEntry(finishedDaysAgo = 8))
    store.prune(fixedNow)
    assertEquals(listOf(ActionLedgerState.UNCERTAIN), store.loadAll().map { it.state })
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.ActionLedgerStoreTest" --tests "com.apk.claw.android.rpa.SingleDispatchExecutorTest"`

Expected: FAIL because ledger types do not exist.

- [ ] **Step 3: Add ledger states and crash recovery**

```kotlin
enum class ActionLedgerState { PREPARED, DISPATCHING, VERIFIED, FAILED_NO_DISPATCH, FAILED_NO_EFFECT, UNCERTAIN }

data class ActionLedgerEntry(
    val runId: String,
    val stepId: String,
    val attempt: Int,
    val state: ActionLedgerState,
    val preparedAt: Long,
    val dispatchedAt: Long = 0L,
    val finishedAt: Long = 0L,
    val uiGeneration: Long,
    val serviceGeneration: String,
    val resolverUsed: ResolverKind,
    val errorCode: String = ""
)

fun ActionLedgerStore.recoverIncompleteRuns(): List<ActionLedgerEntry> = loadAll().map { entry ->
    if (entry.state == ActionLedgerState.DISPATCHING) entry.copy(state = ActionLedgerState.UNCERTAIN, finishedAt = clock()) else entry
}.also(::saveAll)
```

Persist to `workflow_templates/runs/<run-id>/action-ledger.json` using same-directory temporary and backup files. `prune(now)` removes completed ledgers after 7 days and uncertain ledgers after 30 days while respecting the shared 128-MiB cap. Never persist selector text, screenshots, raw parameters, or account data.

- [ ] **Step 4: Implement the sole action executor**

```kotlin
data class PreparedAction(
    val runId: String,
    val stepId: String,
    val attempt: Int,
    val uiGeneration: Long,
    val serviceGeneration: String,
    val resolverUsed: ResolverKind,
    val payload: DispatchPayload
)

sealed interface DispatchPayload
data class DispatchReceipt(val accepted: Boolean, val dispatchedAt: Long, val errorCode: String = "")
fun interface ActionDispatcher { fun dispatch(action: PreparedAction): DispatchReceipt }
fun interface OutcomeVerifier { fun verify(action: PreparedAction, dispatchedAt: Long): VerificationResult }
sealed interface VerificationResult {
    data object EffectVerified : VerificationResult
    data object NoEffectVerified : VerificationResult
    data class Unknown(val errorCode: String) : VerificationResult
}
enum class ActionOutcomeState { VERIFIED, FAILED_NO_DISPATCH, FAILED_NO_EFFECT, UNCERTAIN }
data class ActionOutcome(val state: ActionOutcomeState, val errorCode: String, val entry: ActionLedgerEntry)

fun PreparedAction.toLedgerEntry(state: ActionLedgerState, now: Long) = ActionLedgerEntry(
    runId = runId,
    stepId = stepId,
    attempt = attempt,
    state = state,
    preparedAt = now,
    uiGeneration = uiGeneration,
    serviceGeneration = serviceGeneration,
    resolverUsed = resolverUsed
)

class SingleDispatchExecutor(
    private val store: ActionLedgerStore,
    private val dispatcher: ActionDispatcher,
    private val verifier: OutcomeVerifier,
    private val clock: () -> Long = System::currentTimeMillis
) {
    fun execute(action: PreparedAction): ActionOutcome {
        var entry = action.toLedgerEntry(ActionLedgerState.PREPARED, clock())
        store.write(entry)
        entry = entry.copy(state = ActionLedgerState.DISPATCHING, dispatchedAt = clock())
        store.write(entry)
        val dispatched = dispatcher.dispatch(action)
        if (!dispatched.accepted) return finish(entry, ActionLedgerState.FAILED_NO_DISPATCH, dispatched.errorCode)
        return when (val result = verifier.verify(action, dispatched.dispatchedAt)) {
            VerificationResult.EffectVerified -> finish(entry, ActionLedgerState.VERIFIED, "")
            VerificationResult.NoEffectVerified -> finish(entry, ActionLedgerState.FAILED_NO_EFFECT, "no_effect")
            is VerificationResult.Unknown -> finish(entry, ActionLedgerState.UNCERTAIN, result.errorCode)
        }
    }

    private fun finish(entry: ActionLedgerEntry, state: ActionLedgerState, errorCode: String): ActionOutcome {
        val finished = entry.copy(state = state, finishedAt = clock(), errorCode = errorCode)
        store.write(finished)
        val outcome = when (state) {
            ActionLedgerState.VERIFIED -> ActionOutcomeState.VERIFIED
            ActionLedgerState.FAILED_NO_DISPATCH -> ActionOutcomeState.FAILED_NO_DISPATCH
            ActionLedgerState.FAILED_NO_EFFECT -> ActionOutcomeState.FAILED_NO_EFFECT
            else -> ActionOutcomeState.UNCERTAIN
        }
        return ActionOutcome(outcome, errorCode, finished)
    }
}
```

Any exception after `DISPATCHING` must persist `UNCERTAIN`; it must not invoke `dispatcher` again.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.ActionLedgerStoreTest" --tests "com.apk.claw.android.rpa.SingleDispatchExecutorTest"`

Expected: PASS with exactly one dispatch in every accepted-action test.

```powershell
git add app/src/main/java/com/apk/claw/android/rpa app/src/test/java/com/apk/claw/android/rpa
git commit -m "feat: add durable exactly-once RPA action ledger"
```

### Task 7: Deterministic Hybrid Engine With Legacy RPA Compatibility

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/rpa/HybridResolutionArbiter.kt`
- Create: `app/src/main/java/com/apk/claw/android/rpa/HybridRpaEngine.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflow.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflowParser.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflowRunner.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaRunJson.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/HybridResolutionArbiterTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/HybridRpaEngineTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/rpa/RpaWorkflowParserTest.kt`

**Interfaces:**
- Consumes: evidence, semantic and visual resolvers, validated resolver sets, and `SingleDispatchExecutor`.
- Produces: `HybridRunResult`, additive `RpaStepRecord` metrics, and Agent handoff context.
- Preserves: v1 `RpaWorkflow` defaults to `executionMode="rpa"` and continues through the existing runner.

- [ ] **Step 1: Write resolver-order and single-dispatch engine tests**

```kotlin
@Test fun tree_preferred_uses_semantic_then_validated_visual_before_dispatch() {
    val arbiter = arbiter(semantic = Missing, visual = Found, validated = setOf(ResolverKind.VISUAL_ANCHOR))
    val resolution = arbiter.resolve(step(policy = ResolverPolicy.TREE_PREFERRED))
    assertEquals(ResolverKind.VISUAL_ANCHOR, (resolution as Resolution.Ready).resolverUsed)
}

@Test fun unvalidated_visual_fallback_hands_off_without_dispatch() {
    val result = engine(validated = setOf(ResolverKind.RESOURCE_ID), semantic = Missing, visual = Found).run(workflow())
    assertEquals("fallback_not_validated", result.errorCode)
    assertEquals(0, result.dispatchCount)
    assertTrue(result.agentHandoffRequired)
}

@Test fun uncertain_step_stops_workflow_and_never_executes_next_step() {
    val result = engine(firstOutcome = ActionOutcomeState.UNCERTAIN).run(twoStepWorkflow())
    assertEquals(1, result.steps.size)
    assertEquals("uncertain", result.outcomeState)
}

@Test fun vision_required_on_api_29_hands_off_without_dispatch() {
    val result = engine(apiLevel = 29).run(workflow(policy = ResolverPolicy.VISION_REQUIRED))
    assertEquals("visual_capture_unsupported", result.errorCode)
    assertEquals(0, result.dispatchCount)
}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.HybridResolutionArbiterTest" --tests "com.apk.claw.android.rpa.HybridRpaEngineTest" --tests "com.apk.claw.android.rpa.RpaWorkflowParserTest"`

Expected: FAIL because hybrid engine fields and classes are missing.

- [ ] **Step 3: Add additive workflow and metric fields**

Append defaults to `RpaWorkflow`, `RpaStep`, and `RpaStepRecord`:

```kotlin
val executionMode: String = "rpa"
val templateId: String = ""
val templateRevision: Int = 0
val targetProfileId: String = ""
val resolverPolicy: ResolverPolicy = ResolverPolicy.DIRECT
val allowedResolvers: Set<ResolverKind> = emptySet()
val validatedResolvers: Set<ResolverKind> = emptySet()
val semanticSelector: SemanticSelector? = null
val visualAnchor: VisualAnchorSpec? = null
val resolverUsed: String = ""
val treeSnapshotMs: Long = 0L
val treeLookupMs: Long = 0L
val nodesVisited: Int = 0
val captureMs: Long = 0L
val matchMs: Long = 0L
val verifyMs: Long = 0L
val frameSource: String = ""
val frameAgeMs: Long = 0L
val uiGeneration: Long = 0L
val outcomeState: String = ""
```

Parser defaults must preserve old JSON exactly; hybrid-only fields are parsed only when present.

- [ ] **Step 4: Implement deterministic arbitration and engine stop rules**

```kotlin
fun interface SemanticChannel { fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution }
fun interface VisualChannel { fun resolve(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution }

sealed interface Resolution {
    data class Ready(val payload: DispatchPayload, val resolverUsed: ResolverKind, val confidence: Float = 1f) : Resolution
    data class Missing(val resolver: ResolverKind) : Resolution
    data class Blocked(val errorCode: String) : Resolution
    data class Unsafe(val errorCode: String) : Resolution
    data class Handoff(val errorCode: String) : Resolution
}

data class DirectPayload(val action: String) : DispatchPayload
interface BoundedDispatchPayload : DispatchPayload { val bounds: IntRect }

fun targetsOverlap(first: DispatchPayload, second: DispatchPayload): Boolean {
    if (first !is BoundedDispatchPayload || second !is BoundedDispatchPayload) return false
    val overlapWidth = (minOf(first.bounds.right, second.bounds.right) - maxOf(first.bounds.left, second.bounds.left)).coerceAtLeast(0)
    val overlapHeight = (minOf(first.bounds.bottom, second.bounds.bottom) - maxOf(first.bounds.top, second.bounds.top)).coerceAtLeast(0)
    val overlap = overlapWidth * overlapHeight
    val smaller = minOf((first.bounds.right - first.bounds.left) * (first.bounds.bottom - first.bounds.top), (second.bounds.right - second.bounds.left) * (second.bounds.bottom - second.bounds.top))
    return smaller > 0 && overlap.toFloat() / smaller >= 0.5f
}

class HybridResolutionArbiter(private val semantic: SemanticChannel, private val visual: VisualChannel) {
    fun resolve(step: RpaStep, evidence: UiEvidence): Resolution {
        val ordered = when (step.resolverPolicy) {
            ResolverPolicy.DIRECT -> listOf(ResolverKind.DIRECT)
            ResolverPolicy.TREE_PREFERRED -> listOf(ResolverKind.RESOURCE_ID, ResolverKind.CONTENT_DESCRIPTION, ResolverKind.TEXT_CLASS, ResolverKind.VISUAL_ANCHOR, ResolverKind.NORMALIZED_COORDINATE)
            ResolverPolicy.VISION_REQUIRED -> listOf(ResolverKind.VISUAL_ANCHOR)
            ResolverPolicy.DUAL_CONFIRM -> return resolveDual(step, evidence)
        }
        for (kind in ordered.filter { it in step.allowedResolvers }) {
            val candidate = resolveKind(kind, step, evidence)
            if (candidate is Resolution.Ready) {
                if (kind !in step.validatedResolvers) return Resolution.Blocked("fallback_not_validated")
                return candidate
            }
            if (candidate is Resolution.Unsafe) return candidate
        }
        return Resolution.Handoff("target_unresolved")
    }

    private fun resolveKind(kind: ResolverKind, step: RpaStep, evidence: UiEvidence): Resolution = when (kind) {
        ResolverKind.DIRECT -> Resolution.Ready(DirectPayload(step.action), ResolverKind.DIRECT)
        ResolverKind.EPHEMERAL_REF, ResolverKind.RESOURCE_ID, ResolverKind.CONTENT_DESCRIPTION, ResolverKind.TEXT_CLASS, ResolverKind.STRUCTURAL -> semantic.resolve(kind, step, evidence)
        ResolverKind.VISUAL_ANCHOR, ResolverKind.NORMALIZED_COORDINATE -> visual.resolve(kind, step, evidence)
    }

    private fun resolveDual(step: RpaStep, evidence: UiEvidence): Resolution {
        val semanticResult = semantic.resolve(ResolverKind.RESOURCE_ID, step, evidence)
        val visualResult = visual.resolve(ResolverKind.VISUAL_ANCHOR, step, evidence)
        if (semanticResult !is Resolution.Ready || visualResult !is Resolution.Ready) return Resolution.Handoff("dual_confirmation_missing")
        if (!targetsOverlap(semanticResult.payload, visualResult.payload)) return Resolution.Unsafe("resolver_disagreement")
        if (!step.validatedResolvers.containsAll(setOf(semanticResult.resolverUsed, visualResult.resolverUsed))) return Resolution.Blocked("fallback_not_validated")
        return semanticResult
    }
}
```

`HybridRpaEngine` must stop on `UNCERTAIN`, never execute later steps, include completed-step evidence in `AgentHandoffContext`, allow one pre-dispatch re-resolution, and allow a second dispatch only after `FAILED_NO_DISPATCH` or `FAILED_NO_EFFECT`. Route `executionMode == "hybrid_rpa"` to this engine; all old runs stay on the existing path.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.rpa.*"`

Expected: PASS, including all pre-existing parser and safety tests.

```powershell
git add app/src/main/java/com/apk/claw/android/rpa app/src/test/java/com/apk/claw/android/rpa
git commit -m "feat: add deterministic hybrid RPA engine"
```

### Task 8: Device Profiles, Three-Run Promotion, And Degradation

**Files:**
- Create: `app/src/main/java/com/apk/claw/android/workflow/DeviceProfileProvider.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/TemplatePromotionCoordinator.kt`
- Create: `app/src/main/java/com/apk/claw/android/workflow/TemplateValidationScheduler.kt`
- Modify: `app/src/main/java/com/apk/claw/android/workflow/WorkflowTemplateManager.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaWorkflowRunner.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/DeviceProfileProviderTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/TemplatePromotionCoordinatorTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/workflow/TemplateValidationSchedulerTest.kt`

**Interfaces:**
- Consumes: draft templates and completed hybrid run results.
- Produces: `DeviceProfileProvider.current()`, `TemplatePromotionCoordinator.recordValidation(...)`, and an idle-only scheduler.

- [ ] **Step 1: Write profile, promotion, reset, and degradation tests**

```kotlin
@Test fun same_inputs_produce_same_profile_without_account_identifiers() {
    val profile = DeviceProfileProvider.fingerprint(profileInputs())
    assertEquals(profile, DeviceProfileProvider.fingerprint(profileInputs()))
    assertFalse(profile.contains("account"))
}

@Test fun activation_requires_three_successes_two_resets_and_all_resolvers() {
    val required = setOf(ResolverKind.RESOURCE_ID, ResolverKind.VISUAL_ANCHOR)
    var template = draft(required)
    template = coordinator.recordValidation(template, success("reset-a", ResolverKind.RESOURCE_ID))
    template = coordinator.recordValidation(template, success("reset-b", ResolverKind.VISUAL_ANCHOR))
    assertEquals(TemplateStatus.VALIDATING, template.status)
    template = coordinator.recordValidation(template, success("reset-a", ResolverKind.RESOURCE_ID))
    assertEquals(TemplateStatus.ACTIVE, template.status)
}

@Test fun structural_failure_degrades_but_profile_mismatch_only_bypasses() {
    assertEquals(TemplateStatus.DEGRADED, coordinator.recordRuntimeFailure(active(), "structural_mismatch").status)
    assertEquals(MatchDecision.PROFILE_MISMATCH, coordinator.match(active(profile = "a"), "b"))
}

private fun success(resetId: String, resolver: ResolverKind) = ValidationResult(
    profileId = "emulator-profile",
    resetId = resetId,
    success = true,
    coveredResolvers = setOf(resolver),
    allOutcomesVerified = true,
    usedStaleFrame = false,
    serviceRebound = false,
    retriedAfterDispatch = false
)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.DeviceProfileProviderTest" --tests "com.apk.claw.android.workflow.TemplatePromotionCoordinatorTest" --tests "com.apk.claw.android.workflow.TemplateValidationSchedulerTest"`

Expected: FAIL because profile and promotion classes do not exist.

- [ ] **Step 3: Implement privacy-safe profile hashing**

```kotlin
data class DeviceProfileInputs(
    val packageName: String,
    val appVersionCode: Long,
    val apiLevel: Int,
    val oemFamily: String,
    val widthClass: Int,
    val heightClass: Int,
    val densityDpi: Int,
    val fontScaleBucket: Int,
    val localeTag: String,
    val nightMode: Boolean,
    val navigationMode: String,
    val orientationPolicy: String,
    val webViewMajor: Int
)

object DeviceProfileProvider {
    fun fingerprint(value: DeviceProfileInputs): String {
        val canonical = listOf(
            value.packageName, value.appVersionCode, value.apiLevel, value.oemFamily,
            value.widthClass, value.heightClass, value.densityDpi, value.fontScaleBucket,
            value.localeTag, value.nightMode, value.navigationMode, value.orientationPolicy,
            value.webViewMajor
        ).joinToString("|") { it.toString().replace("|", "%7C") }
        return MessageDigest.getInstance("SHA-256").digest(canonical.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }.take(24)
    }
}

enum class MatchDecision { MATCH, PROFILE_MISMATCH, NOT_ACTIVE }

data class ValidationResult(
    val profileId: String,
    val resetId: String,
    val success: Boolean,
    val coveredResolvers: Set<ResolverKind>,
    val allOutcomesVerified: Boolean,
    val usedStaleFrame: Boolean,
    val serviceRebound: Boolean,
    val retriedAfterDispatch: Boolean
)
```

Do not include Android ID, serial, phone number, account, SSID, token, or user content.

- [ ] **Step 4: Implement validation and idle scheduling rules**

`TemplatePromotionCoordinator.recordValidation` must verify matching profile, fresh reset id, all step outcomes `VERIFIED`, no stale frames, no service rebind, no post-dispatch retry, and no unresolved windows. It increments consecutive successes, unions covered resolvers, tracks distinct reset ids, and activates only at `3/3` with at least two reset ids and complete resolver coverage.

```kotlin
class TemplatePromotionCoordinator {
    fun recordValidation(template: WorkflowTemplate, result: ValidationResult): WorkflowTemplate {
        val valid = result.success && result.allOutcomesVerified && !result.usedStaleFrame && !result.serviceRebound && !result.retriedAfterDispatch
        val nextState = TemplateLifecyclePolicy.recordValidation(
            template.validationState,
            result.profileId,
            result.resetId,
            valid,
            if (valid) result.coveredResolvers else emptySet()
        )
        val required = template.steps.flatMap { it.allowedResolvers }.toSet()
        val nextStatus = if (TemplateLifecyclePolicy.canActivate(nextState, required)) TemplateStatus.ACTIVE else TemplateStatus.VALIDATING
        return template.copy(status = nextStatus, validationState = nextState, activatedAt = if (nextStatus == TemplateStatus.ACTIVE) System.currentTimeMillis() else template.activatedAt)
    }

    fun match(template: WorkflowTemplate, profileId: String): MatchDecision = when {
        template.status != TemplateStatus.ACTIVE -> MatchDecision.NOT_ACTIVE
        template.validationState.profileId != profileId -> MatchDecision.PROFILE_MISMATCH
        else -> MatchDecision.MATCH
    }

    fun recordRuntimeFailure(template: WorkflowTemplate, errorCode: String): WorkflowTemplate =
        if (errorCode in setOf("structural_mismatch", "freshness_violation", "app_version_mismatch")) template.copy(status = TemplateStatus.DEGRADED, degradedReason = errorCode, degradedAt = System.currentTimeMillis()) else template
}
```

`TemplateValidationScheduler` may enqueue only when task queue and RPA runner are idle, device is unlocked, accessibility health is `healthy`, expected package/reset can be restored, risk is allowed, and no other validation is active. A failed reset counts as a validation failure without executing steps.

- [ ] **Step 5: Run tests and commit**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.workflow.*" --tests "com.apk.claw.android.rpa.*"`

Expected: PASS; profile mismatch does not mutate the active revision.

```powershell
git add app/src/main/java/com/apk/claw/android/workflow app/src/main/java/com/apk/claw/android/rpa app/src/test/java/com/apk/claw/android/workflow
git commit -m "feat: add profile-scoped three-run template promotion"
```

### Task 9: Agent Learning, API Contracts, Metrics, And Reconciliation

**Files:**
- Modify: `app/src/main/java/com/apk/claw/android/agent/DefaultAgentService.kt`
- Modify: `app/src/main/java/com/apk/claw/android/server/AgentApiController.kt`
- Modify: `app/src/main/java/com/apk/claw/android/server/RpaApiController.kt`
- Modify: `app/src/main/java/com/apk/claw/android/server/WorkflowApiController.kt`
- Modify: `app/src/main/java/com/apk/claw/android/server/ConfigServer.kt`
- Modify: `app/src/main/java/com/apk/claw/android/rpa/RpaRunJson.kt`
- Modify: `app/src/main/java/com/apk/claw/android/server/AgentTaskPublicSnapshot.kt`
- Test: `app/src/test/java/com/apk/claw/android/server/HybridRpaRouteContractTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/server/HybridRpaResponseTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/server/AgentApiControllerSourceContractTest.kt`
- Test: `app/src/test/java/com/apk/claw/android/server/AgentTaskPublicSnapshotTest.kt`

**Interfaces:**
- Consumes: compiler, promotion coordinator, hybrid runner, and Agent handoff context.
- Produces: additive HTTP/Lumi operations and public metrics without leaking selector text or images.

- [ ] **Step 1: Write route and response contract tests**

```kotlin
@Test fun existing_and_lumi_lifecycle_routes_are_exposed() {
    val source = File("src/main/java/com/apk/claw/android/server/ConfigServer.kt").readText()
    assertTrue(source.contains("/api/workflow/template/validate"))
    assertTrue(source.contains("/api/workflow/template/disable"))
    assertTrue(source.contains("/api/lumi/rpa/template/validate"))
    assertTrue(source.contains("/api/lumi/rpa/template/disable"))
}

@Test fun hybrid_snapshot_contains_additive_metrics_and_no_raw_evidence() {
    val json = RpaRunJson.snapshot(hybridSnapshot())
    assertEquals("hybrid_rpa", json["mode"].asString)
    assertTrue(json.has("templateStatus"))
    assertTrue(json.has("validationProgress"))
    assertEquals("verified", json["outcomeState"].asString)
    assertFalse(json.toString().contains("rawScreenshot"))
    assertFalse(json.toString().contains("rawTree"))
}
```

- [ ] **Step 2: Run focused API tests and verify they fail**

Run: `./gradlew.bat :app:testDebugUnitTest --tests "com.apk.claw.android.server.HybridRpaRouteContractTest" --tests "com.apk.claw.android.server.HybridRpaResponseTest" --tests "com.apk.claw.android.server.AgentApiControllerSourceContractTest"`

Expected: FAIL because lifecycle routes and hybrid fields are missing.

- [ ] **Step 3: Integrate trajectory recording and draft-only learning**

In `AgentApiController`, create the recorder only when `learnTemplate=true`. Capture sanitized pre-action evidence in `onToolCall`, capture post-action evidence in `onToolResult`, and compile only in `onComplete`. Replace the first-success activation behavior:

```kotlin
val compileResult = HybridTemplateCompiler.compile(prompt, detectedAppName, trajectoryRecorder.completed(), profileId)
when (compileResult) {
    is CompileResult.Compiled -> WorkflowTemplateManager.saveDraft(compileResult.template)
    is CompileResult.Ineligible -> taskMetrics.promotionIneligibleReason = compileResult.reason
}
```

Do not call `updateTemplateStats(template.id, true)` during learning. Template fast-path matching must require `ACTIVE` and current profile. On `UNCERTAIN`, prepend reconciliation context to Agent and set `allowReplayFailedStep=false` until Agent proves the old postcondition absent.

- [ ] **Step 4: Add lifecycle routes and sanitized observability**

Add token-protected:

```text
POST /api/workflow/template/validate   {"templateId":"..."}
POST /api/workflow/template/disable    {"templateId":"..."}
```

Add Lumi-signed equivalents:

```text
POST /api/lumi/rpa/template/validate
POST /api/lumi/rpa/template/disable
```

Keep `/api/rpa/capabilities` field `schema="apkclaw.rpa.v1"` and add `hybridSchema="apkclaw.hybrid-rpa.v2"`. Expose `templateStatus`, `templateRevision`, `validationProgress`, `promotionEligible`, `promotionIneligibleReason`, `resolverPolicy`, `resolverUsed`, `uiGeneration`, `frameId`, `frameSource`, `frameAgeMs`, `outcomeState`, `fallbackStepIndex`, `treeSnapshotMs`, `treeLookupMs`, `treeCacheHit`, `nodesVisited`, `compactTreeReads`, and `fullTreeReads`.

All failure responses must retain `success=false`, `errorCode`, `message`, `currentStep`, `mode`, and `retryable`.

- [ ] **Step 5: Run API and full APKClaw unit tests, then commit**

Run: `./gradlew.bat :app:testDebugUnitTest`

Expected: PASS, including legacy route, token, Lumi, action-fast, accessibility, and RPA tests.

```powershell
git add app/src/main/java/com/apk/claw/android/agent app/src/main/java/com/apk/claw/android/server app/src/main/java/com/apk/claw/android/rpa app/src/main/java/com/apk/claw/android/workflow app/src/test/java/com/apk/claw/android/server
git commit -m "feat: expose hybrid RPA lifecycle and reconciliation"
```

### Task 10: LOOM CLI Additive Field Pass-Through

**Files:**
- Modify: `D:/Axiangmu/AUSTART/openclaw_new_launcher/scripts/openclaw-phone-agent.mjs`
- Test: `D:/Axiangmu/AUSTART/openclaw_new_launcher/scripts/openclaw-phone-agent-fast-path.test.mjs`
- Test: `D:/Axiangmu/AUSTART/openclaw_new_launcher/python/tests/test_routes_phone.py`

**Interfaces:**
- Consumes: APKClaw additive response fields from Task 9.
- Produces: unchanged CLI payload plus top-level hybrid state fields for LOOM/Codex; no LOOM UI change.

- [ ] **Step 1: Add a failing CLI response test**

```javascript
test('hybrid fast path exposes lifecycle and outcome fields without dropping raw data', async () => {
  const response = {
    success: true,
    data: {
      mode: 'hybrid_rpa',
      currentStep: 'verify',
      templateStatus: 'validating',
      validationProgress: '2/3',
      resolverPolicy: 'tree_preferred',
      resolverUsed: 'resource_id',
      outcomeState: 'verified',
      fallbackStepIndex: 0,
      metrics: { mode: 'hybrid_rpa', totalMs: 88, rounds: 0 }
    }
  };
  const payload = await runFastPathFixture(response);
  assert.equal(payload.templateStatus, 'validating');
  assert.equal(payload.validationProgress, '2/3');
  assert.equal(payload.outcomeState, 'verified');
  assert.equal(payload.data.resolverUsed, 'resource_id');
});
```

- [ ] **Step 2: Run the Node test and verify it fails**

Run from `D:/Axiangmu/AUSTART/openclaw_new_launcher`: `node --test scripts/openclaw-phone-agent-fast-path.test.mjs`

Expected: FAIL because `fastPathPublicFields` does not copy hybrid fields.

- [ ] **Step 3: Extend only the CLI public-field allowlist**

```javascript
function fastPathPublicFields(data) {
  const fields = {};
  const keys = [
    'action', 'screenHash', 'summary', 'currentPackage', 'beforeHash', 'afterHash',
    'changed', 'actionMs', 'verifyMs', 'templateStatus', 'templateRevision',
    'validationProgress', 'promotionEligible', 'promotionIneligibleReason',
    'resolverPolicy', 'resolverUsed', 'uiGeneration', 'frameId', 'frameSource',
    'frameAgeMs', 'outcomeState', 'fallbackStepIndex'
  ];
  for (const key of keys) if (data?.[key] !== undefined) fields[key] = data[key];
  return fields;
}
```

- [ ] **Step 4: Add a Python bridge contract test without changing production routing**

```python
def test_phone_stdout_payload_preserves_hybrid_rpa_fields(self) -> None:
    stdout = json.dumps({
        "mode": "hybrid_rpa",
        "templateStatus": "active",
        "validationProgress": "3/3",
        "resolverUsed": "resource_id",
        "outcomeState": "verified",
        "metrics": {"totalMs": 91, "rounds": 0},
    })
    payload = _phone_stdout_payload(stdout)
    self.assertEqual(payload["templateStatus"], "active")
    self.assertEqual(payload["outcomeState"], "verified")
```

Run: `python -m unittest python.tests.test_routes_phone.PhoneRouteSnapshotTests.test_phone_stdout_payload_preserves_hybrid_rpa_fields`

Expected: PASS. If it fails, change only `_phone_stdout_payload` so it returns the parsed object unchanged; do not touch route/UI composition.

- [ ] **Step 5: Run focused LOOM checks and commit both repositories separately**

Run:

```powershell
node --check scripts/openclaw-phone-agent.mjs
node --test scripts/openclaw-phone-agent-fast-path.test.mjs
python -m unittest python.tests.test_routes_phone
```

Expected: PASS.

```powershell
git add scripts/openclaw-phone-agent.mjs scripts/openclaw-phone-agent-fast-path.test.mjs python/tests/test_routes_phone.py
git commit -m "feat: expose APKClaw hybrid RPA state"
```

### Task 11: Release Version, Emulator Pressure Suite, Build, And Report

**Files:**
- Create: `app/src/debug/java/com/apk/claw/android/debug/HybridRpaFixtureActivity.kt`
- Create: `app/src/debug/AndroidManifest.xml`
- Create: `app/src/debug/res/layout/activity_hybrid_rpa_fixture.xml`
- Create: `tools/fixtures/hybrid-native-run.json`
- Create: `tools/hybrid-rpa-emulator-pressure.ps1`
- Create: `docs/APKCLAW_HYBRID_RPA_TEST_REPORT_2026-07-14.md`
- Modify: `app/build.gradle.kts`
- Modify: `CHANGELOG.md`
- Update after successful signed build: `AgentPhone_latest.apk`
- Update after successful signed build: `AgentPhone_latest.apk.sha256.txt`

**Interfaces:**
- Consumes: all APKClaw and LOOM work from Tasks 1-10.
- Produces: v6.54/code 923 release artifacts and reproducible before/after timing evidence.

- [ ] **Step 1: Add a debug-only deterministic fixture**

The fixture must expose native controls with stable resource ids, duplicate labels, a delayed transition, and one custom-drawn visual target. It must contain no account, network, payment, delete, login, publish, or private-data action.

```kotlin
class HybridRpaFixtureActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hybrid_rpa_fixture)
        findViewById<Button>(R.id.native_target).setOnClickListener {
            findViewById<TextView>(R.id.result_text).text = "native_verified"
        }
        findViewById<Button>(R.id.delayed_target).setOnClickListener {
            findViewById<TextView>(R.id.result_text).postDelayed({
                findViewById<TextView>(R.id.result_text).text = "delayed_verified"
            }, 700L)
        }
    }
}
```

Declare the activity only in `app/src/debug/AndroidManifest.xml` with `android:exported="true"`; release builds must not contain it.

Create the native workflow fixture:

```json
{
  "workflow": {
    "workflowId": "hybrid-native-fixture",
    "name": "Hybrid native fixture",
    "executionMode": "hybrid_rpa",
    "maxDurationMs": 15000,
    "steps": [
      {
        "id": "tap-native",
        "action": "tap_semantic",
        "resolverPolicy": "TREE_PREFERRED",
        "allowedResolvers": ["RESOURCE_ID"],
        "validatedResolvers": ["RESOURCE_ID"],
        "semanticSelector": {
          "resourceId": "com.apk.claw.android:id/native_target",
          "className": "Button",
          "packageName": "com.apk.claw.android"
        },
        "guard": {"expectedPackage": "com.apk.claw.android"}
      },
      {
        "id": "verify-native",
        "action": "assert_semantic",
        "resolverPolicy": "TREE_PREFERRED",
        "allowedResolvers": ["TEXT_CLASS"],
        "validatedResolvers": ["TEXT_CLASS"],
        "semanticSelector": {"text": "native_verified", "className": "TextView"}
      }
    ]
  }
}
```

- [ ] **Step 2: Add a pressure script with hard assertions**

```powershell
param(
  [string]$Adb = 'D:\android-sdk-windows\android-sdk-windows\platform-tools\adb.exe',
  [string]$Serial = 'emulator-5554',
  [string]$BaseUrl = 'http://127.0.0.1:9527',
  [string]$Token = $env:APKCLAW_TOKEN,
  [int]$Runs = 30
)
if (-not (Test-Path -LiteralPath $Adb)) { throw 'adb_not_found' }
if ([string]::IsNullOrWhiteSpace($Token)) { throw 'APKCLAW_TOKEN_not_set' }
& $Adb -s $Serial forward tcp:9527 tcp:9527 | Out-Null
$headers = @{ 'X-APKCLAW-TOKEN' = $Token; 'Content-Type' = 'application/json' }
$null = New-Item -ItemType Directory -Force 'build/reports'
$results = @()
for ($i = 1; $i -le $Runs; $i++) {
  $started = [Diagnostics.Stopwatch]::StartNew()
  $response = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/rpa/run" -Headers $headers -Body (Get-Content -Raw '.\tools\fixtures\hybrid-native-run.json')
  $started.Stop()
  if ($response.success -ne $true) { throw "run_$i failed" }
  $results += [pscustomobject]@{ run = $i; wallMs = $started.ElapsedMilliseconds; mode = $response.data.mode; outcome = $response.data.outcomeState }
}
if (($results | Where-Object outcome -eq 'verified').Count -lt 29) { throw 'success_rate_below_29_of_30' }
$results | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 'build/reports/hybrid-rpa-pressure.json'
```

Extend the script with named cases for `observe_fast`, fresh screenshot, `TREE_PREFERRED`, `VISION_REQUIRED`, `DUAL_CONFIRM`, duplicate selector, stale frame, timeout, busy, accessibility disabled, model missing, process kill after `DISPATCHING`, App restart, orientation change, and Agent fallback. Every case must assert structured JSON fields.

- [ ] **Step 3: Bump the release version and run complete source verification**

Change:

```kotlin
versionCode = 923
versionName = if (android7Compat) "6.54-stability-android7" else "6.54-stability"
```

Run from the APKClaw repository:

```powershell
.\gradlew.bat :app:testDebugUnitTest
.\gradlew.bat test
.\gradlew.bat :app:assembleDebug
```

Expected: all tests pass and a debug APK exists under `app/build/outputs/apk/debug/`.

Run from `D:/Axiangmu/AUSTART/openclaw_new_launcher`:

```powershell
node --check scripts/openclaw-phone-agent.mjs
node --test scripts/openclaw-phone-agent-fast-path.test.mjs
python -m unittest python.tests.test_phone_signature_contract python.tests.test_phone_fast_path_contract python.tests.test_routes_phone
```

Expected: all phone-only contract tests pass.

- [ ] **Step 4: Install on the emulator and run the pressure matrix**

```powershell
$adb='D:\android-sdk-windows\android-sdk-windows\platform-tools\adb.exe'
& $adb devices -l
& $adb -s emulator-5554 install -r -g (Get-ChildItem 'app/build/outputs/apk/debug/*.apk' | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
& $adb -s emulator-5554 shell am start -n 'com.apk.claw.android/com.apk.claw.android.debug.HybridRpaFixtureActivity'
.\tools\hybrid-rpa-emulator-pressure.ps1 -Adb $adb -Serial emulator-5554 -Runs 30
```

Expected:

- Draft progression is exactly `0/3 -> 1/3 -> 2/3 -> active 3/3`.
- At least 29/30 active runs finish without LLM rounds.
- Native tree-resolved median step overhead is below 250 ms, excluding configured waits.
- Visual timings are reported separately with fresh frame ids; cached/stale frames authorize zero actions.
- All production replay snapshots report `fullTreeReads=0`.
- A killed `DISPATCHING` action restarts as `UNCERTAIN` and is not replayed.
- Input and dangerous fixtures return Agent-only/ineligible results.

- [ ] **Step 5: Build the signed release, publish the local artifact, and write the report**

Run only with existing local signing configuration; do not print the property values:

```powershell
.\gradlew.bat :app:assembleRelease
$apk=(Get-ChildItem 'app/build/outputs/apk/release/*.apk' | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
Copy-Item -LiteralPath $apk.FullName -Destination '.\AgentPhone_latest.apk' -Force
$hash=(Get-FileHash -Algorithm SHA256 '.\AgentPhone_latest.apk').Hash
Set-Content -Encoding ASCII '.\AgentPhone_latest.apk.sha256.txt' $hash
```

The report must include exact commit, version, APK path, SHA-256, Gradle/LOOM commands, emulator/API level, baseline and optimized P50/P95, 30-run success count, resolver distribution, fallback count, stale-frame rejection count, uncertain-action result, build result, missing real-device evidence, remaining bottlenecks, and next recommendation. Do not claim real-device validation unless a real device was actually used.

```powershell
git add app/build.gradle.kts app/src/debug tools docs/APKCLAW_HYBRID_RPA_TEST_REPORT_2026-07-14.md CHANGELOG.md AgentPhone_latest.apk AgentPhone_latest.apk.sha256.txt
git commit -m "release: build APKClaw 6.54 hybrid RPA"
```

## Spec Coverage Matrix

| Design requirement | Implementation tasks |
| --- | --- |
| Lifecycle, migration, active-only matching | Tasks 1 and 8 |
| Sanitized successful trajectory capture | Tasks 2 and 9 |
| Risk policy and Agent-only exclusions | Tasks 2, 8, and 9 |
| Compact/full tree retention and semantic selectors | Tasks 1, 3, and 4 |
| Fixed `DIRECT`/`TREE_PREFERRED`/`VISION_REQUIRED`/`DUAL_CONFIRM` policy | Tasks 2, 7, and 8 |
| Frame identity, freshness, display transform, and visual matching | Tasks 3 and 5 |
| Single arbiter, single executor, durable outcome, and `UNCERTAIN` | Tasks 6 and 7 |
| Profile-scoped three-run validation and degradation | Task 8 |
| Atomic storage, checksums, backup recovery, and pruning | Tasks 1, 5, and 6 |
| Additive HTTP, Lumi, CLI, SSE, metrics, and structured errors | Tasks 9 and 10 |
| Unit, contract, emulator, restart, failure, stress, build, and report | Task 11 |

## Final Completion Gate

Do not mark the implementation complete until all conditions are true:

- The signed release APK builds with the existing signing configuration.
- Legacy RPA, Agent, Token, Lumi, observe-fast, action-fast, screenshot, busy, timeout, and accessibility-error tests pass.
- The template fast path matches only active templates for the current device profile.
- Three consecutive validations and every declared resolver branch are proven by tests.
- No cached/stale frame can authorize or verify an action.
- Every accepted action has one durable terminal outcome; `UNCERTAIN` never auto-replays.
- Emulator pressure evidence is stored in the report, with real-device gaps stated explicitly.
- LOOM phone-only contract tests pass and no LOOM UI or installer file changed.
