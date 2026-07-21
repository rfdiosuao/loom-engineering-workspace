# OpenClaw Super Installer Implementation Plan

Updated: 2026-06-28

## 1. Scope

Implement the next installer/runtime-console foundation in a controlled sequence. The goal is not to redesign every feature at once; the goal is to create the stable spine that makes future UI, packaging, and model sync work predictable.

Primary output:

- manifest-driven component installer
- online and offline package lanes
- Heang account-to-wire sync
- bridge-owned config writes
- concise runtime console UI states
- release verification gates

## 2. Workstreams

### A. Manifest And Component Installer

Deliverables:

- `release-manifest.schema.json`
- `release-manifest.example.json`
- manifest fetch/cache service
- component install state store
- downloader with mirror fallback
- SHA256 verifier
- atomic extract/swap
- rollback store
- component health checks

Acceptance:

- corrupt hash blocks install
- primary URL failure tries fallback
- interrupted install does not leave active component half-written
- rollback restores previous component

### B. Account And Wire Sync

Deliverables:

- email-code login route, if server supports it
- password login fallback
- current account snapshot
- model list classification: text, phone, image, video
- default model selection
- `/api/wire/sync`
- `/api/wire/verify`
- `/api/wire/rollback`

Acceptance:

- visitor mode works without account
- login creates scoped model token
- sync writes OpenClaw config
- sync writes Phone Agent model `agnes-2.0-flash`
- Desktop RPA receives URL/API key/model
- logout clears only managed configs

### C. Runtime Status And Jobs

Deliverables:

- unified `/api/runtime/status`
- persistent `/api/jobs` store
- install jobs
- image/video generation job persistence
- phone automation job persistence
- route-independent job polling

Acceptance:

- switching modules does not lose generation animation/state
- start/stop actions show optimistic state then reconcile
- slow endpoints do not block navigation
- old job state is visible after launcher restart when still relevant

### D. UI Simplification

Deliverables:

- route skeleton screens
- lower-left route-independent account block
- component list/detail page
- account page with visitor/login/sync states
- diagnostics disclosure for paths and raw config
- copy cleanup using product-help language

Acceptance:

- first page renders from cached status
- no raw paths in normal view
- no poetic slogan copy in runtime controls
- one primary action per component state

### E. Release And Verification

Deliverables:

- online package build script
- full offline package build script
- manifest generation script
- manifest validation script
- package secret scan
- no-dev-url scan
- smoke script for clean extraction
- release notes template

Acceptance:

- online package can bootstrap from manifest
- offline package runs without network
- no package includes local account/session/license files
- no package points to localhost except intended local bridge health checks

## 3. Phased Sequence

### Phase 1: Installer Spine

Implement:

- manifest schema
- manifest example
- component state model
- downloader/verify/extract/rollback service
- CLI-level validation

Do not yet redesign all UI.

Exit criteria:

- one dummy component can install, verify, fail, and roll back
- schema and example pass validation

### Phase 2: Real Components

Add components:

- `openclaw-engine`
- `desktop-rpa`
- `phone-agent-assets`
- `templates-and-skills`

Exit criteria:

- each component has health check
- install/repair works independently
- component status appears in bridge snapshot

### Phase 3: Account Wire

Implement:

- Heang account snapshot normalization
- scoped token handling
- default model policy
- OpenClaw/Phone/RPA/Image wire writers
- target-specific sync result

Exit criteria:

- login -> sync -> verify works
- target failure does not break all sync
- logout preserves manual configs

### Phase 4: Runtime Console UI

Implement:

- component page
- account page refinements
- route-independent account block
- status skeletons
- job persistence UI

Exit criteria:

- no route switch drops long job state
- first-render feels immediate
- core actions are visible without scrolling through explanatory text

### Phase 5: Release Lanes

Implement:

- online portable build
- full offline build
- manifest publishing
- local verification
- GitHub/Gitee release upload path

Exit criteria:

- online and offline artifacts pass smoke tests
- release notes list components and hashes
- rollback package/version is available

## 4. Concrete File Targets

Likely new files:

```text
openclaw_ui_integration/python/core/release_manifest.py
openclaw_ui_integration/python/core/component_installer.py
openclaw_ui_integration/python/core/wire_manager.py
openclaw_ui_integration/python/core/job_store.py
openclaw_ui_integration/python/api/routes_components.py
openclaw_ui_integration/python/api/routes_wire.py
openclaw_ui_integration/python/api/routes_jobs.py
openclaw_ui_integration/src/redesign/pages/ComponentsPage.tsx
openclaw_ui_integration/src/redesign/state/jobs.ts
schemas/openclaw-release-manifest.schema.json
examples/openclaw-release-manifest.example.json
scripts/build-online-portable.ps1
scripts/generate-release-manifest.ps1
scripts/verify-installer-manifest.ps1
```

Likely changed files:

```text
openclaw_ui_integration/python/bridge.py
openclaw_ui_integration/python/api/routes_account.py
openclaw_ui_integration/python/core/newapi_account_manager.py
openclaw_ui_integration/src/redesign/components/Shell.tsx
openclaw_ui_integration/src/redesign/App.tsx
openclaw_ui_integration/src/redesign/pages/LicensePage.tsx
openclaw_ui_integration/src/redesign/pages/PhonePage.tsx
openclaw_ui_integration/src/redesign/pages/DesktopPage.tsx
scripts/build-portable.ps1
scripts/verify-release.ps1
```

## 5. Testing Plan

Source checks:

```powershell
python -m py_compile openclaw_ui_integration\python\bridge.py
npm run build --prefix openclaw_ui_integration
git diff --check
```

Installer checks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-installer-manifest.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path <zip>
```

Runtime checks:

- launch from clean extraction
- `/api/runtime/status` returns within target timeout
- visitor mode appears without login
- login/sync works
- OpenClaw starts after sync
- phone model sync result appears
- Desktop RPA start/stop returns quickly with reconciled status
- route switch preserves active jobs

Security checks:

- no full API key in source or package
- no password/private key in source or package
- no local session/license artifacts in package
- no production UI points to `localhost` as remote web app
- only intended local bridge/RPA health URLs use `127.0.0.1`

## 6. Rollback Rules

Rollback is mandatory for:

- component install failure after previous ready version exists
- config sync failure after writing a target config
- package update failure after extraction

Rollback is not mandatory for:

- first-time install with no previous component
- login failure
- model list fetch failure when last-good snapshot exists

Always keep:

- previous component directory
- last-good wire config
- last-good account model snapshot
- per-target config backup where practical

## 7. Definition Of Done

The super installer foundation is done when:

- A clean Windows machine can run online portable package and install required components through the launcher.
- A clean Windows machine can run the full offline package without downloading runtime components.
- Visitor mode is usable.
- Heang account login can sync models.
- OpenClaw, Phone Agent, Desktop RPA, and image config can be synced independently.
- Long-running jobs survive route switches.
- Release verification catches secrets, dev URLs, missing templates, missing components, and hash mismatch.
- The UI exposes component status and repair without showing noisy paths by default.

Mac packaging can consume the same manifest once the Windows lane is stable.
