# Luming Unified Phone Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five independently triggered Luming Skills with one `luming-phone-agent` that self-checks the environment, discovers phones, asks for the task, safely builds or reuses a verified recipe, and synchronizes successful recipes for future runs.

**Architecture:** One installable Skill owns a lean orchestration entrypoint, focused reference modules, JSON Schema-backed recipes, and a transactional recipe synchronizer. The repository manifest and installer treat the five old Skill names as exact migration targets, while preserving every unrelated local Skill.

**Tech Stack:** Markdown Skills, JSON/JSON Schema Draft 2020-12, Python 3.11 with `jsonschema` 4.x, Windows PowerShell 5.1, Git, existing Codex `quick_validate.py`.

## Global Constraints

- Do not modify LOOM product backend files, FastAPI routes, Matrix scheduler code, phone Agent code, Feishu integration code, or CLI implementation.
- Only `luming-phone-agent` may remain as an installable and triggerable Luming Skill.
- Runtime order is `SELF_CHECK -> PHONE_DISCOVERY -> ASK_TASK -> RECIPE_MATCH -> PREFLIGHT -> REUSE_OR_EXPLORE -> PLAN -> EXECUTE_VERIFY -> SYNC_RECIPE -> REPORT`.
- A recipe is reusable only when `status` is `verified`, `verification.successCount >= 1`, and every route step is evidence-backed.
- Login submission, captcha, 2FA, permission grants, membership purchase, payment, publish, comment, private message, deletion, rejection, account mutation, and other irreversible actions are hard stops.
- Never persist passwords, tokens, verification codes, phone numbers, contact details, raw resumes, or unrelated personal data in recipes.
- Automatic environment repair is limited to local directories, non-secret templates, path metadata, safe local-service startup, and side-effect-free retries.
- The installer may remove only the five exact legacy names declared in `manifest.json`; all unrelated installed Skills and sibling files must survive.
- Use strict TDD for every behavior change and commit after each task is green.

---

## File Map

### Unified Skill

- `skills/luming-phone-agent/SKILL.md`: only trigger entrypoint and ordered runtime state machine.
- `skills/luming-phone-agent/agents/openai.yaml`: display metadata for the single Skill.
- `skills/luming-phone-agent/references/environment-preflight.md`: self-check output, safe repair allowlist, and human blockers.
- `skills/luming-phone-agent/references/phone-discovery.md`: single/multi-phone discovery and task-question contract.
- `skills/luming-phone-agent/references/safe-navigation.md`: exploration budgets, evidence, blockers, hard stops, and resume checks.
- `skills/luming-phone-agent/references/task-compiler.md`: task plan and recipe promotion rules.
- `skills/luming-phone-agent/references/matrix-supervision.md`: one-dispatch event-first multi-phone supervision.
- `skills/luming-phone-agent/references/builtin-playbooks.md`: migrated BOSS screening and acquisition rules.
- `skills/luming-phone-agent/references/recipe-sync-contract.md`: source/installed synchronization and `sync_pending` behavior.
- `skills/luming-phone-agent/schemas/recipe.schema.json`: recipe validation contract.
- `skills/luming-phone-agent/schemas/recipe-index.schema.json`: recipe registry validation contract.
- `skills/luming-phone-agent/recipes/index.json`: built-in and learned recipe registry.
- `skills/luming-phone-agent/recipes/boss-resume-screening/recipe.json`: built-in draft playbook.
- `skills/luming-phone-agent/recipes/acquisition/recipe.json`: built-in draft playbook.
- `skills/luming-phone-agent/scripts/sync_recipe.py`: lock, sanitize, schema validation, atomic dual write, rollback, and hash verification.
- `skills/luming-phone-agent/examples/*.json`: ready/blocked self-check, task plan, and sync result examples.

### Repository Integration

