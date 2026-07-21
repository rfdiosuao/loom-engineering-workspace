# Super Installer Architecture

This page tracks the next installer/runtime-console direction for OpenClaw.

The target is a launcher that works like a complete control console:

- visitor mode for local setup and diagnostics
- Heang/NewAPI login for managed model sync
- manifest-driven online and offline packages
- component install, repair, rollback, and health checks
- unified wire sync to OpenClaw, Phone Agent, Desktop RPA, and media gateways
- concise UI states instead of exposed paths and raw provider settings

## Architecture Documents

Source documents in this repository:

```text
docs/OPENCLAW_SUPER_INSTALLER_ARCHITECTURE.md
docs/OPENCLAW_SUPER_INSTALLER_IMPLEMENTATION_PLAN.md
docs/OPENCLAW_RUNTIME_CONSOLE_MIGRATION_ARCHITECTURE.md
```

Keep this VitePress page as the public summary. Keep the source documents as the detailed engineering references until they are split into site-native pages.

## Current Direction

Use the Xinflo-style shape as a reference, but improve it for OpenClaw:

| Area | Direction |
| --- | --- |
| Account | Heang account login, scoped token, quota, model sync |
| Installer | release manifest, mirrors, sha256, signature, rollback |
| Runtime | OpenClaw as one managed engine, not the product center |
| Phone | one-click sync to `agnes-2.0-flash` |
| Desktop RPA | sync URL/API key/model from account |
| UI | status first, one action per state, diagnostics folded |

## Validation Gates

Before a release claims this installer direction is complete:

- online package installs from a clean machine
- full offline package runs without network
- visitor mode is usable
- account login syncs model access
- OpenClaw, Phone Agent, Desktop RPA, and image config sync independently
- long-running jobs survive route switches
- package verification catches secrets, dev URLs, missing components, and hash mismatch
