# Task 6 Report

Date: 2026-07-10
Workspace: `D:\Axiangmu\AUSTART`
Scope: installer performance harness, release verification contract, final validation support

## Changes

- Updated `openclaw_new_launcher/scripts/measure-installer-performance.ps1` to report explicit performance gates instead of release-ready wording.
- Hardened the benchmark tar extraction path handling so every archive member must stay under the temporary `install_path`.
- Extended `openclaw_new_launcher/python/tests/test_release_scripts_contract.py` with Task 6 contract coverage for performance gate naming, validate-only semantics, and tar member validation.

## Safety Notes

- No real account login, bulk outreach, upload, or release publish was triggered.
- The benchmark uses quick prerequisite diagnostics plus a temporary managed Codex detection workspace.
- `performanceGate`, `onlinePerformanceGate`, and `completePerformanceGate` describe only benchmark status. They do not claim a real release is ready.
- `releaseValidation` is the only field that reports `build-dual-nsis.ps1 -ValidateOnly` input checks, and that validation runs only when `-ValidateOnly` is passed.
- `-Simulate` is available for contract/demo runs without touching local release assets.

## Verification

- PowerShell script syntax/execution: `measure-installer-performance.ps1 -ValidateOnly`
- Contract test: `openclaw_new_launcher/python/tests/test_release_scripts_contract.py`
- Validate-only release input validation: `measure-installer-performance.ps1 -ValidateOnly`

## Benchmark Summary

- Expected JSON keys:
  - `prerequisiteMs`
  - `codexDetectMs`
  - `appxCalls`
  - `npmCalls`
  - `prerequisiteBudgetPassed`
  - `codexBudgetPassed`
  - `performanceGate`
  - `onlinePerformanceGate`
  - `completePerformanceGate`
  - `releaseValidation`

- Success rule:
  - prerequisite check <= 2000 ms
  - managed Codex detect <= 500 ms
  - `appxCalls == 0`
  - `npmCalls == 0`

## Notes

- Script is release-safe by default.
- Output can be redirected with `-OutputPath`.
- `build-dual-nsis.ps1 -ValidateOnly` is used only for explicit release input validation and is reported through `releaseValidation`.

## Managed Codex Detect Narrowing

- Updated `openclaw_new_launcher/python/core/component_installer.py` so `_detect_installed_version()` checks managed Codex payload metadata before falling back to `codex.exe --version`.
- The metadata fast path reads `agents/codex-desktop/package/package.json`, normalizes versions like `0.142.3-win32-x64` to `0.142.3`, and only trusts metadata that still matches the managed payload layout.
- If payload metadata is missing, malformed, or does not match the managed entrypoint, version detection falls back to the existing `codex.exe --version` probe. A failed fallback still keeps managed Codex out of `ready`.
- Added targeted coverage in `openclaw_new_launcher/python/tests/test_component_installer.py` for:
  - managed Codex metadata fast path without invoking `--version`
  - malformed metadata falling back to `--version`
  - non-managed components still using the existing version probe path

## Additional Verification

- Component installer suite: `python -m unittest openclaw_new_launcher.python.tests.test_component_installer`
- Full Python suite: `python -m unittest discover -s openclaw_new_launcher/python/tests`
