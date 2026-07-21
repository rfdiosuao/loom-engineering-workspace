# APKClaw Semi-automatic Deterministic Hybrid RPA Promotion Design

Date: 2026-07-14

## 1. Objective

Turn a successful APKClaw Agent execution into a safe deterministic hybrid-RPA draft, validate it three consecutive times, and only then allow it to enter the default template fast path.

The promoted workflow keeps the accessibility tree as its fastest semantic channel and uses visual matching where the tree is absent, stale, sparse, or ambiguous. Every step has a fixed resolver policy in a validated template revision; a production run never silently changes that policy. Tasks that require text input remain Agent-only in this release.

The runtime order is:

```text
active hybrid template
  -> fresh generation-tagged evidence
  -> fixed per-step resolver policy
  -> one safety-authorized action dispatch
  -> semantic or fresh-frame verification
  -> verified / uncertain / Agent reconciliation
```

The central invariant is: one fresh evidence bundle, one authorized dispatch, one durable outcome.

## 2. Scope

Included:

- Successful Agent trajectory capture.
- Draft template creation, parameter extraction, and semantic selector compilation.
- Template lifecycle persistence and backward-compatible migration.
- Risk classification and promotion eligibility.
- Three-consecutive-success validation.
- Deterministic hybrid RPA for app launch, semantic click, visual tap, swipe, drag, long press, wait, assertions, back, and home.
- Generation-tagged compact trees, screenshot anchors, normalized coordinates, page fingerprints, and stable-state waits.
- Freshness-aware screenshot capture and a durable action-outcome ledger.
- Active-template matching, degradation, revision, and partial Agent fallback.
- Existing HTTP, Lumi-signed, CLI, and SSE contract extensions.
- Unit, contract, emulator integration, restart, failure, and stress testing.

Excluded:

- Custom APKClaw input method.
- Automatic promotion of workflows containing text input.
- Automatic replay of payment, purchase, deletion, login authorization, privacy disclosure, account binding, or other dangerous actions.
- LOOM main UI redesign, installer changes, package/signature changes, or Lumi security semantic changes.

## 3. Template Lifecycle

Templates gain a persisted lifecycle:

```text
draft -> validating (1/3) -> validating (2/3) -> active (3/3)
active -> degraded -> validating -> active
any non-running state -> disabled
```

Required fields, all with backward-compatible defaults:

```json
{
  "schemaVersion": 2,
  "status": "draft",
  "executionMode": "hybrid_rpa",
  "defaultResolverPolicy": "tree_preferred",
  "riskLevel": "read_only",
  "validationMode": "auto_replay",
  "validationTarget": 3,
  "consecutiveValidationSuccesses": 0,
  "validationFailures": 0,
  "lastValidationAt": 0,
  "activatedAt": 0,
  "degradedAt": 0,
  "degradedReason": "",
  "revision": 1,
  "sourceAgentTaskId": "",
  "targetPackage": "",
  "targetVersionCode": 0,
  "targetProfileId": "",
  "visualAssetDirectory": ""
}
```

Only `active` templates may be returned by automatic `matchTemplate()`. A caller may inspect drafts and explicitly request validation, but a draft must never silently execute as a production fast path.

Validation success must be consecutive. Any failed validation resets the consecutive counter to zero and records a structured failure. Runtime failures do not silently retry an irreversible action.

## 4. Legacy Migration

Existing JSON remains readable.

- Existing learned templates identified by their learned-template metadata migrate to `degraded` and require validation.
- Existing templates never become active solely because their historical success rate is above 50 percent.
- Existing success and failure counters remain available as historical metrics but do not count toward the new three-validation threshold.
- Explicitly requested legacy templates may be inspected or manually validated; automatic prompt matching only sees `active` templates.
- Migration writes atomically and preserves the original file until the new index has been committed successfully.

## 5. Successful Trajectory Capture

`AgentTrajectoryRecorder` records action boundaries during a successful Agent run:

- Tool id and sanitized parameters.
- Timestamp, round, duration, and result.
- Current package and orientation.
- Fresh pre-action screenshot when visual fallback or confirmation is required.
- Fresh stable post-action screenshot when visual verification is required.
- Compact pre-action tree snapshot generation and sanitized semantic target attributes.
- Candidate selector bundle containing resource id, content description, text, class, package, and structural hints.
- Tap or gesture coordinates normalized to the content rectangle.
- A cropped visual anchor around the action target when applicable.
- A post-action page fingerprint and expected visual checkpoint.

Observation-only calls such as `get_screen_info` are not copied into the hybrid workflow. Secrets, raw model configuration, tokens, clipboard contents, credentials, and sensitive text are never persisted.

The compiler rejects promotion when the trajectory contains:

- `input_text`, clipboard paste, password entry, or equivalent text injection.
- Unsupported or ambiguous tools.
- A dangerous action according to the risk policy.
- Missing evidence required by the compiled resolver policy, such as a visual anchor for `VISION_REQUIRED`.
- A terminal result that cannot be verified.

Rejected tasks continue to work through Agent fallback and expose a structured `promotionIneligibleReason`.

## 6. Risk And Validation Policy

Risk levels:

| Level | Examples | Promotion behavior |
| --- | --- | --- |
| `read_only` | Open page, inspect status, collect visible information | Automatic three-run validation while idle |
| `reversible` | Navigate tabs, toggle a test-only setting with a reset step | Automatic validation only when reset is proven |
| `side_effect` | Like, follow, send, publish, upload | No immediate replay; natural successes may be reviewed later |
| `dangerous` | Payment, deletion, login authorization, account binding, privacy disclosure | Never auto-promote |

This release automatically promotes only `read_only` and proven-reset `reversible` workflows. `side_effect`, `dangerous`, and text-input workflows remain Agent-only.

Automated validation runs only when the task queue is idle, the device is unlocked, accessibility is healthy, and the expected start package can be restored. Each run has its own timeout and cancellation point.

## 7. Deterministic Hybrid Resolution

Every compiled step has exactly one persisted resolver policy:

| Policy | Use | Resolution behavior |
| --- | --- | --- |
| `DIRECT` | App launch, back, home, wait | No target lookup; verify package or transition where applicable |
| `TREE_PREFERRED` | Ordinary native Android controls | Fresh compact tree and unique semantic selector first; vision may fall back only before dispatch |
| `VISION_REQUIRED` | Canvas, games, opaque WebView, or sparse Compose semantics | Fresh screenshot anchor first; tree still checks package, window, and safety context |
| `DUAL_CONFIRM` | Ambiguous target or proven-reset reversible step | Tree and vision must identify a compatible target before dispatch |

The default policy is `TREE_PREFERRED`. Validation may compile a different policy for an individual step, but an active revision cannot change policy at runtime. Each persisted policy contains an ordered, finite set of allowed resolvers. Every resolver branch that may dispatch an action must pass targeted validation before activation; an unvalidated fallback may collect diagnostics and hand off to Agent but may not click. Telemetry can only create a new draft revision that must pass validation again.

Semantic selector priority is:

```text
same-generation ephemeral ref
  -> exact resourceId
  -> exact contentDescription
  -> exact text plus class and package
  -> bounded structural hints
```

A semantic match must be visible, enabled, package-compatible, class-compatible, and unique. Persisted templates store selector bundles, never live `AccessibilityNodeInfo` objects or traversal-dependent node ids. Immediately before dispatch, the selected target is reacquired against the current generation. `ACTION_CLICK` may be used on the unique node or its clickable ancestor; a failed semantic action must not silently become an unverified center-coordinate tap.

The compact tree remains the default observation returned to Agent and API callers. `tree_only`, `visual_only`, and `debug_full` remain explicit diagnostic or caller-selected modes. `debug_full` may serialize the complete tree, but automatic template replay never requires full-tree serialization.

Supported hybrid steps include:

```text
open_app
wait_stable
assert_package
assert_semantic
assert_frame
tap_semantic
tap_anchor
tap_normalized
swipe_normalized
drag_normalized
long_press_anchor
back
home
wait
finish
```

`tap_anchor` stores a cropped anchor, a normalized search region, a tap offset within the anchor, scale tolerance, minimum confidence, normalized-coordinate fallback, and an expected post-action checkpoint. `tap_semantic` stores the semantic selector bundle plus an optional visual fallback or confirmation asset.

## 8. Evidence Freshness And Visual Matching

`UiEvidenceProvider` creates immutable evidence bundles tagged with:

- `uiGeneration`, accessibility service generation, package, window id, and captured time.
- Display id, physical dimensions, screenshot dimensions, rotation, density, insets, content rectangle, font scale, locale, theme, and navigation mode.
- Compact semantic snapshot generation.
- Screenshot `frameId`, `source`, `capturedAt`, and `ageMs` when a frame is present.

`uiGeneration` increments on relevant window, content, scroll, text, focus, selection, package, rotation, inset, and display events, and immediately after every injected action. A compact snapshot may be reused only when generation, package, window, display transform, and service generation still match and it was captured after the previous action. Live node objects are never cached.

Screenshot sources are `fresh`, `cache`, and `stale_fallback`. Cached frames may serve read-only observation when their age is reported. Only a `fresh` frame captured after the required timestamp may authorize a visual action or verify a post-action state. Two-frame stability requires two distinct fresh callback-generated `frameId` values; two copies of one cached bitmap count as one frame.

`VisualAnchorMatcher` uses a lightweight on-device coarse-to-fine matcher to avoid a large native dependency:

1. Convert the search region and anchor to grayscale.
2. Downsample for a coarse search.
3. Search only the configured region at supported scale variants.
4. Refine the best candidates at full local resolution.
5. Return location, scale, confidence, and match duration.

Default scale variants are `0.90`, `1.00`, and `1.10`. Templates may narrow this range. Page checkpoints use a perceptual fingerprint over stable regions and ignore status-bar time, transient progress indicators, and the APKClaw floating overlay region.

The matcher never taps when confidence is below the configured threshold. A normalized fallback is allowed only when the current page fingerprint, display transform, package, and window match the recorded pre-action state and no semantic safety predicate blocks the region.

## 9. Execution And Verification

For every action step, one `HybridResolutionArbiter` constructs a fresh evidence bundle and resolves the target according to the persisted step policy. One `ActionExecutor` is the only component allowed to dispatch the action. Tree and vision resolvers never dispatch independently.

Before dispatch, the runner:

1. Restores or confirms the expected package, window, service generation, and display transform.
2. Verifies the pre-action semantic or visual checkpoint.
3. Resolves a unique target using the fixed step policy.
4. Runs risk, overlay, and coordinate-bound checks.
5. Persists an action ledger entry as `PREPARED`.

The executor then transitions the entry through:

```text
PREPARED -> FAILED_NO_DISPATCH
         -> DISPATCHING -> VERIFIED
                        -> FAILED_NO_EFFECT
                        -> UNCERTAIN
```

`DISPATCHING` means Android accepted the action request, not that the intended business effect occurred. Post-state verification first uses package and semantic predicates, then requests a fresh visual frame only when required or inconclusive. A process death, accessibility-service generation change, unprovable post-state, or lost verification while `DISPATCHING` produces `UNCERTAIN`. An uncertain step is never automatically replayed; Agent reconciliation may inspect the state but may not repeat the action without proving that it had no effect.

One pre-dispatch re-resolution is allowed for stale, missing, or ambiguous evidence. After dispatch, a local retry is allowed only when the action was not accepted or an independent postcondition proves the original state is unchanged. The current RPA behavior of generically retrying every failed step must not be used for promoted workflows.

Structured step results include:

```json
{
  "stepIndex": 2,
  "action": "tap_semantic",
  "status": "succeeded",
  "resolverPolicy": "tree_preferred",
  "resolverUsed": "resource_id",
  "uiGeneration": 418,
  "confidence": 0.94,
  "matchMs": 82,
  "gestureMs": 131,
  "verifyMs": 247,
  "attempts": 1,
  "outcomeState": "verified",
  "screenHashBefore": "...",
  "screenHashAfter": "..."
}
```

## 10. Promotion And Revision Flow

After a successful eligible Agent task:

1. Compile a `draft` hybrid template.
2. Parameterize safe values and verify that no unresolved sensitive values remain.
3. Bind the draft revision to an app and device profile and schedule validation run 1 when the device is idle.
4. Reset to the recorded start state and run the hybrid template.
5. Increment the consecutive count only after every step and terminal checkpoint pass.
6. Repeat until 3/3 succeeds across at least two fresh start-state resets within the same compatible device profile.
7. Atomically mark the template `active`.

Activation is scoped to `targetProfileId`. The local profile fingerprint covers the app package and version, Android API and OEM family, display class, density, font scale, locale, theme, navigation mode, orientation policy, and relevant WebView version. An emulator-validated revision is not automatically active on a physical device or incompatible display profile. A compatible new profile requires its own three validations. A profile mismatch bypasses the revision without mutating it; an app-version or structural mismatch degrades the affected revision.

If an active template fails:

1. Stop at the failed step.
2. Preserve completed-step evidence, the action ledger state, and current sanitized evidence.
3. Mark the template `degraded` for structural semantic or visual failures, freshness violations, or app-version mismatch.
4. If the outcome is not uncertain, start Agent with the original goal, completed steps, failed step, error code, and current state. If uncertain, start reconciliation first and forbid blind replay.
5. If Agent completes successfully, compile revision `N+1` as a new draft.
6. Keep the failed revision for diagnostics but exclude it from automatic matching.

## 11. Storage

Template JSON remains under the existing workflow template directory. Visual assets and durable action ledgers use one directory per template revision and run:

```text
workflow_templates/
  template_index.json
  <template-id>.json
  assets/<template-id>/r<revision>/
    step-01-before.webp
    step-01-anchor.webp
    step-01-after.webp
  runs/<run-id>/action-ledger.json
```

Writes use temporary files followed by atomic rename. Each asset has a SHA-256 checksum. Orphaned drafts and old degraded revisions are pruned by age and total storage budget, while active and most recent diagnostic revisions are retained.

## 12. API And Compatibility

Existing endpoints and fields remain intact. Additive fields expose:

- `templateStatus`
- `templateRevision`
- `validationProgress`
- `promotionEligible`
- `promotionIneligibleReason`
- `executionMode=hybrid_rpa`
- `resolverPolicy`
- `resolverUsed`
- `uiGeneration`
- `frameId`, `frameSource`, and `frameAgeMs`
- `outcomeState`
- `fallbackStepIndex`
- semantic and visual timing and confidence metrics

Workflow APIs gain signed operations for validation, disabling, and lifecycle inspection. Existing TokenValidator and Lumi HMAC semantics are unchanged. SSE snapshots expose sanitized lifecycle state without raw screenshots or parameters.

## 13. Observability

Task and template results report:

- `totalMs`
- `captureMs`
- `treeSnapshotMs`
- `treeLookupMs`
- `treeCacheHit`
- `treeGeneration`
- `nodesVisited`
- `matchMs`
- `gestureMs`
- `verifyMs`
- `steps`
- `attempts`
- `mode=hybrid_rpa`
- `resolverPolicy`
- `resolverUsed`
- `templateStatus`
- `validationProgress`
- `fallbackReason`
- `fallbackStepIndex`
- `compactTreeReads`
- `fullTreeReads`
- `frameSource`
- `frameAgeMs`
- `outcomeState`

`fullTreeReads` must remain zero for automatic production replay unless the caller explicitly selects `debug_full`. Metrics and logs never include raw screenshots, screen text, secrets, credentials, or unsanitized parameters.

## 14. Test And Emulator Pressure Plan

Unit and contract tests:

- Lifecycle transitions and invalid transitions.
- Drafts never match automatically.
- Activation occurs only after three consecutive validation successes.
- A validation failure resets the consecutive counter.
- Legacy migration does not auto-activate learned templates.
- Risk and text-input eligibility policy.
- Fixed per-step resolver policy compilation and revision immutability.
- Targeted validation of every action-dispatching fallback branch.
- Device-profile-scoped activation and incompatible-profile bypass.
- Compact tree generation, invalidation, uniqueness, and target reacquisition.
- Visual anchor matching across translation and supported scale variants.
- Fingerprint stability and transient-region masking.
- Normalized coordinate and inset conversion.
- Fresh, cached, and stale screenshot source enforcement.
- Single-arbiter and single-executor dispatch ownership.
- Durable action ledger transitions and restart recovery from `UNCERTAIN`.
- Retry, cancellation, timeout, busy, restart, and structured errors.
- Agent fallback starts at the failed step and does not repeat verified actions.

Emulator validation:

1. Establish Agent baseline for a safe navigation task.
2. Complete one Agent run and verify a `draft` is created.
3. Run three isolated validations and observe `0/3 -> 1/3 -> 2/3 -> active 3/3`.
4. Run native-view steps through `TREE_PREFERRED`, opaque surfaces through `VISION_REQUIRED`, and ambiguous test targets through `DUAL_CONFIRM`.
5. Force every declared fallback branch once before activation and verify an unvalidated fallback cannot dispatch.
6. Run the active template at least 30 times on the stable emulator.
7. Introduce stale trees, stale screenshots, duplicate labels, anchor displacement, delayed animation, an unexpected popup, orientation change, and an App restart.
8. Kill the process after `DISPATCHING` and verify restart produces `UNCERTAIN` without replay.
9. Force both semantic and visual resolution failures and verify partial Agent takeover.
10. Restart APKClaw between runs and verify lifecycle, ledger, and assets persist.
11. Submit concurrent work and verify task-busy behavior remains structured.
12. Verify accessibility-off and screenshot-failure responses.
13. Verify input and dangerous tasks remain Agent-only.

Acceptance targets on the stable emulator:

- Exactly three consecutive validations are required for activation.
- Activation on the emulator profile never activates the same revision on an incompatible physical-device profile.
- At least 29 of 30 active-template runs succeed without LLM use.
- All native-view replay attempts use the compact semantic channel before visual fallback unless their fixed policy says otherwise.
- Automatic replay never serializes a full tree.
- Cached or stale screenshots never authorize an action or satisfy post-action verification.
- An unvalidated fallback resolver never dispatches an action.
- Median tree-resolved step overhead excluding configured waits is below 250 ms on the stable emulator.
- Median visual-resolved step overhead is reported separately; no fixed target is accepted until fresh-frame cooldown behavior is measured.
- No failed verification causes an unproven side-effect action to repeat.
- Process death during dispatch produces `UNCERTAIN` and never automatically repeats the step.
- Process restart does not lose active/degraded state or validation progress.
- All failures return structured JSON and preserve existing security contracts.

## 15. Delivery Sequence

Implementation is divided into independently verifiable increments:

1. Lifecycle model, migration, and active-only matching.
2. Eligibility and risk policy.
3. Generation-tagged compact evidence provider and screenshot freshness metadata.
4. Trajectory recorder, selector bundle compiler, and fixed per-step policy assignment.
5. Durable action ledger and single-dispatch executor.
6. Visual matcher, fingerprints, and coordinate calibration.
7. Deterministic hybrid runner and semantic or visual verification.
8. Three-run validator and idle scheduling.
9. Degradation, uncertain-state reconciliation, partial Agent fallback, and revision creation.
10. API/SSE metrics and compatibility tests.
11. Full unit suite, release build, emulator promotion test, and 30-run pressure test.

Each increment must pass its focused tests before the next begins. No unrelated UI, installer, login, release, package, signature, TokenValidator, or Lumi protocol changes are included.
