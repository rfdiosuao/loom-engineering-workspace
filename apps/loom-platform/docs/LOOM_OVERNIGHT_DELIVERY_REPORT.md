# LOOM Overnight Delivery Report

Date: 2026-07-01

Scope is frozen to `openclaw_new_launcher`. No production server, real account, real token, private key, payment, or real customer data was touched.

## Executive Status

| Area | Status | Evidence |
| --- | --- | --- |
| Source checks | Pass | `git diff --check` passed with LF/CRLF warnings only. |
| Python compile | Pass | `python -m py_compile openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py` passed. |
| Python tests | Pass via unittest | `python -m unittest discover -s openclaw_new_launcher/python/tests -p "test*.py"` ran 230 tests, OK. `pytest` is not installed in the current Python environment. |
| Frontend build | Pass | `npm run build` in `openclaw_new_launcher` passed. |
| Source text / secret scan | Pass | `scripts/verify-source-text.ps1` passed; high-confidence `sk-*` / private-key scan returned no matches. |
| Installer manifest | Pass | `scripts/verify-installer-manifest.ps1` passed: LOOM `2.1.19-rc.20260628`, 5 components. |
| Portable smoke | Pass | `scripts/verify-portable-smoke.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable` passed. |
| Strict release verification | Pass for current online zip/folder and portable folder | Online package verification passes in online mode. Portable folder now passes strict release verification after removing Python bytecode cache pollution. |
| computer-use UI audit | Completed two passes | Core entries were clicked in the running LOOM desktop window. The install-page manifest blocker was rerun after the debug payload sync and is no longer visible. |

## 2026-07-01 Continuation Evidence

Latest full release rebuild:

- Rebuilt `LOOM-Portable-v2.1.32-20260630-rc1-ui-stable` with a full Tauri build, not `-SkipBuild`; the generated app is `app v2.1.32`.
- Tauri also produced installer bundles at `openclaw_new_launcher\src-tauri\target\release\bundle\msi\LOOM_2.1.32_x64_en-US.msi` and `openclaw_new_launcher\src-tauri\target\release\bundle\nsis\LOOM_2.1.32_x64-setup.exe`.
- Portable zip: `release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable.zip`, SHA256 `CC73AF61E961F6F99A88D59893551DA17274A7E09A190479618D5D9673E8A690`.
- Online zip: `release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip`, SHA256 `BAEAE35D41C213CD14EDFFF747081B8834AC24513666BAA47E0DE64A0FD9211B`.
- Online one-click installer: `release\LOOM-Online-Setup-v2.1.32-20260630-rc1-ui-stable.exe`, SHA256 `860F39893CD8C7428BE52D7634E572469670CB1BF0A33ABDF39B6ED9C21BBD7A`.
- `scripts\verify-release.ps1` passed for online folder, online zip, portable folder, and portable zip; `scripts\verify-portable-smoke.ps1` passed for the portable folder.
- Packaged MCP version check passed for both online and portable payloads: `loom_mcp.SERVER_VERSION == 2.1.32`.
- Computer-use launched `release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable\LOOM.exe`; process path and bridge-session both pointed at the current online package, and the home page displayed `LOOM 2.1.32`.
- Package UI smoke covered Overview, Install, OpenClaw selected state, Models/account login modal, and Phone. The Install page showed a stable detection overlay, compact logs, OpenClaw `打开网页`, and locked one-click model config; the Phone page showed the download/connect/task/result flow.
- Root cause of the earlier `2.1.31` UI proof was identified: `build-portable.ps1 -SkipBuild` reused the seed portable EXE while the frontend bundle in `LOOM.exe` is embedded by Tauri. The current proof supersedes that stale package.
- GitHub RC channel was refreshed and pushed to `rfdiosuao/loom-release-channel` at commit `59084d8`. Remote raw manifest, remote online zip, and remote online setup exe were downloaded after push and their hash/size matched the manifest.
- Online installer smoke passed with `--silent --install-dir <temp> --no-shortcuts --no-launch`: it downloaded the RC zip, installed `LOOM.exe` and `LOOMFiles`, and the installed `LOOMFiles\package.json` reported `2.1.32`; the temporary install directory was removed.

Latest CLI/MCP smoke:

- `python openclaw_new_launcher\python\loom_cli.py status --json` returned structured OK JSON.
- `python openclaw_new_launcher\python\loom_cli.py phone status --json` returned structured `bridge_not_configured` because no LOOM Bridge was running.
- `python openclaw_new_launcher\python\loom_cli.py phone read-screen --json` returned structured `bridge_not_configured` for the same reason.
- `LOOM_CLI_PERMISSION=control python openclaw_new_launcher\python\loom_cli.py phone run-task --prompt "读取当前屏幕" --dry-run --json` returned a dry-run `POST /api/phone/task` payload with `profile=fast` and `maxRounds=12`.
- `python openclaw_new_launcher\python\loom_cli.py logs ledger --limit 3 --json` read Task Ledger entries from `%LOCALAPPDATA%\LOOM\logs\loom-task-ledger.jsonl`.
- MCP module smoke discovered 20 tools: status, models, agents, phone screenshot/read/quick/template, scheduler, logs, matrix, template, and experience tools.
- MCP `loom_phone_read` dry-run returned structured OK JSON under default read permission.
- MCP `loom_phone_quick_task` is rejected under default read permission and succeeds as dry-run with `LOOM_MCP_PERMISSION=control`, preserving the permission boundary.

Latest focused contract tests:

- `python -m unittest openclaw_new_launcher.python.tests.test_loom_cli_contract openclaw_new_launcher.python.tests.test_loom_mcp_contract openclaw_new_launcher.python.tests.test_task_ledger_contract openclaw_new_launcher.python.tests.test_phone_fast_path_contract openclaw_new_launcher.python.tests.test_scheduler_contract` ran 35 tests, OK.

Latest package hygiene:

- `scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk -Online` passed.
- `scripts\verify-release.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk` passed.
- Current online and portable folders contain no `mcp-audit.jsonl`, `loom-task-ledger.jsonl`, phone token config, `bridge-session.json`, `license.json`, `install_id.txt`, `*.pyc`, `*.pyo`, or `__pycache__`.

Latest computer-use pass on the running debug window:

| Entry | Result | Evidence |
| --- | --- | --- |
| Overview | Pass | Shows the two main paths: install agents and connect phone. |
| Install | Pass | Preflight is ready, install controls are enabled, logs are compact, model one-click config is locked until login. |
| Phone | Pass with no-device fallback | Shows App download, IP/token connection, task input, task status, multi-device empty state, scheduler area. Disabled buttons explain missing device/config state. |
| Phone App modal | Pass | `下载手机端 App` opens a native modal with QR code, copy action, and three install steps; close button works. |
| Models/account | Pass for entry | Opens native LOOM login view with verification-code login, password login, guest mode, and subscription entry. No external browser pop-up was triggered. |
| Other abilities | Pass | Shows stable `暂未开放` states and no blank pages. |
| Settings data | Pass | Exposes diagnostics, logs, model account, install, and developer access entries. |
| Developer access | Pass | Opens `.mcp.json`, `python/loom_mcp.py`, CLI smoke command, MCP launch command, and copy buttons. |
| Logs | Pass | `查看日志` opens the log page and exposes `导出日志`. |
| Diagnostics | Partial | Opens and finishes, but in the debug window it reports package-level blockers such as missing portable payload and old Bridge occupation. This must be rechecked in a freshly built package before demo proof. |

No latest UI evidence of blank page, English stack trace, `localhost` user-facing page, or visible `LumiClaw` / `Lumi Agent` branding in the clicked paths.

Installed-package UI check:

- Launched `D:\LOOM\LOOM.exe` through computer-use.
- Window title is `LOOM - 麓鸣智能体安装器`.
- The package window renders the LOOM left navigation, logo, overview, installation status, model/account state, phone path, and "other abilities temporarily unavailable" state.
- The installed package is distinguishable from the debug process: package process is `D:\LOOM\LOOM.exe`; debug process is `openclaw_new_launcher\src-tauri\target\debug\app.exe`.
- The installed package accessibility tree shows the package can read existing local state: model/account, 5/5 agent readiness, phone path, and advanced diagnostics entry.
- Attempted computer-use click on the installed package `安装` nav item failed because Windows hit-testing reported the click point as over the Tauri `msedgewebview2.exe` child window instead of the parent `LOOM.exe` target.
- Attempted UI Automation secondary action also failed because the exposed button only supports `Raise`, `Scroll Up/Down/Left/Right`, `Expand`, and `Collapse`, not `Invoke`.
- Attempted keyboard fallback (`Tab` trace) also did not move focus into the Web content; focus stayed on the outer Tauri text node.
- Attempted WebView2 remote-debugging fallback by relaunching `D:\LOOM\LOOM.exe` with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9223 --remote-allow-origins=*`; `http://127.0.0.1:9223/json/list` was unavailable.
- Therefore, installed-package evidence is currently "launch + screenshot/accessibility tree read" rather than full installed-package click-through. The debug window click-through remains the full interaction evidence. A final release proof still needs manual recording on the package, a Tauri/WebView-aware harness, or a build-time test hook that exposes the WebView automation surface.

## MCP / CLI Closed Loop

Verified:

- `loom status --json` returns structured JSON.
- `loom phone status --json` returns structured JSON; without a running Bridge it reports `bridge_not_configured` in Chinese-safe JSON.
- `loom phone read-screen --json` returns structured JSON; without a running Bridge it reports `bridge_not_configured`.
- `LOOM_CLI_PERMISSION=control loom phone run-task --dry-run --json` returns `POST /api/phone/task` with `profile=fast`, `maxRounds=12`.
- `loom logs ledger --json` reads the Task Ledger from `%LOCALAPPDATA%\LOOM\logs\loom-task-ledger.jsonl`.
- MCP tool discovery exposes status, models, agents, phone, scheduler, logs, matrix, template, and experience tools.
- MCP `loom_phone_read` dry-run returns structured JSON and writes audit to the user log directory, not source.
- Read permission rejects control actions; control permission allows dry-run dispatch.

## Phone Task Compliance Loop

Verified by contract tests and dry-run:

- Device status routes exist and return structured results.
- Phone read/screenshot/task routes are covered by tests.
- Fast/template/direct task profiles are covered by tests.
- Safety gate rejects high-risk bulk outreach in MCP/Matrix tests.
- Task Scheduler contract tests pass.
- Matrix status/dispatch/watch/cancel and template/experience endpoints are covered by tests.

Not verified with a real phone in this pass:

- Real APKClaw connection.
- Real screenshot/read-screen.
- Real action execution on a device.
- Real Lumi/APKClaw signature request against a live handset.

## Task Evidence / Experience Layer

Verified:

- Task Ledger records task id, source, permission, parameter summary, duration, result, failure reason, and action trace id.
- Action Trace records structured steps for CLI/Bridge phone calls.
- Template Optimizer artifacts are written to the user log directory through `audit_log_path`, not into source.
- `logs ledger` can read recent ledger entries.

Release hygiene:

- `openclaw_new_launcher/.gitignore` excludes launcher audit logs and template optimizer artifacts under source data.
- `scripts/verify-release.ps1` forbids audit logs, phone config, bridge session, ledger, trace, and template optimizer files in packages.

## computer-use UI Audit

Tested running window:

- Title: `LOOM - 麓鸣智能体安装器`
- App: `openclaw_new_launcher\src-tauri\target\debug\app.exe`

| Entry | Result | Notes |
| --- | --- | --- |
| Overview | Pass | First screen clearly shows two main paths: install agents and connect phone. |
| Install | Pass | Preflight overlay is stable and full; detection completed in about 18s. The earlier debug blocker was root manifest discovery from `src-tauri\target\debug`; `default_manifest_path` now resolves the repository root manifest. After restarting the debug window and syncing the debug payload copy, the page no longer shows `安装清单未就绪`; `一键安装` and per-agent `安装并启动` are available. |
| Phone | Pass with no-device fallback | Page follows download app -> connect phone -> input task -> view result. QR modal opens. Empty IP validation shows Chinese toast: `请输入手机 IP，例如 192.168.1.78`. |
| Models/account | Pass for entry | Login page opens native LOOM modal. Visitor mode works and returns to overview with Chinese toast. No browser-native alert appeared. |
| Other | Pass | Locked modules show stable `暂未开放` state. No blank page. |
| Settings | Pass | Appearance/update/data/about tabs work. Theme/language controls are visible. |
| Diagnostics | Partial | Page opens and runs diagnostics. In debug environment it reports `阻塞` due missing packaged payload/core-service state, so this should be rechecked in a built package. |
| Logs | Pass | Settings -> Data -> View Logs opens log page. |
| Agent Access / MCP | Pass | Settings -> Data -> Developer Access opens MCP config page with `.mcp.json`, `python/loom_mcp.py`, CLI smoke command, and copy buttons. |

UI issues found:

1. The earlier install-page debug blocker (`安装清单未就绪`) is resolved in the computer-use rerun. The visible page now shows `前置环境已就绪`, available agent rows, and enabled install controls.
2. Phone download modal does not close with Escape in the computer-use pass; the explicit close button works.
3. Diagnostics in debug mode reports package-level blockers; verify in a freshly built package before using it as a demo proof.
4. Advanced entries are cleanly hidden under Settings -> Data, but they are not obvious to a first-time tester.

No UI evidence of:

- Mojibake in rendered UI.
- English stack traces in rendered UI.
- Old `LumiClaw` or `Lumi Agent` branding in visible UI.

## Release Evaluation

Existing artifacts found:

- Online folder: `release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable`
- Online zip: `release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip`
- Online installer: `release\LOOM-Online-Setup-v2.1.32-20260630-rc1-ui-stable.exe`
- Portable folder: `release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable`

Current verdict:

- Online package: can be evaluated. `scripts\verify-release.ps1` now detects `LOOM-Online-*` packages or accepts `-Online`, allows `README-ONLINE.txt`, requires the online `dist-cache` manifest, and does not require bundled `node/node.exe` or `node_modules/openclaw/openclaw.mjs`.
- Online zip verification passed: `scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip -AllowPhoneAgentApk -Online`.
- Online folder verification passed: `scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk -Online`.
- Online auto-detect verification passed without `-Online`: `scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip -AllowPhoneAgentApk`.
- Offline/portable package folder: strict release verification now passes. The failure source was `verify-portable-smoke.ps1` importing Python modules without bytecode suppression and creating `__pycache__` inside the artifact. The smoke script now sets `PYTHONDONTWRITEBYTECODE=1` and runs Python with `-B`; after cleaning the current portable folder, strict -> smoke -> strict all pass with zero `__pycache__` directories/files.
- Latest portable package smoke rerun passed: `scripts\verify-portable-smoke.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable`.
- Latest portable strict release rerun passed: `scripts\verify-release.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk`.
- New package upload: not performed in this pass.

## 2026-07-01 P0 Hygiene Rebuild

New local release candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc2-p0-hygiene`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc2-p0-hygiene.zip`.
- Portable SHA256: `0760A6672E689A12129E7717264ED0F6387C72065144AACA25EF905A992C57D7`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc2-p0-hygiene`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc2-p0-hygiene.zip`.
- Online SHA256: `2C9D288A1227DB61C7E53AA06BDA253F75D8BACF0D36E05F4F300AF71DF71653`.
- MSI: `openclaw_new_launcher\src-tauri\target\release\bundle\msi\LOOM_2.1.33_x64_en-US.msi`.
- NSIS: `openclaw_new_launcher\src-tauri\target\release\bundle\nsis\LOOM_2.1.33_x64-setup.exe`.

