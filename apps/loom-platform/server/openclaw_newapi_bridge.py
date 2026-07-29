#!/usr/bin/env python3
"""Small NewAPI helper for OpenClaw account login.

This service runs on localhost behind nginx. It authenticates against the
existing NewAPI login endpoint, then reads the user's full API token from the
local SQLite database. NewAPI's public token APIs return masked keys, which is
safe for the web UI but not enough for a launcher that must configure an
OpenAI-compatible gateway.
"""

from __future__ import annotations

import base64
import binascii
import http.cookiejar
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import smtplib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import bcrypt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # SQLite remains available for an explicit rollback.
    psycopg2 = None
    RealDictCursor = None


HOST = os.environ.get("OPENCLAW_NEWAPI_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPENCLAW_NEWAPI_BRIDGE_PORT", "3016"))
NEWAPI_BASE = os.environ.get("OPENCLAW_NEWAPI_BASE", "http://127.0.0.1:3000").rstrip("/")
PUBLIC_API_BASE = os.environ.get("OPENCLAW_PUBLIC_API_BASE", "https://api.heang.top/v1").rstrip("/")
DB_PATH = os.environ.get("OPENCLAW_NEWAPI_DB", "/mnt/data/new-api/one-api.db")
PG_DSN = os.environ.get("OPENCLAW_NEWAPI_PG_DSN", "").strip()
BIND_DB_PATH = os.environ.get(
    "OPENCLAW_BIND_DB",
    "/mnt/data/openclaw/openclaw-bridge-state.db",
)
BIND_TICKET_TTL_SEC = int(os.environ.get("OPENCLAW_BIND_TICKET_TTL_SEC", "600"))
BIND_TICKET_SECRET = os.environ.get("OPENCLAW_BIND_TICKET_SECRET", "").strip()
EMAIL_CODE_TTL_SEC = int(os.environ.get("OPENCLAW_EMAIL_CODE_TTL_SEC", "600"))
EMAIL_CODE_RATE_WINDOW_SEC = int(os.environ.get("OPENCLAW_EMAIL_CODE_RATE_WINDOW_SEC", "900"))
EMAIL_CODE_RATE_LIMIT = int(os.environ.get("OPENCLAW_EMAIL_CODE_RATE_LIMIT", "5"))
AUTH_FAILURE_RATE_WINDOW_SEC = int(os.environ.get("OPENCLAW_AUTH_FAILURE_RATE_WINDOW_SEC", "900"))
AUTH_FAILURE_RATE_LIMIT = int(os.environ.get("OPENCLAW_AUTH_FAILURE_RATE_LIMIT", "10"))
EMAIL_CODE_PEPPER = os.environ.get("OPENCLAW_EMAIL_CODE_SECRET") or secrets.token_hex(32)
PRODUCT_NAME = os.environ.get("OPENCLAW_PRODUCT_NAME", "LOOM / 麓鸣")
DEFAULT_TEXT_MODEL = "glm-5.2-coding"
TEXT_MODEL_PRIORITY = (
    DEFAULT_TEXT_MODEL,
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "glm-4-flash",
    "kimi-k2.5",
    "MiniMax-M2.5",
)
DUMMY_PASSWORD_HASH = b"$2b$12$r8bkOL9d2uvfwYy6HLOTfetYMOqQwrlwXkXL774PW/7LFPTy90hju"
ENTITLEMENT_LEASE_TTL_SEC = int(os.environ.get("OPENCLAW_ENTITLEMENT_LEASE_TTL_SEC", "3600"))
ENTITLEMENT_OFFLINE_GRACE_SEC = int(os.environ.get("OPENCLAW_ENTITLEMENT_OFFLINE_GRACE_SEC", str(72 * 3600)))
ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC = max(
    5,
    min(
        int(
            os.environ.get(
                "OPENCLAW_ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC",
                "30",
            )
        ),
        60,
    ),
)
ENTITLEMENT_KEY_ID = os.environ.get("OPENCLAW_ENTITLEMENT_KEY_ID", "openclaw-ed25519-v1")
TRUSTED_ENTITLEMENT_KEY_ID = "openclaw-ed25519-v1"
TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64 = "njEIf3io24DAXRYVp37p2gIT5u2KZaWoGvBPD0JlTZ4="
PHONE_SEAT_LEASE_SCHEMA = "loom.phone_seat_lease.v1"
ENTITLEMENT_PRIVATE_KEY_B64 = (
    os.environ.get("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_B64")
    or os.environ.get("LICENSE_PRIVATE_KEY_B64")
    or ""
).strip()
ENTITLEMENT_PRIVATE_KEY_FILE = (
    os.environ.get("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_FILE")
    or os.environ.get("LICENSE_PRIVATE_KEY_FILE")
    or ""
).strip()
LICENSE_ENTITLEMENT_SERVICE_BASE = os.environ.get(
    "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_BASE",
    "https://license.heang.top",
).strip().rstrip("/")
LICENSE_ENTITLEMENT_SERVICE_TOKEN = os.environ.get(
    "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN",
    "",
).strip()
SAFETY_ENTITLEMENT_OPERATIONS = {
    "diagnostics",
    "matrix.cancel",
    "matrix.device.release",
    "matrix.diagnostics",
    "matrix.emergency_stop",
    "matrix.task.cancel",
    "matrix.task.pause",
    "matrix.task.stop",
}
_ENTITLEMENT_AUTHORIZATION_REFRESHED_AT: dict[str, float] = {}
_ENTITLEMENT_AUTHORIZATION_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_ENTITLEMENT_AUTHORIZATION_REFRESH_LOCKS_GUARD = threading.Lock()
ACTIVATED_PHONE_DEVICE_LIMIT = 1000
ENTITLEMENT_GROUP_POLICIES: dict[str, dict[str, Any]] = {
    "default": {
        "plan": "inactive",
        "features": [],
        "limits": {"devices": 0, "concurrentTasks": 0},
    },
    "free": {
        "plan": "inactive",
        "features": [],
        "limits": {"devices": 0, "concurrentTasks": 0},
    },
    "standard": {
        "plan": "standard",
        "features": [
            "matrix.devices",
            "matrix.tasks",
            "matrix.parallel_tasks",
            "matrix.diagnostics",
            "legacy.license.migration",
        ],
        "limits": {"devices": 3, "concurrentTasks": 2},
    },
    "pro": {
        "plan": "pro",
        "features": [
            "matrix.devices",
            "matrix.tasks",
            "matrix.parallel_tasks",
            "matrix.diagnostics",
            "legacy.license.migration",
        ],
        "limits": {"devices": 5, "concurrentTasks": 3},
    },
    "vip": {
        "plan": "vip",
        "features": [
            "matrix.devices",
            "matrix.tasks",
            "matrix.parallel_tasks",
            "matrix.diagnostics",
            "legacy.license.migration",
        ],
        "limits": {"devices": 5, "concurrentTasks": 3},
    },
    "svip": {
        "plan": "svip",
        "features": [
            "matrix.devices",
            "matrix.tasks",
            "matrix.parallel_tasks",
            "matrix.diagnostics",
            "legacy.license.migration",
        ],
        "limits": {"devices": 10, "concurrentTasks": 5},
    },
    "enterprise": {
        "plan": "enterprise",
        "features": [
            "matrix.devices",
            "matrix.tasks",
            "matrix.parallel_tasks",
            "matrix.diagnostics",
            "legacy.license.migration",
        ],
        "limits": {"devices": 50, "concurrentTasks": 20},
    },
}


class BridgeUpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str = "",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = str(code or "").strip()
        self.details = dict(details or {})


def default_text_model(models: list[str]) -> str:
    for model in TEXT_MODEL_PRIORITY:
        if model in models:
            return model
    return models[0] if models else ""


