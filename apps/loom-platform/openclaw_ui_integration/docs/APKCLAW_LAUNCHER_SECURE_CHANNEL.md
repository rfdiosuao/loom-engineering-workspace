# APKClaw Launcher Secure Channel

> Updated: 2026-05-11
> Status: implemented in APKClaw v6.26 / versionCode 860.
> Goal: keep APKClaw's native LAN API usable, while reserving Lumi/OpenClaw advanced orchestration for the paired launcher.

## Positioning

The LAN port is not the real security boundary. A port can be scanned, and HTTP traffic on a local network can be replayed if the token leaks.

The better boundary is layered authorization:

- APKClaw native API: keeps the existing token model for base tools and compatibility.
- Lumi/OpenClaw secure channel: adds a paired launcher secret, request signature, nonce, and timestamp for advanced endpoints.

This lets other clients continue using APKClaw's native features, while Lumi/OpenClaw-only capabilities require the paired launcher.

## Endpoint Split

Keep these as native-compatible APIs:

- `/api/device/status`
- `/api/tool/*`
- `/api/agent/status`

Advanced launcher-only capabilities now live behind a secure namespace:

- `/api/lumi/device/profile`
- `/api/lumi/agent/execute_task`
- `/api/lumi/media/import_image`
- `/api/lumi/media/record/*`
- `/api/lumi/vision/*`

Game/vision mode endpoints currently include:

- `GET /api/lumi/vision/status`
- `GET /api/lumi/vision/frame`
- `POST /api/lumi/vision/action`

The launcher-level game loop is exposed as `npm run phone:game`. It keeps the default path as:

```text
APKClaw Agent probe -> signed vision frame -> OpenClaw visual plan -> launcher safety guard -> APKClaw Agent safe_action -> after-frame verification
```

Direct `/api/lumi/vision/action` remains available for fallback/debug, but v6.26 adds safety metadata and blocks obvious sensitive targets when labels or reasons mention login, authorization, payment, purchase, recharge, account binding, delete, clear-cache, upload-log, log-out, or exit-game flows.

In the current product build, old advanced endpoints return `403` and the launcher/CLI must use `/api/lumi/*`.

Blocked legacy advanced endpoints include:

- `/api/device/profile`
- `/api/agent/execute_task`
- `/api/agent/cancel_task`
- `/api/collect/list`
- `/api/media/import_image`
- `/api/media/record/*`
- `/api/media/videos`
- `/api/media/video`

## Pairing Model

1. Launcher requests secure pairing through `/api/lumi/security/pair` with the existing APKClaw token.
2. Phone generates and stores a random `launcherSecret` during secure-pair setup.
3. Phone stores the secret in private app storage.
4. Launcher stores the secret in its phone connection config.
5. Requests to `/api/lumi/*` require:
   - `X-LUMI-LAUNCHER-ID`
   - `X-LUMI-TIMESTAMP`
   - `X-LUMI-NONCE`
   - `X-LUMI-BODY-SHA256`
   - `X-LUMI-SIGNATURE`

Signature input:

```text
METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + SHA256(BODY)
```

Signature:

```text
base64url(HMAC-SHA256(launcherSecret, signatureInput))
```

Reject if:

- timestamp drift is above 120 seconds;
- nonce was already used recently;
- signature mismatch;
- launcher id is not paired or has been revoked.

## Encryption

Phase 1 has shipped HMAC signing. It blocks casual third-party use and replay.

Phase 2 can add body encryption for sensitive endpoints:

- derive a session key from the pairing secret;
- encrypt request and response bodies with AES-GCM;
- keep `/api/device/status` readable for diagnostics.

Full TLS or mutual TLS on local phones is possible, but more expensive to support across Android versions and customer networks.

## Practical Product Rule

For now:

- Keep native APKClaw token for compatibility and debugging.
- Add Lumi secure channel before exposing advanced vision/game/large-collection workflows.
- Do not rely on an obscure port as protection.
- Treat this as "paired launcher can use advanced capabilities", not "impossible to reverse engineer".

No local-only protection is absolute if someone controls both APK and PC binaries, but paired HMAC plus nonce gives us the right product-grade boundary.
