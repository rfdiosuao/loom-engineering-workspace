# LOOM 手机连接与 Agent 生态加固实施计划

> 日期：2026-07-31  
> 当前基线：LOOM Desktop 2.4.0 / LumiAgent 6.63；目标版本：LOOM Desktop 2.4.2 / LumiAgent 6.64
> 适用仓库：`loom-engineering-workspace`  
> 状态：执行中，本文档是后续开发的唯一任务入口
> 原则：先修基础连接与模型配置，再扩展 Agent；所有外部发布、付费模型和手机写操作继续遵守确认、审计和幂等规则。

## 1. 目标与非目标

### 1.1 本轮目标

1. 让手机在 Wi-Fi、手机热点、纯 USB 三种网络形态下都能稳定与 LOOM 配对、连接、断开和恢复。
2. 让 USB 连接真正获得低延迟画面，而不是继续把截图轮询包装成“实时流”。
3. 简化手机设置页，把“与 LOOM 配对”和“局域网连接”放到第一屏，移除面向用户的“发布中转”入口。
4. 修正 ChatGPT / Codex 安装识别，建立可解释、可自检、可恢复的安装状态。
5. 把 Agent 安装从硬编码名单升级为声明式目录，首批评估并接入 Grok Build、Pi，第二批评估 Goose。
6. 保证支持的 Agent 可以安全写入 LOOM 中转站 Base URL、API Key 和模型配置，同时不破坏官方账号和历史会话。
7. 借鉴 OpenMinis 的 Provider、Skill、Memory、Workspace、Trace 和 Native Offload 架构，形成 APKClaw 的可商业化融合路线。
8. 把此前审查中尚未闭环的 P0/P1 可靠性问题纳入同一执行清单。
9. 增加可选 PRoot/Linux 兼容运行时，让适合本地批处理和 CLI 的任务减少远程往返；原生 Android 能力仍是默认快路径。
10. 增加可选 Shizuku 增强能力层，以类型化、可审计、可撤销的接口补足标准 Android 权限，未授权时自动降级。
11. 完成 LOOM Desktop 2.4.2 与 LumiAgent 6.64 的版本冻结、全量验证、可复现构建和产物校验。

### 1.2 非目标

1. 不在本轮把 OpenMinis 源代码直接合入 APKClaw。
2. 不承诺所有第三方 Agent 都兼容 OpenAI 风格中转站；必须逐个验证协议、模型目录和会话行为。
3. 不把多台手机的所有矩阵缩略图都升级为高帧率视频。高帧率只用于当前聚焦设备，矩阵缩略图继续自适应降帧。
4. 不删除手机内部现有发布协议或正式发布审计链。用户要求删除的是手机设置页中的“发布中转”入口；底层能力是否删除需先做调用引用审计。
5. 不以模拟器通过代替实体手机、真实热点、真实 USB 和真实模型验收。
6. 不把 PRoot 宣称为所有操作的性能加速器；性能收益必须来自减少远程模型往返、本地批处理或 Native Offload，并用基准数据证明。
7. 不把原始 `rish`、root shell、PRoot shell 或任意命令执行直接暴露给模型、LAN API、Skill 或第三方 Agent。
8. 不复制、改名或内嵌 Shizuku 应用；LumiAgent 只通过官方兼容 API 与用户单独安装并授权的 Shizuku/Sui 服务协作。

## 2. 结论摘要

| 问题 | 当前证据 | 结论 | 优先级 |
| --- | --- | --- | --- |
| 有 Wi-Fi 时看不到 USB 配对码 | `PcPairingReadinessPolicy` 只要拿到 `lanIp` 就选 `lan`；`PcPairingActivity` 仅在 `transportHint == "usb"` 时显示验证码 | 已定位确定根因，不是配对码功能未开发 | P0 |
| 开热点后无法稳定局域网连接 | 服务器能枚举 `ap*`、`swlan*`、`softap*`，但没有明确的网络模式状态机、地址刷新确认和热点实体机测试 | 具备部分基础，但不能证明热点模式可靠 | P0 |
| 局域网服务打开后无法关闭 | `toggleConfigServer()` 和 `stop()` 已存在；同时存在持久化自动启动和网络回调重启逻辑 | 需复现并验证关闭与回调/生命周期竞争，不能简单认定“没有关闭功能” | P0 |
| 发布中转入口应删除 | 设置布局把 `publishGroup` 放在连接设置前面，`PUBLISH_RELAY` 单独暴露 | 直接影响信息架构，可独立修复 | P1 |
| 配对与局域网应置顶 | 两项当前被塞在“通道”列表末尾 | 已定位确定原因 | P1 |
| USB 矩阵画面不实时 | `useVisibleScreens.ts` 调 `matrixApi.screens()`；聚焦设备最快 700ms 一次；手机端仍返回单帧 JSON/图片 | 当前没有视频流，USB 只转发截图 HTTP 接口 | P0 |
| ChatGPT 安装识别错误 | `CODEX_DESKTOP_PACKAGE_NAMES` 同时包含 `OpenAI.Codex`、`OpenAI.ChatGPT`，再猜测多个 exe 路径 | 包身份和产品身份混用，状态不够可解释 | P1 |
| Agent 名单不足 | UI 与后端均硬编码 Codex、Claude Code、OpenCode、OpenClaw、Hermes | 需改为声明式目录后再扩展 | P1 |
| OpenMinis 融合 | 官方项目提供手机本地 Linux sandbox、Skills、Memory、Workspace、Native Offload 和 Provider 管理 | 值得借鉴接口，不应直接复制 GPLv3 组合代码 | P2 |

## 3. 当前实现证据

### 3.1 USB 配对码并未缺失，而是被错误隐藏