- `manifest.json`: one active Skill plus exact `replaces` list.
- `README.md`: one-Skill install, workflow, recipe memory, and migration docs.
- `scripts/install.ps1`: install one Skill, write source metadata, remove exact legacy targets, verify parity.
- `scripts/package.ps1`: package the one-Skill library without old or nested archives.
- `scripts/validate.ps1`: validate every JSON file under the unified Skill and run all contracts.
- `tests/luming-phone-agent-contract.ps1`: orchestration, safety, built-in migration, and acceptance contract.
- `tests/luming-recipe-sync-contract.ps1`: verified promotion, schema, redaction, concurrency, parity, and failure behavior.
- `tests/luming-skills-install-contract.ps1`: one-Skill install and exact legacy cleanup.
- `tests/luming-skills-package-contract.ps1`: one triggerable Skill and forward-slash package paths.

### Removed Legacy Sources

- `skills/luming-acquisition-agent/`
- `skills/luming-boss-resume-screening/`
- `skills/luming-matrix-supervisor-loop/`
- `skills/luming-phone-scenario-builder/`
- `skills/luming-scenario-skill-writer/`
- `tests/luming-phone-scenario-builder-contract.ps1`
- Generated `skills/luming-phone-scenario-builder.zip` when present.

---

### Task 1: Build The Unified Orchestration Skill

**Files:**
- Create: `tests/luming-phone-agent-contract.ps1`
- Create: `skills/luming-phone-agent/SKILL.md`
- Create: `skills/luming-phone-agent/agents/openai.yaml`
- Create: `skills/luming-phone-agent/references/environment-preflight.md`
- Create: `skills/luming-phone-agent/references/phone-discovery.md`
- Create: `skills/luming-phone-agent/references/safe-navigation.md`
- Create: `skills/luming-phone-agent/references/task-compiler.md`
- Create: `skills/luming-phone-agent/references/matrix-supervision.md`
- Create: `skills/luming-phone-agent/references/builtin-playbooks.md`
- Create: `skills/luming-phone-agent/references/recipe-sync-contract.md`
- Create: `skills/luming-phone-agent/examples/self-check-ready.json`
- Create: `skills/luming-phone-agent/examples/self-check-blocked.json`
- Create: `skills/luming-phone-agent/examples/task-plan.json`
- Create: `skills/luming-phone-agent/examples/sync-result.json`

**Interfaces:**
- Consumes: design specification `docs/superpowers/specs/2026-07-15-luming-unified-phone-agent-design.md` and rules in the five legacy Skills.
- Produces: ordered state names, `loom.phone-agent.self-check.v1`, `loom.phone-agent.task-plan.v1`, and the safety/promotion rules used by later tasks.

- [ ] **Step 1: Write the failing orchestration contract**

Create a PowerShell contract that asserts the directory exists, `SKILL.md` contains every state in exact order, each reference link resolves, examples parse, the hard-stop list is complete, and the acceptance table binds all fourteen design cases to concrete outcomes.

```powershell
$states = @(
  "SELF_CHECK", "PHONE_DISCOVERY", "ASK_TASK", "RECIPE_MATCH",
  "PREFLIGHT", "REUSE_OR_EXPLORE", "PLAN", "EXECUTE_VERIFY",
  "SYNC_RECIPE", "REPORT"
)
$cursor = -1
foreach ($state in $states) {
  $next = $skillText.IndexOf($state, $cursor + 1, [StringComparison]::Ordinal)
  if ($next -lt 0) { throw "Missing or out-of-order state: $state" }
  $cursor = $next
}

$hardStops = @(
  "login submission", "captcha", "2FA", "permission grant",
  "membership purchase", "payment", "publish", "comment",
  "private message", "deletion", "candidate rejection", "account mutation"
)
foreach ($marker in $hardStops) {
  if (-not $skillText.Contains($marker)) { throw "Missing hard stop: $marker" }
}
```

The test must also assert that `ASK_TASK` follows phone discovery, one healthy phone is auto-selected, multiple phones require a single/matrix decision when the task did not already decide it, and three unchanged page fingerprints stop exploration.

