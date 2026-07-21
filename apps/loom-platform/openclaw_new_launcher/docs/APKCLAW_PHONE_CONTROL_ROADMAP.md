# APKClaw 手机控制路线图

> 更新时间：2026-05-10
> 目标：让 Lumi 桌面启动器原生支持连接手机端 APKClaw，并通过截图、多模态理解、可视化 AI 指针和动作闭环，实现丝滑的 AI 手机控制体验。

## 1. 产品愿景

Lumi 不只做桌面启动器，而是升级为“桌面 AI 控制中枢”。

APKClaw 运行在 Android 手机上，负责真实设备操作：

- 截图。
- 获取 UI 树。
- 点击、滑动、长按、输入。
- 打开 App。
- 执行自然语言任务。
- 记录动作结果。

OpenClaw / Lumi 运行在电脑上，负责大脑和控制台：

- 看手机截图。
- 理解当前界面。
- 规划下一步动作。
- 通过 APKClaw 下发操作。
- 观察操作结果。
- 将成功流程固化成模板。

最终体验：

```text
用户在电脑上说一句话
  -> Lumi 截取手机画面
  -> OpenClaw 理解屏幕
  -> APKClaw 显示 AI 指针并执行操作
  -> Lumi 继续观察和纠错
  -> 手机任务完成
```

## 2. 总体架构

```text
Lumi Desktop Launcher
  |
  | Phone Connector
  v
OpenClaw Orchestrator
  |
  | screenshots + UI tree + action plan
  v
APKClaw HTTP API
  |
  | AccessibilityService / MediaProjection / Overlay
  v
Android Apps
```

建议职责边界：

- Lumi：连接管理、投屏预览、配置、日志、人工接管。
- OpenClaw：多模态分析、动作规划、任务循环、模板复用。
- APKClaw：截图、UI 树、动作执行、AI 指针层、设备状态。

## 3. 核心概念

### Phone Connector

桌面端的手机连接模块。

负责：

- 保存手机地址。
- 保存 Token。
- 检查 APKClaw 状态。
- 获取截图和 UI 树。
- 发送动作命令。
- 展示执行日志。

### AI Cursor Overlay

手机端的可视化 AI 指针层。

它不是给用户手动点击的鼠标，而是让 AI 的动作变得可观察。

价值：

- OpenClaw 截屏时能看到 AI 准备点哪里。
- 用户能看到 AI 的操作意图。
- 开发时能快速发现坐标换算和误触问题。
- 投屏演示时会更有“AI 正在操作手机”的感觉。

### Visual Action Loop

视觉动作闭环。

```text
截图
  -> 多模态识别
  -> 规划动作
  -> 显示指针
  -> 执行动作
  -> 再截图
  -> 判断是否成功
```

这个闭环是“丝滑控制”的核心。

### Workflow Template

成功完成一次任务后，把步骤固化成模板。

第一次靠 AI 看图规划。

第二次类似任务直接匹配模板、替换参数、快速执行。

## 4. 阶段路线

## P0：先接通手机

目标：Lumi 能连接 APKClaw，能看见手机，能下发基础命令。

### 桌面端任务

- [ ] 新增“手机控制”页面。
- [ ] 支持配置 APKClaw 地址，例如 `http://192.168.x.x:9527`。
- [ ] 支持配置 Token。
- [ ] 支持保存多个手机设备。
- [ ] 支持连接测试。
- [ ] 展示手机在线/离线状态。
- [ ] 展示 APKClaw 版本。
- [ ] 展示无障碍服务状态。
- [ ] 展示截图能力状态。
- [ ] 展示当前任务执行状态。

### 手机端 API 任务

- [ ] 统一鉴权 Header 名称。
- [ ] 提供 `/api/device/status`。
- [ ] 提供 `/api/tool/screenshot`。
- [ ] 提供 `/api/tool/ui-tree`。
- [ ] 提供 `/api/tool/tap`。
- [ ] 提供 `/api/tool/swipe`。
- [ ] 提供 `/api/tool/input`。
- [ ] 提供 `/api/tool/back`。
- [ ] 提供 `/api/agent/execute_task`。