相关文件：

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PcPairingReadinessPolicy.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/PcPairingActivity.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PhonePairingBootstrap.kt`
- `apps/loom-phone-agent/app/src/main/res/layout/activity_pc_pairing.xml`
- `apps/loom-phone-agent/app/src/main/res/values-zh/strings.xml`

当前逻辑：

```text
有 LAN IP -> transportHint=lan -> 隐藏 6 位码
无 LAN IP -> transportHint=usb -> 显示 6 位码
```

这意味着手机只要连着 Wi-Fi，即便电脑已经通过 USB/ADB 转发连接，手机端仍会把配对页判定为 LAN 模式，导致用户看不到 USB 配对码。

正确行为应当是“传输方式由用户和桌面端能力协商”，而不是“手机当前有没有 LAN IP”：

```text
自动
  ├─ 桌面已确认 USB forward -> USB
  ├─ 桌面可达 LAN -> LAN
  └─ 同时可用 -> 显示两种选择
USB
  └─ 始终显示 6 位码，不受 Wi-Fi/热点影响
局域网
  └─ 显示二维码和局域网地址
```

### 3.2 局域网服务存在启动、停止和自动恢复的竞争面

相关文件：

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/utils/KVUtils.kt`

已有能力：

- 无 LAN 地址时仍启动 loopback，供 USB ADB forward 使用。
- `stop()` 会注销网络回调、停止 NanoHTTPD 并清空实例。
- `KEY_CONFIG_SERVER_ENABLED` 支持重启后自动恢复。
- 网络重新可用时，回调会在“配置为开启但服务器不存活”时重启。

尚未证实的故障点：

1. 用户点击关闭与 `NetworkCallback.onAvailable()` 之间是否存在竞争。
2. `server.stop()` 后 `isAlive` 是否短时间仍返回 true，导致 UI 显示旧状态。
3. Activity 重建、应用回前台或自动启动是否读取了关闭前的旧持久化值。
4. 热点开关造成多个网络回调时，旧回调是否仍能把服务拉起。
5. 关闭仅影响 LAN 暴露还是连 USB loopback 一并停止，目前 UI 文案没有讲清。

修复前必须先加入结构化生命周期日志：

```text
config_server.intent       requested=start|stop, source=user|boot|network
config_server.transition   old=..., new=..., generation=...
config_server.bound        host=0.0.0.0, port=..., interfaces=[...]
config_server.stopped      generation=..., elapsedMs=...
config_server.callback     networkId=..., event=available|lost, ignoredReason=...
```

### 3.3 热点不是普通 Wi-Fi 的同义词

当前 `getLanIpAddress()` 会依次读取 `WifiManager` 和 `NetworkInterface`，并优先选择：

1. `wlan*`
2. `ap*` / `swlan*` / `softap*`
3. `eth*`
4. `rndis*` / `usb*`

这比只读取 Wi-Fi 地址更好，但仍缺：

- 明确区分 `wifi-client`、`hotspot-host`、`usb-loopback`、`usb-tethering`。
- 热点接口出现/消失后的地址稳定窗口。
- 多接口同时存在时的可达性探测。
- 厂商私有热点接口名样本。
- 桌面端从热点客户端实际回连手机的验收。

因此本轮应新增 `PhoneNetworkMode`，禁止继续用一个可空 `lanIp` 推断所有状态。

### 3.4 矩阵“实时流”目前不是屏幕视频流

相关文件：

- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/useVisibleScreens.ts`
- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/screenScheduler.ts`
- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/useMatrixStream.ts`
- `apps/loom-platform/openclaw_new_launcher/src/services/api.ts`
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_matrix.py`
- `apps/loom-platform/openclaw_new_launcher/scripts/openclaw-phone-vision.mjs`

当前两条链路必须分清：

```text
useMatrixStream
  -> SSE/实时事件
  -> 设备状态、任务状态、矩阵事件
  -> 不承载屏幕视频

useVisibleScreens
  -> /api/matrix/screens
  -> /api/lumi/vision/frame
  -> 单帧截图 + knownHash + Blob URL
```

当前截图调度基线：

- 聚焦设备：约 700 ms
- 运行设备：约 1500 ms
- 空闲设备：约 4000 ms
- 失败后：最长约 15 s 退避

USB 连接只是通过 ADB forward 访问相同的手机 HTTP 单帧接口，不会自动变成 H.264/WebRTC/scrcpy 视频。因此用户看到“USB 也不实时”是现有架构的必然结果。

### 3.5 ChatGPT 与 Codex 的安装身份被混在一起

相关文件：

- `apps/loom-platform/openclaw_new_launcher/python/core/official_codex.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/component_installer.py`
- `apps/loom-platform/openclaw_new_launcher/src/components/AgentInstallerPage.tsx`

当前探测同时接受：

```text
OpenAI.Codex
OpenAI.ChatGPT
```

再依次猜测：

```text
app/ChatGPT.exe
app/Codex.exe
ChatGPT.exe
Codex.exe
```

这会产生三个问题：

1. ChatGPT 已安装可能被显示成 Codex 已安装。
2. 包存在但入口不可启动时仍可能留下旧的“已安装”状态。
3. Store 包、独立桌面包、Codex CLI 和 App Execution Alias 没有分别给出证据。

## 4. 目标架构

### 4.1 手机连接状态机

```text
DISABLED
  -> STARTING
  -> LOOPBACK_READY
  -> LAN_DISCOVERING
  -> LAN_READY
  -> STOPPING
  -> DISABLED

任意状态
  -> DEGRADED
  -> RECOVERING
```

状态输出必须包含：

```json
{
  "serviceState": "loopback_ready",
  "generation": 12,
  "usbPairingAvailable": true,
  "lanAvailable": false,
  "networkMode": "hotspot-host",
  "addresses": [],
  "port": 9527,
  "lastTransitionAt": "...",
  "lastErrorCode": ""
}
```