- [ ] **Step 2: Run the focused contract and verify RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-phone-agent-contract.ps1
```

Expected: exit `1` with `Unified Skill directory is missing`.

- [ ] **Step 3: Write the unified Skill and focused modules**

Use this frontmatter and keep the entrypoint under 5,000 words:

```yaml
---
name: luming-phone-agent
description: Use when a user asks LOOM/Luming/麓鸣 to operate one or more phones, discover what phones can do, build a new mobile App task, reuse a previously verified task recipe, supervise a phone matrix, screen BOSS直聘 resumes, run acquisition work, or report missing App/account/login/membership/permission prerequisites.
---
```

The body must command the agent to load only the reference needed for the current state, never invent CLI commands, and emit this terminal summary:

```json
{
  "schema": "loom.phone-agent.run-result.v1",
  "status": "completed|blocked|needs_human|failed",
  "selfCheck": "ready|blocked",
  "selectedDevices": [],
  "task": {},
  "recipe": {"match": "none|reused|stale|created", "sync": "not_needed|synced|sync_pending"},
  "evidence": [],
  "resumeFrom": null
}
```

Move the detailed legacy behavior into the seven reference files. BOSS and acquisition must remain draft-only/human-review workflows until real routes are verified. Matrix supervision must use one dispatch, event watch, light health polling, and abnormal-device-only diagnosis.

- [ ] **Step 4: Add valid examples and run GREEN**

Every example must have a unique schema and strict JSON Boolean fields. Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-phone-agent-contract.ps1
.\scripts\validate.ps1
```

Expected: `luming-phone-agent contract ok`; repository validation may still include the five legacy Skills but must otherwise pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/luming-phone-agent-contract.ps1 skills/luming-phone-agent
git commit -m "feat: add unified Luming phone agent"
```

---

### Task 2: Add Recipe Schemas And Transactional Synchronization

**Files:**
- Create: `tests/luming-recipe-sync-contract.ps1`
- Create: `skills/luming-phone-agent/schemas/recipe.schema.json`
- Create: `skills/luming-phone-agent/schemas/recipe-index.schema.json`
- Create: `skills/luming-phone-agent/recipes/index.json`
- Create: `skills/luming-phone-agent/recipes/boss-resume-screening/recipe.json`
- Create: `skills/luming-phone-agent/recipes/acquisition/recipe.json`
- Create: `skills/luming-phone-agent/scripts/sync_recipe.py`
- Modify: `skills/luming-phone-agent/references/recipe-sync-contract.md`
- Modify: `skills/luming-phone-agent/references/task-compiler.md`

**Interfaces:**
- Consumes: `verified` recipe JSON, `--source-skill-root`, `--installed-skill-root`, and `--state-root`.
- Produces: JSON stdout with `schema=loom.phone-agent.recipe-sync.v1`, `status=synced|sync_pending|rejected`, hashes, redactions, and transaction path.

- [ ] **Step 1: Write the failing recipe sync contract**

The test creates isolated source, installed, and state roots; creates a valid verified recipe with one successful run; includes a `password` key and a Chinese mobile number in evidence; then invokes:

```powershell
python .\skills\luming-phone-agent\scripts\sync_recipe.py `
  --recipe-file $recipeFile `
  --source-skill-root $sourceRoot `
  --installed-skill-root $installedRoot `
  --state-root $stateRoot
```

Assert:

```powershell
if ($result.status -cne "synced") { throw "Recipe did not sync" }
if ($sourceText -match 'password|138\d{8}') { throw "Sensitive data persisted" }
if ((Get-FileHash $sourceRecipe).Hash -cne (Get-FileHash $installedRecipe).Hash) {
  throw "Source and installed recipe hashes differ"
}
```

Run two processes concurrently with distinct recipe IDs. Both must exit `0`, both recipes must appear once in the index, and the index must parse. Also verify draft, zero-success, unknown-step, and schema-invalid recipes return nonzero without changing either target.

- [ ] **Step 2: Run the focused contract and verify RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-recipe-sync-contract.ps1
```

