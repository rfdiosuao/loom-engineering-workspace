# LOOM Engineering Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a private, clean LOOM engineering workspace that preserves current platform and phone source while enabling isolated parallel pull-request development.

**Architecture:** A private engineering hub owns policy, cross-repository contracts, documentation, and orchestration scripts. The LOOM platform and Phone Agent remain independent private repositories linked as submodules, and every feature is implemented in a repository-local worktree.

**Tech Stack:** Git, GitHub CLI, Git submodules, Git worktrees, PowerShell 7/Windows PowerShell 5.1, GitHub Actions, JSON.

## Global Constraints

- Do not delete, rename, reset, stash, or clean either legacy checkout.
- Do not push private source to `rfdiosuao/lumi`.
- Do not track secrets, signing material, local configuration, databases, APK/AAB files, logs, screenshots, caches, or generated media.
- Use `codex/` for all new branches.
- Every source push must target a private GitHub repository.

---

### Task 1: Freeze The Workspace Contract

**Files:**
- Create: `docs/superpowers/specs/2026-07-15-loom-engineering-workspace-design.md`
- Create: `docs/superpowers/plans/2026-07-15-loom-engineering-workspace.md`

**Interfaces:**
- Consumes: Current repository inventory and GitHub visibility results.
- Produces: The authoritative paths, repository boundaries, and migration acceptance criteria.

- [ ] **Step 1: Validate the design contains no placeholders**

Run:

```powershell
rg -n "T[B]D|T[O]DO|fill\s+in|implement\s+later" docs/superpowers/specs/2026-07-15-loom-engineering-workspace-design.md docs/superpowers/plans/2026-07-15-loom-engineering-workspace.md
```

Expected: no matches.

- [ ] **Step 2: Commit only the two governance documents**

```powershell
git add docs/superpowers/specs/2026-07-15-loom-engineering-workspace-design.md docs/superpowers/plans/2026-07-15-loom-engineering-workspace.md
git commit -m "docs: design clean LOOM engineering workspace"
```

### Task 2: Create The Private Engineering Hub

**Files:**
- Create: `D:\Axiangmu\LOOM-Workspace\.gitignore`
- Create: `D:\Axiangmu\LOOM-Workspace\README.md`
- Create: `D:\Axiangmu\LOOM-Workspace\LOOM.code-workspace`
- Create: `D:\Axiangmu\LOOM-Workspace\docs\architecture\workspace-map.md`
- Create: `D:\Axiangmu\LOOM-Workspace\docs\decisions\0001-private-multi-repo-workspace.md`

**Interfaces:**
- Consumes: The repository table in the design.
- Produces: Private repository `rfdiosuao/loom-engineering-workspace` and the human-facing project entry point.

- [ ] **Step 1: Create and clone the private repository**

```powershell
Set-Location D:\Axiangmu
gh repo create rfdiosuao/loom-engineering-workspace --private --description "Private engineering control workspace for LOOM" --clone
```

Expected: repository visibility is `PRIVATE` and local directory is `D:\Axiangmu\LOOM-Workspace` after renaming the clone directory if necessary.

- [ ] **Step 2: Add the workspace skeleton**

Create the files listed above with the exact layout from the design. `.gitignore` must exclude `/worktrees/`, `/artifacts/`, `.env*`, `*.log`, `*.db`, `*.apk`, `*.aab`, `*.jks`, `*.keystore`, `local.properties`, caches, and IDE state.

- [ ] **Step 3: Validate workspace metadata**

```powershell
Get-Content -Raw .\LOOM.code-workspace | ConvertFrom-Json | Out-Null
git check-ignore worktrees artifacts test.apk test.jks test.log
```

Expected: JSON parsing succeeds and every generated/sensitive test path is ignored.

### Task 3: Preserve And Push The Platform Baseline

**Files:**
- Source repository: `D:\Axiangmu\AUSTART`
- Create in hub: `docs\migration\platform-baseline-20260715.txt`

**Interfaces:**
- Consumes: Existing `codex/customer-acquisition-v1` checkout with 80 working-tree changes.
- Produces: Private branch `codex/workspace-baseline-20260715` on `rfdiosuao/loom-luming-launcher`.

- [ ] **Step 1: Record the complete status without changing it**

```powershell
git -C D:\Axiangmu\AUSTART status --short --branch
git -C D:\Axiangmu\AUSTART diff --stat
git -C D:\Axiangmu\AUSTART ls-files --others --exclude-standard
```

Expected: inventory includes all modified and untracked paths.

- [ ] **Step 2: Create the migration branch**

```powershell
git -C D:\Axiangmu\AUSTART switch -c codex/workspace-baseline-20260715
```

Expected: the working tree is unchanged and the new branch is active.

- [ ] **Step 3: Stage only core source categories**

Stage tracked modifications and untracked source under `openclaw_new_launcher`, `server`, `scripts`, `docs`, and root build metadata. Inspect `git diff --cached --name-only` and remove any generated or sensitive path from the index before commit.

- [ ] **Step 4: Verify the staged platform baseline**

```powershell
npm --prefix D:\Axiangmu\AUSTART\openclaw_new_launcher run build
python -m pytest D:\Axiangmu\AUSTART\openclaw_new_launcher\python\tests -q
```

Expected: the frontend build exits zero and Python tests report zero failures. Any pre-existing failure is recorded before continuing.

- [ ] **Step 5: Commit and push to the private remote**

