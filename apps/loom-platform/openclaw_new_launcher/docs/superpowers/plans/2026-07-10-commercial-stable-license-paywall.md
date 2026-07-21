# Luming 2.1.56 Commercial Stable License Paywall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a recoverable, release-tested `2.1.56` Windows build whose startup flow, protected APIs, release workflow, and Volcengine license service enforce the same signed commercial-license contract.

**Architecture:** Keep the existing signed license payload and `/api/license/current`, `/activate`, and `/authorized` endpoints as the source of truth. Add one normalized frontend gate state, mirror one explicit path-to-feature policy in Tauri and Python, keep sanitized diagnostics available before activation, and make `openclaw_new_launcher` the only current CI/Release build source without deleting historical source or artifacts.

**Tech Stack:** React 19, TypeScript, Zustand, Vite, Tauri 2/Rust, FastAPI/Python, `unittest`, GitHub Actions, NSIS, existing Volcengine license server.

**Commercial Feature Contract**

| Feature key | Protected capabilities | Notes |
| --- | --- | --- |
| `acquisition.workbench` | acquisition snapshot, lead/customer/draft/task/log state | Read and write workbench APIs are licensed |
| `acquisition.feishu` | Feishu login, bind, create table, write, retry sync | No production token is shown in UI or diagnostics |
| `matrix.devices` | matrix status/config/dispatch and phone task APIs | Existing outbound confirmation policy is unchanged |
| `templates.cloud` | cloud template list/upload/download/sync | Local static template help remains readable |
| `publishing.draft` | publishing draft preparation and publish pipeline entry | Actual publish still requires human confirmation/allowlist/rate limit/logging |
| `diagnostics.export` | reserved entitlement for enhanced support bundles | Baseline sanitized `/api/diagnostics/export` remains available without a license |

**State Contract**

```ts
export type LicenseGateStatus =
  | "checking"
  | "authorized"
  | "unauthorized"
  | "expired"
  | "disabled"
  | "device_mismatch"
  | "offline_grace"
  | "service_error";

export interface LicenseGateSnapshot {
  status: LicenseGateStatus;
  authorized: boolean;
  reason: string;
  license: License | null;
  installId: string;
  deviceId: string;
  purchaseUrl: string;
  supportUrl: string;
}
```

The local signed license is authoritative at startup. A valid cached signature enters the app even if remote client configuration is temporarily unavailable; the UI labels that condition as `offline_grace`. Missing or invalid local authorization never enters the workbench. Error classification must prefer stable backend error codes and fall back to conservative text matching only for legacy responses.

---

### Task 0: Freeze the 2.1.55 Checkpoint

**Evidence:**
- Branch: `codex/customer-acquisition-v1`
- Baseline: `v2.1.45-20260706-ai-matrix-name-rc14` -> `12106a73ebe2e75f5a2eae4eb9b31e49922f4090`
- Checkpoint commit: `9ecd56655ef07ca3779df25a47b37bed7bb110bd7`
- Secret scan: 41 files, zero matches, zero risky filenames
- `git diff --check`: passed before commit

- [x] Run branch, baseline, and worktree checks.
- [x] Inspect all modified and untracked files.
- [x] Scan the checkpoint for credentials/private data.
- [x] Commit the complete user worktree without rebasing, resetting, or dropping changes.

---

### Task 1: Lock the Frontend License State Contract with Tests

**Files:**
- Create: `python/tests/test_commercial_license_paywall_contract.py`
- Create: `src/components/license/licenseGate.ts`
- Modify: `src/types/index.ts`
- Modify: `src/services/api.ts`
- Modify: `src/stores/appStore.ts`

- [ ] Add a contract test that initially fails unless source contains:
  - `data-license-paywall`
  - `data-license-code-input`
  - `data-license-activate`
  - `data-license-install-id`
  - `data-license-copy-install-id`
  - `data-license-diagnostics-export`
  - every `LicenseGateStatus` value
  - no gateway/access token rendered by the paywall

- [ ] Add pure normalization tests for backend payload variants:

```ts
normalizeLicenseGate({ authorized: false, code: "LICENSE_EXPIRED" })
// => status === "expired"

normalizeLicenseGate({ authorized: false, code: "DEVICE_MISMATCH" })
// => status === "device_mismatch"
```

- [ ] Run the focused test and record the expected initial failure:

```powershell
python-runtime\python.exe -m unittest discover -s python\tests -p "test_commercial_license_paywall_contract.py"
```