Expected: exit `1` because `sync_recipe.py` and schemas do not exist.

- [ ] **Step 3: Define strict Draft 2020-12 schemas**

The recipe schema must require these top-level fields and reject unknown status values:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "required": ["schema", "recipeId", "name", "aliases", "status", "app", "goal", "mode", "prerequisites", "steps", "safety", "verification", "source"],
  "properties": {
    "schema": {"const": "loom.phone-agent.recipe.v1"},
    "status": {"enum": ["draft", "verified", "stale", "blocked"]},
    "mode": {"enum": ["single", "matrix"]}
  }
}
```

Require `steps[*].verification` to be `verified|unknown`, `steps[*].requiresConfirmation` to be a JSON Boolean, and `verification.successCount` to be a non-negative integer. The index schema must require unique `recipeId` values through the syncer's semantic check.

- [ ] **Step 4: Implement the synchronizer**

Implement these exact Python interfaces: `load_json(path: Path) -> dict`, `validate_document(document: dict, schema_path: Path) -> None`, `sanitize_recipe(recipe: dict) -> tuple[dict, list[str]]`, `assert_promotable(recipe: dict) -> None`, `acquire_lock(lock_path: Path, timeout_seconds: float = 15.0) -> int`, `atomic_write_json(path: Path, document: dict) -> None`, `update_index(index: dict, recipe: dict, relative_path: str) -> dict`, `sync_recipe(recipe: dict, source_root: Path, installed_root: Path, state_root: Path) -> dict`, and `main(argv: list[str] | None = None) -> int`.

Use `jsonschema.Draft202012Validator`. Acquire the lock with this exclusive operation and retry it until the bounded deadline:

```python
lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
```

Write UTF-8 JSON to a same-directory temporary file, call `flush()` and `os.fsync()`, then use `os.replace`. Back up affected recipe and index files in the transaction directory and restore them if either root fails. Update the recipe first and index last. Compare SHA256 for the synchronized recipe and index before returning `synced`.

Sanitization must remove keys named `password`, `passcode`, `token`, `secret`, `captcha`, `otp`, `verificationCode`, `phoneNumber`, `email`, `wechat`, or `idCard`, and replace Chinese mobile-number and email patterns in free text with `[REDACTED]`. Preserve `deviceId` and non-secret page fingerprints.

- [ ] **Step 5: Add built-in draft recipes and run GREEN**

Register `boss-resume-screening` and `acquisition` with `status: draft`, `successCount: 0`, and `source.kind: builtin`. Their safety blocks must preserve human review and outbound-action stops.

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-recipe-sync-contract.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-phone-agent-contract.ps1
.\scripts\validate.ps1
```

Expected: both focused contracts pass; all unified JSON files parse and validate.

- [ ] **Step 6: Commit**

```powershell
git add tests/luming-recipe-sync-contract.ps1 skills/luming-phone-agent
git commit -m "feat: add verified recipe memory"
```

---

### Task 3: Migrate Installation To One Managed Skill

**Files:**
- Modify: `manifest.json`
- Modify: `scripts/install.ps1`
- Modify: `tests/luming-skills-install-contract.ps1`

**Interfaces:**
- Consumes: manifest `skills` array with one item and top-level `replaces` array with five exact names.
- Produces: installer JSON with `installed`, `removed`, `destination`, and `sourceMetadata`; writes `%USERPROFILE%\.luming\phone-agent\source.json` or the supplied `-StateRoot` equivalent.

- [ ] **Step 1: Extend the installer contract first**

Create a temp destination containing stale copies of all five legacy Skills, a stale `luming-phone-agent`, and `unowned-sentinel/keep.txt`. Invoke the installer with an isolated state root:

