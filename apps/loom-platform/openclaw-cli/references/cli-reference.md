# OpenClaw 自带 CLI — 完整参数参考

来源:`openclaw_new_launcher/scripts/openclaw-*.mjs` 与 `package.json` 的 `phone:*` / `desktop:*` / `openclaw:context` 脚本。
全部命令在 `openclaw_new_launcher/` 下运行。npm 形式参数前需加 `--` 分隔符。

## npm 脚本 ↔ 脚本文件对照

| npm 脚本 | 脚本文件 | 用途 |
|----------|----------|------|
| `openclaw:context` | `openclaw-context.mjs` | 自描述上下文 / 能力发现 |
| `phone:agent` | `openclaw-phone-agent.mjs` | 自然语言手机 Agent 任务 |
| `phone:fleet` | `openclaw-phone-fleet.mjs` | 多设备编队 |
| `phone:vision` | `openclaw-phone-vision.mjs` | 取帧 / 单步动作 |
| `phone:image` | `openclaw-image-phone.mjs` | AI 生图 |
| `phone:image:edit` | `openclaw-image-phone.mjs --mode edit` | 图生图 / 编辑 |
| `phone:video` | `openclaw-phone-video.mjs` | 录屏 / 取视频 |
| `phone:game` | `openclaw-phone-game.mjs` | 游戏模式单步 |
| `phone:publish` | `openclaw-publish-phone.mjs` | 平台发布 |
| `phone:relay` / `:check` / `:smoke` | `openclaw-publish-relay*.mjs` | 发布中继侧工具 |
| `phone:demo:shopping` / `:read` / `:game` | `openclaw-phone-demo.mjs` | 端到端演示 |
| `desktop:agent` | `openclaw-desktop-agent.mjs` | 桌面 Agent 状态、启停、截图、点击、输入、微信动作 |
| `desktop:reply` | `openclaw-desktop-agent.mjs reply` | 显式桌面回复观察与单次回复 |
| `verify:phone` | `verify-phone-agent.ps1` | 手机 Agent 自检 |

公共可选项(多数命令通用):`--device-id <id>`、`--phone-url <url>`、`--phone-token <token>`、`--json`、`-h/--help`。
默认从启动器"手机控制"配置读取设备地址与令牌。

---

## openclaw:context — 能力发现

```
npm run openclaw:context -- [options]
```
| 选项 | 说明 |
|------|------|
| `--root <path>` | 启动器或 OpenClawFiles 根目录。默认项目根 |
| `--device-id <id>` | 选择一个已配置的 APKClaw 设备作为上下文默认 |
| `--phone-url <url>` | 本次刷新用的手机 Agent 地址 |
| `--phone-token <token>` | 手机 Agent 令牌(不会写入上下文文件) |
| `--phone-album <name>` | 手机相册名。默认 `OpenClaw` |
| `--probe` | 当 URL 与令牌存在时探测 `/api/device/status` |
| `--write` | 写入 `data/.openclaw/workspace/runtime-context.json` |
| `--json` | 打印上下文 JSON |

输出 JSON 含各能力的精确 CLI 调用串(`agentCli` / `imageCli` / `imageEditCli` /
`visionCli` / `videoCli` / `publishCli` / `directCli` / `reverseCli` / `fleetCli` /
`gameModeCli` / `shoppingDemoCli` / `readDemoCli` / `gameFallbackDemoCli` /
`desktopAgent.agentCli` / `desktopAgent.replyCli`)。

---

## phone:agent — 手机 Agent 任务

```
npm run phone:agent -- <command> [options]
```
命令:`run`(提交并等结果) · `submit`(提交返回 task id) · `status` · `cancel` · `history`

| 选项 | 默认 | 说明 |
|------|------|------|
| `--prompt <text>` | — | run/submit 必填 |
| `--task-id <id>` | — | status/cancel 必填 |
| `--mode <observe\|safe\|full>` | `safe` | 操作放开程度 |
| `--timeout-sec <n>` | `600` | APKClaw 侧超时(手机会夹到支持范围) |
| `--max-rounds <n>` | `60` | Agent 回合预算 |
| `--max-wait-sec <n>` | `615` | run 的 CLI 等待窗口 |
| `--poll-ms <n>` | `1800` | 轮询间隔 |
| `--limit <n>` | `20` | history 打印行数 |

