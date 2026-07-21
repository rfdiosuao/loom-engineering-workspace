# OpenClaw Desktop Agent Skill

Use this skill when the user asks OpenClaw to inspect or control the local Windows desktop, especially WeChat or enterprise messaging workflows.

## Runtime Source

Read `runtime-context.json` first. The desktop Agent is exposed through the launcher Bridge, not by direct token or port access.

Hard rules:

- Do not connect to Luminode directly.
- Do not read, print, ask for, or construct the Luminode token.
- Do not infer the local Luminode port. Use the launcher Bridge routes only.
- Click, type, and WeChat send may be blocked by launcher policy unless the user has enabled them in Desktop Agent settings.
- When a route returns `blocked=true`, report the launcher policy reason instead of retrying through a lower-level path.

Private config lives at:

```text
data/.openclaw/launcher/desktop-agent.json
```

Never print or ask for the desktop Agent token when `desktop.tokenAvailable=true`.

## Preferred Calls

Use launcher Bridge routes:

- `GET/POST /api/desktop-agent/status`
- `GET/POST /api/desktop-agent/health`
- `POST /api/desktop-agent/screenshot`
- `POST /api/desktop-agent/click`
- `POST /api/desktop-agent/type`
- `POST /api/desktop-agent/wechat/send`
- `POST /api/desktop-agent/wechat/unread`

Prefer the CLI wrappers when available:

```powershell
npm run desktop:agent -- status
npm run desktop:agent -- health
npm run desktop:agent -- start
npm run desktop:agent -- screenshot --out .\data\desktop.png
npm run desktop:reply -- observe
npm run desktop:reply -- once --text "reply text" --confirmed
```

## Safety Rules

- Prefer screenshot and observe before clicking or typing.
- Ask for explicit user confirmation before enabling auto-reply or sending messages to real contacts.
- For `desktop.click`, `desktop.type`, and `wechat.send`, include `confirmed=true` only when the user has explicitly approved that exact action.
- Do not type passwords, payment data, real-name identity data, or authorization codes.
- Keep actions bounded: one inspect, one click/type sequence, then verify with another screenshot.
- If the desktop Agent is not ready, ask the launcher to start Luminode from the Desktop Control page.

## Tool Semantics

- `desktop.screenshot`: inspect current visible desktop/app state.
- `desktop.click`: click absolute screen coordinates from screenshot analysis.
- `desktop.type`: type text into the currently focused control.
- `wechat.send`: send text through the currently supported WeChat flow.
- `wechat.unread`: inspect unread state when Luminode has a measured layout.
- `desktop.reply.observe`: inspect status, health, unread state, and screenshot summary.
- `desktop.reply.once`: send one explicit reply text after user confirmation.
