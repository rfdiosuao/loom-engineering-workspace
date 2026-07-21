# Bridge Migration Guard

> Purpose: keep the current Python Bridge behavior stable before replacing the
> `http.server` implementation with FastAPI.

## Why This Exists

The launcher is already close to delivery, so the FastAPI migration should not
start by rewriting `python/bridge.py` directly. First we need a small behavior
contract and a repeatable smoke check. After those pass, each endpoint can be
moved to FastAPI without guessing what the old bridge used to return.

Current call chain after phase 1:

```text
React UI -> Tauri invoke(proxy_request) -> Rust -> HTTP -> FastAPI Bridge
```

The FastAPI service now owns the known launcher API endpoints directly. The old
`http.server` route implementation has been removed. If FastAPI dependencies
are missing, the bridge starts a small dependency-error service that returns
Bridge JSON 503 responses instead of silently running stale route logic.
FastAPI no longer delegates unknown routes back to the old handler; unknown
routes return the standard Bridge JSON 404 shape.

Known launcher endpoints are now registered as native FastAPI routes:

| Endpoint | Status |
| --- | --- |
| `/api/system/info` | FastAPI native |
| `/api/process/start` | FastAPI native |
| `/api/process/stop` | FastAPI native |
| `/api/process/status` | FastAPI native |
| `/api/log/get` | FastAPI native |
| `/api/log/clear` | FastAPI native |
| `/api/license/current` | FastAPI native |
| `/api/license/activate` | FastAPI native |
| `/api/license/authorized` | FastAPI native |
| `/api/image/generate` | FastAPI native |
| `/api/video/generate` | FastAPI native |
| `/api/theme/current` | FastAPI native |
| `/api/theme/by_merchant` | FastAPI native |
| `/api/theme/list` | FastAPI native |
| `/api/config/read` | FastAPI native |
| `/api/config/write` | FastAPI native |
| `/api/auth/profiles` | FastAPI native |
| `/api/diagnostics/run` | FastAPI native |
| `/api/diagnostics/repair` | FastAPI native |
| `/api/diagnostics/export` | FastAPI native |
| `/api/update/check` | FastAPI native |
| `/api/update/do` | FastAPI native |
| `/api/skills/list` | FastAPI native |
| `/api/skills/install_zip` | FastAPI native |
| `/api/skills/enable` | FastAPI native |
| `/api/skills/uninstall` | FastAPI native |
| `/api/skills/readme` | FastAPI native |
| `/api/skills/paths` | FastAPI native |

All known launcher API endpoints now have native FastAPI handlers. The remaining
`http.server` handler is not an API implementation; it only reports missing
FastAPI dependencies.

Cleanup has started:

| Module | Responsibility |
| --- | --- |
| `python/bridge.py` | bridge process entrypoint, dependency-error fallback, shared service context |
| `python/api/fastapi_routes.py` | route aggregator, exception handler, native 404 fallback |
| `python/api/routes_process.py` | OpenClaw process start/stop/status |
| `python/api/routes_license.py` | license status, activation, feature authorization |
| `python/api/routes_media.py` | AI image and video generation |
| `python/api/routes_config.py` | config file read/write and API profile sync |
| `python/api/routes_diagnostics.py` | diagnostics run/repair/export |
| `python/api/routes_skills.py` | Skill list/install/enable/uninstall/readme |
| `python/api/routes_system.py`, `routes_log.py`, `routes_theme.py`, `routes_update.py` | small focused system routes |

Target call chain after the full migration:

```text
React UI -> Tauri/Rust security gate -> FastAPI routers
```

## Migration Rule

Do not change the public response shape of an endpoint during the framework
migration. If a response shape needs to change, do it in a separate product
change after the FastAPI migration is already stable.

Additive compatibility fields are allowed when they do not replace legacy
payload fields. Every Bridge JSON response now includes `_meta`:

```json
{
  "_meta": {
    "ok": true,
    "status": 200
  }
}
```

Error responses still keep the legacy top-level `error` string and additionally
include structured error metadata:

```json
{
  "error": "message",
  "_meta": {
    "ok": false,
    "status": 400,
    "error": {
      "code": 400,
      "message": "message"
    }
  }
}
```

Do not use `_meta` for endpoint business data.

## Current Protected Endpoints

These endpoints require a valid local license before Rust/Python should allow
the action:

| Endpoint | Feature |
| --- | --- |
| `POST /api/process/start` | `openclaw` |
| `POST /api/image/generate` | `image` |
| `POST /api/video/generate` | `video` |

The smoke script intentionally does not call these endpoints because it must not
start OpenClaw, spend API credits, or require a customer license.

## Read-Only Smoke Contract

The local smoke script verifies the bridge can start, accepts its runtime token,
rejects missing tokens, and returns valid JSON from low-risk read-only endpoints.

Run it from the repository root:

```powershell
python -m pip install -r openclaw_new_launcher\python\requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\smoke-bridge.ps1
```

To assert the FastAPI implementation explicitly during local migration testing,
run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\smoke-bridge.ps1 -RequireFastApi
```

Checked endpoints:

| Endpoint | Method | Expected shape |
| --- | --- | --- |
| `/api/system/info` | `GET` | `node_path`, `base_path`, `openclaw_version` |
| `/api/process/status` | `GET` | `running`, `pid` |
| `/api/process/start` | `POST` | unauthenticated/protected rejection |
| `/api/process/stop` | `POST` | `status`, `message` |
| `/api/log/get` | `GET` | `log` |
| `/api/license/current` | `GET` | `license` |
| `/api/license/activate` | `POST` | empty-code rejection |
| `/api/license/authorized` | `POST` | `authorized` |
| `/api/image/generate` | `POST` | protected rejection |
| `/api/video/generate` | `POST` | protected rejection |
| `/api/theme/current` | `GET` | `theme` |
| `/api/theme/list` | `GET` | `themes` |
| `/api/auth/profiles` | `GET` | `profiles` |
| `/api/diagnostics/run` | `GET` | `checks`, `summary` |
| `/api/diagnostics/export` | `POST` | `path`, `directory`, `filename`, `size` |
| `/api/config/write` | `POST` | `status` |
| `/api/config/read` | `POST` | `data` |
| `/api/log/clear` | `POST` | `status` |
| `/api/skills/list` | `GET` | `skills`, `directories`, `sites` |
| `/api/skills/paths` | `GET` | `directories`, `sites` |
| `/api/skills/install_zip` | `POST` | `skill` |
| `/api/skills/readme` | `POST` | `id`, `path`, `content` |
| `/api/skills/enable` | `POST` | `skill` |
| `/api/skills/uninstall` | `POST` | `status`, `id` |

## FastAPI Migration Phases

1. Contract phase
   - Keep `bridge.py` unchanged except for bug fixes.
   - Keep this document and `scripts/smoke-bridge.ps1` passing.

2. Skeleton phase
   - Add FastAPI dependencies.
   - Switch the HTTP service layer to FastAPI.
   - Keep endpoint behavior delegated to the legacy route logic. Done; this
     compatibility layer has now been removed after native routes passed smoke.

3. Shadow phase
   - Add `python/api/` routers and Pydantic models.
   - Move read-only endpoints first.
   - Compare smoke responses before and after each endpoint move.

4. Switch phase
   - Move protected and write endpoints only after read-only routes are stable.
   - Keep Rust license checks in place for protected endpoints.

5. Cleanup phase
   - Delete the old route chain from `bridge.py`.
   - Update API docs and remove migration-only flags.

## Stop Conditions

Pause the migration if any of these happen:

- Activation cannot complete.
- OpenClaw service startup becomes less reliable.
- Feishu or Weixin binding regresses.
- Packaged Windows portable verification fails.
- The root package layout is no longer `OpenClaw.exe + OpenClawFiles/`.

The goal is not to make the architecture prettier first. The goal is to make it
safe to improve the architecture without breaking delivery.