```powershell
& powershell -NoProfile -ExecutionPolicy Bypass -File $installScript `
  -Destination $destination `
  -StateRoot $stateRoot
```

Assert exact sets:

```powershell
Assert-StringSetEqual -Expected @("luming-phone-agent") -Actual @($result.installed)
Assert-StringSetEqual -Expected $legacyNames -Actual @($result.removed)
if (-not (Test-Path "$destination\unowned-sentinel\keep.txt")) {
  throw "Installer removed unowned content"
}
```

Verify the installed unified Skill recursively matches source hashes, all five legacy paths are absent, and `source.json` contains absolute source and installed roots without credentials.

- [ ] **Step 2: Run the installer contract and verify RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-skills-install-contract.ps1
```

Expected: exit `1` because `-StateRoot`, `removed`, and one-Skill migration are not implemented.

- [ ] **Step 3: Update manifest and installer**

Use this manifest shape:

```json
{
  "name": "luming-skills-library",
  "displayName": "麓鸣 Skills Library",
  "version": "2026.07.15",
  "schema": "loom.skills.library.v2",
  "updatedAt": "2026-07-15",
  "skillsRoot": "skills",
  "replaces": [
    "luming-acquisition-agent",
    "luming-boss-resume-screening",
    "luming-matrix-supervisor-loop",
    "luming-phone-scenario-builder",
    "luming-scenario-skill-writer"
  ],
  "skills": [
    {
      "name": "luming-phone-agent",
      "path": "skills/luming-phone-agent",
      "category": "phone-agent-orchestration",
      "summary": "Self-check, discover phones, build or reuse verified tasks, supervise execution, and remember successful recipes."
    }
  ]
}
```

Add `[string]$StateRoot` to `install.ps1`. Read managed source directories from `manifest.skills` instead of every child directory. Complete staging and parity verification for `luming-phone-agent`, then remove only direct-child targets named by `manifest.replaces`. Atomically write:

```json
{
  "schema": "loom.phone-agent.source.v1",
  "sourceSkillRoot": "D:/Axiangmu/U盘启动器/luming-skills-library/skills/luming-phone-agent",
  "installedSkillRoot": "C:/Users/Administrator/.codex/skills/luming-phone-agent"
}
```

Do not remove legacy targets until the unified target passes parity.

- [ ] **Step 4: Run GREEN and regression checks**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-skills-install-contract.ps1
.\scripts\validate.ps1
git diff --check
```

Expected: installer contract passes; unowned sentinel survives; all prior unified contracts pass.

- [ ] **Step 5: Commit**

```powershell
git add manifest.json scripts/install.ps1 tests/luming-skills-install-contract.ps1
git commit -m "feat: migrate installer to unified phone agent"
```

---

### Task 4: Remove Legacy Triggers And Enforce A One-Skill Package

**Files:**
- Modify: `README.md`
- Modify: `scripts/package.ps1`
- Modify: `scripts/validate.ps1`
- Modify: `tests/luming-skills-package-contract.ps1`
- Delete: `tests/luming-phone-scenario-builder-contract.ps1`
- Delete: all tracked files below the five legacy Skill directories.
- Delete: `skills/luming-phone-scenario-builder.zip` when present.

**Interfaces:**
- Consumes: `manifest.json` v2 and `skills/luming-phone-agent`.
- Produces: a ZIP with one top-level Skill directory and no legacy names or nested ZIP files.

- [ ] **Step 1: Tighten the package contract before deletion**

Assert the source tree and archive each contain exactly one directory matching `skills/*/SKILL.md`, that its name is `luming-phone-agent`, that no `manifest.replaces` name appears under `skills/`, and that no archive entry ends in `.zip`.

