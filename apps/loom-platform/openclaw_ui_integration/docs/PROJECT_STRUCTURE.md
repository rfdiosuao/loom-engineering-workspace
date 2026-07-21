# Project Structure

This document is the quick orientation map for the current Lumi / OpenClaw launcher repository.

## Canonical Workspace

Use this as the repository root:

```text
D:\Axiangmu\AUSTART
```

Use this as the active launcher project:

```text
D:\Axiangmu\AUSTART\openclaw_new_launcher
```

Do not treat `D:\Axiangmu\U盘启动器` as the source workspace. That path is only suitable for temporary package testing or historical portable-build output.

## Repository Layout

```text
D:\Axiangmu\AUSTART
├─ openclaw_new_launcher/      # Main Tauri + React + Python Bridge launcher
├─ license_server/             # Online license server
├─ scripts/                    # Repo-level verification, packaging, release scripts
├─ docs/                       # Repo-level branding, CI/CD, packaging docs
├─ data/                       # Local runtime state; state files are ignored
└─ release/                    # Local build outputs; ignored by git
```

## Launcher Layout

```text
openclaw_new_launcher/
├─ src/                        # React UI
│  ├─ components/              # Pages and shared UI components
│  ├─ features/                # Feature registry and page wiring
│  ├─ services/                # Frontend API client
│  ├─ stores/                  # Frontend state stores
│  ├─ styles/                  # Global CSS and theme variables
│  └─ theme/                   # Built-in theme defaults
├─ python/                     # Python bridge, FastAPI routes, services
│  ├─ api/                     # FastAPI route modules
│  ├─ core/                    # Paths, storage, license, theme primitives
│  └─ services/                # Image, video, process, update, skills services
├─ src-tauri/                  # Tauri/Rust shell, icons, packaging config
├─ data/themes/                # Brand/theme profiles
├─ docs/                       # Launcher docs and handoff notes
└─ scripts/                    # Launcher-local helper scripts
```

## Keep

- Source code under `src/`, `python/`, and `src-tauri/src/`.
- Theme profiles under `openclaw_new_launcher/data/themes/`.
- Current documentation listed in `openclaw_new_launcher/docs/DOCS_INDEX.md`.
- Build, release, verification scripts under repository `scripts/`.
- `license_server/` source and service files.

## Do Not Commit Or Ship

- `node_modules/`
- `dist/`
- `src-tauri/target/` or `src-tauri/target*/`
- `release/`
- `__pycache__/`, `*.pyc`, logs, IDE caches
- `data/license.json`
- `data/install_id.txt`
- API keys, license codes, server passwords, private keys, databases
- User bot binding cache or scanned-account state

## Removed Historical Areas

The old Tkinter launcher was removed and should not be restored:

```text
openclaw_launcher/
launcher.py
OpenClaw.spec
OpenClaw-USB.spec
clean_portable_package.ps1
```

The old rewrite/API/architecture snapshots were also removed. Use the current code and `DOCS_INDEX.md` instead of recreating those historical files.
