# Parallel Development Runbook

## Start A Feature

```powershell
.\scripts\new-feature.ps1 -Area platform -Issue 101 -Name matrix-device-assignments
```

The command creates a branch such as `codex/101-matrix-device-assignments` and a local checkout under `worktrees/features/101-matrix-device-assignments`. Assign exactly one Agent or engineer to that directory.

`-Area` is only a label for intent. It does not select another repository. Valid values are `platform`, `phone`, `contracts`, `skills`, `docs`, and `cross-cutting`.

## Cross-Component Feature

Use one branch and one PR when a feature touches platform, phone, contracts or skills together.

Recommended order inside the same branch:

1. Update contracts or fixtures first.
2. Update platform and phone implementations.
3. Update UI, docs and tests.
4. Run `scripts/verify.ps1` or the narrower area verification.
5. Explain all touched areas in the PR body.

## Before Opening A PR

1. Run the relevant tests.
2. Run `scripts/status.ps1` and confirm only the intended worktree is dirty.
3. Inspect `git diff --check` and the complete changed-file list.
4. Confirm no local data, log, image, APK, installer, key, token, authorization code, or customer file is staged.
5. Include verification output and rollback notes in the PR body.

## After Merge

Fetch the repository, remove the merged worktree with `git worktree remove`, delete the local feature branch if no longer needed, and run `scripts/status.ps1` again.
