# ADR 0002: Single Repository Monorepo

- Status: Accepted
- Date: 2026-07-22

## Context

LOOM development had grown into a platform repository, a phone Agent repository, a governance hub, generated release folders, local installer directories, and several historical workspaces. Even with scripts, engineers and Agents still had to decide which repository owned a change. Cross-cutting work such as Matrix dispatch, phone screenshots, Agent capability routing, media generation, licensing, and installer stability often required linked PRs across multiple repositories.

That split made the product harder to reason about and made parallel Agent work slower than necessary.

## Decision

Use the public `rfdiosuao/loom-engineering-workspace` repository as the single source repository for active LOOM engineering.

Platform code lives under `apps/loom-platform`. Android phone Agent code lives under `apps/loom-phone-agent`. Contracts, Skills, scripts and docs remain in the same repository. There are no submodules, gitlinks, or nested Git repositories under `apps/`.

Old platform and phone repositories are retained read-only as migration provenance and rollback references until a formal release from the monorepo is validated.

## Consequences

- One clone, one branch and one PR can cover platform, phone, contracts and docs.
- CI must move to root-level workflows, because nested `.github/workflows` directories do not run from imported app folders.
- Release workflows need explicit component paths and component-specific tag policy.
- Historical commits remain available through migration records and old repositories.
- Repository hygiene checks must reject future gitlinks and nested `.git` directories.
