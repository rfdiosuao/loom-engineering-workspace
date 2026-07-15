# Parallel Development Runbook

## Start A Feature

```powershell
.\scripts\new-feature.ps1 -Repository platform -Issue 101 -Name matrix-device-assignments
```

The command creates `codex/101-matrix-device-assignments` in `worktrees/platform/101-matrix-device-assignments`. Assign exactly one Agent or engineer to that directory.

## Cross-Repository Feature

Create one worktree per repository with the same Issue number. Merge the contract PR first, update dependent branches to that contract commit, then merge platform and phone implementation PRs independently.

## Before Opening A PR

1. Run the repository-specific tests.
2. Run `scripts/status.ps1` and confirm only the intended worktree is dirty.
3. Inspect `git diff --check` and the complete changed-file list.
4. Confirm no local data, log, image, APK, key, or token is staged.
5. Include verification output and rollback notes in the PR body.

## After Merge

Fetch the private repository, remove the merged worktree with `git worktree remove`, delete the local feature branch, and run `scripts/status.ps1` again.
