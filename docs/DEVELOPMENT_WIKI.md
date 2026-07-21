# LOOM 开发 Wiki

这里是麓鸣工程资料的唯一入口。平台端、手机 Agent、合同、Skills 和文档已经合并到同一个 Git 仓库，日常开发不再选择“平台仓库”或“手机仓库”。

## 新成员从这里开始

1. 阅读[工作区架构图](architecture/workspace-map.md)，确认代码目录和职责边界。
2. 阅读[并行开发手册](runbooks/parallel-development.md)，每个 Issue 使用独立 worktree。
3. 阅读[仓库卫生手册](runbooks/repository-hygiene.md)，不要从旧目录或构建产物目录提交代码。
4. 阅读[ADR 0002](decisions/0002-single-repository-monorepo.md)，理解为什么改成单仓库。
5. 查看[迁移记录](migration/MONOREPO_CUTOVER_20260722.md)，需要追溯旧提交时从这里找来源。

## 文档地图

| 主题 | 文档 |
| --- | --- |
| 仓库与模块边界 | [Workspace Map](architecture/workspace-map.md) |
| 单仓库决策 | [ADR 0002](decisions/0002-single-repository-monorepo.md) |
| 历史多仓库决策 | [ADR 0001](decisions/0001-private-multi-repo-workspace.md) |
| 并行开发 | [Parallel Development](runbooks/parallel-development.md) |
| 清理与归档 | [Repository Hygiene](runbooks/repository-hygiene.md) |
| Agent/Matrix 生产设计 | [Production Design](superpowers/specs/2026-07-15-loom-agent-matrix-production-design.md) |
| 单仓库迁移 | [Monorepo Cutover](migration/MONOREPO_CUTOVER_20260722.md) |

## 日常命令

```powershell
.\scripts\status.ps1
.\scripts\sync.ps1
.\scripts\verify.ps1
```

创建功能工作树：

```powershell
.\scripts\new-feature.ps1 -Area platform -Issue 123 -Name matrix-fix
```

`worktrees/` 只是被忽略的本地 checkout 目录，不是子仓库，不应该手工复制或直接删除。
