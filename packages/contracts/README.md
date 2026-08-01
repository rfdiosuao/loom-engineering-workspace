# LOOM Contracts

This package owns versioned JSON Schemas shared between the LOOM platform, Phone Agent, Skills, and external integrations.

The first contract series will cover Matrix campaigns, per-device assignments, device events, task results, retry decisions, and error classification. Contract files use explicit schema identifiers and remain backward compatible within a released major version.

`mobile-agent-runtime.schema.json` is the clean-room PoC contract shared by Desktop and LumiAgent for Provider schema discovery, scoped Workspace/Memory, lazy Skill metadata, typed native capabilities, backend fallback, and redacted traces. It deliberately excludes credential values and arbitrary shell commands.

`mobile-linux-runtime.schema.json` describes a separately reviewed optional Linux companion: fixed entrypoint identifiers, verified artifact/SBOM digests, bounded resources, account-scoped mounts, default-deny Provider networking, typed native offload, deterministic fallback, and user-file-preserving cleanup. The 2.4.2 APK does not bundle a rootfs or PRoot binary, and synthetic benchmark results cannot be used to claim a speedup.
