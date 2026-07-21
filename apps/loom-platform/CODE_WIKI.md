# AUSTART / OpenClaw 项目 Code Wiki

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体架构](#2-整体架构)
- [3. 子项目详解](#3-子项目详解)
  - [3.1 openclaw_new_launcher — 主启动器](#31-openclaw_new_launcher--主启动器)
  - [3.2 sightflow-desktop-agent-main — 桌面控制代理](#32-sightflow-desktop-agent-main--桌面控制代理)
  - [3.3 license_server — 授权服务器](#33-license_server--授权服务器)
- [4. 关键类与函数说明](#4-关键类与函数说明)
  - [4.1 Rust 后端 (Tauri)](#41-rust-后端-tauri)
  - [4.2 Python Bridge 层](#42-python-bridge-层)
  - [4.3 前端 (React + TypeScript)](#43-前端-react--typescript)
- [5. 模块间依赖关系](#5-模块间依赖关系)
- [6. 数据流与通信机制](#6-数据流与通信机制)
- [7. 授权体系](#7-授权体系)
- [8. 项目运行方式](#8-项目运行方式)
- [9. 目录结构速查](#9-目录结构速查)

---

## 1. 项目概述

AUSTART（产品名 OpenClaw / Lumi）是一个 **AI 创意控制台**，以 U 盘便携包形式分发，提供以下核心能力：

| 能力 | 说明 |
|------|------|
| AI 生图 | 通过 OpenAI 兼容 API 生成/编辑图片 |
| AI 视频 | 支持 DashScope (通义万相) 和火山引擎 Seedance 两种视频生成后端 |
| 广告分镜 | 分镜/首尾帧/九宫格广告视频制作 |
| 手机控制 | 通过 APKClaw Agent 远程操控手机 |
| 桌面控制 | 通过 SightFlow Agent 操控桌面应用（微信等） |
| 授权管理 | Ed25519 签名的在线激活 + 本地验证授权体系 |

项目采用 **Tauri 2.0 + Vue3/React + Python FastAPI** 三层架构，以 Rust 为壳、Python 为桥、TypeScript 为面。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri 桌面窗口 (WebView2)                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              React 前端 (TypeScript + Vite)              │ │
│  │  Sidebar │ Dashboard │ Image │ Video │ License │ ...    │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │ invoke / proxy_request             │
│  ┌──────────────────────┴──────────────────────────────────┐ │
│  │              Rust 后端 (src-tauri/src/lib.rs)            │ │
│  │  • start_bridge() — 启动 Python Bridge 进程              │ │
│  │  • proxy_request() — 代理 HTTP 请求到 Bridge             │ │
│  │  • verify_license() — Rust 层授权校验                    │ │
│  │  • phone_proxy_request() — 手机 Agent 代理               │ │
│  └──────────────────────┬──────────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────────┘
                          │ HTTP (127.0.0.1:18791~18950)
┌─────────────────────────┴───────────────────────────────────┐
│              Python Bridge (FastAPI / uvicorn)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Process  │ │ License  │ │  Image   │ │    Video      │  │
│  │ Service  │ │ Manager  │ │  Client  │ │    Client     │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Desktop  │ │  Theme   │ │ Updater  │ │    Skill      │  │
│  │  Agent   │ │ Manager  │ │          │ │    Service    │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   OpenClaw 核心      SightFlow       License
   (Node.js:18790)   Desktop Agent   Server
                      (Electron)     (HTTPS)
```

**关键设计决策：**

- **Rust 层**负责窗口管理、Bridge 进程生命周期、授权前置校验
- **Python Bridge**作为中间层，提供所有业务 API（进程管理、生图、视频、授权等）
- **前端**通过 Tauri `invoke` 调用 Rust 命令，Rust 再代理到 Python Bridge 的 HTTP API
- Bridge 启动时输出 `BRIDGE_PORT=xxxxx` 和 `BRIDGE_TOKEN=xxx`，Rust 读取后用于后续请求鉴权

---

## 3. 子项目详解

### 3.1 openclaw_new_launcher — 主启动器

主启动器是整个项目的核心，包含三个技术栈的代码：

#### 3.1.1 Rust 后端 (`src-tauri/`)

| 文件 | 职责 |
|------|------|
| `src/lib.rs` | Tauri 命令注册、Bridge 启动/代理、诊断报告、日志导出 |
| `src/license.rs` | Ed25519 授权验证（签名校验、installId/deviceId/过期/功能检查） |
| `src/main.rs` | 入口，调用 `lib::run()` |
| `Cargo.toml` | Rust 依赖：tauri、reqwest、ed25519-dalek、sha2、chrono、base64 等 |
| `tauri.conf.json` | Tauri 窗口配置、权限声明、资源打包规则 |

**核心 Tauri 命令：**

| 命令 | 功能 |
|------|------|
| `start_bridge` | 查找并启动 Python Bridge 进程，读取端口和 Token |
| `proxy_request` | 代理前端 HTTP 请求到 Bridge，受保护路径需先通过授权校验 |
| `phone_proxy_request` | 代理手机 Agent 的 HTTP 请求 |
| `get_bridge_port` | 返回当前 Bridge 端口 |
| `get_portable_base_path` | 返回便携包根目录 |
| `verify_license` | Rust 层授权状态检查 |
| `bridge_startup_report` | Bridge 启动诊断报告 |
| `export_log` | 导出日志到文件 |
| `open_path` | 在系统文件管理器中打开路径 |

**受保护路径（需授权）：**

- `/api/process/start` → 需要 `openclaw` 功能
- `/api/image/generate` → 需要 `image` 功能
- `/api/video/generate` → 需要 `video` 功能

#### 3.1.2 Python Bridge (`python/`)

Bridge 是一个 FastAPI 应用，作为 Tauri 和业务逻辑之间的中间层。

**核心模块：**

| 模块 | 路径 | 职责 |
|------|------|------|
| `bridge.py` | `python/bridge.py` | 入口，服务发现、依赖注入、FastAPI 启动 |
| `core/paths.py` | `python/core/paths.py` | 路径发现（便携包/开发模式/打包模式） |
| `core/constants.py` | `python/core/constants.py` | 全局常量（端口、URL、模型名、主题色） |
| `core/storage.py` | `python/core/storage.py` | JSON 文件读写工具 |
| `core/license_manager.py` | `python/core/license_manager.py` | 授权管理（在线激活、本地验证、设备绑定） |
| `core/theme_manager.py` | `python/core/theme_manager.py` | 主题管理（三级回退策略） |
| `services/process.py` | `python/services/process.py` | OpenClaw 核心进程管理（启动/停止/诊断/修复） |
| `services/desktop_agent.py` | `python/services/desktop_agent.py` | SightFlow 桌面代理管理 |
| `services/image_api.py` | `python/services/image_api.py` | AI 生图 API 客户端 |
| `services/video_api.py` | `python/services/video_api.py` | AI 视频 API 客户端（DashScope + Seedance） |
| `services/updater.py` | `python/services/updater.py` | OpenClaw 包更新器 |
| `services/skills.py` | `python/services/skills.py` | Skill 包管理（安装/卸载/启用/禁用） |

**API 路由模块：**

| 路由模块 | 路径 | 端点前缀 |
|----------|------|----------|
| `routes_process` | `api/routes_process.py` | `/api/process/*` |
| `routes_license` | `api/routes_license.py` | `/api/license/*` |
| `routes_media` | `api/routes_media.py` | `/api/image/*`, `/api/video/*` |
| `routes_desktop_agent` | `api/routes_desktop_agent.py` | `/api/desktop-agent/*` |
| `routes_diagnostics` | `api/routes_diagnostics.py` | `/api/diagnostics/*` |
| `routes_config` | `api/routes_config.py` | `/api/config/*` |
| `routes_theme` | `api/routes_theme.py` | `/api/theme/*` |
| `routes_log` | `api/routes_log.py` | `/api/log/*` |
| `routes_update` | `api/routes_update.py` | `/api/update/*` |
| `routes_skills` | `api/routes_skills.py` | `/api/skills/*` |
| `routes_system` | `api/routes_system.py` | `/api/system/*` |

#### 3.1.3 前端 (`src/`)

基于 React 18 + TypeScript + Vite 的单页应用。

**目录结构：**

| 目录 | 职责 |
|------|------|
| `components/` | 页面组件（Dashboard、Image、Video、License 等） |
| `components/sidebar/` | 侧边栏导航 |
| `components/common/` | 通用组件（Toast 等） |
| `components/dialogs/` | 对话框（API 配置、飞书/微信机器人） |
| `components/window/` | 窗口标题栏 |
| `features/` | 功能注册表（导航项定义、页面映射） |
| `hooks/` | 自定义 Hook（useTheme） |
| `providers/` | Context Provider（ThemeProvider） |
| `services/` | API 服务层（api.ts、phoneApi.ts） |
| `stores/` | Zustand 状态管理（appStore、logStore） |
| `styles/` | 全局样式 |
| `theme/` | 主题默认配置 |
| `types/` | TypeScript 类型定义 |

**页面组件映射：**

| key | 组件 | 说明 |
|-----|------|------|
| `dashboard` | `DashboardPage` | 控制台总览 |
| `terminal` | `TerminalPage` | 服务日志 |
| `license` | `LicensePage` | 授权码激活 |
| `image` | `ImagePage` | AI 生图 |
| `video` | `VideoPage` | AI 视频 |
| `storyboard` | `StoryboardPage` | 广告分镜 |
| `diagnostics` | `DiagnosticsPage` | 环境诊断 |
| `skills` | `SkillsPage` | Skill 管理 |
| `phone` | `PhoneControlPage` | 手机控制 |
| `desktop` | `DesktopAgentPage` | 桌面控制 |

### 3.2 sightflow-desktop-agent-main — 桌面控制代理

SightFlow 是一个基于 Electron 的桌面 RPA 代理，提供以下能力：

| 模块 | 路径 | 职责 |
|------|------|------|
| `core/rpa/` | `src/core/rpa/` | RPA 核心操作（截图、点击、输入、窗口管理） |
| `core/engine.ts` | `src/core/engine.ts` | 任务执行引擎 |
| `core/http-api-server.ts` | `src/core/http-api-server.ts` | HTTP API 服务 |
| `core/openclaw-adapter.ts` | `src/core/openclaw-adapter.ts` | OpenClaw 集成适配器 |
| `core/openclaw-tools.ts` | `src/core/openclaw-tools.ts` | OpenClaw 工具定义 |
| `core/ai-client.ts` | `src/core/ai-client.ts` | AI 客户端 |
| `core/device.ts` | `src/core/device.ts` | 设备抽象层 |
| `core/rpa-device.ts` | `src/core/rpa-device.ts` | RPA 设备实现 |
| `main/index.ts` | `src/main/index.ts` | Electron 主进程 |
| `main/permission.ts` | `src/main/permission.ts` | 权限管理 |

**HTTP API 端点（由 Bridge 代理）：**

| 端点 | 功能 |
|------|------|
| `/health` | 健康检查 |
| `/screenshot` | 屏幕截图 |
| `/click` | 鼠标点击 |
| `/type` | 键盘输入 |
| `/wechat/send` | 微信发送消息 |
| `/wechat/unread` | 微信未读消息检测 |
| `/wechat/contact_unread` | 联系人未读检测 |
| `/measure_layout` | 布局测量 |
| `/wechat/chat_diff` | 聊天差异检测 |
| `/engine/status` | 引擎状态 |

### 3.3 license_server — 授权服务器

独立的 Python HTTP 服务器，提供授权码管理和在线激活功能。

| 组件 | 说明 |
|------|------|
| 数据库 | SQLite（codes 表 + activations 表） |
| 签名算法 | Ed25519（私钥签名，公钥验证） |
| 授权码格式 | `OC-{EDITION}-XXXX-XXXX-XXXX-XXXX` |
| 管理后台 | 内嵌 HTML 单页应用（`/admin`） |
| 默认端口 | 18791 |

**API 端点：**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/activate` | POST | 在线激活授权码 |
| `/public-key` | GET | 获取公钥（Base64） |
| `/health` | GET | 健康检查 |
| `/admin` | GET | 管理后台页面 |
| `/admin/api/codes` | GET/POST | 查询/创建授权码 |
| `/admin/api/codes/toggle` | POST | 启用/停用授权码 |
| `/admin/api/codes/clear` | POST | 清空所有授权码 |
| `/admin/api/codes/hash` | POST | 计算授权码哈希 |
| `/admin/api/codes/delete` | POST | 删除授权码 |

---

## 4. 关键类与函数说明

### 4.1 Rust 后端 (Tauri)

#### `license.rs` — 授权验证模块

```rust
pub fn check_license(base_path: &Path) -> LicenseStatus
```
检查本地 `data/license.json` 的有效性，返回 `LicenseStatus`（authorized、licensee、edition、expires、device_bound）。

```rust
pub fn ensure_authorized(base_path: &Path, feature: Option<&str>) -> Result<(), String>
```
验证授权并检查特定功能权限，用于受保护 API 的前置校验。

**验证链：** 签名校验 → installId 匹配 → deviceId 匹配 → 过期检查 → 功能检查

#### `lib.rs` — 主逻辑模块

```rust
fn spawn_bridge(py_path: &Path) -> Result<String, String>
```
启动 Python Bridge 子进程，读取 stdout 中的 `BRIDGE_PORT=` 和 `BRIDGE_TOKEN=` 行，后台线程持续读取 stderr。

```rust
async fn proxy_request(app, path, method, body) -> Result<String, String>
```
代理前端请求到 Bridge HTTP 服务。受保护路径先调用 `license::ensure_authorized` 校验。

```rust
fn portable_base_dir() -> Result<PathBuf, String>
```
发现便携包根目录：优先查找 `OpenClawFiles/` 子目录，回退到 EXE 所在目录。

### 4.2 Python Bridge 层

#### `AppPaths` (`core/paths.py`)

```python
@dataclass(frozen=True)
class AppPaths:
    base_path: str
```

路径发现核心类，从 `python/core/paths.py` 向上推导项目根目录，支持开发模式、Tauri 打包模式、便携包模式。

**关键属性：**

| 属性 | 路径 | 说明 |
|------|------|------|
| `node_dir` | `{base}/node` 或 `{base}/SystemData/.core/node` | Node.js 运行时目录 |
| `node_exe` | `{node_dir}/node.exe` | Node.js 可执行文件 |
| `data_dir` | `{base}/data` | 数据目录 |
| `state_dir` | `{base}/data/.openclaw` | 状态目录 |
| `openclaw_config` | `{state_dir}/openclaw.json` | OpenClaw 配置文件 |
| `license_file` | `{data_dir}/license.json` | 授权文件 |
| `install_id_file` | `{data_dir}/install_id.txt` | 安装 ID |
| `generated_images_dir` | `{data_dir}/generated-images` | 生图输出目录 |
| `skills_dir` | `{state_dir}/skills` | Skill 安装目录 |
| `themes_dir` | `{data_dir}/themes` | 主题目录 |

#### `LicenseManager` (`core/license_manager.py`)

```python
class LicenseManager:
    def __init__(self, paths: AppPaths)
```

授权管理器，负责在线激活和本地验证。

| 方法 | 说明 |
|------|------|
| `get_install_id()` | 获取/生成安装 ID（UUID） |
| `device_id()` | 生成设备 ID（基于磁盘卷序列号 SHA256） |
| `current_license()` | 读取并验证本地授权文件 |
| `is_authorized(feature)` | 检查是否已授权（可指定功能） |
| `verify(license_data)` | 完整验证链（签名→installId→deviceId→过期） |
| `activate(code)` | 在线激活：向 License Server 发送授权码，获取签名许可证 |
| `diagnose()` | 诊断授权状态，返回详细错误信息 |

#### `OpenClawProcessService` (`services/process.py`)

```python
class OpenClawProcessService:
    def __init__(self, paths: AppPaths, append_log: LogCall, ui_call: UiCall)
```

OpenClaw 核心进程管理器，负责启动/停止 Node.js 网关进程。

| 方法 | 说明 |
|------|------|
| `start(on_exit)` | 同步启动核心服务（含锁） |
| `start_background(on_exit)` | 后台线程启动 |
| `stop()` | 停止服务（taskkill /F /T） |
| `status()` | 获取进程状态（running、pid、portReady 等） |
| `diagnose_environment()` | 全面环境诊断（12+ 检查项） |
| `repair_environment()` | 自动修复（清理残留进程、重建配置、释放端口） |

**启动流程：** 存储健康检查 → 清理残留进程 → 重建 openclaw.json → 初始化 workspace → 写入 runtime-context.json → 启动 Node.js → 等待端口就绪

#### `DesktopAgentService` (`services/desktop_agent.py`)

```python
class DesktopAgentService:
    def __init__(self, paths: AppPaths, append_log: LogCall)
```

SightFlow 桌面代理管理器。

| 方法 | 说明 |
|------|------|
| `start()` | 启动 SightFlow 进程 |
| `stop()` | 停止 SightFlow 进程 |
| `status()` | 获取代理状态 |
| `health(config, quiet)` | 健康检查 |
| `proxy(path, body, method, config)` | 代理请求到 SightFlow HTTP API（含策略执行） |
| `resolve_agent_dir(config)` | 发现代理目录 |
| `resolve_command(agent_dir)` | 发现启动命令（Electron/EXE/Node） |

**安全策略：** 通过 `_enforce_policy` 方法执行操作策略检查（截图/点击/输入/微信发送的权限和确认要求）。

#### `DashScopeVideoClient` (`services/video_api.py`)

```python
class DashScopeVideoClient:
    def generate(self, dash_key, prompt, mode, resolution, duration, ratio, ...) -> bytes
```

视频生成客户端，支持两种后端：

| 后端 | provider_id | 说明 |
|------|-------------|------|
| DashScope (通义万相) | `dashscope` | 阿里云 DashScope 异步任务 API |
| Seedance (火山引擎) | `seedance` / `custom` | 火山引擎兼容 API |

**生成流程：** 构建请求体 → 提交异步任务 → 轮询任务状态 → 下载视频

#### `ImageApiClient` (`services/image_api.py`)

```python
class ImageApiClient:
    def generate(self, base_url, api_key, prompt, size, *, edit_image_path=None) -> bytes
    def generate_many(self, base_url, api_key, prompt, size, *, count=1, edit_image_path=None) -> list[bytes]
```

图片生成客户端，支持 OpenAI 兼容的 `/v1/images/generations` 和 `/v1/images/edits` 端点。

#### `SkillService` (`services/skills.py`)

```python
class SkillService:
    def __init__(self, paths: AppPaths)
```

Skill 包管理器，支持三种来源：

| 来源 key | 说明 | 可写 |
|----------|------|------|
| `uploaded` | 上传安装 | ✅ |
| `openclaw-extensions` | OpenClaw 扩展目录 | ❌ |
| `node-modules` | Node 包目录 | ❌ |

**元数据识别顺序：** `skill.json` → `.codex-plugin/plugin.json` → `package.json`（需含 openclaw 关键字） → `SKILL.md`

#### `ThemeManager` (`core/theme_manager.py`)

```python
class ThemeManager:
    def __init__(self, paths: AppPaths)
```

主题管理器，三级回退策略：

1. `data/theme.json` — 激活响应缓存（最高优先级）
2. `data/themes/{merchantId}/theme.json` — 本地主题包
3. `data/brand_profile.json` — 打包品牌配置
4. `DEFAULT_THEME` — 内置默认主题

### 4.3 前端 (React + TypeScript)

#### `useAppStore` (`stores/appStore.ts`)

Zustand 全局状态管理，核心状态：

| 状态 | 类型 | 说明 |
|------|------|------|
| `currentPage` | `string` | 当前页面 key |
| `serviceRunning` | `boolean` | 核心服务是否运行 |
| `serviceStatus` | `'idle' \| 'starting' \| 'running' \| 'stopping' \| 'stopped'` | 服务状态 |
| `isAuthorized` | `boolean` | 是否已授权 |
| `licenseInfo` | `License \| null` | 授权信息 |
| `themeConfig` | `ThemeConfig \| null` | 主题配置 |
| `navItems` | `NavItem[]` | 导航项列表 |

#### `api.ts` — API 服务层

所有 API 调用通过 `proxyRequest` → Tauri `invoke('proxy_request')` → Rust → Python Bridge 的链路。

**核心 API 命名空间：**

| 命名空间 | 方法 | 说明 |
|----------|------|------|
| `processApi` | `start()`, `stop()`, `status()` | 进程管理 |
| `logApi` | `get(offset)`, `clear()` | 日志管理 |
| `licenseApi` | `current()`, `activate(code)`, `authorized(feature)` | 授权管理 |
| `imageApi` | `generate(params)` | AI 生图 |
| `videoApi` | `generate(params)` | AI 视频 |
| `updateApi` | `check()`, `do()` | 更新管理 |
| `configApi` | `read(path)`, `write(path, data)` | 配置读写 |
| `themeApi` | `current()` | 主题获取 |
| `diagnosticsApi` | `run()`, `repair()`, `export()` | 诊断修复 |
| `desktopAgentApi` | `status()`, `start()`, `stop()`, `screenshot()`, `click()`, `type()`, `wechatSend()`, `wechatUnread()` | 桌面代理 |
| `skillsApi` | `list()`, `installZip()`, `setEnabled()`, `uninstall()`, `readme()` | Skill 管理 |

#### `registry.ts` — 功能注册表

定义所有导航功能项，包含 key、label、icon、group、是否需要授权、动作类型（page/dialog/external/command）。

---

## 5. 模块间依赖关系

```
前端 (React)
  ├── @tauri-apps/api/core (invoke)
  ├── @tauri-apps/plugin-shell (open)
  ├── zustand (状态管理)
  └── → services/api.ts → Tauri invoke → Rust proxy_request → Python Bridge

Rust 后端
  ├── tauri 2.0
  ├── reqwest (HTTP 客户端)
  ├── ed25519-dalek + sha2 (授权验证)
  ├── chrono (日期处理)
  └── → 启动 Python Bridge 子进程 → 代理 HTTP 请求

Python Bridge
  ├── fastapi + uvicorn (HTTP 服务)
  ├── cryptography (Ed25519 授权验证)
  ├── Pillow (图片处理)
  └── → OpenClaw Node.js 进程 (子进程管理)
      → SightFlow Electron 进程 (子进程管理)
      → License Server (HTTP 请求)
      → DashScope / Seedance API (HTTP 请求)
      → OpenAI 兼容 API (HTTP 请求)
```

**Python 内部依赖图：**

```
bridge.py
  ├── core/paths.py (AppPaths)
  ├── core/storage.py (read_json, write_json)
  ├── core/constants.py (APP_PORT, URLs, models)
  ├── core/license_manager.py (LicenseManager)
  │     ├── core/paths.py
  │     ├── core/storage.py
  │     ├── core/constants.py (LICENSE_SERVER_URL)
  │     └── cryptography
  ├── core/theme_manager.py (ThemeManager)
  │     ├── core/paths.py
  │     └── core/storage.py
  ├── services/process.py (OpenClawProcessService)
  │     └── core/paths.py, core/constants.py
  ├── services/desktop_agent.py (DesktopAgentService)
  │     └── core/paths.py
  ├── services/image_api.py (ImageApiClient)
  │     └── core/constants.py (IMAGE_MODEL)
  ├── services/video_api.py (DashScopeVideoClient)
  │     └── core/constants.py (VIDEO_MODEL_*)
  ├── services/updater.py (OpenClawUpdater)
  │     └── core/paths.py
  ├── services/skills.py (SkillService)
  │     ├── core/paths.py
  │     └── core/storage.py
  └── api/fastapi_routes.py
        └── api/routes_*.py (各路由模块)
```

---

## 6. 数据流与通信机制

### 6.1 前端 → 后端通信

```
React 组件
  → api.ts (api<T>(path, method, body))
    → ensureBridgeStarted() (确保 Bridge 已启动)
      → invoke('start_bridge') (Rust 启动 Bridge)
    → invoke('proxy_request', { path, method, body })
      → Rust: protected_feature() 检查 (受保护路径需授权)
      → Rust: reqwest → http://127.0.0.1:{port}/{path}
        → Python FastAPI 路由处理
          → 返回 JSON
        ← Rust 返回响应文本
      ← api.ts 解析 JSON
    ← React 组件获取数据
```

### 6.2 Bridge 启动流程

```
Tauri App 启动
  → setup() 中异步调用 start_bridge()
    → 查找 bridge.py (多个候选路径)
    → 查找 Python 可执行文件 (随包 Python / 系统 Python)
    → spawn_bridge(py_path)
      → Command::new(python_exe).arg(bridge.py)
      → 读取 stdout:
        BRIDGE_PORT=18791  → 存入 AtomicU16
        BRIDGE_TOKEN=xxx   → 存入 Mutex<Option<String>>
      → 后台线程读取 stderr
```

### 6.3 核心服务启动流程

```
前端点击"启动"
  → processApi.start()
    → Python: OpenClawProcessService.start()
      → 存储健康检查 (磁盘读写测试)
      → 清理残留进程 (ClawPanel、Gateway、端口占用)
      → 重建 openclaw.json (如损坏)
      → 初始化 workspace (AGENTS.md, SOUL.md 等)
      → 写入 runtime-context.json
      → subprocess.Popen([node_exe, start.js])
      → 等待端口 18790 就绪 (最长 420s)
      → 写入启动快照
```

---

## 7. 授权体系

### 7.1 整体流程

```
1. 管理员在 License Server 生成授权码 (OC-PRO-XXXX-XXXX-XXXX-XXXX)
2. 用户在启动器输入授权码
3. 启动器向 License Server /activate 发送 { code, installId, deviceId }
4. Server 验证授权码有效性，生成签名许可证
5. 许可证写入 data/license.json
6. 后续每次使用受保护功能时，Rust/Python 双层验证许可证
```

### 7.2 许可证验证链

```
1. 读取 data/license.json
2. 提取 signature 字段
3. 用 Ed25519 公钥验证签名 (canonical JSON)
4. 验证 installId 匹配 (data/install_id.txt)
5. 验证 deviceId 匹配 (磁盘卷序列号 SHA256，支持盘符变更)
6. 验证未过期 (expires >= today)
7. 验证功能权限 (features 数组包含所需功能)
```

### 7.3 设备绑定

- Windows: 使用 `GetVolumeInformationW` 获取磁盘卷序列号
- 绑定到卷序列号而非盘符（支持 U 盘拔插后盘符变更）
- 兼容旧版盘符绑定（遍历 A-Z 所有盘符生成候选 deviceId）

---

## 8. 项目运行方式

### 8.1 开发模式

```bash
# 1. 安装前端依赖
cd openclaw_new_launcher
npm install

# 2. 安装 Python 依赖
pip install -r python/requirements.txt

# 3. 安装 Rust 工具链 (需 rustup)
# 参见 https://rustup.rs

# 4. 开发模式启动 (Tauri dev)
cd openclaw_new_launcher
npm run tauri dev
```

### 8.2 生产构建

```bash
cd openclaw_new_launcher
npm run tauri build
```

输出安装包到 `src-tauri/target/release/bundle/`。

### 8.3 License Server

```bash
cd license_server

# 启动服务
python server.py serve

# 生成授权码
python server.py create-code --licensee "客户名" --edition pro --count 5 --expires 2027-05-01

# 查看授权码列表
python server.py list-codes

# 获取公钥
python server.py public-key
```

### 8.4 SightFlow 桌面代理

```bash
cd sightflow-desktop-agent-main

# 安装依赖
pnpm install

# 开发模式
pnpm dev

# 构建
pnpm build
```

### 8.5 便携包部署

便携包目录结构：

```
{USB_ROOT}/
├── OpenClaw.exe              # Tauri 打包的主程序
├── OpenClawFiles/            # 便携包载荷目录
│   └── _up_/
│       ├── python/            # Python Bridge
│       │   ├── bridge.py
│       │   ├── core/
│       │   ├── services/
│       │   └── api/
│       └── python-runtime/    # 随包 Python 运行时
├── node/                      # 随包 Node.js
├── node_modules/openclaw/     # OpenClaw 核心包
├── start.js                   # 启动脚本
├── data/                      # 数据目录
│   ├── .openclaw/             # 状态目录
│   │   ├── openclaw.json
│   │   ├── workspace/
│   │   ├── launcher/
│   │   ├── extensions/
│   │   └── skills/
│   ├── license.json
│   ├── install_id.txt
│   ├── generated-images/
│   └── themes/
├── scripts/                   # CLI 脚本
└── redist/                    # WebView2 安装程序
```

---

## 9. 目录结构速查

```
AUSTART/
├── openclaw_new_launcher/          # 主启动器项目
│   ├── src-tauri/                  # Rust/Tauri 后端
│   │   ├── src/
│   │   │   ├── lib.rs              # 主逻辑（Bridge 启动、请求代理、诊断）
│   │   │   ├── main.rs             # 入口
│   │   │   └── license.rs          # 授权验证（Ed25519）
│   │   ├── Cargo.toml              # Rust 依赖
│   │   └── tauri.conf.json         # Tauri 配置
│   ├── src/                        # React 前端
│   │   ├── App.tsx                 # 应用根组件
│   │   ├── main.tsx                # 入口
│   │   ├── components/             # 页面组件
│   │   │   ├── dashboard/          # 控制台
│   │   │   ├── terminal/           # 服务日志
│   │   │   ├── license/            # 授权码
│   │   │   ├── image/              # AI 生图
│   │   │   ├── video/              # AI 视频
│   │   │   ├── storyboard/         # 广告分镜
│   │   │   ├── diagnostics/        # 环境诊断
│   │   │   ├── skills/             # Skill 管理
│   │   │   ├── phone/              # 手机控制
│   │   │   ├── desktop/            # 桌面控制
│   │   │   ├── sidebar/            # 侧边栏
│   │   │   ├── dialogs/            # 对话框
│   │   │   ├── common/             # 通用组件
│   │   │   └── window/             # 窗口标题栏
│   │   ├── features/               # 功能注册
│   │   │   ├── registry.ts         # 功能定义表
│   │   │   └── pages.tsx           # 页面映射
│   │   ├── services/               # API 服务
│   │   │   ├── api.ts              # 主 API 层
│   │   │   └── phoneApi.ts         # 手机 Agent API
│   │   ├── stores/                 # 状态管理
│   │   │   ├── appStore.ts         # 应用状态
│   │   │   └── logStore.ts         # 日志状态
│   │   ├── hooks/                  # 自定义 Hook
│   │   ├── providers/              # Context Provider
│   │   ├── theme/                  # 主题配置
│   │   ├── types/                  # 类型定义
│   │   └── styles/                 # 样式
│   ├── python/                     # Python Bridge
│   │   ├── bridge.py               # Bridge 入口
│   │   ├── core/                   # 核心模块
│   │   │   ├── paths.py            # 路径发现
│   │   │   ├── constants.py        # 全局常量
│   │   │   ├── storage.py          # JSON 存储
│   │   │   ├── license_manager.py  # 授权管理
│   │   │   └── theme_manager.py    # 主题管理
│   │   ├── services/               # 业务服务
│   │   │   ├── process.py          # 进程管理
│   │   │   ├── desktop_agent.py    # 桌面代理
│   │   │   ├── image_api.py        # 生图客户端
│   │   │   ├── video_api.py        # 视频客户端
│   │   │   ├── updater.py          # 更新器
│   │   │   └── skills.py           # Skill 管理
│   │   ├── api/                    # FastAPI 路由
│   │   │   ├── fastapi_routes.py   # 路由注册
│   │   │   ├── routes_process.py
│   │   │   ├── routes_license.py
│   │   │   ├── routes_media.py
│   │   │   ├── routes_desktop_agent.py
│   │   │   ├── routes_diagnostics.py
│   │   │   ├── routes_config.py
│   │   │   ├── routes_theme.py
│   │   │   ├── routes_log.py
│   │   │   ├── routes_update.py
│   │   │   ├── routes_skills.py
│   │   │   └── routes_system.py
│   │   └── requirements.txt        # Python 依赖
│   └── package.json                # 前端依赖
├── sightflow-desktop-agent-main/   # 桌面控制代理
│   ├── src/
│   │   ├── core/                   # 核心逻辑
│   │   │   ├── rpa/                # RPA 操作
│   │   │   ├── engine.ts           # 任务引擎
│   │   │   ├── http-api-server.ts  # HTTP API
│   │   │   ├── openclaw-adapter.ts # OpenClaw 适配
│   │   │   └── openclaw-tools.ts   # 工具定义
│   │   ├── main/                   # Electron 主进程
│   │   ├── preload/                # 预加载
│   │   └── renderer/               # 渲染进程
│   └── package.json
└── license_server/                 # 授权服务器
    └── server.py                   # 服务器（含管理后台 HTML）
```
