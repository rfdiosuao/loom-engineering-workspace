# 更新日志

## v6.53 - 2026-07-14

### Node-aware Agent Taps
- Revalidated Agent coordinate taps against the live accessibility tree immediately before execution.
- Preferred the smallest visible, enabled clickable node under the requested point, including clickable parents around text labels.
- Kept exact coordinate behavior as a fallback for canvases, games, visual actions, and fixed RPA workflows.
- Applied the same live-node targeting to `click_ref` while preserving existing action and security contracts.

### Changes
- Android version updated to `6.53-stability`, versionCode updated to `922`.

## v6.52 - 2026-07-14

### Sequential Agent Progress And Tool Calls
- Kept each round's thinking event and real tool call as separate chronological log entries.
- Deduplicated repeated progress callbacks without hiding the tool that APKClaw actually invoked.
- Assigned every visible progress event its own increasing stage number and labeled tool calls explicitly.

### Changes
- Android version updated to `6.52-stability`, versionCode updated to `921`.

## v6.51 - 2026-07-14

### One Log Line Per Agent Stage
- Merged each round's transient thinking line into its subsequent real tool action.
- A stage now occupies one recent-log line, followed by one separate terminal completion or error line.

### Changes
- Android version updated to `6.51-stability`, versionCode updated to `920`.

## v6.50 - 2026-07-14

### Persistent Human-readable Task Log
- Kept the latest three real Agent progress steps visible after the five-second terminal animation resets.
- Connected the home-screen task log to the same HTTP Agent progress history used by the floating panel.
- Made floating progress strings follow Android per-app language settings, including Chinese on an English-system emulator.

### Changes
- Android version updated to `6.50-stability`, versionCode updated to `919`.

## v6.49 - 2026-07-14

### Human-readable Floating Progress
- Replaced internal `status/round/mode/action/target` tokens with plain-language task progress.
- The floating panel now translates live Agent tool calls such as opening an app, reading the screen, entering text, swiping, taking a screenshot, and preparing the final result.
- The home-screen task log now uses readable Agent/RPA sentences for source, progress, current action, elapsed time, completion, and errors instead of wire-protocol fields.
- Kept the full structured task events for diagnostics while presenting concise user-facing progress on the phone.

### Changes
- Android version updated to `6.49-stability`, versionCode updated to `918`.

## v6.48 - 2026-07-14

### Floating Overlay Drag
- Fixed the interactive floating overlay remaining immovable because EasyFloat drag handling was disabled.
- The Settings switch now enables both click and drag; safe mode still passes all touches through.

### Changes
- Android version updated to `6.48-stability`, versionCode updated to `917`.

## v6.47 - 2026-07-14

### Floating Log Interaction
- Added a persistent "floating overlay clickable" switch to Settings.
- Click mode immediately makes the live-log overlay touchable so it can expand or collapse; disabling it restores touch passthrough to prevent Agent mis-taps.
- Click mode is disabled by default and survives app/process restarts.

### Changes
- Android version updated to `6.47-stability`, versionCode updated to `916`.

## v6.31 - 2026-07-02

### Control Plane Recovery
- Fixed a foreground-service restart regression: ConfigServer auto-restore now runs whenever the foreground service restarts and is no longer gated by LLM configuration.
- This keeps fast-path/status/metrics phone control routes recoverable after task completion or system service restart, even for template/fast-action devices without model config.

### Changes
- Android version updated to `6.31-stability`, versionCode updated to `900`.

## v6.30 - 2026-07-01

### Long-Running Stability Diagnostics
- Split Accessibility status into Android Settings enabled state and current process-bound state.
- Added `accessibilityMasterEnabled`, `accessibilityListedInSettings`, `accessibilityEnabledInSettings`, `accessibilityBound`, `accessibilityStale`, `accessibilityHealthy`, and `accessibilityState` to status/profile/error payloads while keeping the old `accessibilityRunning` field.
- Home permission card now shows a reconnect-needed state when Android Settings still has Accessibility enabled but APKClaw has not been rebound after process death.
- Added unit coverage for parsing `Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES` component formats.

