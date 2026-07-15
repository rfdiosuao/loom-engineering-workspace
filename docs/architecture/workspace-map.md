# Workspace Map

```text
GitHub Issue
    |
    v
LOOM Engineering Hub
    |-- versioned contracts
    |-- plans and architecture decisions
    |-- status, sync, verify and worktree automation
    |
    |-- LOOM Platform private repository
    |      |-- React and Tauri desktop application
    |      |-- Python control plane
    |      |-- Matrix scheduler and device registry
    |      `-- media, model, Feishu and delivery services
    |
    `-- Phone Agent private repository
           |-- Android application
           |-- deterministic and vision RPA
           |-- phone event stream and device APIs
           `-- phone-side safety and recovery
```

## Ownership Boundaries

The platform owns campaign planning, dispatch, supervision, cross-device state, deduplication, result aggregation, and operator UI. The phone Agent owns execution on one device, screen observation, deterministic actions, phone-local progress events, and bounded recovery.

Cross-repository payloads are versioned in `packages/contracts`. Neither repository copies an unversioned private data class from the other.

## First Product PR Series

1. Contract PR: per-device assignment, job state, event, result, and error schemas.
2. Platform PR: bounded-concurrency Matrix scheduler and per-device dispatch.
3. Phone PR: assignment acknowledgement and progress-event compatibility.
4. Platform UI PR: live fleet progress, targeted retry, and exception isolation.
5. Vertical demo PR: BOSS resume-screening queue partitioning and result aggregation.
