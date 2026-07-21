# Installer Performance And Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将安装页前置检测和 Codex 首装从多轮阻塞式探测改成快速、可拖动、可后台运行的单次下载流程，并交付在线版与完整离线版两个 NSIS 安装包。

**Architecture:** 保留完整诊断用于售后，新增只覆盖安装依赖的快速前置接口和 scoped 修复接口。组件安装器优先解析受管目录内的 Codex 原生入口，流式下载到 SHA 校验缓存，命中本地入口时跳过旧 manifest 中的远程 npm 安装命令。安装页只锁当前组件操作，统一从持久化 Job 恢复进度；发布脚本临时注入同一份已验证 Codex 包构建在线/完整两个 NSIS 产物。

**Tech Stack:** React 18、TypeScript、Zustand、Tailwind CSS、FastAPI、Python 3、urllib、Tauri 2、PowerShell、NSIS、unittest

## Global Constraints

- 缓存存在时安装页立即展示；冷启动快速前置检测必须低于 2 秒，当前开发机目标低于 800 毫秒。
- 本地 Codex 包检测必须低于 500 毫秒且不启动 Appx/npm 子进程。
- 在线安装只下载一个 manifest 指定的 Codex 平台包，不能再执行第二次远程 npm 下载。
- 完整安装包必须在断网状态完成 Codex 安装并通过 `codex --version`。
- 检测和安装期间主窗口始终可拖动，侧栏、滚动和非当前组件操作保持可用。
- 保留 manifest 签名、SHA-256、路径穿越保护、回滚和日志；不得写入账号、token、授权码或客户数据。
- 不修改 Codex 登录、模型协议、手机 Agent 协议、飞书 API 或任何自动触达策略。
- 不删除现有 release 产物，不改主分支，不回滚现有未提交授权修复。

---

## File Map

- `python/services/process.py`: 快速前置检测、耗时字段和 scoped 修复。
- `python/api/routes_diagnostics.py`: 快速检测与 scoped 修复接口。
- `python/bridge.py`: FastAPI context 暴露快速 payload 构建器。
- `src/services/api.ts`: 快速前置接口、timing 和 Job 进度类型。
- `python/core/component_installer.py`: Codex 本地入口、单次探测、流式下载、断点缓存和跳过重复 npm。
- `src/components/agents/AgentInstallerPage.tsx`: 缓存先显示、移除自动深检、组件级锁定和 Job 恢复。
- `src/components/common/index.tsx`: BusyOverlay 不覆盖标题栏。
- `src/components/window/WindowTitlebar.tsx`: 标题栏 z-index 与拖动契约。
- `../scripts/build-dual-nsis.ps1`: 在线/完整双包构建。
- `scripts/measure-installer-performance.ps1`: 可重复热路径基准。
- `python/tests/test_process_diagnostics.py`: 快速检测和 scoped 修复测试。
- `python/tests/test_routes_diagnostics.py`: 新接口测试。
- `python/tests/test_component_installer.py`: 探测、缓存、续传和单下载测试。
- `python/tests/test_agent_installer_page_contract.py`: 非阻塞安装页契约。
- `python/tests/test_window_chrome_contract.py`: 标题栏拖动契约。
- `python/tests/test_release_scripts_contract.py`: 双包脚本契约。

---

### Task 1: Fast Prerequisite Detection And Scoped Repair

**Files:**
- Modify: `python/services/process.py:254-560`
- Modify: `python/api/routes_diagnostics.py:13-37`
- Modify: `python/bridge.py:567-590,782-804`
- Modify: `src/services/api.ts:475-532`
- Test: `python/tests/test_process_diagnostics.py`
- Create: `python/tests/test_routes_diagnostics.py`

**Interfaces:**
- Produces: `OpenClawProcessService.diagnose_prerequisites() -> dict`
- Produces: `OpenClawProcessService.repair_prerequisites() -> dict`
- Produces: `GET|POST /api/diagnostics/prerequisites`
- Produces: `POST /api/diagnostics/repair` body `{ confirmed: true, scope: "prerequisites" }`
- Produces: `DiagnosticReport.timing?: { totalMs: number; checksMs: Record<string, number>; measuredAt: string }`

- [ ] **Step 1: Write failing fast-path tests**

Add a test that replaces `_port_range_listeners`, `_openclaw_gateway_processes`, `_clawpanel_processes`, `_phone_agent_apk_check`, `_member_gateway_check`, and `_core_service_snapshot_check` with functions that raise. Call `diagnose_prerequisites()` and assert the IDs are exactly:

```python
[
    "python_runtime", "node", "npm", "git",
    "git_bash", "uv", "webview2", "data_dir",
]
```

Assert `timing.totalMs >= 0`, every returned ID exists in `timing.checksMs`, and no heavy replacement is called. Add a scoped repair test asserting service stop, port cleanup and config rebuild are not called while public prerequisite install, WebView2 repair and exactly one final quick recheck occur.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\python-runtime\python.exe -m unittest discover -s python\tests -p "test_process_diagnostics.py"
.\python-runtime\python.exe -m unittest discover -s python\tests -p "test_routes_diagnostics.py"
```

Expected: failures because quick methods and route do not exist.

- [ ] **Step 3: Extract shared prerequisite construction**

Create `_build_prerequisite_checks(with_timing: bool = False)` and reuse it from full diagnostics. Implement:

```python
def diagnose_prerequisites(self) -> dict:
    started = time.perf_counter()
    checks, checks_ms = self._build_prerequisite_checks(with_timing=True)
    return {
        "basePath": self.paths.base_path,
        "serviceRunning": self.status().get("running", False),
        "servicePid": self.process.pid if self.process and self.process.poll() is None else None,
        "checks": checks,
        "timing": {
            "totalMs": round((time.perf_counter() - started) * 1000),
            "checksMs": checks_ms,
            "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
    }
```

Preserve existing check IDs and Chinese messages in `diagnose_environment()`.

- [ ] **Step 4: Implement scoped repair**

`repair_prerequisites()` must obtain one quick snapshot, run `_install_public_prerequisites_action`, `_repair_webview2_runtime`, `_prerequisite_source_check_action`, ensure `data_dir`, then run exactly one final `diagnose_prerequisites()`. It must not call `repair_environment()`.

- [ ] **Step 5: Add API and TypeScript contracts**

Expose `/api/diagnostics/prerequisites`, route `scope == "prerequisites"` to scoped repair, add `timing` to `DiagnosticReport`, and add:

```ts
prerequisites: (): Promise<DiagnosticReport> => api('/api/diagnostics/prerequisites'),
repairPrerequisites: (): Promise<DiagnosticRepairResult> =>
  api('/api/diagnostics/repair', 'POST', { confirmed: true, scope: 'prerequisites' }),
```

- [ ] **Step 6: Run focused tests and commit**

Stage only Task 1 files and commit `perf: add fast prerequisite checks` after both focused suites pass.

---

### Task 2: Single-Pass Codex Detection And Direct Native Entry

**Files:**
- Modify: `python/core/component_installer.py:287-350,520-960`
- Test: `python/tests/test_component_installer.py`

**Interfaces:**
- Produces: `_managed_codex_entry(install_path: str) -> str | None`
- Produces: `_resolve_component_entry(component, install_path, allow_expensive=True) -> str`
- Changes: `_detect_installed_version(component, install_path, entry_path=None) -> str | None`

- [ ] **Step 1: Write failing call-count tests**

Create `package/vendor/x86_64-pc-windows-msvc/bin/codex.exe` in a temp install path. The fake runner returns `codex-cli 0.142.3` only for that executable and fails if PowerShell or npm is called. Assert status `ready`, version `0.142.3`, and exactly one runner call. Add an external-only case asserting at most one Appx query and one each of `npm prefix`, `npm bin`, and `npm root`.

- [ ] **Step 2: Run component tests and verify RED**

Run `test_component_installer.py`; expected failure is repeated external discovery and missing vendor-entry recognition.

- [ ] **Step 3: Resolve the managed Codex entry first**

```python
def _managed_codex_entry(self, install_path: str) -> str | None:
    candidate = os.path.abspath(os.path.join(
        install_path, "package", "vendor",
        "x86_64-pc-windows-msvc", "bin", "codex.exe",
    ))
    return candidate if _is_path_inside(candidate, install_path) and os.path.isfile(candidate) else None
```

Resolve one entry at the start of `detect()` and pass it into availability, source checks and version detection. Never call `_first_existing_external_entry()` repeatedly in one transaction.

- [ ] **Step 4: Cache expensive external discovery for 30 seconds**

Cache found and not-found results by component. Explicit refresh bypasses the cache. A cached file path must be discarded if it no longer exists.

- [ ] **Step 5: Skip legacy npm for valid managed Codex**

After swap, if the managed Codex entry exists and `--version` succeeds, skip `component.install_command` only for `codex-desktop`. Other components keep current command behavior.

- [ ] **Step 6: Run tests, benchmark and commit**

Verify managed detection issues one direct version command and zero Appx/npm commands. Commit `perf: detect managed Codex in one pass`.

---

### Task 3: Streaming Download, Verified Cache And Resume

**Files:**
- Modify: `python/core/component_installer.py:154-286,450-525,1080-1120`
- Test: `python/tests/test_component_installer.py`

**Interfaces:**
- Produces: `_verified_cache_path(component) -> str`
- Produces: `_download_to_cache(component, on_progress=None) -> str`
- Produces: `_default_stream_fetcher(url, timeout, target_path, offset, on_progress) -> None`
- Changes: `_extract(component, package_path, staging_path) -> None`

- [ ] **Step 1: Add failing tests**

Add `test_verified_cache_hit_avoids_fetcher`, `test_stream_download_reports_percent_and_size`, `test_partial_download_uses_range_and_appends`, and `test_server_ignoring_range_restarts_without_duplicate_bytes`. Preserve SHA mismatch, retry and traversal tests.

- [ ] **Step 2: Run tests and verify RED**

Run `test_component_installer.py`; expected failures are missing path-based cache and progress APIs.

- [ ] **Step 3: Convert package flow from bytes to verified files**

```python
def _verified_cache_path(self, component):
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", component.version)
    name = f"{component.component_id}-{safe_version}-{component.sha256}.pkg"
    return os.path.join(self.cache_dir, name)
```

Use the same path plus `.part` for partial data. Validate existing cache SHA before use. Hash the completed file and atomically rename only after SHA matches. Extract TGZ/ZIP directly from the file.

- [ ] **Step 4: Add bounded progress**

Report connection, each 5 percentage points or 2 seconds, and completion. Use `下载 Codex：35%（41.3 / 118.0 MB）`. Do not add one Job history entry per network chunk.

- [ ] **Step 5: Add safe Range resume and URL fallback**

Send `Range: bytes=<size>-` only for an existing partial. Append only for HTTP 206; HTTP 200 truncates and restarts. Switching domains restarts unless validators prove identity. Keep finite retry delays.

- [ ] **Step 6: Keep injected byte fetchers compatible**

Write bytes returned by test fetchers to `.part`, then pass through the same SHA and atomic-cache path.

- [ ] **Step 7: Run tests and commit**

Verify cache hits call no fetcher and log `使用已验证本地缓存`. Commit `perf: stream and cache component downloads`.

---

### Task 4: Non-Blocking Installer UI And Draggable Window

**Files:**
- Modify: `src/components/agents/AgentInstallerPage.tsx:19-45,808-1150,1460-1535`
- Modify: `src/components/common/index.tsx:281-330`
- Modify: `src/components/window/WindowTitlebar.tsx:57-83`
- Modify: `src/services/api.ts:605-625`
- Test: `python/tests/test_agent_installer_page_contract.py`
- Test: `python/tests/test_window_chrome_contract.py`

**Interfaces:**
- Consumes: Task 1 quick diagnostics and Task 3 progress messages.
- Produces markers: `data-installer-nonblocking`, `data-installer-active-job`, `data-window-drag-above-overlays`.

- [ ] **Step 1: Add failing UI contracts**

Require quick diagnostic APIs, absence of `AUTO_DETECT_COMPONENT_IDS` and the sequential first-open detect loop, no `overflow-y-hidden` while Jobs run, titlebar z-index above BusyOverlay, and blocking overlay content below the 40px titlebar.

- [ ] **Step 2: Run contracts and verify RED**

Run `test_agent_installer_page_contract.py` and `test_window_chrome_contract.py`.

- [ ] **Step 3: Use cached quick prerequisites**

Show cache immediately, revalidate through `diagnostics.prerequisites()`, and repair through `repairPrerequisites()`. Put timing and measured time only in collapsed details.

- [ ] **Step 4: Remove first-open deep auto-detection**

Delete `AUTO_DETECT_COMPONENT_IDS`, `autoDetectAttempted`, and the sequential effect. Keep explicit selected-component detection and install-time detection.

- [ ] **Step 5: Make locking component-scoped**

Derive active Jobs by component ID. Disable only mutating controls for that component. Poll while any component Job runs so leaving and returning restores progress. Keep sidebar, scrolling, titlebar and other component selection active.

- [ ] **Step 6: Keep titlebar above every overlay**

Change blocking overlay from `fixed inset-0` to `fixed bottom-0 left-0 right-0 top-10`. Add `relative z-[100000]` and `data-window-drag-above-overlays` to `WindowTitlebar`. Installer detection/install uses corner mode with `pointer-events-none`.

- [ ] **Step 7: Render stable progress**

Show latest Job message in the selected component panel. Parse percentage into an `aria-valuenow` progress bar; use a fixed-size indeterminate bar when no percentage exists.

- [ ] **Step 8: Run tests, build and commit**

Run both UI contracts and `npm run build`. Commit `perf: keep installer responsive during jobs`.

---

### Task 5: Online And Complete NSIS Packages

**Files:**
- Create: `../scripts/build-dual-nsis.ps1`
- Modify: `python/core/component_installer.py`
- Test: `python/tests/test_release_scripts_contract.py`
- Test: `python/tests/test_component_installer.py`

**Interfaces:**
- Produces: `build-dual-nsis.ps1 -CodexPackagePath <path> -OutputRoot <path> [-ValidateOnly]`
- Produces filenames ending `-online-setup.exe` and `-complete-setup.exe` plus SHA files.
- Consumes: existing Tauri resource glob `../redist/**/*`.

- [ ] **Step 1: Add failing script contracts**

Require manifest parsing, Codex source size/SHA validation, online build before seed injection, seed only under `openclaw_new_launcher/redist/components/codex-desktop`, complete build after injection, cleanup in `finally`, distinct output names and no deletion of existing release files.

- [ ] **Step 2: Run contracts and verify RED**

Run `test_release_scripts_contract.py`; expected failure is the missing script.

- [ ] **Step 3: Add verified local seed discovery**

Before network access, search `base/redist/components/<id>`, `base/_up_/redist/components/<id>`, and parent `redist/components/<id>`. Verify SHA before copying into cache. A bad seed logs a warning and falls through to URL download.

- [ ] **Step 4: Implement dual build**

Online build runs with no Codex seed. Complete build temporarily copies the verified TGZ under the existing `redist/**/*` resource tree. Copy each Tauri NSIS output to `OutputRoot` before the next build overwrites target output. `-ValidateOnly` performs all safety checks without invoking Tauri.

- [ ] **Step 5: Run dry-run contracts and commit**

Assert source package remains untouched and temporary seed is absent. Commit `build: add online and complete NSIS variants`.

---

### Task 6: Performance Harness And Release-Level Verification

**Files:**
- Create: `scripts/measure-installer-performance.ps1`
- Test: `python/tests/test_process_diagnostics.py`
- Test: `python/tests/test_component_installer.py`
- Test: `python/tests/test_agent_installer_page_contract.py`
- Test: `python/tests/test_window_chrome_contract.py`
- Test: `python/tests/test_release_scripts_contract.py`

**Interfaces:**
- Produces JSON keys: `prerequisiteMs`, `codexDetectMs`, `appxCalls`, `npmCalls`, `prerequisiteBudgetPassed`, `codexBudgetPassed`.

- [ ] **Step 1: Add deterministic benchmark harness**

Run the real quick prerequisite method and temp-state managed Codex detect. Exit nonzero when prerequisites exceed 2000ms, Codex exceeds 500ms, or Appx/npm calls are nonzero.

- [ ] **Step 2: Run focused and full regression**

```powershell
.\python-runtime\python.exe -m unittest discover -s python\tests -p "test_*.py"
npm run build
powershell -ExecutionPolicy Bypass -File scripts\measure-installer-performance.ps1
```

Expected: all tests pass, build succeeds, both budget verdicts are true.

- [ ] **Step 3: Build both installers**

```powershell
powershell -ExecutionPolicy Bypass -File ..\scripts\build-dual-nsis.ps1 `
  -CodexPackagePath "D:\Axiangmu\AUSTART\artifacts\loom-rc\direct-agent-components-20260628\codex-0.142.3-win32-x64.tgz" `
  -OutputRoot "D:\Axiangmu\AUSTART\release"
```

Expected: two new setup files and hashes; no existing release file removed.

- [ ] **Step 4: Smoke-test both variants**

Install each into a unique temp directory. Online logs must show one Codex package download and no `npm install -g @openai/codex`. Complete variant must install Codex with network disabled and pass `codex --version`.

- [ ] **Step 5: Visual interaction verification**

Use Computer Use at 1200x800 and 960x640: drag during detection, scroll and switch sidebar, begin install and drag, navigate away and return, inspect progress/error/retry/completion, and confirm no overlap or blank state.

- [ ] **Step 6: Final adversarial review and commit**

Review cache poisoning, partial corruption, stale Job recovery, duplicate-click races, external Codex preservation, Chinese/English paths and cleanup. Run `git diff --check` and commit the harness as `test: verify installer performance budgets`.

---

## Deferred Next Phase

本计划稳定发布后，为 `license.heang.top/admin` 单独创建授权站优化规格。授权站不得与安装性能改动混合提交，保持独立发布和回滚边界。
