<p align="center"><strong>简体中文</strong> · <a href="README.en.md">English</a></p>

<p align="center">
  <img src="apps/loom-platform/openclaw_new_launcher/src/assets/luming-logo.svg" width="96" alt="LOOM Logo" />
</p>

<h1 align="center">麓鸣 AI 矩阵获客工作台</h1>

<p align="center">
  <strong>LOOM Engineering Workspace</strong><br />
  桌面平台、手机 Agent、矩阵控制、媒体生成、业务 Skills 与工程文档的统一主仓库。
</p>

<p align="center">
  <a href="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/workspace-ci.yml"><img alt="Workspace CI" src="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/workspace-ci.yml/badge.svg" /></a>
  <a href="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/platform-ci.yml"><img alt="Platform CI" src="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/platform-ci.yml/badge.svg" /></a>
  <a href="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/phone-ci.yml"><img alt="Phone Agent CI" src="https://github.com/rfdiosuao/loom-engineering-workspace/actions/workflows/phone-ci.yml/badge.svg" /></a>
  <img alt="Monorepo" src="https://img.shields.io/badge/repo-monorepo-006b5b" />
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Android-0b7285" />
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0%20or%20commercial-7a3e9d" /></a>
  <img alt="Status" src="https://img.shields.io/badge/status-active%20development-1f9d70" />
</p>

## 项目定位

麓鸣是一套面向矩阵化获客与手机自动化运营的本地总控工作台。它把桌面控制台、Android 手机 Agent、AI 智能体、媒体生成、矩阵任务、业务技能包和工程治理放在同一条产品链路里，目标是让销售、中介、招聘劳务等高重复获客场景可以稳定地批量执行、观察、追踪和复盘。

从 2026-07-22 起，本仓库是 LOOM 的唯一工程主仓库。平台端和手机端已经从旧的多仓库/子仓库模式合并为普通目录，不再以 submodule 或 gitlink 参与日常开发。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 手机矩阵控制 | 多台 Android 手机的连接、截图、任务下发、急停、状态回传和异常展示 |
| 中枢智能体 | 在 LOOM 内部调用平台能力、手机能力、媒体生成和只读监控能力 |
| 媒体生成 | 图片/视频生成任务、素材保存、本地素材库和手机相册传输链路 |
| 获客工作流 | 面向招聘、劳务、销售、中介等场景的线索处理与平台发布自动化 |
| Agent 接入 | Codex、Claude Code、其他 CLI/MCP Agent 通过提示词或 Skill 接入 LOOM |
| 工程治理 | 单仓库开发、统一脚本、统一 CI、统一文档和 PR 验证链路 |

## 仓库结构

```text
rfdiosuao/loom-engineering-workspace
|-- apps/
|   |-- loom-platform       # 桌面端、矩阵工作台、智能体、媒体生成、模型账号
|   `-- loom-phone-agent    # Android 手机 Agent、RPA、设备 API、视觉观察
|-- packages/
|   |-- contracts           # 跨端任务、事件、结果、错误与 Schema
|   `-- skills              # LOOM 业务 Skills 和对外接入能力包
|-- docs/                   # 开发 Wiki、架构决策、迁移记录、Runbook
|-- scripts/                # 工作区脚本、验证脚本、并行开发辅助脚本
|-- workspace.json          # 单仓库组件索引
`-- LOOM.code-workspace     # VS Code / Cursor 工作区入口
```

## 快速开始

首次进入仓库：

```powershell
.\scripts\bootstrap.ps1
```

查看当前工作区状态：

```powershell
.\scripts\status.ps1
```

创建功能 worktree：

```powershell
.\scripts\new-feature.ps1 -Area platform -Issue 101 -Name matrix-device-assignments
```

同步远端：

```powershell
.\scripts\sync.ps1
```

运行验证：

```powershell
.\scripts\verify.ps1
.\scripts\verify.ps1 -Area platform
.\scripts\verify.ps1 -Area phone
```

## 开发规则

- 只克隆一个仓库：`rfdiosuao/loom-engineering-workspace`。
- 只使用一个根 `.git`：`apps/loom-platform` 和 `apps/loom-phone-agent` 都不是子仓库。
- 一个 Issue 对应一个分支和一个 PR，跨平台/手机/合同的改动也放在同一个 PR 里。
- 分支统一使用 `codex/<issue>-<feature>` 或 `codex/<feature>`。
- `worktrees/` 只是本地并行 checkout 目录，不是 GitHub 仓库。
- 禁止提交 Token、密钥、授权码、数据库、日志、截图、APK、安装包、模型输出和本地配置。
- 合并前必须运行对应验证，并在 PR 中写清楚验证结果。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [开发 Wiki](docs/DEVELOPMENT_WIKI.md) | 新成员入口、目录地图、日常命令 |
| [工作区架构图](docs/architecture/workspace-map.md) | 单仓库边界、组件职责和代码位置 |
| [并行开发手册](docs/runbooks/parallel-development.md) | 多 Agent/多人并行开发方式 |
| [仓库卫生手册](docs/runbooks/repository-hygiene.md) | 如何保持仓库干净、可维护 |
| [ADR 0002 单仓库决策](docs/decisions/0002-single-repository-monorepo.md) | 为什么从多仓库切到 monorepo |
| [2026-07-22 迁移记录](docs/migration/MONOREPO_CUTOVER_20260722.md) | 子仓库合并来源、验证和回滚说明 |

## 历史仓库说明

旧的 `loom-luming-launcher` 和 `lumiapkclaw` 只作为迁移来源与短期回滚参考保留。至少一个正式版本从本仓库完成构建、安装、升级和回滚验证之前，不建议删除旧仓库；但新的产品 PR 不再从旧仓库发起。

## 安全

安全问题、凭据泄漏、授权绕过、手机控制越权、外部发布链路风险，请优先参考 [SECURITY.md](SECURITY.md)，并在修复 PR 中补充验证证据。

## 许可证

LOOM 自有代码采用双许可证模式：

- 开源许可：GNU Affero General Public License v3.0 only（`AGPL-3.0-only`），完整条款见 [LICENSE](LICENSE)。修改后通过网络提供服务时，需要按照 AGPL-3.0 向对应用户提供源代码。
- 商业许可：需要闭源分发、专有集成、白标/OEM 或不履行 AGPL 对应源代码义务时，必须取得单独商业授权，详见 [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md)。

第三方和上游组件继续适用各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。LOOM 名称、Logo 和其他品牌标识不因代码许可证而自动获得使用授权。
