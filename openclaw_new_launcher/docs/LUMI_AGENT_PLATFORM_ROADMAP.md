# Lumi Agent 平台长期开发路线

> 定位：把当前启动器从“OpenClaw 便携启动器”逐步升级为“本地 Agent 能力中枢”。  
> 原则：先稳交付，再做扩展；先沉淀协议，再堆功能；所有新能力都要能被 UI、CLI、Skill 和外部 Agent 复用。

## 1. 产品目标

Lumi 后续不只负责启动 OpenClaw，而是负责管理一台电脑上的 AI 创作和 Agent 自动化能力：

- 启动、停止、诊断 OpenClaw 本体。
- 管理 API、授权码、飞书、微信、Skills。
- 管理多个 Agent 的安装、启用、配置和运行。
- 展示 Agent 工作过程，让用户可以观察、接管、重试。
- 对外提供 CLI 和本地 API，让其他 Agent 也能调用启动器能力。

最终形态：

```text
Lumi Desktop UI
  管理、观察、配置、人工确认

Lumi CLI
  自动化脚本、售后排障、外部 Agent 调用

Lumi Local API / Bridge
  统一能力入口

OpenClaw Runtime
  真正运行 Agent、插件、模型和工具
```

## 2. 当前阶段优先级

近期不要急着继续加大功能。先把当前交付链路做稳：

1. 修复 U 盘插拔后重新授权问题。
   - 新授权指纹不能包含盘符。
   - 需要兼容旧授权文件。
   - 服务端最好允许同一个安装 ID 平滑换签新 deviceId。

2. 完成 Lumi 自用版 UI 换皮。
   - Logo、窗口标题、任务栏图标一致。
   - 默认深色高级主题。
   - 浅色/深色切换不能闪白。
   - 所有主要页面不能出现乱码文案。

3. 保持现有启动、授权、AI 生图、AI 视频、广告视频、飞书/微信绑定可用。
   - 这批功能是交付底座。
   - 任何 Agent 化改造都不能破坏它们。

4. 打包一版稳定测试包。
   - 跑 `npm run build`。
   - 跑 Bridge smoke。
   - 跑 release verify。
   - 真实 U 盘启动测试一次。

## 3. 第一阶段：把启动器能力服务化

目标：UI 不再是唯一入口。所有核心功能都沉到 Bridge API。

### 需要沉淀的能力

```text
openclaw.status
openclaw.start
openclaw.stop
openclaw.openWeb

license.current
license.activate

api.profile.read
api.profile.write

skills.list
skills.installZip
skills.enable
skills.disable

bots.feishu.install
bots.weixin.install

video.generate
image.generate
storyboard.project.read
storyboard.project.write

diagnostics.run
diagnostics.repair
logs.export
```

### 验收标准

- UI 页面只调用服务层，不直接写复杂业务逻辑。
- Bridge API 有清晰路径和返回格式。
- 失败时返回统一错误结构。
- 后续 CLI 可以不复制业务逻辑，直接调用同一套 API。

## 4. 第二阶段：Lumi CLI

目标：让启动器可以被命令行、脚本、外部 Agent 调用。

### 首批命令

```powershell
lumi status
lumi start
lumi stop
lumi open
lumi logs export
lumi diagnostics run
lumi diagnostics repair

lumi license current
lumi license activate OC-PRO-XXXX-XXXX-XXXX-XXXX

lumi skill list
lumi skill install .\my-skill.zip
lumi skill enable skill-id
lumi skill disable skill-id
```

### 后续命令

```powershell
lumi agent list
lumi agent install .\agent.zip
lumi agent enable agent-id
lumi agent run agent-id --input input.json

lumi workflow list
lumi workflow run ad-video --brief product.md
lumi run watch run-id
```

### 实现建议

短期最快：Node CLI。

```text
scripts/lumi-cli.mjs
```

长期更稳：Rust CLI。

```text
src-tauri/src/bin/lumi.rs
```

### 验收标准

- 不打开 UI 也能查询状态。
- 不打开 UI 也能导出日志和诊断。
- CLI 调用失败时输出明确错误。
- CLI 不读取明文敏感配置，必要时通过本地 Bridge 处理。

## 5. 第三阶段：Agent 管理器

目标：让用户可以安装、启用、关闭和配置多个 Agent。

### Agent 包结构