P0 fix included in the package:

- `.mcp.json` now launches MCP through `python -B LOOMFiles/_up_/python/loom_mcp.py`.
- `.mcp.json` sets `PYTHONDONTWRITEBYTECODE=1`.
- `bridge.py`, `loom_cli.py`, and `loom_mcp.py` set `sys.dont_write_bytecode = True`.
- `AppPaths.process_env()` injects `PYTHONDONTWRITEBYTECODE=1` for launcher-managed child processes.

Verification evidence:

- `scripts\verify-release.ps1` passed for the 2.1.33 portable folder, portable zip, online folder, and online zip.
- `scripts\verify-portable-smoke.ps1` passed for the 2.1.33 portable folder.
- Package CLI/MCP smoke with `-B` returned structured JSON and created zero `__pycache__`/`*.pyc` files in the package.
- Full Python unittest suite passed: 231 tests OK.
- Frontend build passed: `cd openclaw_new_launcher && npm run build`.
- `git diff --check` passed with line-ending warnings only.
- Brand/mojibake scan found no `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw` hits under `openclaw_new_launcher/src`, `data`, or `python`.

Known limits:

- `pytest` is not installed in the local environment, so Python validation used `unittest`.
- 2.1.33 has not been uploaded to the GitHub release channel in this pass.
- A 2.1.33 online setup exe that downloads from GitHub was not regenerated because the final downloadable URL is not live yet.
- Real phone, real account, real subscription, and real OpenClaw web/model-config recordings remain manual release-gate evidence.

## 2026-07-01 RC3 Version Display Fix

Reason:

- Computer Use launched the 2.1.33 rc2 online package from `release\LOOM-Online-v2.1.33-20260701-rc2-p0-hygiene\LOOM.exe`.
- The process path was correct, but the overview UI still displayed `LOOM 2.1.32`.
- Root cause: two frontend hard-coded version strings remained in `DashboardPage.tsx` and `SettingsPage.tsx`.

Fix:

- Added `openclaw_new_launcher\src\version.ts`, which reads `APP_VERSION` from root `package.json`.
- Updated the overview local-service status and Settings -> About version to use `APP_VERSION`.
- Added `test_frontend_version_contract.py` so future package bumps cannot leave the visible UI hard-coded to an old version.

New candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc3-version-fix`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc3-version-fix.zip`.
- Portable SHA256: `528A323B75D9EC4330BFFE914A534802809A82253544F4F2F944FC565DBE839D`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc3-version-fix`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc3-version-fix.zip`.
- Online SHA256: `9821E24E758628B9E23B7DA161A2CA04AD9C37CE9F223E104B5214171D503675`.

Verification:

- `python -m unittest openclaw_new_launcher.python.tests.test_frontend_version_contract openclaw_new_launcher.python.tests.test_settings_page_contract` passed.
- `npm run build` passed.
- `build-portable.ps1` rebuilt the Tauri app as `app v2.1.33` and passed release verification, portable smoke, and post-smoke release verification.
- `build-online-portable.ps1` produced the matching online zip.
- `scripts\verify-release.ps1` passed for rc3 portable zip, rc3 online zip, and rc3 online folder.
- Package CLI smoke: `loom_cli.py status --json` returned structured JSON.
- Package MCP smoke: `loom_mcp.py` loaded with server version `2.1.33` and 20 tools.
- Runtime pollution scan after package smoke: zero `__pycache__`, `*.pyc`, audit log, ledger, job state, bridge session, license, or install id hits.

Computer Use rc3 UI audit:

| Entry | Result | Notes |
| --- | --- | --- |
| Process path | Pass | Running `LOOM.exe` path was `release\LOOM-Online-v2.1.33-20260701-rc3-version-fix\LOOM.exe`. |
| Version display | Pass | Overview accessibility tree and screenshot showed `LOOM 2.1.33`. |
| Overview | Pass | Shows the two main paths: install agents and connect phone. |
| Install | Pass | Page opens; preflight detection locks accidental clicks, then recovers to available controls. |
| Model account | Pass | Opens the native LOOM relay login modal with verification login, password login, email registration, visitor mode, and old authorization-code entry. |
| Phone | Pass with no-device fallback | Page opens and follows download app -> connect phone -> input task -> result. No-device buttons stay disabled where appropriate. |
| Other | Pass | Shows stable `暂未开放` content instead of blank pages. |
| Settings | Pass | Opens System Settings with Appearance, Updates, Data, and About tabs. |

Remaining release gates:

- rc3 has not been uploaded to the GitHub release channel.
- The online setup exe has not been rebuilt for rc3 because the final downloadable URL is not live yet.
- Real phone, real account, real subscription page, OpenClaw web page, and one-click OpenClaw model configuration still need manual release-gate recording.

Final local validation after rc3:

- `git diff --check` passed with line-ending warnings only.
- `python -m py_compile openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py openclaw_new_launcher/python/bridge.py openclaw_new_launcher/python/core/paths.py` passed.
- `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` passed: 232 tests OK.
- `scripts\verify-source-text.ps1` passed.
- Brand/mojibake scan under `openclaw_new_launcher/src`, `openclaw_new_launcher/data`, and `openclaw_new_launcher/python` returned no hits.
- rc3 online and portable expanded directories both had zero runtime-pollution hits after smoke and UI launch.

## 2026-07-01 RC4 MCP stdio Fix

Reason:

- Package MCP calls worked after the first line, but a Windows stdin smoke exposed that the first JSON-RPC line could be decoded with a BOM/mojibake prefix and return `Parse error`.
- This matters for Codex/Claude Code because tool discovery commonly starts with `tools/list` or `initialize` as the first stdio message.

Fix:

- `loom_mcp.py` now normalizes both standard UTF-8 BOM and Windows ANSI-decoded `UTF-8 BOM + {` mojibake before parsing JSON-RPC.
- Added contract tests for both first-line BOM cases.

New candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc4-mcp-stdio-fix`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc4-mcp-stdio-fix.zip`.
- Portable SHA256: `9E74D68E432B10678ED768346FB2E01F0301C72B2B23CE7D87CC39FA8701EB69`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc4-mcp-stdio-fix`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc4-mcp-stdio-fix.zip`.
- Online SHA256: `017DE34E8FDA82FAAC08EF82668BCCA5D68E13D79943DEA7676166F0F9E21B95`.

Verification:

- `python -m unittest openclaw_new_launcher.python.tests.test_loom_mcp_contract` passed: 11 tests OK.
- Source MCP stdio smoke with a BOM/mojibake first line passed: `tools/list` returned 20 tools; `loom_matrix_dispatch` for `批量私信所有客户` returned `safety_confirmation_required`.
- `build-portable.ps1` rebuilt the Tauri app as `app v2.1.33` and passed release verification, portable smoke, and post-smoke release verification.
- `build-online-portable.ps1` produced the matching online zip.
- `scripts\verify-release.ps1` passed for rc4 portable zip and rc4 online zip.
- Package CLI smoke passed: `status --json` and `phone read-screen --dry-run --json`.
- Package MCP stdio smoke passed: `tools/list` returned 20 tools, `loom_phone_read` returned `/api/phone/read`, and high-risk Matrix dispatch returned `safety_confirmation_required`.
- Runtime pollution scan after package smoke returned zero hits for online and portable expanded directories.
- High-confidence secret scan returned no real `sk-*`, GitHub token, AWS key, Slack token, or private-key block in first-party source or rc4 packages. Broad token/password keyword hits were documentation, variables, and test placeholders.

Current release status after rc4:

- Online package: locally evaluable, not yet uploaded.
- Portable/offline package: locally evaluable, not yet uploaded.
- Online setup exe: not regenerated for rc4 because the final downloadable URL is not live yet.
- Server deployment: not performed.
- Real phone/account/subscription/OpenClaw web/model-config recordings: still required before calling the release candidate fully demo-ready.

