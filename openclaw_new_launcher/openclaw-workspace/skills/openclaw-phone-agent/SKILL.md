---
name: openclaw-phone-agent
description: This skill should be used when the user asks to "control my phone", "use phone Agent", "run APKClaw task", "inspect phone screen", "drag phone screen", "open an Android app", or perform Android automation through the portable launcher.
version: 0.1.0
---

# OpenClaw Phone Agent

Use this skill to control or inspect the connected Android phone through the phone Agent.

## Runtime Connection Rules

OpenClaw must not guess or hardcode the phone IP or token.

- Hard rule: send APKClaw Agent tasks only with launcher wrappers: `npm run phone:agent` for one phone and `npm run phone:fleet` for multiple phones. Do not call APKClaw task endpoints directly from generated shell, JavaScript, Python, browser code, or HTTP clients.
- Hard rule: do not construct phone URLs, endpoint paths, auth headers, signatures, or token-bearing requests manually.
- Read `runtime-context.json` for current phone state and capability limits.
- `runtime-context.json` exposes phone readiness and wrapper names, but it must not expose the raw phone URL or token.
- The raw token is saved by the launcher in `data/.openclaw/launcher/phone-agent.json`; prefer the launcher CLI helpers because they read this file automatically and do not print the token.
- Do not ask the user for the token when `phone.tokenAvailable=true`; use the configured launcher helpers instead.
- If the CLI reports missing token or missing phone URL, tell the user to fill the Phone Control page and click a phone action once so the launcher writes the config.

For CLI commands, rely on the launcher-saved Phone Control config:

```powershell
npm run phone:agent -- run --prompt "inspect the current phone screen safely" --mode observe
npm run phone:agent -- history --limit 20
npm run phone:fleet -- list
npm run phone:fleet -- run --target all --prompt "inspect each current phone screen safely" --mode observe
npm run phone:vision -- status
npm run phone:game -- run --goal "inspect the current phone screen safely"
npm run phone:video -- status
```

If a helper reports missing phone config, tell the user to save/test the Phone Control page once.

## Task Budget

APKClaw has a hard per-task planning budget of 60 rounds.

- Plan phone goals as short stages.
- For long shopping/search/research flows, ask APKClaw to collect a bounded batch, return results, then let OpenClaw decide the next task.
- If a task seems likely to exceed 60 rounds, split it before starting.
- If APKClaw returns `needs_vision`, `needs_followup`, timeout, or partial results, treat that as a handoff point, not a failure.
- After timeout, crash, unauthorized, accessibility-off, task-busy, or unclear results, inspect `npm run phone:agent -- history --limit 20` before retrying.
- `npm run phone:agent` sends a 60-round budget by default; use `--max-rounds <n>` only when the user explicitly asks for a different bounded budget.
- Do not instruct APKClaw to keep trying indefinitely.

## Preferred Control Path

Prefer natural language Agent tasks before low-level coordinate tools:

1. Check `/api/device/status`.
2. Wake the screen with `/api/device/wake` if needed.
3. Read signed `/api/lumi/device/profile` when device context matters.
4. Send natural-language tasks with `npm run phone:agent -- run --prompt "..." --mode observe|safe|full`.
5. If APKClaw reports low confidence, empty screen data, low-node/game-like UI, or repeated failure, read signed `/api/lumi/vision/frame` to diagnose.
6. Prefer rewriting the next APKClaw Agent command with clearer visual guidance.
7. Execute signed `/api/lumi/vision/action` or low-level `/api/tool/*` only for debugging, explicit coordinate tasks, or fallback after repeated APKClaw failure.

The launcher and CLI pair automatically through `/api/lumi/security/pair` and then sign `/api/lumi/*` requests. Do not bypass the launcher secure-channel helper for advanced operations.

OpenClaw is responsible for planning and evaluation. APKClaw is the Android-side executor: it observes, clicks, types, records, and returns structured state. Do not ask APKClaw to become the product brain.