```powershell
git -C D:\Axiangmu\AUSTART commit -m "chore: preserve LOOM workspace baseline"
git -C D:\Axiangmu\AUSTART push -u source-private codex/workspace-baseline-20260715
```

Expected: the branch exists only on the private source repository.

### Task 4: Preserve And Push The Phone Agent Baseline

**Files:**
- Source repository: `D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction`
- Create in hub: `docs\migration\phone-agent-baseline-20260715.txt`

**Interfaces:**
- Consumes: Existing `main` checkout with 156 working-tree changes.
- Produces: Private branch `codex/workspace-baseline-20260715` on `rfdiosuao/lumiapkclaw`.

- [ ] **Step 1: Create the migration branch without cleaning the checkout**

```powershell
git -C D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction switch -c codex/workspace-baseline-20260715
```

- [ ] **Step 2: Stage core Android source and documentation**

Stage `app/src`, Gradle configuration, `skills`, `docs`, `README*`, and `CHANGELOG.md`. Exclude `Screenshots`, APK/AAB files, signing keys, `local.properties`, build output, caches, and root `screen-*.png` files.

- [ ] **Step 3: Verify the Android baseline**

```powershell
& D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction\gradlew.bat testDebugUnitTest
```

Expected: Gradle exits zero and reports `BUILD SUCCESSFUL`.

- [ ] **Step 4: Commit and push to the private remote**

```powershell
git commit -m "chore: preserve Phone Agent workspace baseline"
git push -u origin codex/workspace-baseline-20260715
```

### Task 5: Link The Verified Source Repositories

**Files:**
- Modify: `.gitmodules`
- Create: `apps/loom-platform`
- Create: `apps/loom-phone-agent`

**Interfaces:**
- Consumes: Both private baseline branches.
- Produces: Reproducible source pointers in the engineering hub.

- [ ] **Step 1: Add private submodules**

```powershell
git submodule add -b codex/workspace-baseline-20260715 https://github.com/rfdiosuao/loom-luming-launcher.git apps/loom-platform
git submodule add -b codex/workspace-baseline-20260715 https://github.com/rfdiosuao/lumiapkclaw.git apps/loom-phone-agent
```

- [ ] **Step 2: Verify the pointers**

```powershell
git submodule status
git -C apps/loom-platform remote get-url origin
git -C apps/loom-phone-agent remote get-url origin
```

Expected: both URLs target private GitHub repositories and both submodules point at baseline commits.

### Task 6: Add Parallel Development Automation

**Files:**
- Create: `scripts/workspace-core.ps1`
- Create: `scripts/status.ps1`
- Create: `scripts/new-feature.ps1`
- Create: `scripts/sync.ps1`
- Create: `scripts/verify.ps1`
- Create: `scripts/test-workspace.ps1`

**Interfaces:**
- Consumes: repository keys `platform` and `phone`.
- Produces: `Get-LoomRepository`, `Get-LoomStatus`, `New-LoomFeatureWorktree`, `Sync-LoomRepository`, and `Invoke-LoomVerification` commands.

- [ ] **Step 1: Implement repository resolution and dry-run support**

`workspace-core.ps1` returns absolute paths for the two submodules and validates that worktrees remain below `D:\Axiangmu\LOOM-Workspace\worktrees`.

- [ ] **Step 2: Implement feature worktree creation**

`new-feature.ps1 -Repository platform -Issue 123 -Name matrix-device-assignments` creates branch `codex/123-matrix-device-assignments` and worktree `worktrees/platform/123-matrix-device-assignments`. It rejects invalid repository keys, non-numeric issues, duplicate branches, dirty default checkouts, and paths outside the workspace.

- [ ] **Step 3: Test automation behavior**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-workspace.ps1
```

Expected: all path, naming, ignore, and dry-run assertions pass without creating a branch.

### Task 7: Add GitHub Collaboration Policy

**Files:**
- Create: `.github\PULL_REQUEST_TEMPLATE.md`
- Create: `.github\ISSUE_TEMPLATE\feature.yml`
- Create: `.github\ISSUE_TEMPLATE\bug.yml`
- Create: `.github\workflows\workspace-ci.yml`
- Create: `docs\runbooks\parallel-development.md`

**Interfaces:**
- Consumes: scripts from Task 6.
- Produces: repeatable issue-to-PR governance and CI verification.

- [ ] **Step 1: Add templates and CI**

Require scope, linked issue, test evidence, risk, rollback, screenshots only for UI changes, and confirmation that no secret or generated artifact is included.

- [ ] **Step 2: Validate workflow syntax and local checks**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-workspace.ps1
git diff --check
```

Expected: script exits zero and Git reports no whitespace errors.

### Task 8: Publish And Verify The Engineering Hub

**Files:**
- Modify: `README.md`
- Create: `docs\migration\migration-report-20260715.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a private, cloneable engineering hub and an evidence-backed migration report.

- [ ] **Step 1: Run the complete workspace verification**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1
git status --short
git submodule status
gh repo view rfdiosuao/loom-engineering-workspace --json visibility,url,defaultBranchRef
```

Expected: verification exits zero, intended files are staged or committed, submodules resolve, and visibility is `PRIVATE`.

- [ ] **Step 2: Commit and push the hub**

```powershell
git add .
git commit -m "chore: establish LOOM engineering workspace"
git push -u origin main
```

- [ ] **Step 3: Confirm legacy preservation**

Compare the recorded migration inventories against both legacy checkouts. Confirm the original paths still exist and no source file was deleted during migration.
