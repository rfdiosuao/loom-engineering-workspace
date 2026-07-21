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

## Migration

`manifest.json` records the five retired triggers that are replaced by
`luming-phone-agent`:

- `luming-acquisition-agent`
- `luming-boss-resume-screening`
- `luming-matrix-supervisor-loop`
- `luming-phone-scenario-builder`
- `luming-scenario-skill-writer`

Installations remove those retired names and install the unified Skill. New
automation must target `luming-phone-agent` only.

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
    install.ps1
    validate.ps1
    package.ps1
  manifest.json
```

## Install

The installer is host-neutral and requires an explicit Skills destination. It
never guesses that the caller is Codex and never creates another Agent's
configuration directory.

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
`dist/luming-skills-library-YYYYMMDD.zip` with forward-slash ZIP entries.

Keep product code and Skill authoring separate. Backend paths mentioned by the
Skill are architecture anchors unless implementation is explicitly requested.
