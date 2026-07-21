# OpenClaw Portable Launcher Capability Map

This file is the stable capability map for OpenClaw when it runs inside the portable launcher. For current online/offline state, read `runtime-context.json`.

For product-level business scenarios, read `docs/OPENCLAW_APKCLAW_COMBINED_CAPABILITIES.md` in the launcher package.

## Portable Runtime

- Runs from a portable package, often copied to a U disk.
- Uses bundled Node.js and Python runtime when packaged.
- Stores launcher and OpenClaw data under `data/`.
- Keeps OpenClaw config at `data/.openclaw/openclaw.json`.
- Uses this workspace at `data/.openclaw/workspace`.
- Uses the active theme/profile from launcher runtime; do not hardcode merchant branding in Agent behavior.

## Launcher Capabilities

- Start, stop, and diagnose the local OpenClaw gateway.
- Manage API configuration for image and video generation.
- Generate images from an OpenAI-compatible image API.
- Generate videos from configured video providers.
- Manage theme/profile based launcher UI modules.
- Scan and display launcher/OpenClaw skills.
- Connect to the Android phone Agent over Wi-Fi.
- Pull phone screen recordings back to the PC for AI demo material collection.
- Host Luminode Desktop Agent as a local desktop execution sidecar for screenshots, coordinate clicks, typing, and WeChat-oriented workflows.

## Desktop Agent Capabilities

Luminode Desktop Agent is the local PC executor. The launcher owns process lifecycle, token storage, diagnostics, policy enforcement, and Bridge proxying. OpenClaw must call the launcher Bridge instead of connecting to Luminode directly.

Current first-stage tools:

- status, health, start, and stop via `npm run desktop:agent`;
- desktop screenshot;
- coordinate click;
- keyboard text input;
- WeChat send text;
- WeChat unread inspection;
- explicit desktop reply flow via `npm run desktop:reply`.

Private config:

```text
data/.openclaw/launcher/desktop-agent.json
```

Do not expose the token, infer the local port, or call Luminode endpoints directly. Use `runtime-context.json` and `/api/desktop-agent/*` routes. Mutating routes may require `confirmed=true` and can be blocked by launcher policy.

Safe CLI flow:

```powershell
npm run desktop:reply -- observe
npm run desktop:reply -- once --text "reply text" --confirmed
```

## Phone Agent Capabilities

The Android phone Agent currently supports:

- connection status and version checks;
- screenshots and screen tree inspection;
- device profile initialization, including model, RAM, storage, installed apps, current UI, and preferred browser;
- device profile vision hints for low-node, image-heavy, or game-like screens;
- signed game/vision mode frame capture through `npm run phone:vision`, including optional grid overlay and image-to-screen coordinate mapping;
- productized game/canvas loop through `npm run phone:game`: APKClaw Agent probe, signed vision frame, OpenClaw visual plan, launcher safety guard, APKClaw Agent guided execution, and after-frame verification;
- signed visual coordinate actions through `npm run phone:vision`; these now accept/return safety metadata and block obvious sensitive targets, but should still be used as debugging/fallback tools while the default path remains OpenClaw commanding APKClaw Agent through `npm run phone:agent`;
- fixed demo wrappers for product search, read-only screen summaries, and game/canvas fallback:
  - `npm run phone:demo:shopping`
  - `npm run phone:demo:read`
  - `npm run phone:demo:game`
- wake screen without bypassing lock screen;
- natural language Agent task execution;
- safe task policies: `observe_only`, `safe_action`, `full_access`;
- low-level tap, long press, swipe, drag, input text, system key, and open app tools;
- structured list collection through `collect_list_items` for jobs (`target=job`), products (`target=product`), comments, search results, and other visible feed/list tasks;
- visible cursor/action preview;
- PC image generation, image-to-image editing, and Android gallery import through `npm run phone:image` / `npm run phone:image:edit`;
- screen recording with Android MediaProjection user consent;
- phone-to-PC recording list and MP4 download.
- cold-start benchmark wrapper: `npm run measure:cold-start`.

Current validated phone version target:

```text
APKClaw 6.26 / versionCode 860
```

## Image Workflow

