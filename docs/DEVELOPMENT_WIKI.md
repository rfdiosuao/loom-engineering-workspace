# LOOM 开发 Wiki

这里是 LOOM 工程资料的唯一总入口。产品源码仍由平台仓和手机仓分别维护。

## 新成员从这里开始

1. 阅读[工作区架构图](architecture/workspace-map.md)，确认修改属于总控、平台还是手机端。
2. 阅读[并行开发手册](runbooks/parallel-development.md)，每个 Issue 使用独立 worktree。
3. 阅读[仓库卫生手册](runbooks/repository-hygiene.md)，不要从旧目录或构建产物目录提交代码。
4. 跨端修改先更新 `packages/contracts`，再分别创建平台 PR 和手机 PR。

## 文档地图

| 主题 | 文档 |
| --- | --- |
| 仓库与模块边界 | [Workspace Map](architecture/workspace-map.md) |
| 多仓决策依据 | [ADR 0001](decisions/0001-private-multi-repo-workspace.md) |
| 并行开发 | [Parallel Development](runbooks/parallel-development.md) |
| 清理与归档 | [Repository Hygiene](runbooks/repository-hygiene.md) |
| Agent/Matrix 生产设计 | [Production Design](superpowers/specs/2026-07-15-loom-agent-matrix-production-design.md) |
| 迁移记录 | [Migration Report](migration/migration-report-20260715.md) |

## 日常命令

```powershell
.\scripts\status.ps1
.\scripts\sync.ps1
.\scripts\verify.ps1 -Repository hub -Fast
```

创建平台工作树：

```powershell
.\scripts\new-feature.ps1 -Repository platform -Issue 123 -Name matrix-fix
```

`worktrees/` 只是被忽略的本地检出目录，不是子仓库，不应手工复制或直接删除。