### 验收标准

- [ ] Lumi 能连上同一局域网的 APKClaw。
- [ ] Lumi 能显示手机截图。
- [ ] Lumi 能显示 UI 树摘要。
- [ ] Lumi 能从电脑端点击手机某个坐标。
- [ ] Lumi 能发送一句自然语言任务给 APKClaw。

## P0.5：AI 指针层

目标：让 AI 操作在手机屏幕上可见，方便 OpenClaw 截屏观察和用户理解。

### 手机端任务

- [ ] 新增悬浮窗权限引导。
- [ ] 实现 AI Cursor Overlay。
- [ ] 指针不拦截触摸事件。
- [ ] 支持显示/隐藏指针。
- [ ] 支持移动指针到坐标。
- [ ] 支持点击波纹。
- [ ] 支持滑动轨迹线。
- [ ] 支持长按进度环。
- [ ] 支持错误状态高亮。
- [ ] 支持设置轨迹保留时间。

### API 建议

```text
POST /api/cursor/show
POST /api/cursor/hide
POST /api/cursor/move
POST /api/cursor/config
```

动作 API 可支持：

```json
{
  "x": 512,
  "y": 1360,
  "visualize": true,
  "cursor_duration_ms": 250,
  "trace_duration_ms": 800
}
```

### 验收标准

- [ ] OpenClaw 获取的截图里能看到 AI 指针。
- [ ] 点击前指针能移动到目标点。
- [ ] 滑动前能显示轨迹。
- [ ] 指针不会挡住真实点击。
- [ ] 可以通过 API 关闭指针，获得干净截图。

## P1：轻量投屏控制台

目标：电脑上能看到手机画面，并能像控制远程屏幕一样操作。

### 桌面端任务

- [ ] 手机截图预览区域。
- [ ] 轮询截图，默认 500ms 到 1000ms 一帧。
- [ ] 显示真实手机分辨率。
- [ ] 点击预览图时换算为手机坐标。
- [ ] 拖动预览图时换算为 swipe。
- [ ] 支持返回键、主页键、最近任务键。
- [ ] 支持文本输入框。
- [ ] 支持截图暂停和刷新。
- [ ] 显示动作日志。
- [ ] 显示最近一次动作坐标。

### 坐标换算要求

```text
screen_x = preview_x / preview_width * device_width
screen_y = preview_y / preview_height * device_height
```

必须处理：

- 横屏。
- 竖屏。
- 截图缩放。
- 高 DPI 显示器。
- 手机状态栏和导航栏。

### 验收标准

- [ ] 点击电脑预览图上的按钮，手机能点中对应位置。
- [ ] 拖动电脑预览图，手机能完成滑动。
- [ ] 截图延迟可接受。
- [ ] 操作日志能复盘每一步。

## P2：OpenClaw 多模态控制

目标：让 OpenClaw 根据手机截图和 UI 树自动规划动作。

### 动作循环

```text
1. 获取截图。
2. 获取 UI 树。
3. 用户给出任务目标。
4. 多模态模型判断下一步。
5. 生成动作 JSON。
6. APKClaw 显示 AI 指针。
7. APKClaw 执行动作。
8. 再次截图。
9. 判断是否完成。
10. 未完成则继续循环。
```

### 动作格式建议

```json
{
  "type": "tap",
  "reason": "点击搜索框以输入关键词",
  "target": {
    "x": 512,
    "y": 320
  },
  "visualize": true,
  "confidence": 0.86
}
```

支持动作：

- `tap`
- `swipe`
- `long_press`
- `input_text`
- `back`
- `open_app`
- `wait`
- `finish`
- `ask_user`

### 安全限制

- [ ] 支付、转账、删除、发消息等敏感操作必须二次确认。
- [ ] 支持暂停任务。
- [ ] 支持人工接管。
- [ ] 支持最大步骤数限制。
- [ ] 支持最大执行时间限制。
- [ ] 支持危险 App 黑名单。

### 验收标准

