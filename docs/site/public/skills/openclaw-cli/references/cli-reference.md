# OpenClaw CLI 参数参考

来源：`openclaw_ui_integration/package.json` 与 `openclaw_ui_integration/scripts/openclaw-*.mjs`。所有命令默认在 `openclaw_ui_integration/` 下运行。npm 形式的脚本参数需要放在 `--` 后面。

## 脚本对照

| npm 脚本 | 脚本文件 | 用途 |
| --- | --- | --- |
| `openclaw:context` | `scripts/openclaw-context.mjs` | 能力发现、运行时上下文 |
| `verify:phone` | `scripts/verify-phone-agent.ps1` | 手机 Agent 自检 |
| `phone:agent` | `scripts/openclaw-phone-agent.mjs` | 自然语言手机 Agent 任务 |
| `phone:fleet` | `scripts/openclaw-phone-fleet.mjs` | 多设备编队 |
| `phone:vision` | `scripts/openclaw-phone-vision.mjs` | 取帧、视觉状态、单步动作 |
| `phone:video` | `scripts/openclaw-phone-video.mjs` | 录屏、列出和下载视频 |
| `phone:image` | `scripts/openclaw-image-phone.mjs` | AI 生图或图片导入手机 |
| `phone:image:edit` | `scripts/openclaw-image-phone.mjs --mode edit` | 图像编辑 |
| `phone:game` | `scripts/openclaw-phone-game.mjs` | 游戏模式单步 |
| `phone:publish` | `scripts/openclaw-publish-phone.mjs` | 平台发布 |
| `phone:relay` | `scripts/openclaw-publish-relay.mjs` | 发布中继 |
| `phone:relay:check` | `scripts/openclaw-publish-relay-check.mjs` | 中继状态检查 |
| `phone:relay:smoke` | `scripts/openclaw-publish-relay-smoke.mjs` | 中继冒烟测试 |
| `phone:demo:shopping` | `scripts/openclaw-phone-demo.mjs shopping` | 购物演示 |
| `phone:demo:read` | `scripts/openclaw-phone-demo.mjs read` | 阅读演示 |
| `phone:demo:game` | `scripts/openclaw-phone-demo.mjs game` | 游戏演示 |
| `desktop:agent` | `scripts/openclaw-desktop-agent.mjs` | 桌面 Agent 状态、启停、截图、点击、输入 |
| `desktop:reply` | `scripts/openclaw-desktop-agent.mjs reply` | 桌面观察和显式单次回复 |

通用选项：`--json`、`--device-id`、`--phone-url`、`--phone-token`。Token 参数仅用于调试，不应写入日志。

## openclaw:context

```powershell
npm run openclaw:context -- --json
npm run openclaw:context -- --probe --write --json
```

| 选项 | 说明 |
| --- | --- |
| `--root PATH` | 启动器或 OpenClawFiles 根目录，默认当前项目根 |
| `--device-id ID` | 选择一个已配置的 APKClaw 设备 |
| `--phone-url URL` | 本次刷新使用的手机 Agent 地址 |
| `--phone-token TOKEN` | 本次刷新使用的手机 Token，不写入上下文文件 |
| `--phone-album NAME` | 默认手机相册名 |
| `--probe` | 存在 URL 与 Token 时探测手机状态 |
| `--write` | 写入 `data/.openclaw/workspace/runtime-context.json` |
| `--json` | 输出 JSON |

输出包含 `agentCli`、`visionCli`、`videoCli`、`publishCli`、`fleetCli`、`desktopAgent.agentCli`、`desktopAgent.replyCli` 等字段。

## phone:agent