## 2026-07-01 RC6 Phone UI And Label Cleanup

Reason:

- Computer-use UI smoke on the phone download dialog showed the raw APK URL in the customer-facing modal. The URL still contains historical repository names, so exposing it in the main UI created brand noise even though the download itself worked.
- `scripts\verify-source-text.ps1` then caught two remaining mojibake labels in `routes_phone.py` for phone Agent task submission.

Fix:

- `PhoneDemoPage.tsx` keeps the QR code and copy action, but the modal now displays `手机端 App 下载链接已准备` instead of the raw download URL.
- `test_phone_demo_page_contract.py` now prevents the raw URL presentation style from coming back.
- `routes_phone.py` task labels now use `手机 Agent`; no APKClaw/Lumi signature compatibility fields were renamed.

Latest candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc6-phone-label-clean`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc6-phone-label-clean.zip`.
- Portable SHA256: `023F2A13B7D07CAFAFE28E7268AAC4214B42C71019E1EC7798455DF5BDF384BF`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc6-phone-label-clean`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc6-phone-label-clean.zip`.
- Online SHA256: `8676FDD83AE1B04EAFD58B6FE0A6D1A697AB5320070426E572846455963069B9`.

Verification:

- `scripts\verify-source-text.ps1` passed after the phone label cleanup.
- `git diff --check` passed; only Git line-ending warnings were printed.
- `python -m py_compile openclaw_new_launcher/python/api/routes_phone.py openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py` passed.
- `python -m unittest openclaw_new_launcher.python.tests.test_routes_phone openclaw_new_launcher.python.tests.test_phone_signature_contract openclaw_new_launcher.python.tests.test_phone_fast_path_contract` passed: 37 tests OK.
- `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` passed: 243 tests OK.
- `python -m pytest openclaw_new_launcher/python/tests` could not run because this machine does not have `pytest` installed; `unittest` is the project-available runner for this workspace.
- `npm run build` passed during the rc6 Tauri build.
- `scripts\verify-release.ps1` passed for rc6 portable zip and rc6 online zip.
- `scripts\verify-portable-smoke.ps1` passed inside the rc6 portable build flow.
- rc6 package CLI/MCP smoke passed: CLI `status --json` returned `ok=true`, CLI `phone read-screen --dry-run --json` returned `/api/phone/read`, MCP `tools/list` returned 20 tools, and MCP `loom_phone_read` returned `/api/phone/read`.
- rc6 package pollution scan returned zero hits for `__pycache__`, `*.pyc`, `mcp-audit.jsonl`, `jobs-state.json`, `account-state.json`, and `bridge-session.json`.
- rc6 high-confidence secret scan returned no real `sk-*`, GitHub token, AWS key, Slack token, or private-key block.
- Computer-use rc6 smoke confirmed the homepage shows `LOOM 2.1.33`, the two main paths `安装智能体` and `连接手机`, and the phone download dialog shows `手机端 App 下载链接已准备` without exposing the raw historical APK URL.

Computer-use UI coverage completed:

| Area | Result |
| --- | --- |
| Account login / guest | Native LOOM login modal opens; verification login, password login, email registration, guest browsing, subscription entry, and old license-code fallback are visible. |
| Installer | Preflight check uses full-page busy overlay, disables unsafe actions during detection, then restores interaction. |
| OpenClaw card | `安装并启动`, `打开网页`, locked `一键配置`, `回滚配置`, uninstall/rollback, and compact install logs are visible. |
| Phone control | Flow is `下载 App -> 连接手机 -> 输入任务 -> 查看结果`; IP field hides `http://` expectations and documents fixed port 9527. |
| Phone App modal | QR code and copy button are usable; raw URL is no longer displayed. |
| Other abilities | Locked as `暂未开放`, no blank page or crash. |
| Settings | Appearance, update, data, and about tabs open; data tab exposes diagnostics, logs, model account, installer, and developer access. |
| Agent Access | Opens from Settings -> Data; shows `.mcp.json`, `python/loom_mcp.py`, CLI smoke, MCP smoke, and copy buttons for Codex / Claude Code configuration. |
| Diagnostics | Opens, runs with full busy overlay, and returns categorized normal/needs-action/blocking status. |
| Logs | Opens from Settings -> Data and shows export/clear controls without flooding the main flow. |

Current release status after rc6:

- Online package: locally evaluable and verified, not uploaded to GitHub release channel in this turn.
- Portable/offline package: locally evaluable and verified.
- Online setup exe: Tauri produced `openclaw_new_launcher\src-tauri\target\release\bundle\nsis\LOOM_2.1.33_x64-setup.exe`, but it has not been wired to a live rc6 download URL.
- Server deployment: not performed.
- Real phone/account/subscription/OpenClaw web/model-config recordings: still required before calling the release candidate fully demo-ready.
- Known dependency risk: `npm install` still reports 1 high severity audit finding; not addressed in this freeze pass.

## 2026-07-01 RC9 P0 Text Cleanup And Package Verification

Reason:

- Final source-text verification passes found remaining mojibake progress messages in `routes_phone.py`: the phone task Agent fallback message and screenshot cache messages.
- rc8 packages were therefore superseded so the final local candidate includes all phone text cleanup.

Fix:

- Replaced the garbled progress messages with `手机任务进入 Agent 兜底`, `手机截图缓存命中`, `手机截图`, and `手机截图缓存已命中`.
- Kept APKClaw/Lumi compatibility protocol fields untouched.

Latest candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc9-phone-text-final`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc9-phone-text-final.zip`.
- Portable SHA256: `BE968979F2C0838F32294F98986AF22185D4F6E97AE1863B2B7E5EA3AE92D137`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc9-phone-text-final`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc9-phone-text-final.zip`.
- Online SHA256: `7184B646E2299343CB724F52F146DF8416AF915C3E694918EAF3C0B5D6CE5135`.

Verification:

- `scripts\verify-source-text.ps1` passed.
- Brand/mojibake scan for `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw` returned no hits under `openclaw_new_launcher/src`, `openclaw_new_launcher/data`, and `openclaw_new_launcher/python`.
- `python -m unittest openclaw_new_launcher.python.tests.test_routes_phone openclaw_new_launcher.python.tests.test_phone_signature_contract openclaw_new_launcher.python.tests.test_phone_fast_path_contract openclaw_new_launcher.python.tests.test_phone_demo_page_contract` passed: 60 tests OK.
- `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` passed: 249 tests OK when run in isolation. A previous parallel run with package verification produced a transient selector KeyError, then the same single test and full suite passed on immediate isolated reproduction.
- `npm run build` passed.
- `scripts\verify-release.ps1` passed for rc9 online directory, online zip, portable directory, and portable zip.
- `scripts\verify-portable-smoke.ps1` passed for rc9 portable directory during package creation.
- Package CLI smoke passed: `status --json`, `phone status --json`, and `phone run-task --dry-run --json --permission control`.
- Package MCP stdio smoke passed: `tools/list` returned 20 tools and `loom_status` returned structured JSON.
- Runtime pollution scan after smoke returned zero hits for `__pycache__`, `*.pyc`, `mcp-audit.jsonl`, `task-ledger.jsonl`, `jobs-state.json`, account snapshots, and account sessions in rc9 online and portable expanded directories.

Current release status after rc9:

- Online package: locally evaluable and verified, not uploaded to GitHub release channel in this turn.
- Portable/offline package: locally evaluable and verified.
- Online setup exe: not regenerated for rc9 or wired to a live rc9 download URL.
- Server deployment: not performed.
- Real phone/account/subscription/OpenClaw web/model-config recordings and Windows shell icon verification are still required before calling this fully demo-ready.

## 2026-07-01 RC9 P0 Window Smoke

Scope:

- Launched and inspected the actual rc9 online package process: `release\LOOM-Online-v2.1.33-20260701-rc9-phone-text-final\LOOM.exe`.
- Confirmed the window title is `LOOM - 麓鸣智能体安装与手机控制启动器`.

Manual UI evidence:

- Installer page: preflight completes to `前置环境已就绪`; during detection, the busy overlay covers the business viewport consistently and disables primary actions.
- Account/subscription: the built-in login dialog exposes verification-code login, password login, email registration, guest browsing, subscription, and legacy license entry. When logged out, `打开订阅页` shows `请先登录中转站账号，再打开订阅页`.
- OpenClaw: selecting the OpenClaw card exposes `打开网页`, `安装并启动`, model configuration, locked `一键配置`, rollback configuration, uninstall, and compact logs. When OpenClaw is not installed, `打开网页` shows `请先安装 OpenClaw，再打开网页版`.
- Phone page: the flow is visible as `下载 App -> 连接手机 -> 输入任务 -> 查看结果`; without a configured device, risky detection/screenshot actions are disabled and task history panes remain visible.

Additional verification after window smoke:

- P0 contract tests passed: 45 tests OK.
- Full Python contract suite passed: 251 tests OK.
- `npm run build` passed.
- `git diff --check`, `scripts\verify-source-text.ps1`, and the brand/mojibake scan passed.

Remaining risks:

- Real account login, live subscription page, OpenClaw installed-state web launch, one-click OpenClaw model write, real phone task, and Windows desktop/taskbar/Alt-Tab icon verification still require a test machine recording.

## 2026-07-01 MCP UTF-8 And Phone Safety Gate Follow-Up

Reason:

- CLI smoke showed `schedule add --command "phone read-screen"` was rejected even though read-screen is a safe phone read path.
- MCP stdio smoke showed a Windows pipeline could mangle Chinese prompts into `????????` unless the MCP process runs with explicit UTF-8 I/O.
- The same smoke also proved phone quick tasks need the same bulk-outreach safety gate as Matrix dispatch.

Fix:

- Allowed the safe scheduled command pair `phone read-screen`.
- Added phone quick/run-task safety gating for bulk private-message/comment/reply/outreach prompts; unsafe prompts now return `safety_confirmation_required`.
- Added `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` to `.mcp.json`, the portable package `.mcp.json` generator, and the Agent Access MCP config example.

Verification:

- `python -m py_compile openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py` passed.
- CLI/MCP/Task Ledger/scheduler/Matrix/phone fast-path contract tests passed: 49 tests OK.
- Full Python test suite passed after the fix: 257 tests OK.
- `npm run build` passed.
- CLI smoke with temp audit dir passed: status, models, phone status, screenshot, read-screen, run-task, template-task, schedule add, logs ledger all returned JSON; bulk Matrix and bulk phone tasks returned `safety_confirmation_required`; ledger/action trace/template optimizer artifacts were written to the temp audit dir.
- MCP stdio smoke with explicit UTF-8 passed: `tools/list` returned 20 tools, `loom_phone_read` returned `/api/phone/read`, and `loom_phone_quick_task` with `批量私信所有客户` returned `safety_confirmation_required`.
- `git diff --check`, `scripts\verify-source-text.ps1`, the brand/mojibake scan, and high-risk secret scan passed.
- Existing rc9 online and portable expanded directories still pass `scripts\verify-release.ps1`.

Packaging note:

- The existing rc9 packages remain locally evaluable, but they do not contain this source-side MCP UTF-8/safety follow-up. A fresh rc10 package is required before uploading or handing a new build to testers.

## 2026-07-01 RC10 MCP UTF-8/Safety Package

Scope:

- Rebuilt a fresh rc10 package from the verified `openclaw_new_launcher` mainline so the MCP UTF-8 and phone safety-gate fixes are included in the distributable artifacts.
- Built the online package from the rc10 portable package and bound it to the RC release manifest URL.

Latest candidate:

- Version: `2.1.33`.
- Portable folder: `release\LOOM-Portable-v2.1.33-20260701-rc10-mcp-utf8-safety`.
- Portable zip: `release\LOOM-Portable-v2.1.33-20260701-rc10-mcp-utf8-safety.zip`.
- Portable SHA256: `BEACA2DA3456695B860824884B36F48F63B425BC2376B276A86997F752BB6EFD`.
- Online folder: `release\LOOM-Online-v2.1.33-20260701-rc10-mcp-utf8-safety`.
- Online zip: `release\LOOM-Online-v2.1.33-20260701-rc10-mcp-utf8-safety.zip`.
- Online SHA256: `00BFFB3EEAB5A6EE117FE8F230DC2BBE5F5D7B55C632DF3941168D1FC62F5C35`.

Package verification:

- rc10 portable directory and portable zip passed `scripts\verify-release.ps1 -AllowPhoneAgentApk`.
- rc10 online directory and online zip passed `scripts\verify-release.ps1 -Online -AllowPhoneAgentApk`.
- rc10 portable directory passed `scripts\verify-portable-smoke.ps1`.
- Package `.mcp.json` contains `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUTF8=1`, and `PYTHONIOENCODING=utf-8`.
- Package CLI smoke passed: `status --json`, `phone read-screen --dry-run --json`, and the high-risk prompt `批量私信所有客户` returns `safety_confirmation_required` under `control` permission.
- Package MCP stdio smoke passed: `tools/list` returns 20 tools, and `loom_phone_quick_task` returns `safety_confirmation_required` for the same high-risk Chinese prompt.
- Runtime pollution scan after smoke returned zero hits for `__pycache__`, `*.pyc`, `mcp-audit.jsonl`, `task-ledger.jsonl`, `jobs-state.json`, account snapshots, and account sessions in the rc10 online expanded directory.

Current release status after rc10:

- Online package: locally evaluable and verified, not uploaded to GitHub release channel in this turn.
- Portable/offline package: locally evaluable and verified.
- Online setup exe: not regenerated for rc10 or wired to a live rc10 download URL.
- Real account login, live subscription page, OpenClaw installed-state web launch, one-click OpenClaw model write, real phone task, and Windows shell icon verification are still required before calling this fully demo-ready.

## Commands Run

```powershell
git status --short
git diff --check
python -m py_compile openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py
python -m pytest openclaw_new_launcher/python/tests
python -m unittest discover -s openclaw_new_launcher/python/tests -p "test*.py"
python -m unittest discover -s openclaw_new_launcher/python/tests -p "test_component_catalog.py"
python -m py_compile openclaw_new_launcher/python/core/component_catalog.py
cd openclaw_new_launcher; npm run build
python openclaw_new_launcher/python/loom_cli.py status --json
python openclaw_new_launcher/python/loom_cli.py phone status --json
python openclaw_new_launcher/python/loom_cli.py phone read-screen --json
$env:LOOM_CLI_PERMISSION='control'; python openclaw_new_launcher/python/loom_cli.py phone run-task --prompt "读取当前屏幕" --dry-run --json
python openclaw_new_launcher/python/loom_cli.py logs ledger --json
powershell -ExecutionPolicy Bypass -File scripts\verify-source-text.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-installer-manifest.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-portable-smoke.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip -AllowPhoneAgentApk
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable.zip -AllowPhoneAgentApk -Online
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\LOOM-Online-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk -Online
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk
powershell -ExecutionPolicy Bypass -File scripts\verify-portable-smoke.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable
powershell -ExecutionPolicy Bypass -File scripts\verify-release.ps1 -Path release\LOOM-Portable-v2.1.32-20260630-rc1-ui-stable -AllowPhoneAgentApk
```

## Next Required Work

1. Regenerate any final portable zip/installer artifact if the release channel needs a fresh archive, then rerun strict verification on that final file.
2. Run one real phone test: connect, screenshot, read-screen, submit one safe template task, read result.
3. Complete installed-package interaction proof. Current installed package can launch and render, but computer-use click is blocked by the Tauri/WebView child hit-test; use manual recording, a WebView-aware harness, or another package-level test method.