关键约束：

- 用户关闭后，任何旧网络回调不得重新启动服务。
- 启动和停止必须通过单一串行化入口，带 generation token。
- USB 配对能力不依赖 LAN IP。
- LAN 地址只表示“候选地址”，桌面探测成功后才标记“可用”。
- 设置页只呈现结果，不自行推断状态。

### 4.2 USB 实时画面通道

推荐采用“双通道”：

```text
控制面
  HTTP/JSON + 签名 + 审计
  负责输入、任务、状态、错误、权限

媒体面
  USB: ADB forward + H.264/WebSocket 或 scrcpy-compatible stream
  LAN: H.264/WebSocket，失败时降级 JPEG snapshot
```

第一阶段不需要把所有设备都开成 30 FPS：

- 当前聚焦设备：10-20 FPS。
- 可见且运行中的矩阵卡片：2-6 FPS 或增量帧。
- 其余设备：保留当前自适应截图。
- 窗口不可见：暂停媒体流。
- CPU、带宽或解码压力过高：自动降级，不显示“设备异常”。

建议优先做技术验证：

1. 评估复用 scrcpy-server 的协议和许可证边界。
2. 若不复用，则在手机端用 MediaProjection + MediaCodec 输出 H.264。
3. 桌面 Bridge 只转发二进制帧，不把视频塞入 base64 JSON。
4. 前端使用 `MediaSource`/WebCodecs；不支持时降级 `<canvas>` JPEG。

USB 实时画面 SLO：

- 首帧 P95 < 1.5 s。
- 聚焦设备端到端延迟 P95 < 250 ms。
- 控制指令 ACK P95 < 200 ms。
- 断线后 3 s 内自动降级到截图，恢复后自动升回视频。
- 10 台设备同时在线时，只有聚焦设备获得高帧率，不因截图拥塞阻塞下发任务或急停。

### 4.3 声明式 Agent 目录

从以下硬编码位置抽离：

- `AgentInstallerPage.tsx`
- `component_catalog.py`
- `component_installer.py`
- `wire_config.py`
- CLI/MCP 路由中的组件白名单
- release manifest 和 smoke test 中的固定数组

定义统一 `AgentDefinition`：

```json
{
  "id": "grok-build",
  "displayName": "Grok Build",
  "vendor": "xAI",
  "kind": "cli",
  "platforms": ["windows-x64"],
  "install": {
    "strategy": "vendor-script",
    "source": "https://x.ai/cli/install.ps1"
  },
  "detect": {
    "commands": ["grok"],
    "versionArgs": ["--version"]
  },
  "launch": {
    "command": "grok"
  },
  "modelConfig": {
    "adapter": "grok-custom-openai",
    "relayCompatible": "probe-required"
  },
  "sessions": {
    "preserve": true,
    "paths": []
  },
  "security": {
    "executionClass": "user-shell",
    "requiresSandbox": false
  }
}
```

目录必须描述：

- 安装、检测、启动、升级、卸载。
- Windows 支持等级。
- 是否支持自定义 Base URL。
- 协议：OpenAI Chat Completions、Responses、Anthropic、OAuth 或厂商专用。
- API Key 写入位置和是否能安全回滚。
- 会话目录与迁移策略。
- MCP、Skill、Headless、ACP 等能力。
- 是否必须在 sandbox 中运行。

### 4.4 OpenMinis 启发下的 APKClaw 分层

不替换 APKClaw，而是分层：

```text
LOOM Desktop Control Plane
  ├─ Agent Orchestrator
  ├─ Provider / Model Registry
  ├─ Matrix Scheduler
  ├─ Audit / Approval / Entitlement
  └─ Device Stream Gateway

APKClaw Device Execution Plane
  ├─ Deterministic RPA
  ├─ Accessibility / Template / App adapters
  ├─ Screen stream / Screenshot / Input
  ├─ Native device tools
  └─ Optional Mobile Agent Runtime
       ├─ Workspace
       ├─ Memory
       ├─ Skills
       └─ Sandboxed shell (later)
```

可以借鉴的设计：

1. `SKILL.md` 按需加载，而不是把所有 Skill 常驻上下文。
2. Workspace 与 Memory 分离，避免跨客户、跨账号污染。
3. 重平台能力通过 Native Offload 暴露给 Agent。
4. Provider 类型由 schema 运行时发现，UI 不硬编码字段。
5. 凭据只写不读，配置与安全存储原子提交，失败回滚。
6. LLM 请求 Trace 自动移除 `Authorization`、`x-api-key`，响应体限长。
7. 调试 API 与正式生产 API 分离，调试能力默认关闭。

不能照搬的部分：

- OpenMinis 组合项目采用 GPLv3，并链接 PRoot/iSH 等 GPL 组件。
- LOOM/APKClaw 当前有商业闭源/OEM 交付目标，不能直接复制或链接其 GPL 组合实现后仍假设许可证没有变化。
- 如未来引入其 sandbox，只能选择：
  1. 完全独立的 clean-room 实现；
  2. 作为明确隔离、单独分发并履行 GPL 义务的可选 companion；
  3. 在完成商业和法律评估后改变对应模块的分发策略。

## 5. 分阶段实施任务

## Task 1：重构手机设置页信息架构

**修改文件**

- `apps/loom-phone-agent/app/src/main/res/layout/activity_settings.xml`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/SettingsActivity.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt`
- `apps/loom-phone-agent/app/src/main/res/values/strings.xml`
- `apps/loom-phone-agent/app/src/main/res/values-zh/strings.xml`
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/ui/settings/SettingsInformationArchitectureTest.kt`

**实施**

1. 新增第一组“连接 LOOM”。
2. 顺序固定为：
   - 与 LOOM 配对
   - 连接方式与局域网
   - 连接诊断
