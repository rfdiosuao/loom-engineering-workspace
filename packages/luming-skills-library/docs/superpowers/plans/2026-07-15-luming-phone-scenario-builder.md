# Luming Phone Scenario Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deliver `luming-phone-scenario-builder`, a LOOM/Luming Skill that safely explores a real mobile App before compiling verified navigation into a reusable scenario Skill, while explicitly reporting missing prerequisites.

**Architecture:** Use a two-phase Skill workflow: safe discovery produces an evidence-backed route and gap report, then compilation converts only verified route steps into a runnable Skill. Keep detailed schemas and generation templates in references, use JSON examples as executable contracts, and integrate the finished Skill into the existing local library without modifying LOOM product code.

**Tech Stack:** Markdown Skill instructions, YAML agent metadata, JSON contract examples, PowerShell validation/install/package scripts, Codex `skill-creator` utilities, Git.

## Global Constraints

- Exploration mode is exactly `safe_navigation`.
- Allow opening an App, ordinary navigation taps, tab changes, scrolling, non-sensitive search input, screenshots, screen reading, and back navigation.
- Stop before login submission, captcha, 2FA, permission grants, membership purchase, payment, publish, comment, private message, account mutation, deletion, or other irreversible actions.
- Never infer a button, page, route, or completion signal that was not observed on the selected phone.
- A route containing `unknown` steps or a `blocking` gap must never produce or register a runnable Skill.
- Preserve `resumeFrom` and re-check the prerequisite and current page before resuming.
- Keep product code and Skill authoring separate; do not modify LOOM Matrix, FastAPI, phone Agent, or desktop source files.
- Do not add third-party dependencies.

---

## File Map

Create:

- `tests/luming-phone-scenario-builder-contract.ps1`: deterministic contract test for required files, safety markers, and ready/blocked examples.
- `skills/luming-phone-scenario-builder/SKILL.md`: orchestration instructions and resource routing.
- `skills/luming-phone-scenario-builder/agents/openai.yaml`: Codex UI metadata.
- `skills/luming-phone-scenario-builder/references/discovery-contract.md`: safe actions, states, gap codes, route-step fields, and output schemas.
- `skills/luming-phone-scenario-builder/references/generated-skill-template.md`: exact structure for scenario Skills generated from verified routes.
- `skills/luming-phone-scenario-builder/examples/discovery-ready.json`: successful exploration contract.
- `skills/luming-phone-scenario-builder/examples/discovery-blocked.json`: missing membership contract with checkpoint.

Modify:

- `scripts/validate.ps1`: validate Skill structure, parse all example JSON files, and run repository contract tests.
- `manifest.json`: register the fifth Skill under `scenario-authoring`.
- `README.md`: list the new Skill in the included-Skills table.

Generated during delivery and not committed:

- `dist/luming-skills-library-20260715.zip`
- `%USERPROFILE%\.codex\skills\luming-phone-scenario-builder\`

### Task 1: Add the failing behavior contract

**Files:**

- Create: `tests/luming-phone-scenario-builder-contract.ps1`

**Interfaces:**

- Consumes: repository root resolved from `$PSScriptRoot`.
- Produces: exit code `0` and `luming-phone-scenario-builder contract ok` only when the package, markers, and JSON examples satisfy the contract.

- [ ] **Step 1: Create the contract test**

Create `tests/luming-phone-scenario-builder-contract.ps1` with this content:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillRoot = Join-Path $repoRoot "skills\luming-phone-scenario-builder"

$requiredFiles = @(
  "SKILL.md",
  "agents\openai.yaml",
  "references\discovery-contract.md",
  "references\generated-skill-template.md",
  "examples\discovery-ready.json",
  "examples\discovery-blocked.json"
)

foreach ($relativePath in $requiredFiles) {
  $fullPath = Join-Path $skillRoot $relativePath
  if (-not (Test-Path -LiteralPath $fullPath)) {
    throw "Missing required file: $relativePath"
  }
}

$skillText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "SKILL.md")
$requiredMarkers = @(
  "safe_navigation",
  "blocked_by_prerequisite",
  "resumeFrom",
  "membership_required",
  "unsafe_action_required",
  "Do not modify LOOM product code"
)

foreach ($marker in $requiredMarkers) {
  if (-not $skillText.Contains($marker)) {
    throw "SKILL.md is missing marker: $marker"
  }
}

$readyPath = Join-Path $skillRoot "examples\discovery-ready.json"
$blockedPath = Join-Path $skillRoot "examples\discovery-blocked.json"
$ready = Get-Content -Raw -Encoding UTF8 -LiteralPath $readyPath | ConvertFrom-Json
$blocked = Get-Content -Raw -Encoding UTF8 -LiteralPath $blockedPath | ConvertFrom-Json

if ($ready.schema -ne "loom.phone-scenario.discovery.v1") {
  throw "Ready example has the wrong schema"
}
if ($ready.mode -ne "safe_navigation" -or -not $ready.runnable) {
  throw "Ready example must be runnable safe_navigation"
}
if (@($ready.route | Where-Object { $_.verification -ne "verified" }).Count -ne 0) {
  throw "Ready example contains an unverified route step"
}
if ($blocked.status -ne "blocked_by_prerequisite" -or $blocked.runnable) {
  throw "Blocked example must be non-runnable"
}
if (@($blocked.missing | Where-Object { $_.severity -eq "blocking" }).Count -eq 0) {
  throw "Blocked example must contain a blocking gap"
}
if (-not $blocked.resumeFrom) {
  throw "Blocked example must preserve resumeFrom"
}

Write-Output "luming-phone-scenario-builder contract ok"
```

