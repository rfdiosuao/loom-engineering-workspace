# LOOM Command Brain Workflows

## Common CLI Prefix

python -B "<LOOM_HOME>/python/loom_cli.py"

Always add --json. Use --dry-run before unfamiliar control/admin commands.

For bundled phone helpers, run from the LOOM package root:

cd "<LOOM_HOME>"

Always add --json. Prefer saved launcher phone config; use --phone-url / --phone-token only for explicit debugging and never print raw tokens.

## Phone Helper Catalog

- Agent runtime: npm run phone:agent -- run/submit/status/cancel/metrics/events-sync --json
- Vision: npm run phone:vision -- status/frame/read/action --json
- Recording: npm run phone:video -- status/start/stop/list/download --json
- Image transfer/generation: npm run phone:image -- --prompt "..." --json or npm run phone:image -- --image ./file.png --json
- Image editing: npm run phone:image:edit -- --reference-image ./input.png --prompt "..." --json
- Multi-device helper: npm run phone:fleet -- list/status/run --json
- Game/canvas fallback: npm run phone:game -- run --goal "..." --json
- Publishing helper: npm run phone:publish -- --platform xiaohongshu --title "..." --body "..." --json
- Publish relay: npm run phone:relay -- ..., npm run phone:relay:check -- ..., npm run phone:relay:smoke -- ...
- Demos: npm run phone:demo:shopping -- --query "..." --json; npm run phone:demo:read -- --json; npm run phone:demo:game -- --goal "..." --json
- LOOM aliases: npm run loom:phone -- ...; npm run loom:phone:vision -- ...; npm run loom:phone:video -- ...; npm run loom:phone:fleet -- ...; npm run loom:phone:publish -- ...

## Matrix Dispatch Recipe

1. commands --json
2. matrix status --json
3. matrix dispatch --prompt "<task>" --device "<deviceId>" --json --permission control
4. matrix watch --campaign "<campaignId>" --json
5. logs ledger --limit 20 --json
6. experience report --json

If an action involves publishing, private messaging, comments, batch reach-out, or account-affecting work, require user confirmation before dispatch.

## Phone Worker Correction Recipe

1. matrix watch --campaign "<campaignId>" --json
2. If stuck, phone screenshot --json
3. If screenshot is not enough, phone read --prompt "Read the current page, page state, and three actionable entries." --json
4. If wrong page, use phone template-task --template back --json --permission control or template run --template open-settings --json --permission control
5. If repeated failure, matrix cancel --campaign "<campaignId>" --json --permission control

## Phone Recording Recipe

Use this when the user wants a proof video, failure replay, demo capture, or task review:

1. Confirm the purpose of recording.
2. npm run phone:video -- status --json
3. npm run phone:video -- start --max-seconds 180 --filename "<name>.mp4" --json
4. Tell the user to approve the Android screen-capture consent prompt if it appears.
5. Run the phone task or Matrix dispatch.
6. npm run phone:video -- stop --json
7. npm run phone:video -- download --latest --out-dir ./data/phone-videos --json
8. Report the local MP4 path.

## Phone Vision and Game Recipe

Use this when screen text is insufficient, a canvas/game has no accessibility tree, or a single visual action needs proof:

1. npm run phone:vision -- status --json
2. npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg --json
3. For read-only analysis, npm run phone:vision -- read --json
4. For game/canvas loop, npm run phone:game -- run --goal "<safe goal>" --json
5. For an explicit fallback action, write an action JSON file with action, gridCell, targetLabel, and reason, then run npm run phone:vision -- action --force-action --action-body-file ./action.json --json

## Phone Media and Publish Recipe

Use media helpers before publishing so APKClaw receives files through the signed channel:

1. Generate/upload image: npm run phone:image -- --prompt "..." --json or npm run phone:image -- --image ./file.png --json
2. Edit/upload image: npm run phone:image:edit -- --reference-image ./input.png --prompt "..." --json
3. Publish direct: npm run phone:publish -- --platform xiaohongshu --title "..." --body "..." --image ./a.png --json
4. Publish reverse packet: npm run phone:publish -- --transport reverse --platform douyin --packet-out ./publish-packet.json --json
5. Publishing, comments, private messages, batch reach-out, account changes, and paid actions require explicit user confirmation.

## Multi-Phone Helper Recipe

Use phone:fleet when the task is the same across several configured APKClaw devices and Matrix is heavier than needed:

1. npm run phone:fleet -- list --json
2. npm run phone:fleet -- status --target all --json
3. npm run phone:fleet -- run --target all --prompt "<bounded task>" --mode observe --concurrency 2 --json
4. For long or retry-heavy work, switch to Matrix dispatch/watch instead of repeatedly running fleet commands.

## ADB Recovery Recipe

1. phone adb-doctor --json --permission admin
2. diagnostics run --json
3. matrix status --json
4. phone status --json

Treat ADB repair as an admin action. Do not run it repeatedly without evidence.

## Experience and Template Loop

1. Prefer template run for repeated low-risk tasks.
2. After completion, read experience report --json.
3. Suggest a stable template when success rate is high and task text is repeatable.
4. Keep safety boundaries in the template notes.
5. Do not store sensitive values in template names, notes, or prompts.

## Agent Model Configuration

1. models --json
2. wire current --json
3. agents model-status --component codex-desktop --json
4. agents model-apply --component codex-desktop --json --permission control
5. If wrong, agents model-rollback --component codex-desktop --json --permission control

Keep main model and phone model separate. Phone defaults to qwen3.7-plus unless LOOM returns another selected available phone model; do not overwrite the main model with an unrelated phone model.