3. 从 UI 删除 `publishGroup` 和 `PUBLISH_RELAY` 菜单项。
4. 不立即删除 KV 字段和内部发布代码；先用 `rg` 做调用审计，确认正式发布链不依赖手机设置入口。
5. 把“局域网配置”改名为“连接方式与局域网”，状态文案区分：
   - USB 可用
   - 局域网可用：`IP:PORT`
   - 热点可用：`IP:PORT`
   - 服务已关闭
   - 正在切换

**测试**

```powershell
cd apps/loom-phone-agent
.\gradlew.bat :app:testDefaultDebugUnitTest --tests "*SettingsInformationArchitectureTest"
```

**验收**

- 第一屏无需滚动即可进入配对和连接设置。
- 用户不可再看到“发布中转”。
- 删除入口不影响矩阵正式发布、手机相册传输和平台发布协议测试。

## Task 2：修复 USB 配对码与传输方式选择

**修改文件**

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PcPairingReadinessPolicy.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PhonePairingBootstrap.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/PcPairingActivity.kt`
- `apps/loom-phone-agent/app/src/main/res/layout/activity_pc_pairing.xml`
- `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/server/PcPairingReadinessPolicyTest.kt`
- `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/server/PhonePairingBootstrapTest.kt`
- 新增 `apps/loom-phone-agent/app/src/androidTest/java/com/apk/claw/android/ui/settings/PcPairingActivityTest.kt`

**实施**

1. 新增 `PairingTransportMode = AUTO | USB | LAN`。
2. 配对页提供紧凑的 USB/局域网分段选择，不再用 `lanIp != null` 隐式隐藏功能。
3. USB 模式始终生成并显示 6 位一次性码。
4. LAN 模式显示二维码、局域网地址和有效期。
5. 桌面配对成功后返回实际 transport，并写入设备连接档案。
6. 旧版完整配对 payload 保持兼容；禁止输出长期 token。

**先写失败测试**

- Wi-Fi 已连接但选择 USB 时仍显示验证码。
- 热点已开启但选择 USB 时仍显示验证码。
- LAN 不可达时不影响 USB 配对。
- 6 位码只能通过 loopback/USB 兑换。
- 过期码和重复兑换被拒绝。

**验收**

- Wi-Fi、热点、无网三种状态都能进入 USB 配对。
- 已插 USB 时，电脑端 30 秒内完成首次配对。
- UI 不再出现“电脑明明插着 USB，但手机只给 LAN 二维码”。

## Task 3：建立可关闭、可恢复的连接服务状态机

**修改文件**

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/ui/settings/SettingsViewModel.kt`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerState.kt`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PhoneNetworkMode.kt`
- `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/server/ConfigServerManagerTest.kt`
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/server/PhoneNetworkModeTest.kt`

**实施**

1. 所有 start/stop/recover 进入单线程状态机。
2. 每次启动生成 `generation`；旧回调发现 generation 不匹配时直接忽略。
3. 用户关闭先持久化 `enabled=false`，再注销回调并停止服务，避免回调读取旧值。
4. 停止完成前 UI 显示“正在关闭”，不得立即回显“已关闭”。
5. 启动后等待端口真实监听，再发布 Ready。
6. 地址变化只更新候选地址，不重启仍健康的 loopback 服务。
7. 记录结构化事件，供 LOOM 自检导出。

**验收**

- 连 Wi-Fi 启动后可连续执行 50 次开/关，无自动复活。
- 开启热点、关闭热点、切回 Wi-Fi 不产生重复 server。
- App 前后台切换和进程重启尊重最后一次用户开关。

## Task 4：完成手机热点与多网络模式

**修改文件**

- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt`
- `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/PhoneNetworkMode.kt`
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_phone.py`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/core/phone_connection.py`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_phone.py`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/tests/test_phone_connection.py`

**实施**

1. 枚举并返回所有候选接口，不只返回第一个 IP。
2. 分类 `wifi-client`、`hotspot-host`、`usb-tethering`、`ethernet`。
3. 桌面对每个候选地址并行执行短超时签名健康检查，首个通过者成为 active transport。
4. 热点地址变化后触发重探测，不重置长期配对身份。
5. 错误提示区分：
   - 手机热点未开启
   - 电脑未连接该热点
   - 端口不可达
   - 配对身份无效
   - 服务已关闭

**实体机验收矩阵**

| 场景 | 预期 |
| --- | --- |
| 手机连路由器 Wi-Fi，电脑同网 | LAN 连接成功 |
| 手机开热点，电脑连手机热点 | Hotspot LAN 连接成功 |
| 手机开热点且插 USB | USB 和 Hotspot 都可见，默认优先 USB |
| 无 Wi-Fi、无热点、只插 USB | USB 配对与控制成功 |
| 热点切 Wi-Fi | 5 秒内恢复，不重新配对 |
| 用户关闭连接服务 | 所有网络入口停止，重启 App 后仍关闭 |

## Task 5：实现 USB 聚焦设备实时画面 MVP

**新增/修改文件**

- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/stream/PhoneStreamService.kt`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/stream/H264Encoder.kt`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/server/stream/StreamSessionRegistry.kt`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/api/routes_phone_stream.py`
- `apps/loom-platform/openclaw_new_launcher/python/api/bridge.py`
- 新增 `apps/loom-platform/openclaw_new_launcher/src/components/matrix/usePhoneVideoStream.ts`
- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/MatrixWorkbenchPage.tsx`
- `apps/loom-platform/openclaw_new_launcher/src/components/matrix/useVisibleScreens.ts`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_phone_stream.py`
- 新增 `apps/loom-platform/openclaw_new_launcher/src/components/matrix/usePhoneVideoStream.test.ts`

**技术门禁**

先建立一个不进入生产包的 spike，比较：

1. scrcpy-server 兼容方案。
2. 原生 MediaProjection + MediaCodec。