### Changes
- Android version updated to `6.30-stability`, versionCode updated to `890`.

## v6.29 - 2026-07-01

### Long-Running Stability
- Fixed foreground keep-alive startup so Android 13+ notification permission denial no longer prevents the persistent foreground service from starting.
- Restart alarms now use foreground-service pending intents on Android 8+ to reduce background-start failures after the service is killed.
- KeepAlive job is now scheduled from app startup, foreground-service startup, and boot receiver paths.
- Foreground service restarts after system destruction unless explicitly stopped by the user.
- ConfigServer auto-restore no longer depends on LLM configuration, so phone control APIs can recover for fast-path/status/metrics use even when model config is missing.

### Changes
- Android version updated to `6.29-hotspot`, versionCode updated to `880`.

## v6.28 - 2026-07-01

### APKClaw Speed / Observability
- Added queued async Agent task scheduling with visible queue depth, queue position, queue wait time, current task id, priority, and cancellable task states.
- Added read-only runtime metrics endpoints for task count, success/failure/busy counts, queue depth, average latency, average rounds, cache hit rate, template hit rate, Agent fallback rate, mode counts, and sanitized recent errors.
- Added structured template fallback metrics including fallback reason, template hit, and Agent fallback markers.
- Added LOOM bridge compatibility for phone runtime metrics and queue fields without changing the main LOOM UI or Lumi signing semantics.

### Changes
- Android version updated to `6.28-hotspot`, versionCode updated to `870`.

## v6.26 - 2026-05-11

### Game / Vision Safety
- Added phone-side safety metadata for `/api/lumi/vision/status` and `/api/lumi/vision/frame`.
- Added a safety guard for `/api/lumi/vision/action`; visual actions with labels/reasons that mention login, authorization, payment, purchase, recharge, account binding, delete, clear-cache, upload-log, log-out, or exit-game flows are blocked.
- Blocked direct visual coordinate actions in common sensitive apps such as WeChat, QQ, Alipay, contacts, messages, files, and gallery unless explicitly allowed for package-level debugging.
- Added an APKClaw Agent safe-action tap guard for visible accessibility nodes with sensitive labels, preventing accidental taps on payment/login/destructive controls.
- Updated the Agent prompt so game/vision guidance remains one safe action at a time and reports blocked actions instead of guessing.

### Changes
- Android version updated to `6.26`, versionCode updated to `860`.

## v6.25 - 2026-05-11

### Agent Policy
- Tightened `observe_only` current-screen tasks so APKClaw exposes only `get_screen_info` and `finish`.
- Prevented simple read-only screen summaries from drifting into installed-app inventory or generic tool explanations.

### Changes
- Android version updated to `6.25`, versionCode updated to `850`.

## v6.24 - 2026-05-11

### Stability
- Added serialized screenshot capture with a short cooldown, retry, and recent-frame cache.
- Improved high-frequency `/api/tool/screenshot` and `/api/lumi/vision/frame` stability during OpenClaw pressure tests.

### Changes
- Android version updated to `6.24`, versionCode updated to `840`.

## v6.23 - 2026-05-11

### Agent Collaboration Policy
- Clarified the phone-side Agent role: OpenClaw is the commander, APKClaw is the Android-side executor.
- Added game/vision fallback behavior to the APKClaw Agent prompt: if a game/canvas/image-heavy screen exposes too little accessibility structure, stop blind loops and finish with a `needs_vision:` summary.
- Added support for OpenClaw visual guidance in the prompt: when OpenClaw provides a grid cell, target area, normalized coordinate, or exact coordinate, APKClaw should execute it as the phone-side executor and report the result.

### Changes
- Android version updated to `6.23`, versionCode updated to `830`.

## v6.22 - 2026-05-11