```powershell
npm run phone:agent -- run --prompt "读取当前屏幕" --mode observe --json
npm run phone:agent -- submit --prompt "打开设置页" --mode safe --json
npm run phone:agent -- status --task-id TASK_ID --json
npm run phone:agent -- cancel --task-id TASK_ID --json
npm run phone:agent -- history --limit 20 --json
npm run phone:agent -- enqueue --prompt "稍后检查屏幕" --mode observe --json
npm run phone:agent -- queue --json
npm run phone:agent -- drain --json
```

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--prompt TEXT` | 无 | `run`、`submit`、`enqueue` 必填 |
| `--task-id ID` | 无 | `status`、`cancel` 必填 |
| `--mode observe|safe|full` | `safe` | 操作模式 |
| `--timeout-sec N` | `600` | 手机端任务超时 |
| `--max-rounds N` | `60` | Agent 回合预算 |
| `--max-wait-sec N` | `615` | `run` 的 CLI 等待窗口 |
| `--poll-ms N` | `1800` | 轮询间隔 |
| `--priority N` | `0` | 队列优先级，数值越大越优先 |
| `--queue-id ID` | 无 | 指定队列任务 |
| `--limit N` | `20` | 历史条数 |

任务历史写入 `data/.openclaw/logs/phone-agent-history.jsonl`，本地队列写入 `data/.openclaw/launcher/phone-agent-queue.json`。

## phone:vision

```powershell
npm run phone:vision -- status --json
npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json
npm run phone:vision -- action --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"设置按钮\",\"reason\":\"打开设置面板\"}" --json
```

| 命令 | 说明 |
| --- | --- |
| `status` | 读取视觉链路状态 |
| `frame` | 抓取当前屏幕帧 |
| `action` | 执行一个视觉动作 |

动作体字段通常包含 `action`、`gridCell`、`targetLabel`、`reason`。`--force-action` 会跳过确认，只能在明确授权后使用。

## phone:video

```powershell
npm run phone:video -- start --max-seconds 60 --filename demo.mp4 --json
npm run phone:video -- status --json
npm run phone:video -- stop --json
npm run phone:video -- list --json
npm run phone:video -- download --latest --out-dir ./data/phone-videos --json
```

| 选项 | 说明 |
| --- | --- |
| `--max-seconds N` | 录屏时长上限 |
| `--filename NAME` | 手机端录屏文件名 |
| `--fps N` | 帧率，手机端会夹到支持范围 |
| `--bit-rate N` | 码率，手机端会夹到支持范围 |
| `--latest` | 下载最近一条视频 |
| `--out-dir PATH` | 下载目录 |

Android 录屏通常需要手机端确认屏幕录制授权。

## phone:image 与 phone:image:edit

```powershell
npm run phone:image -- --prompt "产品图标，清晰边缘" --json
npm run phone:image:edit -- --reference-image ./input.png --prompt "改成深色科技风" --json
npm run phone:image -- --image ./ready.png --json
```

| 选项 | 说明 |
| --- | --- |
| `--prompt TEXT` | 生图或编辑提示词 |
| `--mode edit` | 编辑模式，`phone:image:edit` 已内置 |
| `--reference-image PATH` | 编辑参考图 |
| `--image PATH` | 将已有图片导入手机 |

## phone:publish

```powershell
npm run phone:publish -- --platform xiaohongshu --title "标题" --body "正文" --image ./a.png --json
npm run phone:publish -- --transport reverse --platform douyin --packet-out ./publish-packet.json --json
```

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--platform xiaohongshu|douyin|wechat|custom` | `xiaohongshu` | 目标平台 |
| `--transport direct|reverse` | `direct` | 直连或反向中继 |
| `--title TEXT` | 无 | 标题 |
| `--body TEXT` | 无 | 正文 |
| `--hashtags TEXT` | 无 | 话题标签 |
| `--notes TEXT` | 无 | 给 Agent 的额外说明 |
| `--album NAME` | `OpenClaw Publish` | 手机相册 |
| `--image PATH` | 无 | 可重复传入图片 |
| `--video PATH` | 无 | 可重复传入视频 |
| `--file PATH` | 无 | 可重复传入通用媒体 |
| `--relay-url URL` | 无 | 反向中继端点 |
| `--relay-token TOKEN` | 环境变量 | 中继鉴权令牌 |
| `--channel-id ID` | 无 | 中继通道 |
| `--wait-relay` | 关闭 | 等待中继回执 |
| `--packet-out PATH` | 无 | 写出 reverse packet |

## phone:fleet

```powershell
npm run phone:fleet -- list --json
npm run phone:fleet -- status --target all --json
npm run phone:fleet -- run --target redmi-k70,pixel-01 --prompt "检查当前屏幕" --mode observe --json
```

