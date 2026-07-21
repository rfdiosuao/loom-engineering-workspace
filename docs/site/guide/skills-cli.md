# Skills 与 CLI

Skills 工作区用于管理可复用能力，CLI 用于让 Agent 和开发者调用启动器已有能力。建议先发现当前能力，再执行具体任务；自动化调用默认使用 JSON 输出。

## 先跑上下文

```powershell
cd D:\Axiangmu\AUSTART\openclaw_ui_integration
npm run openclaw:context -- --json
```

这个命令会读取当前环境里的手机、桌面、图像、视频、发布、编队和工作区能力。它比静态说明可靠，因为它直接读取启动器配置和运行时上下文。

## 下载 OpenClaw CLI Skill

这个 Skill 已经挂到文档站，可直接下载并安装到 Codex：

<div class="route-grid">
  <a class="route-card" href="/skills/openclaw-cli.skill" download>
    <strong>下载 openclaw-cli.skill</strong>
    <span>用于手机控制、桌面 RPA、发布、生图、录屏、视觉识别和显式回复。</span>
  </a>
  <a class="route-card" href="/skills/openclaw-cli/SKILL.md">
    <strong>查看 Skill 文件夹</strong>
    <span>文档站发布了解包后的 openclaw-cli/ 目录，可直接审阅 SKILL.md。</span>
  </a>
  <a class="route-card" href="/guide/openclaw-cli-skill">
    <strong>查看安装说明</strong>
    <span>包含 Skill 内容边界、安装位置、命令口径和更新流程。</span>
  </a>
</div>

## 高频命令

<div class="command-grid">
  <div class="command-card">
    <strong>手机 Agent</strong>

```powershell
npm run phone:agent -- run --prompt "读取当前屏幕" --mode observe --json
```
  </div>
  <div class="command-card">
    <strong>屏幕视觉</strong>

```powershell
npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json
```
  </div>
  <div class="command-card">
    <strong>桌面观察</strong>

```powershell
npm run desktop:reply -- observe --json
```
  </div>
  <div class="command-card">
    <strong>桌面回复</strong>

```powershell
npm run desktop:reply -- once --text "确认回复内容" --confirmed --json
```
  </div>
</div>

## 命令分层

| 层级 | 命令 | 适合做什么 |
| --- | --- | --- |
| 发现 | `openclaw:context` | 获取能力清单、默认配置、设备状态 |
| 手机 | `phone:agent`、`phone:vision`、`phone:video`、`phone:fleet` | 手机任务、截图、录屏、多设备 |
| 桌面 | `desktop:agent`、`desktop:reply` | 桌面截图、健康检查、显式回复 |
| 生产 | `phone:publish`、`phone:relay` | 平台发布、中继回执 |
| 生成 | `phone:image`、`phone:image:edit` | 生图和图像编辑入口 |

## mode 怎么选

| mode | 含义 | 建议 |
| --- | --- | --- |
| `observe` | 只观察，不执行真实动作 | 默认起步 |
| `safe` | 带安全护栏执行 | 明确目标后使用 |
| `full` | 放开更多动作 | 只在用户明确授权后使用 |

## Skill 更新原则

1. Skill 说明要写清触发词和边界。
2. 已有启动器 CLI 时，优先复用 CLI 提供的路径和参数。
3. 所有写操作必须有确认条件。
4. 避免在 Skill 里固化用户机器的绝对私密路径。
5. 文档写当前口径，代码用 `openclaw:context` 动态发现。

## 如果命令显示乱码

Skill 文件统一按 UTF-8 保存。如果在 PowerShell 里看到乱码，优先检查读取命令是否指定 `-Encoding UTF8`，不要把乱码内容再写回文件。
