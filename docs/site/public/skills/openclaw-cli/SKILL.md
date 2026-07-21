---
name: openclaw-cli
description: >
  Use the OpenClaw or Lumi launcher built-in CLI for phone control, APKClaw, screen vision, screenshots, recording, image generation, platform publishing, multi-device fleet tasks, desktop RPA, SightFlow or Luminode control, and explicit desktop or WeChat replies. Trigger on 手机控制, APKClaw, 手机 Agent, 生图, 出图, 截图, 录屏, 屏幕识别, 视觉, 平台发布, 小红书发布, 抖音发布, 编队, fleet, 桌面控制, 桌面 RPA, SightFlow, Luminode, 微信发送, 微信未读, OpenClaw CLI, phone agent, desktop control, publish, screenshot, vision.
---

# OpenClaw CLI 调用指南

OpenClaw / Lumi 启动器在 `openclaw_ui_integration/` 下提供一组 Node CLI。优先使用这些 CLI 调用手机、桌面、发布和生成能力，不要绕过启动器配置直接拼 HTTP 请求。

## 调用前检查

1. 在仓库或便携包的 `openclaw_ui_integration/` 目录运行命令。
2. 每次任务开始先发现当前能力：

```powershell
npm run openclaw:context -- --json
```

3. 机读输出一律加 `--json`，解析 JSON 字段，不解析人类可读文本。
4. 手机 URL、Token、设备 ID 默认读取启动器“手机控制”配置。只有调试或多设备时才显式传 `--device-id`、`--phone-url`、`--phone-token`。
5. 不要把 Token、API Key、Bridge Token 写入日志、回复、文档或仓库。

## 安全边界

- 默认从 `observe` 开始，只观察不执行真实动作。
- 目标明确后使用 `safe`。
- `full`、`--force-action`、点击、输入、发送消息等真实动作，只能在用户明确授权后使用。
- 桌面写动作必须带 `--confirmed`，并接受 Bridge 策略校验。
- 命中 `blocked=true`、401、403、签名失败或设备离线时，先报告原因并建议修配置，不要绕过 CLI 直连底层服务。

## 高频命令

### 手机 Agent

```powershell
npm run phone:agent -- run --prompt "读取当前手机屏幕并返回摘要" --mode observe --json
npm run phone:agent -- submit --prompt "打开设置页" --mode safe --json
npm run phone:agent -- status --task-id TASK_ID --json
npm run phone:agent -- history --limit 20 --json
```

离线或长任务可走本地队列：

```powershell
npm run phone:agent -- enqueue --prompt "稍后检查当前屏幕" --mode observe --json
npm run phone:agent -- queue --json
npm run phone:agent -- drain --json
```

### 屏幕视觉与单步动作

```powershell
npm run phone:vision -- status --json
npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json
npm run phone:vision -- action --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"设置按钮\",\"reason\":\"打开设置面板\"}" --json
```

只有在用户明确同意时才使用 `--force-action`。

### 录屏与视频

```powershell
npm run phone:video -- start --max-seconds 60 --filename demo.mp4 --json
npm run phone:video -- status --json
npm run phone:video -- stop --json
npm run phone:video -- list --json
npm run phone:video -- download --latest --out-dir ./data/phone-videos --json
```

### 图像生成与导入手机

```powershell
npm run phone:image -- --prompt "干净的产品图标，工作室灯光" --json
npm run phone:image:edit -- --reference-image ./input.png --prompt "调整为深色科技风" --json
```

### 平台发布

```powershell
npm run phone:publish -- --platform xiaohongshu --title "标题" --body "正文" --image ./a.png --json
npm run phone:publish -- --transport reverse --platform douyin --packet-out ./publish-packet.json --json
```

发布前确认平台、标题、正文、素材和账号，不要自动发布不确定内容。

### 多设备编队

```powershell
npm run phone:fleet -- list --json
npm run phone:fleet -- status --target all --json
npm run phone:fleet -- run --target redmi-k70,pixel-01 --prompt "检查当前屏幕" --mode observe --json
```

### 桌面 RPA 与显式回复

```powershell
npm run desktop:agent -- status --json
npm run desktop:agent -- health --json
npm run desktop:agent -- start --json
npm run desktop:agent -- screenshot --out ./data/desktop.png --json
npm run desktop:reply -- observe --json
npm run desktop:reply -- once --text "收到，稍后回复" --confirmed --json
```

配置桌面组件时通过启动器 Bridge 修改，不直连 Luminode：

```powershell
npm run desktop:agent -- config --app-type dingtalk --enabled --confirmed --json
npm run desktop:agent -- config --allow-wechat-send true --send-mode draft_only --confirmed --json
```

## 推荐工作流

1. `npm run openclaw:context -- --json` 获取当前能力与默认配置。
2. 用 `phone:vision frame`、`phone:agent run --mode observe` 或 `desktop:reply observe` 看清状态。
3. 将任务拆成小步执行，优先 `safe` 模式。
4. 对发布、输入、点击、发送消息等动作，在回复中说明将要做什么，并等待用户确认。
5. 产物路径、任务 ID、失败原因从 JSON 中读取并回传给用户。

## 故障处理

| 现象 | 处理 |
| --- | --- |
| 找不到设备或未配置 | 打开启动器“手机控制”页保存设备；多设备时用 `phone:fleet list --json` |
| `Invalid Lumi signature` | 手机端 Token 或配对签名状态不一致，重新配对或刷新手机控制配置 |
| 任务超时 | 拆小 prompt，或调高 `--max-wait-sec`；不要把一个长流程塞进单次任务 |
| 桌面 401 | Bridge Token 不匹配；使用 `desktop:agent` CLI 自动拉起 Bridge |
| 桌面 403 或 `blocked=true` | 策略拦截；在启动器里开启对应能力并带 `--confirmed` |
| 参数报 Missing value | npm 脚本参数前确认有 `--` 分隔 |

完整参数和脚本对照见 `references/cli-reference.md`。
