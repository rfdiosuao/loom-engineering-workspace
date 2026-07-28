<div align="center">

# 🤖 Lumi APKClaw / Agent Phone

**AI-Powered Android Automation via HTTP API**

让 Agent 更自然地操控你的 Android 设备 📱

[![GitHub release](https://img.shields.io/github/v/release/rfdiosuao/lumiapkclaw?include_prereleases)](https://github.com/rfdiosuao/lumiapkclaw/releases)
[![GitHub Downloads](https://img.shields.io/github/downloads/rfdiosuao/lumiapkclaw/total)](https://github.com/rfdiosuao/lumiapkclaw/releases)
[![License](https://img.shields.io/github/license/rfdiosuao/lumiapkclaw)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Android%209%2B-green)]()
[![Hermes](https://img.shields.io/badge/Hermes-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Version](https://img.shields.io/badge/Version-v6.31--stability-orange)]()

<p align="center">
  <a href="#quick-start">快速开始</a> •
  <a href="#http-api">HTTP API</a> •
  <a href="#workflow-template-api">流程固化</a> •
  <a href="#hermes-integration">Hermes 集成</a> •
  <a href="CHANGELOG.md">更新日志</a> •
  <a href="#examples">使用示例</a>
</p>

</div>

---

## 🆕 V6 版本更新

| 版本 | 变更 |
|------|------|
| **v6.11** | 🖼️ **PC → 手机相册图片导入** - 新增 `/api/media/import_image`，电脑端可上传 PNG/JPEG/WebP 到手机 `Pictures/Lumi` |
| **v6.10** | 🧩 **Lumi 集成版** - 适配 Lumi 启动器联动、可配置悬浮球尺寸、唤醒与状态接口、中文任务输出修复 |
| **v6.1** | 🏷️ **品牌统一** - 应用、Web 配置页、文档统一为 Agent Phone |
| **v6.1** | 🛠️ **模板参数抽取修复** - 联系人、消息、搜索词自动占位，缺参自动回退 Agent |
| **v6.1** | 🔧 **旧模板兼容** - 自动兼容“点击/输入文本”等展示名工具步骤 |
| **v6** | 🔄 **流程固化系统** - 成功流程自动保存为模板，下次直接执行 |
| **v6** | 🗑️ 移除记忆系统 - 简化架构，避免任务干扰 |
| **v6** | 🔧 修复中文关键词匹配问题 |
| **v5** | 📡 HTTP API 完整支持 Agent 远程调用 |
| **v5** | 🎨 悬浮窗状态同步 - 任务执行实时显示 |

---

## ✨ 核心能力

| 特性 | 描述 |
|------|------|
| 🧠 **智能 Agent** | 发送自然语言指令，Agent 自动规划并执行任务 |
| 🔄 **流程固化** | 成功的流程自动保存为模板，下次直接执行，节省 Token |
| 🔌 **HTTP API** | RESTful 接口，支持远程调用和第三方集成 |
| 🤝 **Agent 集成** | 与 Hermes Agent CLI 等外部 Agent 工具无缝配合，AI 控制手机 |
| 🔐 **安全配对** | 短期配对码建立连接，长期凭据由 LOOM 与手机自动保管 |
| 📸 **截图 & UI分析** | 实时截图、UI树解析，Agent 理解屏幕内容 |
| 🎯 **精准操作** | 点击、滑动、输入、长按等手势操作 |
| 🖼️ **图片导入相册** | PC / Lumi 启动器可通过 HTTP API 上传图片，手机端保存到相册并触发图库刷新 |
| 📱 **多通道消息** | 钉钉/飞书/QQ/Discord/Telegram/微信 |

---

## 🎯 适用场景

```
✅ "打开微信给老王发消息说今天加班"          → Agent 自动打开微信 → 搜索联系人 → 发送消息
✅ "淘宝搜索蓝牙耳机，看第一个商品详情"       → Agent 打开淘宝 → 搜索 → 点击商品
✅ "打开支付宝充值话费100块"                 → Agent 打开支付宝 → 进入充值 → 输入金额
✅ "帮我看看美团外卖订单状态"                 → Agent 打开美团 → 查看订单
✅ "抖音刷几个视频看看"                      → Agent 打开抖音 → 自动滑动观看
✅ "设置里把亮度调低一点"                    → Agent 打开设置 → 调整亮度
```

**你只需要描述要做什么，Agent 会自动完成！**

---

## 🚀 Quick Start

### Step 1: 安装 APK

从 [Releases](https://github.com/rfdiosuao/lumiapkclaw/releases) 下载最新 APK，安装到 Android 设备（Android 9+）。

### Step 2: 开启权限

在首页开启所有必需权限：

| 权限 | 用途 |
|------|------|
| 🔴 Accessibility Service | **核心权限** - Agent 操作设备的必要条件 |
| 🔵 Notification | 保持后台运行 |
| 🟢 System Window | 显示悬浮面板 |
| 🟡 Battery Whitelist | 防止系统杀进程 |
| 🟣 File Access | 读写文件 |

### Step 3: 配置 LLM

进入 Settings → LLM Config：

```
API Key:    sk-xxxxx（你的 OpenAI/Anthropic/通义千问 API Key）
Base URL:   https://api.openai.com/v1（或其他服务商）
Model Name: gpt-4o（或其他模型）
```

### Step 4: 与 LOOM 配对

1. 手机进入 Settings → 与 LOOM 配对。
2. USB 连接时，在电脑 LOOM 的“手机连接”页输入手机显示的 6 位配对码。
3. 局域网连接时，在 LOOM 扫码或粘贴完整配对信息。

配对信息短期有效且只能使用一次。长期连接凭据由 LOOM 与手机自动生成并安全保存，用户无需查看、复制或维护。

### Step 5: 检查连接

回到 LOOM 的“手机连接”页等待自动检测。已配对设备会优先恢复 USB 转发或上次验证过的局域网地址；地址变化、USB 未授权和凭据失效会显示不同的中文修复提示。

---

## 📡 HTTP API（内部开发协议）

普通用户和外部 Agent 不需要配置本节内容，应通过 LOOM 配对并调用 LOOM CLI/MCP。以下端点只用于协议维护、自动化测试和 LOOM 内部传输；认证凭据由配对流程托管，不是用户配置。

内部接口认证由 LOOM 配对流程自动完成。普通用户不应复制请求头、查看长期凭据或让外部 Agent 直连手机端口。

### 🖼️ Media API

这个能力用于“电脑端生成图片 → 直接出现在手机相册”。适合 Lumi 启动器、Codex、ComfyUI、网页生图工具等在 PC 上生成图片后，立即把结果推送给 APKClaw 手机端。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/media/import_image` | POST | 上传 PNG/JPEG/WebP 图片并保存到手机相册 |

在 LOOM“创作”或“本地素材库”中选择素材和目标设备即可传输；Agent 应调用 LOOM CLI/MCP 的素材传输能力。LOOM 会解析已配对设备、处理认证、重试和逐设备结果。

响应示例：

```json
{
  "success": true,
  "data": {
    "album": "Lumi",
    "filename": "lumi-output.png",
    "mimeType": "image/png",
    "uri": "content://media/external/images/media/12345",
    "relativePath": "Pictures/Lumi/lumi-output.png",
    "path": "",
    "sizeBytes": 1234567,
    "width": 1024,
    "height": 1024
  }
}
```

实现说明：手机端 HTTP Server 接收 LOOM 内部传输请求，校验图片类型与大小后，通过 Android `MediaStore` 写入 `Pictures/Lumi`，再触发媒体库刷新。Android 10+ 使用分区存储的 `MediaStore` 流程，Android 9 兼容传统外部存储写入。内部认证凭据由配对流程托管，单文件最大 32 MB。

### 🧠 Agent API（推荐）

**发送自然语言任务，Agent 智能执行：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agent/execute_task` | POST | **执行任务（最长等待 120 秒）** |
| `/api/agent/status` | GET | 检查 Agent 状态 |
| `/api/agent/cancel_task` | POST | 取消正在执行的任务 |

#### 执行任务

在 LOOM 智能体或矩阵工作台中选择设备并输入自然语言任务。外部 Agent 通过 LOOM CLI/MCP 下发，不能绕过 LOOM 直接调用手机端口。

**响应（任务完成后返回）：**
```json
{
  "success": true,
  "data": {
    "success": true,
    "answer": "消息已发送成功",
    "rounds": 5,
    "tokens": 1200
  }
}
```

#### 检查状态

LOOM 手机连接页、矩阵工作台和 CLI/MCP 会返回同一份设备状态，并区分在线、锁屏、未授权、地址变化和执行中等状态。

### 🔄 Workflow Template API（流程固化）

**让 Agent 记住成功的流程，下次直接执行！**

这是本项目的核心创新：当 Agent 成功完成任务后，会自动将执行流程保存为模板。下次执行相似任务时，直接使用模板，无需 LLM 重新规划，节省时间和 Token。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/workflow/templates` | GET | 获取所有模板列表 |
| `/api/workflow/template?id=xxx` | GET | 获取单个模板详情 |
| `/api/workflow/execute` | POST | 执行指定模板 |
| `/api/workflow/create` | POST | 手动创建模板 |
| `/api/workflow/delete` | POST | 删除模板 |
| `/api/workflow/match` | POST | 测试模板匹配（不执行） |

#### 工作原理

```
第一次执行: "微信给张三发消息说你好"
  → Agent 规划并执行任务（消耗 Token）
  → 成功后自动保存为模板

第二次执行: "微信给李四发消息说今天开会"
  → 匹配到模板 → 直接执行（不消耗 Token）
  → 3秒完成 vs 原来30秒 + 2000 tokens
```

#### 执行任务（优先使用模板）

LOOM 根据任务语义自动匹配已验证模板；没有可靠模板时才进入 Agent 规划。模板参数、设备范围和执行模式由 LOOM 统一传递。

**参数说明：**
- `use_template`: 是否优先使用模板（默认 true）
- `force_agent`: 强制使用 Agent 规划，跳过模板匹配（默认 false）
- `template_params`: 模板参数（替换模板中的占位符）

#### 手动创建模板

模板属于内部执行资产，应通过 LOOM 的模板管理与调试流程创建、验证和发布，避免未经验证的坐标脚本进入生产任务。

#### 查看所有模板

在 LOOM 模板管理或 CLI/MCP 只读能力中查看。

#### 执行指定模板

由 LOOM 绑定明确设备和参数后执行，并保留运行审计、取消与失败恢复信息。

### 🔧 Tool API（底层控制）

**手动指定坐标和操作：**

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/tool/tap` | POST | `{"x":500,"y":300}` | 点击坐标 |
| `/api/tool/swipe` | POST | `{"start_x":0,"start_y":500,"end_x":500,"end_y":500,"duration_ms":300}` | 滑动 |
| `/api/tool/long_press` | POST | `{"x":500,"y":300,"duration_ms":1000}` | 长按 |
| `/api/tool/screenshot` | GET | - | 截图（返回 base64 PNG） |
| `/api/tool/get_screen_info` | GET | - | 获取 UI 层级树 |
| `/api/tool/find_node_info` | POST | `{"text":"登录"}` | 查找 UI 元素 |
| `/api/tool/open_app` | POST | `{"package_name":"com.tencent.mm"}` | 打开应用 |
| `/api/tool/input_text` | POST | `{"text":"Hello"}` | 输入文本 |
| `/api/tool/system_key` | POST | `{"key":"back"}` | 返回/主页/最近任务 |
| `/api/tool/get_installed_apps` | GET | - | 获取已安装应用列表 |
| `/api/tool/list` | GET | - | 获取所有可用工具 |

#### 截图

通过 LOOM 手机连接页、矩阵工作台或 CLI/MCP 截图能力获取；LOOM 负责并发限制、超时预算、缓存和设备级错误。

---

## 🔗 LOOM Agent Integration

### 安装 Skill

```bash
# 在 LOOM 的“Agent 接入”页安装统一 Skill
# 或从 LOOM 官方 Skill 包安装 luming-phone-agent
```

### 唯一手机 Skill

`luming-phone-agent` 是唯一对外手机 Skill。Codex、Claude Code、OpenCode、Hermes 和其他 Agent 都通过 LOOM CLI/MCP 调用它，不直连手机 HTTP 端口，也不保存手机地址或长期凭据。

它包含：
- 🧠 自然语言智能执行
- 🔄 流程模板系统（零Token秒执行）
- 🔧 精确坐标控制
- 📸 截图视觉验证
- 🔄 自动错误恢复
- 📊 状态实时监控

### 使用示例

```
你: "帮我用微信给老王发消息说今天加班晚点回去"

Agent → 调用 luming-phone-agent → 通过 LOOM CLI/MCP 检查状态
      → 匹配模板（如有）或 Agent 执行
      → 打开微信 → 搜索老王 → 发送消息
      → 截图验证 → 返回结果: "消息已发送"
```

### 快速命令参考

| 命令 | 说明 |
|------|------|
| `status()` | 检查设备状态 |
| `execute("任务描述")` | 智能执行任务 |
| `template("模板名", params)` | 执行模板 |
| `templates()` | 查看所有模板 |
| `screenshot()` | 截图查看 |
| `tap(x, y)` | 精确点击 |
| `swipe(...)` | 滑动操作 |
| `apps()` | 应用列表 |

---

## 🌐 兼容其他 AI 工具

任何支持 CLI 或 MCP 的 Agent 都能通过 LOOM 使用手机能力。对外集成应调用 LOOM CLI/MCP；手机 REST 认证属于 LOOM 内部传输协议，不应成为用户或第三方 Agent 的配置项。

### 已验证兼容的工具

| 工具 | 状态 | 集成方式 |
|------|------|----------|
| **Codex** | ✅ 已适配 | LOOM MCP / CLI + `luming-phone-agent` |
| **Claude Code** | ✅ 已适配 | LOOM MCP / CLI + `luming-phone-agent` |
| **OpenCode** | ✅ 已适配 | LOOM MCP / CLI + `luming-phone-agent` |
| **Hermes Agent** | ✅ 已适配 | LOOM CLI + `luming-phone-agent` |
| 其他支持 MCP/CLI 的 Agent | 可接入 | 读取 LOOM 能力目录后调用，不直连手机 |

### 接入边界

1. 先在 LOOM “手机连接”页完成配对。
2. Agent 读取 LOOM 的 CLI/MCP 能力目录。
3. Agent 调用 LOOM 手机能力并传入任务和设备范围。
4. LOOM 负责设备发现、认证、重连、审计和错误翻译。

第三方 Agent 不应写入自己的 `.codex` 目录冒充 Codex，也不应保存手机 URL、端口、认证 Header 或长期凭据。

---

## 💡 Examples

### 应用操作

```json
{"prompt": "打开微信"}
{"prompt": "打开支付宝"}
{"prompt": "打开抖音刷几个视频"}
```

### 发送消息

```json
{"prompt": "打开微信，给张三发消息说下午三点开会"}
{"prompt": "打开QQ，给李四发送最近的照片"}
```

### 购物

```json
{"prompt": "打开淘宝，搜索蓝牙耳机，看第一个商品"}
{"prompt": "打开京东，查看我的订单"}
{"prompt": "打开美团，点一杯奶茶外卖"}
```

### 系统

```json
{"prompt": "打开设置，调低屏幕亮度"}
{"prompt": "打开设置，关闭WiFi"}
{"prompt": "打开文件管理，找最近的PDF文件"}
```

### 复合任务

```json
{"prompt": "打开微信，在工作群里发送今天的日报截图"}
{"prompt": "打开支付宝，充值话费100元"}
{"prompt": "打开音乐APP，播放我喜欢的歌单"}
```

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         外部调用方                                   │
│   Hermes Agent  │  Python脚本  │  其他 HTTP 客户端                   │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ LOOM CLI / MCP（已配对设备范围）
                       │ 任务、素材与状态请求
                       ▼
              ┌─────────────────────┐
              │  HTTP API Server    │  NanoHTTPD @ Port 9527
              │                     │
              │  /api/agent/*       │  ← Agent 任务执行
              │  /api/tool/*        │  ← 底层工具调用
              │  /api/channels      │  ← 配置管理
              └──────────────┬──────┘
                             │
                             ▼
              ┌─────────────────────┐
              │   AgentService      │  LangChain4j Agent Loop
              │                     │
              │  ┌───────────────┐  │
              │  │   LLM Call    │◄─┼── GPT-4o / Claude / Qwen
              │  └───────┬───────┘  │
              │          │          │
              │  ┌───────▼───────┐  │
              │  │  Tool Exec    │◄─┼── ToolRegistry
              │  └───────┬───────┘  │     tap / swipe / input
              │          │          │     screenshot / open_app
              │   Loop until        │
              │   task complete     │
              └──────────────┬──────┘
                             │
                             ▼
              ┌─────────────────────┐
              │ AccessibilityService│  Android 无障碍服务
              │                     │
              │  • dispatchGesture  │  手势操作
              │  • getRootInActive  │  UI树解析
              │  • takeScreenshot   │  截图
              │  • performGlobal    │  返回/主页/最近
              └─────────────────────┘
```

---

## 📁 Project Structure

```
agent-phone/
├── app/src/main/java/com/apk/claw/android/
│   ├── agent/                   # Agent 核心
│   │   ├── AgentService.kt      # Agent 接口
│   │   ├── DefaultAgentService.kt  # Agent 实现
│   │   ├── langchain/           # LangChain4j 桥接
│   │   └── llm/                 # LLM 客户端
│   │
│   ├── server/                  # HTTP API 服务
│   │   ├── ConfigServer.kt      # NanoHTTPD 服务器
│   │   ├── AgentApiController.kt  # /api/agent/* 处理
│   │   ├── ToolApiController.kt   # /api/tool/* 处理
│   │   ├── WorkflowApiController.kt # /api/workflow/* 处理
│   │   └── TokenValidator.kt    # Token 验证
│   │
│   ├── workflow/                # 流程模板系统
│   │   ├── WorkflowTemplate.kt  # 模板数据结构
│   │   └── WorkflowTemplateManager.kt # 模板管理器
│   │
│   ├── tool/                    # 工具系统
│   │   ├── ToolRegistry.kt      # 工具注册
│   │   └── impl/                # 工具实现
│   │       ├── TapTool.kt       # 点击
│   │       ├── SwipeTool.kt     # 滑动
│   │       ├── ScreenshotTool.kt # 截图
│   │       └── ...              # 其他工具
│   │
│   ├── channel/                 # 消息通道
│   │   ├── dingtalk/            # 钉钉
│   │   ├── feishu/              # 飞书
│   │   ├── qqbot/               # QQ
│   │   ├── discord/             # Discord
│   │   └── telegram/            # Telegram
│   │
│   ├── service/                 # 系统服务
│   │   ├── ClawAccessibilityService.java  # 无障碍服务
│   │   ├── ForegroundService.kt # 前台服务
│   │   └── KeepAliveJobService.kt # 定时守护
│   │
│   └── ui/                      # 界面
│       ├── home/                # 首页
│       ├── settings/            # 设置页
│       │   ├── PcPairingActivity.kt       # LOOM 安全配对
│       │   └── LlmConfigActivity.kt       # LLM 配置
│       └── splash/              # 启动页
│
├── ../loom-platform/packages/luming-skills-library/
│   └── skills/luming-phone-agent/  # 唯一统一手机 Skill
│
└── README.md
```

---

## 📄 License

```
Apache License 2.0

Copyright 2026 Agent Phone Team

Licensed under the Apache License, Version 2.0
```

---

## 🔧 Build

```bash
git clone https://github.com/rfdiosuao/lumiapkclaw.git agent-phone
cd agent-phone

# Debug build
./gradlew assembleDebug

# APK output: app/build/outputs/apk/debug/AgentPhone-*.apk
```

**Requirements:** Java 17+, Android SDK 36, Android Studio Ladybug+

---

## 📦 Dependencies

| 库 | 版本 | 用途 |
|----|------|------|
| LangChain4j | 1.12.2 | Agent 编排 |
| OkHttp | 4.12.0 | HTTP 客户端 |
| NanoHTTPD | 2.3.1 | HTTP 服务器 |
| MMKV | 2.3.0 | 本地存储 |
| Gson | 2.13.2 | JSON 序列化 |

---

## 🐛 Troubleshooting

| 问题 | 解决方案 |
|------|----------|
| 🔴 Connection refused | Settings → LAN Config → 开启 |
| 🔴 Unauthorized | 检查 Header 中的 Token |
| 🔴 Accessibility not running | 首页 → 开启无障碍服务 |
| 🔴 LLM not configured | Settings → LLM Config → 配置 API Key |
| 🔴 Task timeout | 简化任务或分步执行 |

---

## 🔗 Links

| 链接 | 说明 |
|------|------|
| [📦 Releases](https://github.com/rfdiosuao/lumiapkclaw/releases) | 下载 APK |
| [🤖 Hermes Agent](https://github.com/nousresearch/hermes-agent) | AI CLI 工具 |
| [📚 Original ApkClaw](https://github.com/apkclaw-team/ApkClaw) | 原始项目 |

---

<div align="center">

**Made with ❤️ by Agent Phone Team**

**Star ⭐ us if you like it!**

</div>