```text
agents/
  ad-video-agent/
    agent.json
    README.md
    config.schema.json
    prompts/
    skills/
```

### agent.json 示例

```json
{
  "id": "ad-video-agent",
  "name": "广告视频 Agent",
  "description": "生成广告脚本、分镜、首尾帧和视频素材",
  "version": "1.0.0",
  "entry": "openclaw",
  "requiredSkills": [],
  "configSchema": "config.schema.json",
  "permissions": [
    "image.generate",
    "video.generate",
    "files.write"
  ]
}
```

### UI 模块

新增 `Agents` 页面：

- 已安装 Agent 列表。
- 上传 Agent 压缩包。
- 启用、禁用、卸载。
- 查看 README。
- 配置模型、提示词、权限。
- 打开 Agent 输出目录。

### 验收标准

- Agent 可以被扫描识别。
- Agent 可以启用和禁用。
- 配置结构由 `config.schema.json` 驱动。
- 不执行未知危险脚本。
- Agent 权限可见、可控。

## 6. 第四阶段：Agent Run Viewer

目标：用户能观察 Agent 制作过程，而不是只看一坨日志。

### Run 数据结构

```json
{
  "id": "run_20260508_001",
  "workflow": "ad-video",
  "status": "running",
  "createdAt": "2026-05-08T12:00:00+08:00",
  "steps": [
    {
      "id": "brief",
      "agent": "策划 Agent",
      "status": "done",
      "input": {},
      "output": {},
      "logs": [],
      "artifacts": []
    }
  ]
}
```

### 前端表现

```text
左侧：任务列表
中间：步骤时间线
右侧：当前步骤详情和产物预览
```

每一步显示：

- 当前状态：等待、运行中、完成、失败、需要确认。
- 使用的 Agent。
- 使用的模型。
- 输入内容。
- 输出结果。
- 日志。
- 图片、视频、文件等产物。
- 重试按钮。
- 人工确认按钮。

### 事件格式

```json
{"type":"run.started","runId":"run_001"}
{"type":"step.started","stepId":"storyboard"}
{"type":"artifact.created","kind":"image","path":"data/storyboards/a.png"}
{"type":"step.waiting_approval","stepId":"frames"}
{"type":"step.completed","stepId":"frames"}
{"type":"run.completed","runId":"run_001"}
```

### 验收标准

- 用户能看清 Agent 正在做哪一步。
- 用户能看到每一步产物。
- 失败步骤能重试。
- 关键步骤能人工确认后继续。
- 任务结束后可以导出完整项目包。

## 7. 第五阶段：多 Agent 协作工作流

目标：多个 Agent 串联或并行完成复杂任务。

### 广告视频工作流示例

```text
用户输入产品资料
  ↓
策划 Agent：提炼卖点、目标人群、平台规格
  ↓
分镜 Agent：拆成 6 到 8 个镜头
  ↓
生图 Agent：生成首帧、尾帧、九宫格候选
  ↓
质检 Agent：检查产品变形、Logo 清晰度、卖点表达
  ↓
视频 Agent：调用 DashScope / 可灵 / Seedance 生成视频
  ↓
交付 Agent：整理素材、导出项目包
```

### workflow.json 示例

```json
{
  "id": "ad-video",
  "name": "广告视频生产流",
  "steps": [
    {
      "id": "brief",
      "agent": "product-planner"
    },
    {
      "id": "storyboard",
      "agent": "storyboard-director",
      "dependsOn": ["brief"]
    },
    {
      "id": "frames",
      "agent": "image-generator",
      "dependsOn": ["storyboard"]
    },
    {
      "id": "quality-check",
      "agent": "visual-qa",
      "dependsOn": ["frames"]
    },
    {
      "id": "video",
      "agent": "video-producer",
      "dependsOn": ["quality-check"]
    }
  ]
}
```

### 编排规则

- 支持串行步骤。
- 支持并行步骤。
- 支持失败重试。
- 支持人工确认。
- 支持步骤产物传给下一个步骤。
- 支持中断和恢复。

### 验收标准

- 一个工作流可以完整跑完。
- 中间失败后不会丢失历史产物。
- 用户能从任意失败步骤继续。
- 每个 Agent 的输入输出可追溯。

## 8. 第六阶段：Skill 和 Agent 生态

目标：让 Lumi 能扩展，而不是每次都改主程序。