- [ ] Extend `License` only with server-backed display fields. Accept both `expires` and `expiresAt` at the API boundary, then expose one normalized value to components.
- [ ] Add `licenseApi.authorized(feature?)` response typing and preserve existing endpoint paths.
- [ ] Replace `gatewayProfile` authorization fallback in `appStore.checkLicense()` with signed-license state only.
- [ ] Add a finite check timeout. A Bridge/network failure must resolve to `service_error`, never an endless spinner.
- [ ] Run the focused test until green, then run `npm run build`.
- [ ] Commit: `feat: define commercial license gate state`

---

### Task 2: Build the Startup Paywall and Route Gate

**Files:**
- Create: `src/components/license/LicensePaywall.tsx`
- Create: `src/components/license/LicensePaywall.css`
- Modify: `src/App.tsx`
- Modify: `src/components/LoomSplash.tsx` only if a bounded splash callback is needed
- Modify: `python/tests/test_commercial_license_paywall_contract.py`

- [ ] Add a full-window commercial activation page after the bounded brand splash. Keep native window controls usable, but do not render the normal sidebar or protected routes underneath it.
- [ ] Render only real values from `LicenseGateSnapshot`: status, plan/edition, expiry, install ID, device ID, and licensed features.
- [ ] Render the capability summary without fake counters or customer data:
  - multi-phone matrix acquisition
  - lead/customer sedimentation
  - AI follow-up drafts
  - Feishu Bitable synchronization
  - cloud templates
  - sanitized support diagnostics
- [ ] Add an activation form that trims but never logs the code:

```tsx
<form onSubmit={activateLicense} data-license-paywall>
  <input type="password" data-license-code-input autoComplete="off" />
  <button type="submit" data-license-activate>Activate</button>
</form>
```

- [ ] Add copy-install-ID, retry, sanitized-diagnostics, purchase, and support actions. Purchase/support URLs must come from `/api/license/client-config` with safe HTTPS validation and a non-secret fallback to `https://license.heang.top/`.
- [ ] Give each failure a distinct title/action:
  - `unauthorized`: enter a license code
  - `expired`: renew the displayed expired plan
  - `disabled`: contact support
  - `device_mismatch`: copy this machine ID for rebinding
  - `service_error`: retry or export diagnostics
  - `offline_grace`: allow entry with a clear offline banner
- [ ] Keep existing `LicensePage` for account/subscription details after entry; do not duplicate its 900+ lines into the paywall.
- [ ] Ensure `App.tsx` renders protected navigation only for `authorized` or `offline_grace`.
- [ ] Add unit/contract coverage proving the sidebar and acquisition workbench are absent from the unauthorized branch.
- [ ] Run focused contract test and `npm run build`.
- [ ] Start the local frontend/Tauri app and visually inspect desktop plus narrow widths for blank screens, overlap, translucent modal artifacts, and infinite loading.
- [ ] Commit: `feat: add startup commercial license paywall`

---

### Task 3: Enforce the Feature Policy in Python

**Files:**
- Create: `python/core/feature_access.py`
- Create: `python/tests/test_commercial_license_feature_gate.py`
- Modify: `python/bridge.py`
- Modify: related route modules under `python/api/`
- Modify: `python/core/license_manager.py` only for stable error codes/status fields

- [ ] Write table-driven failing tests for path normalization and feature mapping:

```python
CASES = {
    "/api/matrix/acquisition/feishu/status": "acquisition.feishu",
    "/api/matrix/acquisition/templates/upload": "templates.cloud",
    "/api/matrix/acquisition/snapshot": "acquisition.workbench",
    "/api/matrix/status": "matrix.devices",
    "/api/phone/task": "matrix.devices",
}
```

- [ ] Explicitly assert `feature_for_path("/api/diagnostics/export") is None` so an unlicensed customer can obtain a sanitized support bundle.
- [ ] Centralize longest-prefix-first mapping in `feature_access.py`; strip query strings, normalize slashes, and reject ambiguous lookalike paths.
- [ ] Change `_fastapi_protected_error(path)` to request `LicenseManager.is_authorized(feature)` for the mapped feature. Return structured 403 JSON with stable code `LICENSE_FEATURE_REQUIRED` and the non-secret feature key.
- [ ] Ensure every protected route invokes `protected_error(request.url.path)` before business logic. Do not rely on frontend hiding.
- [ ] Leave these endpoints unlicensed:
  - `/api/license/current`
  - `/api/license/client-config`
  - `/api/license/activate`
  - `/api/version` or equivalent basic version route
  - sanitized `/api/diagnostics/export`
  - minimum environment/Bridge health checks needed for activation support
