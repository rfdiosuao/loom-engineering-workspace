<p align="center"><a href="README.md">简体中文</a> · <strong>English</strong></p>

<p align="center">
  <img src="apps/loom-platform/openclaw_new_launcher/src/assets/luming-logo.svg" width="96" alt="LOOM logo" />
</p>

<h1 align="center">LOOM AI Matrix Acquisition Workbench</h1>

<p align="center">
  A unified monorepo for the desktop platform, Android phone agent, device matrix, media generation, business skills, and engineering documentation.
</p>

LOOM is a local control workbench for multi-device customer-acquisition and mobile automation operations. It connects a Windows desktop console, Android agents, AI orchestration, media generation, matrix tasks, and reusable business skills into one observable product workflow.

## Core Capabilities

| Capability | Description |
| --- | --- |
| Phone matrix | Connect devices, capture screens, dispatch tasks, stop work, and collect status |
| Built-in agent | Call platform, phone, media, and read-only monitoring capabilities |
| Media pipeline | Generate images and videos, store assets locally, and transfer media to phones |
| Acquisition workflows | Automate repetitive recruiting, staffing, sales, and agency operations |
| Agent integration | Expose LOOM through prompts and skills for Codex, Claude Code, and MCP/CLI agents |
| Engineering governance | One repository, shared scripts, CI, documentation, and PR verification |

## Repository Layout

```text
apps/
  loom-platform/       Windows desktop platform and matrix workbench
  loom-phone-agent/    Android agent, RPA, device API, and visual observation
packages/
  contracts/           Cross-device task, event, result, error, and schema contracts
  skills/              Business skills and external integration packages
docs/                  Architecture, decisions, migration records, and runbooks
scripts/               Bootstrap, status, sync, worktree, and verification scripts
workspace.json         Component index
LOOM.code-workspace    VS Code / Cursor workspace
```

## Quick Start

Windows PowerShell:

```powershell
.\scripts\bootstrap.ps1
.\scripts\status.ps1
.\scripts\verify.ps1
```

Create a feature worktree:

```powershell
.\scripts\new-feature.ps1 -Area platform -Issue 101 -Name matrix-device-assignments
```

## Development Rules

- Clone only this monorepo; the platform and phone directories are not submodules.
- Use one issue, branch, and pull request for each coherent change.
- Run the relevant verification scope before requesting review.
- Never commit tokens, keys, databases, logs, screenshots, APKs, installers, model output, or local configuration.

Start with the [development wiki](docs/DEVELOPMENT_WIKI.md) and [workspace map](docs/architecture/workspace-map.md).

## Security

Report credential exposure, authorization bypass, device-control issues, or publishing-chain risks according to [`SECURITY.md`](SECURITY.md).

## License

LOOM-owned code is dual-licensed:

- [AGPL-3.0-only](LICENSE) for open-source use
- A separate [commercial license](LICENSE-COMMERCIAL.md) for proprietary distribution, white-label/OEM use, or integrations that cannot meet AGPL obligations

Third-party components remain under their own terms; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
