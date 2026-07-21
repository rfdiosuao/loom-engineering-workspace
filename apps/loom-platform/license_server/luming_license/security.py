from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlparse

from .config import DEFAULT_ADMIN_CORS_ORIGINS
from .errors import ActivationError


ADMIN_SESSION_COOKIE_NAME = "__Host-luming_admin_session"
StorageKeyFn = Callable[[str, str], str]
RateLimitCheckFn = Callable[[str, str], None]


@dataclass
class RateLimitState:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_DEFAULT_RATE_LIMIT_STATE = RateLimitState()


def password_hash(password: str, *, salt: bytes | None = None, iterations: int = 210_000) -> str:
    if not str(password or ""):
        raise ValueError("password is required")
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt_bytes, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.b64encode(salt_bytes).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_b64, digest_b64 = str(encoded or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, iterations)
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def admin_session_token_hash(token: str) -> str:
    return hashlib.sha256(f"openclaw-admin-session-v1:{str(token).strip()}".encode("utf-8")).hexdigest()


def generate_admin_session_token() -> str:
    return secrets.token_urlsafe(36)


def normalize_code_expires(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ActivationError("\u5230\u671f\u65e5\u671f\u4e0d\u80fd\u4e3a\u7a7a")
    candidate = raw.split("T", 1)[0].strip()
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError:
        raise ActivationError(f"\u5230\u671f\u65e5\u671f\u683c\u5f0f\u65e0\u6548\uff0c\u9700\u8981 YYYY-MM-DD\uff1a{raw}")
    if parsed <= date.today():
        raise ActivationError("\u5230\u671f\u65e5\u671f\u5fc5\u987b\u665a\u4e8e\u4eca\u5929")
    return candidate


def require_confirmation(body: dict[str, Any], expected: str) -> None:
    confirmation = str(body.get("confirmation") or "").strip().upper()
    if confirmation != expected:
        raise ActivationError(f"\u5371\u9669\u64cd\u4f5c\u9700\u8981\u8f93\u5165\u786e\u8ba4\u8bcd {expected}", status=400)


def extract_bearer_token(headers: Any) -> str:
    auth = str(headers.get("Authorization", "") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def extract_admin_session_cookie(headers: Any, *, cookie_name: str = ADMIN_SESSION_COOKIE_NAME) -> str:
    raw_cookie = str(headers.get("Cookie", "") or "").strip()
    if not raw_cookie:
        return ""
    try:
        cookies = SimpleCookie()
        cookies.load(raw_cookie)
        morsel = cookies.get(cookie_name)
        return str(morsel.value if morsel else "").strip()
    except Exception:
        return ""


def request_admin_token(headers: Any, *, cookie_name: str = ADMIN_SESSION_COOKIE_NAME) -> str:
    return (
        extract_bearer_token(headers)
        or str(headers.get("X-Admin-Session", "") or "").strip()
        or str(headers.get("X-Admin-Token", "") or "").strip()
        or extract_admin_session_cookie(headers, cookie_name=cookie_name)
    )


def admin_session_cookie(
    token: str,
    *,
    max_age: int | None = None,
    ttl_days: int = 30,
    cookie_name: str = ADMIN_SESSION_COOKIE_NAME,
) -> str:
    cookie_age = max_age if max_age is not None else ttl_days * 86_400
    value = str(token or "").strip()
    return (
        f"{cookie_name}={value}; Path=/; Max-Age={max(0, int(cookie_age))}; "
        "HttpOnly; Secure; SameSite=Strict"
    )


def rate_limit_storage_key(scope: str, key: str) -> str:
    return f"{scope}:{key.strip().lower()[:160]}"


def rate_limit_check(
    scope: str,
    key: str,
    *,
    state: RateLimitState | None = None,
    storage_key_fn: StorageKeyFn = rate_limit_storage_key,
) -> None:
    active_state = state or _DEFAULT_RATE_LIMIT_STATE
    now = time.time()
    storage_key = storage_key_fn(scope, key)
    with active_state.lock:
        entry = active_state.entries.get(storage_key)
        if not entry:
            return
        locked_until = float(entry.get("locked_until") or 0)
        if locked_until > now:
            raise ActivationError("\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5", 429)
        window_start = float(entry.get("window_start") or 0)
        window_seconds = float(entry.get("window_seconds") or 0)
        if window_seconds and now - window_start > window_seconds:
            active_state.entries.pop(storage_key, None)


def rate_limit_record_failure(
    scope: str,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    lockout_seconds: int,
    state: RateLimitState | None = None,
    storage_key_fn: StorageKeyFn = rate_limit_storage_key,
) -> None:
    active_state = state or _DEFAULT_RATE_LIMIT_STATE
    now = time.time()
    storage_key = storage_key_fn(scope, key)
    with active_state.lock:
        entry = active_state.entries.get(storage_key)
        if not entry or now - float(entry.get("window_start") or 0) > window_seconds:
            entry = {"window_start": now, "count": 0, "locked_until": 0, "window_seconds": window_seconds}
        entry["count"] = int(entry.get("count") or 0) + 1
        if int(entry["count"]) >= limit:
            entry["locked_until"] = now + lockout_seconds
        active_state.entries[storage_key] = entry


def rate_limit_clear(
    scope: str,
    key: str,
    *,
    state: RateLimitState | None = None,
    storage_key_fn: StorageKeyFn = rate_limit_storage_key,
) -> None:
    active_state = state or _DEFAULT_RATE_LIMIT_STATE
    with active_state.lock:
        active_state.entries.pop(storage_key_fn(scope, key), None)


def rate_limit_consume(
    scope: str,
    key: str,
    *,
    limit: int,
    window_seconds: int,
    lockout_seconds: int,
    state: RateLimitState | None = None,
    storage_key_fn: StorageKeyFn = rate_limit_storage_key,
    check_fn: RateLimitCheckFn | None = None,
) -> None:
    active_state = state or _DEFAULT_RATE_LIMIT_STATE
    if check_fn:
        check_fn(scope, key)
    else:
        rate_limit_check(scope, key, state=active_state, storage_key_fn=storage_key_fn)
    now = time.time()
    storage_key = storage_key_fn(scope, key)
    with active_state.lock:
        entry = active_state.entries.get(storage_key)
        if not entry or now - float(entry.get("window_start") or 0) > window_seconds:
            entry = {"window_start": now, "count": 0, "locked_until": 0, "window_seconds": window_seconds}
        count = int(entry.get("count") or 0)
        if count >= limit:
            entry["locked_until"] = now + lockout_seconds
            active_state.entries[storage_key] = entry
            raise ActivationError("\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5", 429)
        entry["count"] = count + 1
        if int(entry["count"]) >= limit:
            entry["locked_until"] = now + lockout_seconds
        active_state.entries[storage_key] = entry


def admin_cors_origin_allowed(origin: str, *, allowed_origins: set[str] | None = None) -> bool:
    normalized = origin.strip().rstrip("/")
    if not normalized:
        return False
    if normalized in (allowed_origins if allowed_origins is not None else set(DEFAULT_ADMIN_CORS_ORIGINS)):
        return True
    parsed = urlparse(normalized)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}


def is_admin_request_path(path: str) -> bool:
    return urlparse(path).path.startswith("/admin")