- [ ] Add tests with a fake license manager for no license, wrong feature, correct feature, expired payload, and device mismatch.
- [ ] Run:

```powershell
python-runtime\python.exe -m unittest discover -s python\tests -p "test_commercial_license_feature_gate.py"
python-runtime\python.exe -m unittest discover -s python\tests -p "test_*.py"
```

- [ ] Commit: `feat: enforce license features in python bridge`

---

### Task 4: Mirror Feature Enforcement in Tauri

**Files:**
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/src/license.rs` only if stable result/error fields are missing

- [ ] Add Rust table tests before changing `protected_feature(path)`.
- [ ] Implement the same longest-prefix policy as Python. `proxy_request` must reject missing entitlements before forwarding to Bridge.
- [ ] Preserve unlicensed activation, version, health, client configuration, and sanitized diagnostics export.
- [ ] Do not pass license codes, gateway tokens, or activation response bodies into logs.
- [ ] Add parity tests for every path in the Python table and for path-boundary attacks such as `/api/matrix/acquisitionevil`.
- [ ] Run:

```powershell
Set-Location src-tauri
cargo test
cargo check
```

- [ ] Commit: `feat: enforce license features in tauri proxy`

---

### Task 5: Align the Volcengine License Service Contract

**Files:**
- Modify: `license_server/server.py`
- Modify: `license_server/tests/test_license_flow.py`
- Modify: `openclaw_new_launcher/python/core/license_manager.py` only if response normalization requires it
- Modify: `openclaw_new_launcher/src/types/index.ts`

- [ ] Add failing server tests proving activation/current payloads expose only the signed commercial fields needed by the client:
  - `licensee`
  - `edition`
  - `plan`
  - `expires` and/or normalized `expiresAt`
  - `features`
  - `installId`/`deviceId`
  - `deviceLimit`
- [ ] Add the six commercial feature keys to server defaults and plan templates without widening existing customer licenses implicitly.
- [ ] Keep current signed payload verification and device binding; do not introduce a second token system.
- [ ] Return stable public error codes for invalid, expired, disabled, and device-mismatch activation. Keep internal exceptions, database details, and admin credentials out of responses.
- [ ] Return purchase/support links through public client configuration. The admin URL is not the customer purchase URL.
- [ ] Confirm `/admin` authentication/RBAC is unchanged.
- [ ] Run:

```powershell
python -m unittest discover -s license_server\tests -p "test_*.py"
```

- [ ] Commit: `feat: align commercial license service contract`

---

### Task 6: Make `openclaw_new_launcher` the Release Source and Bump 2.1.56

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `scripts/ci-check.ps1`
- Modify: version files under `openclaw_new_launcher/`:
  - `package.json`
  - `package-lock.json`
  - `src-tauri/tauri.conf.json`
  - `src-tauri/Cargo.toml`
  - `src-tauri/Cargo.lock`
- Modify: release/version contract tests if present

- [ ] Add a source-of-truth check that fails if active workflow build/caching paths point to `openclaw_ui_integration`.
- [ ] Update CI cache keys, working directories, Cargo paths, frontend build, Python tests, and artifact paths to `openclaw_new_launcher`.
- [ ] Update Release to build NSIS from `openclaw_new_launcher` and preserve historical releases/artifacts.
- [ ] Extend `scripts/ci-check.ps1` to run the full launcher Python test suite plus existing license server checks.
- [ ] Bump every authoritative version to `2.1.56`; avoid unrelated generated metadata churn.
- [ ] Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-version-consistency.ps1
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

- [ ] Commit: `build: release commercial stable from new launcher`

---

### Task 7: Run Release-Grade Local and Visual Verification

**Files:**
- Create: `openclaw_new_launcher/docs/releases/2.1.56-verification.md`
- Modify tests only when a failure exposes a real contract gap

- [ ] Run the complete required suite from clean command shells:

```powershell
Set-Location D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run build
python-runtime\python.exe -m unittest discover -s python\tests -p "test_*.py"
Set-Location src-tauri
cargo test
cargo check
Set-Location D:\Axiangmu\AUSTART
python -m unittest discover -s license_server\tests -p "test_*.py"
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

- [ ] Start local Tauri or frontend with representative deterministic fixtures and inspect:
  - no license
  - valid license
  - expired license
  - device mismatch
  - offline/service unavailable
