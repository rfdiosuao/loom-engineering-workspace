---
name: openclaw-cli
description: >
  调用 OpenClaw / Lumi 启动器自带的命令行工具(项目内置 CLI),用于手机控制、AI 生图、
  录屏取视频、屏幕视觉识别、平台发布、多设备编队、桌面控制和显式微信回复。
  所有命令位于 openclaw_new_launcher/,经 `npm run phone:* -- <args>`、
  `npm run desktop:* -- <args>` 或 `node scripts/openclaw-*.mjs` 调用。
  触发词:手机控制、APKClaw、手机 Agent、生图、出图、录屏、截图、屏幕识别、视觉、
  平台发布、小红书、抖音发布、编队、fleet、桌面控制、Luminode、微信发送、微信未读、
  openclaw cli、phone agent、phone control、desktop control、publish、screenshot、vision。
---

# OpenClaw 自带 CLI(Agent 调用指南)

OpenClaw / Lumi 启动器在 `openclaw_new_launcher/scripts/` 下提供一套 Node 命令行工具,
专为 Agent 自动化设计:手机控制、生图、录屏、视觉识别、平台发布、多设备编队、桌面控制。
本 Skill 教你如何正确调用它们。

## 0. 调用约定(先读)

- **工作目录**:所有命令在 `openclaw_new_launcher/` 下运行。
- **两种调用形式**(等价):
  - npm 形式:`npm run phone:agent -- run --prompt "..."`(`--` 后面才是 CLI 参数)
  - 桌面形式:`npm run desktop:agent -- status` / `npm run desktop:reply -- observe`
  - 直接形式:`node scripts/openclaw-phone-agent.mjs run --prompt "..."`
- **机读输出**:几乎所有命令都支持 `--json`,Agent 应**始终加 `--json`** 并解析它,
  不要去解析人类可读文本。
- **设备 / 令牌默认值**:CLI 默认从启动器"手机控制"页已保存的配置读取
  手机地址与令牌(经 `openclaw-phone-secure.mjs` 做签名请求)。通常**无需手动传**
  `--phone-url` / `--phone-token`;只有调试或多设备时才显式指定 `--device-id`。
- **前置条件**:已 `npm ci`;启动器已配置并连接好 APKClaw 手机 Agent(手机控制页可见在线设备)。

## 1. 第一步永远是:发现当前能力

项目自带一个**自描述上下文命令**,会输出当前环境下所有可用 CLI 的精确调用串。
开始任何任务前先跑它,拿到最新、最准确的命令清单和默认参数:

```bash
npm run openclaw:context -- --json
```

它返回一个 JSON,内含 `agentCli` / `imageCli` / `visionCli` / `videoCli` /
`publishCli` / `fleetCli` / `gameModeCli` / `desktopAgent.agentCli` /
`desktopAgent.replyCli` 等字段,以及当前手机/相册/桌面 Agent 等默认值。
加 `--write` 可把上下文写入 `data/.openclaw/workspace/runtime-context.json`
供 OpenClaw 工作区读取;加 `--probe` 会探测设备在线状态。

> 经验法则:**先 `openclaw:context --json` 对齐能力,再执行具体命令。**

## 2. 命令速查

完整参数见 [references/cli-reference.md](references/cli-reference.md)。下面是高频用法。

### 手机 Agent —— 自然语言驱动手机(`phone:agent`)
提交一个有界的异步 APKClaw Agent 任务并等待结果。

```bash
# 跑一个任务并等结果(安全模式)
npm run phone:agent -- run --prompt "读取当前手机屏幕并返回摘要" --mode safe --json
# 只提交、拿 task id
npm run phone:agent -- submit --prompt "打开设置页" --json
# 查询 / 取消 / 历史
npm run phone:agent -- status --task-id <id> --json
npm run phone:agent -- cancel --task-id <id> --json
npm run phone:agent -- history --limit 20 --json
```

`--mode` 取值:`observe`(只看不操作)/ `safe`(默认,带确认/护栏)/ `full`(放开操作)。
从 `observe` 起步最安全。

### 屏幕视觉 —— 取帧与单步操作(`phone:vision`)
比 Agent 更底层,适合"先看一帧、再决定下一步动作"的精细控制。

```bash
npm run phone:vision -- status --json
npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json
npm run phone:vision -- action --force-action \
  --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"设置按钮\",\"reason\":\"打开安全的设置面板\"}" --json
```

动作用九宫格坐标(如 `C7`)+ 目标标签 + 原因描述。`--force-action` 跳过确认,谨慎使用。

### AI 生图(`phone:image` / `phone:image:edit`)

```bash
npm run phone:image -- --prompt "干净的产品图标,工作室灯光" --json
npm run phone:image -- --mode edit --reference-image ./input.png --prompt "改成赛博朋克风" --json
```

### 录屏取视频(`phone:video`)

```bash
npm run phone:video -- start --max-seconds 60 --filename demo.mp4 --json
npm run phone:video -- status --json
npm run phone:video -- stop --json
npm run phone:video -- list --json
npm run phone:video -- download --latest --out-dir ./data/phone-videos --json
```

### 平台发布(`phone:publish`)
支持直连(direct)与反向中继(reverse)两种传输。平台:`xiaohongshu` / `douyin` / `wechat` / `custom`。

```bash
# 直连发布图文 + 视频
npm run phone:publish -- --platform xiaohongshu --title "标题" --body "正文" \
  --image ./a.png --video ./b.mp4 --json
# 反向中继:生成 packet 给中继端
npm run phone:publish -- --transport reverse --platform douyin --packet-out ./publish-packet.json --json
# 反向中继 + 等待中继回执
npm run phone:publish -- --transport reverse --platform douyin \
  --relay-url https://relay.example.com/api/lumi/publish/packet \
  --relay-token <token> --channel-id publish-channel-01 --wait-relay --json
```

