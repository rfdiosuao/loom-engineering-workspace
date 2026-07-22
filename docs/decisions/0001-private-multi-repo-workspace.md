# ADR 0001: Private Multi-Repository Engineering Workspace

- Status: Superseded by [ADR 0002](0002-single-repository-monorepo.md)
- Date: 2026-07-15

## Context

LOOM platform code, Phone Agent code, public distribution material, experimental projects, generated output, and local runtime state previously lived under broad development directories with multiple Git roots. This made repository selection ambiguous and made parallel Agent work risky.

## Decision

Use a private engineering hub with the platform and Phone Agent linked as independent private Git repositories. Keep generated output and worktrees local. Keep the public `rfdiosuao/lumi` repository outside the private development flow.

## Consequences

- Platform and phone changes can ship through independent PRs and CI.
- Cross-repository work requires a versioned contract and linked PRs.
- A fresh clone requires private GitHub access and submodule initialization.
- The legacy `AUSTART` checkout remains available until migration verification is complete.

## Supersession

On 2026-07-22 this approach was replaced by a single public monorepo. The old decision remains as historical context for why the engineering workspace was first separated from public distribution material.