| 命令 | 说明 |
| --- | --- |
| `list` | 列出已配置设备 |
| `status --target all` | 批量读取状态 |
| `run --target ID,ID --prompt TEXT` | 批量执行手机 Agent 任务 |

## phone:game 与 phone:demo

```powershell
npm run phone:game -- run --goal "查看当前游戏画面" --json
npm run phone:game -- act --plan-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"按钮\",\"reason\":\"确认\"}" --json
npm run phone:demo:shopping -- --query "高性价比商品" --json
npm run phone:demo:read --json
npm run phone:demo:game -- --goal "安全查看当前画面" --json
```

## desktop:agent

```powershell
npm run desktop:agent -- status --json
npm run desktop:agent -- health --json
npm run desktop:agent -- start --json
npm run desktop:agent -- stop --json
npm run desktop:agent -- screenshot --out ./data/desktop.png --json
npm run desktop:agent -- click --x 100 --y 200 --confirmed --json
npm run desktop:agent -- type --text "输入内容" --confirmed --json
npm run desktop:agent -- wechat unread --json
npm run desktop:agent -- wechat send --text "收到，稍后回复" --confirmed --json
```

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| `--root PATH` | 自动发现 | 启动器或 OpenClawFiles 根目录 |
| `--python PATH` | bundled 或系统 Python | Python executable |
| `--bridge-timeout-sec N` | `20` | 临时 Bridge 启动等待 |
| `--wait-sec N` | `15` | `start` 等待 sidecar health |
| `--timeout-ms N` | `45000` | HTTP 请求超时 |
| `--text TEXT` | 无 | 输入或发送文本 |
| `--x N --y N` | 无 | 点击坐标 |
| `--out PATH` | 无 | 截图保存路径 |
| `--agent-dir PATH` | 无 | Luminode agent 目录 |
| `--port N` | `21900` | Luminode HTTP API 端口 |
| `--app-type NAME` | `weixin` | `wechat`、`dingtalk`、`lark`、`generic` 等 |
| `--enabled` / `--disabled` | 无 | 开关桌面 Agent |
| `--allow-click true|false` | 无 | 是否允许点击 |
| `--allow-type true|false` | 无 | 是否允许输入 |
| `--allow-wechat-send true|false` | 无 | 是否允许微信发送 |
| `--send-mode draft_only|auto_enter` | `draft_only` | 发送模式 |
| `--confirmed` / `--yes` | false | 真实动作或危险策略必需 |
| `--no-screenshot` | false | `reply observe` 跳过截图 |

默认策略通常只允许截图。点击、输入、发送消息需要启动器配置放行，并且请求带 `--confirmed`。

## desktop:reply

```powershell
npm run desktop:reply -- observe --json
npm run desktop:reply -- once --text "回复内容" --confirmed --json
```

| 命令 | 说明 |
| --- | --- |
| `observe` | 汇总 status、health、未读状态和截图摘要 |
| `once` | 先观察，再发送一条显式给定的回复 |

`reply auto` 不是默认能力。没有侧边端点和用户授权时，不要自动生成并发送回复。

## 故障矩阵

| 现象 | 建议 |
| --- | --- |
| 找不到设备 | 在启动器手机控制页保存设备，或先跑 `phone:fleet list --json` |
| `Invalid Lumi signature` | Token、配对状态或签名通道不一致，重新配对并刷新配置 |
| `Missing value` | 检查 npm 脚本参数前是否有 `--` |
| 任务超时 | 拆成更小任务，或调整 `--max-wait-sec`、`--timeout-sec` |
| 桌面 401 | 使用 CLI 自动拉起 Bridge，不手写端口和 Token |
| 桌面 403 / `blocked=true` | 策略未放行；在启动器配置并带 `--confirmed` |
| 输出无法解析 | 增加 `--json`，只读 JSON 字段 |

## 直接 Node 调用

```powershell
node scripts/openclaw-context.mjs --json
node scripts/openclaw-phone-agent.mjs run --prompt "读取屏幕" --mode observe --json
node scripts/openclaw-desktop-agent.mjs status --json
```

直接 Node 调用不需要 npm 的 `--` 分隔符，其余参数一致。
