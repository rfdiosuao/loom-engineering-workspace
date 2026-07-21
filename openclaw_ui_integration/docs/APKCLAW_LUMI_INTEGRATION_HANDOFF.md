# APKClaw 与 Lumi 桌面端对接交接文档

> 更新时间：2026-05-11
> 目的：给新的开发窗口或 APKClaw 侧开发任务使用，明确 Lumi 桌面端与 APKClaw 手机端的长期接口方向、当前实测结果、兼容策略和下一步改造清单。

> 当前稳定基线：APKClaw 已推进到 `versionName=6.26` / `versionCode=860`，`/api/lumi/*` 安全通道、初始化体检、图片导入、录屏回传、游戏/视觉模式、视觉动作安全黑名单和独立指针开关都已进入可验收状态。本文后半部分保留 v6.1-v6.11 的历史演进记录，遇到冲突时以 `PHONE_CONNECTOR_API_CONTRACT.md`、`APKCLAW_LAUNCHER_SECURE_CHANNEL.md` 和当前代码为准。

## 1. 结论先说

正式方向建议使用新 header：

```text
X-AGENT-PHONE-TOKEN: <token>
```

旧 header：

```text
X-APKCLAW-TOKEN: <token>
```

只保留为过渡兼容。

原因：

- `X-AGENT-PHONE-TOKEN` 更通用，不把协议名字绑死在 APKClaw 上。
- 未来可能不止 APKClaw，也可能有 iOS 端、模拟器端、USB/ADB 代理端、云手机端，用 `AGENT-PHONE` 更像长期协议。
- Lumi 已经可以同时发送新旧 header，因此 APKClaw 可以大胆改，迁移期不会立刻断掉旧版本。
- APKClaw 新版本应优先接受 `X-AGENT-PHONE-TOKEN`，同时临时接受 `X-APKCLAW-TOKEN`，等稳定后再考虑移除旧 header。

## 2. 当前真实设备实测

测试设备：

```text
APKClaw 地址：http://192.168.1.137:9527
设备归属：远程 Wi-Fi 设备是红米 K80（实测型号 25060RK16C）；USB 数据线连接的另一台设备是荣耀，不是当前 Wi-Fi 验收目标。
Token：已由用户提供，文档不记录明文
```

实测结果：

- `GET /api/device/status` 可访问。
- 单独发送 `X-AGENT-PHONE-TOKEN` 可成功鉴权。
- 单独发送 `X-APKCLAW-TOKEN` 可成功鉴权。
- 不发送 token 会返回 `401`。
- `OPTIONS` 预检已返回允许 `X-AGENT-PHONE-TOKEN` 和 `X-APKCLAW-TOKEN` 的 CORS headers。
- `GET /api/tool/screenshot` 可成功返回结构化 PNG 对象。
- 截图尺寸：`1280 x 2772`。
- `GET /api/tool/screen_tree` 可成功返回结构化无障碍控件树，当前实测 31 个节点。
- `GET /api/tool/get_screen_info` 仍可成功返回旧文本控件树。
- `POST /api/tool/wait` 可成功执行无副作用工具调用。

当前状态返回内容解析后大致为：

```json
{
  "taskRunning": false,
  "agentInitialized": false,
  "llmConfigured": true,
  "accessibilityRunning": true,
  "screenshotSupported": true,
  "screenInfoSupported": true,
  "overlayPermission": true,
  "cursorOverlayEnabled": true,
  "version": "6.1",
  "versionCode": 610,
  "serverPort": 9527
}
```

无障碍控件树已经能返回可点击控件的文本和 bounds，例如：

```text
[TextView] text="设置"
[LinearLayout] [clickable] bounds=[51,453][1229,631]
  [TextView] text="LLM 配置"
  [TextView] text="Kimi-K2.6"
[LinearLayout] [clickable] bounds=[51,1853][1229,2034]
  [TextView] text="API Token"
  [TextView] text="已设置"
```

这说明后续可以走“截图视觉 + 无障碍结构树 + 动作执行”的混合控制路线，不必只靠裸截图盲点。

## 3. Lumi 当前行为

Lumi 当前已经新增手机连接服务：

```text
openclaw_new_launcher/src/services/phoneApi.ts
```

当前请求会同时发送：

```text
X-AGENT-PHONE-TOKEN: <token>
X-APKCLAW-TOKEN: <token>
```

这是为了兼容当前 APKClaw 运行版本。

Lumi 当前已优先调用：

```text
GET /api/device/status
GET /api/tool/screenshot
GET /api/tool/screen_tree
POST /api/tool/tap
POST /api/tool/swipe
POST /api/tool/long_press
```

其中 `/api/agent/status` 仅作为旧版本手机端兜底。

Lumi 手机控制页当前已支持：

- 点击截图坐标。
- 点击结构树节点中心坐标。
- 长按结构树节点。
- 四向滑动手势。
- “AI 指针”开关控制动作请求里的 `visualize`。
- 每次动作记录 `traceId`、before screenshot、after screenshot 和动作坐标。

长期目标不是让两个 header 永久存在，而是：

1. APKClaw 新版本正确支持 `X-AGENT-PHONE-TOKEN`。
2. Lumi 保留旧 header 一段时间用于兼容旧手机端。
3. 等 APKClaw 发布稳定后，再决定是否移除 `X-APKCLAW-TOKEN`。

## 4. 标准 API 契约

### 4.1 鉴权

所有 API 都应接受：

```text
X-AGENT-PHONE-TOKEN: <token>
```

迁移期兼容：

```text
X-APKCLAW-TOKEN: <token>
```

优先级建议：

1. 如果存在 `X-AGENT-PHONE-TOKEN`，优先校验它。
2. 如果不存在，再尝试 `X-APKCLAW-TOKEN`。
3. 如果两个都存在但其中一个正确，迁移期建议允许通过；稳定期可以改为新 header 优先且必须正确。