比较项：

- 许可证/OEM 影响。
- Android 7 到当前版本覆盖。
- 是否需要每次弹 MediaProjection 授权。
- H.264 首帧、延迟、CPU、断线恢复。
- 通过 ADB forward 和 LAN 两种 transport 的复用程度。

**MVP 实施**

1. 只为聚焦设备创建高帧率 stream session。
2. stream session 带配对身份、短期 token、设备 ID 和过期时间。
3. 二进制帧与控制 JSON 分离。
4. 前端无法解码时自动降级 `useVisibleScreens`。
5. 流失败只标记“画面已降级”，不得把在线设备标成异常。
6. 下发任务、返回、主页、急停不等待视频链。

**测试**

- 单设备 30 分钟稳定流。
- USB 拔插 20 次。
- 10 设备在线、1 个聚焦高帧率。
- 窗口最小化后流暂停。
- 视频权限拒绝后截图仍可用。

**2026-08-01 实施记录**

- 技术门禁选择原生 `MediaProjection + MediaCodec`：复用 LumiAgent 已有的 Android 权限与前台服务边界，USB ADB forward 和 LAN 共用同一个受签名保护的 H.264 端点；当前实现不引入或复制 scrcpy-server 代码，也不增加新的常驻通用控制服务。
- 手机端已实现聚焦会话、30 秒发起凭据、H.264 二进制分帧协议、容量为 6 的丢旧帧队列、用户授权 Activity、`mediaProjection` 前台服务以及显式停止/投屏撤销/一小时上限清理。
- Desktop Bridge 只向 WebView 返回一次性本地 ticket；手机长期配对密钥、手机流 token 和成员 token 均保留在后端。`/api/phone-stream` 已纳入 `matrix.devices` 权限，停止会话的 `DELETE` 作为安全清理不受商业授权失效阻断。
- 矩阵仅为当前聚焦设备启动高帧率通道；WebCodecs 不支持、用户拒绝权限、解码失败或网络中断时只把画面标为“已降级”，立即恢复截图轮询，不改变设备在线/任务状态。窗口隐藏时停止视频会话。
- 自动化结果：前端平台合同 `221/221`、Node 合同 `98/98`、相关 Python `109/109`、商业权限 Rust `4/4`、LumiAgent `:app:testDebugUnitTest` 全量成功，Desktop 前端 production build 成功。
- 尚未完成实体机门禁：单设备 30 分钟、USB 拔插 20 次、10 台在线仅 1 台高帧率、不同 Android/OEM 的授权行为与首帧/延迟/CPU 数据。没有实体机证据前，本任务状态为“代码与自动化完成，生产验收待完成”，不得把截图降级路径或未测 SLO 宣称为实时视频验收通过。

## Task 6：拆分 ChatGPT、Codex Desktop 与 Codex CLI 检测

**修改文件**

- `apps/loom-platform/openclaw_new_launcher/python/core/official_codex.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/component_installer.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/component_catalog.py`
- `apps/loom-platform/openclaw_new_launcher/src/components/AgentInstallerPage.tsx`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_component_installer.py`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_component_catalog.py`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_agent_installer_page_contract.py`

**实施**

1. 定义独立探测证据：
   - Store package name/family/version。
   - 实际 executable path。
   - executable 架构。
   - App Execution Alias。
   - `--version` 或最小启动探测。
2. ChatGPT Desktop、Codex Desktop、Codex CLI 不再共享一个模糊状态。
3. UI 显示“检测到什么、为什么认为可用、下一步修复什么”。
4. 旧缓存只能作为初始占位，强制检测后必须由新证据覆盖。
5. 自检覆盖 Microsoft Store 不可用、包残留、入口缺失、32/64 位不兼容和旧 16 位 shim。

**验收**

- 只安装 ChatGPT 时不会误报 Codex CLI 可用。
- 包存在但入口不可启动时显示“安装损坏”，而不是“已安装”。
- 修复按钮能重新注册/安装正确架构入口。

## Task 7：把 Agent 安装改为声明式目录

**新增/修改文件**

- 新增 `apps/loom-platform/openclaw_new_launcher/python/config/agent_definitions/`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/core/agent_definition.py`
- 新增 `apps/loom-platform/openclaw_new_launcher/python/core/agent_catalog.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/component_catalog.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/component_installer.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/wire_config.py`
- `apps/loom-platform/openclaw_new_launcher/src/components/AgentInstallerPage.tsx`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_agent_catalog.py`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_wire_config.py`

**第一批**

| Agent | 安装 | LOOM 中转配置 | 建议 |
| --- | --- | --- | --- |
| Grok Build | 官方提供 Windows PowerShell 安装脚本和预编译包 | 先验证官方 custom model/OpenAI-compatible 配置；不能只写 key 就宣称成功 | P1 接入 |
| Pi | npm 包含 coding agent、agent core、统一 LLM API | 通过 provider adapter 验证 Base URL、模型列表和 tool call | P1 接入 |
| Goose | 官方支持多模型和扩展，需验证 Windows 安装及自定义 OpenAI provider | 作为第二批 | P2 评估 |
| Gemini CLI | 安装可做，但不应假设兼容 LOOM OpenAI 中转 | 账号模式/官方 provider 独立呈现 | P2 评估 |

**安全要求**

- 不把 API Key 放命令行。
- 不把明文 Key 写入日志、任务结果或 UI 回显。
- 写配置前备份，写后执行最小真实探测，失败自动回滚。
- 保留官方账号和历史会话；中转配置与官方登录可切换。
- Pi 本身不提供权限系统时，LOOM 必须明确显示其运行权限边界，不给“安全沙箱”假标签。

## Task 8：建立 Agent Provider 兼容性探测

**修改文件**

