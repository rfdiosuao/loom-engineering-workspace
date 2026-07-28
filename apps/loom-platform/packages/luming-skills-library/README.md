# Luming Skills Library

This library ships one triggerable Skill: `luming-phone-agent`. It manages the
full phone-agent lifecycle: environment self-check, phone discovery, task and
recipe matching, weak-gate preflight, task-authorized automatic outbound and
routine mutations, verification, recipe sync, and a structured report.

## Included Skill

| Skill | Purpose |
| --- | --- |
| `luming-phone-agent` | Discover phones, compile or reuse verified tasks, supervise execution, and retain successful recipes. |

## Recipe Lifecycle

Recipes under `skills/luming-phone-agent/recipes/` use one of these statuses:

| Status | Meaning |
| --- | --- |
| `draft` | Candidate recipe that is not eligible for reuse. |
| `verified` | Reusable recipe with successful, evidenced verification. |
| `stale` | Previously known recipe that must be rechecked before reuse. |
| `blocked` | Recipe cannot proceed until its stated condition is resolved. |

The agent may sync only verified recipes. It keeps source and installed recipe
trees in parity and reports `synced` or `sync_pending` rather than claiming a
partial write succeeded.

## Migration And Ownership

`manifest.json` is the source of truth for retired trigger names replaced by
`luming-phone-agent`. The installer never deletes a directory merely because
its name appears in `manifest.replaces`. Removal requires both a matching
`.loom-skill-owner.json` marker and matching durable ownership state under the
installer `StateRoot`. Unowned user or third-party directories are preserved
and reported through `skippedUnowned`.

The installed Skill and the durable source mirror each preserve custom
`recipes/` entries during upgrades. New automation must target
`luming-phone-agent` only.

## Layout

```text
luming-skills-library/
  skills/
    luming-phone-agent/
      SKILL.md
      agents/
      examples/
      recipes/
      references/
      schemas/
      scripts/
  scripts/
    deterministic_zip.py
    install.ps1
    validate.ps1
    package.ps1
  manifest.json
```

## Install

The installer is host-neutral and requires an explicit Skills destination. It
never guesses that the caller is Codex and never creates another Agent's
configuration directory. Installation is serialized through a cross-process
lock. Before any mutation it writes a persistent transaction journal; a later
run recovers a process crash before starting the next upgrade.

```powershell
.\scripts\install.ps1 -Destination "<official-skills-directory-for-current-agent>"
```

Common destinations:

| Host | Destination or supported flow |
| --- | --- |
| Codex | `$env:CODEX_HOME\skills`, or `%USERPROFILE%\.codex\skills` when `CODEX_HOME` is unset |
| Claude Code | `%USERPROFILE%\.claude\skills` |
| CodeBuddy | `$env:CODEBUDDY_CONFIG_DIR\skills`, or `%USERPROFILE%\.codebuddy\skills` when unset |
| WorkBuddy | Import the verified ZIP through WorkBuddy's Skills UI; do not guess a private Skills directory |
| Unknown Agent | Do not run the installer until the host's official Skills directory is known |

WorkBuddy MCP configuration belongs in `<project>/.workbuddy/mcp.json` or
`~/.workbuddy/mcp.json`. It must not be written to `.codex`.

## Validate And Package

```powershell
.\scripts\validate.ps1
.\scripts\package.ps1
```

Validation checks the manifest-to-directory parity, every JSON document in the
unified Skill, the recipe-sync Python environment, and every contract test.
Packaging reads `manifest.skills`, includes only the declared Skill, and writes
the archive named by `BUNDLE_PROVENANCE.json`. The archive name is derived from
the manifest version rather than the machine clock. Entry ordering, timestamps,
permissions, and compression are deterministic, and the official build fails
unless the generated SHA256 exactly matches bundle provenance.

The product build command is:

```powershell
.\apps\loom-platform\scripts\build-luming-skills-library.ps1
.\apps\loom-platform\scripts\build-luming-skills-library.ps1 -VerifyOnly -SkipValidation
```

The first command rebuilds the launcher copy. The second independently rebuilds
and compares it. CI and release workflows run both checks; release publication
then verifies the GitHub and domestic mirrors by downloading the asset and
rechecking the provenance SHA256.

Keep product code and Skill authoring separate. Backend paths mentioned by the
Skill are architecture anchors unless implementation is explicitly requested.