### Game / Vision Mode
- Added signed launcher-only game mode APIs under `/api/lumi/vision/*`.
- Added `GET /api/lumi/vision/status` for current screen vision hints and input contract.
- Added `GET /api/lumi/vision/frame` to return a screenshot frame with optional grid overlay, image-to-screen coordinate mapping, and current UI/vision hints.
- Added `POST /api/lumi/vision/action` for visual coordinate actions: `tap`, `long_press`, `swipe`, and `drag`.
- Vision actions accept screen pixels, normalized coordinates, image coordinates, nested `start`/`end` points, or grid cells like `C7`.

### Changes
- Android version updated to `6.22`, versionCode updated to `820`.

## v6.21 - 2026-05-11

### Security
- Added the Lumi launcher secure channel under `/api/lumi/*`.
- Added launcher pairing at `POST /api/lumi/security/pair`, returning a per-device launcher secret.
- Added HMAC-SHA256 request signing with launcher id, timestamp, nonce, and SHA-256 body hash.
- Added nonce replay protection and timestamp drift checks for launcher-only APIs.

### Changes
- Agent execution, device profile, media import/recording, video list/download, and collector APIs are now launcher-only advanced capabilities. Use signed `/api/lumi/*` routes for these operations.
- Added signed JSON image import at `POST /api/lumi/media/import_image`.
- Android version updated to `6.21`, versionCode updated to `810`.

## v6.20 - 2026-05-11

### 修复
- 修复 `/api/device/profile` 在部分节点字段为 JSON null 时返回 500 的问题，初始化体检和视觉提示可以稳定读取空文本、空描述、空包名节点。

### 变更
- Android 版本更新为 `6.20`，`versionCode` 更新为 `800`。

## v6.19 - 2026-05-11

### 新功能
- `/api/device/profile` 新增顶层 `vision` 提示，返回当前屏幕的节点计数、推荐模式、原因和置信度，方便 OpenClaw 在游戏、纯图或低节点页面自动切到视觉流程。
### 改进
- `currentScreen.packageName` 改为优先使用真实前台包名，再回退到树节点包名，减少空树或多包名场景下的误判。
- Android 版本更新为 `6.19`，`versionCode` 更新为 `790`。

## v6.18 - 2026-05-11

### 新功能
- `collect_list_items` 新增 `target=product`，用于京东、淘宝、闲鱼等商品搜索结果页的商品卡片采集。

### 改进
- 商品采集改为以价格节点锚定商品卡片，再向上寻找商品标题，降低“筛选栏、优惠券、加购物车、排序标签”等页面控件被误采为商品的概率。
- Agent 提示词补充采集参数规则：岗位用 `target=job`，商品用 `target=product`，其他列表用 `target=generic`。
- Android 版本更新为 `6.18`，`versionCode` 更新为 `780`。

## v6.17 - 2026-05-11

### 修复
- `safe_action` 策略现在允许 `collect_list_items`，让 OpenClaw 指挥手机端 Agent 做岗位、商品、评论、搜索结果等列表采集时，可以调用结构化采集器，而不是手动循环 `get_screen_info + swipe`。

### 变更
- Agent 系统提示新增采集规则：列表采集类任务优先使用 `collect_list_items`。
- Agent 历史上下文对 `collect_list_items` 结果做占位压缩，避免长列表撑爆上下文。
- Android 版本更新为 `6.17`，`versionCode` 更新为 `770`。

## v6.13 - 2026-05-10

### 修复
- 优化岗位采集器启发式：避免将 BOSS 底部导航“有了”等短标签误判为公司名，并扩大岗位卡片下方解析窗口以提高地点识别率。

### 变更
- Android 版本号更新为 `6.13`，`versionCode` 更新为 `730`。

## v6.12 - 2026-05-10

