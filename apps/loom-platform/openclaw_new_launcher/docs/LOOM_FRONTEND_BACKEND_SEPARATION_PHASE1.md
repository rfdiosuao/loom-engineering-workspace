# LOOM Frontend Backend Separation Phase 1

Date: 2026-07-02

Scope:
- Main line: `openclaw_new_launcher`
- No changes to `openclaw_ui_integration`
- No route renames or incompatible API field changes
- No APKClaw, signing, production server, real account, or real device changes

## Goal

Phase 1 separates high-risk UI pages from direct backend access by routing migrated frontend code through one facade:

```text
React page
  -> src/services/loomClient.ts
  -> src/services/api.ts
  -> Tauri proxy / FastAPI bridge
  -> Python routes / core services
  -> CLI / MCP shared backend surface
```

This is a strangler step, not a rewrite. The backend route/core service layer remains the source of truth.

## Added Frontend Boundary

Added files:

- `src/services/loomClient.ts`
  - Unified UI-facing facade.
  - Groups backend calls by domain: `account`, `wire`, `components`, `diagnostics`, `jobs`, `process`, `phone`, `matrix`.
  - Wraps calls with shared error normalization.

- `src/services/loomContracts.ts`
  - Re-exports stable DTO and contract types from the typed API layer.
  - Lets migrated pages avoid importing backend transport files for DTO shapes.

- `src/services/loomErrors.ts`
  - Converts backend/Tauri/Bridge errors into `LoomClientError`.
  - Keeps migrated pages from calling `parseErrorText` directly.

- `src/services/loomMock.ts`
  - Holds explicit mock snapshots for account, wire, and matrix previews/contracts.
  - Mock data must not be used to fake real device/account success.

`src/services/api.ts` remains the lower-level transport and typed endpoint wrapper under `loomClient`.

## Migrated Pages

### Model Account Page

File:
- `src/components/models/ModelsPage.tsx`

Backend access now goes through:
- `loomClient.account.current()`
- `loomClient.account.sync()`
- `loomClient.account.selectModels(...)`
- `loomClient.wire.current()`
- `loomClient.wire.custom(...)`
- `loomClient.wire.rollback()`

Contract:
- `python/tests/test_models_page_contract.py`

Separated:
- Page no longer imports `accountApi`, `wireApi`, or `parseErrorText`.
- Model and wire calls route through `loomClient`.
- Cached account snapshots are not treated as writable sessions.
- Managed model selection avoids stale/non-text model defaults and does not hardcode `qwen3.7-plus`.

Still frontend-owned:
- Local form state.
- Display mapping.
- Lightweight required-field checks before submitting custom provider config.

### Agent Installer Page

File:
- `src/components/agents/AgentInstallerPage.tsx`

Backend access now goes through:
- `loomClient.components.status()`
- `loomClient.components.detect(...)`
- `loomClient.components.install(...)`
- `loomClient.components.start(...)`
- `loomClient.components.rollback(...)`
- `loomClient.components.uninstall(...)`
- `loomClient.components.modelConfigStatus(...)`
- `loomClient.components.applyModelConfig(...)`
- `loomClient.components.rollbackModelConfig(...)`
- `loomClient.diagnostics.run()`
- `loomClient.diagnostics.repair(...)`
- `loomClient.jobs.list(...)`
- `loomClient.process.status()`
- `loomClient.process.start()`
- `loomClient.process.waitForReady(...)`

Contract:
- `python/tests/test_agent_installer_page_contract.py`

Separated:
- Page no longer imports `componentApi`, `diagnosticsApi`, `jobApi`, `processApi`, `waitForProcessReady`, or `parseErrorText`.
- Component install status, preflight diagnostics, model config status, job log reads, and local process readiness route through `loomClient`.
- Confirmed install/repair boundaries remain explicit at the UI call sites.

Still frontend-owned:
- Selection state.
- Progress rendering.
- Copy/export of visible install log text.
- Confirmation prompts before repair/install actions.

## Backend / CLI / MCP Compatibility

No backend route fields were renamed or removed.

