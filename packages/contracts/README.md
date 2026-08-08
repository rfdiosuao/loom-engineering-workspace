# LOOM Contracts

This package owns versioned JSON Schemas shared between the LOOM platform, Phone Agent, Skills, and external integrations.

The first contract series will cover Matrix campaigns, per-device assignments, device events, task results, retry decisions, and error classification. Contract files use explicit schema identifiers and remain backward compatible within a released major version.

Published schema IDs are immutable compatibility boundaries. Optional fields may be added to an existing version, but a previously optional field cannot become required under the same `$id`. `loom.agent.run.v1` therefore continues to read the original v1 shape without `executionState`; `executionState`, `modelId`, and `modelSource` are optional public fields. Repository-only fields such as `ownerAccountId` and `request`, and an empty producer checkpoint, remain outside the public contract.

`packages/contracts/schemas` is the canonical source for the Platform test snapshots. The validator rejects duplicate canonical `$id` values and byte-level drift in `apps/loom-platform/openclaw_new_launcher/python/tests/contract_schemas`.

`loom.matrix.dispatch.v2` retains its published acceptance set. `loom.matrix.dispatch.v3` expresses the current consumer bounds (concurrency 1..8, 1..100 assignments, prompt up to 2000 characters, template ID up to 80 characters, and timeout 30..1200 seconds). `consumer-compatibility.v1.json` records that a v2-to-consumer adapter is still required; the contract package does not silently redefine v2.

`mobile-agent-runtime.schema.json` is the clean-room PoC contract shared by Desktop and LumiAgent for Provider schema discovery, scoped Workspace/Memory, lazy Skill metadata, typed native capabilities, backend fallback, and redacted traces. It deliberately excludes credential values and arbitrary shell commands.

`mobile-linux-runtime.schema.json` describes a separately reviewed optional Linux companion: fixed entrypoint identifiers, verified artifact/SBOM digests, bounded resources, account-scoped mounts, default-deny Provider networking, typed native offload, deterministic fallback, and user-file-preserving cleanup. The 2.4.2 APK does not bundle a rootfs or PRoot binary, and synthetic benchmark results cannot be used to claim a speedup.
