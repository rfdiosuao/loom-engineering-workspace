# Monorepo Cutover 2026-07-22

## Purpose

This record explains how LOOM moved from a private engineering hub plus child repositories into one active monorepo.

## Canonical Repository

`https://github.com/rfdiosuao/loom-engineering-workspace.git`

## Imported Sources

| Component | Source | Commit |
| --- | --- | --- |
| Engineering hub base | `loom-engineering-workspace` after governance PR #18 | `e57f849` |
| Platform stable source | `loom-luming-launcher` branch `codex/18-stability-spine` | `25653a0` |
| Platform validated snapshot | local integration snapshot | `e45e244` |
| Phone baseline | `lumiapkclaw` baseline | `c27250e` |
| Phone imported PR head | phone progress-log contract PR snapshot | `c601c42` |

The platform snapshot includes the 2.2.0 local work that had not yet been pushed to the old platform repository, plus conflict resolutions in feature access and creative media UI tests.

## Validation Before Import

Platform snapshot validation:

- `npm run build`: passed.
- `npm run test:platform-contracts`: 136 passed.
- `npm run test:node-contracts`: 63 passed.
- `python -m pytest python\tests -q`: 1325 passed with one non-blocking collection warning.

Rust `cargo check` could not run locally because the machine did not have Visual Studio C++ Build Tools / `link.exe`. GitHub Windows runners are expected to cover this in root CI.

Phone source imported from the validated PR snapshot. Existing phone CI had passed on that PR before import.

## Cutover Rules

- `apps/loom-platform` and `apps/loom-phone-agent` are ordinary directories.
- `.gitmodules` is removed.
- No gitlink mode `160000` entries are allowed.
- No nested `.git` directories are allowed under app folders.
- New product work starts from the monorepo.
- Old component repositories are read-only references until at least one formal monorepo release completes build, install, upgrade and rollback validation.

## Rollback Reference

If a production release must be traced back to pre-cutover sources, use the commits listed above and the old component repositories. Do not re-open normal product development in the old repositories without a new ADR.
