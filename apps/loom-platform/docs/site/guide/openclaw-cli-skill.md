# OpenClaw CLI Skill

`openclaw-cli.skill` 是给 Codex 使用的能力包。它把启动器已有 CLI 整理成稳定调用规则：先发现能力，再观察状态，最后在明确授权下执行真实动作。

## 下载

<div class="route-grid">
  <a class="route-card" href="/skills/openclaw-cli.skill" download>
    <strong>下载 Skill 包</strong>
    <span>文件名：openclaw-cli.skill。安装后 Codex 会在相关任务中自动触发。</span>
  </a>
  <a class="route-card" href="/skills/openclaw-cli/SKILL.md">
    <strong>查看 Skill 文件夹</strong>
    <span>文档站同时发布了解包后的 openclaw-cli/ 目录，便于在线审阅和二次维护。</span>
  </a>
  <a class="route-card" href="/guide/skills-cli">
    <strong>返回 Skills 与 CLI</strong>
    <span>查看常用命令、模式选择和启动器能力分层。</span>
  </a>
</div>

## 包内结构

```text
openclaw-cli/
  SKILL.md
  references/
    cli-reference.md
```

`SKILL.md` 保存触发条件、调用约定和安全边界；`references/cli-reference.md` 保存完整参数表。Codex 安装 Skill 后，会优先读取 `SKILL.md`，需要细节时再读取 reference。

在线文件：

- [SKILL.md](/skills/openclaw-cli/SKILL.md)
- [references/cli-reference.md](/skills/openclaw-cli/references/cli-reference.md)

## 适用场景

| 场景 | 推荐入口 |
| --- | --- |
| 读取手机屏幕、执行 APKClaw 任务 | `npm run phone:agent` |
| 截图、视觉识别、单步点击 | `npm run phone:vision` |
| 录屏、下载手机视频 | `npm run phone:video` |
| AI 生图、图片导入手机 | `npm run phone:image` |
| 小红书、抖音、微信发布 | `npm run phone:publish` |
| 多设备状态和批量任务 | `npm run phone:fleet` |
| 桌面 RPA、Luminode 状态、截图 | `npm run desktop:agent` |
| 显式桌面回复、微信未读观察 | `npm run desktop:reply` |

## 安装到 Codex

1. 下载 [openclaw-cli.skill](/skills/openclaw-cli.skill)。
2. 将 Skill 安装到 Codex 的 Skills 目录，或通过当前 Codex 客户端的 Skill 导入入口安装。
3. 新开一个 Codex 会话，输入“手机控制”“桌面 RPA”“OpenClaw CLI”等任务词，确认 Skill 被触发。

如果手动解包安装，目录应保持为：

```text
C:\Users\Administrator\.codex\skills\openclaw-cli\SKILL.md
C:\Users\Administrator\.codex\skills\openclaw-cli\references\cli-reference.md
```

## 调用口径

每次执行前先跑：

```powershell
cd D:\Axiangmu\AUSTART\openclaw_ui_integration
npm run openclaw:context -- --json
```

这一步用于确认当前设备、桌面组件、模型、发布和生成能力。后续命令以它返回的能力为准，不以过期文档或记忆为准。

## 安全策略

| 动作 | 默认策略 |
| --- | --- |
| 观察屏幕、读取状态 | 可以直接执行，仍建议使用 `--json` |
| 手机任务 | 从 `observe` 开始，必要时升到 `safe` |
| 点击、输入、发送消息、发布内容 | 必须有用户明确确认 |
| 桌面写动作 | 必须带 `--confirmed`，同时通过 Bridge 策略 |
| Token、API Key、Bridge Token | 不展示、不写日志、不提交仓库 |

## 更新流程

1. 更新 `openclaw-cli/SKILL.md` 和 `references/cli-reference.md`。
2. 运行 Skill 校验，确认 frontmatter 合法。
3. 重新压缩为 `.skill`。
4. 覆盖 `docs/site/public/skills/openclaw-cli.skill`。
5. 执行 `npm run docs:build`，确认下载链接被打入站点产物。

## 验证命令

```powershell
cd D:\Axiangmu\AUSTART\docs\site
npm run docs:build
```

构建完成后访问：

```text
http://127.0.0.1:5501/guide/openclaw-cli-skill
http://127.0.0.1:5501/skills/openclaw-cli.skill
```