## Tool Policies

- `observe_only`: screen reading, summaries, UI understanding. No mutation.
- `safe_action`: safe click/input/back/open-app tasks where user intent is clear.
- `full_access`: use only when the user explicitly asks for a broader phone automation task.

Default to `observe_only` for inspection and `safe_action` for ordinary phone operation.

For jobs, products, comments, search results, and other visible list tasks, instruct the phone Agent to use `collect_list_items`. Use `target=job` for jobs, `target=product` for products, and `target=generic` for other lists. This keeps OpenClaw as the planner while APKClaw performs structured collection on the phone.

For product search tasks, prefer this shape:

```text
Search for <query>. Collect at most 10 visible product candidates using collect_list_items target=product. Return title, price, store, visible rating/sales if present, and why each candidate looks cost-effective. Stop after one bounded collection pass and return results to OpenClaw.
```

If the device profile marks `vision.recommended=true`, treat the screen as vision-first but keep APKClaw as the executor. Send APKClaw a game/vision-oriented task first. Use `GET /api/lumi/vision/frame?overlayGrid=true&format=jpeg` to diagnose or guide the next instruction. Use `POST /api/lumi/vision/action` only when debugging, when the user gave an explicit coordinate action, or after APKClaw repeatedly fails.

For game/canvas screens, use the productized game loop:

1. Run the game probe and frame capture.
2. Inspect the saved frame.
3. Produce exactly one visual plan with `action`, `targetLabel`, `reason`, and coordinates.
4. Let the CLI safety guard check the plan.
5. Default to APKClaw Agent execution; direct coordinate action is only fallback/debug.
6. Capture the after-frame and verify the result before continuing.

CLI equivalent:

```powershell
npm run phone:agent -- run --prompt "inspect this game screen and return what is visible" --mode observe
npm run phone:game -- run --goal "inspect this game screen"
npm run phone:game -- run --goal "open safe settings panel" --plan-body "{\"action\":\"tap\",\"gridCell\":\"F3\",\"targetLabel\":\"settings wrench\",\"reason\":\"open safe repair/settings panel\"}"
npm run phone:vision -- frame --out .\data\phone-frames\frame.jpg
npm run phone:vision -- action --force-action --action-body "{\"action\":\"tap\",\"gridCell\":\"C7\",\"targetLabel\":\"safe menu button\",\"reason\":\"debug one known safe tap\"}"
```

Game/vision safety blacklist: never auto-tap login, authorization, payment, purchase, recharge, account binding, real-name, delete, clear-cache, upload-log, log-out, or exit-game targets. If a plan touches one of these, report it as blocked instead of forcing through.

## Screen Recording And Video Pull

For demonstrations, QA evidence, or AI material collection, use the launcher CLI:

```powershell
npm run phone:video -- start --max-seconds 60 --filename demo.mp4
npm run phone:video -- stop
npm run phone:video -- download --latest --out-dir .\data\phone-videos
```

Rules:

- Start recording only when the user clearly asked for recording, debugging evidence, or demo material.
- Android will show a screen-capture consent prompt; wait for the user to confirm it.
- After stopping, pull the MP4 to `data/phone-videos/` and report the exact local path.
- Never summarize or expose private chat/file content from the video unless the user explicitly asks and it is necessary.

## Before Running A Task

Verify:

- base URL is configured;
- token is available;
- phone Agent service is online;
- accessibility service is running;
- screen is on;
- phone is not locked when mutation is required.

If locked, tell the user to unlock manually. Do not bypass lock screen.

## Browser Preference

When opening URLs, searching, downloading APKs, or browsing web pages, prefer the browser marked as preferred in device profile. If Via Browser is detected, use it before Chrome or system browsers.

## Reporting

Report:

- task mode used;
- whether device profile context was included;
- visible result or final answer;
- any blocked action and reason.

Keep reports short and specific.