### SkillHub

当前 Skill 网站：

```text
https://www.skillhub.cn/skills
```

后续可以提供：

- 官方推荐 Skill。
- 用户上传 Skill。
- Agent 所需 Skill 自动检测。
- Skill 版本升级。
- Skill 权限展示。

### AgentHub

后续可新增 Agent 下载站：

```text
https://www.skillhub.cn/agents
```

先不急着做平台。可以先在文档里提供几个下载地址，启动器里只做“打开网站”和“上传 zip”。

## 9. 第七阶段：商业化和授权增强

目标：既方便客户使用，又减少复制盗用。

### 授权策略

- 授权码绑定安装 ID。
- U 盘版绑定稳定卷序列号，不绑定盘符。
- 客户换 U 盘需要后台人工解绑或换签。
- 授权文件不能内置在交付包里。
- 打包脚本必须清理 `data/license.json` 和 `data/install_id.txt`。

### 后续增强

- Rust 二进制内做核心验签。
- Python 侧只做辅助状态读取。
- 服务端增加授权设备管理。
- WebUI 增加授权码、设备、客户备注、激活次数管理。

### 验收标准

- 插拔 U 盘不需要重新授权。
- 换电脑但同一个 U 盘能正常使用。
- 复制到另一块 U 盘不能直接使用。
- 打包出来的新包默认未授权。

## 10. 第八阶段：跨平台交付

目标：Windows 和 Mac 都能运行，但不要强行共用同一份小文件目录。

### 推荐交付方式

```text
U盘/
  Windows/
    Lumi.exe
    LumiFiles/
  macOS/
    Lumi.app
    LumiFiles/
  SharedProjects/
    storyboards/
    exports/
```

### 不推荐

不要让 Windows 和 Mac 共用同一套 `node_modules` 和运行时目录。小文件太多，U 盘会很慢，也容易因为平台差异损坏。

### 验收标准

- Windows 包独立运行。
- Mac 包独立运行。
- 项目文件和导出素材可以共享。
- 运行时文件不跨平台混用。

## 11. 技术债治理路线

### 高优先级

- 授权核心迁移到 Rust。
- [x] Bridge API 返回结构统一，已落地 `_meta` 契约。
- [x] legacy Bridge route 退场，FastAPI native routes 成为主实现。
- [x] 品牌 profile 打包和 release 校验接入。
- [x] Vite / npm audit / Node 22 CI 收束。
- 视频 provider 抽象继续完善，支持 DashScope、可灵、Seedance。
- 打包脚本强制清理授权文件和本地隐私配置。
- 主要 UI 文案消除乱码。

### 中优先级

- Pydantic 模型补齐。
- Agent / Skill manifest 规范化。
- 日志事件结构化。
- 插件安装流程做成可恢复任务。
- 前端页面继续按功能域拆分。

### 低优先级

- 更漂亮的动效。
- 在线主题市场。
- 自动更新器深度集成。
- 云端任务同步。

## 12. 建议执行顺序

### 近期 1 到 2 周

1. 修复 U 盘授权稳定性。
2. 完成 Lumi 自用版 UI。
3. 打包并真实 U 盘测试。
4. 保持客户版和自用版可区分。

### 中期 1 个月

1. CLI 第一版。
2. Agent manifest 第一版。
3. Agent 管理页面第一版。
4. Agent Run Viewer 原型。

### 中期 2 到 3 个月

1. 广告视频工作流 Agent 化。
2. 多 Agent 串行编排。
3. 支持人工确认和重试。
4. SkillHub / AgentHub 下载入口。

### 长期 3 到 6 个月

1. Rust 授权核心。
2. 完整 Agent Orchestrator。
3. 插件生态和版本管理。
4. Mac 正式交付链路。
5. 授权后台设备管理完善。

## 13. 关键判断

Lumi 后续最值得做的不是单纯堆页面，而是建立三个稳定协议：

1. **能力协议**
   - UI、CLI、Skill、Agent 都调用同一套 Bridge API。

2. **扩展协议**
   - Skill 和 Agent 都用 manifest 描述自己。

3. **运行协议**
   - Agent 任务用 Run / Step / Artifact / Event 记录全过程。

这三层立住以后，Lumi 就不只是启动器，而是一个可以持续扩展的本地 Agent 平台。