## 2026-07-01 rc13 Public Candidate

### Why rc13 Supersedes rc11/rc12

- rc11 was superseded after package MCP smoke showed a Windows stdio encoding edge case: a high-risk Chinese prompt could arrive as `????????`.
- rc12 included the MCP/CLI safety fix, but the portable package was built with internal `-IncludePhoneAgentApk`, so strict public `verify-release.ps1` rejected bundled APK files.
- rc13 is the clean public candidate: it keeps the MCP/CLI safety fix and excludes internal phone APK payloads.

### Artifacts

- Portable: `release\LOOM-Portable-v2.1.34-20260701-rc13-public-clean.zip`
- Portable SHA256: `E5C535375FCBD182EEBF0610F1498C7B321BCE6B5C8F7D853286901F5515C911`
- Online: `release\LOOM-Online-v2.1.34-20260701-rc13-public-clean.zip`
- Online SHA256: `B4B4A3D3AE5C24C3A9DE2A27C3FB3815E9FB11A0F3A09C726F54B700F15D1983`

### Verification Evidence

- Source tests: `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` -> 268 OK.
- Focused MCP/CLI tests: `test_loom_cli_contract`, `test_loom_mcp_contract`, `test_scheduler_contract`, `test_task_ledger_contract` -> 40 OK.
- Frontend build: `cd openclaw_new_launcher && npm run build` -> passed.
- Static checks: `git diff --check` -> passed; brand/mojibake scan -> no hits.
- Release checks: rc13 portable directory, portable zip, online directory, and online zip all passed `scripts\verify-release.ps1`.
- Portable smoke: rc13 portable directory passed `scripts\verify-portable-smoke.ps1`.
- Installer manifest: rc13 online manifest passed `scripts\verify-installer-manifest.ps1`.
- Package CLI smoke: bundled CLI `status --json` and `phone read-screen --dry-run --json` returned structured JSON; high-risk Chinese prompt and garbled `????????` prompt returned structured `safety_confirmation_required`.
- Package MCP smoke: bundled MCP `tools/list` returned 20 tools; `loom_phone_quick_task` with garbled prompt returned structured `safety_confirmation_required`; audit output was redirected to a temp directory.
- Package hygiene: rc13 portable and online directories contain no `mcp-audit.jsonl`, `task-ledger.jsonl`, `jobs-state.json`, `*.pyc`, `__pycache__`, `*.apk`, account session, account snapshot, or wire runtime state files.

### UI Click Evidence

- Exact process path verified: `release\LOOM-Online-v2.1.34-20260701-rc13-public-clean\LOOM.exe`.
- Overview: shows `LOOM 2.1.34`, and the two main paths are visible: install agents first, then connect phone.
- Install page: detection state disables primary actions, shows progress/animation, and returns to `前置环境已就绪`.
- Phone page: organized as `下载 App -> 连接手机 -> 输入任务 -> 查看结果`; IP field only asks for IP and keeps port `9527` fixed.
- Account page: native login modal includes verification login, password login, email registration, guest mode, subscription entry, and old authorization code fallback.
- Settings page: update tab now says `智能体运行时更新`, `检查智能体运行时组件版本`, avoiding confusion with launcher app updates.

### Remaining Manual Gates

- Real account login, balance/subscription page, and model sync still need a credentialed test run.
- OpenClaw installed-state web entry and one-click model write still need a machine with OpenClaw installed and a logged-in model list.
- Real phone task still needs at least one device: connect, screenshot, read-screen, safe template task, result review.
- Windows desktop/taskbar/Alt-Tab icon still needs installed-machine visual recording.
- The online one-click EXE installer was not regenerated for rc13 because the rc13 zip has not been uploaded to a stable URL yet.

## 2026-07-01 Continuation Verification Addendum

### Additional Commands

- `python -m py_compile openclaw_new_launcher/python/loom_cli.py openclaw_new_launcher/python/loom_mcp.py` -> passed.
- `python -m pytest openclaw_new_launcher/python/tests` -> not runnable in this machine because `pytest` is not installed.
- Fallback project test command: `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` -> 268 tests OK.
- `scripts\verify-version-consistency.ps1` -> passed, version `2.1.34`.
- rc13 package scan for `openclaw_ui_integration` / redesign old UI paths -> no hits.
- rc13 package runtime-pollution scan -> 0 files for audit log, task ledger, jobs state, pyc, APK, account session/snapshot, and wire runtime state.

### Secret Scan Notes

- High-risk source scan for real `sk-*`, GitHub PAT, `ghp_*`, AWS access key, Slack token, and private-key blocks -> no source hits in `docs`, `scripts`, and `openclaw_new_launcher` after excluding build/release/vendor output.
- High-risk rc13 package scan found only third-party library false positives: `cryptography` contains the literal OpenSSH private-key header constant, and `PIL` contains encoded font/test data that matches an AWS-key-like pattern. No real project credential was found.
- Broader assignment-style scan reports environment-variable names, test placeholders, and OpenClaw companion example docs such as `YOUR_*`, `${*_API_KEY}`, `shared-secret`, and `xoxb-REPLACE_ME`. These are not real credentials, but they remain noisy third-party example documentation.

### Online Installer State

- `scripts\build-online-exe-installer.ps1` is present and supports a package URL, SHA256, root package name, version, and output path.
- A correct rc13 online installer cannot be regenerated until `LOOM-Online-v2.1.34-20260701-rc13-public-clean.zip` is uploaded to a stable URL. Building it before upload would bake a dead URL into the installer.
- Current valid shareable artifacts are therefore the rc13 online zip and portable zip. The small one-click online setup EXE is pending upload URL confirmation.

## 2026-07-01 rc14 CLI UTF-8 Candidate

### Why rc14 Supersedes rc13

- rc13 was clean enough for public package shape, but a follow-up package smoke found that naked Windows CLI usage could emit Chinese JSON stdout using the system code page if the caller did not set `PYTHONUTF8` or `PYTHONIOENCODING`.
- `loom_cli.py` and `loom_mcp.py` now configure standard streams to UTF-8 at process start, so Codex/Claude Code/MCP and direct CLI calls receive stable structured JSON.
- A regression test covers `phone read-screen --dry-run --json` with both UTF-8 environment variables removed.

### Artifacts

- Portable: `release\LOOM-Portable-v2.1.34-20260701-rc14-cli-utf8.zip`
- Portable SHA256: `07E09383BEFBEDFE73C277D57C35E801981DC01A1125B40422B5C37C4A70D12D`
- Online: `release\LOOM-Online-v2.1.34-20260701-rc14-cli-utf8.zip`
- Online SHA256: `9A1090C200E3708865AE204FB5A3E4161DD615516D6A93D00CFA89D29A9DC0FA`

### Verification Evidence

- `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` -> 269 OK.
- `python -m py_compile` over Bridge, CLI, MCP, account, component, phone, installer, model/account manager, and wire config files -> passed.
- `cd openclaw_new_launcher && npm run build` -> passed.
- `git diff --check` -> passed with line-ending warnings only.
- `scripts\verify-source-text.ps1` -> passed; brand/mojibake scan -> no hits.
- rc14 portable directory, portable zip, online directory, and online zip all passed `scripts\verify-release.ps1`.
- rc14 portable directory passed `scripts\verify-portable-smoke.ps1`.
- rc14 online package manifest passed `scripts\verify-installer-manifest.ps1`.
- Package CLI smoke passed without UTF-8 env vars: `status --json`, `phone status --json`, `phone read-screen --dry-run --json`, and a `????????` control task returning `safety_confirmation_required`.
- Package MCP smoke passed with `LOOM_MCP_PERMISSION=control`: `tools/list` returned 20 tools and `loom_phone_quick_task` returned structured `safety_confirmation_required` for a garbled control task.
- Package hygiene scan found 0 package-local audit logs, task ledgers, job state files, pyc/cache files, APK files, account state files, wire runtime state, or `openclaw_ui_integration` paths.
- Strict zip credential scan found no unexpected real OpenAI keys, GitHub tokens, AWS access keys, or Slack tokens. One Pillow font-table false positive remains documented as third-party library noise.
- rc14 online package launched successfully from `release\LOOM-Online-v2.1.34-20260701-rc14-cli-utf8\LOOM.exe`; the process path pointed at rc14 and the window title was `LOOM - 麓鸣智能体安装与手机控制启动器`.