- [ ] **Step 2: Run the contract test to verify the red state**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-phone-scenario-builder-contract.ps1
```

Expected: command fails with `Missing required file: SKILL.md` because the new Skill does not exist yet.

- [ ] **Step 3: Commit the red contract**

```powershell
git add -- tests/luming-phone-scenario-builder-contract.ps1
git commit -m "test: define phone scenario builder contract"
```

Expected: one new test file is committed.

### Task 2: Initialize the Skill and implement the orchestration workflow

**Files:**

- Create: `skills/luming-phone-scenario-builder/SKILL.md`
- Create: `skills/luming-phone-scenario-builder/agents/openai.yaml`

**Interfaces:**

- Consumes: `goal`, `app_name`, optional `device_id`, optional `entry_hint`, `expected_result`, and optional `confirmation_boundary`.
- Produces: a discovery result matching `loom.phone-scenario.discovery.v1`, then either a blocked report or a generated scenario Skill candidate.

- [ ] **Step 1: Initialize the Skill package**

Run:

```powershell
$env:PYTHONUTF8 = "1"
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\init_skill.py" luming-phone-scenario-builder --path .\skills --resources references --interface 'display_name=麓鸣手机场景生成器' --interface 'short_description=先安全探索手机 App，再把真实路径生成可执行 Skill' --interface 'default_prompt=Use $luming-phone-scenario-builder to safely explore a real mobile App, report missing prerequisites, and compile only verified steps into a reusable LOOM/Luming Skill.'
```

Expected: the Skill directory, `SKILL.md`, `agents/openai.yaml`, and `references/` are created.

- [ ] **Step 2: Replace `SKILL.md` with the complete workflow**

Write these exact frontmatter values:

```yaml
---
name: luming-phone-scenario-builder
description: Use when a user asks LOOM/Luming/麓鸣 to explore a real mobile App and generate an application-scenario Skill from observed phone steps, including requests such as "先探索 App 再生成 Skill", "我想让手机 Agent 完成这个任务", or "缺账号、会员、App 和权限时要报告". Covers safe navigation, prerequisite discovery, evidence-backed route mapping, resumable blockers, and compilation of verified steps into a reusable Skill.
---
```

The body must implement this ordered workflow:

1. Enforce the Skill-only boundary with the literal sentence `Do not modify LOOM product code`.
2. Normalize the six input fields and ask only for missing values that change the exploration route.
3. Resolve phone-control commands through `loom-command-brain` or `openclaw-cli` when real execution is requested; never invent command names.
4. Run phone/App/network/account preflight before navigation.
5. Explore in `safe_navigation` using the allowlist and the 40-action/15-minute default budget.
6. Capture before/after screenshots or screen reads for every action and fingerprint visited pages.
7. Classify blockers with the contract reference and return `blocked_by_prerequisite` plus `resumeFrom`.
8. Validate each route step as `verified` or `unknown`.
9. Compile only an all-verified, non-blocked route with the generated-Skill template.
10. Keep blocked drafts outside `skills/` and `manifest.json`.
11. Require human confirmation before every risky action.
12. Return artifact locations, gap summary, verification result, and whether the generated Skill is runnable.

Add a `Resources` section that directly links:

```markdown
- Read `references/discovery-contract.md` before exploration or when classifying a gap.
- Read `references/generated-skill-template.md` only after the route is fully verified and compilation can begin.
- Use `examples/discovery-ready.json` and `examples/discovery-blocked.json` to validate result shape.
```

- [ ] **Step 3: Verify generated agent metadata**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 .\skills\luming-phone-scenario-builder\agents\openai.yaml
```

Expected: `display_name`, `short_description`, and `default_prompt` match the values passed to `init_skill.py`, and the default prompt references `$luming-phone-scenario-builder`.

- [ ] **Step 4: Run the Skill structure validator**