### 新功能
- 新增 APKClaw Collector 列表采集内核，支持从当前可滚动列表中自动读屏、滑动、解析、去重并返回结构化条目。
- 新增 `POST /api/collect/list`，第一版支持 `job` 岗位列表和 `generic` 通用列表，采集不足时也会返回已采集的 partial 结果。
- 新增 Agent 工具 `collect_list_items`，用于让手机端 Agent 在“采集/筛选/列出 N 个岗位、商品、评论或列表项”场景下优先调用确定性采集器。

### 变更
- Android 版本号更新为 `6.12`，`versionCode` 更新为 `720`。

## v6.11 - 2026-05-10

### 新功能
- 新增 `POST /api/media/import_image`，支持 PC / Lumi 启动器上传 PNG、JPEG、WebP 图片到手机相册。
- Android 10+ 通过 `MediaStore` 写入 `Pictures/Lumi`，Android 9 兼容传统外部存储目录并触发媒体扫描。
- 上传接口沿用 API Token 认证，限制单文件最大 32 MB，并校验真实图片类型。

### 变更
- Android 版本号更新为 `6.11`，`versionCode` 更新为 `710`。

## v6.10 - 2026-05-10

### 新功能
- APK 设置页新增“显示 / 悬浮球大小”，支持小、中、大三档，默认“大”保持旧尺寸。
- 悬浮球尺寸设置会持久化保存，并在当前悬浮球显示时即时刷新。

### 变更
- Android 版本号更新为 `6.10`，`versionCode` 更新为 `700`。

## v6.9 - 2026-05-10

### 变更
- APKClaw 视觉升级为 Lumi Agent Phone 蓝黑皮肤：更新 launcher icon、splash logo、悬浮球、悬浮指针和 Web 配置页主色。
- 悬浮球运行态改为 Lumi cyan/gold 指针，提高真机上的可见性和品牌一致性。
- Android 版本号更新为 `6.9`，`versionCode` 更新为 `690`。

## v6.8 - 2026-05-10

### 新功能
- `/api/device/status` 新增 `screenOn`、`interactive`、`keyguardLocked`、`deviceLocked`，用于 Lumi 判断手机是否息屏或锁屏。
- 新增 `POST /api/device/wake`，在任务开始前尝试点亮息屏手机；如果设备仍处于锁屏状态，会返回明确状态，不绕过安全锁。

### 变更
- Android 版本号更新为 `6.8`，`versionCode` 更新为 `680`。

## v6.7 - 2026-05-10

### 修复
- 修复 `/api/agent/execute_task` 等 JSON POST 接口读取中文任务时可能被 NanoHTTPD `parseBody()` 解码成乱码的问题；现在优先按原始请求体字节读取并使用 UTF-8 解码。
- Lumi 侧请求头补充 `charset=utf-8`，让浏览器、脚本和手机端编码约定保持一致。

### 变更
- Android 版本号更新为 `6.7`，`versionCode` 更新为 `670`。

## v6.6 - 2026-05-10

### 变更
- 首页改为 Lumi Agent Phone 设备就绪面板，集中展示 5 项权限、LAN 端口和当前版本。
- 权限卡片从开关样式改为状态徽标，减少“可手动切开关”的误解。
- AI 执行动作时的悬浮指针改为高对比黄色准星，显示 TAP / HOLD / SWIPE / DRAG 动作标签。
- Android 版本号更新为 `6.6`，`versionCode` 更新为 `660`。

## v6.5 - 2026-05-10

### 变更
- 网页浏览、URL 打开、APK 下载和浏览器搜索类任务优先使用 Via 浏览器（`mark.via` / `mark.via.gp`），Via 不可用或失败后再使用 Chrome。
- `GET /api/device/profile` 和 `get_installed_apps` 的应用列表把 Via 浏览器排到最前面，减少 Agent 误选 Chrome 的概率。
- Android 版本号更新为 `6.5`，`versionCode` 更新为 `650`。

## v6.4 - 2026-05-10

