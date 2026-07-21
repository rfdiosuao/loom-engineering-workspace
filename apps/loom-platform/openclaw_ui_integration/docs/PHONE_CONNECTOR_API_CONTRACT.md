# Phone Connector API Contract

> 更新时间：2026-05-11
> 用途：定义 Lumi 桌面端对接 APKClaw 手机端的 API 契约，覆盖连接、截图、低层动作、Agent 任务、设备画像和图片导入手机相册。

## 1. 当前 APKClaw 事实

源码位置：

```text
D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction
```

当前手机端实现：

- HTTP server：NanoHTTPD。
- 默认端口：`9527`。
- 当前验收版本：`versionName=6.26` / `versionCode=860`。
- Server 文件：`app/src/main/java/com/apk/claw/android/server/ConfigServer.kt`。
- Tool API：`ToolApiController.kt`。
- Agent API：`AgentApiController.kt`。
- Media API：`MediaApiController.kt`。
- Token 校验：`TokenValidator.kt`。

当前已存在的可用接口：

- `GET /api/device/status`
- `POST /api/device/wake`
- `GET /api/lumi/device/profile`
- `GET /api/agent/status`
- `POST /api/lumi/agent/execute_task`
- `POST /api/lumi/agent/cancel_task`
- `GET /api/tool/screenshot`
- `POST /api/tool/tap`
- `POST /api/tool/swipe`
- `POST /api/tool/drag`
- `POST /api/tool/long_press`
- `GET /api/tool/get_screen_info`
- `GET /api/tool/screen_tree`
- `POST /api/tool/input_text`
- `POST /api/tool/system_key`
- `POST /api/tool/open_app`
- `POST /api/overlay/cursor`
- `POST /api/overlay/cursor/preview`
- `POST /api/lumi/media/import_image`

当前鉴权 Header：

```text
X-AGENT-PHONE-TOKEN: <token>
```

兼容旧 Header：

```text
X-APKCLAW-TOKEN: <token>
```

Lumi 新接入统一使用 `X-AGENT-PHONE-TOKEN`。

## 2. Lumi 端连接配置

Lumi 需要保存一组最小配置：

```json
{
  "name": "My Android Phone",
  "baseUrl": "http://192.168.1.100:9527",
  "token": "your-token"
}
```

规则：

- `baseUrl` 必须包含协议。
- 默认端口是 `9527`。
- 末尾 `/` 在保存时去掉。
- Token 只用于请求 Header，不写入日志明文。
- MVP 先支持单设备，数据结构预留多设备。

## 3. 统一响应模型

APKClaw 当前多数 API 返回：

```json
{
  "success": true,
  "data": "...",
  "error": null
}
```

Lumi `phoneApi` 内部统一转换成：

```ts
interface PhoneApiResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
  raw?: unknown;
}
```

转换规则：

- `success === true` -> `ok: true`
- `success === false` -> `ok: false`
- HTTP `401` -> `ok: false`, `error: "unauthorized"`
- 网络失败 -> `ok: false`, `error: "network_error"`
- JSON 解析失败 -> `ok: false`, `error: "invalid_response"`

## 4. 状态接口

### MVP 使用现有接口

```text
GET /api/agent/status
```

Header：

```text
X-AGENT-PHONE-TOKEN: <token>
```

当前 APKClaw 返回的 `data` 是 JSON 字符串，内容类似：

```json
{
  "taskRunning": false,
  "agentInitialized": true,
  "llmConfigured": true,
  "accessibilityRunning": true
}
```

Lumi 端规范化为：

```ts
interface PhoneStatus {
  online: boolean;
  taskRunning: boolean;
  agentInitialized: boolean;
  llmConfigured: boolean;
  accessibilityRunning: boolean;
  screenshotSupported?: boolean;
  version?: string;
}
```

### 当前推荐接口

```text
GET /api/device/status
```

返回示例：

```json
{
  "success": true,
  "data": {
    "version": "6.26",
    "versionCode": 860,
    "taskRunning": false,
    "agentInitialized": false,
    "llmConfigured": true,
    "accessibilityRunning": true,
    "screenshotSupported": true,
    "screenInfoSupported": true,
    "overlayPermission": true,
    "cursorPreviewSupported": true,
    "screenOn": true,
    "interactive": true,
    "keyguardLocked": false,
    "deviceLocked": false,
    "serverPort": 9527
  }
}
```

Lumi 应优先调用 `/api/device/status`；只有兼容旧包时才回退到 `/api/agent/status`。

## 4.5. Device Profile Hints

`GET /api/lumi/device/profile` is the best initialization probe. In addition to the device facts and app list, it now returns a `currentScreen` summary with node counts and a `vision` hint object. The launcher uses this for initialization health checks and for deciding whether to prompt OpenClaw to use the visual fallback path.

Example shape:

```json
{
  "currentScreen": {
    "accessibilityAvailable": true,
    "packageName": "com.tencent.nrc",
    "title": "洛克王国：世界",
    "screenWidth": 1280,
    "screenHeight": 2772,
    "nodeCount": 3,
    "textNodeCount": 1,
    "clickableNodeCount": 2,
    "imageNodeCount": 4
  },
  "vision": {
    "recommended": true,
    "mode": "vision",
    "reason": "game_package",
    "confidence": 0.96
  }
}
```

Use this hint on the launcher side:
- if `vision.recommended=true`, first send APKClaw Agent a clearer game/vision-oriented task instead of forcing more accessibility-tree scraping;
- if `currentScreen.nodeCount` is `0` or very low, show a visual fallback prompt in the launcher so the next task asks APKClaw to observe the screenshot, visible buttons, and safe action candidates;
- use screenshot/OCR/VLM workflows to diagnose and improve the next APKClaw instruction when APKClaw returns empty or low-confidence results;
- use direct visual coordinate actions only for debugging, explicit coordinate tasks, or fallback after repeated APKClaw failure;
- if `vision.mode=accessibility`, keep using accessibility-tree tools first.

## 4.6. Game / Vision Mode

Game mode is a signed launcher-only visual workflow for screens where accessibility nodes are missing, sparse, or not semantically useful. It is a diagnostic and fallback layer around APKClaw Agent, not the default control loop.

Default product loop:

```text
npm run phone:game -- run
  -> APKClaw Agent probe
  -> signed vision frame
  -> OpenClaw visual plan with action + targetLabel + reason
  -> launcher safety guard
  -> APKClaw Agent safe_action execution
  -> after-frame verification
```

```text
GET  /api/lumi/vision/status
GET  /api/lumi/vision/frame?overlayGrid=true&format=jpeg&maxLongSide=1600
POST /api/lumi/vision/action
```

`vision/frame` returns:

- screenshot image as base64 JPEG/PNG;
- optional grid overlay, default `6 x 12`;
- `coordinateSpace` with image-to-screen scaling;
- current screen counters and vision hints.

`vision/action` supports direct fallback/debug actions:

- `tap`
- `long_press`
- `swipe`
- `drag`

Coordinates can be sent as screen pixels, normalized `nx/ny`, image coordinates with `imageWidth/imageHeight`, nested `start`/`end` points, or grid cells such as `C7`.

For mutating visual actions, include `targetLabel` and `reason`. Launcher and phone-side guards block obvious sensitive targets such as login, authorization, payment, purchase, recharge, account binding, real-name verification, delete, clear-cache, upload-log, log-out, and exit-game targets.

## 5. 截图接口

```text
GET /api/tool/screenshot
```

Header：

```text
X-AGENT-PHONE-TOKEN: <token>
```

当前返回：

```json
{
  "success": true,
  "data": "<base64 png>",
  "error": null
}
```

Lumi 端规范化为：

```ts
interface PhoneScreenshot {
  mime: "image/png";
  base64: string;
  dataUrl: string;
  capturedAt: string;
  width?: number;
  height?: number;
}
```

MVP 显示方式：

```text
data:image/png;base64,<base64>
```

后续建议 APKClaw 返回宽高：

```json
{
  "success": true,
  "data": {
    "mime": "image/png",
    "base64": "...",
    "width": 1080,
    "height": 2400,
    "orientation": "portrait"
  }
}
```

MVP 里如果后端没有宽高，Lumi 可从 `<img>` 加载完成后的 `naturalWidth` / `naturalHeight` 读取。

## 6. 点击接口

```text
POST /api/tool/tap
```

Header：

```text
Content-Type: application/json
X-AGENT-PHONE-TOKEN: <token>
```

请求：

```json
{
  "x": 512,
  "y": 1360
}
```

当前返回：

```json
{
  "success": true,
  "data": "...",
  "error": null
}
```

Lumi 端请求模型：

```ts
interface PhoneTapRequest {
  x: number;
  y: number;
  traceId?: string;
  visualize?: boolean;
}
```

MVP 只发送 `x` 和 `y`。`traceId` 和 `visualize` 先保留在 Lumi 内部，等待 APKClaw AI Cursor Overlay 支持。

## 7. 坐标换算

Lumi 截图预览区域坐标转换为手机真实坐标：

```text
phoneX = previewX / renderedImageWidth * naturalImageWidth
phoneY = previewY / renderedImageHeight * naturalImageHeight
```

要求：

- 使用图片真实渲染区域，不使用外层容器尺寸。
- 结果四舍五入为整数。
- 坐标最小值为 `0`。
- 坐标最大值不超过图片宽高。
- 点击后自动刷新截图。

## 8. Agent 自然语言任务

```text
POST /api/lumi/agent/execute_task
```

请求：

```json
{
  "prompt": "打开微信",
  "use_template": true,
  "force_agent": false,
  "tool_policy": "safe_action",
  "template_params": {}
}
```

推荐策略：

- `observe_only`：只观察，不改变手机状态。
- `safe_action`：允许常规 UI 操作，禁止敏感文件/剪贴板等能力。
- `full_access`：完整工具权限，仅用于明确授权任务。