### 多设备编队(`phone:fleet`)

```bash
npm run phone:fleet -- list --json
npm run phone:fleet -- status --target all --json
npm run phone:fleet -- run --target redmi-k70,pixel-01 --prompt "检查当前屏幕" --mode observe --json
```

### 游戏模式与演示(`phone:game` / `phone:demo:*`)

```bash
npm run phone:game -- run --goal "查看当前游戏画面" --json
npm run phone:demo:shopping -- --query "拼多多 高性价比商品" --json
npm run phone:demo:read --json
npm run phone:demo:game -- --goal "安全地查看当前画面" --json
```

## 3. 安全与护栏

- **模式分级**:`observe` < `safe` < `full`。不确定时用 `observe`/`safe`;`full` 与
  `--force-action` 会真实操作设备,仅在用户明确授权后使用。
- **任务有界**:Agent 任务有超时(`--timeout-sec`,默认 600)与回合预算
  (`--max-rounds`,默认 60),不会无限运行。
- **签名请求**:CLI 经 `openclaw-phone-secure.mjs` 对请求做签名;令牌不会写入上下文文件。
  不要把 `--phone-token` 打印到日志或提交到仓库。
- **桌面/微信类操作**由 Bridge 侧策略(`desktop_agent.py` 的 `_enforce_policy`)再做一层校验。

## 4. 推荐工作流

1. `npm run openclaw:context -- --json` → 确认设备在线与可用命令。
2. 先 `phone:vision frame` 取一帧或 `phone:agent run --mode observe` 看清现状。
3. 再用 `phone:agent run --mode safe`(自然语言)或 `phone:vision action`(精细单步)执行。
4. 需要产物:`phone:image` 出图 / `phone:video` 录屏 / `phone:publish` 发布。
5. 全程加 `--json`,解析结果里的 `taskId` / `status` / 产物路径。

## 5. 桌面控制与显式回复(`desktop:agent` / `desktop:reply`)

桌面控制现在有 npm CLI。CLI 会自己启动一个临时 Python Bridge,读取运行时
`BRIDGE_TOKEN`,再通过 `/api/desktop-agent/*` 调用 Luminode;不要手写端口、
token 或直连 Luminode。

```bash
npm run desktop:agent -- status --json
npm run desktop:agent -- health --json
npm run desktop:agent -- start --json
npm run desktop:agent -- screenshot --out ./data/desktop.png --json
npm run desktop:agent -- wechat unread --json
npm run desktop:reply -- observe --json
npm run desktop:reply -- once --text "回复内容" --confirmed --json
```

常用命令:
- `status` / `health`:只读状态与健康检查。
- `start` / `stop`:通过启动器 Bridge 启停 Luminode;`start` 会等待 sidecar health。
- `screenshot --out <path>`:截图并保存本地图片。
- `click --x <n> --y <n> --confirmed`:显式确认后点击。
- `type --text <text> --confirmed`:显式确认后输入。
- `wechat unread`:读取未读状态。
- `wechat send --text <text> --confirmed`:显式确认后发送。
- `reply observe`:汇总 status、health、未读和截图摘要。
- `reply once --text <text> --confirmed`:观察未读后发送一条明确给定的回复。

安全策略:
- 默认只允许截图;点击、输入、微信发送通常被 launcher policy 禁用。
- 打开策略也必须显式确认,例如:

```bash
npm run desktop:agent -- config --allow-wechat-send true --send-mode auto_enter --confirmed --json
```

- 所有真实动作必须带 `--confirmed`;否则 CLI 会先拦截。
- 命中 Bridge 策略时返回 `blocked=true` 或错误原因;不要绕过 CLI 直连 sidecar。
- CLI 会串行化临时 Bridge 启动,并打码 token / api key;不要把私密参数写进日志。

完整端点和参数说明见 [references/cli-reference.md](references/cli-reference.md)。

## 6. 相关 CLI(非手机自动化)

- **授权服务器**(`license_server/`,需 Python):
  `python server.py serve | create-code --licensee <名> --edition pro --count 5 --expires <YYYY-MM-DD> | list-codes | public-key`
- **构建 / 发布**(`scripts/`,PowerShell):`build-portable.ps1`、`ci-check.ps1`、
  `verify-release.ps1`、`smoke-bridge.ps1` 等。详见 `docs/PROJECT_DOCUMENTATION.md` 第 11 节。

## 7. 故障排查

| 现象 | 处理 |
|------|------|
| 提示找不到设备 / 未配置 | 打开启动器"手机控制"页配置并连接 APKClaw,或显式传 `--phone-url` / `--phone-token` |
| 命令参数报 "Missing value" | npm 形式记得加 `--` 分隔:`npm run phone:agent -- run ...` |
| 输出难解析 | 一律加 `--json`,解析 JSON 字段而非文本 |
| 任务超时 | 调大 `--timeout-sec` / `--max-wait-sec`,或拆成更小的 prompt |
| 不确定命令是否存在 | 跑 `npm run openclaw:context -- --json` 以当前环境为准 |
| 桌面 click/type 返回 403 blocked | 默认禁用,需在启动器开 `allowClick`/`allowType`,且请求体带 `confirmed:true` |
| 桌面接口 401 / 鉴权失败 | 请求头缺 `X-Bridge-Token`,或令牌与 Bridge 启动打印的 `BRIDGE_TOKEN` 不符 |