### 新功能
- 新增 `drag` Agent 工具和 `POST /api/tool/drag`，支持“按住起点 -> 拖到终点”的真实无障碍手势。
- `safe_action` 工具策略允许 `drag`，用于滑块、地图拖动、拖拽排序、长按移动图标等场景；普通滚屏仍建议使用 `swipe`。
- Lumi 手机控制页新增“拖拽”和“截图拖拽”调试入口：可一键中心拖拽，也可在截图上依次点选起点和终点。

### 变更
- 链式启动拦截弹窗优先选择“本次允许/仅本次允许”等一次性授权，避免误点“始终允许”。
- `safe_action` 下增加 tap 防护：若模型仍点向“始终允许”按钮，会自动改写到同屏的“本次允许”按钮。
- Android 版本号更新为 `6.4`，`versionCode` 更新为 `640`。

## v6.3 - 2026-05-10

### 新功能
- `/api/agent/execute_task` 新增 `tool_policy` / `toolPolicy`，支持 `observe_only`、`safe_action`、`full_access` 三档任务模式。
- `observe_only` 继承严格只读边界，只允许屏幕、结构树、应用列表、等待和结束类工具。
- `safe_action` 允许 UI 操作类工具：打开应用、点击、长按、滑动、滚动查找、输入文本和系统按键；继续禁止剪贴板、文件发送、定时任务和主动建议处理。

### 变更
- 受限策略下不走模板匹配，也不在任务开始前自动回到桌面，避免观察/安全操作任务出现额外状态变化。
- API 执行结果新增 `toolPolicy` 字段，方便 Lumi 显示、复制轨迹和验收。
- Android 版本号更新为 `6.3`，`versionCode` 更新为 `630`。

## v6.2 - 2026-05-10

### 新功能
- 新增严格只读模式：`/api/agent/execute_task` 支持 `read_only` / `readOnly`。
- 只读模式下 Agent 只允许观察类工具：`get_screen_info`、`take_screenshot`、`find_node_info`、`get_installed_apps`、`wait`、`finish`。
- 只读模式下模型即使请求点击、滑动、输入、打开应用等动作工具，手机端也会阻断真实执行。

### 变更
- 只读模式不再在任务开始前自动 `pressHome()`，避免观察任务改变当前手机状态。
- API 执行结果新增 `readOnly` 字段，方便 Lumi 复盘和验收。
- Android 版本号更新为 `6.2`，`versionCode` 更新为 `620`。

## v6.1 - 2026-04-25

### 修复
- 修复流程模板学习时把联系人、消息、搜索词写死的问题，改为提取 `${contact_name}`、`${message}`、`${keyword}` 等占位符。
- 修复模板命中后缺少必要参数时仍继续执行的问题；现在会回退到 Agent 重新规划，避免复用旧联系人或旧消息。
- 修复历史模板中保存了“点击”“输入文本”等展示名导致执行时找不到工具的问题；旧模板命中时会自动迁移为内部工具名。
- 修复模板 fallback 步骤没有复用已解析参数的问题。

### 变更
- 项目对外名称统一为 `Agent Phone`，包括应用名、通知、Web 配置页、README 与 Skills 文档。
- API 推荐认证头更新为 `X-AGENT-PHONE-TOKEN`，同时保留旧版 `X-APKCLAW-TOKEN` 兼容。
- Android 版本号更新为 `6.1`，`versionCode` 更新为 `610`。

## v6 - 2026-04-12

### 新功能
- 新增流程固化系统，成功流程可自动保存为模板，下次执行相似任务时优先复用模板。

### 变更
- 移除记忆系统，简化任务执行上下文，降低任务间干扰。

### 修复
- 修复中文关键词匹配问题。

## v1.0.1 - 2026-04-12

### 修复
- 修复 Agent API 执行任务时悬浮窗状态不同步的问题。
- 修复 HTTP API 中文请求编码问题。

## v1.0.0 - 2026-04-12

### 新功能
- 新增 Hermes Skills，支持通过 Hermes Agent 远程控制 Android 设备。
