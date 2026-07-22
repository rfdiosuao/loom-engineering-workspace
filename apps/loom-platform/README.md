# OpenClaw Launcher / Lumi Automation Workbench

[![CI](https://github.com/rfdiosuao/lumi/actions/workflows/ci.yml/badge.svg)](https://github.com/rfdiosuao/lumi/actions/workflows/ci.yml)
[![Release](https://github.com/rfdiosuao/lumi/actions/workflows/release.yml/badge.svg)](https://github.com/rfdiosuao/lumi/actions/workflows/release.yml)
[![GitHub release](https://img.shields.io/github/v/release/rfdiosuao/lumi?include_prereleases&label=release)](https://github.com/rfdiosuao/lumi/releases)

> 中文: OpenClaw Launcher 是一套面向交付的 AI 自动化工作台,把 OpenClaw 运行时、桌面启动器、手机控制、桌面 RPA、IM 通道、图像/视频工作流和授权交付封装成客户能直接运行的产品包。
>
> English: OpenClaw Launcher is a delivery-ready AI automation workbench that packages the OpenClaw runtime, desktop launcher, phone control, desktop RPA, IM connectors, image/video workflows, and license delivery into a product-ready desktop distribution.

Current launcher version: `v2.1.11`
Bundled OpenClaw runtime target: `2026.6.5`

Repository: [github.com/rfdiosuao/lumi](https://github.com/rfdiosuao/lumi)

---

## 中文说明

### 这是什么

OpenClaw Launcher 不是一个演示壳,而是一套把 AI Agent 能力交付到真实桌面环境里的工程化平台。它把模型配置、OpenClaw 本体、Python Bridge、Tauri 桌面端、手机 APKClaw 控制、桌面 RPA、飞书/微信/钉钉等通道、在线授权、便携包打包和发布校验串成一条完整链路。

目标很直接:让用户拿到一个包,解压或安装后就能开始做自动化任务,而不是先理解一堆 CLI、依赖、端口、token 和运行时目录。

### 核心能力

| 能力 | 说明 |
| --- | --- |
| OpenClaw 运行时封装 | 默认面向 OpenClaw `2026.6.5`,便携包内置 Node/OpenClaw 运行环境和 workspace 上下文 |
| 桌面启动器 | Tauri 2 + React 18 + TypeScript,提供统一控制台、日志、环境诊断、模型配置和授权入口 |
| 手机控制 | 连接 APKClaw,支持截图、状态读取、任务执行、录屏、图片导入、平台发布和安全签名通道 |
| 桌面控制 | 集成 Luminode 桌面 Agent 源码,支持窗口识别、截图理解、坐标点击、回复发送和 Provider Hub |
| IM 通道 | 飞书、微信、钉钉连接器入口,用于把自动化能力接入消息工作流 |
| AI 图像与视频 | 支持图像生成/编辑、视频生成、广告分镜、首尾帧和素材工作流 |
| Skills 工作区 | 内置办公向 skills,覆盖会议纪要、周报、PDF/OCR、Excel 分析、PPT 生成、文件整理等场景 |
| 授权交付 | 在线 license server、设备绑定、授权状态检查,交付包不内置客户授权码 |
| 便携发布 | Windows portable zip 只暴露 `OpenClaw.exe` + `OpenClawFiles/`,并自动清理 API Key、install id、license 和缓存 |
| 跨平台构建 | Windows 生成安装包/便携包,macOS 生成 `.app` / `.dmg`,Release 自动附带 SHA256 |

### 产品结构

```text
.
├─ openclaw_ui_integration/                # 当前主启动器: Tauri + React + Python Bridge
│  ├─ src/                                 # 前端功能页: 手机控制/桌面控制/图像/视频/Skills/授权/诊断
│  ├─ python/                              # 本地 FastAPI Bridge 与服务层
│  ├─ openclaw-workspace/                  # 交付给 OpenClaw 的 Agent 上下文、能力清单和 skills
│  └─ src-tauri/                           # Tauri shell、授权校验、Bridge 进程管理
├─ openclaw_new_launcher/                  # 旧版启动器目录,保留为 legacy,不再作为发布主线
├─ sightflow-desktop-agent-main/           # 桌面 RPA / Luminode 代理源码
├─ iosclaw/                                # iOS / macOS 适配源码
├─ license_server/                         # 在线授权服务与后台管理
├─ scripts/                                # CI、打包、校验、发布脚本
├─ docs/                                   # 仓库级交付、品牌、CI/CD 和迁移文档
└─ release/                                # 本地构建产物,不提交到 Git
```

### 技术栈

| 层级 | 技术 |
| --- | --- |
| 桌面壳 | Tauri 2, Rust, WebView2/WKWebView |
| 前端 | React 18, TypeScript, Vite, Zustand, Tailwind CSS |
| 本地服务 | Python 3.11, FastAPI-style Bridge, local HTTP API |
| Agent 运行时 | Node.js, OpenClaw `2026.6.5`, local workspace skills |
| 手机侧 | APKClaw / Lumi secure channel |
| 桌面 RPA | Electron/Vite/TypeScript Luminode agent, VLM-assisted UI control |
| 发布 | GitHub Actions, Windows runner, macOS runner, SHA256 verification |

### 快速开始

Windows 开发环境建议:

- Windows 10/11
- Node.js 20+
- Rust stable
- Python 3.11+
- npm

```powershell
cd openclaw_ui_integration
npm ci
npm run build
npm run tauri dev
```

完整本地检查:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

轻量检查:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1 -SkipRust -SkipLicenseFlowTests
```

### Windows 便携包

```powershell
powershell -ExecutionPolicy Bypass -File openclaw_ui_integration\scripts\build-portable-ui-integration.ps1 `
  -Version 2.1.11 `
  -PackageName OpenClaw-Portable-v2.1.11-YYYY.MM.DD `
  -BrandProfile lumi
```

交付包必须保持干净:

```text
OpenClaw.exe
OpenClawFiles/
```

不能带入:

- `data/license.json`
- `data/install_id.txt`
- 客户 API Key
- 客户 IM 账号缓存
- `node_modules/`, `dist/`, `src-tauri/target/`
- 历史 `release/` 产物

### macOS 构建

macOS 构建必须在真实 macOS 环境或 GitHub Actions macOS runner 上执行:

```bash
cd openclaw_ui_integration
npm ci
npm run build
npm run tauri -- build --bundles app,dmg
```

macOS 不能复用 Windows 的 `node_modules`、`src-tauri/target`、Windows Node runtime 或 `.exe` 文件。

### CI/CD 与发行

仓库内置三条主要 workflow:

| Workflow | 用途 |
| --- | --- |
| `ci.yml` | Windows CI: source guard、版本一致性、前端构建、Rust check、Python compile、授权服务测试 |
| `release.yml` | 主启动器 Release: Windows 安装包/便携包 + macOS `.app/.dmg` + SHA256 + GitHub Release |
| `openclaw-ui-integration-release.yml` | UI integration 变体的源码包与 Windows portable 发布 |

手动触发主发布:

```powershell
gh workflow run release.yml `
  --repo rfdiosuao/lumi `
  --ref codex/phone-agent-hardguard `
  -f tag_name=v2.1.11
```

### 安全交付底线

这个仓库按“可交付产品”处理,不是随手堆脚本。任何提交或发行包都必须遵守:

- 不提交真实 API Key、license、install id、IM 登录缓存、数据库和私钥
- 发布包必须生成 SHA256
- Windows portable 必须通过 `verify-release.ps1`
- OpenClaw workspace 必须包含 `AGENTS.md`、`SOUL.md`、`TOOLS.md`、`CAPABILITIES.md`
- 手机和桌面 Agent 的 token 只能存放在私有 launcher config,不能写入公开 runtime context

---

## English

### What It Is

OpenClaw Launcher is an engineering-grade desktop automation platform built around the OpenClaw runtime. It turns a loose collection of agent tools, local services, connectors, packaging scripts, and runtime folders into a product that can be shipped, installed, verified, and operated.

The goal is simple: a user should be able to download one release, install or unzip it, configure their models and channels, and start running automation workflows without manually wiring every dependency.

### Highlights

| Capability | Description |
| --- | --- |
| OpenClaw runtime packaging | Targets OpenClaw `2026.6.5` with bundled runtime dependencies and workspace context |
| Desktop launcher | Tauri 2 + React 18 + TypeScript console for services, logs, settings, diagnostics, and licensing |
| Phone automation | APKClaw integration for screenshots, device state, task execution, recording, media import, and publishing |
| Desktop RPA | Luminode desktop agent source with VLM-assisted layout detection and click/reply automation |
| IM connectors | Feishu, WeChat, DingTalk-oriented entry points for message-channel automation |
| Image and video workflows | AI image generation/editing, video generation, storyboard, keyframe, and material workflows |
| Skills workspace | Office-oriented skills for meeting notes, weekly reports, PDF/OCR, spreadsheet analysis, slides, and file organization |
| License delivery | Online license server, device binding, activation checks, and clean customer packages |
| Portable distribution | Windows portable packages expose only `OpenClaw.exe` and `OpenClawFiles/` at the top level |
| Cross-platform release | GitHub Actions builds Windows assets and macOS `.app` / `.dmg` assets with SHA256 files |

### Architecture

```text
User
  │
  ├─ OpenClaw Launcher UI (React / Tauri)
  │    ├─ Settings, diagnostics, logs, license, skills
  │    ├─ Image / video / storyboard workflows
  │    ├─ Phone control and publishing
  │    └─ Desktop agent control
  │
  ├─ Rust shell
  │    ├─ License verification
  │    ├─ Python Bridge process lifecycle
  │    └─ Packaged resource resolution
  │
  ├─ Python Bridge
  │    ├─ Local HTTP API
  │    ├─ OpenClaw process management
  │    ├─ Media, model, license, diagnostics routes
  │    └─ Secure phone / desktop sidecar config
  │
  └─ OpenClaw runtime
       ├─ Workspace context
       ├─ Built-in skills
       ├─ IM connectors
       └─ Automation execution
```

### Development

```powershell
cd openclaw_ui_integration
npm ci
npm run build
npm run tauri dev
```

Run the full local validation suite:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ci-check.ps1
```

### Release

The main release workflow builds and publishes:

- Windows Tauri installer assets
- Windows portable zip
- macOS `.app.zip`
- macOS `.dmg`
- SHA256 checksum files

```powershell
gh workflow run release.yml `
  --repo rfdiosuao/lumi `
  --ref codex/phone-agent-hardguard `
  -f tag_name=v2.1.11
```

### Audience

OpenClaw Launcher is for builders who need an AI automation product that can actually be delivered:

- AI automation studios
- Desktop RPA builders
- Agent workflow integrators
- Teams packaging OpenClaw into customer-ready deployments
- Developers adapting the launcher to Windows, macOS, phone, and IM automation scenarios

### License

LOOM-owned code is dual-licensed under GNU AGPL v3.0 only or a separate commercial license. See the repository root [`LICENSE`](../../LICENSE), [`LICENSE-COMMERCIAL.md`](../../LICENSE-COMMERCIAL.md), and [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md). Third-party components remain under their respective licenses.
