# TOOLS.md - Portable Launcher Tool Conventions

Use these conventions when working inside the OpenClaw portable package.

## Runtime

- Treat the package root as portable. It may be on a U disk and may not keep the same drive letter.
- Prefer paths from `runtime-context.json` over hardcoded paths.
- Prefer bundled Node from `node/node.exe` when available.
- Keep generated assets under `data/generated-images/`, `data/videos/`, or task-specific folders under `data/`.
- Hard rule: phone automation goes through launcher wrappers. Do not construct APKClaw URLs, ports, endpoint paths, auth headers, HMAC signatures, or token-bearing requests by hand.
- Do not hardcode APKClaw phone URL or token. The launcher writes the private phone config to `data/.openclaw/launcher/phone-agent.json`; CLI helpers read it automatically and must not print the token.
- Hard rule: do not hardcode or infer Luminode Desktop Agent ports, tokens, endpoint URLs, or auth headers. The launcher writes desktop sidecar config to `data/.openclaw/launcher/desktop-agent.json`; call it only through `/api/desktop-agent/*`.

## Desktop Agent

Use the desktop Agent only when `runtime-context.json` says `capabilities.desktopAgent.configured=true` or the user has just started it from the launcher Desktop Control page.

Preferred safe order:

1. `GET /api/desktop-agent/status`
2. `GET /api/desktop-agent/health`
3. `POST /api/desktop-agent/screenshot`
4. Decide one bounded action.
5. `POST /api/desktop-agent/click` or `POST /api/desktop-agent/type` with `confirmed=true` only after explicit user approval.
6. Verify with another screenshot.

For WeChat tasks, get explicit user intent before sending messages:

```text
POST /api/desktop-agent/wechat/unread
POST /api/desktop-agent/wechat/send
```

Preferred CLI wrappers:

```powershell
npm run desktop:agent -- status
npm run desktop:agent -- start
npm run desktop:agent -- screenshot --out .\data\desktop.png
npm run desktop:agent -- wechat unread
npm run desktop:reply -- observe
npm run desktop:reply -- once --text "reply text" --confirmed
```

Never request or print the raw token.
If the Bridge returns `blocked=true`, stop and report the launcher policy reason. Do not bypass with direct Luminode calls.

## Image To Phone

Use this command to generate or upload an image to the connected phone Agent:

```powershell
npm run phone:image -- --image .\data\generated-images\example.png --filename example.png
```

If API image generation is needed:

```powershell
npm run phone:image -- --prompt "describe the image"
```

If image-to-image editing is needed, use the dedicated edit wrapper. Do not tell the user this ability is missing when an image API is configured:

```powershell
npm run phone:image:edit -- --reference-image .\data\generated-images\input.png --prompt "keep the subject, change the background to a clean studio scene"
```

Default album: use `runtime-context.json` value `capabilities.phoneAgent.defaultAlbum`; fallback is `OpenClaw`.

Phone result should appear under:

```text
Pictures/<configured-album>
```

## Phone Video Capture

Use this command to control APKClaw phone recording and pull MP4 files back to the PC:

```powershell
npm run phone:video -- status
npm run phone:video -- start --max-seconds 60 --filename demo.mp4
npm run phone:video -- stop
npm run phone:video -- download --latest --out-dir .\data\phone-videos
```

Recording requires the Android screen-capture consent prompt on the phone. Use it for explicit debugging, demonstration, or collection tasks only.

## Phone Agent

Use the Android phone Agent only when the phone is online and authorized.

Preferred safe order:

1. Use `npm run phone:agent -- run --prompt "..." --mode observe` for reading/inspection.
2. Use `npm run phone:agent -- run --prompt "..." --mode safe` for ordinary user-requested phone actions.
3. Use `npm run phone:agent -- run --prompt "..." --mode full` only when the user explicitly requests broad automation.
4. Use `npm run phone:fleet -- list` to inspect configured devices, and `npm run phone:fleet -- run --target <id|id,id|all> --prompt "..." --mode observe|safe|full` for multi-device dispatch.
5. Use `npm run phone:agent -- history --limit 20` after long, timed-out, or unclear tasks to inspect the launcher-side task trail before sending a follow-up.
6. Use `npm run phone:vision` or `npm run phone:game` only for vision/game fallback and debugging.
7. Low-level phone APIs are implementation details of the launcher wrappers, not model-facing tools.

The launcher and bundled CLIs pair automatically and sign advanced requests. Do not call advanced phone endpoints without a launcher wrapper.

For collection or demonstrations, OpenClaw should plan the task and APKClaw should execute on the phone. Do not let OpenClaw become a manual phone remote unless the task is debugging or APKClaw has already failed enough to justify intervention.

APKClaw Agent has a hard 60-round budget per task. The launcher wrapper sends this as `--max-rounds 60` by default. For long product searches, jobs, feeds, or game tasks, ask for one bounded batch and return results to OpenClaw. Then OpenClaw decides whether to send a follow-up task.

For jobs, products, comments, search results, and other visible list tasks, ask the phone Agent to use `collect_list_items` instead of manually repeating `get_screen_info` plus `swipe`. Use `target=job` for jobs, `target=product` for products, and `target=generic` for other lists.

When the device profile says `vision.recommended=true`, do not force accessibility-tree scraping. First send APKClaw a clearer game/vision-oriented natural-language task. If APKClaw returns empty results, low confidence, or repeats failed actions, inspect `GET /api/lumi/vision/frame?overlayGrid=true&format=jpeg`, then either rewrite the next APKClaw Agent command or, as a fallback/debug step, execute `POST /api/lumi/vision/action`.

Use the game-mode loop when the screen is game/canvas/image-heavy:

```powershell
npm run phone:game -- run --goal "inspect this game screen"
npm run phone:game -- run --goal "open safe settings panel" --plan-body "{\"action\":\"tap\",\"gridCell\":\"F3\",\"targetLabel\":\"settings wrench\",\"reason\":\"open safe repair/settings panel\"}"
```

The plan must include `targetLabel` and `reason`. The launcher guard blocks login, authorization, payment, purchase, recharge, account binding, real-name, delete, clear-cache, upload-log, log-out, and exit-game targets.

CLI helpers:

```powershell
npm run phone:agent -- run --prompt "Search for budget headphones. Collect at most 10 visible product candidates using collect_list_items target=product, then return."
npm run phone:demo:shopping -- --query "拼多多 好玩又有性价比的商品"
npm run phone:demo:read
npm run phone:demo:game -- --goal "inspect the current game/canvas screen safely"
npm run phone:fleet -- list
npm run phone:fleet -- status --target all
npm run phone:fleet -- run --target all --prompt "Read the current screen on each phone and summarize visible app/page state." --mode observe
npm run phone:vision -- frame --out .\data\phone-frames\frame.jpg
npm run phone:vision -- action --force-action --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"safe menu button\",\"reason\":\"debug one known safe tap\"}"
```

Cold-start benchmark:

```powershell
npm run measure:cold-start -- --root <portable-root>
```

## Context Files

- `CAPABILITIES.md`: stable capability map.
- `runtime-context.json`: current portable runtime state.
- `skills/*/SKILL.md`: task-specific operating recipes.

## Reporting

When a task writes a file, report the exact path.

When a task sends something to the phone, report:

- local file path;
- phone album/path;
- upload status;
- retry command if it failed.

When a task pulls video from the phone, report:

- local MP4 path;
- recording id;
- file size;
- whether Android recording consent was required.