### Remaining Manual Gates

- Credentialed NewAPI login, balance/subscription page, and model sync still need a real-account recording.
- OpenClaw installed-state web entry and one-click model write still need a machine with OpenClaw installed and a synced model list.
- Real phone task still needs one device: connect, screenshot, read-screen, safe template task, result review.
- Windows desktop/taskbar/Alt-Tab icon still needs installed-machine visual recording.
- The small online setup EXE should be regenerated only after the rc14 online zip is uploaded to a stable URL.

### Workspace Hygiene Addendum

- Root `.gitignore` now ignores `/artifacts/`, which contains local smoke evidence, screenshots, old expanded installer tests, and transient logs. The files remain on disk for inspection, but they no longer appear as untracked source changes.
- rc14 online and portable package scans found no `openclaw_ui_integration` paths and no `artifacts` paths.
- This does not remove or rewrite any evidence files; it only prevents accidental source commits of local runtime/test output.
- Added `scripts\verify-release-secrets.ps1` as a reusable release secret scan. It scans selected source roots and package zip/directory text files for real OpenAI keys, GitHub tokens, AWS access keys, Slack tokens, and private-key blocks, while allowlisting known third-party library constants/examples.
- Release secret scan passed for source plus rc14 online and portable zips: `Secret verification target count: 344`, `Checked text files: 2056`, `Allowed third-party findings: 2`, `Secret verification passed`.

### Source CLI/MCP Contract Smoke

- CLI smoke used an isolated temp `LOOM_AUDIT_DIR`, so no real user LOOM logs or account state were touched.
- CLI commands verified:
  - `status --json`
  - `phone status --dry-run --json`
  - `phone screenshot --dry-run --json`
  - `phone read-screen --dry-run --json`
  - `phone run-task --prompt "open settings" --mode safe --dry-run --json --permission control`
  - `phone run-task --prompt "????????" --mode safe --dry-run --json --permission control`
  - `phone template-task --template read-screen --dry-run --json`
  - `template run --template read-screen --dry-run --json`
  - `schedule add --name "read screen smoke" --command "phone read-screen --dry-run" --every PT15M --dry-run --json --permission automation`
  - `logs ledger --limit 20 --json`
- CLI results: status succeeded; phone status/screenshot/read routed to `/api/phone/status`, `/api/phone/screenshot`, and `/api/phone/read`; safe task routed to `/api/phone/task`; garbled control task returned structured `safety_confirmation_required`; logs ledger returned recent ledger lines.
- CLI evidence artifacts in the temp audit directory: `loom-cli-audit.jsonl`, `loom-task-ledger.jsonl`, `loom-action-trace.jsonl`, and `loom-template-optimizer.json` were all generated. Ledger schema was `loom.task_ledger.v1`; trace schema was `loom.action_trace.v1`; optimizer schema was `loom.template_optimizer.v1` with phone template candidates.
- MCP smoke used isolated temp `LOOM_AUDIT_DIR` and `LOOM_MCP_PERMISSION=automation`.
- MCP `initialize` returned server `loom-mcp` version `2.1.34`; `tools/list` returned 20 tools.
- MCP tools verified: `loom_status`, `loom_phone_screenshot`, `loom_phone_read`, `loom_phone_quick_task`, `loom_schedule_add`, and `loom_logs_tail`.
- MCP results: screenshot/read/safe quick task returned structured dry-run endpoints; garbled quick task returned structured `safety_confirmation_required`; schedule add and ledger tail returned structured success.
- MCP evidence artifacts in the temp audit directory: `mcp-audit.jsonl`, `loom-task-ledger.jsonl`, `loom-action-trace.jsonl`, and `loom-template-optimizer.json` were all generated.

### 2026-07-01 Phone Compliance Closure Addendum

- Filled the remaining compliance-loop gap for local lead records and failed-task retry without adding a new UI surface.
- `MatrixControlPlane` now writes local lead records to `matrix-leads.jsonl` with schema `loom.matrix.lead.v1`; stored fields are source, status, device/campaign/task IDs, short title, redacted summary, and tags. Token-like values, Bearer tokens, phone numbers, and emails are redacted before returning through CLI/API/MCP.
- `MatrixControlPlane.retry_failed()` creates a new retry campaign for failed device tasks only. It preserves execution layer, mode/profile, template/action, target device IDs, `retryOf`, and `retryCount`; safety checks still run, so high-risk outreach prompts cannot bypass confirmation through retry.
- Bridge routes added:
  - `GET/POST /api/matrix/leads`
  - `POST /api/matrix/retry`
- CLI additions:
  - `loom matrix leads --limit N --json`
  - `loom matrix record-lead --summary ... --json`
  - `loom matrix retry --campaign ... --json`
- MCP additions:
  - `loom_lead_list`
  - `loom_lead_record`
  - `loom_matrix_retry`
  Source MCP `tools/list` now returns 23 tools.
- Contract tests added/updated:
  - lead record redaction and local listing
  - failed Matrix campaign retry
  - Bridge lead/retry routes
  - CLI dry-run endpoint contracts and contact-value redaction
  - MCP tool discovery and CLI routing
- Verification:
  - Targeted Matrix/CLI/MCP tests: 46 OK.
  - Full Python tests: `python -m unittest discover -s openclaw_new_launcher\python\tests -p "test*.py"` ran 274 tests OK.
  - Frontend build: `cd openclaw_new_launcher && npm run build` passed.
  - `python -m py_compile` passed for `phone_matrix.py`, `routes_matrix.py`, `loom_cli.py`, and `loom_mcp.py`.
  - `git diff --check` passed with only CRLF warnings.
  - `scripts\verify-source-text.ps1` passed.
  - Brand/mojibake scan found no matches for `澶|鏅|绋|鍚|閿|Lumi Agent|LumiClaw|Lumi / OpenClaw`.
  - Source secret scan passed: 343 text files checked, no real token/password/API key/private key findings.
- Still not claimed complete: computer-use UI all-entry click pass is still pending because the current tool list does not expose the computer-use controller; real account subscription/model sync, installed OpenClaw web/model write, real phone task, and Windows icon recording remain manual gates.

### 2026-07-01 rc15 Matrix Compliance Package Candidate

- Built a new local package candidate after the lead/retry compliance work.
- Offline portable package:
  - `release\LOOM-Portable-v2.1.34-20260701-rc15-matrix-compliance.zip`
  - Size: `346643309`
  - SHA256: `216720DFD69E6921E9D653351E416C748464264EFDB575E8115960A7444B407A`
- Online portable package:
  - `release\LOOM-Online-v2.1.34-20260701-rc15-matrix-compliance.zip`
  - Size: `69127051`
  - SHA256: `23FAB0F5602D248FF687F50B2CC5D1E604047A5E9766FC36C8BD1B1EDAC47F1A`
- Tauri installer artifacts from the same build:
  - `openclaw_new_launcher\src-tauri\target\release\bundle\msi\LOOM_2.1.34_x64_en-US.msi`
  - `openclaw_new_launcher\src-tauri\target\release\bundle\nsis\LOOM_2.1.34_x64-setup.exe`