- [ ] AI 能完成打开 App。
- [ ] AI 能完成搜索和输入。
- [ ] AI 能根据截图纠错。
- [ ] AI 点错后能识别没有成功并重试。
- [ ] 用户可以随时暂停。

## P3：Workflow Template 固化

目标：让成功流程变成可复用自动化。

### 模板生成

- [ ] 记录每一步截图。
- [ ] 记录每一步 UI 树。
- [ ] 记录每一步动作。
- [ ] 记录成功判断条件。
- [ ] 抽取变量参数。
- [ ] 保存为 workflow template。

### 模板执行

- [ ] 根据当前屏幕匹配模板。
- [ ] 替换参数。
- [ ] 快速执行。
- [ ] 执行中仍可截图校验。
- [ ] 模板失败时回退到多模态规划。

### 模板示例

- [ ] 打开某 App 并搜索关键词。
- [ ] 在社交 App 发布固定格式内容。
- [ ] 批量整理相册。
- [ ] 查询订单状态。
- [ ] 执行客服回复流程。

## P4：产品化和商业化

目标：把手机控制能力做成 Lumi 的杀手级扩展模块。

### 桌面端产品化

- [ ] 手机设备管理。
- [ ] 手机配对向导。
- [ ] 权限状态检查。
- [ ] 手机投屏控制台。
- [ ] AI 操作日志。
- [ ] 工作流模板库。
- [ ] 任务回放。
- [ ] 失败诊断。

### 手机端产品化

- [ ] 无障碍权限引导。
- [ ] 悬浮窗权限引导。
- [ ] 电池白名单引导。
- [ ] 后台保活提示。
- [ ] 局域网连接提示。
- [ ] Token 重置。
- [ ] 安全锁。
- [ ] 敏感操作确认。

### 商业包装

- [ ] Lumi Phone Control。
- [ ] APKClaw Connector。
- [ ] AI Mobile Operator。
- [ ] 工作流模板市场。
- [ ] 客户行业模板包。

## 5. 技术风险

### 截图能否截到悬浮窗

不同 Android 版本和截图方式可能不同。

需要实测：

- MediaProjection。
- Accessibility screenshot。
- 系统截图 API。
- 厂商 ROM。

### 截图延迟

轮询截图 MVP 可以用，但长期可能不够丝滑。

后续候选方案：

- WebSocket 推帧。
- MJPEG。
- WebRTC。
- USB / ADB。
- scrcpy 类方案。

### 无障碍稳定性

Android 无障碍服务容易受系统限制。

必须处理：

- 服务被系统杀掉。
- 权限被用户关闭。
- 后台限制。
- 电池优化。
- 厂商 ROM 差异。

### 坐标和 UI 树不一致

截图坐标、UI 树坐标、真实点击坐标可能存在偏差。

需要：

- 坐标校准。
- 屏幕旋转监听。
- 状态栏/导航栏处理。
- 点击后截图验证。

## 6. MVP 建议

第一版不要做太大。

建议 MVP 只做：

1. Lumi 手机控制页面。
2. 连接 APKClaw。
3. 获取手机截图。
4. 点击截图转手机点击。
5. 发送自然语言任务。
6. AI Cursor Overlay。
7. 动作日志。

这个 MVP 做完，方向就能被验证。

## 7. 推荐开发顺序

1. 统一 APKClaw API 和鉴权 Header。
2. Lumi 新增 Phone Connector 服务层。
3. Lumi 新增手机控制页面。
4. APKClaw 实现 AI Cursor Overlay。
5. Lumi 支持截图点击坐标换算。
6. OpenClaw 加入多模态动作循环。
7. 加入敏感操作确认。
8. 加入 workflow template 固化。
9. 优化投屏帧率。
10. 做模板库和商业包装。

## 8. 一句话定位

```text
Lumi Phone Control = 桌面 AI 大脑 + 手机真实执行器 + 可视化 AI 指针 + 多模态动作闭环。
```

这个方向如果做成，会让用户感觉 AI 不是在“建议怎么操作手机”，而是真的在电脑上看着手机、理解手机、操作手机。
