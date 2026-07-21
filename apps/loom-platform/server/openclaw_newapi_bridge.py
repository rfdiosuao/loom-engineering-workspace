#!/usr/bin/env python3
"""Small NewAPI helper for OpenClaw account login.

This service runs on localhost behind nginx. It authenticates against the
existing NewAPI login endpoint, then reads the user's full API token from the
local SQLite database. NewAPI's public token APIs return masked keys, which is
safe for the web UI but not enough for a launcher that must configure an
OpenAI-compatible gateway.
"""

from __future__ import annotations

import http.cookiejar
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import smtplib
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import bcrypt

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
BIND_DB_PATH = os.environ.get("OPENCLAW_BIND_DB", "/tmp/openclaw-bind-tickets.db")
BIND_TICKET_TTL_SEC = int(os.environ.get("OPENCLAW_BIND_TICKET_TTL_SEC", "600"))
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


class BridgeUpstreamError(RuntimeError):
    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


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
    )


def handle_ensure_launcher_token(
    _body: dict[str, Any],
    authorization: str = "",
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
    return build_launcher_payload(user_id=user_id, account=account, group=group)


def build_launcher_payload(
    *,
    user_id: str,
    account: str,
    group: str = "default",
    preferred_name: str = "",
    session_cookie: str = "",
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
    return 200, {
        "success": True,
        "data": {
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
            "defaults": {
                "textModel": default_text_model(models),
            },
        },
    }


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
    status, payload = build_launcher_payload(
        user_id=user_id,
        account=email,
        group=group,
        session_cookie=cookie_header(cookie_jar),
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
    return build_launcher_payload(
        user_id=str(user["id"]),
        account=account,
        group=str(user.get("group") or "default"),
    )


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _bind_connection() -> sqlite3.Connection:
    directory = os.path.dirname(BIND_DB_PATH)
    if directory:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    connection = sqlite3.connect(BIND_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        create table if not exists bind_tickets (
            ticket_hash text primary key,
            payload text not null,
            created_at integer not null,
            expires_at integer not null,
            claimed_at integer
        )
        """
    )
    try:
        os.chmod(BIND_DB_PATH, 0o600)
    except OSError:
        pass
    return connection


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
            (_ticket_hash(ticket), json.dumps(payload, ensure_ascii=False), now, expires_at),
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
        payload = json.loads(row["payload"])
    except Exception:
        return 500, {"success": False, "error": "ticket payload corrupted"}
    if not isinstance(payload, dict):
        return 500, {"success": False, "error": "ticket payload invalid"}
    return 200, payload


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
            if length > 65536:
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
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"openclaw-newapi-bridge listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