- Build and verification passed:
  - `scripts\build-portable.ps1 -PackageName LOOM-Portable-v2.1.34-20260701-rc15-matrix-compliance`
  - `scripts\build-online-portable.ps1 -SourcePortableDir release\LOOM-Portable-v2.1.34-20260701-rc15-matrix-compliance -PackageName LOOM-Online-v2.1.34-20260701-rc15-matrix-compliance -DistributionManifestUrl https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/rc/release-manifest.json`
  - `scripts\verify-release.ps1` passed for rc15 portable dir, portable zip, online dir, and online zip.
  - `scripts\verify-portable-smoke.ps1` passed for the rc15 portable dir.
  - `scripts\verify-installer-manifest.ps1` passed for the rc15 online `LOOMFiles\release-manifest.json`.
  - `scripts\verify-release-secrets.ps1 -Source` passed against rc15 online and portable zips: 2056 package text files checked, 2 allowed third-party findings.
- Package CLI smoke passed from the rc15 online package:
  - `matrix leads --limit 2 --json --dry-run` -> `/api/matrix/leads?limit=2`
  - `matrix record-lead --summary ... --permission control --json --dry-run` -> `/api/matrix/leads`
  - `matrix retry --campaign campaign_123 --permission control --json --dry-run` -> `/api/matrix/retry`
  - Contact-like values were redacted in structured output: phone numbers, email addresses, and Bearer tokens did not appear in clear text.
- Package MCP stdio smoke passed from the rc15 online package:
  - `initialize` returned server `loom-mcp` version `2.1.34`.
  - `tools/list` returned 23 tools.
  - `loom_lead_list`, `loom_lead_record`, and `loom_matrix_retry` were discovered and returned structured dry-run endpoints.
- Package hygiene passed after smoke:
  - rc15 online and portable directories contained zero `__pycache__`, `*.pyc`, `mcp-audit.jsonl`, `loom-task-ledger.jsonl`, `loom-action-trace.jsonl`, `loom-template-optimizer.json`, `matrix-leads.jsonl`, `matrix-events.jsonl`, `matrix-tasks.json`, `jobs-state.json`, `bridge-session.json`, `account-state.json`, or `*.apk`.
- Packaging warnings to track:
  - `npm install` reported one high severity vulnerability; this was not remediated in this freeze pass to avoid dependency churn.
  - npm also reported an `EBADENGINE` warning for `hosted-git-info@10.1.1` with current Node `v24.13.0`; build still completed.
- Release judgement:
  - Offline package: locally buildable and verifier-clean for engineering evaluation.
  - Online package: locally buildable and verifier-clean for engineering evaluation; it uses the GitHub RC distribution manifest URL and has not been uploaded or promoted.
  - Installer EXE/MSI: built locally, but not re-smoked on a clean machine in this turn.
  - Server deployment and GitHub/Gitee release: not performed.
  - True release/demo gate remains open until computer-use/desktop click recording, real account subscription/model sync, installed OpenClaw model/web entry, real phone task, and Windows icon recording are completed.

### 2026-07-01 rc15 UI Smoke And Preflight Cache P0

- Computer Use smoke was rerun against the exact rc15 online package by launching `release\LOOM-Online-v2.1.34-20260701-rc15-matrix-compliance\LOOM.exe` with an explicit process path. Initial Computer Use app resolution by product name was polluted by the existing installed `D:\LOOM\LOOM.exe`; explicit process launch confirmed the rc15 process path.
- rc15 overview smoke: window title `LOOM - 麓鸣智能体安装与手机控制启动器`, visible UI shows `LOOM 2.1.34`, and the two main paths are clear: first `安装智能体`, then `连接手机`.
- Account smoke: native model-account modal opens with `验证码登录`、`密码登录`、`邮箱注册`、`暂不登录，继续以访客身份浏览`、`打开订阅页` and `旧授权码`. Guest mode returns to overview with a Chinese toast and no blank page or stack trace.
- Agent installer smoke: install page shows prerequisite detection overlay, disables primary actions during detection, exposes locked one-click model config for Codex/Claude/OpenClaw when not logged in, and keeps advanced details/logs collapsed by default.
- P0 fix after smoke: `ensurePreflightReady()` now reuses a successful in-memory or localStorage preflight report before calling `diagnosticsApi.run()`. This prevents repeat prerequisite scans after a successful detection; manual `重新检测` still forces a fresh check and repair still updates the cache.
- Regression evidence:
  - Red test first: `test_first_open_uses_cached_preflight_until_user_refreshes` failed before the fix because `ensurePreflightReady()` did not consult `preflightCacheUsable`.
  - After the fix: `python -m unittest openclaw_new_launcher.python.tests.test_agent_installer_page_contract.AgentInstallerPageContractTests.test_first_open_uses_cached_preflight_until_user_refreshes` passed.
  - Related UI contracts passed: `python -m unittest openclaw_new_launcher.python.tests.test_agent_installer_page_contract openclaw_new_launcher.python.tests.test_busy_overlay_contract` -> 17 tests OK.
  - Frontend build passed: `cd openclaw_new_launcher && npm run build`.
  - Static check passed: `git diff --check`, with only CRLF normalization warnings.
- Remaining UI smoke gaps: Computer Use was interrupted by physical `Esc` during a later diagnostic click attempt, so Agent Access / diagnostics / task-log pages still need one clean recorded pass. Real login sync, OpenClaw web/model write, and real phone task are still manual release gates.

### 2026-07-01 rc17 APKClaw Download QR Refresh

- Updated the built-in phone App download URL from the old lowercase APK filename to:
  - `https://gitee.com/rfdiosuao/lumiapkclaw/releases/download/lumiclaw13241/OpenClaw-AgentPhone.apk`
- Regenerated `openclaw_new_launcher/public/phone-agent-apk-qr.svg` from the new URL. The SVG includes a `<desc>` with the same URL so the contract test can detect future drift between the button link and QR asset.
- Contract coverage:
  - Red check: `test_phone_demo_has_builtin_phone_app_download_modal` failed while `PhoneDemoPage.tsx` still used the old URL.
  - Green check: `python -m unittest openclaw_new_launcher.python.tests.test_phone_demo_page_contract.PhoneDemoPageContractTests.test_phone_demo_has_builtin_phone_app_download_modal` passed after the page constant and QR were updated.
  - Full phone page contract: `python -m unittest openclaw_new_launcher.python.tests.test_phone_demo_page_contract` -> 14 tests OK.
- Static and build evidence:
  - Old lowercase URL scan returned no matches: `rg -n "openClaw-AgentPhone\.apk" openclaw_new_launcher/src openclaw_new_launcher/public openclaw_new_launcher/python/tests`.
  - `git diff --check` passed with only CRLF normalization warnings.
  - `cd openclaw_new_launcher && npm run build` passed.
  - Gitee HEAD check followed the new URL to `OpenClaw-AgentPhone.apk`, final response `200 OK`, `Content-Length: 35201472`.
- Packages rebuilt after the QR refresh:
  - Portable: `release\LOOM-Portable-v2.1.34-20260701-rc17-phone-apk-url.zip`
  - Portable SHA256: `F7B781EFAC56AB39DE8C25E82B73D595AED2C2EF5EA49D079A439429BCCF5B2F`
  - Online: `release\LOOM-Online-v2.1.34-20260701-rc17-phone-apk-url.zip`
  - Online SHA256: `3C6A5C9D912EE86A42D662C5F67104FBDB5526DBDB986F07D1109BD2269EE11E`
- Release validation passed:
  - `scripts\verify-release.ps1` passed for both rc17 portable zip and rc17 online zip.
  - `scripts\verify-installer-manifest.ps1` passed for rc17 online `LOOMFiles\release-manifest.json`.
  - `scripts\verify-release-secrets.ps1 -Source` passed for rc17 online and portable zips: 2056 package text files checked, 2 allowed third-party findings.
- Packaging warnings unchanged:
  - npm still reports one high severity vulnerability and an `EBADENGINE` warning for `hosted-git-info@10.1.1` under Node `v24.13.0`; this was not remediated during the QR-only patch.