The preferred image workflow is:

1. Generate or receive an image on the PC.
2. Save it under `data/generated-images/` when possible.
3. If phone import is available and enabled, send it to the configured phone album.
4. Tell the user both the local path and phone path.

The image import API accepts:

- PNG
- JPEG
- WebP
- max 32MB per file

Phone-side result:

```text
Pictures/<configured-album>/<filename>
```

## Video Workflow

The preferred phone-video workflow is:

1. Let OpenClaw or a specialist Agent decide why a recording is needed.
2. Ask APKClaw to start recording only after the user intent is clear.
3. The user confirms the Android screen-capture prompt on the phone.
4. Stop the recording after the demonstration or collection window.
5. Pull the MP4 into `data/phone-videos/` and use it as local AI material.

Phone recording uses `npm run phone:video`, which owns the signed launcher channel internally.

## Commands

Upload an existing image:

```powershell
npm run phone:image -- --image .\logo_256.png --filename openclaw-output.png
```

Generate and upload:

```powershell
npm run phone:image -- --prompt "a clean app icon, cyan and gold"
```

Edit an image and upload:

```powershell
npm run phone:image:edit -- --reference-image .\data\generated-images\input.png --prompt "keep the subject, make the style cleaner and more commercial"
```

Run a bounded phone Agent task:

```powershell
npm run phone:agent -- run --prompt "Search for budget headphones. Collect at most 10 visible product candidates using collect_list_items target=product, then return." --mode safe
```

Start phone screen recording:

```powershell
npm run phone:video -- start --max-seconds 60 --filename demo.mp4
```

Stop recording and download the latest MP4:

```powershell
npm run phone:video -- stop
npm run phone:video -- download --latest --out-dir .\data\phone-videos
```

Capture a game/vision frame:

```powershell
npm run phone:vision -- frame --out .\data\phone-frames\frame.jpg
```

Run the game/canvas loop:

```powershell
npm run phone:game -- run --goal "inspect this game screen"
npm run phone:game -- run --goal "open safe settings panel" --plan-body "{\"action\":\"tap\",\"gridCell\":\"F3\",\"targetLabel\":\"settings wrench\",\"reason\":\"open safe repair/settings panel\"}"
```

Execute a visual grid action:

```powershell
npm run phone:vision -- action --force-action --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"safe menu button\",\"reason\":\"debug one known safe tap\"}"
```

Refresh runtime context:

```powershell
npm run openclaw:context -- --write
```

## Agent Collaboration Rule

APKClaw is the phone executor, not the product brain. OpenClaw and its specialist Agents should plan, choose policy, inspect results, and then command APKClaw through the safest available API.

Connection and budget rules:

- The launcher-saved phone URL/token live in private launcher config: `data/.openclaw/launcher/phone-agent.json` for legacy single-device config, or `data/.openclaw/launcher/phone-agents.json` for multi-device config.
- `runtime-context.json` intentionally does not expose the phone URL or raw token to model-facing context.
- Bundled phone CLIs read the launcher config automatically, so normal commands do not need `--phone-token`.
- Use `npm run phone:agent` for APKClaw Agent tasks. Raw APKClaw task APIs are not model-facing tools.
- Use `npm run phone:agent -- history --limit 20` to inspect recent APKClaw task outcomes, timeout classes, and launcher-side failure summaries before retrying.
- APKClaw Agent can run at most 60 rounds per task. Split long tasks into bounded batches and follow-ups.

## Trust Rules

- Do not expose secrets.
- Do not upload personal user files automatically.
- Do not start screen recording unless the user explicitly asked for collection, debugging, or demonstration material.
- Do not assume the phone is unlocked.
- Do not mutate Android settings in observe-only tasks.
- Keep the preferred browser from device profile; when Via Browser is detected, prefer it for browsing and downloads.
- Advanced phone capabilities must use launcher CLI wrappers. Plain token requests and raw phone endpoints are not model-facing tools.
- Game/vision plans must include a visible `targetLabel` and `reason`; block login, authorization, payment, purchase, recharge, account binding, real-name, delete, clear-cache, upload-log, log-out, and exit-game targets.