Run:

```powershell
$env:PYTHONUTF8 = "1"
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" .\skills\luming-phone-scenario-builder
```

Expected: `Skill is valid!`

- [ ] **Step 5: Commit the Skill entry point**

```powershell
git add -- skills/luming-phone-scenario-builder/SKILL.md skills/luming-phone-scenario-builder/agents/openai.yaml
git commit -m "feat: add phone scenario builder workflow"
```

Expected: the Skill instructions and agent metadata are committed.

### Task 3: Add discovery contracts, generation template, and examples

**Files:**

- Create: `skills/luming-phone-scenario-builder/references/discovery-contract.md`
- Create: `skills/luming-phone-scenario-builder/references/generated-skill-template.md`
- Create: `skills/luming-phone-scenario-builder/examples/discovery-ready.json`
- Create: `skills/luming-phone-scenario-builder/examples/discovery-blocked.json`

**Interfaces:**

- Consumes: observed phone state, page evidence, action edges, and prerequisite failures from Task 2.
- Produces: stable state names, blocker codes, route-step fields, result JSON, and a scenario-Skill skeleton.

- [ ] **Step 1: Write the discovery contract reference**

Define these exact state values:

```text
collecting_inputs
preflight
exploring
blocked_by_prerequisite
explored
compiling
draft
ready
```

Define these exact blocker codes:

```text
device_offline
app_missing
account_missing
login_required
session_expired
captcha_required
two_factor_required
membership_required
payment_required
permission_required
network_unavailable
region_restricted
app_version_unsupported
target_data_missing
unsupported_ui
unsafe_action_required
exploration_budget_exhausted
```

Define the route-step fields as `stepId`, `precondition`, `expectedScreen`, `action`, `successSignal`, `evidence`, `verification`, `failureCode`, `recovery`, and `requiresConfirmation`. State explicitly that `verification` is only `verified` or `unknown`, and `unknown` is forbidden in a runnable route.

Define every gap object with `type`, `severity`, `observedAt`, `evidence`, `impact`, `requiredAction`, and `resumeFrom`. State that the Agent must re-check the gap and current page before continuing from a saved checkpoint.

- [ ] **Step 2: Write the generated-Skill template reference**

The template must require:

```text
YAML frontmatter with name and concrete trigger description
Overview and scenario identity
Verified prerequisites
Inputs and selected device
Safe execution mode
Numbered route with one phone action per step
Expected screen and success signal per step
Failure classification and recovery per step
Human-confirmation gates
Evidence and output JSON
Verification checklist
Template-memory recommendation only after stable repeated runs
```

Include a compiler gate that rejects generation when `runnable` is false, `missing` contains a blocking item, or any route step is `unknown`.

- [ ] **Step 3: Add the ready example**

Create a valid `loom.phone-scenario.discovery.v1` object with `mode: safe_navigation`, `status: explored`, `runnable: true`, an empty `missing` array, and two `verified` route steps: opening the App and opening a visible search page. Each step must include every route-step field and at least one evidence reference.

- [ ] **Step 4: Add the blocked example**

Create a valid `loom.phone-scenario.discovery.v1` object with `mode: safe_navigation`, `status: blocked_by_prerequisite`, `runnable: false`, `resumeFrom: export_page`, and one blocking `membership_required` item containing all gap fields. Its route may contain verified navigation to the export page but must not contain a purchase or confirmation action.

- [ ] **Step 5: Run the contract test to verify the green state**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-phone-scenario-builder-contract.ps1
```

Expected: `luming-phone-scenario-builder contract ok`.

- [ ] **Step 6: Parse both examples independently**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 .\skills\luming-phone-scenario-builder\examples\discovery-ready.json | ConvertFrom-Json | Out-Null
Get-Content -Raw -Encoding UTF8 .\skills\luming-phone-scenario-builder\examples\discovery-blocked.json | ConvertFrom-Json | Out-Null
Write-Output "phone scenario examples json ok"
```

Expected: `phone scenario examples json ok`.

- [ ] **Step 7: Commit the contracts and examples**

```powershell
git add -- skills/luming-phone-scenario-builder/references skills/luming-phone-scenario-builder/examples
git commit -m "feat: define phone discovery contracts"
```

Expected: both references and both JSON examples are committed.

### Task 4: Integrate library validation and catalog metadata

**Files:**

- Modify: `scripts/validate.ps1`
- Modify: `manifest.json`
- Modify: `README.md`

**Interfaces:**

- Consumes: every `skills/*` directory, every `skills/*/examples/*.json` file, and every `tests/*-contract.ps1` file.
- Produces: JSON validation results after all validators and contract tests pass; any failure returns a non-zero exit code.

- [ ] **Step 1: Extend repository validation**