No duplicate CLI/MCP business logic was added. `loomClient` is a frontend facade on top of the existing typed API layer. `loom_cli.py` and `loom_mcp.py` still use the existing Python backend capability surface.

Current shape:

```text
Migrated UI pages -> LoomClient -> existing local API surface
CLI / MCP         -> existing Python backend surface
```

The Python route/core layer remains the shared source of truth.

## Remaining Direct Calls

Known remaining frontend direct calls/imports after this phase:

- `App.tsx`
  - `processApi`, `logApi`, `updateApi`

- `DashboardPage.tsx`
  - `accountApi`, `componentApi`

- `LicensePage.tsx`
  - `accountApi`
  - Login/register/email-code/subscription URL logic remains in the page.

- `PhoneDemoPage.tsx`
  - `accountApi`, `phoneApi`, `matrixApi`
  - Phone URL/token state and phone/matrix task display remain in the page.

- `MatrixWorkbenchPage.tsx`
  - `matrixApi`
  - Matrix dispatch and worker display mapping remain in the page.

- `CreativeMediaPage.tsx`
  - `jobApi`

- `DiagnosticsPage.tsx`
  - `diagnosticsApi`

- `TerminalPage.tsx` and `DiagnosticsPage.tsx`
  - `invoke('open_path', ...)`
  - This is Tauri shell/open-path behavior, not business backend logic, but it is still a direct invoke.

Expected lower layer:

- `src/services/api.ts`
  - Continues to define typed endpoint wrappers such as `accountApi`, `wireApi`, `componentApi`, `phoneApi`, `matrixApi`, and `jobApi`.
  - This is the transport layer under `loomClient`, not a migrated page.

## Next Migration Order

Recommended next steps:

1. `LicensePage.tsx`
   - Move account login/register/email-code/subscription calls to `loomClient.account`.
   - Move subscription URL fallback and account center policy further toward backend/config.

2. `MatrixWorkbenchPage.tsx`
   - Move `matrixApi` calls to `loomClient.matrix`.
   - Keep high-risk dispatch confirmation explicit.

3. `PhoneDemoPage.tsx`
   - Move `phoneApi`, `matrixApi`, and account status reads to `loomClient`.
   - Keep real phone verification as a separate manual/device gate.

4. `CreativeMediaPage.tsx`
   - Move job polling to `loomClient.jobs`.
   - Later move default media model policy behind backend/config.

## Verification

Passed:

```powershell
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
python -m unittest python.tests.test_models_page_contract python.tests.test_agent_installer_page_contract
npm run build
```

Result:
- `28` contract tests passed.
- `npm run build` passed.

Passed:

```powershell
cd D:\Axiangmu\AUSTART
git diff --check
cd D:\Axiangmu\AUSTART\openclaw_new_launcher
python -m py_compile python\bridge.py python\loom_cli.py python\loom_mcp.py
```

Result:
- `git diff --check` passed with existing CRLF warnings only.
- Python compile passed.

Blocked by missing dependency:

```powershell
python -m pytest python\tests\test_routes_account.py python\tests\test_routes_wire.py python\tests\test_routes_components.py python\tests\test_routes_phone.py python\tests\test_routes_matrix.py python\tests\test_loom_cli_contract.py python\tests\test_loom_mcp_contract.py
```

Result:
- Could not run because the active Python environment is missing `pytest`.
- Error: `No module named pytest`.

## Release Risks

- No real account verification was performed.
- No phone unlock or real device matrix run was performed.
- No production server, payment, or subscription purchase flow was touched.
- No APKClaw source, signing chain, Lumi protocol, or phone HTTP/ADB fallback implementation was changed.
- Existing unrelated working tree changes were left untouched.

## Phase 1 Done State

Satisfied:
- Unified `LoomClient` facade exists.
- Two high-value pages are migrated through `LoomClient`.
- Per-page contract tests cover the migration boundary.
- Build passes.
- Python bridge/CLI/MCP entry files compile.
- No incompatible backend API field changes were introduced.

Not included:
- Full app-wide removal of direct `api.ts` imports.
- Real phone/device verification.
- Production account/payment/subscription verification.
- Old `openclaw_ui_integration` migration.
