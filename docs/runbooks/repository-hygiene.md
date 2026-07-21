# Repository Hygiene Runbook

## Source Of Truth

| 内容 | 唯一来源 |
| --- | --- |
| 平台端源码 | `apps/loom-platform` |
| Android 手机 Agent 源码 | `apps/loom-phone-agent` |
| 工程合同、架构和协作脚本 | `packages/contracts`、`docs`、`scripts` |
| 业务 Skill | `packages/skills` |
| 对外安装包、APK 和 Skill ZIP | 发布渠道，不进入源码仓库 |

不要把 `AUSTART`、`U盘启动器`、下载目录、安装目录、`artifacts` 或临时测试目录当作当前源码入口。

## Clean-State Check

```powershell
Set-Location D:\Axiangmu\LOOM-Workspace
.\scripts\status.ps1
git status --short --branch
git ls-files -s | Select-String ' 160000 '
```

最后一条命令不应该输出任何内容。`160000` 代表 gitlink，也就是旧 submodule 指针；单仓库治理后不允许再次出现。

## Worktree Lifecycle

1. 用 `scripts/new-feature.ps1` 创建，不手工复制源码目录。
2. 一个 Issue、一个分支、一个 worktree、一个 PR。
3. PR 合并前运行对应验证并确认没有密钥、日志、截图、安装包或授权码。
4. PR 合并后先确认 worktree 干净，再执行 `git worktree remove <path>`。
5. 最后执行 `git worktree prune`，清理已经不存在的登记项。

`worktrees/` 下的目录数量不等于 GitHub 仓库数量。它只是本地并行工作副本。

## Old Repository Retirement

旧平台仓库和旧手机仓库暂时只作为迁移来源与回滚参照保留。只有同时满足以下条件时才允许归档：

- 没有构建、CI、更新器或下载地址继续引用旧仓库。
- 独有源码已经迁移并通过测试。
- 至少一个正式版本从新仓库完成构建、安装、升级和回滚验证。
- README 和开发文档都指向新的唯一入口。
- GitHub 仓库先设为只读归档，不直接删除。

目录重命名、移动到 `legacy/` 或复制到另一个仓库，都不能代替上述审计。

## PR Scope Gate

打开 PR 前检查：

```powershell
git diff --check
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
```

治理 PR 不要混入产品运行时行为修改。产品 PR 可以跨平台和手机目录，但必须在 PR 描述里明确说明触达范围、验证结果和回滚方式。
