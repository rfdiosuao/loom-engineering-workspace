---
name: loom-command-brain
description: "Use when Codex, Claude Code, or another agent needs to operate LOOM/Luming through CLI or MCP: inspect capabilities, configure models, dispatch or monitor phone workers, read screenshots/logs, run phone templates, capture phone video, use phone vision/media/publish helpers, recover ADB/phone connection issues, or turn repeated phone work into reusable templates."
---

# LOOM Command Brain

Use LOOM as the local control plane. Codex is the Command Brain; LOOM is the Matrix Control Plane; each connected APKClaw phone is a Phone Worker.

## Path Discovery

Never assume one developer machine path.

1. Resolve Codex home:
   - Use CODEX_HOME if set.
   - Windows fallback: %USERPROFILE%\.codex
   - macOS/Linux fallback: $HOME/.codex
2. Resolve LOOM home:
   - Use LOOM_HOME if set.
   - If running inside source, find openclaw_new_launcher/python/loom_cli.py.
   - Windows fallbacks: %LOCALAPPDATA%\LOOM, %ProgramFiles%\LOOM, D:\LOOM, C:\LOOM.
   - macOS fallbacks: /Applications/LOOM.app/Contents/Resources, ~/Applications/LOOM.app/Contents/Resources, ~/Library/Application Support/LOOM.
   - Linux fallbacks: /opt/loom, ~/.local/share/LOOM.
3. Resolve LOOM package root:
   - Prefer the directory that contains package.json and python/loom_cli.py.
   - If CLI and npm helper roots differ, ask loom_cli.py commands --json for the concrete helper path.

## First Move

Run the capability catalog before taking action:

python -B "<LOOM_HOME>/python/loom_cli.py" commands --json

Prefer MCP tools when available. Prefer CLI when you need deterministic JSON, dry-runs, or local subprocess verification. Every CLI command must include --json; use --dry-run before destructive or unfamiliar actions.

## Capability Map

- System: status, commands, models
- Account/model wire: account current, account sync, wire current, wire custom, wire verify, wire rollback
- Agents: agents list, agents start, agents model-status, agents model-apply, agents model-rollback
- Single phone via loom_cli.py: phone status, phone screenshot, phone read, phone events-start, phone events-status, phone events-stop, phone template-task, phone quick-task
- Phone npm helpers from LOOM package root: phone:agent, phone:vision, phone:video, phone:image, phone:image:edit, phone:fleet, phone:game, phone:publish, phone:relay, phone:relay:check, phone:relay:smoke, phone:demo:shopping, phone:demo:read, phone:demo:game
- LOOM phone npm aliases: loom:phone, loom:phone:fleet, loom:phone:vision, loom:phone:video, loom:phone:publish
- Phone recovery: phone adb-doctor with --permission admin
- Matrix: matrix status, matrix dispatch, matrix watch, matrix retry, matrix cancel
- Media config/generation: media config, media save-image, media save-video, media test-image, media test-video, media image, media video
- Templates and experience: template run, experience report, logs ledger

## Operating Rules

1. Use Direct -> Template -> Agent. Screenshots, status checks, Back, Home, and read-screen should not call a deep model.
2. During a running phone task, do not repeatedly interrupt the Phone Worker. Watch events and logs instead: matrix watch, jobs get, logs ledger.
3. For correction, inspect first: phone screenshot or phone read; then decide retry, cancel, or dispatch a narrower task.
4. For multi-phone work, dispatch once, then supervise by events. Codex should do macro-control, not micromanage every tap.
5. For outbound messages, comments, private messages, publishing, batch reach-out, account changes, or paid actions, require explicit user confirmation.
6. Never print or store raw API keys, tokens, passwords, launcher secrets, or phone tokens.
7. For npm run phone:* commands, work from LOOM package root, always add --json, and prefer saved launcher phone config. Pass --phone-url / --phone-token only for explicit debugging.
8. Phone screen recording requires clear user intent and may show an Android screen-capture consent prompt for every phone:video start.
9. Generated HTML, Markdown, scripts, and config files must be UTF-8. HTML files must include <!doctype html>, <html lang="zh-CN">, <meta charset="UTF-8">, and a viewport meta tag.
10. If Computer Use, Node REPL, Browser, Chrome, or desktop automation tools are unavailable, do not stop the task. Continue through LOOM CLI/MCP, local file edits, direct phone/matrix commands, phone npm helpers, and concise manual handoff only for login, captcha, payment, 2FA, or OS permission prompts.

## Tool Fallback

Some models can chat but cannot call Codex tools. In that case, they cannot be made into a full desktop operator by prompt alone.

Use this fallback order:

1. Continue deterministic work with LOOM CLI or MCP.
2. Use Browser or Chrome tooling for web tasks if available.
3. Use phone screenshot, phone read, template run, or matrix dispatch for phone work.
4. Use npm run phone:vision, phone:video, phone:image, phone:fleet, phone:game, or phone:publish when the needed phone ability is not exposed in loom_cli.py.
5. If the selected model cannot call tools, switch to a tool-capable Codex model or a LOOM-configured text model with tool support.
6. Pause only for user-owned secrets, verification codes, payments, 2FA, OS capture permission prompts, or irreversible actions.

