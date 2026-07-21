from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from collections.abc import Callable
from typing import Any

from .. import db
from ..config import Settings
from ..security import admin_session_token_hash, generate_admin_session_token
from ..timeutils import add_days_iso, utc_now
from . import accounts


ConnectFn = Callable[[], sqlite3.Connection]
TokenLoader = Callable[[], str | None]
CountFn = Callable[..., int]
TokenHashFn = Callable[[str], str]
TokenGenerator = Callable[[], str]
AdminContextFromRowFn = Callable[..., dict[str, Any]]


def _connection_factory(connect_fn: ConnectFn | None) -> ConnectFn:
    return connect_fn or db.connect


def _load_admin_token() -> str | None:
    token = os.environ.get("LICENSE_ADMIN_TOKEN")
    if token:
        return token.strip()
    try:
        with open(Settings.from_env().admin_token_file, "r", encoding="utf-8") as file:
            return file.read().strip() or None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def admin_context_from_row(row: sqlite3.Row, *, auth_type: str, token: str = "") -> dict[str, Any]:
    display_name = str(row["display_name"] or "").strip() or str(row["username"] or "admin")
    account_id = int(row["id"])
    role = str(row["role"] or accounts.ACCOUNT_ROLE_MERCHANT)
    return {
        "authType": auth_type,
        "accountId": account_id,
        "username": str(row["username"] or ""),
        "displayName": display_name,
        "role": role,
        "status": str(row["status"] or accounts.ACCOUNT_STATUS_ACTIVE),
        "actor": f"{str(row['username'] or 'admin')}#{account_id}",
        "sessionToken": token,
    }


def load_admin_context_from_session(
    token: str,
    *,
    connect_fn: ConnectFn | None = None,
    token_hash_fn: TokenHashFn = admin_session_token_hash,
    admin_context_from_row_fn: AdminContextFromRowFn = admin_context_from_row,
) -> dict[str, Any] | None:
    session_token = str(token or "").strip()
    if not session_token:
        return None
    session_hash = token_hash_fn(session_token)
    now = utc_now()
    with _connection_factory(connect_fn)() as conn:
        row = conn.execute(
            """
            select s.session_hash, s.account_id, s.created_at, s.updated_at, s.expires_at,
                   s.revoked_at, s.request_ip, s.user_agent,
                   a.id, a.username, a.display_name, a.password_hash, a.role, a.status, a.note,
                   a.created_at, a.updated_at, a.last_login_at, a.last_login_ip
            from admin_sessions s join accounts a on a.id = s.account_id where s.session_hash = ?
            """,
            (session_hash,),
        ).fetchone()
        if not row:
            return None
        if row["revoked_at"] or row["expires_at"] < now or row["status"] != accounts.ACCOUNT_STATUS_ACTIVE:
            return None
        conn.execute("update admin_sessions set updated_at = ? where session_hash = ?", (now, session_hash))
        conn.commit()
    return admin_context_from_row_fn(row, auth_type="session", token=session_token)


def load_legacy_admin_context(token: str, *, load_admin_token_fn: TokenLoader | None = None) -> dict[str, Any] | None:
    expected = (load_admin_token_fn or _load_admin_token)()
    provided = str(token or "").strip()
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        return None
    digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()[:10]
    return {
        "authType": "legacy",
        "accountId": 0,
        "username": "legacy-admin",
        "displayName": "Legacy Admin",
        "role": accounts.ACCOUNT_ROLE_SUPER_ADMIN,
        "status": accounts.ACCOUNT_STATUS_ACTIVE,
        "actor": f"legacy:{digest}",
        "sessionToken": provided,
    }


def create_admin_session(
    account_id: int,
    *,
    request_ip: str = "",
    user_agent: str = "",
    connect_fn: ConnectFn | None = None,
    ttl_days: int | None = None,
    token_hash_fn: TokenHashFn = admin_session_token_hash,
    token_generator: TokenGenerator = generate_admin_session_token,
) -> tuple[str, str]:
    raw_token = token_generator()
    session_hash = token_hash_fn(raw_token)
    now = utc_now()
    expires_at = add_days_iso(ttl_days if ttl_days is not None else Settings.from_env().admin_session_ttl_days)
    with _connection_factory(connect_fn)() as conn:
        conn.execute(
            """insert into admin_sessions (session_hash, account_id, created_at, updated_at, expires_at,
               revoked_at, request_ip, user_agent) values (?, ?, ?, ?, ?, '', ?, ?)""",
            (session_hash, int(account_id), now, now, expires_at, request_ip[:80], user_agent[:240]),
        )
        conn.commit()
    return raw_token, expires_at


def revoke_admin_session(
    token: str,
    *,
    connect_fn: ConnectFn | None = None,
    token_hash_fn: TokenHashFn = admin_session_token_hash,
) -> bool:
    session_token = str(token or "").strip()
    if not session_token:
        return False
    session_hash = token_hash_fn(session_token)
    with _connection_factory(connect_fn)() as conn:
        result = conn.execute(
            "update admin_sessions set revoked_at = ?, updated_at = ? where session_hash = ? and revoked_at = ''",
            (utc_now(), utc_now(), session_hash),
        )
        conn.commit()
    return result.rowcount > 0


def auth_status_snapshot(
    *,
    connect_fn: ConnectFn | None = None,
    load_admin_token_fn: TokenLoader | None = None,
    count_accounts_fn: CountFn | None = None,
    count_invites_fn: CountFn | None = None,
    ttl_days: int | None = None,
) -> dict[str, Any]:
    count_accounts_call = count_accounts_fn or (lambda: accounts.count_accounts(connect_fn=connect_fn))
    count_invites_call = count_invites_fn or (lambda **kwargs: accounts.count_invites(connect_fn=connect_fn, **kwargs))
    account_count = count_accounts_call()
    invite_count = count_invites_call()
    active_invite_count = count_invites_call(active_only=True)
    active_ttl_days = ttl_days if ttl_days is not None else Settings.from_env().admin_session_ttl_days
    return {
        "hasAccounts": account_count > 0,
        "accountCount": account_count,
        "inviteCount": invite_count,
        "activeInviteCount": active_invite_count,
        "registrationMode": "invite",
        "inviteRegistrationEnabled": True,
        "bootstrapAvailable": bool((load_admin_token_fn or _load_admin_token)()) and account_count == 0,
        "sessionTtlDays": active_ttl_days,
    }
