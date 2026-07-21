# Repository Hygiene Runbook

## Source Of Truth

| 内容 | 唯一来源 |
| --- | --- |
| 工程合同、架构和协作脚本 | `loom-engineering-workspace` |
| 桌面端产品源码 | `loom-luming-launcher` |
| Android 手机 Agent 源码 | `lumiapkclaw` |
| 对外安装包、APK 和 Skill ZIP | 发布渠道，不进入源码仓 |

不要把平台、手机和官网代码复制到总控仓。不要把 `AUSTART`、`U盘启动器`、下载目录或 `artifacts` 当作当前源码。

## Clean-State Check

```powershell
Set-Location D:\Axiangmu\LOOM-Workspace
.\scripts\status.ps1
git status --short --branch
git submodule status
```

总控仓只允许合同、文档、脚本和 Submodule 指针变化。平台或手机产品文件必须在对应仓库的 worktree 中修改。

## Worktree Lifecycle

1. 用 `scripts/new-feature.ps1` 创建，不手工复制源码目录。
2. 一个 Issue、一个分支、一个 worktree、一个 PR。
3. PR 合并前运行对应验证并确认没有密钥、日志、截图或安装包。
4. PR 合并后先确认 worktree 干净，再执行 `git worktree remove <path>`。
5. 最后执行 `git worktree prune`，清理已经不存在的登记项。

`worktrees/` 下目录数量不等于 GitHub 仓库数量。活跃任务可保留；只有已合并且干净的 worktree 才能移除。

## Repository Retirement

仓库只有在同时满足以下条件时才允许归档：

- 没有构建、CI、更新器或下载地址继续引用；
- 独有源码已经迁移并通过测试；
- 至少一个正式版本从新来源完成构建和回滚验证；
- README 指向新的唯一入口；
- GitHub 仓库先设为只读归档，不直接删除。

目录重命名、移动到 `legacy/` 或复制到另一个仓库，都不能代替上述审计。

## PR Scope Gate

打开 PR 前检查：

```powershell
git diff --check
git diff --stat origin/<base>...HEAD
git diff --name-status origin/<base>...HEAD
```

仓库治理 PR 不得混入 Agent 功能、UI、发布包或运行时行为修改。超过一个所有权边界时拆成关联 PR。