BIND_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OpenClaw 网站绑定</title>
  <style>
    :root { color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0f172a; color: #f8fafc; }
    main { width: min(460px, calc(100vw - 32px)); border: 1px solid rgba(148, 163, 184, .35); border-radius: 18px; background: rgba(15, 23, 42, .92); box-shadow: 0 24px 80px rgba(0,0,0,.35); padding: 28px; }
    h1 { margin: 0 0 8px; font-size: 24px; line-height: 1.2; }
    p { margin: 0 0 22px; color: #cbd5e1; line-height: 1.65; }
    label { display: block; margin: 14px 0 6px; color: #e2e8f0; font-size: 14px; }
    input { width: 100%; box-sizing: border-box; border-radius: 12px; border: 1px solid rgba(148, 163, 184, .45); background: rgba(2, 6, 23, .65); color: #f8fafc; padding: 12px 13px; outline: none; font-size: 14px; }
    input:focus { border-color: #34d399; box-shadow: 0 0 0 3px rgba(52, 211, 153, .16); }
    button { width: 100%; margin-top: 18px; border: 0; border-radius: 12px; padding: 12px 14px; background: #10b981; color: #04130e; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .65; cursor: progress; }
    .result { margin-top: 18px; padding: 14px; border-radius: 12px; background: rgba(16, 185, 129, .12); border: 1px solid rgba(52, 211, 153, .32); display: none; }
    .result strong { display: block; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; margin-top: 8px; color: #86efac; }
    .error { margin-top: 14px; color: #fca5a5; min-height: 20px; }
    .meta { margin-top: 12px; font-size: 12px; color: #94a3b8; }
  </style>
</head>
<body>
  <main>
    <h1>OpenClaw 网站绑定</h1>
    <p>登录模型账号，生成一次性绑定码。回到启动器的账号页粘贴绑定码，即可同步模型。</p>
    <form id="bind-form">
      <label for="username">账号</label>
      <input id="username" name="username" autocomplete="username" placeholder="邮箱或用户名" required />
      <label for="password">密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button id="submit" type="submit">生成绑定码</button>
    </form>
    <div class="result" id="result">
      <span>绑定码</span>
      <strong id="ticket"></strong>
      <div class="meta" id="expires"></div>
    </div>
    <div class="error" id="error"></div>
  </main>
  <script>
    const form = document.getElementById('bind-form');
    const submit = document.getElementById('submit');
    const result = document.getElementById('result');
    const ticketEl = document.getElementById('ticket');
    const expiresEl = document.getElementById('expires');
    const errorEl = document.getElementById('error');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      submit.disabled = true;
      errorEl.textContent = '';
      result.style.display = 'none';
      const body = {
        username: form.username.value.trim(),
        password: form.password.value,
      };
      try {
        const response = await fetch('/api/openclaw/bind/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok || payload.success === false) throw new Error(payload.error || payload.message || '生成失败');
        form.password.value = '';
        ticketEl.textContent = payload.data.ticket;
        const expiresAt = new Date((payload.data.expiresAt || 0) * 1000);
        expiresEl.textContent = Number.isNaN(expiresAt.getTime()) ? '10 分钟内有效' : `有效期至 ${expiresAt.toLocaleString()}`;
        result.style.display = 'block';
        if (navigator.clipboard) navigator.clipboard.writeText(payload.data.ticket).catch(() => {});
      } catch (error) {
        errorEl.textContent = error instanceof Error ? error.message : String(error);
      } finally {
        submit.disabled = false;
      }
    });
  </script>
</body>
</html>"""


def mask_secret(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def request_json(
    opener: urllib.request.OpenerDirector,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    data = None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{NEWAPI_BASE}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"message": raw}
        raise BridgeUpstreamError(
            str(payload.get("message") or payload.get("error") or f"HTTP {error.code}"),
            status_code=error.code,
            code=str(payload.get("code") or ""),
            details=payload.get("details") if isinstance(payload.get("details"), dict) else None,
        ) from error
    except urllib.error.URLError as error:
        raise BridgeUpstreamError("upstream service unavailable", status_code=502) from error


def candidate_user_id(login_payload: dict[str, Any]) -> str:
    data = login_payload.get("data")
    if isinstance(data, dict):
        value = data.get("id") or data.get("user_id") or data.get("userId")
        if value:
            return str(value)
    for key in ("id", "user_id", "userId"):
        value = login_payload.get(key)
        if value:
            return str(value)
    return ""


def user_group(login_payload: dict[str, Any]) -> str:
    data = login_payload.get("data")
    if isinstance(data, dict):
        return str(data.get("group") or "default")
    return "default"


def cookie_header(cookie_jar: http.cookiejar.CookieJar) -> str:
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)


def upstream_error_response(error: BridgeUpstreamError, *, authentication: bool = False) -> tuple[int, dict[str, Any]]:
    status_code = int(error.status_code or 502)
    if status_code == 429:
        public_status = 429
    elif authentication and status_code in {400, 401, 403}:
        public_status = 401
    elif not authentication and status_code in {400, 409, 422}:
        public_status = status_code
    else:
        public_status = 502
    return public_status, {"success": False, "error": str(error)}


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entitlement_session_binding(session_token: str) -> str:
    return hashlib.sha256(
        b"loom-entitlement-session-v1\0" + str(session_token).encode("utf-8")
    ).hexdigest()


def entitlement_policy_for_group(group: str) -> dict[str, Any]:
    normalized = str(group or "default").strip().lower() or "default"
    if normalized not in ENTITLEMENT_GROUP_POLICIES:
        if "svip" in normalized:
            normalized = "svip"
        elif "vip" in normalized:
            normalized = "vip"
        elif "enterprise" in normalized or "company" in normalized:
            normalized = "enterprise"
        elif "pro" in normalized:
            normalized = "pro"
        elif "standard" in normalized:
            normalized = "standard"
        else:
            normalized = "default"
    policy = ENTITLEMENT_GROUP_POLICIES[normalized]
    return {
        "group": str(group or "default").strip() or "default",
        "plan": policy["plan"],
        "source": "plan_defaults",
        "features": list(policy["features"]),
        "limits": dict(policy["limits"]),
    }


def inactive_entitlement_policy(group: str = "default") -> dict[str, Any]:
    return {
        "group": str(group or "default").strip() or "default",
        "plan": "inactive",
        "source": "authorization_required",
        "features": [],
        "limits": {
            "devices": 0,
            "concurrentTasks": 0,
            "unlimitedDevices": False,
        },
    }


def _strict_positive_int(value: Any, default: int, maximum: int) -> int:
    if type(value) is not int:
        return default
    return max(1, min(value, maximum))


def _entitlement_expiry_epoch(value: Any) -> int:
    if type(value) is int:
        return max(0, value)
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return int((parsed + timedelta(days=1)).timestamp()) - 1
        normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (OverflowError, TypeError, ValueError):
        return 0


def normalize_authorization_entitlement(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    entitlement = (
        data.get("entitlement")
        if isinstance(data, dict) and isinstance(data.get("entitlement"), dict)
        else data
    )
    if not isinstance(entitlement, dict):
        raise BridgeUpstreamError("授权服务没有返回有效权益。", status_code=502)

    plan = str(entitlement.get("plan") or "standard").strip().lower() or "standard"
    defaults = entitlement_policy_for_group(plan)
    allowed_features = {
        feature
        for policy in ENTITLEMENT_GROUP_POLICIES.values()
        for feature in policy.get("features", [])
    }
    raw_features = entitlement.get("features")
    features = (
        [
            str(feature).strip()
            for feature in raw_features
            if str(feature).strip() in allowed_features
        ]
        if isinstance(raw_features, list)
        else list(defaults["features"])
    )
    if "matrix.devices" not in features:
        features.append("matrix.devices")
    if "matrix.tasks" not in features:
        features.append("matrix.tasks")
    if "matrix.diagnostics" not in features:
        features.append("matrix.diagnostics")

    raw_limits = entitlement.get("limits") if isinstance(entitlement.get("limits"), dict) else {}
    default_limits = defaults["limits"]
    devices = ACTIVATED_PHONE_DEVICE_LIMIT
    concurrent_tasks = _strict_positive_int(
        raw_limits.get("concurrentTasks"),
        int(default_limits.get("concurrentTasks") or 1),
        100,
    )
    concurrent_tasks = min(concurrent_tasks, devices)
    expires_at = _entitlement_expiry_epoch(
        entitlement.get("expiresAt") or entitlement.get("expires")
    )
    if expires_at and expires_at <= int(time.time()):
        raise BridgeUpstreamError(
            "授权码已过期。",
            status_code=403,
            code="LICENSE_EXPIRED",
        )
    return {
        "group": "",
        "plan": plan,
        "source": "authorization_code",
        "features": sorted(set(features)),
        "limits": {
            "devices": devices,
            "concurrentTasks": concurrent_tasks,
            "unlimitedDevices": True,
        },
        "expiresAt": expires_at,
        "codeLabel": str(
            entitlement.get("codeLabel")
            or entitlement.get("activationCodeLabel")
            or ""
        ).strip()[:80],
    }


def _license_service_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    if not LICENSE_ENTITLEMENT_SERVICE_TOKEN:
        raise BridgeUpstreamError(
            "授权兑换服务尚未配置。",
            status_code=503,
        )
    parsed_base = urllib.parse.urlparse(LICENSE_ENTITLEMENT_SERVICE_BASE)
    if parsed_base.scheme != "https" or not parsed_base.hostname:
        raise BridgeUpstreamError(
            "授权服务必须使用 HTTPS。",
            status_code=503,
            code="ENTITLEMENT_SERVICE_INSECURE",
        )
    request = urllib.request.Request(
        f"{LICENSE_ENTITLEMENT_SERVICE_BASE}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LICENSE_ENTITLEMENT_SERVICE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            message = str(payload.get("message") or payload.get("error") or "").strip()
            code = str(payload.get("code") or "").strip()
            details = payload.get("details") if isinstance(payload.get("details"), dict) else None
        except Exception:
            message = ""
            code = ""
            details = None
        raise BridgeUpstreamError(
            message or f"授权服务返回 HTTP {error.code}",
            status_code=error.code,
            code=code,
            details=details,
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise BridgeUpstreamError(
            "暂时无法连接授权服务，请稍后重试。",
            status_code=503,
        ) from error
    if not isinstance(payload, dict):
        raise BridgeUpstreamError("授权服务响应格式无效。", status_code=502)
    if payload.get("ok") is False or payload.get("success") is False:
        raise BridgeUpstreamError(
            str(payload.get("message") or payload.get("error") or "授权兑换失败。"),
            status_code=int(payload.get("status") or 400),
            code=str(payload.get("code") or ""),
            details=payload.get("details") if isinstance(payload.get("details"), dict) else None,
        )
    return payload


def redeem_authorization_code_with_license_server(
    code: str,
    *,
    account_id: str,
) -> dict[str, Any]:
    payload = _license_service_json(
        "/api/service/account-entitlements/redeem",
        {"code": code, "accountId": account_id},
    )
    return normalize_authorization_entitlement(payload)


def current_authorization_entitlement_from_license_server(
    account_id: str,
) -> dict[str, Any] | None:
    payload = _license_service_json(
        "/api/service/account-entitlements/current",
        {"accountId": account_id},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    entitlement = data.get("entitlement") if isinstance(data, dict) else None
    if entitlement in (None, False):
        return None
    return normalize_authorization_entitlement(payload)


def migrate_legacy_authorization_with_license_server(
    legacy_license: dict[str, Any],
    *,
    account_id: str,
) -> dict[str, Any]:
    payload = _license_service_json(
        "/api/service/account-entitlements/migrate-legacy",
        {
            "legacyLicense": legacy_license,
            "accountId": account_id,
        },
    )
    return normalize_authorization_entitlement(payload)


def _authorization_refresh_lock(account_id: str) -> threading.Lock:
    account = str(account_id)
    with _ENTITLEMENT_AUTHORIZATION_REFRESH_LOCKS_GUARD:
        return _ENTITLEMENT_AUTHORIZATION_REFRESH_LOCKS.setdefault(
            account,
            threading.Lock(),
        )


def refresh_account_entitlement_authorization(account_id: str) -> None:
    if not LICENSE_ENTITLEMENT_SERVICE_TOKEN:
        return
    account = str(account_id)
    refresh_lock = _authorization_refresh_lock(account)
    with refresh_lock:
        now = time.monotonic()
        last_refreshed = _ENTITLEMENT_AUTHORIZATION_REFRESHED_AT.get(account, 0.0)
        if (
            last_refreshed
            and now - last_refreshed
            < float(ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC)
        ):
            return
        try:
            entitlement = current_authorization_entitlement_from_license_server(
                account
            )
        except BridgeUpstreamError as error:
            if error.code in {
                "ACCOUNT_ENTITLEMENT_NOT_FOUND",
                "ACCOUNT_ENTITLEMENT_REVOKED",
                "LICENSE_DISABLED",
                "LICENSE_EXPIRED",
                "LICENSE_INVALID",
            }:
                persist_account_entitlement_grant(
                    account,
                    None,
                    action=f"operation_refresh_{error.code.lower()}",
                )
            _ENTITLEMENT_AUTHORIZATION_REFRESHED_AT[account] = time.monotonic()
            return
        persist_account_entitlement_grant(
            account,
            entitlement,
            action="operation_refresh",
        )
        _ENTITLEMENT_AUTHORIZATION_REFRESHED_AT[account] = time.monotonic()


def entitlement_error(
    code: str,
    message: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "code": code,
        "message": message,
        "error": message,
        "action": action,
        "details": details or {},
    }


def _private_key_from_bytes(raw: bytes) -> Ed25519PrivateKey:
    # A raw Ed25519 private key is arbitrary binary data. Its first or last
    # byte may legitimately look like ASCII whitespace, so never strip a
    # correctly sized raw key before parsing it.
    if len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    stripped = raw.strip()
    if b"-----BEGIN" in stripped:
        loaded = serialization.load_pem_private_key(stripped, password=None)
    else:
        try:
            decoded = base64.b64decode(stripped, validate=True)
        except (ValueError, binascii.Error):
            decoded = b""
        if len(decoded) == 32:
            return Ed25519PrivateKey.from_private_bytes(decoded)
        loaded = serialization.load_der_private_key(stripped, password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("entitlement signing key must be Ed25519")
    return loaded


def _validate_entitlement_signing_identity(
    private_key: Ed25519PrivateKey,
) -> None:
    if ENTITLEMENT_KEY_ID != TRUSTED_ENTITLEMENT_KEY_ID:
        raise RuntimeError(
            "entitlement key id does not match the LOOM client trust anchor"
        )
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    actual_public_key = base64.b64encode(public_key).decode("ascii")
    if not hmac.compare_digest(
        actual_public_key,
        TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64,
    ):
        raise RuntimeError(
            "entitlement signing key does not match the LOOM client trust anchor"
        )


def entitlement_private_key() -> Ed25519PrivateKey:
    if ENTITLEMENT_PRIVATE_KEY_B64:
        private_key = _private_key_from_bytes(
            base64.b64decode(ENTITLEMENT_PRIVATE_KEY_B64)
        )
    elif ENTITLEMENT_PRIVATE_KEY_FILE:
        with open(ENTITLEMENT_PRIVATE_KEY_FILE, "rb") as handle:
            private_key = _private_key_from_bytes(handle.read())
    else:
        raise RuntimeError("entitlement signing key is not configured")
    _validate_entitlement_signing_identity(private_key)
    return private_key


def entitlement_public_key_b64() -> str:
    public_key = entitlement_private_key().public_key()
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def entitlement_key_payload() -> dict[str, Any]:
    return {"keyId": ENTITLEMENT_KEY_ID, "publicKey": entitlement_public_key_b64()}


def sign_entitlement_payload(payload: dict[str, Any]) -> str:
    signed = dict(payload)
    signed.pop("signature", None)
    signature = entitlement_private_key().sign(canonical_json(signed).encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def lease_identity_from_body(body: dict[str, Any]) -> tuple[str, str]:
    install_id = str(body.get("installId") or body.get("install_id") or "").strip()
    device_id = str(
        body.get("hostDeviceId")
        or body.get("deviceId")
        or body.get("device_id")
        or ""
    ).strip()
    return install_id, device_id


def _newapi_fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if PG_DSN:
        if psycopg2 is None or RealDictCursor is None:
            raise RuntimeError("PostgreSQL support requires python3-psycopg2")
        connection = psycopg2.connect(PG_DSN)
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql.replace("?", "%s"), params)
                return [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    connection = sqlite3.connect(DB_PATH)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def _newapi_fetchone(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _newapi_fetchall(sql, params)
    return rows[0] if rows else None


def _newapi_execute(sql: str, params: tuple[Any, ...]) -> None:
    if PG_DSN:
        if psycopg2 is None:
            raise RuntimeError("PostgreSQL support requires python3-psycopg2")
        connection = psycopg2.connect(PG_DSN)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.replace("?", "%s"), params)
            connection.commit()
        finally:
            connection.close()
        return

    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def token_usable(row: dict[str, Any]) -> bool:
    if int(row["status"] or 0) != 1:
        return False
    if row["deleted_at"]:
        return False
    try:
        raw_expired_time = row.get("expired_time")
        expired_time = -1 if raw_expired_time is None else int(raw_expired_time)
    except (TypeError, ValueError):
        expired_time = -1
    if expired_time != -1 and expired_time <= int(time.time()):
        return False
    if bool(row["unlimited_quota"]):
        return True
    try:
        return int(row["remain_quota"] or 0) > 0
    except (TypeError, ValueError):
        return False


def launcher_token_name(name: str | None) -> bool:
    value = str(name or "")
    return value.startswith("LOOM Launcher ") or value.startswith("OpenClaw Launcher ")


def launcher_token_usable(row: dict[str, Any]) -> bool:
    key = str(row["key"] or "")
    return token_usable(row) and key.isalnum() and not bool(row["model_limits_enabled"])


def launcher_token_uses_default_policy(row: dict[str, Any], account_group: str = "") -> bool:
    try:
        raw_expired_time = row.get("expired_time")
        expired_time = -1 if raw_expired_time is None else int(raw_expired_time)
        remain_quota = int(row.get("remain_quota") or 0)
    except (TypeError, ValueError):
        return False
    token_group = str(row.get("group") or "").strip()
    expected_group = str(account_group or "").strip()
    group_matches_account = not token_group or bool(expected_group and token_group == expected_group)
    return (
        launcher_token_usable(row)
        and expired_time == -1
        and remain_quota == 0
        and bool(row.get("unlimited_quota"))
        and not bool(row.get("model_limits_enabled"))
        and not str(row.get("model_limits") or "").strip()
        and not str(row.get("allow_ips") or "").strip()
        and group_matches_account
        and not bool(row.get("cross_group_retry"))
    )


def token_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "name": row["name"],
        "remainQuota": row["remain_quota"],
        "unlimitedQuota": bool(row["unlimited_quota"]),
        "modelLimitsEnabled": bool(row["model_limits_enabled"]),
        "modelLimits": row["model_limits"] or "",
        "tokenGroup": row.get("group") or "",
        "permissionMode": "default",
    }


def select_token(user_id: str, preferred_name: str = "", account_group: str = "") -> dict[str, Any] | None:
    rows = _newapi_fetchall(
        """
        select id, key, name, expired_time, remain_quota, unlimited_quota, model_limits_enabled,
               model_limits, allow_ips, "group", cross_group_retry, status, deleted_at, created_time
        from tokens
        where user_id = ? and deleted_at is null and status = 1
        order by created_time desc, id desc
        """,
        (user_id,),
    )
    if not rows:
        return None

    def preferred_for_account(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        expected_group = str(account_group or "").strip()
        if expected_group:
            exact = [row for row in candidates if str(row.get("group") or "").strip() == expected_group]
            if exact:
                return exact[0]
        return candidates[0] if candidates else None

    if preferred_name:
        preferred = [
            row
            for row in rows
            if row["name"] == preferred_name
            and launcher_token_name(row["name"])
            and launcher_token_uses_default_policy(row, account_group)
        ]
        if preferred:
            selected = preferred_for_account(preferred)
            return token_payload(selected) if selected else None
        return None

    # Do not reuse arbitrary historical tokens. Old user tokens may have
    # model_limits enabled, which makes Codex see only agnes models and behave
    # like a chat bot instead of a tool-using coding agent.
    launcher_rows = [
        row
        for row in rows
        if launcher_token_name(row["name"]) and launcher_token_uses_default_policy(row, account_group)
    ]
    if launcher_rows:
        selected = preferred_for_account(launcher_rows)
        return token_payload(selected) if selected else None

    return None


def api_token_owner(authorization: str) -> dict[str, Any] | None:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        return None
    supplied = value[7:].strip()
    if not supplied:
        return None
    alternate = supplied[3:] if supplied.startswith("sk-") else f"sk-{supplied}"
    row = _newapi_fetchone(
        """
        select t.id, t.key, t.name, t.status, t.deleted_at, t.expired_time,
               t.remain_quota, t.unlimited_quota, t.model_limits_enabled,
               t.model_limits, t.allow_ips, t."group", t.cross_group_retry,
               u.id as user_id, u.username, u.email, u."group" as user_group,
               u.status as user_status, u.deleted_at as user_deleted_at
        from tokens t
        join users u on u.id = t.user_id
        where t.key in (?, ?)
        order by case when t.key = ? then 0 else 1 end
        limit 1
        """,
        (supplied, alternate, supplied),
    )
    if not row:
        return None
    if int(row.get("status") or 0) != 1 or row.get("deleted_at"):
        return None
    if int(row.get("user_status") or 0) != 1 or row.get("user_deleted_at"):
        return None
    try:
        raw_expired_time = row.get("expired_time")
        expired_time = -1 if raw_expired_time is None else int(raw_expired_time)
    except (TypeError, ValueError):
        expired_time = -1
    if expired_time != -1 and expired_time <= int(time.time()):
        return None
    if not bool(row.get("unlimited_quota")):
        try:
            if int(row.get("remain_quota") or 0) <= 0:
                return None
        except (TypeError, ValueError):
            return None
    return row


def create_token(opener: urllib.request.OpenerDirector, user_id: str, group: str) -> dict[str, Any] | None:
    token_name = f"OpenClaw Launcher {int(time.time())}-{secrets.token_hex(3)}"
    headers = {"New-Api-User": user_id}
    attempts = [
        {
            "name": token_name,
            "remain_quota": 0,
            "expired_time": -1,
            "unlimited_quota": True,
            "model_limits_enabled": False,
            "model_limits": "",
            "allow_ips": "",
            "group": group or "",
            "cross_group_retry": False,
        },
        {
            "name": token_name,
            "remain_quota": 0,
            "expired_time": -1,
            "unlimited_quota": True,
            "model_limits_enabled": False,
            "model_limits": "",
            "group": group or "",
        },
    ]
    last_error = ""
    for body in attempts:
        try:
            payload = request_json(opener, "/api/token/", method="POST", body=body, headers=headers)
            if payload.get("success") is False:
                last_error = str(payload.get("message") or "token create failed")
                continue
            token = select_token(user_id, token_name, group)
            if token and token.get("key"):
                token["source"] = "created"
                return token
        except Exception as error:  # Keep trying compatible payloads.
            last_error = str(error)
    if last_error:
        raise RuntimeError(last_error)
    return None


def create_token_direct(user_id: str, group: str = "") -> dict[str, Any]:
    token_name = f"LOOM Launcher {int(time.time())}-{secrets.token_hex(3)}"
    key = secrets.token_hex(24)
    now = int(time.time())
    _newapi_execute(
        """
        insert into tokens(
            user_id, key, status, name, created_time, accessed_time,
            expired_time, remain_quota, unlimited_quota, model_limits_enabled,
            model_limits, allow_ips, used_quota, "group", cross_group_retry, deleted_at
        )
        values(?, ?, 1, ?, ?, 0, -1, 0, ?, ?, '', '', 0, ?, ?, null)
        """,
        (user_id, key, token_name, now, True, False, str(group or "").strip(), False),
    )
    token = select_token(user_id, token_name, group)
    if token and token.get("key"):
        token["source"] = "created"
        return token
    return {
        "id": None,
        "key": key,
        "name": token_name,
        "remainQuota": 0,
        "unlimitedQuota": True,
        "modelLimitsEnabled": False,
        "modelLimits": "",
        "tokenGroup": str(group or "").strip(),
        "permissionMode": "default",
        "source": "created",
    }


def fetch_models(token: str) -> list[str]:
    opener = urllib.request.build_opener()
    try:
        payload = request_json(opener, "/v1/models", headers={"Authorization": f"Bearer {token}"}, timeout=25)
    except Exception:
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    models: list[str] = []
    for item in data:
        model_id = ""
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
        else:
            model_id = str(item or "").strip()
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def handle_launcher_token(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    username = str(body.get("username") or body.get("email") or "").strip()
    password = str(body.get("password") or "")
    preferred_name = str(body.get("tokenName") or "").strip()
    install_id, device_id = lease_identity_from_body(body)
    if not username or not password:
        return 400, {"success": False, "error": "username and password are required"}
    if not reserve_auth_attempt(username, "password"):
        return 429, {"success": False, "error": "登录失败次数过多，请稍后再试"}

    try:
        user = authenticate_user(username, password)
    except Exception:
        release_auth_attempt(username, "password")
        return 503, {"success": False, "error": "authentication service is temporarily unavailable"}
    if not user:
        return 401, {"success": False, "error": "invalid username or password"}
    clear_auth_failures(username, "password")

    user_id = str(user.get("id") or "")
    if not user_id:
        return 500, {"success": False, "error": "authenticated user id is unavailable"}

    return build_launcher_payload(
        user_id=user_id,
        account=str(user.get("email") or user.get("username") or username),
        group=str(user.get("group") or "default"),
        preferred_name=preferred_name,
        install_id=install_id,
        device_id=device_id,
    )


def handle_ensure_launcher_token(
    body: dict[str, Any],
    authorization: str = "",
    *,
    entitlement_source_verified: bool = False,
) -> tuple[int, dict[str, Any]]:
    owner = api_token_owner(authorization)
    if not owner:
        return 401, {"success": False, "error": "valid API token is required"}
    if not launcher_token_name(owner.get("name")) or not launcher_token_uses_default_policy(
        owner,
        str(owner.get("user_group") or "default"),
    ):
        return 403, {
            "success": False,
            "error": "launcher token upgrade requires re-login",
        }
    user_id = str(owner.get("user_id") or "")
    if not user_id:
        return 401, {"success": False, "error": "API token owner is unavailable"}
    account = str(owner.get("email") or owner.get("username") or user_id)
    group = str(owner.get("user_group") or "default")
    install_id, device_id = lease_identity_from_body(body)
    return build_launcher_payload(
        user_id=user_id,
        account=account,
        group=group,
        install_id=install_id,
        device_id=device_id,
        entitlement_source_verified=entitlement_source_verified,
    )


def build_launcher_payload(
    *,
    user_id: str,
    account: str,
    group: str = "default",
    preferred_name: str = "",
    session_cookie: str = "",
    install_id: str = "",
    device_id: str = "",
    entitlement_source_verified: bool = False,
) -> tuple[int, dict[str, Any]]:
    token = select_token(user_id, preferred_name, group)
    expected_group = str(group or "default").strip()
    if token and expected_group and str(token.get("tokenGroup") or "").strip() != expected_group:
        token = None
    source = "existing"
    if not token:
        token = create_token_direct(user_id, group)
        source = "created"
    if not token or not token.get("key"):
        return 500, {"success": False, "error": "no usable token found or created"}

    key = str(token["key"])
    models = fetch_models(key)
    if not models:
        return 503, {"success": False, "error": "model catalog is temporarily unavailable"}
    entitlement = effective_entitlement_policy(str(user_id), group)
    lease_payload: dict[str, Any] = {
        "success": True,
        "entitlement": entitlement,
    }
    if install_id or device_id:
        entitlement_status, lease_payload = issue_entitlement_lease(
            account_id=str(user_id),
            group=group,
            install_id=install_id,
            device_id=device_id,
            session_token=key,
            source_verified=entitlement_source_verified,
        )
        if (
            entitlement_status != 200
            and str(lease_payload.get("code") or "") != "authorization_required"
        ):
            return entitlement_status, lease_payload
    data = {
        "userId": user_id,
        "account": account,
        "group": group or "default",
        "sessionCookie": session_cookie,
        "key": key,
        "apiKey": key,
        "apiToken": key,
        "tokenMasked": mask_secret(key),
        "tokenId": token.get("id"),
        "tokenName": token.get("name"),
        "tokenKind": "launcher",
        "permissionMode": token.get("permissionMode") or "default",
        "tokenGroup": token.get("tokenGroup") or "",
        "source": token.get("source") or source,
        "remainQuota": token.get("remainQuota"),
        "unlimitedQuota": token.get("unlimitedQuota"),
        "modelLimitsEnabled": token.get("modelLimitsEnabled"),
        "modelLimits": token.get("modelLimits"),
        "models": models,
        "api": {
            "token": key,
            "apiKey": key,
            "baseUrl": PUBLIC_API_BASE,
        },
        "entitlement": lease_payload.get("entitlement") or entitlement,
        "defaults": {
            "textModel": default_text_model(models),
        },
    }
    if "entitlementLease" in lease_payload:
        data["entitlementLease"] = lease_payload["entitlementLease"]
        data["entitlementKey"] = lease_payload["entitlementKey"]
    return 200, {"success": True, "data": data}


def handle_email_code_register(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    email = normalize_email(body.get("email") or body.get("username"))
    password = str(body.get("password") or "").strip()
    code = str(body.get("code") or body.get("verification_code") or "").strip()
    if not email or "@" not in email:
        return 400, {"success": False, "error": "valid email is required"}
    if len(password) < 6:
        return 400, {"success": False, "error": "password must contain at least 6 characters"}
    if not code:
        return 400, {"success": False, "error": "verification code is required"}
    if not reserve_auth_attempt(email, "register"):
        return 429, {"success": False, "error": "注册失败次数过多，请稍后再试"}

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    try:
        register_payload = request_json(
            opener,
            "/api/user/register",
            method="POST",
            body={
                "email": email,
                "username": email,
                "password": password,
                "code": code,
                "verification_code": code,
            },
        )
    except BridgeUpstreamError as error:
        if error.status_code not in {400, 409, 422}:
            release_auth_attempt(email, "register")
        return upstream_error_response(error)
    except RuntimeError as error:
        return 400, {"success": False, "error": str(error)}
    if register_payload.get("success") is False:
        return 400, {
            "success": False,
            "error": str(register_payload.get("message") or register_payload.get("error") or "registration failed"),
        }
    clear_auth_failures(email, "register")

    try:
        login_payload = request_json(
            opener,
            "/api/user/login",
            method="POST",
            body={"username": email, "password": password},
        )
    except BridgeUpstreamError as error:
        status, error_payload = upstream_error_response(error, authentication=True)
        if status == 401:
            status = 502
        error_payload["error"] = f"registration succeeded but automatic login failed: {error_payload['error']}"
        return status, error_payload
    except RuntimeError as error:
        return 502, {"success": False, "error": f"registration succeeded but automatic login failed: {error}"}
    if login_payload.get("success") is False:
        return 502, {"success": False, "error": "registration succeeded but automatic login failed"}

    user = find_user_by_email(email)
    if not user:
        return 500, {"success": False, "error": "registration succeeded but the account was not found"}
    user_id = candidate_user_id(login_payload) or str(user.get("id") or "")
    group = user_group(login_payload) or str(user.get("group") or "default")
    install_id, device_id = lease_identity_from_body(body)
    status, payload = build_launcher_payload(
        user_id=user_id,
        account=email,
        group=group,
        session_cookie=cookie_header(cookie_jar),
        install_id=install_id,
        device_id=device_id,
    )
    if status != 200:
        return status, payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data["account"] = {
        "id": user_id,
        "email": email,
        "username": str(user.get("username") or email),
        "name": str(user.get("display_name") or user.get("username") or email),
        "plan": group,
        "group": group,
    }
    data["quota"] = {
        "remaining": data.get("remainQuota"),
    }
    payload["data"] = data
    return status, payload


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def option_value(key: str, default: str = "") -> str:
    try:
        row = _newapi_fetchone("select value from options where key = ? limit 1", (key,))
        if row and row["value"] is not None:
            return str(row["value"])
    except Exception:
        return default
    return default


def auth_capabilities_payload() -> dict[str, Any]:
    smtp_configured = all(
        option_value(key)
        for key in ("SMTPServer", "SMTPAccount", "SMTPToken")
    )
    public_origin = PUBLIC_API_BASE[:-3] if PUBLIC_API_BASE.endswith("/v1") else PUBLIC_API_BASE
    return {
        "passwordLogin": True,
        "inlineEmailCode": smtp_configured,
        "inlineRegistration": False,
        "webRegistrationRequired": smtp_configured,
        "registrationUrl": f"{public_origin}/register",
        "emailConfigured": smtp_configured,
        "emailReason": (
            "邮箱验证码登录可用；新账号请在网页完成人机验证和注册。"
            if smtp_configured
            else "服务器 SMTP 邮箱尚未配置，请使用密码登录。"
        ),
    }


def option_bool(key: str, default: bool = False) -> bool:
    value = option_value(key, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on", "enabled"}


def find_user_by_email(email: str) -> dict[str, Any] | None:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        return None
    return _newapi_fetchone(
        """
        select id, username, email, display_name, status, "group", deleted_at
        from users
        where lower(email) = ? and deleted_at is null
        order by id desc
        limit 1
        """,
        (normalized,),
    )


def find_user_by_login(login_name: str) -> dict[str, Any] | None:
    normalized = str(login_name or "").strip().lower()
    if not normalized:
        return None
    return _newapi_fetchone(
        """
        select id, username, email, password, display_name, status, "group", deleted_at
        from users
        where (lower(username) = ? or lower(email) = ?) and deleted_at is null
        order by id desc
        limit 1
        """,
        (normalized, normalized),
    )


def authenticate_user(login_name: str, password: str) -> dict[str, Any] | None:
    user = find_user_by_login(login_name)
    stored_hash = str(user.get("password") or "").encode("utf-8") if user else DUMMY_PASSWORD_HASH
    try:
        password_matches = bcrypt.checkpw(str(password or "").encode("utf-8"), stored_hash)
    except (TypeError, ValueError):
        password_matches = False
    if not user or not password_matches:
        return None
    if int(user.get("status") or 0) != 1 or user.get("deleted_at"):
        return None
    user.pop("password", None)
    return user


def _email_code_hash(email: str, purpose: str, code: str) -> str:
    message = f"{normalize_email(email)}:{purpose}:{code}".encode("utf-8")
    return hmac.new(EMAIL_CODE_PEPPER.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _send_login_email_code(email: str, code: str) -> None:
    server = option_value("SMTPServer")
    account = option_value("SMTPAccount")
    password = option_value("SMTPToken")
    sender = option_value("SMTPFrom", account)
    port = int(option_value("SMTPPort", "465") or "465")
    ssl_enabled = option_bool("SMTPSSLEnabled", True)
    if not server or not account or not password or not sender:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = f"{PRODUCT_NAME} 登录验证码"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                f"你的 {PRODUCT_NAME} 登录验证码是：{code}",
                "",
                f"验证码 {EMAIL_CODE_TTL_SEC // 60} 分钟内有效。若不是你本人操作，请忽略这封邮件。",
            ]
        )
    )
    if ssl_enabled:
        with smtplib.SMTP_SSL(server, port, timeout=20) as client:
            client.login(account, password)
            client.send_message(message)
    else:
        with smtplib.SMTP(server, port, timeout=20) as client:
            client.starttls()
            client.login(account, password)
            client.send_message(message)


def _email_code_connection() -> sqlite3.Connection:
    connection = _bind_connection()
    connection.execute(
        """
        create table if not exists email_code_challenges (
            id integer primary key autoincrement,
            email text not null,
            purpose text not null,
            code_hash text not null,
            created_at integer not null,
            expires_at integer not null,
            attempts integer not null default 0,
            consumed_at integer
        )
        """
    )
    connection.execute("create index if not exists idx_email_code_email_purpose on email_code_challenges(email, purpose, created_at)")
    connection.execute(
        """
        create table if not exists auth_failures (
            id integer primary key autoincrement,
            subject_hash text not null,
            action text not null,
            created_at integer not null
        )
        """
    )
    connection.execute("create index if not exists idx_auth_failures_subject_action on auth_failures(subject_hash, action, created_at)")
    return connection


def _auth_subject_hash(subject: str) -> str:
    normalized = str(subject or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def auth_failure_limited(subject: str, action: str, now: int | None = None) -> bool:
    now = int(now or time.time())
    subject_hash = _auth_subject_hash(subject)
    connection = _email_code_connection()
    try:
        connection.execute("delete from auth_failures where created_at < ?", (now - AUTH_FAILURE_RATE_WINDOW_SEC,))
        count = connection.execute(
            "select count(*) from auth_failures where subject_hash = ? and action = ? and created_at >= ?",
            (subject_hash, action, now - AUTH_FAILURE_RATE_WINDOW_SEC),
        ).fetchone()[0]
        connection.commit()
        return int(count or 0) >= AUTH_FAILURE_RATE_LIMIT
    finally:
        connection.close()


def reserve_auth_attempt(subject: str, action: str, now: int | None = None) -> bool:
    now = int(now or time.time())
    connection = _email_code_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("delete from auth_failures where created_at < ?", (now - AUTH_FAILURE_RATE_WINDOW_SEC,))
        count = connection.execute(
            "select count(*) from auth_failures where subject_hash = ? and action = ? and created_at >= ?",
            (_auth_subject_hash(subject), action, now - AUTH_FAILURE_RATE_WINDOW_SEC),
        ).fetchone()[0]
        if int(count or 0) >= AUTH_FAILURE_RATE_LIMIT:
            connection.commit()
            return False
        connection.execute(
            "insert into auth_failures(subject_hash, action, created_at) values(?, ?, ?)",
            (_auth_subject_hash(subject), action, now),
        )
        connection.commit()
        return True
    finally:
        connection.close()


def clear_auth_failures(subject: str, action: str) -> None:
    connection = _email_code_connection()
    try:
        connection.execute(
            "delete from auth_failures where subject_hash = ? and action = ?",
            (_auth_subject_hash(subject), action),
        )
        connection.commit()
    finally:
        connection.close()


def release_auth_attempt(subject: str, action: str) -> None:
    connection = _email_code_connection()
    try:
        connection.execute(
            """
            delete from auth_failures
            where id = (
                select id from auth_failures
                where subject_hash = ? and action = ?
                order by id desc
                limit 1
            )
            """,
            (_auth_subject_hash(subject), action),
        )
        connection.commit()
    finally:
        connection.close()


def cleanup_email_codes(now: int | None = None) -> None:
    now = int(now or time.time())
    connection = _email_code_connection()
    try:
        connection.execute(
            "delete from email_code_challenges where expires_at < ? or (consumed_at is not null and consumed_at < ?)",
            (now - 60, now - 60),
        )
        connection.commit()
    finally:
        connection.close()


def handle_email_code_send(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    email = normalize_email(body.get("email"))
    purpose = str(body.get("purpose") or body.get("scene") or body.get("type") or "login").strip().lower()
    purpose = "login" if purpose in {"", "login", "signin", "sign_in", "email"} else purpose
    if "@" not in email:
        return 400, {"success": False, "error": "请输入有效邮箱"}
    if purpose != "login":
        return 400, {"success": False, "error": "邮箱验证码注册请使用 NewAPI 原生注册接口"}

    user = find_user_by_email(email)
    if not user:
        return 404, {"success": False, "error": "邮箱尚未注册，请先注册或使用密码登录"}
    if int(user.get("status") or 0) != 1:
        return 403, {"success": False, "error": "账号当前不可用，请联系管理员"}

    now = int(time.time())
    cleanup_email_codes(now)
    connection = _email_code_connection()
    try:
        recent_count = connection.execute(
            """
            select count(*) from email_code_challenges
            where email = ? and purpose = ? and created_at >= ?
            """,
            (email, "login", now - EMAIL_CODE_RATE_WINDOW_SEC),
        ).fetchone()[0]
        if int(recent_count or 0) >= EMAIL_CODE_RATE_LIMIT:
            return 429, {"success": False, "error": "验证码发送过于频繁，请稍后再试"}

        code = f"{secrets.randbelow(1000000):06d}"
        _send_login_email_code(email, code)
        connection.execute(
            """
            insert into email_code_challenges(email, purpose, code_hash, created_at, expires_at, attempts, consumed_at)
            values(?, ?, ?, ?, ?, 0, null)
            """,
            (email, "login", _email_code_hash(email, "login", code), now, now + EMAIL_CODE_TTL_SEC),
        )
        connection.commit()
    finally:
        connection.close()

    return 200, {
        "success": True,
        "data": {
            "sent": True,
            "email": email,
            "expiresIn": EMAIL_CODE_TTL_SEC,
            "retryAfter": 60,
        },
    }


def handle_email_code_login(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    email = normalize_email(body.get("email"))
    code = str(body.get("code") or body.get("emailCode") or "").strip()
    if "@" not in email:
        return 400, {"success": False, "error": "请输入有效邮箱"}
    if not code:
        return 400, {"success": False, "error": "请输入验证码"}

    now = int(time.time())
    cleanup_email_codes(now)
    expected_hash = _email_code_hash(email, "login", code)
    connection = _email_code_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            select id, code_hash, expires_at, attempts, consumed_at
            from email_code_challenges
            where email = ? and purpose = ? and consumed_at is null
            order by created_at desc, id desc
            limit 1
            """,
            (email, "login"),
        ).fetchone()
        if not row:
            connection.rollback()
            return 400, {"success": False, "error": "验证码不存在或已过期，请重新发送"}
        if int(row["expires_at"] or 0) < now:
            connection.execute("delete from email_code_challenges where id = ?", (row["id"],))
            connection.commit()
            return 400, {"success": False, "error": "验证码已过期，请重新发送"}
        if int(row["attempts"] or 0) >= 5:
            connection.execute("delete from email_code_challenges where id = ?", (row["id"],))
            connection.commit()
            return 400, {"success": False, "error": "验证码尝试次数过多，请重新发送"}
        if not hmac.compare_digest(str(row["code_hash"]), expected_hash):
            connection.execute("update email_code_challenges set attempts = attempts + 1 where id = ?", (row["id"],))
            connection.commit()
            return 400, {"success": False, "error": "验证码错误，请重新输入"}
        connection.execute("update email_code_challenges set consumed_at = ? where id = ?", (now, row["id"]))
        connection.commit()
    finally:
        connection.close()

    user = find_user_by_email(email)
    if not user:
        return 404, {"success": False, "error": "邮箱尚未注册，请先注册或使用密码登录"}
    if int(user.get("status") or 0) != 1:
        return 403, {"success": False, "error": "账号当前不可用，请联系管理员"}
    account = str(user.get("email") or user.get("username") or email)
    install_id, device_id = lease_identity_from_body(body)
    return build_launcher_payload(
        user_id=str(user["id"]),
        account=account,
        group=str(user.get("group") or "default"),
        install_id=install_id,
        device_id=device_id,
    )


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _bind_connection() -> sqlite3.Connection:
    directory = os.path.dirname(BIND_DB_PATH)
    if directory:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    connection = sqlite3.connect(BIND_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        create table if not exists bind_tickets (
            ticket_hash text primary key,
            payload text not null,
            created_at integer not null,
            expires_at integer not null,
            claimed_at integer
        );
        create table if not exists entitlement_accounts (
            account_id text primary key,
            entitlement_version integer not null default 1,
            updated_at integer not null,
            revoked_at integer not null default 0
        );
        create table if not exists entitlement_devices (
            account_id text not null,
            install_id text not null,
            device_id text not null,
            first_seen_at integer not null,
            last_seen_at integer not null,
            entitlement_version integer not null,
            revoked_at integer not null default 0,
            primary key(account_id, install_id, device_id)
        );
        create table if not exists entitlement_phone_seats (
            account_id text not null,
            phone_device_id text not null,
            first_claimed_at integer not null,
            last_seen_at integer not null,
            last_host_device_id text not null,
            entitlement_version integer not null,
            released_at integer not null default 0,
            primary key(account_id, phone_device_id)
        );
        create table if not exists entitlement_account_grants (
            account_id text primary key,
            plan text not null,
            features_json text not null,
            limits_json text not null,
            expires_at integer not null default 0,
            source text not null,
            code_label text not null default '',
            updated_at integer not null,
            revoked_at integer not null default 0
        );
        create table if not exists entitlement_audit (
            id integer primary key autoincrement,
            account_id text not null,
            install_id text,
            device_id text,
            action text not null,
            code text not null,
            details_json text not null,
            created_at integer not null
        );
        """
    )
    try:
        os.chmod(BIND_DB_PATH, 0o600)
    except OSError:
        pass
    return connection


def account_entitlement_policy(
    connection: sqlite3.Connection,
    account_id: str,
    group: str,
    now: int,
) -> dict[str, Any]:
    row = connection.execute(
        """
        select plan, features_json, limits_json, expires_at, source, code_label, revoked_at
        from entitlement_account_grants
        where account_id = ?
        """,
        (account_id,),
    ).fetchone()
    if not row or int(row["revoked_at"] or 0):
        return inactive_entitlement_policy(group)
    expires_at = int(row["expires_at"] or 0)
    if expires_at and expires_at <= now:
        return inactive_entitlement_policy(group)
    try:
        features = json.loads(row["features_json"] or "[]")
        limits = json.loads(row["limits_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return inactive_entitlement_policy(group)
    if not isinstance(features, list) or not isinstance(limits, dict):
        return inactive_entitlement_policy(group)
    policy = normalize_authorization_entitlement(
        {
            "plan": row["plan"],
            "features": features,
            "limits": limits,
            "expiresAt": expires_at,
            "codeLabel": row["code_label"],
        }
    )
    policy["group"] = str(group or "default").strip() or "default"
    policy["source"] = str(row["source"] or "authorization_code")
    return policy


def effective_entitlement_policy(
    account_id: str,
    group: str = "default",
) -> dict[str, Any]:
    connection = _bind_connection()
    try:
        return account_entitlement_policy(
            connection,
            str(account_id),
            group,
            int(time.time()),
        )
    finally:
        connection.close()


def persist_account_entitlement_grant(
    account_id: str,
    entitlement: dict[str, Any] | None,
    *,
    action: str,
) -> int:
    account = str(account_id)
    now = int(time.time())
    connection = _bind_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = ensure_entitlement_account(connection, account, now)
        account_row = connection.execute(
            "select revoked_at from entitlement_accounts where account_id = ?",
            (account,),
        ).fetchone()
        account_was_revoked = bool(
            account_row and int(account_row["revoked_at"] or 0)
        )
        previous = connection.execute(
            """
            select plan, features_json, limits_json, expires_at, source, code_label, revoked_at
            from entitlement_account_grants
            where account_id = ?
            """,
            (account,),
        ).fetchone()
        if entitlement is None:
            next_values = None
        else:
            normalized = normalize_authorization_entitlement(entitlement)
            next_values = (
                normalized["plan"],
                json.dumps(normalized["features"], ensure_ascii=False, sort_keys=True),
                json.dumps(normalized["limits"], ensure_ascii=False, sort_keys=True),
                int(normalized.get("expiresAt") or 0),
                "authorization_code",
                str(normalized.get("codeLabel") or ""),
                0,
            )
        previous_values = (
            tuple(previous)
            if previous is not None
            else None
        )
        changed = previous_values != next_values
        if entitlement is not None and account_was_revoked:
            changed = True
        if entitlement is None:
            if previous is not None and not int(previous["revoked_at"] or 0):
                connection.execute(
                    """
                    update entitlement_account_grants
                    set revoked_at = ?, updated_at = ?
                    where account_id = ?
                    """,
                    (now, now, account),
                )
            else:
                changed = False
        else:
            connection.execute(
                """
                insert into entitlement_account_grants(
                    account_id, plan, features_json, limits_json, expires_at,
                    source, code_label, updated_at, revoked_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, 0)
                on conflict(account_id) do update set
                    plan = excluded.plan,
                    features_json = excluded.features_json,
                    limits_json = excluded.limits_json,
                    expires_at = excluded.expires_at,
                    source = excluded.source,
                    code_label = excluded.code_label,
                    updated_at = excluded.updated_at,
                    revoked_at = 0
                """,
                (account, *next_values[:-1], now),
            )
        if changed:
            version += 1
            connection.execute(
                """
                update entitlement_accounts
                set entitlement_version = ?, updated_at = ?, revoked_at = 0
                where account_id = ?
                """,
                (version, now, account),
            )
        record_entitlement_audit(
            connection,
            account_id=account,
            action=action,
            code="ok",
            details={
                "plan": str(entitlement.get("plan") or "inactive") if entitlement else "inactive",
                "entitlementVersion": version,
                "changed": changed,
            },
            now=now,
        )
        connection.commit()
        return version
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_entitlement_account(connection: sqlite3.Connection, account_id: str, now: int) -> int:
    row = connection.execute(
        "select entitlement_version from entitlement_accounts where account_id = ?",
        (account_id,),
    ).fetchone()
    if row:
        return int(row["entitlement_version"] or 1)
    connection.execute(
        """
        insert into entitlement_accounts(account_id, entitlement_version, updated_at, revoked_at)
        values(?, 1, ?, 0)
        """,
        (account_id, now),
    )
    return 1


def record_entitlement_audit(
    connection: sqlite3.Connection,
    *,
    account_id: str,
    install_id: str = "",
    device_id: str = "",
    action: str,
    code: str,
    details: dict[str, Any] | None = None,
    now: int | None = None,
) -> None:
    connection.execute(
        """
        insert into entitlement_audit(account_id, install_id, device_id, action, code, details_json, created_at)
        values(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            install_id,
            device_id,
            action,
            code,
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            int(now or time.time()),
        ),
    )


def entitlement_audit_events(account_id: str) -> list[dict[str, Any]]:
    connection = _bind_connection()
    try:
        rows = connection.execute(
            """
            select account_id, install_id, device_id, action, code, details_json, created_at
            from entitlement_audit
            where account_id = ?
            order by id
            """,
            (str(account_id),),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError:
                item["details"] = {}
            events.append(item)
        return events
    finally:
        connection.close()


def signed_entitlement_lease(
    *,
    account_id: str,
    session_token: str,
    install_id: str,
    device_id: str,
    policy: dict[str, Any],
    entitlement_version: int,
    now: int,
) -> dict[str, Any]:
    grant_expires_at = _entitlement_expiry_epoch(policy.get("expiresAt"))
    expires_at = now + int(ENTITLEMENT_LEASE_TTL_SEC)
    if grant_expires_at:
        expires_at = min(expires_at, grant_expires_at)
    offline_grace_until = expires_at + int(ENTITLEMENT_OFFLINE_GRACE_SEC)
    if grant_expires_at:
        offline_grace_until = min(offline_grace_until, grant_expires_at)
    lease = {
        "schema": "loom.entitlement_lease.v1",
        "accountId": account_id,
        "sessionBinding": entitlement_session_binding(session_token),
        "installId": install_id,
        "deviceId": device_id,
        "hostDeviceId": device_id,
        "plan": str(policy.get("plan") or "activated"),
        "source": str(policy.get("source") or "authorization_code"),
        "features": list(policy["features"]),
        "limits": dict(policy["limits"]),
        "issuedAt": now,
        "expiresAt": expires_at,
        "offlineGraceUntil": offline_grace_until,
        "entitlementVersion": int(entitlement_version),
        "keyId": ENTITLEMENT_KEY_ID,
    }
    lease["signature"] = sign_entitlement_payload(lease)
    return lease


def issue_entitlement_lease(
    *,
    account_id: str,
    group: str,
    install_id: str,
    device_id: str,
    session_token: str,
    source_verified: bool = False,
) -> tuple[int, dict[str, Any]]:
    if not install_id or not device_id or not session_token:
        return 400, entitlement_error(
            "device_identity_required",
            "矩阵授权需要完整的设备身份和账号会话，请升级 LOOM 后重新登录。",
            "relogin_with_device_identity",
            {
                "accountId": account_id,
                "hasInstallId": bool(install_id),
                "hasDeviceId": bool(device_id),
                "hasSessionToken": bool(session_token),
            },
        )

    if not source_verified:
        cached_policy = effective_entitlement_policy(account_id, group)
        cached_paid = cached_policy.get("source") == "authorization_code"
        if not LICENSE_ENTITLEMENT_SERVICE_TOKEN:
            if cached_paid:
                return 503, entitlement_error(
                    "authorization_service_unavailable",
                    "授权服务尚未配置，不能签发新的付费矩阵权益。",
                    "contact_support",
                    {"offlineLeasePreserved": True},
                )
        else:
            try:
                live_entitlement = (
                    current_authorization_entitlement_from_license_server(account_id)
                )
                persist_account_entitlement_grant(
                    account_id,
                    live_entitlement,
                    action="sync_before_issue_lease",
                )
            except BridgeUpstreamError as error:
                permanent_codes = {
                    "ACCOUNT_ENTITLEMENT_NOT_FOUND",
                    "ACCOUNT_ENTITLEMENT_REVOKED",
                    "LICENSE_DISABLED",
                    "LICENSE_EXPIRED",
                    "LICENSE_INVALID",
                }
                if error.code in permanent_codes:
                    persist_account_entitlement_grant(
                        account_id,
                        None,
                        action=f"sync_before_issue_lease_{error.code.lower()}",
                    )
                elif cached_paid:
                    return 503, entitlement_error(
                        "authorization_service_unavailable",
                        "授权服务暂时不可用，不能签发新的付费矩阵权益。",
                        "retry_later",
                        {
                            "upstreamCode": error.code or "service_unavailable",
                            "offlineLeasePreserved": True,
                        },
                    )

    now = int(time.time())
    try:
        key_payload = entitlement_key_payload()
    except Exception:
        return 503, entitlement_error(
            "entitlement_signing_unavailable",
            "服务器权益签名密钥未配置，暂时无法签发矩阵授权。",
            "contact_support",
            {"accountId": account_id},
        )

    connection = _bind_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        policy = account_entitlement_policy(connection, account_id, group, now)
        version = ensure_entitlement_account(connection, account_id, now)
        if policy.get("source") != "authorization_code":
            record_entitlement_audit(
                connection,
                account_id=account_id,
                install_id=install_id,
                device_id=device_id,
                action="issue_lease",
                code="authorization_required",
                details={"group": policy["group"]},
                now=now,
            )
            connection.commit()
            payload = entitlement_error(
                "authorization_required",
                "当前账号尚未绑定有效授权码，手机连接和矩阵能力暂不可用。",
                "bind_authorization_code",
                {"accountId": account_id},
            )
            payload["entitlement"] = policy
            return 403, payload
        connection.execute(
            """
            insert into entitlement_devices(
                account_id, install_id, device_id, first_seen_at, last_seen_at,
                entitlement_version, revoked_at
            )
            values(?, ?, ?, ?, ?, ?, 0)
            on conflict(account_id, install_id, device_id) do update set
                last_seen_at = excluded.last_seen_at,
                entitlement_version = excluded.entitlement_version,
                revoked_at = 0
            """,
            (account_id, install_id, device_id, now, now, version),
        )
        lease = signed_entitlement_lease(
            account_id=account_id,
            session_token=session_token,
            install_id=install_id,
            device_id=device_id,
            policy=policy,
            entitlement_version=version,
            now=now,
        )
        record_entitlement_audit(
            connection,
            account_id=account_id,
            install_id=install_id,
            device_id=device_id,
            action="issue_lease",
            code="ok",
            details={
                "group": policy["group"],
                "plan": policy["plan"],
                "limits": policy["limits"],
                "entitlementVersion": version,
            },
            now=now,
        )
        connection.commit()
        return 200, {
            "success": True,
            "entitlement": policy,
            "entitlementLease": lease,
            "entitlementKey": key_payload,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def revoke_account_entitlements(account_id: str, *, reason: str = "") -> int:
    now = int(time.time())
    account = str(account_id)
    connection = _bind_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = ensure_entitlement_account(connection, account, now) + 1
        connection.execute(
            """
            update entitlement_accounts
            set entitlement_version = ?, updated_at = ?, revoked_at = ?
            where account_id = ?
            """,
            (version, now, now, account),
        )
        connection.execute(
            "update entitlement_devices set revoked_at = ? where account_id = ? and revoked_at = 0",
            (now, account),
        )
        record_entitlement_audit(
            connection,
            account_id=account,
            action="revoke_entitlements",
            code="ok",
            details={"reason": reason, "entitlementVersion": version},
            now=now,
        )
        connection.commit()
        return version
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def verify_entitlement_lease(lease: Any) -> tuple[int, dict[str, Any]]:
    if not isinstance(lease, dict):
        return 401, entitlement_error(
            "entitlement_required",
            "缺少有效的账号权益租约，请重新登录。",
            "relogin",
        )
    required = {
        "accountId",
        "sessionBinding",
        "installId",
        "deviceId",
        "features",
        "limits",
        "issuedAt",
        "expiresAt",
        "offlineGraceUntil",
        "entitlementVersion",
        "keyId",
        "signature",
    }
    missing = sorted(key for key in required if key not in lease)
    if missing:
        return 401, entitlement_error(
            "lease_malformed",
            "账号权益租约字段不完整，请重新登录。",
            "relogin",
            {"missing": missing},
        )
    signature = str(lease.get("signature") or "")
    signed = dict(lease)
    signed.pop("signature", None)
    try:
        entitlement_private_key().public_key().verify(
            base64.b64decode(signature, validate=True),
            canonical_json(signed).encode("utf-8"),
        )
    except (InvalidSignature, ValueError, TypeError, RuntimeError, base64.binascii.Error):
        return 401, entitlement_error(
            "lease_signature_invalid",
            "账号权益租约验签失败，请重新登录。",
            "relogin",
        )
    return 200, {"success": True, "lease": lease}


def _normalized_phone_device_ids(phone_device_ids: Any) -> list[str]:
    if not isinstance(phone_device_ids, (list, tuple, set)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in phone_device_ids:
        device_id = str(value or "").strip()
        if not device_id or device_id in seen:
            continue
        seen.add(device_id)
        normalized.append(device_id)
    return normalized


def _phone_seat_result(
    connection: sqlite3.Connection,
    *,
    lease: dict[str, Any],
    operation: str,
    phone_device_ids: list[str],
    now: int,
) -> tuple[int, dict[str, Any]]:
    account_id = str(lease["accountId"])
    host_device_id = str(lease.get("hostDeviceId") or lease["deviceId"])
    limit = max(1, int((lease.get("limits") or {}).get("devices") or 1))
    released: list[str] = []

    if operation == "matrix.device.release":
        if phone_device_ids:
            placeholders = ",".join("?" for _ in phone_device_ids)
            connection.execute(
                f"""
                update entitlement_phone_seats
                set released_at = ?, last_seen_at = ?
                where account_id = ? and phone_device_id in ({placeholders}) and released_at = 0
                """,
                (now, now, account_id, *phone_device_ids),
            )
            released = phone_device_ids
        record_entitlement_audit(
            connection,
            account_id=account_id,
            install_id=str(lease["installId"]),
            device_id=host_device_id,
            action=operation,
            code="ok",
            details={"releasedPhoneDeviceIds": released},
            now=now,
        )
        phone_seat_lease = signed_phone_seat_lease(
            connection,
            entitlement_lease=lease,
            now=now,
        )
        return 200, {
            "success": True,
            "code": "ok",
            "operation": operation,
            "releasedPhoneDeviceIds": released,
            "limits": lease["limits"],
            "phoneSeatLease": phone_seat_lease,
        }

    if not phone_device_ids:
        return 400, entitlement_error(
            "phone_device_required",
            "矩阵任务需要明确选择手机，不能使用空目标绕过设备额度。",
            "select_phone_device",
            {"operation": operation},
        )

    placeholders = ",".join("?" for _ in phone_device_ids)
    foreign_rows = connection.execute(
        f"""
        select account_id, phone_device_id
        from entitlement_phone_seats
        where phone_device_id in ({placeholders})
          and account_id != ?
          and released_at = 0
        order by first_claimed_at, account_id
        """,
        (*phone_device_ids, account_id),
    ).fetchall()
    foreign_phone_ids = sorted(
        {str(row["phone_device_id"]) for row in foreign_rows}
    )
    if foreign_phone_ids and operation != "matrix.device.reclaim":
        details = {
            "phoneDeviceIds": foreign_phone_ids,
            "operation": operation,
        }
        record_entitlement_audit(
            connection,
            account_id=account_id,
            install_id=str(lease["installId"]),
            device_id=host_device_id,
            action=operation,
            code="phone_owned_by_another_account",
            details=details,
            now=now,
        )
        return 409, entitlement_error(
            "phone_owned_by_another_account",
            "这台手机已绑定其他模型账号，请在手机端重新生成配对码后修复连接。",
            "repair_phone",
            details,
        )
    reclaimed: list[str] = []
    if foreign_phone_ids:
        connection.execute(
            f"""
            update entitlement_phone_seats
            set released_at = ?, last_seen_at = ?
            where phone_device_id in ({placeholders})
              and account_id != ?
              and released_at = 0
            """,
            (now, now, *phone_device_ids, account_id),
        )
        reclaimed = foreign_phone_ids

    active_rows = connection.execute(
        """
        select phone_device_id
        from entitlement_phone_seats
        where account_id = ? and released_at = 0
        """,
        (account_id,),
    ).fetchall()
    active = {str(row["phone_device_id"]) for row in active_rows}
    new_phone_ids = [device_id for device_id in phone_device_ids if device_id not in active]
    if len(active) + len(new_phone_ids) > limit:
        details = {
            "accountId": account_id,
            "limit": limit,
            "used": len(active),
            "requested": len(phone_device_ids),
            "newPhoneDeviceIds": new_phone_ids,
        }
        record_entitlement_audit(
            connection,
            account_id=account_id,
            install_id=str(lease["installId"]),
            device_id=host_device_id,
            action=operation,
            code="device_limit_exceeded",
            details=details,
            now=now,
        )
        return 403, entitlement_error(
            "device_limit_exceeded",
            "当前账号绑定的手机数量超过系统安全上限，请联系技术支持。",
            "contact_support",
            details,
        )

    for phone_device_id in phone_device_ids:
        connection.execute(
            """
            insert into entitlement_phone_seats(
                account_id, phone_device_id, first_claimed_at, last_seen_at,
                last_host_device_id, entitlement_version, released_at
            )
            values(?, ?, ?, ?, ?, ?, 0)
            on conflict(account_id, phone_device_id) do update set
                last_seen_at = excluded.last_seen_at,
                last_host_device_id = excluded.last_host_device_id,
                entitlement_version = excluded.entitlement_version,
                released_at = 0
            """,
            (
                account_id,
                phone_device_id,
                now,
                now,
                host_device_id,
                int(lease["entitlementVersion"]),
            ),
        )
    record_entitlement_audit(
        connection,
        account_id=account_id,
        install_id=str(lease["installId"]),
        device_id=host_device_id,
        action=operation,
        code="ok",
        details={"claimedPhoneDeviceIds": phone_device_ids, "limit": limit},
        now=now,
    )
    phone_seat_lease = signed_phone_seat_lease(
        connection,
        entitlement_lease=lease,
        now=now,
    )
    return 200, {
        "success": True,
        "code": "ok",
        "operation": operation,
        "claimedPhoneDeviceIds": phone_device_ids,
        **({"reclaimedPhoneDeviceIds": reclaimed} if reclaimed else {}),
        "features": lease["features"],
        "limits": lease["limits"],
        "phoneSeatLease": phone_seat_lease,
    }


def signed_phone_seat_lease(
    connection: sqlite3.Connection,
    *,
    entitlement_lease: dict[str, Any],
    now: int,
) -> dict[str, Any]:
    account_id = str(entitlement_lease["accountId"])
    host_device_id = str(
        entitlement_lease.get("hostDeviceId")
        or entitlement_lease["deviceId"]
    )
    rows = connection.execute(
        """
        select phone_device_id
        from entitlement_phone_seats
        where account_id = ? and last_host_device_id = ? and released_at = 0
        order by phone_device_id
        """,
        (account_id, host_device_id),
    ).fetchall()
    expires_at = min(
        int(entitlement_lease["offlineGraceUntil"]),
        now + int(ENTITLEMENT_OFFLINE_GRACE_SEC),
    )
    payload = {
        "schema": PHONE_SEAT_LEASE_SCHEMA,
        "accountId": account_id,
        "installId": str(entitlement_lease["installId"]),
        "hostDeviceId": host_device_id,
        "phoneDeviceIds": [str(row["phone_device_id"]) for row in rows],
        "limit": max(
            1,
            int((entitlement_lease.get("limits") or {}).get("devices") or 1),
        ),
        "issuedAt": now,
        "expiresAt": expires_at,
        "entitlementVersion": int(entitlement_lease["entitlementVersion"]),
        "keyId": ENTITLEMENT_KEY_ID,
    }
    payload["signature"] = sign_entitlement_payload(payload)
    return payload


def authorize_entitlement_operation(
    lease: Any,
    operation: str = "matrix.task.start",
    phone_device_ids: Any = None,
) -> tuple[int, dict[str, Any]]:
    status, payload = verify_entitlement_lease(lease)
    if status != 200:
        return status, payload
    checked_lease = payload["lease"]
    account_id = str(checked_lease["accountId"])
    install_id = str(checked_lease["installId"])
    device_id = str(checked_lease["deviceId"])
    now = int(time.time())
    normalized_operation = str(operation or "matrix.task.start").strip()
    normalized_phone_ids = _normalized_phone_device_ids(phone_device_ids)
    if normalized_operation in SAFETY_ENTITLEMENT_OPERATIONS:
        connection = _bind_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if normalized_operation == "matrix.device.release":
                status, result = _phone_seat_result(
                    connection,
                    lease=checked_lease,
                    operation=normalized_operation,
                    phone_device_ids=normalized_phone_ids,
                    now=now,
                )
            else:
                record_entitlement_audit(
                    connection,
                    account_id=account_id,
                    install_id=install_id,
                    device_id=device_id,
                    action=normalized_operation,
                    code="safety_cleanup_allowed",
                    details={"entitlementVersion": checked_lease["entitlementVersion"]},
                    now=now,
                )
                status, result = 200, {
                    "success": True,
                    "code": "ok",
                    "operation": normalized_operation,
                    "features": checked_lease["features"],
                    "limits": checked_lease["limits"],
                }
            connection.commit()
            return status, result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    refresh_account_entitlement_authorization(account_id)
    connection = _bind_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            select entitlement_version, revoked_at
            from entitlement_accounts
            where account_id = ?
            """,
            (account_id,),
        ).fetchone()
        if (
            not row
            or int(row["revoked_at"] or 0)
            or int(row["entitlement_version"] or 0)
            != int(checked_lease["entitlementVersion"])
        ):
            connection.rollback()
            return 403, entitlement_error(
                "lease_revoked",
                "账号权益已刷新或撤销，请重新同步账号。",
                "refresh_entitlement",
                {"accountId": account_id},
            )
        device = connection.execute(
            """
            select 1 from entitlement_devices
            where account_id = ? and install_id = ? and device_id = ? and revoked_at = 0
            """,
            (account_id, install_id, device_id),
        ).fetchone()
        if not device:
            connection.rollback()
            return 403, entitlement_error(
                "device_not_registered",
                "当前设备未在账号权益中登记，请重新登录。",
                "relogin",
                {"accountId": account_id, "installId": install_id, "deviceId": device_id},
            )
        if int(checked_lease["expiresAt"]) <= now:
            connection.rollback()
            return 403, entitlement_error(
                "lease_expired",
                "账号权益租约已过期，不能启动新的矩阵任务；请联网重新同步账号。",
                "refresh_entitlement",
                {"accountId": account_id, "expiredAt": checked_lease["expiresAt"]},
            )
        status, result = _phone_seat_result(
            connection,
            lease=checked_lease,
            operation=normalized_operation,
            phone_device_ids=normalized_phone_ids,
            now=now,
        )
        connection.commit()
        return status, result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def cleanup_bind_tickets(now: int | None = None) -> None:
    now = int(now or time.time())
    connection = _bind_connection()
    try:
        connection.execute(
            "delete from bind_tickets where expires_at < ? or (claimed_at is not null and claimed_at < ?)",
            (now - 60, now - 60),
        )
        connection.commit()
    finally:
        connection.close()


def _bind_ticket_encryption_key() -> bytes:
    if BIND_TICKET_SECRET:
        secret = BIND_TICKET_SECRET.encode("utf-8")
    else:
        secret = entitlement_private_key().private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    return hashlib.sha256(b"loom-bind-ticket-aesgcm-v1\0" + secret).digest()


def _seal_bind_ticket_payload(payload: dict[str, Any]) -> str:
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = AESGCM(_bind_ticket_encryption_key()).encrypt(
        nonce,
        plaintext,
        b"loom.bind_ticket.v1",
    )
    return "v1." + base64.b64encode(nonce + ciphertext).decode("ascii")


def _open_bind_ticket_payload(sealed: str) -> dict[str, Any]:
    if not sealed.startswith("v1."):
        raise ValueError("unsupported bind ticket payload")
    raw = base64.b64decode(sealed[3:], validate=True)
    if len(raw) < 29:
        raise ValueError("invalid bind ticket payload")
    plaintext = AESGCM(_bind_ticket_encryption_key()).decrypt(
        raw[:12],
        raw[12:],
        b"loom.bind_ticket.v1",
    )
    payload = json.loads(plaintext.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid bind ticket payload")
    return payload


def create_bind_ticket(payload: dict[str, Any], ttl_sec: int = BIND_TICKET_TTL_SEC) -> dict[str, Any]:
    ticket = "ocb_" + secrets.token_urlsafe(24)
    now = int(time.time())
    expires_at = now + int(ttl_sec)
    cleanup_bind_tickets(now)
    connection = _bind_connection()
    try:
        connection.execute(
            """
            insert into bind_tickets(ticket_hash, payload, created_at, expires_at, claimed_at)
            values(?, ?, ?, ?, null)
            """,
            (_ticket_hash(ticket), _seal_bind_ticket_payload(payload), now, expires_at),
        )
        connection.commit()
    finally:
        connection.close()
    return {"ticket": ticket, "expiresAt": expires_at}


def _public_bind_payload(data: dict[str, Any], ticket_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket": ticket_info["ticket"],
        "expiresAt": ticket_info["expiresAt"],
        "account": data.get("account") or "",
        "userId": data.get("userId") or "",
        "tokenMasked": data.get("tokenMasked") or mask_secret(str(data.get("key") or "")),
        "tokenId": data.get("tokenId"),
        "tokenName": data.get("tokenName") or "",
        "source": data.get("source") or "bridge",
        "models": data.get("models") if isinstance(data.get("models"), list) else [],
    }


def handle_bind_start(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    status, payload = handle_launcher_token(body)
    if status != 200 or payload.get("success") is False:
        return status, payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data.get("key"):
        return 500, {"success": False, "error": "launcher token payload missing key"}
    ticket_info = create_bind_ticket(payload)
    return 200, {"success": True, "data": _public_bind_payload(data, ticket_info)}


def handle_bind_claim(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    ticket = str(body.get("ticket") or body.get("code") or "").strip()
    if not ticket:
        return 400, {"success": False, "error": "ticket is required"}
    now = int(time.time())
    cleanup_bind_tickets(now)
    connection = _bind_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "select payload, expires_at, claimed_at from bind_tickets where ticket_hash = ?",
            (_ticket_hash(ticket),),
        ).fetchone()
        if not row:
            connection.rollback()
            return 404, {"success": False, "error": "ticket not found"}
        if row["claimed_at"]:
            connection.rollback()
            return 410, {"success": False, "error": "ticket already claimed"}
        if int(row["expires_at"] or 0) < now:
            connection.execute("delete from bind_tickets where ticket_hash = ?", (_ticket_hash(ticket),))
            connection.commit()
            return 410, {"success": False, "error": "ticket expired"}
        connection.execute("delete from bind_tickets where ticket_hash = ?", (_ticket_hash(ticket),))
        connection.commit()
    finally:
        connection.close()
    try:
        payload = _open_bind_ticket_payload(str(row["payload"] or ""))
    except Exception:
        return 500, {"success": False, "error": "ticket payload corrupted"}
    if not isinstance(payload, dict):
        return 500, {"success": False, "error": "ticket payload invalid"}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    install_id, device_id = lease_identity_from_body(body)
    if data is not None and (install_id or device_id):
        entitlement_status, entitlement_payload = issue_entitlement_lease(
            account_id=str(data.get("userId") or ""),
            group=str(data.get("group") or "default"),
            install_id=install_id,
            device_id=device_id,
            session_token=str(data.get("apiToken") or data.get("apiKey") or data.get("key") or ""),
        )
        if (
            entitlement_status != 200
            and str(entitlement_payload.get("code") or "") != "authorization_required"
        ):
            return entitlement_status, entitlement_payload
        data["entitlement"] = entitlement_payload["entitlement"]
        if "entitlementLease" in entitlement_payload:
            data["entitlementLease"] = entitlement_payload["entitlementLease"]
            data["entitlementKey"] = entitlement_payload["entitlementKey"]
    return 200, payload


def entitlement_public_key_response() -> tuple[int, dict[str, Any]]:
    try:
        return 200, {"success": True, "data": entitlement_key_payload()}
    except Exception:
        return 503, entitlement_error(
            "entitlement_signing_unavailable",
            "服务器权益签名密钥未配置，暂时无法提供矩阵授权公钥。",
            "contact_support",
        )


def handle_entitlement_refresh(body: dict[str, Any], authorization: str = "") -> tuple[int, dict[str, Any]]:
    owner = api_token_owner(authorization)
    if owner and not LICENSE_ENTITLEMENT_SERVICE_TOKEN:
        return 503, entitlement_error(
            "authorization_service_unavailable",
            "授权服务尚未配置，无法安全刷新矩阵权益。",
            "contact_support",
            {"offlineLeasePreserved": True},
        )
    source_verified = False
    if owner:
        account_id = str(owner.get("user_id") or "")
        try:
            entitlement = current_authorization_entitlement_from_license_server(account_id)
            persist_account_entitlement_grant(
                account_id,
                entitlement,
                action="sync_authorization_code",
            )
            source_verified = True
        except BridgeUpstreamError as error:
            permanent_codes = {
                "ACCOUNT_ENTITLEMENT_NOT_FOUND",
                "ACCOUNT_ENTITLEMENT_REVOKED",
                "LICENSE_DISABLED",
                "LICENSE_EXPIRED",
                "LICENSE_INVALID",
            }
            if error.code in permanent_codes:
                persist_account_entitlement_grant(
                    account_id,
                    None,
                    action=f"sync_authorization_code_{error.code.lower()}",
                )
                source_verified = True
            else:
                # Refuse to mint a fresh paid lease while the source of truth
                # is unreachable. The client keeps its existing signed lease
                # only until that lease's bounded offline grace expires.
                return 503, entitlement_error(
                    "authorization_service_unavailable",
                    "授权服务暂时不可用，正在保留本机已有的离线权益。",
                    "retry_later",
                    {
                        "upstreamCode": error.code or "service_unavailable",
                        "offlineLeasePreserved": True,
                    },
                )
    return handle_ensure_launcher_token(
        body,
        authorization,
        entitlement_source_verified=source_verified,
    )


def handle_entitlement_redeem(
    body: dict[str, Any],
    authorization: str = "",
) -> tuple[int, dict[str, Any]]:
    owner = api_token_owner(authorization)
    if not owner:
        return 401, entitlement_error(
            "account_token_required",
            "请先登录模型账号，再绑定授权码。",
            "login",
        )
    code = str(body.get("code") or "").strip().upper()
    if len(code) < 8 or len(code) > 256:
        return 400, entitlement_error(
            "authorization_code_invalid",
            "请输入有效的商业授权码。",
            "check_code",
        )
    install_id, device_id = lease_identity_from_body(body)
    if not install_id or not device_id:
        return 400, entitlement_error(
            "device_identity_required",
            "当前安装缺少设备身份，请升级 LOOM 后重新登录。",
            "relogin_with_device_identity",
        )
    account_id = str(owner.get("user_id") or "")
    try:
        entitlement = redeem_authorization_code_with_license_server(
            code,
            account_id=account_id,
        )
        persist_account_entitlement_grant(
            account_id,
            entitlement,
            action="redeem_authorization_code",
        )
    except BridgeUpstreamError as error:
        status = int(error.status_code or 502)
        public_status = status if status in {400, 401, 403, 404, 409, 422, 429} else 503
        public_code = {
            "LICENSE_EXPIRED": "authorization_code_expired",
            "LICENSE_DISABLED": "authorization_code_disabled",
            "ACCOUNT_ENTITLEMENT_REVOKED": "authorization_code_revoked",
            "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED": "authorization_code_already_bound",
            "LICENSE_INVALID": "authorization_code_invalid",
            "LICENSE_DATA_INVALID": "authorization_code_invalid",
            "ACCOUNT_REDEEM_INVALID_REQUEST": "authorization_code_invalid",
        }.get(
            error.code,
            "authorization_code_rejected"
            if public_status < 500
            else "authorization_service_unavailable",
        )
        return public_status, entitlement_error(
            public_code,
            str(error),
            "check_code" if public_status < 500 else "retry_later",
            error.details,
        )
    status, payload = issue_entitlement_lease(
        account_id=account_id,
        group=str(owner.get("user_group") or "default"),
        install_id=install_id,
        device_id=device_id,
        session_token=str(owner.get("key") or ""),
        source_verified=True,
    )
    if status != 200:
        return status, payload
    return 200, payload


def handle_entitlement_migrate_legacy(
    body: dict[str, Any],
    authorization: str = "",
) -> tuple[int, dict[str, Any]]:
    owner = api_token_owner(authorization)
    if not owner:
        return 401, entitlement_error(
            "account_token_required",
            "请先登录模型账号，再迁移旧版商业授权。",
            "login",
        )

    legacy_license = body.get("legacyLicense")
    required_fields = {
        "schema",
        "licenseId",
        "installId",
        "deviceId",
        "expires",
        "signature",
    }
    try:
        proof_size = len(
            json.dumps(
                legacy_license,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        proof_size = 0
    if (
        not isinstance(legacy_license, dict)
        or legacy_license.get("schema") != "loom.license.v1"
        or not required_fields.issubset(legacy_license)
        or any(
            not str(legacy_license.get(field) or "").strip()
            for field in required_fields
        )
        or proof_size <= 0
        or proof_size > 131072
    ):
        return 400, entitlement_error(
            "legacy_license_proof_invalid",
            "旧版授权证明无效，无法安全迁移。",
            "use_authorization_code",
        )

    install_id, device_id = lease_identity_from_body(body)
    if not install_id or not device_id:
        return 400, entitlement_error(
            "device_identity_required",
            "当前安装缺少设备身份，请升级 LOOM 后重新登录。",
            "relogin_with_device_identity",
        )

    account_id = str(owner.get("user_id") or "")
    try:
        entitlement = migrate_legacy_authorization_with_license_server(
            legacy_license,
            account_id=account_id,
        )
        persist_account_entitlement_grant(
            account_id,
            entitlement,
            action="migrate_legacy_authorization",
        )
    except BridgeUpstreamError as error:
        status = int(error.status_code or 502)
        public_status = status if status in {400, 401, 403, 404, 409, 422, 429} else 503
        public_code = {
            "LEGACY_LICENSE_PROOF_INVALID": "legacy_license_proof_invalid",
            "LEGACY_LICENSE_PROOF_NOT_FOUND": "legacy_license_proof_not_found",
            "LICENSE_EXPIRED": "authorization_code_expired",
            "LICENSE_DISABLED": "authorization_code_disabled",
            "ACCOUNT_ENTITLEMENT_REVOKED": "authorization_code_revoked",
            "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED": "authorization_code_already_bound",
        }.get(
            error.code,
            "legacy_license_migration_rejected"
            if public_status < 500
            else "authorization_service_unavailable",
        )
        return public_status, entitlement_error(
            public_code,
            str(error),
            "use_authorization_code" if public_status < 500 else "retry_later",
            error.details,
        )

    status, payload = issue_entitlement_lease(
        account_id=account_id,
        group=str(owner.get("user_group") or "default"),
        install_id=install_id,
        device_id=device_id,
        session_token=str(owner.get("key") or ""),
        source_verified=True,
    )
    if status != 200:
        return status, payload
    return 200, payload


def handle_entitlement_check(
    body: dict[str, Any],
    authorization: str = "",
) -> tuple[int, dict[str, Any]]:
    owner = api_token_owner(authorization)
    if not owner:
        return 401, entitlement_error(
            "account_token_required",
            "需要有效的模型账号令牌才能校验手机席位。",
            "relogin",
        )
    lease = body.get("entitlementLease") or body.get("lease")
    lease_account_id = str(lease.get("accountId") or "") if isinstance(lease, dict) else ""
    owner_account_id = str(owner.get("user_id") or "")
    if not lease_account_id or lease_account_id != owner_account_id:
        return 403, entitlement_error(
            "account_mismatch",
            "当前账号与权益租约不一致。",
            "relogin",
            {
                "leaseAccountId": lease_account_id,
                "tokenAccountId": owner_account_id,
            },
        )
    lease_session_binding = (
        str(lease.get("sessionBinding") or "") if isinstance(lease, dict) else ""
    )
    owner_session_binding = entitlement_session_binding(str(owner.get("key") or ""))
    if (
        not lease_session_binding
        or not owner_session_binding
        or not hmac.compare_digest(lease_session_binding, owner_session_binding)
    ):
        return 403, entitlement_error(
            "account_session_mismatch",
            "当前登录会话与权益租约不一致，请重新登录后再试。",
            "relogin",
        )
    operation = str(body.get("operation") or "matrix.task.start")
    return authorize_entitlement_operation(
        lease,
        operation,
        body.get("phoneDeviceIds") or body.get("deviceIds"),
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep default access logging quiet to avoid accidental sensitive context.
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, status: int, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"success": True, "service": "openclaw-newapi-bridge"})
            return
        if self.path == "/api/openclaw/auth/capabilities":
            self._send(200, {"success": True, "data": auth_capabilities_payload()})
            return
        if self.path == "/api/openclaw/entitlements/public-key":
            status, payload = entitlement_public_key_response()
            self._send(status, payload)
            return
        if self.path in ("/api/openclaw/bind/page", "/openclaw-bind"):
            self._send_html(200, BIND_PAGE_HTML)
            return
        self._send(404, {"success": False, "error": "not found"})

    def do_POST(self) -> None:
        routes = {
            "/api/openclaw/launcher-token": handle_launcher_token,
            "/api/openclaw/launcher-token/ensure": lambda body: handle_ensure_launcher_token(
                body,
                self.headers.get("Authorization") or "",
            ),
            "/api/openclaw/entitlements/refresh": lambda body: handle_entitlement_refresh(
                body,
                self.headers.get("Authorization") or "",
            ),
            "/api/openclaw/entitlements/redeem": lambda body: handle_entitlement_redeem(
                body,
                self.headers.get("Authorization") or "",
            ),
            "/api/openclaw/entitlements/migrate-legacy": lambda body: handle_entitlement_migrate_legacy(
                body,
                self.headers.get("Authorization") or "",
            ),
            "/api/openclaw/entitlements/check": lambda body: handle_entitlement_check(
                body,
                self.headers.get("Authorization") or "",
            ),
            "/api/openclaw/bind/start": handle_bind_start,
            "/api/openclaw/bind/claim": handle_bind_claim,
            "/api/openclaw/auth/email-code/send": handle_email_code_send,
            "/api/openclaw/email-code/send": handle_email_code_send,
            "/api/openclaw/auth/email-code/login": handle_email_code_login,
            "/api/openclaw/email-code/login": handle_email_code_login,
            "/api/openclaw/auth/email-code/register": handle_email_code_register,
            "/api/openclaw/email-code/register": handle_email_code_register,
        }
        handler = routes.get(self.path)
        if not handler:
            self._send(404, {"success": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            max_request_bytes = (
                196608
                if self.path == "/api/openclaw/entitlements/migrate-legacy"
                else 65536
            )
            if length > max_request_bytes:
                self._send(413, {"success": False, "error": "request too large"})
                return
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send(400, {"success": False, "error": "invalid json"})
                return
            status, payload = handler(body)
            self._send(status, payload)
        except Exception:
            self._send(500, {
                "success": False,
                "error": "internal server error",
                "code": "bridge_internal_error",
            })


def main() -> None:
    entitlement_private_key()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"openclaw-newapi-bridge listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