- `apps/loom-platform/openclaw_new_launcher/python/core/wire_config.py`
- `apps/loom-platform/openclaw_new_launcher/python/core/model_directory.py`
- `apps/loom-platform/openclaw_new_launcher/python/api/routes_components.py`
- `apps/loom-platform/openclaw_new_launcher/src/components/AgentInstallerPage.tsx`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_wire_config.py`
- `apps/loom-platform/openclaw_new_launcher/python/tests/test_routes_components.py`

**探测不能只请求一个固定模型**

按顺序执行：

1. `/models` 或 Agent 对应模型目录。
2. 选择真实可用模型，不使用过期 UI 缓存。
3. 最小文本请求。
4. 最小 tool-call 请求。
5. 流式响应探测。
6. 记录协议能力，不记录密钥。

结果示例：

```json
{
  "reachable": true,
  "protocols": ["responses", "chat_completions"],
  "toolCall": true,
  "streaming": true,
  "selectedModel": "actual-model-id",
  "latencyMs": 812,
  "source": "live-probe",
  "fallbackUsed": false
}
```

对 `404`、`408`、`429`、`500`、`502`、`503`、`504`、DNS、TLS、连接重置分别给中文修复建议。上游挂掉时不得覆盖本地最后一份健康配置。

## Task 9：OpenMinis 启发式融合与 Mobile Runtime PoC

**先写设计，不直接进生产**

- 新增 `docs/superpowers/specs/loom-mobile-agent-runtime.md`
- 新增 `docs/security/openminis-license-boundary.md`
- 新增 `packages/contracts/mobile-agent-runtime.schema.json`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/runtime/MobileRuntimeCapability.kt`
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/runtime/TypedNativeToolGateway.kt`
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/runtime/TypedNativeToolGatewayTest.kt`

**PoC 做五件事**

1. Provider schema 运行时发现。
2. Workspace/Memory 隔离。
3. Skill 元数据按需加载。
4. Native Offload 的 typed tool gateway。
5. Runtime backend 发现、授权、健康检查和确定性回退，不绑定具体 Linux 发行版。

**明确不做**

- 不在未完成许可证、来源、供应链和实体机评审前把 Alpine/PRoot 直接打进正式 APK；兼容运行时先以可选组件和干净接口验证。
- 不复制 OpenMinis GPL 源码。
- 不让手机 Agent 绕过 LOOM 的审批、授权、频控和审计。
- 不把开放 shell 默认授予生产手机。

**验收**

- 同一 Skill 可在 Desktop Agent 与 Mobile Runtime 读取相同元数据。
- 手机只收到被批准的能力子集。
- Provider credential 只写不读，失败不留下半配置。
- 每个 Workspace 的 Memory 不跨账号、不跨客户。
- 运行时不可用、超时或撤权后，任务能够回退原生能力或给出明确的不可执行原因，不出现半执行状态。

**2026-08-01 PoC 实施记录**

- 已新增独立设计规范、OpenMinis clean-room/许可证边界、`loom.mobile-agent-runtime.v1` Draft 2020-12 合同和 fixture。官方公开资料仅用于功能级需求与许可证核对，未引入 OpenMinis 源码、submodule、二进制、rootfs 或依赖。
- `MobileRuntimeCapability` 固定原生能力闭集；Provider schema 对敏感字段强制 `writeOnly`；Workspace/Memory 合同同时绑定账号、客户和工作区；Skill 合同只常驻元数据与来源摘要。
- `ProviderConfigurationCoordinator` 使用 write-only vault 接口和 staging/probe/commit 流程；故障注入证明 probe 失败时旧配置不被替换，新 credential handle 回滚删除，原始 `CharArray` 在完成后清零。
- `TypedNativeToolGateway` 对 scope、审批、过期、能力子集、参数 schema 和幂等键失败关闭；并发重复调用只执行一次，输入变化返回冲突。审计只含摘要，不含参数、输出或凭据。
- backend selector 默认 Android Native 快路径；首选可选 runtime 不健康、未授权或缺失时在执行前确定性回退，能力完全不可用时明确拒绝。任意 shell、`rish`、root 和 Shizuku binder 不在合同能力集中。
- 自动化结果：共享合同 `10/10` schema + fixture 校验通过；LumiAgent JVM 全量 `637/637`、`0` skipped。真实 AndroidKeyStore/Workspace/Memory 存储接线、实体机 scope 切换与可选 Linux runtime 仍由后续任务和实体机门禁完成。

## Task 10：闭环此前尚未完成的可靠性问题

以下项目来自前序对抗审查，尚不能视为完成：

### P0

1. 旧账号后台同步可能覆盖新账号凭据和配置。
2. 授权兑换若发生在账号切换事务之外，可能持久化到旧账号。

### P1

1. 账号切换期间 Matrix 路由仍可能创建任务。
2. 正式发布可能把点击前遗留的“成功”页面当作本次发布成功。
3. 正式发布 15 秒 commit token 的过期约束未在完成阶段再次强制校验。
4. 更新器在退出应用后若备份失败，可能无法重新拉起旧版本。
5. 图片/视频已经生成但下载失败时仍返回 `regenerationAllowed=true`，可能重复计费。
6. 提交请求收到截断或畸形的 HTTP 200 JSON 时未标记 `outcomeIndeterminate`，可能重复计费。

### P2

1. Agent 附件先落盘、后持久化；失败时可能留下孤儿文件。
2. 模型目录错误分类未完整覆盖 `408`、`500`、`520-524`、DNS 和连接重置。
3. 图片批量接口部分返回时可能静默补发新的付费请求。

这些问题应独立 PR，不与手机 UI 重排混合。

## Task 11：Shizuku 增强能力层

**先写失败测试**

- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/privilege/PrivilegeBackendSelectorTest.kt`
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/privilege/PrivilegedActionPolicyTest.kt`
- 覆盖未安装、已安装未授权、已授权、binder 失效、重启后撤权、Sui/root 默认禁用和标准模式回退。

**实现**

- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/privilege/PrivilegeBackend.kt`，统一 `STANDARD`、`SHIZUKU` 和受控 `SUI` 后端能力描述。
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/privilege/ShizukuPrivilegeBackend.kt`，只调用经策略批准的类型化动作，不提供通用 shell 接口。
- 新增 `apps/loom-phone-agent/app/src/main/java/com/apk/claw/android/privilege/PrivilegedActionPolicy.kt`，按动作、账号、设备状态、用户授权和审计上下文做白名单判定。
- 在设置页增加“增强设备能力”状态、自检、授权引导和撤销入口；未安装 Shizuku 时保持标准模式，不阻塞配对、RPA、截图和急停。
- 日志仅记录动作类型、结果、耗时和脱敏设备标识，不记录命令正文、Key、令牌、剪贴板或用户内容。

**验收**

- Android 7-10 可通过电脑 ADB 启动外部 Shizuku 服务后授权；Android 11+ 同时验证无线调试路径。
- Shizuku 被停止、升级、撤权或手机重启时，LumiAgent 不崩溃、不循环申请权限，并在 2 秒内切换到标准模式。
- 所有增强动作都有一次性或持久授权语义、审计记录、超时和幂等键；远程调用不能提交任意命令字符串。

## Task 12：可选 PRoot/Linux 兼容运行时

**先写 contract 和基准测试**

- 新增 `packages/contracts/mobile-linux-runtime.schema.json`，限定 runtime 状态、资源预算、挂载、网络、允许的入口点和脱敏 trace。
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/runtime/LinuxRuntimePolicyTest.kt`。
- 新增 `apps/loom-phone-agent/app/src/test/java/com/apk/claw/android/runtime/LinuxRuntimeFallbackTest.kt`。
- 新增 `apps/loom-phone-agent/tools/benchmark-mobile-runtime.ps1`，比较原生类型化工具、PRoot 本地批处理和远程逐步调用的冷启动、热启动、耗时、内存与电量。

**实现边界**

- PRoot/Linux 是按需安装的兼容 backend，不替换 Android 原生 RPA、MediaProjection、网络服务或 Native Offload。
- 运行时只挂载独立 workspace；默认只读输入、独立输出、禁止访问 app 私有凭据、系统目录、其他账号 workspace 和宿主 Unix socket。
- 网络默认关闭；只有 manifest 声明并经用户批准的 Provider 域名可临时放行，凭据通过一次性句柄注入且不可回读。
- Skill 只能调用 `TypedNativeToolGateway` 中批准的能力；PRoot 内部进程不能连接 Shizuku binder、`rish` 或 root shell。
- 发行物来源、许可证、哈希、SBOM 和升级/回滚策略写入 `docs/security/mobile-linux-runtime-supply-chain.md`；在评审完成前正式 APK 不内嵌发行版 rootfs。

**验收**

- 兼容运行时缺失、损坏、空间不足、OOM、超时和被用户停用时均可恢复，不影响 LumiAgent 主进程与标准能力。
- 同一批处理任务相较远程逐步调用减少模型往返并有可复现实测；若某任务比原生工具慢，调度器必须保留原生快路径。
- workspace、Memory、输出物和缓存按账号隔离；卸载运行时能清理其可再生成数据且不删除用户业务文件。

## Task 13：版本冻结、构建与 2.4.2 发布候选

**先写版本失败测试**

- Desktop 版本单一来源校验必须覆盖 `package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml` 和 `src-tauri/Cargo.lock`，目标均为 `2.4.2`。
- LumiAgent 版本合同测试先改为期望 `versionCode 933`、`versionName 6.64-stability`，同时覆盖 Android 7 变体后再修改构建配置。
- 新增 `docs/RELEASE_NOTES_2.4.2.md`，明确 USB 视频、PRoot 兼容运行时和 Shizuku 的已实现范围与已知限制，不把 PoC 表述为默认生产能力。

**构建与校验**

- 先只读检查系统盘与构建盘空间；只可清理经确认可再生成的本项目缓存，不得删除用户文件。
- 执行全量自动测试、实体机矩阵、受保护发布验证、签名验证和 smoke test。
- 构建 LOOM Desktop 2.4.2 NSIS 安装包以及 LumiAgent 6.64 default/android7 APK；记录绝对路径、大小、SHA256、签名、来源提交和已知限制。
- 本任务只生成本地发布候选；未经用户明确确认，不推正式更新通道、不创建正式 GitHub Release、不对外发布。

## 6. PR 与 Worktree 划分

| PR | Worktree 建议 | 内容 | 依赖 |
| --- | --- | --- | --- |
| A | `phone-settings-pairing` | Task 1-2 | 无 |
| B | `phone-network-state` | Task 3-4 | A 可并行，合并时处理冲突 |
| C | `phone-usb-stream-spike` | Task 5 技术验证 | B 的 transport contract |
| D | `agent-catalog-detection` | Task 6-7 | 无 |
| E | `agent-provider-probes` | Task 8 | D |
| F | `mobile-runtime-spec` | Task 9 文档与 contract | 无 |
| G | `reliability-p0-account` | Task 10 P0 | 独立优先 |
| H | `reliability-p1-publish-update-media` | Task 10 P1/P2 | 可拆 3 个更小 PR |
| I | `phone-shizuku-capabilities` | Task 11 | Task 9 typed gateway |
| J | `phone-linux-runtime` | Task 12 | Task 9 contract；许可证与供应链评审门禁 |
| K | `release-2.4.2` | Task 13 | A-J 全部验收后 |

禁止多个会话共享同一 worktree 写入。每个 PR 在开始前必须：

```powershell
git fetch origin
git rebase origin/main
git status --short
```

## 7. 推荐执行顺序

### 阶段一：先让基础连接可信

1. Task 2 USB 配对码。
2. Task 3 服务开关状态机。
3. Task 4 热点模式。
4. Task 1 设置页重排。
5. Task 6 ChatGPT/Codex 检测。

完成标准：新用户只靠第一屏可以完成 USB 或 LAN 配对；关闭后不会复活；安装检测不误报。

### 阶段二：让核心商业链稳定

1. Task 10 P0。
2. Task 8 Provider 探测。
3. Task 10 更新、发布、媒体 P1。
4. Task 7 Agent 声明式目录。

完成标准：模型或中转站异常不会破坏配置，不会重复计费；账号切换不会串数据。

### 阶段三：提升差异化体验

1. Task 5 USB 实时画面。
2. Grok Build / Pi 首批接入。
3. Task 9 OpenMinis 启发式 PoC。
4. Task 11 Shizuku 增强能力层。
5. Task 12 PRoot/Linux 兼容运行时与性能基准。

完成标准：聚焦手机 USB 低延迟预览；新增 Agent 有真实安装、检测、配置、回滚和会话保留证据；增强权限和 Linux 运行时均可撤销、可降级、可审计且不暴露通用 shell。

### 阶段四：冻结 2.4.2 发布候选

1. Task 13 版本合同、全量回归和实体机门禁。
2. 构建 Desktop 2.4.2 与 LumiAgent 6.64 default/android7 安装产物。
3. 生成 SHA256、签名、SBOM、来源提交、测试计数、实体机记录和已知限制证据包。

完成标准：所有任务验收证据齐全且工作树可复现；只生成本地候选，不未经确认对外发布。

## 8. 总体验收门禁

### 自动测试

```powershell
# Phone default + Android 7 compatibility property
cd apps/loom-phone-agent
.\gradlew.bat :app:testDebugUnitTest
.\gradlew.bat -Pandroid7Compat=true :app:testDebugUnitTest