任务历史落盘于 `data/.openclaw/logs/phone-agent-history.jsonl`。

---

## phone:vision — 取帧与单步动作

```
npm run phone:vision -- <command> [options]
```
| 命令 | 说明 |
|------|------|
| `status` | 视觉链路状态 |
| `frame --out <path>` | 抓取一帧到文件 |
| `action --action-body <json> [--force-action]` | 执行一个动作 |

`--action-body` JSON 形如:
```json
{"action":"tap","gridCell":"C7","targetLabel":"设置按钮","reason":"打开安全的设置面板"}
```
`--force-action` 跳过确认(谨慎)。

---

## phone:image / phone:image:edit — AI 生图

```
npm run phone:image -- --prompt "<text>" [--json]
npm run phone:image -- --mode edit --reference-image <path> --prompt "<edit>" [--json]
npm run phone:image -- --image <path>            # 把已有图片推送到手机相册
```
| 选项 | 说明 |
|------|------|
| `--prompt <text>` | 生图提示词 |
| `--mode edit` | 进入图生图 / 编辑模式 |
| `--reference-image <path>` | 编辑模式的参考图 |
| `--image <path>` | 直接推送的图片文件 |

---

## phone:video — 录屏 / 取视频

```
npm run phone:video -- <command> [options]
```
| 命令 | 说明 |
|------|------|
| `start --max-seconds <n> --filename <name>` | 开始录屏 |
| `status` | 录制状态 |
| `stop` | 停止录制 |
| `list` | 列出设备上的视频 |
| `download --latest --out-dir <dir>` | 下载最近一条到本地目录 |

---

## phone:publish — 平台发布

```
npm run phone:publish -- [options]
```
| 选项 | 默认 | 说明 |
|------|------|------|
| `--platform <xiaohongshu\|douyin\|wechat\|custom>` | `xiaohongshu` | 目标平台 |
| `--transport <direct\|reverse>` | `direct` | 直连 / 反向中继 |
| `--title <text>` | — | 标题 |
| `--body <text>` | — | 正文 / 文案 |
| `--hashtags <a,b>` | — | 话题标签(逗号/空格/换行分隔) |
| `--notes <text>` | — | 给 Agent 的额外操作说明 |
| `--album <name>` | `OpenClaw Publish` | 手机相册 |
| `--image <path>` | — | 可重复,图片 |
| `--video <path>` | — | 可重复,视频 |
| `--file <path>` | — | 可重复,通用媒体 |
| `--relay-url <url>` | — | 反向中继 / 发布端点 |
| `--relay-token <token>` | env `OPENCLAW_PUBLISH_RELAY_TOKEN` | 中继鉴权令牌 |
| `--channel-id <id>` / `--channel <id>` | — | 反向发布通道 |
| `--wait-relay` | — | reverse 模式等待中继回执 done/failed |
| `--relay-wait-sec <n>` | 见脚本 | 中继等待窗口 |
| `--relay-poll-ms <n>` | 见脚本 | 中继状态轮询间隔 |
| `--packet-out <path>` | — | 写出 reverse packet 文件 |
| `--timeout-sec <n>` | `600` | APKClaw 侧超时 |
| `--max-wait-sec <n>` | `615` | direct 模式等待窗口 |
| `--poll-ms <n>` | `1800` | 轮询间隔 |

---

## phone:fleet — 多设备编队

```
npm run phone:fleet -- <command> [options]
```
| 命令 | 说明 |
|------|------|
| `list` | 列出已配置设备 |
| `status --target <all\|id,id>` | 批量状态 |
| `run --target <id,id> --prompt <text> --mode <observe\|safe\|full>` | 批量跑 Agent 任务 |

---

## phone:game — 游戏模式

