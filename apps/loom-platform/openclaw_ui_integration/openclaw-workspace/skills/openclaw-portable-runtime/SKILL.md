---
name: openclaw-portable-runtime
description: This skill should be used when the user asks about "U disk mode", "portable launcher", "where files are stored", "package the launcher", "OpenClaw portable runtime", "runtime context", or local OpenClaw paths.
version: 0.1.0
---

# OpenClaw Portable Runtime

Use this skill when working with the OpenClaw portable package layout.

## Principles

- Treat the install root as movable.
- Avoid hardcoded drive letters.
- Prefer paths from `runtime-context.json`.
- Keep runtime data under `data/`.
- Keep user secrets out of committed files and delivery packages.

## Important Paths

```text
OpenClaw.exe
OpenClawFiles/
OpenClawFiles/data/.openclaw/openclaw.json
OpenClawFiles/data/.openclaw/workspace/
OpenClawFiles/data/generated-images/
OpenClawFiles/scripts/
OpenClawFiles/imgapi_config.json
OpenClawFiles/video_config.json
```

In source/dev mode, the same paths exist under the launcher project root without `OpenClawFiles/`.

## Runtime Context

Refresh current context with:

```powershell
npm run openclaw:context -- --write
```

Read:

```text
data/.openclaw/workspace/runtime-context.json
```

Use it to discover:

- package root;
- launcher version;
- OpenClaw version;
- configured image/video APIs;
- phone Agent capability;
- generated image directory;
- policy for automatic phone image sync.

## Packaging

Before delivering a package:

1. Run launcher build checks.
2. Ensure `data/.openclaw/workspace` is included.
3. Ensure `imgapi_config.json` and `video_config.json` are empty JSON objects.
4. Ensure no token/API key is packaged.
5. Verify the final portable directory or zip with `verify-release.ps1`.
