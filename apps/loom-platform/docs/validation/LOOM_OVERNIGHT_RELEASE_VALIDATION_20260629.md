# LOOM overnight release validation - 2026-06-29

## Verdict

不建议发布 stable。

当前分支已经从 rc8 推进到“明确阻塞”状态：rc8 能安装、能启动 Bridge、主界面/安装页/账号入口/手机入口可访问，但在线首启运行时层没有补齐 `LOOMFiles\node_modules\openclaw\openclaw.mjs`。已做最小 rc9 修复并重新打包，构建和静态验证通过，但 clean online smoke 仍未补齐 openclaw-deps。根因已定位到 release-channel 的 `openclaw-deps.tar.gz` 层包格式损坏，Rust bootstrap 解压失败。

## Worktree and Boundary

- Branch: `codex/xinflo-style-super-installer`
- Worktree: dirty;主要改动仍集中在 `openclaw_new_launcher`、`scripts`、`docs`。`openclaw_ui_integration` 仍有历史脏改，但 release zip 边界检查未包含它。
- `git diff --check`: passed. Evidence: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\logs\git-diff-check-final.txt`
- rc9 release boundary check: no `openclaw_ui_integration` and no `OpenClawFiles`. Evidence: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\logs\release-boundary-check-rc9.json`

## Release Artifacts

rc8 checked:

- `D:\Axiangmu\AUSTART\release\LOOM-Online-Setup-v2.1.19-20260629-rc8.exe`
- `D:\Axiangmu\AUSTART\release\LOOM-Online-v2.1.19-20260629-rc8.zip`
- `D:\Axiangmu\AUSTART\release\LOOM-Portable-v2.1.19-20260629-rc8.zip`

rc9 generated after the minimal bootstrap fix:

- `D:\Axiangmu\AUSTART\release\LOOM-Online-Setup-v2.1.19-20260629-rc9.exe`
  - SHA256 `F2EFD1CCBDF8ACDA0353F3258228DF5DFEBE718278CF1D511879FB397EADABCA`
- `D:\Axiangmu\AUSTART\release\LOOM-Online-v2.1.19-20260629-rc9.zip`
  - SHA256 `91D2298810D263D2059BBFD01B19BDF889EE9308DA8AA314D9127D532F199D78`
- `D:\Axiangmu\AUSTART\release\LOOM-Portable-v2.1.19-20260629-rc9.zip`
  - SHA256 `BF1CF45C34F7889454210B189345D6463D034A21A2900BA82EC61047F69FE323`

## Passed Evidence

- rc8 online installer clean-dir install succeeded.
  - Evidence: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\logs\online-installer-smoke.txt`
- rc8 app launched and Bridge started.
  - Bridge log: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\install\LOOM\LOOMFiles\data\logs\bridge-service.log`
  - Port evidence: `[Bridge] Started on port 18793 (fastapi)`
- rc8 UI screenshots captured:
  - startup/main: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\01-startup-or-main.png`
  - overview: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\02-overview-main.png`
  - Agents: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\07-agents-stable-page.png`
  - account: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\04-account-entry.png`
  - phone: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\05-phone-entry.png`
- rc9 build/static verification passed:
  - `cargo check`: passed.
  - `npm run build`: passed with existing Vite dynamic import warning.
  - `scripts\verify-release.ps1` against rc9 portable zip: passed.
  - `scripts\verify-portable-smoke.ps1` against rc9 portable dir: passed.
  - `scripts\verify-installer-manifest.ps1` against rc9 portable manifest: passed.
  - Online package shape check: passed.

## Blocking Evidence

rc8 and rc9 both fail the online runtime dependency completion gate:

- Missing file after online first run:
  - `LOOMFiles\node_modules\openclaw\openclaw.mjs`
- rc8 UI after “一键补齐” still reports:
  - `便携包完整性`
  - `缺失: node_modules\openclaw\openclaw.mjs`
  - Evidence screenshot: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\screenshots\10-after-one-click-fill.png`
  - Accessibility log: `D:\Axiangmu\AUSTART\artifacts\overnight-rc8-20260629\logs\10-after-one-click-fill-accessibility.txt`
- rc9 clean online package smoke:
  - Node layer installed.
  - Python runtime present.
  - `node_modules\openclaw\openclaw.mjs` still missing after timeout.
  - Evidence: `D:\Axiangmu\AUSTART\artifacts\overnight-rc9-20260629\logs\layer-final-rc9.txt`
  - Screenshot: `D:\Axiangmu\AUSTART\artifacts\overnight-rc9-20260629\screenshots\rc9-current-window.png`

Root cause evidence:

- The release-channel layer downloads and matches the manifest hash:
  - `D:\Axiangmu\AUSTART\artifacts\overnight-rc9-20260629\logs\openclaw-deps-manual.tar.gz`
  - SHA256 matched `be7b699fc967e5e74041664142cf286b201cc4b2b8f633a759f5265885188dcd`
- The same archive emits repeated tar errors:
  - `Damaged tar archive (bad header checksum)`
- Manual extraction still reveals the expected file, but Rust bootstrap treats the tar error as fatal and removes the layer archive.
  - Probe output confirmed `node_modules\openclaw\openclaw.mjs` exists after manual extraction.

## Minimal Fix Already Applied

Changed `openclaw_new_launcher\src-tauri\src\bootstrap.rs` so layer presence is based on known sentinels:

- `node` -> `node.exe`
- `openclaw-deps` -> `openclaw\openclaw.mjs`
- `python-runtime` -> `python.exe`

This fixes the weak “directory non-empty” detection, but it cannot overcome the damaged release-channel tar layer.

## Next Fix Order

1. Regenerate `openclaw-deps.tar.gz` from a clean `LOOMFiles\node_modules` using a tar writer that Rust `tar` can read without checksum errors.
2. Update `D:\Axiangmu\loom-release-channel\rc\layers\v2.1.19\openclaw-deps.tar.gz` and its sha file locally.
3. Update `D:\Axiangmu\loom-release-channel\rc\release-manifest.json` with the new `openclaw-deps` sha256 and, if rc9 is the selected candidate, rc9 package metadata.
4. Rebuild the online package with the fixed distribution manifest cache.
5. Repeat clean online smoke until `LOOMFiles\node_modules\openclaw\openclaw.mjs` appears and Agents preflight is clean.
6. Only after that, upload/push the release-channel changes and validate the online installer against the raw GitHub URL.

## Publishing Decision

- Publish stable now: no.
- Publish rc8 as stable: no.
- Publish rc9 as stable: no.
- rc9 can be kept as a local candidate build only; it is not externally usable until the release-channel `openclaw-deps` layer is regenerated and uploaded.
- GitHub/Gitee push: not performed.