### 4.2 CORS

APKClaw 如果继续让 Lumi 前端直接访问手机 HTTP server，需要 CORS 允许这两个 header。

建议所有响应带：

```text
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN
```

`OPTIONS` 预检也必须返回同样的 `Access-Control-Allow-Headers`。

否则命令行能通，但 Lumi WebView 里会被浏览器 CORS 拦掉。

### 4.3 统一响应格式

建议 APKClaw 所有 API 统一返回：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

失败：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "unauthorized",
    "message": "Invalid or missing token"
  }
}
```

如果暂时不想改太多，`error` 也可以先继续用字符串，但长期建议改成对象，方便 Lumi 展示可读错误。

## 5. MVP 必须稳定的接口

### 5.1 状态

```text
GET /api/agent/status
```

当前可用，但 `data` 是 JSON 字符串。长期建议直接返回对象。

建议目标返回：

```json
{
  "success": true,
  "data": {
    "taskRunning": false,
    "agentInitialized": true,
    "llmConfigured": true,
    "accessibilityRunning": true,
    "screenshotSupported": true,
    "screenInfoSupported": true,
    "overlayPermission": false,
    "version": "0.1.0"
  },
  "error": null
}
```

### 5.2 截图

```text
GET /api/tool/screenshot
```

当前可用，返回 PNG base64 字符串。

建议目标返回：

```json
{
  "success": true,
  "data": {
    "mime": "image/png",
    "base64": "...",
    "width": 1280,
    "height": 2772,
    "orientation": "portrait",
    "capturedAt": "2026-05-10T01:50:00+08:00"
  },
  "error": null
}
```

### 5.3 屏幕结构树

```text
GET /api/tool/get_screen_info
```

当前可用，返回文本化无障碍树。

MVP 可以继续返回文本，但长期建议增加结构化 JSON 接口：

```text
GET /api/tool/screen_tree
```

建议返回：

```json
{
  "success": true,
  "data": {
    "screen": {
      "width": 1280,
      "height": 2772,
      "orientation": "portrait"
    },
    "nodes": [
      {
        "id": "node-1",
        "className": "TextView",
        "text": "LLM 配置",
        "description": null,
        "clickable": false,
        "bounds": {
          "left": 228,
          "top": 512,
          "right": 957,
          "bottom": 572
        }
      }
    ]
  },
  "error": null
}
```

这个接口是后续“AI 精准控制手机”的关键，比只看截图更稳。

### 5.4 点击

```text
POST /api/tool/tap
```

请求：

```json
{
  "x": 512,
  "y": 1360
}
```

长期建议扩展为：

```json
{
  "x": 512,
  "y": 1360,
  "traceId": "lumi-20260510-0001",
  "visualize": true,
  "durationMs": 120
}
```

返回：

```json
{
  "success": true,
  "data": {
    "x": 512,
    "y": 1360,
    "traceId": "lumi-20260510-0001",
    "executedAt": "2026-05-10T01:50:00+08:00"
  },
  "error": null
}
```

### 5.5 滑动

```text
POST /api/tool/swipe
```

建议请求：

```json
{
  "startX": 640,
  "startY": 2200,
  "endX": 640,
  "endY": 800,
  "durationMs": 450,
  "traceId": "lumi-20260510-0002",
  "visualize": true
}
```

### 5.6 输入文本

```text
POST /api/tool/input_text
```

建议请求：

```json
{
  "text": "hello",
  "traceId": "lumi-20260510-0003"
}
```

### 5.7 系统按键

```text
POST /api/tool/system_key
```

建议请求：

```json
{
  "key": "BACK",
  "traceId": "lumi-20260510-0004"
}
```

建议支持 key：

```text
BACK
HOME
RECENTS
ENTER
POWER
VOLUME_UP
VOLUME_DOWN
```

## 6. AI Cursor Overlay 协议

用户希望手机端有一个“AI 鼠标/指针”，让 OpenClaw 截屏时能看到 AI 的运动轨迹。

这个方向建议做，而且非常适合 APKClaw。

### 6.1 权限

APKClaw 需要悬浮窗权限：

```text
SYSTEM_ALERT_WINDOW
```

状态接口需要返回：

```json
{
  "overlayPermission": true,
  "cursorOverlayEnabled": true
}
```

### 6.2 开关接口

```text
POST /api/overlay/cursor
```

请求：

```json
{
  "enabled": true,
  "style": "lumi",
  "showTrail": true,
  "showTapRipple": true
}
```

### 6.3 移动指针

```text
POST /api/overlay/cursor/move
```

请求：

```json
{
  "x": 512,
  "y": 1360,
  "durationMs": 300,
  "traceId": "lumi-20260510-0005"
}
```

### 6.4 点击可视化

`tap` 请求里的 `visualize: true` 可以触发：

- 指针移动到目标位置。
- 点击前停顿 100-200ms。
- 目标点显示 ripple。
- 点击后保留短暂轨迹。

这样 OpenClaw 后续再次截图时，能看见“AI 刚刚点了哪里”，有助于多模态自校正。

### 6.5 当前 APKClaw 实现状态

当前源码已接入最小可视化版本：

- 复用 APKClaw 现有 `FloatingCircleManager` 圆形悬浮窗。
- `tap` 收到 `visualize: true` 时，先移动 AI 圆球到目标坐标，再执行点击。
- `long_press` 收到 `visualize: true` 时，先移动 AI 圆球到目标坐标，再执行长按。
- `swipe` 收到 `visualize: true` 时，AI 圆球先定位到起点，再按手势时长移动到终点。
- 点按显示 `点`，长按显示 `按`，滑动显示 `滑`。
- 动作成功显示成功状态，失败显示失败状态，并自动回到 idle。
- 当前稳定版已经具备独立 `POST /api/overlay/cursor` 开关接口和 `POST /api/overlay/cursor/preview` 预览接口；动作请求里的 `visualize` 仍保留为低层工具动作的可视化开关。

## 7. Lumi 侧下一步

Lumi 已经做完：

- 手机控制入口。
- 地址和 token 保存。
- 状态测试。
- 截图显示。
- 点击截图坐标换算到手机真实坐标。
- tap 调用。
- 新旧 token header 兼容。
- AI 指针开关。
- 节点点按、节点长按、四向滑动。
- before/action/after 动作轨迹。
- `/api/agent/execute_task` 自然语言任务入口。
- `/api/agent/cancel_task` 取消任务入口。
- `手机 Agent 工作台` 主控区：自然语言任务、优先模板、强制 Agent、执行记录。
- 低层截图点按/节点点按/手势滑动已降级为 `DEBUG / MANUAL OVERRIDE`。
- `Live Trace` 可展示 APKClaw Agent 事件流：loop、content、tool_call、tool_result、complete/error/timeout。
- 任务失败或超时时，Lumi 仍保留 Agent 事件，用于复盘“走到哪一步停了”。
- 预设低风险任务：设置巡检、搜索框验证、当前屏幕摘要。
- 连接健康诊断：离线、无障碍、截图、结构树、悬浮窗、LLM、任务占用。
- 复制最新任务轨迹，方便贴给下一窗口或写入排障记录。
- Lumi 调用 `/api/agent/execute_task` 默认带 `learn_template:false`，避免模板学习导致服务重启或假超时。

Lumi 下一步建议：

1. 手机服务重新在线后，从 UI 点一条预设任务，验证浏览器内的完整 Agent run。
2. 继续完善独立 overlay 设置接口在 UI 里的产品化入口：`/api/overlay/cursor` 已可用，后续重点是状态展示、大小/样式同步和失败提示。
3. 给 screenshot 画点击/滑动标注层，让用户在桌面端也能看清动作。
4. 把 `Live Trace` 的复制内容升级为结构化 JSON 导出。
5. 后续再考虑多设备、多 Agent 编排和模板市场。

## 8. APKClaw 侧下一步

建议按这个顺序改：

1. 修 `TokenValidator`，正式支持 `X-AGENT-PHONE-TOKEN`。
2. 保留 `X-APKCLAW-TOKEN` 兼容旧调用。
3. 修 CORS `OPTIONS`，允许两个 token header。
4. 给 `/api/agent/status` 增加 `version`、`screenshotSupported`、`screenInfoSupported`、`overlayPermission`。
5. 让 `/api/tool/screenshot` 返回对象，带 `width`、`height`、`mime`。
6. 新增结构化 `/api/tool/screen_tree`，不要只返回文本树。
7. 保持 `/api/agent/execute_task` 作为主入口，低层 `/api/tool/*` 作为 Agent 工具层和调试层。
8. 扩展 `input_text/system_key`，支持 `traceId`。
9. 已完成独立 `/api/overlay/cursor` 开关接口；后续只需要增强 trail/ripple、traceId 展示和 UI 入口。
10. 增强 AI Cursor Overlay：点击 ripple、swipe trail、traceId 文本提示。

## 9. 当前代码位置提示

APKClaw 本地源码位置：

```text
D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
```

已知关键文件：

```text
app/src/main/java/com/apk/claw/android/server/ConfigServer.kt
app/src/main/java/com/apk/claw/android/server/TokenValidator.kt
app/src/main/java/com/apk/claw/android/server/ToolApiController.kt
app/src/main/java/com/apk/claw/android/server/AgentApiController.kt
app/src/main/java/com/apk/claw/android/server/ConfigServerManager.kt
```

Lumi 关键文件：

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher\src\services\phoneApi.ts
D:\Axiangmu\AUSTART\openclaw_new_launcher\src\components\phone\PhoneControlPage.tsx
D:\Axiangmu\AUSTART\openclaw_new_launcher\src\features\registry.ts
D:\Axiangmu\AUSTART\openclaw_new_launcher\src\features\pages.tsx
```

## 10. 验收标准

第一轮验收：

- Lumi 输入 `http://手机IP:9527` 和 token 后，可以连接成功。
- Lumi 能显示手机状态。
- Lumi 能显示实时截图。
- Lumi 点击截图后，手机能收到 tap。
- APKClaw 日志不泄露 token 明文。
- WebView 中没有 CORS 报错。

第二轮验收：

- Lumi 能拿到结构化 screen tree。
- Lumi 能在截图上叠加可点击区域。
- Lumi 能调用 BACK/HOME/RECENTS。
- APKClaw 能显示 AI Cursor Overlay。
- 点击/滑动动作能显示轨迹和 ripple。

第三轮验收：

- OpenClaw 可以根据截图和 screen tree 生成动作计划。
- APKClaw 执行动作后返回 traceId。
- Lumi 能把 before/after screenshot、动作坐标、结构树摘要串成一次可追踪操作。

## 11. 给新窗口的开工提示

可以直接从这句话开始：

```text
请按 D:\Axiangmu\AUSTART\openclaw_new_launcher\docs\APKCLAW_LUMI_INTEGRATION_HANDOFF.md 的契约改 APKClaw。优先修 TokenValidator 和 CORS，让 X-AGENT-PHONE-TOKEN 成为正式 header，保留 X-APKCLAW-TOKEN 兼容；然后把 screenshot/status/screen_tree 按文档补齐。
```

## 12. 2026-05-10 手机初始化与指针可见性更新

本轮新增两个产品化入口：

```text
POST /api/overlay/cursor/preview
GET  /api/device/profile
```

`/api/overlay/cursor/preview` 用于只显示 AI 指针，不执行真实点击。请求示例：

```json
{
  "x": 640,
  "y": 1160,
  "action": "tap",
  "durationMs": 3200,
  "traceId": "cursor_preview_001"
}
```

APKClaw 指针视觉已增强：

- 悬浮层从 56pt 放大到 64pt。
- 动作态使用亮黄色底、黑色描边、白色外环、红色中心点。
- 动作标签显示在指针内，底部显示 `AI TAP / AI HOLD / AI SWIPE` 和坐标。
- 低层工具动作预览停留时间从 380ms 提升到 900ms。

`/api/device/profile` 是只读初始化画像，当前包含：

- 设备型号、品牌、Android 版本、屏幕尺寸、DPI、APKClaw 版本。
- 权限能力：无障碍、截图、结构树、悬浮窗、指针预览、LLM 配置。
- 内存、存储、电量。
- 当前屏幕包名、节点数量、屏幕尺寸。
- 公共目录元数据：Download、Documents、DCIM、Pictures、Movies。
- 可启动应用列表：应用名、包名、Activity。

隐私边界：初始化画像不读取私人文件内容，不扫描全盘文件，只记录公共目录元数据和可启动应用清单。

Lumi 已接入：

- `phoneApi.deviceProfile()`。
- `phoneApi.previewCursor()`。
- 手机工作台连接区新增“预览AI指针”和“初始化手机”按钮。
- 初始化成功后在左侧展示 Device Profile 摘要。

真机验证：

- `AgentPhone_v6.1_20260510_131244.apk` 已安装并验证。
- `POST /api/overlay/cursor/preview` 可显示明显的黄色 AI 指针，不执行真实点击。
- `GET /api/device/profile` 返回正常：Redmi `25060RK16C`、Android 16、`1280x2772`、电量 86%、可启动应用 220 个。
- 指针截图保存位置：`D:\Axiangmu\AUSTART\openclaw_new_launcher\tmp-cursor-preview-fast.png`。

最新微调包：

- `AgentPhone_v6.1_20260510_132210.apk`。
- 作用：把指针动作态的文字进一步简化为干净的 `TAP/HOLD/SWIPE`，避免坐标文字挤在圆里。
- 真机复测截图保存位置：`D:\Axiangmu\AUSTART\openclaw_new_launcher\tmp-cursor-preview-clean.png`。
- 结果：`TAP` 标签可见，但中心红色准心仍有轻微重叠。

最新最终小修包：

- `AgentPhone_v6.1_20260510_132737.apk`。
- 作用：中心只保留红色准心，底部显示 `AI TAP/HOLD/SWIPE`，避免文字和准心重叠。
- 真机复测通过。
- 最终指针截图保存位置：`D:\Axiangmu\AUSTART\openclaw_new_launcher\tmp-cursor-preview-final.png`。

## 13. 2026-05-10 Lumi 初始化画像持久化更新

Lumi 侧把“初始化手机”从一次性展示升级为可复用画像：

- `phoneApi` 新增 `loadPhoneDeviceProfile()`、`savePhoneDeviceProfile()`、`clearPhoneDeviceProfile()`。
- 画像按 APKClaw `baseUrl` 存入 `localStorage`，同一台电脑可记住多台手机。
- Agent 任务默认通过 `buildAgentPromptWithDeviceProfile()` 注入精简画像上下文。
- 注入内容包括设备型号、Android、屏幕、APKClaw 版本、能力开关、内存/存储、电量、当前屏幕、可启动应用、公共目录元数据。
- 注入上下文明确隐私边界：画像不授权读取私人文件内容，实时屏幕与缓存冲突时以实时屏幕为准。
- 工作台的 Agent Mission 新增“手机画像”开关，可临时关闭画像注入。
- Device Profile 卡片显示保存时间、Agent 使用状态，并支持清除画像。
- 复制 Live Trace 时会带上本次是否使用画像，方便排障。

验证：

- `npm run build` 通过。
- 该更新只改 Lumi 前端与服务封装，不需要重新打 APK。

## 14. 2026-05-10 Agent 只读安全边界更新

真机测试暴露了一个重要问题：用户任务写了“不要点击”，模型仍然调用了 `tap`。因此这轮补了代码级硬约束，不能再只依赖 prompt。

APKClaw 更新：

- `POST /api/agent/execute_task` 新增参数 `read_only`，兼容 `readOnly`。
- `read_only=true` 时跳过执行前的 `pressHome()`，不改变当前手机状态。
- `read_only=true` 时 Agent 只暴露/允许这些观察类工具：
  - `get_screen_info`
  - `take_screenshot`
  - `find_node_info`
  - `get_installed_apps`
  - `wait`
  - `finish`
- 若模型仍请求 `tap`、`swipe`、`input_text`、`open_app`、系统按键、剪贴板写入、文件发送、定时任务修改等动作工具，手机端返回阻断错误，真实动作不会执行。
- API 返回数据增加 `readOnly` 字段，方便 Lumi 复盘。

Lumi 更新：

- `phoneApi.executeTask()` 新增 `readOnly` 参数并发送 `read_only`。
- Agent Mission 新增“只读”开关。
- 默认任务改为当前屏幕摘要，默认启用只读。
- 预设任务可携带自己的只读策略：当前屏幕摘要只读，设置巡检/搜索框验证允许导航操作。
- Live Trace 和复制轨迹会记录本次任务是否只读。

构建与分发：

- Lumi：`npm run build` 通过。
- APKClaw：`:app:assembleDebug` 通过。
- 新 APK：`AgentPhone_v6.1_20260510_134642.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.1_20260510_134642.apk`。

## 15. 2026-05-10 v6.2 稳定联调收口

本轮目标：停止 ADB/USB 支线，统一用 Wi-Fi API 收口 Lumi + APKClaw 的稳定联调版。

版本：

- APKClaw `versionName=6.2`。
- APKClaw `versionCode=620`。
- 新包：`AgentPhone_v6.2_20260510_145123.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.2_20260510_145123.apk`。

Lumi 新增：

- 连接区新增“一键验收”按钮。
- 一键验收覆盖：
  - `/api/device/status`
  - `/api/tool/screenshot`
  - `/api/tool/screen_tree`
  - `/api/device/profile`
  - `/api/overlay/cursor/preview`
  - `read_only=true` 探针任务
  - `read_only=true` 当前屏幕观察任务
  - `read_only=true` 诱导点击阻断任务
- 命令行脚本：`scripts/verify-phone-agent.ps1`。
- npm 入口：`npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666`。

验收结果：

```text
npm run build                      PASS
:app:assembleDebug                 PASS
npm run verify:phone               PASS
Phone Agent verification passed.   18 passed, 0 failed
```

最终真机复验：

```text
version=6.2
versionCode=620
npm run verify:phone
18 passed, 0 failed
```

说明：`AgentPhone_v6.2_20260510_145123.apk` 已安装并通过 Wi-Fi 真机验收。后续回归优先使用同一个 `npm run verify:phone` 脚本，不再依赖 USB/ADB。

## 16. 2026-05-10 v6.3 Agent 任务模式化

本轮目标：把 Lumi 对 APKClaw Agent 的控制从一个“只读”布尔开关升级为可产品化的任务模式，避免后续一边要安全、一边又要能操作 UI 时继续堆 prompt。

版本：

- APKClaw `versionName=6.3`。
- APKClaw `versionCode=630`。
- 新包：`AgentPhone_v6.3_20260510_150756.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.3_20260510_150756.apk`。

APKClaw 新增：

- `POST /api/agent/execute_task` 新增 `tool_policy`，兼容 `toolPolicy`。
- 支持三档策略：
  - `observe_only`：只观察，不改变手机状态。
  - `safe_action`：允许 UI 动作，但禁止剪贴板、文件发送、定时任务和主动建议处理。
  - `full_access`：保留旧版全工具能力和模板匹配。
- `read_only=true` 会强制转换为 `observe_only`，兼容 v6.2 调用方。
- 受限策略下不自动 `pressHome()`，不走模板匹配。
- 返回数据新增 `toolPolicy` 字段，和 `readOnly` 一起用于 Lumi 复盘。

Lumi 新增：

- `phoneApi.executeTask()` 支持 `toolPolicy` 并发送 `tool_policy`。
- Agent Mission 把“只读”开关升级为三档模式：只读观察 / 安全操作 / 完全访问。
- 预设任务携带自己的模式：设置巡检、搜索框验证走 `safe_action`；当前屏幕摘要走 `observe_only`。
- Live Trace 显示实际执行边界；复制轨迹会带上 `Tool policy`。
- 一键验收和 `scripts/verify-phone-agent.ps1` 增加 `toolPolicy` 检查和 `safe_action` 探针。
- `scripts/verify-phone-agent.ps1` 默认要求 `versionCode >= 630`，避免旧 APK 误通过。

本地验证：

```text
npm run build          PASS
:app:assembleDebug     PASS
Browser UI check       PASS
```

最终真机复验：

```text
version=6.3
versionCode=630
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666
24 passed, 0 failed
```

## 17. 2026-05-10 v6.4 拖拽手势与一次性授权

本轮目标：补齐“拖动屏幕/拖动控件”的真实手势能力，并修复 `safe_action` 任务里可能误点“始终允许”的持久授权问题。

版本：

- APKClaw `versionName=6.4`。
- APKClaw `versionCode=640`。
- 新包：`AgentPhone_v6.4_20260510_153743.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.4_20260510_153743.apk`。

APKClaw 新增：

- Agent 工具：`drag`。
- HTTP 工具：`POST /api/tool/drag`。
- 请求示例：

```json
{
  "start_x": 640,
  "start_y": 1800,
  "end_x": 640,
  "end_y": 900,
  "hold_ms": 350,
  "duration_ms": 700,
  "visualize": true,
  "trace_id": "drag-demo"
}
```

- `drag` 使用 Android 无障碍 `GestureDescription` 的连续 stroke：先在起点按住，再移动到终点。
- `safe_action` 白名单加入 `drag`；`observe_only` 仍禁止所有动作工具。
- 链式启动拦截弹窗优先点击“本次允许/仅本次允许/允许一次”等一次性选项。
- `safe_action` 下增加 tap 防护：如果模型点向“始终允许”，后端会尝试改写到同屏“本次允许”坐标。

Lumi 新增：

- `phoneApi.drag()`。
- 手势面板新增“拖拽”：从屏幕中下部按住并上移，适合快速冒烟。
- 手势面板新增“截图拖拽”：开启后在截图上点一次起点、再点一次终点，生成真实 drag。
- 动作轨迹支持 `drag`，会保留 before/after screenshot。

本地验证：

```text
npm run build          PASS
:app:assembleDebug     PASS
APK download HEAD      PASS
```

真机复验结果：

```text
2026-05-10 15:52，当前手机已从 v6.3 自更新到 v6.4。
GET /api/device/status => version=6.4, versionCode=640
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666 => 24 passed, 0 failed
POST /api/tool/drag => success=true
```

自更新路径记录：

- 先让 APKClaw Agent 尝试下载 v6.4 APK，Agent 能打开 Chrome 并输入下载地址，但在下载/安装确认阶段容易超时。
- 后续通过 APKClaw 自身低层工具继续走完：Chrome 下载拦截点“保留” -> 下载完成点“打开” -> 下载列表点 APK -> 系统安装器点“继续” -> 允许 Chrome 本次安装 -> ICP 提示点“继续安装” -> 红米 K80 系统安装器增强防护菜单点“单次安装授权” -> 完成。
- 这条路径证明“自我更新”可走通，但不应长期依赖浏览器 UI；后续应新增 APKClaw 内置更新工具/接口，由手机端直接下载 APK 并拉起系统安装器，Agent 只负责处理系统确认页。

## 18. 2026-05-10 v6.5 Via 浏览器优先级

本轮目标：把 Via 浏览器调成网页/下载类任务的最高优先级。真机自更新时 Chrome 的下载拦截和安装来源确认步骤偏重，Via 更轻、更适合 Agent 自动化。

版本：

- APKClaw `versionName=6.5`。
- APKClaw `versionCode=650`。
- 新包：`AgentPhone_v6.5_20260510_155952.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.5_20260510_155952.apk`。

APKClaw 新增：

- Agent 系统提示新增规则：网页浏览、URL 打开、APK 下载、浏览器搜索任务优先使用 Via Browser。
- Via 包名优先识别：
  - `mark.via`
  - `mark.via.gp`
- `GET /api/device/profile` 的可启动应用列表把 Via 排到最前。
- `get_installed_apps` 工具返回结果把 Via 排到最前。

Lumi 新增：

- 设备画像转换时也会把 Via 排到应用列表最前。
- 注入给 Agent 的画像上下文新增 `Preferred browser` 行；检测到 Via 时明确提示先用 Via，再考虑 Chrome 或系统浏览器。

验证结果：

```text
npm run build => PASS
:app:assembleDebug => PASS
已用 Via 浏览器下载并安装 v6.5
GET /api/device/status => version=6.5, versionCode=650
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666 => 24 passed, 0 failed
GET /api/device/profile?includeApps=true&appLimit=12 => apps[0] = Via / mark.via
GET /api/tool/get_installed_apps => first app line = Via | mark.via
```

## 19. 自更新后复活机制（暂缓）

用户补充的关键观察：APK 安装好后，很多情况下需要回到 Agent Phone App，新版本的前台服务和 `9527` server 才会重新运行。Android 更新 APK 会中断旧进程；如果新进程没有被拉起，Lumi 会暂时连不上手机端。

当前代码事实：

- `ClawApplication.onCreate()` 会启动 `ForegroundService`。
- `ForegroundService` 负责保活，并在销毁/任务移除时尝试延迟重启。
- `ConfigServerManager.autoStartIfNeeded()` 会在 App 初始化后按配置恢复局域网 server。
- 目前已有 `BootReceiver` 处理开机自启动，但还没有专门处理自身 APK 更新完成的 `ACTION_MY_PACKAGE_REPLACED` receiver。

后续建议做：

1. 新增 `PackageReplacedReceiver`，监听 `android.intent.action.MY_PACKAGE_REPLACED`。
2. 收到广播后启动 `ForegroundService`，并确保 `ConfigServerManager.autoStartIfNeeded()` 有机会执行。
3. 自更新安装器页面如果出现“打开”，Agent 优先点“打开”；如果只出现“完成”，点完后等待新进程通过 receiver/前台服务恢复。
4. Lumi 的自更新流程在安装后轮询 `/api/device/status`，直到新 `versionCode` 返回。
5. 如果超时仍不可达，Lumi 明确提示用户手动打开一次 Agent Phone，而不是显示普通网络错误。

验收标准：安装完成后不靠用户手动找 App，`GET /api/device/status` 能恢复，并返回目标 `versionCode`。

## 20. 2026-05-10 v6.6 首页与指针可见性

本轮目标：把 APKClaw 手机端从通用 `Agent Phone` 明确收拢到 Lumi 设备控制端体验，同时解决 AI 动作指针“远看不明显”的问题。

版本：

- APKClaw `versionName=6.6`。
- APKClaw `versionCode=660`。
- 新包：`AgentPhone_v6.6_20260510_163826.apk`。
- 本地下载地址：`http://192.168.1.166:8765/AgentPhone_v6.6_20260510_163826.apk`。

APKClaw 新增/调整：

- 首页标题和 App 名称改为 `Lumi Agent Phone`。
- 首页新增设备就绪面板，展示权限进度、LAN server 端口 `9527` 和当前版本号。
- 权限卡片去掉 Switch 形态，改为 `已开启 / 待开启` 状态徽标，降低误解成本。
- AI 动作态悬浮指针改为高对比黄黑准星，并显示 `TAP` / `HOLD` / `SWIPE` / `DRAG` 动作标签。
- APKClaw `CHANGELOG.md` 新增 v6.6 记录。

Lumi 新增/调整：

- `scripts/verify-phone-agent.ps1` 默认验收版本提升为 `versionCode >= 660`。

真机验收：

```text
已用 Via 浏览器下载并安装 v6.6
GET /api/device/status => version=6.6, versionCode=660
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666
Passed: 24
Failed: 0
```

额外检查：

- 安装后首页可见 `Lumi Agent Phone`。
- 首页显示 `5/5 权限 · 局域网 9527 · v6.6`。
- `/api/overlay/cursor/preview` 真机调用成功，返回 `enabled=true`。

## 21. 2026-05-10 Lumi 初始化体检

本轮目标：把“初始化手机/初始化画像”升级为“初始化体检”。每台新手机接入后，Lumi 先摸清设备、权限、能力、存储、电量、应用、浏览器优先级和当前屏幕，后续 Agent 任务再使用这份画像减少猜测。

Lumi 新增：

- `PhoneInitializationReport`：
  - `generatedAt`
  - `summary`
  - `passed`
  - `total`
  - `preferredBrowser`
  - `recommendations`
  - `checks`
- `PhoneDeviceProfileCache` 增加 `healthReport`，体检报告会随同画像保存到 localStorage。
- `buildPhoneInitializationReport(status, profile, screenTree)` 聚合：
  - APKClaw 版本
  - 核心权限
  - 截图/结构树能力
  - LLM 配置
  - 设备型号与屏幕
  - 可用内存
  - 可用存储
  - 电量/充电状态
  - Via 优先浏览器
  - 可启动 App 数量
  - 当前屏幕包名和节点数
  - 可视指针能力

UI 新增：

- 手机控制页按钮改为“初始化体检”。
- 点击后同时刷新：
  - `/api/device/status`
  - `/api/device/profile?includeApps=true&appLimit=220`
  - `/api/tool/screen_tree`
  - `/api/tool/screenshot`
- Device Profile 卡片新增体检通过数、逐项检查列表和首条建议。
- “运行摘要”的健康建议会合并初始化体检 recommendations。

真机验证：

```text
npm run build
PASS

GET /api/device/status
version=6.6, versionCode=660, agentInitialized=true

GET /api/device/profile?includeApps=true&appLimit=220
model=25060RK16C, android=16, apps=220, apps[0]=Via / mark.via
memoryAvailable=3609538560, externalStorageAvailable=10350673920, battery=57

GET /api/tool/screen_tree
screen=1280x2772, nodes=6
```

隐私边界保持不变：初始化体检只记录设备画像、公共目录元数据、可启动应用清单和当前 UI 摘要，不读取私人文件内容，不做全盘扫描。

## 22. 2026-05-10 v6.7 中文任务编码修复

本轮触发：Lumi 控制台里中文任务显示正常，但 APKClaw Agent 输出提示“收到的信息显示为乱码”，并在回答里出现 `[garbled Android text]`。这说明乱码发生在浏览器请求进入手机端 HTTP server 后、传给 Agent 之前。

原因判断：
- Lumi 前端任务输入和 Live Trace 展示中文正常。
- APKClaw JSON POST 入口统一使用 `ToolApiController.parseJsonBody()`。
- 旧实现依赖 NanoHTTPD `session.parseBody(files)` 后的 `files["postData"]`，该路径在中文 UTF-8 JSON 请求体上可能产生错误解码。

修复：
- APKClaw `ToolApiController.parseJsonBody()` 改为优先按 `content-length` 从 `session.inputStream` 读取原始 body 字节，并使用 UTF-8 解码。
- 保留 `parseBody()` 作为无 `content-length` 场景的兜底。
- Lumi `phoneApi.ts` POST JSON 请求头改为 `application/json; charset=utf-8`。
- APKClaw 版本更新为 `versionName=6.7` / `versionCode=670`。
- `scripts/verify-phone-agent.ps1` 默认验收版本提升到 `versionCode >= 670`。

真机验收：
```text
npm run build => PASS
:app:assembleDebug => PASS
新包：AgentPhone_v6.7_20260510_172420.apk
已安装到 Redmi K80
GET /api/device/status => version=6.7, versionCode=670
中文 Agent 任务 => answer="中文编码正常。", hasReplacementChar=false
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666 => 24 passed, 0 failed
```

## 23. 2026-05-10 v6.8 任务前自动亮屏保护

本轮目标：解决用户测试时手机息屏导致 Lumi/Agent 后续任务无法继续的问题。安全边界保持清楚：可以自动点亮屏幕，但不绕过 PIN、图案、密码、人脸/指纹等安全锁。

APKClaw 新增：
- `GET /api/device/status` 返回 `screenOn`、`interactive`、`keyguardLocked`、`deviceLocked`。
- `POST /api/device/wake`：如果屏幕不亮，使用 `WAKE_LOCK + ACQUIRE_CAUSES_WAKEUP` 请求点亮；如果设备仍锁屏，返回锁屏状态和明确提示。
- `POST /api/device/wake` 会消费可选请求体，避免 HTTP keep-alive 场景下残留 body 干扰下一条请求。
- Android 版本更新为 `versionName=6.8` / `versionCode=680`。

Lumi 新增：
- `PhoneStatus` 增加亮屏/锁屏字段。
- `phoneApi.wake()` 接入 `/api/device/wake`，使用无 body POST。
- 手机 Agent 工作台运行任务前先调用 wake。
- 若 `keyguardLocked` 或 `deviceLocked` 为真，Lumi 停住任务，提示用户解锁后再运行。
- 初始化体检加入“亮屏状态”检查。
- `scripts/verify-phone-agent.ps1` 默认验收版本提升到 `versionCode >= 680`，并加入 wake endpoint 检查。

真机验收：
```text
npm run build => PASS
:app:assembleDebug => PASS
新包：AgentPhone_v6.8_20260510_174451.apk
已安装到 Redmi K80
GET /api/device/status => version=6.8, versionCode=680, screenOn=true, interactive=true, keyguardLocked=false
POST /api/device/wake => success=true, message="Screen is awake and ready."
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666 => 27 passed, 0 failed
```

## 24. 2026-05-10 v6.9 APKClaw Lumi 视觉皮肤

本轮目标：把 APKClaw 手机端从旧紫色视觉收束成 Lumi Agent Phone 执行端皮肤，让用户在手机 App、启动页、悬浮球和指针上看到同一套品牌语言。

APKClaw 变更：
- Android 版本更新为 `versionName=6.9` / `versionCode=690`。
- 新增 `ic_lumi_agent_launcher`、`ic_lumi_agent_mark`、`ic_lumi_notification` 三套资源。
- Manifest、启动页、菜单入口和悬浮球默认图标切换为 Lumi 资源。
- 悬浮球改为蓝黑底、cyan 外环；Agent 动作运行态指针改为 cyan 十字线 + gold 核心点。
- 旧紫色品牌色替换为 Lumi blue/cyan/gold 色板，并同步浅色/深色主题。
- 内置 Web 配置页主色从 APKClaw 紫色切到 Lumi blue。

Lumi 变更：
- `scripts/verify-phone-agent.ps1` 默认验收版本提升到 `versionCode >= 690`，避免旧包误通过。

构建状态：
```text
npm run build => PASS
:app:assembleDebug => PASS
新包：AgentPhone_v6.9_20260510_181012.apk
已复制到 Lumi 下载目录
下载地址：http://192.168.1.166:8765/AgentPhone_v6.9_20260510_181012.apk
```

v6.9 已被 v6.10 覆盖，不再单独做真机验收：
```text
superseded by AgentPhone_v6.10_20260510_183820.apk
```

## 25. 2026-05-10 v6.10 悬浮球大小可配置

本轮目标：把 APKClaw 的 Lumi 悬浮球做成用户可调大小。当前 76pt 悬浮球作为“大”尺寸保留，新增“小 / 中 / 大”三档，便于不同手机屏幕和用户习惯适配。

APKClaw 新增：
- Android 版本更新为 `versionName=6.10` / `versionCode=700`。
- `KVUtils` 新增 `KEY_FLOATING_CIRCLE_SIZE`，默认值为 `large`。
- `FloatingCircleManager` 新增 `FloatingSize.SMALL / MEDIUM / LARGE`，对应当前大尺寸的 72% / 86% / 100%。
- 悬浮球显示时会按设置动态刷新根布局、圆角、Lumi mark、运行态指针、进度圈和通道图标尺寸。
- 设置页新增“显示 / 悬浮球大小”入口，使用单选弹窗切换小、中、大。

Lumi 变更：
- `scripts/verify-phone-agent.ps1` 默认验收版本提升到 `versionCode >= 700`。

构建状态：
```text
npm run build => PASS
:app:assembleDebug => PASS
新包：AgentPhone_v6.10_20260510_183820.apk
已复制到 Lumi 下载目录
下载地址：http://192.168.1.166:8765/AgentPhone_v6.10_20260510_183820.apk
稳定下载别名：http://192.168.1.166:8765/AgentPhone_latest.apk
说明：当前 `8765` 文件服务根目录是 APKClaw 的 `app/build/outputs/apk/debug`，所以 latest 别名需要同时同步到该目录。
旧 APK 归档目录：releases/agent-phone/archive/
```

真机验收：
```text
GET /api/device/status => version=6.10, versionCode=700, agentInitialized=true, screenOn=true, deviceLocked=false
npm run verify:phone -- -BaseUrl http://192.168.1.137:9527 -Token 66666666 => 27 passed, 0 failed
```

## 26. 2026-05-10 v6.11 PC 图片导入手机相册与 Lumi CLI

本轮目标：把 PC / Lumi 启动器侧的 AI 生图结果直接送入手机相册，形成“AI 生图 -> 手机 `Pictures/Lumi`”闭环。这样 OpenClaw/Lumi 以后生成图标、海报、商品图或测试素材时，不需要手动传文件，手机端可以直接在相册里看到结果。

APKClaw 新增：
- Android 版本更新为 `versionName=6.11` / `versionCode=710`。
- 新增 `MediaApiController.kt`，提供 `POST /api/media/import_image`。
- 接收 `multipart/form-data`，字段为 `file`、可选 `album`、可选 `filename`。
- 支持 PNG / JPEG / WebP，单文件上限 32MB。
- Android 10+ 通过 MediaStore 写入 `Pictures/<album>`；Android 9 及以下使用公开图片目录 fallback。
- 保持 token 鉴权：缺失或错误 token 返回 401；伪图片会被拒绝。

Lumi 新增：
- 新增图片上传 CLI；当前文件名以 `scripts/openclaw-image-phone.mjs` 为准。
- 新增 `npm run phone:image`。
- 支持两种模式：根据 prompt 调 OpenAI-compatible `/v1/images/generations` 生图后上传；或直接上传本地已有图片。
- 生成结果默认保存到 `data/generated-images/`，并上传到手机 `Pictures/Lumi`。
- 支持环境变量 `LUMI_IMAGE_BASE_URL`、`LUMI_IMAGE_API_KEY`、`LUMI_IMAGE_MODEL`、`LUMI_PHONE_BASE_URL`、`LUMI_PHONE_TOKEN`。
- 新增文档 `docs/CLI_IMAGE_TO_PHONE.md`。
- `.gitignore` 已排除 `imgapi_config.json`、`video_config.json`、`data/generated-images/`，避免密钥和生成素材误提交。

版本管理：
- APKClaw 已单独建仓：`https://github.com/rfdiosuao/lumiapkclaw`。
- 主分支为 `main`，当前提交包含 v6.11 图片导入能力。
- GitHub Actions CI 已验证通过。

构建与真机验收：
```text
:app:assembleDebug => PASS
GitHub Actions CI => PASS
node --check scripts\openclaw-image-phone.mjs => PASS
npm run phone:image -- --help => PASS
npm run build => PASS

GET /api/device/status
version=6.11, versionCode=710, agentInitialized=true

POST /api/media/import_image
上传：lumi_import_test_20260510_200000.png
返回：Pictures/Lumi/lumi_import_test_20260510_200000.png
contentUri=content://media/external/images/media/1000082764

无 token / 错 token
返回：401

伪图片 README.md
返回：Unsupported or invalid image

npm run phone:image -- --image .\logo_256.png --phone-url http://192.168.1.137:9527 --phone-token 66666666 --filename lumi-cli-upload-test.png --json
返回：Pictures/Lumi/lumi-cli-upload-test.png
```

后续欠债：
- `scripts/verify-phone-agent.ps1` 还需要把 `/api/media/import_image` 纳入自动验收。
- Lumi AI 生图 UI 还没有按钮直接调用 `phone:image` 或同等服务能力发送到手机相册。
- 交付包还需要整理：最新 APK、变更说明、安装说明、验收说明、回滚说明。

2026-05-11 同步说明：
- v6.11 记录的是早期原生 multipart 路由；当前 Lumi/OpenClaw 产品通道应使用 `POST /api/lumi/media/import_image`。
- 当前启动器侧实际请求为 JSON `dataUrl`，由安全通道保护；旧 `POST /api/media/import_image` 只作为历史/原生兼容能力看待。
- 最新契约以 `PHONE_CONNECTOR_API_CONTRACT.md` 第 9 节为准。