After the existing Skill validation loop, add these exact validation loops before the final `ConvertTo-Json` output:

```powershell
Get-ChildItem -LiteralPath $skillsRoot -Recurse -File -Filter "*.json" |
  Where-Object { $_.FullName -match "[\\/]examples[\\/]" } |
  ForEach-Object {
    Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName | ConvertFrom-Json | Out-Null
    $results += [pscustomobject]@{
      skill = $_.Directory.Parent.Name
      output = "JSON example is valid: $($_.Name)"
    }
  }

$testsRoot = Join-Path $repoRoot "tests"
if (Test-Path -LiteralPath $testsRoot) {
  Get-ChildItem -LiteralPath $testsRoot -File -Filter "*-contract.ps1" | ForEach-Object {
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $_.FullName
    $results += [pscustomobject]@{
      skill = $_.BaseName
      output = ($output -join "`n")
    }
  }
}
```

- [ ] **Step 2: Register the Skill in `manifest.json`**

Append this exact object to the `skills` array and keep the JSON valid:

```json
{
  "name": "luming-phone-scenario-builder",
  "path": "skills/luming-phone-scenario-builder",
  "category": "scenario-authoring",
  "summary": "Safely explore real mobile Apps, report missing prerequisites, and compile verified routes into reusable LOOM/Luming Skills."
}
```

Keep `version` and `updatedAt` at `2026.07.15` and `2026-07-15` respectively.

- [ ] **Step 3: Add the README catalog row**

Add this row to `Included Skills`:

```markdown
| `luming-phone-scenario-builder` | 先安全探索真实手机 App，报告账号、会员、安装和权限缺口，再生成逐步可执行 Skill |
```

- [ ] **Step 4: Run full repository validation**

Run:

```powershell
.\scripts\validate.ps1
```

Expected: five Skill validator entries report `Skill is valid!`, both new examples report valid JSON, and the phone-scenario contract reports `luming-phone-scenario-builder contract ok`.

- [ ] **Step 5: Validate the manifest independently**

Run:

```powershell
$manifest = Get-Content -Raw -Encoding UTF8 .\manifest.json | ConvertFrom-Json
if (@($manifest.skills | Where-Object name -eq "luming-phone-scenario-builder").Count -ne 1) { throw "manifest registration mismatch" }
Write-Output "manifest registration ok"
```

Expected: `manifest registration ok`.

- [ ] **Step 6: Commit library integration**

```powershell
git add -- scripts/validate.ps1 manifest.json README.md
git commit -m "chore: register phone scenario builder"
```

Expected: validation and catalog changes are committed.

### Task 5: Install, package, and verify delivery

**Files:**

- Verify: `%USERPROFILE%\.codex\skills\luming-phone-scenario-builder\SKILL.md`
- Generate: `dist/luming-skills-library-20260715.zip`

**Interfaces:**

- Consumes: the complete five-Skill library.
- Produces: a locally installed discoverable Skill and a delivery archive containing all five Skills.

- [ ] **Step 1: Install the library into the local Codex Skill directory**

Run:

```powershell
.\scripts\install.ps1
```

Expected: the JSON output lists `luming-phone-scenario-builder` in `installed` and the destination is `%USERPROFILE%\.codex\skills` unless `CODEX_HOME` overrides it.

- [ ] **Step 2: Validate the installed Skill**

Run:

```powershell
$env:PYTHONUTF8 = "1"
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" "$env:USERPROFILE\.codex\skills\luming-phone-scenario-builder"
```

Expected: `Skill is valid!`.

- [ ] **Step 3: Build the delivery archive**

Run:

```powershell
.\scripts\package.ps1
```

Expected: `dist/luming-skills-library-20260715.zip` is created with a non-zero length.

- [ ] **Step 4: Verify archive contents and checksum**

Run:

```powershell
$zip = Resolve-Path .\dist\luming-skills-library-20260715.zip
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
  $entry = $archive.Entries | Where-Object FullName -eq "skills/luming-phone-scenario-builder/SKILL.md"
  if (-not $entry) { throw "Packaged Skill entry is missing" }
} finally {
  $archive.Dispose()
}
Get-FileHash -Algorithm SHA256 -LiteralPath $zip
```

Expected: the new `SKILL.md` entry exists and a SHA256 hash is printed.

- [ ] **Step 5: Run final clean verification**

Run:

```powershell
.\scripts\validate.ps1
git diff --check
git status --short
```

Expected: validation passes, `git diff --check` prints nothing, and `git status --short` is empty because `dist/` is ignored.

- [ ] **Step 6: Record delivery result**

Report the installed Skill path, library path, package path, package SHA256, five-Skill validation result, and the fact that no LOOM product code was changed.