# Desktop Python
cd ..\loom-platform\openclaw_new_launcher
python -m pytest python/tests

# Frontend
npm test
npm run build

# Node contracts
npm run test:node

# Rust
cd src-tauri
cargo check --locked
```

### 实体机

- Android 7、Android 10、Android 14+ 各至少一台。
- Wi-Fi、手机热点、纯 USB、USB+Wi-Fi 四种连接。
- 2 台实体机并发配对和控制。
- 10 台设备 2 小时 soak。
- USB 聚焦画面 30 分钟。
- 拔插 USB、锁屏、息屏、前后台、热点切换、路由器切换。
- Shizuku 未安装、未授权、已授权、binder 中断、撤权和重启恢复。
- PRoot/Linux runtime 首次安装、冷/热启动、空间不足、网络禁用、任务超时、强制停止、卸载和原生回退。

### Agent 与中转站

- 官方账号模式。
- LOOM 中转模式。
- 中转站短暂 5xx、模型下架、模型目录为空、Key 错误。
- 配置失败自动回滚。
- 切回官方账号后历史会话仍存在。
- Grok Build、Pi 分别完成安装、检测、启动、最小文本、最小工具调用。

### 证据包

每个正式版本必须包含：

- 测试计数与命令。
- 实体机型号、Android 版本和 transport。
- 关键 SLO 实测。
- 安装包/APK SHA256。
- 版本来源提交。
- 已知限制。
- 失败日志脱敏样本。

## 9. Definition of Done

只有同时满足以下条件，本文档中的对应任务才可标记完成：

1. 根因有代码或运行证据，不以截图猜测替代。
2. 先有失败测试，再有修复。
3. 中文 UI 给出可行动错误，不泄露密钥和内部堆栈。
4. USB、LAN、热点均有实体机证据。
5. 新 Agent 不是“按钮能点”，而是安装、检测、配置、调用、回滚、卸载完整闭环。
6. 上游模型不可用时不破坏健康配置、不重复计费、不制造假成功。
7. 实时画面失败不会阻塞任务、控制和急停。
8. OpenMinis 只借鉴公开接口思想，许可证边界有书面审查。
9. 全量测试、发布来源和产物校验可复现。
10. Shizuku 与 PRoot/Linux 均为可选能力；缺失、失效或撤权不会破坏 LumiAgent 基础功能，且任何远程入口都不能执行任意 shell。
11. Desktop `2.4.2` 与 LumiAgent `6.64-stability` 的版本、签名、SHA256、来源提交和 release notes 一致。

## 10. 官方参考

- OpenMinis：`https://github.com/OpenMinis/OpenMinis`
- OpenMinis Debug/Provider API：`https://github.com/OpenMinis/OpenMinis/blob/main/docs/specs/debug-server-api.md`
- Grok Build：`https://github.com/xai-org/grok-build`
- Pi：`https://github.com/earendil-works/pi`
- Goose：`https://github.com/aaif-goose/goose`
- Shizuku API：`https://github.com/RikkaApps/Shizuku-API`
- PRoot：`https://github.com/proot-me/proot`

## 11. 下次恢复工作的首条提示词

```text
请继续执行 docs/superpowers/plans/2026-07-31-loom-phone-connectivity-agent-ecosystem-hardening.md。
先同步 origin/main，确认当前版本、已合并 PR、工作树和测试基线；然后只领取一个未完成 Task，
在当前任务的独立 worktree 和 codex/ 分支按 TDD 顺序实施。不得把截图轮询称为实时视频流，不得跳过实体机验收，
不得在日志或命令行暴露 API Key，不得直接复制 OpenMinis 的 GPLv3 组合源码，不得把原始 Shizuku/PRoot shell 暴露给模型或远程 API。
完成后给出根因、变更文件、测试计数、实体机证据、残余风险和 PR 链接。
```