## Phone CLI Surface

There are two phone command layers:

- python -B "<LOOM_HOME>/python/loom_cli.py" ... --json: LOOM control-plane commands, best for status, Matrix, templates, logs, and ADB recovery.
- npm run phone:* -- ... --json from LOOM package root: bundled OpenClaw helpers, best for APKClaw Agent, low-level vision, recording, image upload/generation, multi-device fan-out, game/canvas fallback, and publish relay work.

Use the capability catalog first, then choose the narrowest layer.

| Need | Preferred command |
| --- | --- |
| Current phone health | python -B "<LOOM_HOME>/python/loom_cli.py" phone status --json |
| One screenshot | python -B "<LOOM_HOME>/python/loom_cli.py" phone screenshot --json |
| Read current screen | python -B "<LOOM_HOME>/python/loom_cli.py" phone read --prompt "Read the current screen." --json |
| Run a bounded task | npm run phone:agent -- run --prompt "..." --mode safe --json |
| Submit/watch/cancel async Agent work | npm run phone:agent -- submit/status/cancel --json |
| Runtime speed/queue metrics | npm run phone:agent -- metrics --json |
| Signed phone event stream | npm run phone:agent -- events-sync --json or loom_cli.py phone events-start/status/stop --json |
| Fast screen tree or profile read | npm run phone:vision -- read --json |
| Vision frame with grid | npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json |
| Explicit guarded visual action | npm run phone:vision -- action --force-action --action-body-file ./action.json --json |
| Start/stop/download phone recording | npm run phone:video -- start/stop/download --json |
| Generate or upload image to phone | npm run phone:image -- --prompt "..." --json or npm run phone:image -- --image ./file.png --json |
| Edit image and upload | npm run phone:image:edit -- --reference-image ./input.png --prompt "..." --json |
| Run one task on several APKClaw devices | npm run phone:fleet -- run --target all --prompt "..." --mode observe --concurrency 2 --json |
| Game/canvas visual loop | npm run phone:game -- run --goal "..." --json |
| Direct or reverse platform publish | npm run phone:publish -- --platform xiaohongshu --title "..." --body "..." --json |
| Publish relay server/check/smoke | npm run phone:relay -- ..., npm run phone:relay:check -- ..., npm run phone:relay:smoke -- ... |
| Demo wrappers | npm run phone:demo:shopping -- --query "..." --json; npm run phone:demo:read -- --json; npm run phone:demo:game -- --goal "..." --json |
| LOOM aliases | npm run loom:phone -- ...; npm run loom:phone:vision -- ...; npm run loom:phone:video -- ...; npm run loom:phone:fleet -- ...; npm run loom:phone:publish -- ... |

Common npm helper options: --device-id, --phone-url, --phone-token, --json. Keep raw tokens out of logs and files.

## Decision Tree

Need to know what LOOM can do: run commands --json, then read data.codexCommandBrain.

Need to configure models: use models, wire current, account current, then agents model-status. Apply only when the user wants LOOM-managed config.

Need one phone screenshot or screen text: use phone screenshot or phone read.

Need phone recording: use the npm helper because loom_cli.py may not expose recording directly. Tell the user to approve the Android screen-capture prompt if it appears.

Need phone visual fallback: use phone:vision for one frame/read/action, and phone:game for a game/canvas loop.

Need several phones to work: use matrix status -> matrix dispatch -> matrix watch -> logs ledger -> experience report.

Need a stable repeated flow: run a template first; after repeated success, inspect experience report and suggest a template name and guardrails.

Phone says offline, screen is off, APKClaw is not foreground, or ADB is unstable: use phone adb-doctor --json --permission admin. ADB is only a recovery rail. Do not bypass APKClaw signatures, pairing, or LAN Config.

## MCP Tool Equivalents

Use these when LOOM MCP is configured:

- loom_cli_commands
- loom_matrix_status
- loom_matrix_dispatch
- loom_matrix_watch
- loom_matrix_retry
- loom_matrix_cancel
- loom_phone_screenshot
- loom_phone_read
- loom_phone_template_task
- loom_phone_quick_task
- loom_phone_adb_doctor
- loom_logs_tail
- loom_experience_report

MCP default permission is usually read. Control/admin tools must be explicitly granted by the host or via environment.

## Long-Running Supervision

1. Dispatch the task and capture campaignId or jobId.
2. Poll every 1-3 seconds with matrix watch; do not re-send the same task.
3. If the event stream shows no progress for a reasonable interval, take a screenshot/read-screen once.
4. If the phone is on the wrong page, send a narrow corrective template or cancel and redispatch.
5. If the same failure repeats, inspect logs ledger and experience report before changing strategy.

## Extra Reference

For full recipes and command examples, read references/WORKFLOWS.md in this skill directory. If the file is missing, continue with the Phone CLI Surface table above.
