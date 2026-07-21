# LOOM Engineering Workspace

麓鸣 AI 矩阵获客工作台的唯一工程主仓库。

从 2026-07-22 起，平台端、手机 Agent、合同、Skills 和工程文档都在这个仓库里统一开发、统一开分支、统一提 PR。以前分散在多个私有仓库里的源码已经导入为普通目录，不再以 submodule 或子仓库方式参与日常开发。

## 唯一入口

| 内容 | 路径 | 职责 |
| --- | --- | --- |
| LOOM 平台 | `apps/loom-platform` | 桌面端、矩阵工作台、智能体、媒体生成、模型账号、飞书与交付链路 |
| 手机 Agent | `apps/loom-phone-agent` | Android 端、手机控制、RPA、视觉观察、设备 API 与事件回传 |
| 跨端合同 | `packages/contracts` | 任务、设备、事件、结果与错误 Schema |
| 业务 Skills | `packages/skills` | 麓鸣对外接入、招聘获客、矩阵监控等能力包 |
| 工程文档 | `docs` | 架构、决策、迁移记录、开发 Wiki 与操作手册 |

本机推荐工作目录是 `D:\Axiangmu\LOOM-Workspace`。`AUSTART`、`U盘启动器`、`Downloads`、`artifacts` 和安装包输出目录都不是产品源码入口。

## 现在只有一个 GitHub 仓库

```text
rfdiosuao/loom-engineering-workspace
|-- apps/loom-platform
|-- apps/loom-phone-agent
|-- packages/contracts
|-- packages/skills
|-- docs
`-- scripts
```

日常规则很简单：

- 一次克隆：只克隆 `rfdiosuao/loom-engineering-workspace`。
- 一个根 `.git`：`apps/loom-platform` 和 `apps/loom-phone-agent` 不是子仓库。
- 一个功能分支：跨平台和手机的功能也在同一个分支里完成。
- 一个 PR：同一件事不要再拆成平台 PR、手机 PR、合同 PR。
- `worktrees/` 只是本地并行 checkout，不是 GitHub 仓库。

旧的 `loom-luming-launcher` 和 `lumiapkclaw` 只作为迁移来源与短期回滚参照保留。至少一个正式版本从本仓库完成构建、安装、回滚验证之前，不删除旧仓库，也不要从旧仓库继续开新产品 PR。

## 常用命令

首次进入仓库：

```powershell
.\scripts\bootstrap.ps1
```

查看当前状态：

```powershell
.\scripts\status.ps1
```

创建功能 worktree：

```powershell
.\scripts\new-feature.ps1 -Area platform -Issue 101 -Name matrix-device-assignments
```

可选区域包括 `platform`、`phone`、`contracts`、`skills`、`docs`、`cross-cutting`。这只是用于命名和说明改动范围，不会切换到另一个仓库。

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

## 并行开发规则

- 一个 Issue 对应一个分支和一个 PR。
- 一个 Agent 或工程师只进入自己的 worktree。
- 分支统一使用 `codex/<issue>-<feature>` 或 `codex/<feature>`。
- 禁止提交 Token、密钥、授权码、数据库、日志、截图、APK、安装包、模型输出和本地配置。
- 合并前必须运行对应验证，并在 PR 里写清楚验证证据。

更多说明见：

- [开发 Wiki](docs/DEVELOPMENT_WIKI.md)
- [工作区架构图](docs/architecture/workspace-map.md)
- [并行开发手册](docs/runbooks/parallel-development.md)
- [仓库卫生手册](docs/runbooks/repository-hygiene.md)
- [单仓库决策 ADR 0002](docs/decisions/0002-single-repository-monorepo.md)
- [2026-07-22 迁移记录](docs/migration/MONOREPO_CUTOVER_20260722.md)
