# LOOM Engineering Workspace Design

## Objective

Create a clean engineering control workspace for LOOM that makes the active platform and phone code obvious, preserves every current source file, prevents private material from reaching public repositories, and supports one feature per branch, worktree, agent, and pull request.

## Source Of Truth

| Area | Local migration source | GitHub source of truth | Visibility |
| --- | --- | --- | --- |
| LOOM platform | `D:\Axiangmu\AUSTART` | `rfdiosuao/loom-luming-launcher` | Private |
| Phone Agent | `D:\Axiangmu\AUSTART\apkclaw\Hermes-Agent-phone-codex-template-parameter-extraction` | `rfdiosuao/lumiapkclaw` | Private |
| Public distribution | Existing public-safe files only | `rfdiosuao/lumi` | Public |
| Engineering workspace | `D:\Axiangmu\LOOM-Workspace` | `rfdiosuao/loom-engineering-workspace` | Private |

The public `rfdiosuao/lumi` repository is not a development remote for private LOOM source. The existing `AUSTART` directory remains untouched as a migration source until the new workspace has been verified.

## Workspace Layout

```text
D:\Axiangmu\LOOM-Workspace\
|-- README.md
|-- LOOM.code-workspace
|-- apps\
|   |-- loom-platform\
|   `-- loom-phone-agent\
|-- packages\
|   |-- contracts\
|   `-- skills\
|-- docs\
|   |-- architecture\
|   |-- decisions\
|   |-- plans\
|   `-- runbooks\
|-- scripts\
|   |-- status.ps1
|   |-- new-feature.ps1
|   |-- sync.ps1
|   `-- verify.ps1
|-- worktrees\
`-- artifacts\
```

`apps/loom-platform` and `apps/loom-phone-agent` are Git submodules backed by the two private source repositories. `worktrees` and `artifacts` are local-only directories. The root repository contains engineering policy, cross-repository contracts, documentation, and orchestration scripts, not duplicate application source.

## Migration Policy

1. Do not delete, rename, or clean files in either legacy source checkout.
2. Create `codex/workspace-baseline-20260715` in each source repository.
3. Include application source, tests, build configuration, product documentation, and reusable skills.
4. Exclude build output, dependency caches, logs, screenshots, APK/AAB files, signing keys, local configuration, databases, tokens, generated media, and runtime state.
5. Run filename and content secret checks before staging and before every push.
6. Push baseline branches only to private GitHub repositories.
7. Point the workspace submodules at the verified baseline commits.

## Parallel Development Contract

Every feature starts from a GitHub Issue and receives:

- branch: `codex/<issue>-<feature>`
- worktree: `worktrees/<repository>/<issue>-<feature>`
- one owning Codex task or engineer
- one focused pull request
- required build and test evidence

Agents never share a checkout. Cross-repository work uses separate PRs linked by the same issue and a versioned contract in `packages/contracts`. Contract changes merge before dependent implementation PRs unless stacked PRs are explicitly declared.

## Repository Protection

- All engineering repositories are private.
- Pull requests target the protected default branch.
- Direct pushes to the default branch are prohibited by policy.
- PRs require a clean secret scan and repository-specific verification.
- Generated files remain outside Git through `.gitignore` rules.
- Public release publication is a separate reviewed workflow.

## Workspace Experience

`README.md` is the human dashboard. It shows active repositories, current baseline, common commands, architecture boundaries, and the next development priorities. `LOOM.code-workspace` opens only the engineering hub, platform, phone Agent, contracts, and skills. `scripts/status.ps1` reports branch, dirty state, upstream divergence, and worktree inventory without printing secrets.

## Acceptance Criteria

1. `D:\Axiangmu\LOOM-Workspace` opens as one focused workspace.
2. Both source repositories are linked to private GitHub repositories.
3. Current core source is present on private baseline branches.
4. Legacy checkouts still exist and retain their original files.
5. Workspace status, sync, verification, and feature-worktree scripts run successfully.
6. The engineering hub is pushed to a private GitHub repository.
7. No signing key, token, local database, log, APK, or generated screenshot is tracked by the engineering hub.

## Deferred Product Work

True per-device parallel Matrix dispatch is the first product feature after workspace migration. Its implementation will use a separate design and PR series covering device assignments, bounded concurrency, per-device events, deduplication, and targeted retry.