```
npm run phone:game -- run --goal "<目标>" [--plan-body <json>]
npm run phone:game -- act --plan-body "<json>"
```
`--plan-body` 与 vision 的 action-body 同构(action / gridCell / targetLabel / reason)。

---

## phone:demo:* — 端到端演示

```
npm run phone:demo:shopping -- --query "<搜索词>"
npm run phone:demo:read
npm run phone:demo:game -- --goal "<目标>"
```

---

## desktop:agent — 桌面 Agent CLI

```
npm run desktop:agent -- <command> [options]
```

CLI 会启动临时 Python Bridge 并自动处理 `X-Bridge-Token`;不要直连 Luminode 端口或打印 token。

| 命令 | 说明 |
|------|------|
| `status` | 读取 launcher Desktop Agent 状态 |
| `health` | 探测 Luminode sidecar 健康 |
| `config` | 读取或写入桌面 Agent 配置 |
| `start` | 通过 launcher Bridge 启动 Luminode,并等待 health |
| `stop` | 停止 Luminode;进程句柄丢失时按配置端口兜底停止 |
| `screenshot --out <path>` | 截图并可保存本地图片 |
| `click --x <n> --y <n> --confirmed` | 坐标点击 |
| `type --text <text> --confirmed` | 键盘输入 |
| `wechat unread` | 微信未读检测 |
| `wechat send --text <text> --confirmed` | 微信发消息 |

| 选项 | 默认 | 说明 |
|------|------|------|
| `--root <path>` | 自动发现 | 启动器或 OpenClawFiles 根目录 |
| `--python <path>` | bundled 或系统 Python | Python executable |
| `--bridge-timeout-sec <n>` | `20` | 临时 Bridge 启动等待 |
| `--wait-sec <n>` | `15` | start 等待 sidecar health |
| `--timeout-ms <n>` | `45000` | HTTP 请求超时 |
| `--agent-dir <path>` | — | config: 设置 Luminode agent 目录 |
| `--port <n>` | `21900` | config: 设置 Luminode HTTP API 端口 |
| `--app-type <name>` | `weixin` | config: wechat/dingtalk/lark/generic 等 |
| `--enabled` / `--disabled` | — | config: 启用/禁用 |
| `--allow-click <true|false>` | — | config: 是否允许点击 |
| `--allow-type <true|false>` | — | config: 是否允许输入 |
| `--allow-wechat-send <true|false>` | — | config: 是否允许微信发送 |
| `--send-mode <draft_only|auto_enter>` | `draft_only` | config: 发送模式 |
| `--confirmed` / `--yes` | false | 真实动作或打开危险策略必需 |
| `--no-screenshot` | false | reply observe 跳过截图 |
| `--json` | false | JSON 输出 |

常用示例:

```powershell
npm run desktop:agent -- status --json
npm run desktop:agent -- start --json
npm run desktop:agent -- screenshot --out .\data\desktop.png --json
npm run desktop:agent -- config --allow-wechat-send true --send-mode auto_enter --confirmed --json
npm run desktop:agent -- wechat send --text "收到,稍后回复" --confirmed --json
```

默认策略:`allowScreenshot=true`,`allowClick/allowType/allowWechatSend=false`,
`requireConfirmForClick/Type/Send=true`。命中限制返回 `blocked=true` 或错误原因。

---

## desktop:reply — 显式桌面回复

```
npm run desktop:reply -- observe --json
npm run desktop:reply -- once --text "回复内容" --confirmed --json
```

| 命令 | 说明 |
|------|------|
| `observe` | 汇总 status、health、未读状态和截图摘要 |
| `once` | 先读取未读,再发送一条显式传入的回复 |

`reply auto` 目前不会自动生成并发送回复;需要 Luminode sidecar 先暴露一键自动回复端点。

---

## 直接 node 调用(等价形式)

```
node scripts/openclaw-phone-agent.mjs run --prompt "..." --mode safe --json
node scripts/openclaw-context.mjs --json
```
无需 `--` 分隔符;其余参数一致。