## 9. 图片导入手机相册

```text
POST /api/lumi/media/import_image
```

Header：

```text
X-AGENT-PHONE-TOKEN: <token>
```

当前 Lumi / OpenClaw 安全通道请求类型：

```text
application/json; charset=utf-8
```

请求体：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `dataUrl` | 是 | `data:image/png;base64,...`、`data:image/jpeg;base64,...` 或 `data:image/webp;base64,...` |
| `album` | 否 | 手机相册目录名，启动器/CLI 默认 `OpenClaw`，可按发行主题改为 `Lumi` 或其他名称 |
| `filename` | 否 | 保存到手机端的文件名 |

请求示例：

```powershell
$dataUrl = "data:image/png;base64," + [Convert]::ToBase64String([IO.File]::ReadAllBytes("D:/images/lumi-output.png"))
$body = @{
  dataUrl = $dataUrl
  album = "OpenClaw"
  filename = "lumi-output.png"
} | ConvertTo-Json -Compress

curl.exe -X POST "http://192.168.1.137:9527/api/lumi/media/import_image" `
  -H "X-AGENT-PHONE-TOKEN: 66666666" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary $body
```

成功返回：

```json
{
  "success": true,
  "data": {
    "album": "OpenClaw",
    "filename": "lumi-output.png",
    "mimeType": "image/png",
    "uri": "content://media/external/images/media/1000082764",
    "relativePath": "Pictures/OpenClaw/lumi-output.png",
    "path": "",
    "sizeBytes": 9555,
    "width": 512,
    "height": 512
  }
}
```

边界：

- 单文件最大 32 MB。
- 只接受真实可解码的 `image/png`、`image/jpeg`、`image/webp`。
- 无 Token 或错误 Token 必须返回 `401`。
- 伪装图片必须返回 `success=false`，错误信息类似 `Unsupported or invalid image`。
- 旧的 `POST /api/media/import_image` multipart 路由属于 APKClaw 原生兼容/历史能力；当前产品构建里高级导入能力应走 `/api/lumi/media/import_image`，并由启动器安全通道签名。

Lumi CLI 已接入：

```powershell
npm run phone:image -- --image .\logo_256.png --phone-url http://192.168.1.137:9527 --phone-token 66666666
```

## 10. 安全边界

MVP 必须做到：

- Token 不在 UI 日志中明文输出。
- 连接失败不泄露 Token。
- 默认只连接用户手动输入的局域网地址。
- 不自动扫描局域网。
- 不自动执行敏感动作。

后续必须补：

- 手机端配对确认。
- 敏感操作二次确认。
- 任务暂停和终止。
- 操作 trace。
- 日志脱敏。

## 11. 当前验收

第一轮只验收这 5 件事：

- [x] Lumi 能保存手机地址和 Token。
- [x] Lumi 点击连接后能调用 `/api/device/status`。
- [x] Lumi 能显示在线、无障碍、LLM、任务运行状态。
- [x] Lumi 能调用 `/api/tool/screenshot` 并显示手机截图。
- [x] Lumi 点击截图能换算坐标并调用 `/api/tool/tap`。
- [x] Lumi 能调用 `/api/lumi/agent/execute_task` 让 APKClaw 内部 Agent 主控手机任务。
- [x] Lumi 能调用 `/api/lumi/device/profile` 做初始化体检。
- [x] Lumi CLI 能调用 `/api/lumi/media/import_image` 把 PC 图片导入手机相册。

不在第一轮做：

- WebRTC。
- 多设备并发。
- Workflow template 市场。
- USB / ADB 通道。

## OpenClaw Runtime Token And Task Budget Addendum

OpenClaw itself must not hardcode or ask for the APKClaw token when the launcher has already saved it.

- Launcher private config path: `data/.openclaw/launcher/phone-agent.json`.
- `runtime-context.json` only exposes `phone.baseUrl`, `phone.tokenAvailable`, and `phone.configPath`; it never exposes the raw token.
- Bundled CLI helpers (`npm run phone:vision`, `npm run phone:game`, `npm run phone:video`, `npm run phone:image`) read the launcher private config automatically.
- Normal OpenClaw commands should omit `--phone-token`; pass it only for manual debugging.
- If `phone.tokenAvailable=true` but a helper reports missing token, the user should save/test the Phone Control config once so the launcher writes the private config file.

APKClaw Agent has a hard per-task budget of 60 rounds.

- OpenClaw should split long phone goals into bounded stages.
- Product/job/feed collection tasks should request one bounded batch, then return results to OpenClaw.
- If APKClaw returns partial results, `needs_vision`, `needs_followup`, timeout, or low confidence, OpenClaw should treat that as a handoff point and send a follow-up task instead of asking APKClaw to loop indefinitely.
- Preferred task endpoint for new APKClaw: `POST /api/lumi/agent/tasks`; legacy fallback: `POST /api/lumi/agent/execute_task`.
