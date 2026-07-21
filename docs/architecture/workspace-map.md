# Workspace Map

## Repository Topology

```text
rfdiosuao/loom-engineering-workspace
|-- apps/loom-platform        # Windows/macOS desktop, Python bridge, Matrix, Agent UI
|-- apps/loom-phone-agent     # Android phone Agent and device-side execution
|-- packages/contracts        # shared schemas and fixtures
|-- packages/skills           # LOOM skills and external Agent onboarding material
|-- docs                      # engineering wiki, decisions, runbooks and migration logs
|-- scripts                   # local workflow automation
`-- worktrees                 # ignored local checkouts, never pushed
```

This is now one Git repository. There are no submodules, gitlinks, or nested `.git` directories under `apps/`.

## Ownership Boundaries

The platform owns campaign planning, dispatch, supervision, cross-device state, deduplication, result aggregation, model/media orchestration, operator UI, and commercial license gates.

The phone Agent owns execution on one device, screen observation, deterministic actions, phone-local progress events, device recovery, and bounded phone-side safety behavior.

Cross-component payloads are versioned in `packages/contracts`. Platform and phone code should depend on these contracts rather than copying private classes from each other.

## Development Flow

```text
GitHub Issue
    |
    v
one branch in loom-engineering-workspace
    |
    |-- platform changes under apps/loom-platform
    |-- phone changes under apps/loom-phone-agent
    |-- contract changes under packages/contracts
    |-- skill changes under packages/skills
    `-- docs and scripts as needed
    |
    v
one pull request
```

The `workspace.json` file is the machine-readable source of component paths, verification commands, and the canonical repository URL.

## Active Baseline

| Component | Imported source |
| --- | --- |
| Platform | validated snapshot from `codex/18-stability-spine` plus local 2.2.0 changes |
| Phone Agent | validated phone PR snapshot from `lumiapkclaw` |
| Contracts and Skills | existing engineering workspace content |

For exact source commits, see [2026-07-22 cutover record](../migration/MONOREPO_CUTOVER_20260722.md).
