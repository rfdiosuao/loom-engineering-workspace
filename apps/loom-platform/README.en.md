# OpenClaw Launcher / Lumi Automation Workbench

OpenClaw Launcher is a delivery-ready AI automation workbench that packages the OpenClaw runtime, a Tauri desktop launcher, a Python bridge, phone automation, desktop RPA, IM connectors, image/video workflows, skills, and license delivery into a product-ready desktop distribution.

Current launcher version: `v2.3.0`
Bundled OpenClaw runtime target: `2026.6.5`

Main repository README: [README.md](./README.md)

## Core Capabilities

| Capability | Description |
| --- | --- |
| OpenClaw runtime packaging | Bundled runtime dependencies, workspace context, and built-in skills |
| Desktop launcher | Tauri 2 + React 18 + TypeScript control console |
| Phone automation | APKClaw screenshots, state, task execution, recording, media import, and publishing |
| Desktop RPA | Luminode desktop agent source with VLM-assisted UI control |
| IM connectors | Feishu, WeChat, and DingTalk-oriented connection paths |
| AI media workflows | Image generation/editing, video generation, storyboard and keyframe workflows |
| License delivery | Online activation, device binding, and clean customer packages |
| Cross-platform release | Windows installer/portable assets and macOS `.app` / `.dmg` assets through GitHub Actions |

## Development

```powershell
cd openclaw_ui_integration
npm ci
npm run build
npm run tauri dev
```

Run full checks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

## Release

```powershell
gh workflow run platform-release.yml `
  --repo rfdiosuao/loom-engineering-workspace `
  --ref main `
  -f tag_name=v2.3.0
```

The release workflow publishes Windows installer assets, a Windows portable package, macOS `.app.zip`, macOS `.dmg`, and SHA256 checksum files.

## License

LOOM-owned code is dual-licensed under GNU AGPL v3.0 only or a separate commercial license. See the repository root [`LICENSE`](../../LICENSE), [`LICENSE-COMMERCIAL.md`](../../LICENSE-COMMERCIAL.md), and [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md). Third-party components remain under their respective licenses.