- [ ] Check desktop and narrow viewport screenshots. Record evidence that the activation panel is opaque/readable, controls fit, and no protected UI flashes before authorization.
- [ ] Adversarially call protected APIs without a license and with a license missing one feature. Record 403 evidence from both Tauri and Python boundaries.
- [ ] Verify outbound actions still produce drafts and require manual confirmation/allowlists/rate limits/logging.
- [ ] Run a repository/package secret scan covering license codes, admin tokens, SSH keys, model keys, Feishu tokens, customer data, login cache, and Gitee tokens.
- [ ] Commit only real fixes revealed by verification; do not weaken tests to make the suite green.

---

### Task 8: Build and Test the NSIS Deliverable

**Files:**
- Create: `openclaw_new_launcher/docs/releases/2.1.56-installer-report.md`
- Do not delete or overwrite historical release output

- [ ] Build:

```powershell
Set-Location D:\Axiangmu\AUSTART\openclaw_new_launcher
npm run tauri -- build --bundles nsis
```

- [ ] Record exact installer path, filename, version, byte size, build timestamp, and SHA256.
- [ ] Inspect the package manifest/content for bundled Python runtime and Bridge dependencies. The installed app must not depend on system Python, Node, or `lark-cli`.
- [ ] Install into a fresh English path and test first launch/activation/restart persistence.
- [ ] Install under a Chinese Windows user/path and repeat Bridge startup plus license checks.
- [ ] Scan installed files and installer contents for all forbidden secrets/private data.
- [ ] Keep the produced artifact local until the user explicitly approves publishing.

---

### Task 9: Back Up, Deploy, and Regress the Volcengine Service

**Inputs (never commit):**
- `C:\Users\Administrator\Desktop\服务器.md`
- `C:\Users\Administrator\Desktop\heang_server.pub`
- `C:\Users\Administrator\Desktop\heang_server`

- [ ] Read server metadata and public-key fingerprint only. Never print or read private-key content; pass it only as `ssh -i C:\Users\Administrator\Desktop\heang_server`.
- [ ] Compare the live SSH host fingerprint with the documented fingerprint. Stop if they differ.
- [ ] Perform read-only discovery of the service directory, process manager/container, health route, public `/admin`, and data/config locations.
- [ ] Back up service code, non-secret configuration, and database with timestamped paths on the server. Verify backup existence and record restore commands before deployment.
- [ ] Upload only the tested license-service files and restart only that service. Do not change DNS, firewall, certificate, unrelated services, or production customer records.
- [ ] Verify:
  - public site and health endpoint
  - `/admin` renders and RBAC remains enabled
  - client configuration
  - one dedicated non-production test-license activation
  - device binding and restart persistence
  - expired/disabled/device mismatch error codes
- [ ] If health or activation fails, restore the backup and verify rollback health immediately.
- [ ] Record redacted deployment evidence without host credentials, tokens, database contents, or the test license code.

---

### Task 10: Final Evidence, Rollback, and Local Stable Tag

**Files:**
- Create: `openclaw_new_launcher/docs/releases/2.1.56-changelog.md`
- Create: `openclaw_new_launcher/docs/releases/2.1.56-deployment.md`
- Create: `openclaw_new_launcher/docs/releases/2.1.56-rollback.md`

- [ ] Summarize changed files by boundary: UI, frontend state/API, Tauri, Python, license server, CI/Release, tests, docs.
- [ ] Include exact local/online verification commands and outcomes.
- [ ] Include client rollback to the checkpoint/release commit without destructive commands and server restore/restart/health commands with secrets redacted.
- [ ] Re-run `git status --short --branch`, `git diff --check`, final secret scan, version consistency, and focused commercial tests.
- [ ] Create only after all acceptance evidence is green:

```powershell
git tag -a v2.1.56-commercial-stable -m "Luming AI Matrix Acquisition Workbench 2.1.56 commercial stable"
```

- [ ] Verify the annotated tag points at the final tested commit.
- [ ] Do not push the branch/tag, publish the installer, or upload artifacts until the user explicitly confirms.

---

## Plan Self-Review Checklist

- [ ] Every goal requirement maps to at least one task and verification step.
- [ ] Python and Rust policies use the same six feature keys and path boundaries.
- [ ] Sanitized diagnostics remains available before authorization despite the reserved `diagnostics.export` entitlement.
- [ ] No step requires reading, printing, or committing the SSH private key or production secrets.
- [ ] No task adds BOSS scraping, autonomous execution, payment/orders, bulk messaging, or new platform integrations.
- [ ] Release paths point to `openclaw_new_launcher`; historical source and release artifacts remain intact.
- [ ] No unfinished placeholder markers remain in acceptance-critical sections.
- [ ] The stable tag is local-only and is created only after installer plus online regression evidence is complete.