```powershell
$skillEntries = @($entries | Where-Object { $_.FullName -match '^skills/[^/]+/SKILL\.md$' })
if ($skillEntries.Count -ne 1 -or $skillEntries[0].FullName -cne 'skills/luming-phone-agent/SKILL.md') {
  throw "Package must contain exactly one triggerable Luming Skill"
}
if (@($entries | Where-Object { $_.FullName -match '\.zip$' }).Count -ne 0) {
  throw "Nested ZIP artifacts are forbidden"
}
```

- [ ] **Step 2: Run the package contract and verify RED**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-skills-package-contract.ps1
```

Expected: exit `1` because five legacy Skill directories still exist.

- [ ] **Step 3: Remove legacy sources and update library scripts**

Delete only the paths listed in this task. Update `README.md` to document the unified lifecycle, recipe statuses, and migration. Update `package.ps1` to package only Skill paths declared by `manifest.skills`, not arbitrary files under `skills/`. Update `validate.ps1` to:

- assert exactly one manifest Skill and exact directory parity with `skills/`;
- parse and validate every JSON document under the unified Skill;
- invoke `sync_recipe.py --check-environment` to confirm Python and `jsonschema` availability;
- continue running every `*-contract.ps1` and checking child exit codes.

- [ ] **Step 4: Run full GREEN**

```powershell
.\scripts\validate.ps1
.\scripts\package.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-skills-package-contract.ps1
git diff --check
```

Expected output includes one valid Skill, all unified JSON documents valid, four contract tests passing, zero backslash entries, zero nested ZIP entries, and exactly one `skills/luming-phone-agent/SKILL.md` entry.

- [ ] **Step 5: Commit**

```powershell
git add README.md scripts/package.ps1 scripts/validate.ps1 tests skills manifest.json
git commit -m "refactor: consolidate Luming skills into one agent"
```

---

### Task 5: Install, Package, And Verify The Unified Delivery

**Files:**
- Generated: `dist/luming-skills-library-20260715.zip` (ignored delivery artifact)
- Installed: `%USERPROFILE%\.codex\skills\luming-phone-agent`
- Removed installed targets: the five exact legacy Skill directories.

**Interfaces:**
- Consumes: committed repository HEAD after Tasks 1-4.
- Produces: installed unified Skill, source metadata, final ZIP, validation evidence, byte length, and SHA256.

- [ ] **Step 1: Run the full repository validator from committed HEAD**

```powershell
.\scripts\validate.ps1
git diff --check
git status --short
```

Expected: one Skill valid, all JSON documents valid, all four contracts pass, no tracked changes.

- [ ] **Step 2: Install the unified Skill and verify migration**

```powershell
.\scripts\install.ps1
```

Expected installer JSON:

```json
{
  "installed": ["luming-phone-agent"],
  "removed": [
    "luming-acquisition-agent",
    "luming-boss-resume-screening",
    "luming-matrix-supervisor-loop",
    "luming-phone-scenario-builder",
    "luming-scenario-skill-writer"
  ]
}
```

Run `quick_validate.py` with `PYTHONUTF8=1` against the installed Skill. Recursively compare source and installed relative file sets and SHA256 hashes. Confirm all five old installed paths are absent.

- [ ] **Step 3: Build and inspect the final ZIP**

```powershell
.\scripts\package.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\luming-skills-package-contract.ps1
```

Open the archive with `.NET ZipFile`, assert zero backslash entries, one triggerable Skill, no legacy names, and byte-for-byte parity for every unified Skill file. Record ZIP byte length and SHA256.

- [ ] **Step 4: Run final completion checks**

```powershell
.\scripts\validate.ps1
$env:PYTHONUTF8 = "1"
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" "$env:USERPROFILE\.codex\skills\luming-phone-agent"
git diff --check
git status --short
git log -1 --oneline
```

Expected: all commands exit `0`, Git status is clean, and the installed Skill validates.

- [ ] **Step 5: Report residual integration risk**

State that contracts, synchronization, installation, and packaging are verified locally. State separately that real App navigation still requires a connected phone, valid account state, and on-device evidence; do not claim a real platform workflow succeeded without those conditions.
