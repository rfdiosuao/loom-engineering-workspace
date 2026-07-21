# AUSTART · Lumi / OpenClaw 便携启动器 — 项目文档

> 面向商家交付的便携式 AI 创意控制台。本文档基于对仓库源码的实际分析整理,
> 是对 `CODE_WIKI.md` 的校订与扩展版本。
>
> - 仓库根目录:`D:\Axiangmu\AUSTART`
> - 产品名:OpenClaw / Lumi
> - 官网:<https://lumiu.heang.top/>
> - 当前代码版本:**v2.0.6**(`openclaw_new_launcher/package.json` 与 `src-tauri/Cargo.toml`)
> - 文档基准:仓库 `master` 分支实际源码

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈与版本](#2-技术栈与版本)
3. [仓库结构(Monorepo)](#3-仓库结构monorepo)
4. [系统架构](#4-系统架构)
5. [主启动器详解](#5-主启动器详解)
6. [功能矩阵](#6-功能矩阵)
7. [授权与会员体系](#7-授权与会员体系)
8. [子系统:桌面 / 手机 / 发布](#8-子系统桌面--手机--发布)
9. [授权服务器详解](#9-授权服务器详解)
10. [端口与外部服务速查](#10-端口与外部服务速查)
11. [构建、打包与发布](#11-构建打包与发布)
12. [开发与运行](#12-开发与运行)
13. [安全与交付规则](#13-安全与交付规则)
14. [维护备注与已知差异](#14-维护备注与已知差异)

---

## 1. 项目概述

AUSTART(产品名 **OpenClaw / Lumi**)是一个以 **U 盘 / 文件夹便携包**形式交付给商家的
AI 创意控制台。目标是把 OpenClaw 本体、离线运行时、授权激活和一整套 AI 创作能力
封装成客户开箱即可运行的桌面工具,交付包根目录只保留 `OpenClaw.exe` 与 `OpenClawFiles/`。

### 核心能力

| 能力 | 说明 |
|------|------|
| AI 生图 | 通过 OpenAI 兼容 API(默认模型 `gpt-image-2`)生成与编辑图片,内置主图/白底图/详情图三联模板 |
| AI 视频 | 文生视频 / 图生视频,默认模型 `happyhorse-1.0-t2v` / `happyhorse-1.0-i2v`,走 DashScope 异步任务接口 |
| 广告视频 | 分镜、首尾帧、九宫格广告短视频工作流 |
| 手机控制 | 通过 APKClaw 手机 Agent 远程操控安卓设备 |
| 平台发布 | 用手机端发布图文 / 视频,经发布中继(Publish Relay)跨设备协同 |
| 桌面控制 | 通过 SightFlow 桌面代理操控微信等桌面应用 |
| Skills | 本地能力模块的安装、启用、停用与管理 |
| 授权 / 会员 | Ed25519 签名的在线激活 + 本地双层验证;支持会员制与托管 AI 网关下发 |
| 品牌换壳 | 通过主题文件替换 Logo、名称、窗口标题与主题色,无需改前端代码 |
| 环境诊断 | 一键检查并修复端口占用、残留进程、配置损坏等启动问题 |

### 关键设计理念

- **离线优先**:Python 运行时、Node.js 运行时、OpenClaw 核心包随包分发,客户机无需联网安装依赖。
- **交付即净**:打包脚本强制清空授权文件、安装 ID、API Key 与机器人缓存,杜绝把上家信息带给下家。
- **可贴牌**:运行时品牌(主题文件)与构建时品牌(Tauri 图标 / 产品名)解耦,支持轻量换肤与完整换壳两种交付。

---

## 2. 技术栈与版本

以下版本号取自仓库实际的 `package.json` / `Cargo.toml` / `requirements.txt`。

### 主启动器 `openclaw_new_launcher`

| 层 | 技术 | 版本 |
|----|------|------|
| 桌面壳 | Tauri | `2.11.0`(`tauri-build 2.6.0`) |
| 后端语言 | Rust | edition 2021,`rust-version 1.77.2` |
| 前端框架 | React + React DOM | `18.3.1` |
| 状态管理 | Zustand | `5.0.0` |
| 构建工具 | Vite | `8.0.11` |
| 样式 | Tailwind CSS | `3.4.4`(+ PostCSS / Autoprefixer) |
| 语言 | TypeScript | `5.5.0` |
| 中间层 | Python | `3.11+` |
| Web 框架 | FastAPI + Uvicorn | `fastapi>=0.115`、`uvicorn>=0.34` |
| 数据校验 | Pydantic | `>=2.0` |
| 加密 | cryptography(Ed25519) | `>=42` |
| 图像 | Pillow | `>=10` |

> 说明:`CODE_WIKI.md` 中"Tauri + Vue3/React"的表述不准确。前端是**纯 React 18**,
> 无 Vue。打包发布版本是 **v2.0.6**,README 中的 `v2.0.1` 为旧文案。

### 关键 Rust 依赖(`src-tauri/Cargo.toml`)

`tauri 2.11` · `tauri-plugin-shell 2` · `tauri-plugin-log 2` · `reqwest 0.12` ·
`ed25519-dalek 2` · `sha2 0.10` · `chrono 0.4` · `base64 0.22` ·
`windows-sys 0.60`(磁盘卷序列号 / Shell / 窗口管理)。

### 授权服务器 `license_server`

纯 Python 标准库实现(`http.server.ThreadingHTTPServer` + `sqlite3`),
仅依赖 `cryptography` 做 Ed25519 签名。无需 Web 框架。

### 桌面代理 `sightflow-desktop-agent`

Electron + electron-vite(包名 `luminode-desktop-agent` v1.0.0),Node `>=18`。

---

## 3. 仓库结构(Monorepo)

```text
AUSTART/
├─ openclaw_new_launcher/      # 【主项目】Tauri 2 + React 18 + Python FastAPI 桥
├─ openclaw_ui_integration/    # 启动器的 UI 集成工作副本(同名 v2.0.6,含手机脚本集)
├─ license_server/             # 授权服务器:激活 + 会员网关 + 发布中继 + 管理后台
├─ sightflow-desktop-agent/    # 桌面 RPA 代理(Electron,"luminode-desktop-agent")
├─ sightflow-desktop-agent-main/ # 桌面代理主线版本(打包优先取此目录)
├─ apkclaw/                    # 安卓手机 Agent(Hermes-Agent 手机模板)
├─ iosclaw/                    # iOS Agent(XcodeGen project.yml + iOSClaw)
├─ lumiu-official-site/        # 官网 lumiu.heang.top 源码(静态 HTML/CSS/JS)
├─ lumiu-partner-film/         # 合作/宣传片素材
├─ scripts/                    # 仓库级 PowerShell 构建 / 校验 / 发布脚本
├─ docs/                       # 仓库级文档(品牌、CI/CD、本项目文档、文档站)
├─ data/                       # 本地运行状态目录(状态文件不提交)
├─ release/                    # 本地构建产物(不提交)
├─ _research/ · scratch/ · ui-redesign-preview/ · dev-env-profile/ · austart-electron-fix/
│                             # 调研、草稿、UI 预览、开发环境画像、历史修复等辅助目录
```

> 注意:不要把仓库旁边的 `D:\Axiangmu\U盘启动器` 当成源码工作区,那里只作为临时测试包
> 或历史打包产物位置。

---

## 4. 系统架构

主启动器是一套 **三层架构**:Rust 为壳、Python 为桥、TypeScript 为面。

```
┌──────────────────────────────────────────────────────────────┐
│                  Tauri 桌面窗口 (WebView2)                      │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │            React 前端 (TypeScript + Vite)                  │ │
│  │  Sidebar │ Dashboard │ Image │ Video │ Storyboard │ ...   │ │
│  └─────────────────────────┬────────────────────────────────┘ │
│                            │ invoke('proxy_request')           │
│  ┌─────────────────────────┴────────────────────────────────┐ │
│  │              Rust 后端 (src-tauri/src/lib.rs)             │ │
│  │  • start_bridge()   启动 Python Bridge 子进程             │ │
│  │  • proxy_request()  代理 HTTP 到 Bridge(受保护路径鉴权) │ │
│  │  • verify_license() Rust 层 Ed25519 授权校验             │ │
│  │  • phone_proxy_request()  手机 Agent 代理                 │ │
│  └─────────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼───────────────────────────────────┘
                             │ HTTP 127.0.0.1:<bridge_port>
┌────────────────────────────┴───────────────────────────────────┐
│              Python Bridge (FastAPI / uvicorn)                  │
│  Process │ License │ Member │ Image │ Video │ Desktop │ Theme   │
│  Service │ Manager │ Manager│ Client│ Client│ Agent   │ Manager │
│  Updater │ Skill   │ Diagnostics │ Config │ Log │ System ...    │
└────────────────────────────┬───────────────────────────────────┘
            ┌────────────────┼─────────────────┬─────────────────┐
            ▼                ▼                  ▼                 ▼
     OpenClaw 核心      SightFlow 桌面代理   License Server   AI 服务/网关
     (Node.js:18790)    (Electron HTTP)     (HTTPS)          (DashScope/OpenAI 兼容)
```

### 启动与鉴权链路

1. Tauri 启动时在 `setup()` 中异步调用 `start_bridge()`。
2. Rust 定位 `bridge.py` 与 Python 解释器(随包优先,系统回退),`spawn` 子进程。
3. Bridge 启动后向 stdout 打印 `BRIDGE_PORT=<port>` 与 `BRIDGE_TOKEN=<token>`,
   Rust 解析后存入内存(`AtomicU16` / `Mutex`),作为后续请求的端口与令牌。
4. 前端所有业务请求经 `api.ts` → `invoke('proxy_request', {path, method, body})`。
5. Rust 对**受保护路径**先执行 `license::ensure_authorized(feature)`,通过后用
   `reqwest` 转发到 `http://127.0.0.1:<bridge_port>/<path>`,返回响应文本给前端。

### 受保护路径(需授权)

| 路径 | 所需功能 |
|------|----------|
| `/api/process/start` | `openclaw` |
| `/api/image/generate` | `image` |
| `/api/video/generate` | `video` |

---

## 5. 主启动器详解

### 5.1 Rust 后端(`src-tauri/`)

| 文件 | 职责 |
|------|------|
| `src/main.rs` | 入口,调用 `app_lib::run()` |
| `src/lib.rs` | Tauri 命令注册、Bridge 启动 / 代理、诊断报告、日志导出 |
| `src/license.rs` | Ed25519 授权验证(签名校验、installId / deviceId / 过期 / 功能检查) |
| `Cargo.toml` | Rust 依赖声明 |
| `tauri.conf.json` | 窗口配置、权限声明、资源打包规则、产品名与窗口标题 |

**核心 Tauri 命令(`invoke` 名)**

| 命令 | 功能 |
|------|------|
| `start_bridge` | 查找并启动 Python Bridge,读取端口与 Token |
| `proxy_request` | 代理前端 HTTP 请求到 Bridge,受保护路径先鉴权 |
| `phone_proxy_request` | 代理手机 Agent 的 HTTP 请求 |
| `get_bridge_port` | 返回当前 Bridge 端口 |
| `get_portable_base_path` | 返回便携包根目录 |
| `verify_license` | Rust 层授权状态检查 |
| `bridge_startup_report` | Bridge 启动诊断报告 |
| `export_log` | 导出日志到文件 |
| `open_path` | 在系统文件管理器中打开路径 |

### 5.2 Python Bridge(`python/`)

Bridge 是一个 FastAPI 应用,作为 Tauri 与业务逻辑之间的中间层。入口 `bridge.py`
负责服务发现、依赖注入与启动,并打印端口 / Token 供 Rust 读取。

**核心模块**

| 模块 | 路径 | 职责 |
|------|------|------|
| 入口 | `bridge.py` | 服务发现、依赖注入、FastAPI 启动 |
| 路径发现 | `core/paths.py` | 便携包 / 开发 / 打包三种模式下的路径推导(`AppPaths`) |
| 全局常量 | `core/constants.py` | 端口、URL、模型名、Provider 预设、主题色 |
| JSON 存储 | `core/storage.py` | JSON 文件读写工具 |
| 授权管理 | `core/license_manager.py` | 在线激活、本地验证、设备绑定(`LicenseManager`) |
| 会员管理 | `core/member_manager.py` | 会员账号与托管网关凭据(配合 License Server) |
| 主题管理 | `core/theme_manager.py` | 主题三级回退、`DEFAULT_THEME` 单一真源 |
| 进程管理 | `services/process.py` | OpenClaw 核心进程启动 / 停止 / 诊断 / 修复 |
| 桌面代理 | `services/desktop_agent.py` | SightFlow 进程管理与请求代理(含操作策略) |
| 生图客户端 | `services/image_api.py` | OpenAI 兼容生图 / 图生图(`ImageApiClient`) |
| 视频客户端 | `services/video_api.py` | DashScope 异步视频任务(`DashScopeVideoClient`) |
| 更新器 | `services/updater.py` | OpenClaw 包更新 |
| Skill 服务 | `services/skills.py` | Skill 包安装 / 卸载 / 启用 / 禁用(`SkillService`) |

**API 路由(`api/routes_*.py`,经 `fastapi_routes.py` 注册)**

| 路由模块 | 端点前缀 |
|----------|----------|
| `routes_process` | `/api/process/*` |
| `routes_license` | `/api/license/*` |
| `routes_member` | `/api/member/*`(会员 / 网关) |
| `routes_media` | `/api/image/*`、`/api/video/*` |
| `routes_desktop_agent` | `/api/desktop-agent/*` |
| `routes_diagnostics` | `/api/diagnostics/*` |
| `routes_config` | `/api/config/*` |
| `routes_theme` | `/api/theme/*` |
| `routes_log` | `/api/log/*` |
| `routes_update` | `/api/update/*` |
| `routes_skills` | `/api/skills/*` |
| `routes_system` | `/api/system/*` |

**`AppPaths` 关键路径(`core/paths.py`)**

| 属性 | 说明 |
|------|------|
| `node_dir` / `node_exe` | 随包 Node.js 运行时与可执行文件 |
| `data_dir` | 数据目录 `{base}/data` |
| `state_dir` | 状态目录 `{base}/data/.openclaw` |
| `openclaw_config` | `{state_dir}/openclaw.json` |
| `license_file` | `{data_dir}/license.json` |
| `install_id_file` | `{data_dir}/install_id.txt` |
| `generated_images_dir` | `{data_dir}/generated-images` |
| `skills_dir` | `{state_dir}/skills` |
| `themes_dir` | `{data_dir}/themes` |

**OpenClaw 核心启动流程(`services/process.py`)**

存储健康检查 → 清理残留进程(ClawPanel / Gateway / 端口占用)→ 重建
`openclaw.json`(如损坏)→ 初始化 workspace(AGENTS.md、SOUL.md 等)→ 写入
`runtime-context.json` → `subprocess.Popen([node_exe, start.js])` → 等待网关端口
`18790` 就绪(最长约 420s)→ 写入启动快照。

### 5.3 前端(`src/`)

基于 React 18 + TypeScript + Vite 的单页应用,Zustand 管理全局状态。

| 目录 | 职责 |
|------|------|
| `components/` | 页面组件(Dashboard / Image / Video / Storyboard / License / Phone / Desktop / Publish / Skills / Diagnostics / Terminal) |
| `components/sidebar/` | 侧边栏导航 |
| `components/dialogs/` | 对话框(API 配置、飞书、微信机器人安装台) |
| `components/window/` | 自定义窗口标题栏 |
| `features/registry.ts` | 功能注册表(导航定义、是否需授权、动作类型) |
| `features/pages.tsx` | 页面 key → 组件映射 |
| `services/api.ts` | 主 API 层(proxy 链路) |
| `services/phoneApi.ts` | 手机 Agent API |
| `services/gatewayConfig.ts` | 托管网关配置 |
| `stores/appStore.ts` · `stores/logStore.ts` | Zustand 状态 |
| `providers/` · `hooks/` · `theme/` · `types/` · `styles/` | 主题 Provider、Hook、默认主题、类型、样式 |

**前端 → 后端调用链**

```
React 组件
 → api.ts: api<T>(path, method, body)
   → ensureBridgeStarted() → invoke('start_bridge')
   → invoke('proxy_request', { path, method, body })
     → Rust: 受保护路径 license::ensure_authorized(feature)
     → Rust: reqwest → http://127.0.0.1:<port>/<path>
       → Python FastAPI 路由处理 → JSON
     ← Rust 返回响应文本
   ← api.ts 解析 JSON
 ← React 组件渲染
```

---

## 6. 功能矩阵

下表来自前端功能注册表 `src/features/registry.ts`(单一真源),
按侧边栏分组列出。`需授权` 标记的功能在未激活时不可用。

| key | 名称 | 分组 | 需授权 | 动作 |
|-----|------|------|:------:|------|
| `dashboard` | 系统状态总览 | 工作台 | | 页面 |
| `terminal` | 服务日志 | 工作台 | | 页面 |
| `storyboard` | 广告视频(分镜/首尾帧/九宫格) | 工作台 | ✅ | 页面 |
| `image` | AI 生图(生成/编辑) | 工作台 | ✅ | 页面 |
| `video` | AI 视频(多模型生成) | 工作台 | ✅ | 页面 |
| `phone` | 手机控制(连接 APKClaw) | 工作台 | ✅ | 页面 |
| `publish` | 平台发布(手机发图文/视频) | 工作台 | ✅ | 页面 |
| `desktop` | 桌面控制(桌面代理) | 工作台 | ✅ | 页面 |
| `license` | 授权码(在线激活) | 配置 | | 页面 |
| `api` | API 配置(模型密钥) | 配置 | | 对话框 |
| `feishu` | 飞书机器人 | 配置 | | 对话框 |
| `weixin` | 微信机器人 | 配置 | | 对话框 |
| `skills` | Skills(安装/启用能力模块) | 扩展 | | 页面 |
| `web` | 网页界面(本地控制台) | 维护 | | 外链 `127.0.0.1:18790` |
| `diagnostics` | 环境诊断(检查/修复) | 维护 | | 页面 |
| `update` | 检查更新(更新 OpenClaw) | 维护 | | 命令 |
| `help` | 帮助文档 | 维护 | | 外链 `heang.top/docs.html` |

---

## 7. 授权与会员体系

### 7.1 授权激活流程

```
1. 管理员在 License Server 生成授权码:OC-{EDITION}-XXXX-XXXX-XXXX-XXXX
2. 用户在启动器"授权码"页输入授权码
3. 启动器 POST /activate { code, installId, deviceId }
4. Server 校验授权码有效性,用 Ed25519 私钥签发许可证
5. 许可证写入 data/license.json
6. 之后每次使用受保护功能,Rust 与 Python 双层验证许可证
```

### 7.2 许可证验证链(`license.rs` / `license_manager.py`)

```
读取 data/license.json
 → 用 Ed25519 公钥验证 signature(canonical JSON)
 → 校验 installId 匹配(data/install_id.txt)
 → 校验 deviceId 匹配(磁盘卷序列号 SHA256,支持盘符变更)
 → 校验未过期(expires >= today)
 → 校验功能权限(features 数组包含所需功能)
```

默认功能集:`openclaw`、`image`、`video`、`storyboard`。

### 7.3 设备绑定

- Windows 使用 `GetVolumeInformationW` 取磁盘卷序列号(`windows-sys`),对其做 SHA256。
- 绑定到**卷序列号**而非盘符,U 盘拔插后盘符变化仍可识别。
- 兼容旧版盘符绑定(遍历 A–Z 生成候选 deviceId)。

### 7.4 会员与托管网关(新增)

License Server 在激活的基础上扩展了**会员制 + 托管 AI 网关**:

- 服务端通过 `MEMBER_GATEWAY_*` 环境变量配置统一的对话 / 生图 / 生视频网关地址、
  令牌与默认模型。
- 激活 / 登录后,服务端可向客户端下发网关凭据,客户端经
  `core/member_manager.py` 与前端 `services/gatewayConfig.ts` 使用,
  让会员**无需自带 API Key** 即可调用 AI 能力(由平台侧网关统一计费 / 限流)。
- 该机制与"自带 Key"模式并存:`api` 配置对话框仍支持填入自有 Provider 密钥。

---

## 8. 子系统:桌面 / 手机 / 发布

### 8.1 桌面代理 SightFlow(`sightflow-desktop-agent[-main]`)

基于 Electron 的桌面 RPA 执行器(包名 `luminode-desktop-agent`),
由 Bridge 的 `desktop_agent.py` 拉起并代理。提供截图、点击、键盘输入、
窗口管理,以及微信相关自动化。

| HTTP 端点 | 功能 |
|-----------|------|
| `/health` | 健康检查 |
| `/screenshot` | 屏幕截图 |
| `/click` · `/type` | 鼠标点击 / 键盘输入 |
| `/measure_layout` | 布局测量 |
| `/wechat/send` | 微信发送消息 |
| `/wechat/unread` · `/wechat/contact_unread` | 未读检测 |
| `/wechat/chat_diff` | 聊天差异检测 |
| `/engine/status` | 引擎状态 |

> 安全:`desktop_agent.py` 在代理请求前执行 `_enforce_policy`,对截图 / 点击 /
> 输入 / 微信发送等动作做权限与确认校验。打包时**优先取 `-main` 版本**目录。

### 8.2 手机 Agent APKClaw(`apkclaw/`)

安卓侧手机 Agent(Hermes-Agent 手机模板)。启动器"手机控制"页通过
`phone_proxy_request`(Rust)与 `phoneApi.ts`(前端)与之通信,实现远程操控、
取图、视觉识别、自动化脚本(购物 / 阅读 / 游戏等 demo)。

相关脚本集中在启动器 `scripts/openclaw-phone-*.mjs`,经 `package.json` 暴露为
`phone:agent`、`phone:fleet`、`phone:vision`、`phone:video`、`phone:game` 等命令。

### 8.3 iOS Agent(`iosclaw/`)

iOS 侧 Agent,使用 XcodeGen(`project.yml`)管理工程,源码在 `iOSClaw/`,
另附 `docs/`。用于在 iOS 设备上提供与 APKClaw 类似的控制能力。

### 8.4 平台发布与发布中继(Publish Relay)

"平台发布"功能让用户用手机端发布图文 / 视频。跨设备协同由 License Server 内置的
**发布中继**承担(`PUBLISH_RELAY_*`):租约(lease)、等待(wait)、重试与退避机制
保证发布任务在中继侧可靠交接。客户端脚本见
`scripts/openclaw-publish-*.mjs`(`phone:publish`、`phone:relay` 等)。

---

## 9. 授权服务器详解(`license_server/server.py`)

独立的 Python 标准库 HTTP 服务,单文件实现,内嵌管理后台 HTML。

| 组件 | 说明 |
|------|------|
| 运行 | `ThreadingHTTPServer`,默认部署在 `/opt/openclaw-license` |
| 数据库 | SQLite(授权码、激活记录、会员等) |
| 签名 | Ed25519(私钥签发许可证,客户端公钥验证) |
| 授权码格式 | `OC-{EDITION}-XXXX-XXXX-XXXX-XXXX` |
| 默认端口 | `18791`(`LICENSE_PORT`) |
| 管理后台 | 内嵌单页(`admin_console.html`),Token 鉴权 |
| 防护 | 登录 / 注册限流(可配置次数、窗口、锁定时长)、CORS 白名单、数据库备份 |

**主要 API**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/activate` | POST | 在线激活授权码,签发许可证 |
| `/public-key` | GET | 获取 Ed25519 公钥(Base64) |
| `/health` | GET | 健康检查 |
| `/admin` | GET | 管理后台页面 |
| `/admin/api/codes` | GET/POST | 查询 / 创建授权码 |
| `/admin/api/codes/toggle` · `/delete` · `/clear` · `/hash` | POST | 启停 / 删除 / 清空 / 计算哈希 |
| 会员相关 | — | 会员注册 / 登录 / 网关凭据下发(配合 `routes_member`) |
| 发布中继 | — | 发布任务的租约 / 等待 / 交接(`PUBLISH_RELAY_*`) |

**关键环境变量**

`LICENSE_PORT` · `LICENSE_DB` · `LICENSE_PRIVATE_KEY_FILE` · `LICENSE_ADMIN_TOKEN_FILE` ·
`MEMBER_GATEWAY_BASE_URL` / `_IMAGE_` / `_VIDEO_` 及对应 `_TOKEN` / `_MODEL` ·
`OPENCLAW_PUBLISH_RELAY_TOKEN` · 各类 `*_RATE_LIMIT_*`。

> 部署与运维参考 `license_server/deploy.sh`、`openclaw-license.service`(systemd)、
> `deploy_member_update.py`。

---

## 10. 端口与外部服务速查

| 名称 | 地址 / 端口 | 说明 |
|------|-------------|------|
| OpenClaw 网关 | `127.0.0.1:18790` | Node.js 核心服务,"网页界面"入口 |
| Python Bridge | `127.0.0.1:<动态端口>` | 启动时分配,经 `BRIDGE_PORT` 回传 Rust |
| License Server | `:18791`(服务端) | 在线激活 / 会员 / 发布中继 |
| 许可证服务域名 | `https://license.heang.top` | 客户端 `LICENSE_SERVER_URL` |
| 产品官网 | `https://lumiu.heang.top/` | 落地页;源码见 `lumiu-official-site/`,亦为桌面代理 `homepage` |
| 帮助文档 | `https://heang.top/docs.html` | `HELP_URL` |
| 生图 API | OpenAI 兼容 `/v1/images/generations`、`/v1/images/edits` | 默认模型 `gpt-image-2` |
| 视频 API | DashScope 视频合成 + 任务轮询 | 模型 `happyhorse-1.0-t2v` / `-i2v` |
| Provider 预设 | Heang AI / OpenAI / Claude / DeepSeek / 智谱 / Moonshot / 自定义 | 见 `constants.py` |

---

## 11. 构建、打包与发布

### 仓库级脚本(`scripts/`)

| 脚本 | 用途 |
|------|------|
| `build-portable.ps1` | 构建 Windows 便携包(核心打包流程) |
| `ci-check.ps1` | 本地全量 CI 检查(可 `-SkipFrontend -SkipRust`) |
| `verify-release.ps1` | 校验便携 zip(结构、品牌、SHA256) |
| `verify-source-text.ps1` | 源码文本检查 |
| `verify-version-consistency.ps1` | 版本号一致性检查 |
| `smoke-bridge.ps1` | Bridge 冒烟测试 |
| `verify-admin-console.ps1` | 管理后台校验 |
| `verify-portable-smoke.ps1` | 便携包冒烟 |
| `download-webview2-runtime.ps1` | 下载 WebView2 运行时 |
| `publish-gitee-release.ps1` | 发布到 Gitee Releases |
| `clean-workspace.ps1` · `check-workspace-hygiene.ps1` | 清理 / 卫生检查 |
| `gitee-ci.sh` | Gitee 镜像 CI |

### 便携包目录结构(交付形态)

```
{交付根}/
├─ OpenClaw.exe              # Tauri 打包主程序
└─ OpenClawFiles/            # 全部载荷
   ├─ _up_/
   │  ├─ python/             # Python Bridge(bridge.py / core / services / api)
   │  └─ python-runtime/     # 随包 Python
   ├─ node/                  # 随包 Node.js
   ├─ node_modules/openclaw/ # OpenClaw 核心包
   ├─ start.js               # 启动脚本
   ├─ data/                  # 数据 / 状态(.openclaw、license、themes、generated-images)
   ├─ scripts/               # CLI 脚本
   └─ redist/                # WebView2 安装程序
```

打包脚本会:清缓存 → 检查源码文本 → 构建 Tauri → 复制 OpenClaw 离线依赖 →
**清空授权 / 安装 ID / API Key** → 安装并校验飞书 / 微信插件 → 整理为
`OpenClaw.exe + OpenClawFiles/` → 校验 zip 并生成 SHA256。

### CI/CD

- GitHub Actions 是主云端路径:`ci.yml`(push / PR 到 `master`)、`release.yml`(标签
  `v*` 或手动 dispatch)。Gitee 用于国内镜像。
- **云端产物不是完整客户便携包**。完整离线包(含 Node.js、OpenClaw、机器人插件、
  内嵌 Python)必须在 Windows 构建机或本地打包机产出。

---

## 12. 开发与运行

### 主启动器(开发模式)

```powershell
cd openclaw_new_launcher
npm ci
pip install -r python/requirements.txt   # 需要 Python 3.11+
npm run build
npm run tauri dev
```

生产构建:`npm run tauri build`(产物在 `src-tauri/target/release/bundle/`)。

### License Server

```bash
cd license_server
python server.py serve
python server.py create-code --licensee "客户名" --edition pro --count 5 --expires 2027-05-01
python server.py list-codes
python server.py public-key
```

### 桌面代理 SightFlow

```bash
cd sightflow-desktop-agent-main
npm install   # 或 pnpm install
npm run dev
npm run build
```

### macOS 迁移

参考 `openclaw_new_launcher/docs/MAC_BUILD_NOTES.md`、`MAC_MIGRATION_CHECKLIST.md`、
`RUNTIME_PATHS.md`。注意:macOS 不能复用 Windows 的 `node_modules`、
`src-tauri/target`、Windows Node 运行时或 `.exe`。

---

## 13. 安全与交付规则

禁止提交或打入交付包:

- 授权服务器私钥、后台 Token、数据库文件
- `data/license.json`、`data/install_id.txt`
- 客户 API Key
- 客户扫码后的微信 / 飞书账号缓存
- `node_modules/`、`dist/`、`src-tauri/target/`、`release/`

交付前必须确认:不存在 `data/license.json` 与 `data/install_id.txt`;
`imgapi_config.json` / `video_config.json` 为空配置;根目录只保留
`OpenClaw.exe` 和 `OpenClawFiles/`;打开后未授权、API Key 输入框为空。

---

## 14. 维护备注与已知差异

整理本文档时发现的、与旧文档 / README 的差异,建议同步修正:

1. **版本号**:实际代码 `v2.0.6`,README 仍写 `v2.0.1`。发布脚本可用
   `verify-version-consistency.ps1` 统一校验。
2. **前端框架**:`CODE_WIKI.md` 写"Vue3/React",实际为**纯 React 18**,无 Vue。
3. **视频模型**:旧文档写"通义万相 / Seedance 火山引擎",`constants.py` 实际默认模型为
   `happyhorse-1.0-t2v` / `happyhorse-1.0-i2v`,经 DashScope 异步任务接口。
4. **新增子系统**:会员 + 托管 AI 网关(`member_manager.py` / `routes_member.py` /
   `gatewayConfig.ts`)与发布中继(Publish Relay)在旧 Code Wiki 中尚未覆盖。
5. **新增功能页**:`publish`(平台发布)是注册表中的新功能,旧页面清单未列出。
6. **桌面代理双目录**:`sightflow-desktop-agent` 与 `sightflow-desktop-agent-main`
   并存,打包优先取 `-main`。

---

*本文档由对仓库源码的实际分析整理而成,可作为新成员 onboarding 与二开交付的主参考。
更细的换壳 / 打包步骤见 `docs/BRANDING_AND_PACKAGING.md` 与 `docs/BRAND_THEME.md`。*
