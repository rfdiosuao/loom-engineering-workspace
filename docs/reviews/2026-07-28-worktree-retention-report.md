# 历史 Worktree 保留与复核报告

## 审计口径

- 审计日期：2026-07-28
- 比较基线：`origin/main` at `4f2a01e40c2e0b777ec4f279e06969f962b4bc08`
- 动作：只读枚举；未删除、未移动、未清理任何 worktree 或分支。

## 必须保留

| Worktree | 原因 |
| --- | --- |
| `D:/Axiangmu/LOOM-Workspace` | 主 checkout 落后且含本地未提交/未跟踪内容，禁止自动处理 |
| `worktrees/features/parallel-installer-20260728` | 当前并行开发线 |
| `worktrees/features/parallel-model-gateway-20260728` | 当前并行开发线 |
| `worktrees/features/parallel-agent-runtime-20260728` | 当前并行开发线 |
| `worktrees/features/parallel-phone-matrix-20260728` | 当前并行开发线 |
| `worktrees/features/parallel-ui-journey-20260728` | 当前并行开发线 |
| `worktrees/features/parallel-release-governance-20260728` | 当前并行开发线 |

## 已合并，可复核后清理

以下分支已被 `git branch --merged origin/main` 判定为祖先，但仍需先确认 worktree 干净、无独有未跟踪文件，再由人工执行清理：

- `codex/agent-reliability-audit`
- `codex/brand-build-interface`
- `codex/ci-phone-process-lifecycle-20260722`
- `codex/comprehensive-debt-completion-20260726`
- `codex/license-dual-20260722`
- `codex/migrate-2.3.0-update-center`
- `codex/monorepo-cutover-20260722`
- `codex/pippit-video-provider`
- `codex/repository-hygiene-20260722`
- `codex/restore-desktop-auto-update`
- `codex/storyboard-model-auth-20260724`
- `codex/user-journey-reliability-20260724`
- `codex/yolo-vision-roadmap`

`worktrees/release/loom-2.3.21` 是 detached 发布证据 checkout，不因“已合并”自动删除。

## 需人工确认

以下现有 worktree 对应分支未合并到 `origin/main`，不得自动删除：

- `worktrees/audit/loom-comprehensive-20260726`
- `worktrees/features/loom-holistic-optimization-20260726`
- `worktrees/features/oem-completion-20260726`
- `worktrees/features/reliability-auto-update-20260726`
- `worktrees/release/loom-2.3.19`

任何清理前都必须再次运行：

```powershell
git worktree list --porcelain
git -C <worktree> status --short
git branch --merged origin/main
git branch --no-merged origin/main
```

本报告不是删除授权，也不证明分支内容已经发布。
