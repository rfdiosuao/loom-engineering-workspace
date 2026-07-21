"""Identity, session, security, and ownership facade adapter blueprints."""

from __future__ import annotations

# Functions in this module are rebound to an owning facade namespace before use.
# ruff: noqa: F821

from .facade_core import ACCOUNT_ROLE_MERCHANT, ACCOUNT_STATUS_ACTIVE


# Task 4 facade adapters bind domain operations to this server instance.
def normalize_username(value: Any) -> str:
    return accounts.normalize_username(value)


def normalize_account_role(value: Any) -> str:
    return accounts.normalize_account_role(value)


def normalize_account_status(value: Any) -> str:
    return accounts.normalize_account_status(value)


def role_rank(role: str) -> int:
    return accounts.role_rank(role, normalize_account_role_fn=normalize_account_role)


def password_hash(
    password: str, *, salt: bytes | None = None, iterations: int = 210_000
) -> str:
    return security.password_hash(password, salt=salt, iterations=iterations)


def verify_password(password: str, encoded: str) -> bool:
    return security.verify_password(password, encoded)


def admin_session_token_hash(token: str) -> str:
    return security.admin_session_token_hash(token)


def generate_admin_session_token() -> str:
    return security.generate_admin_session_token()


def normalize_code_expires(value: str) -> str:
    return security.normalize_code_expires(value)


def require_confirmation(body: dict[str, Any], expected: str) -> None:
    security.require_confirmation(body, expected)


def extract_bearer_token(headers: Any) -> str:
    return security.extract_bearer_token(headers)


def extract_admin_session_cookie(headers: Any) -> str:
    return security.extract_admin_session_cookie(
        headers, cookie_name=ADMIN_SESSION_COOKIE_NAME
    )


def request_admin_token(headers: Any) -> str:
    return (
        extract_bearer_token(headers)
        or str(headers.get("X-Admin-Session", "") or "").strip()
        or str(headers.get("X-Admin-Token", "") or "").strip()
        or extract_admin_session_cookie(headers)
    )


def admin_session_cookie(token: str, *, max_age: int | None = None) -> str:
    return security.admin_session_cookie(
        token,
        max_age=max_age,
        ttl_days=ADMIN_SESSION_TTL_DAYS,
        cookie_name=ADMIN_SESSION_COOKIE_NAME,
    )


def account_row_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return accounts.account_row_public(row)


def get_account_by_username(username: str) -> sqlite3.Row | None:
    return accounts.get_account_by_username(
        username, connect_fn=connect, normalize_username_fn=normalize_username
    )


def get_account_by_id(account_id: int) -> sqlite3.Row | None:
    return accounts.get_account_by_id(account_id, connect_fn=connect)


def list_account_rows() -> list[dict[str, Any]]:
    return accounts.list_account_rows(
        connect_fn=connect, account_row_public_fn=account_row_public
    )


def account_summary_row(account_id: int) -> dict[str, Any] | None:
    row = get_account_by_id(account_id)
    return account_row_public(row) if row else None


def normalize_invite_code(value: Any) -> str:
    return accounts.normalize_invite_code(value)


def generate_invite_code() -> str:
    return accounts.generate_invite_code()


def invite_row_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return accounts.invite_row_public(row)


def count_invites(*, active_only: bool = False) -> int:
    return accounts.count_invites(active_only=active_only, connect_fn=connect)


def list_invite_rows() -> list[dict[str, Any]]:
    return accounts.list_invite_rows(
        connect_fn=connect, invite_row_public_fn=invite_row_public
    )


def get_invite_by_code(invite_code: str) -> sqlite3.Row | None:
    return accounts.get_invite_by_code(
        invite_code, connect_fn=connect, normalize_invite_code_fn=normalize_invite_code
    )


def _create_account_record_on_connection(
    conn: sqlite3.Connection,
    *,
    username: str,
    display_name: str = "",
    password: str = "",
    role: str = ACCOUNT_ROLE_MERCHANT,
    status: str = ACCOUNT_STATUS_ACTIVE,
    note: str = "",
    created_by: int = 0,
) -> tuple[dict[str, Any], str]:
    return accounts._create_account_record_on_connection(
        conn,
        username=username,
        display_name=display_name,
        password=password,
        role=role,
        status=status,
        note=note,
        created_by=created_by,
        password_hash_fn=password_hash,
        account_row_public_fn=account_row_public,
        normalize_username_fn=normalize_username,
        normalize_account_role_fn=normalize_account_role,
        normalize_account_status_fn=normalize_account_status,
    )


def create_invite_record(
    *, note: str = "", max_uses: int = 1, expires_at: str = "", created_by: int = 0
) -> tuple[dict[str, Any], str]:
    return accounts.create_invite_record(
        note=note,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=created_by,
        connect_fn=connect,
        invite_code_generator=generate_invite_code,
        invite_row_public_fn=invite_row_public,
    )


def toggle_invite_record(invite_id: int) -> dict[str, Any] | None:
    return accounts.toggle_invite_record(
        invite_id,
        connect_fn=connect,
        invite_row_public_fn=invite_row_public,
        get_invite_by_code_fn=get_invite_by_code,
    )


def register_account_with_invite(
    *,
    invite_code: str,
    username: str,
    display_name: str = "",
    password: str = "",
    request_ip: str = "",
    user_agent: str = "",
) -> tuple[dict[str, Any], str, str]:
    return accounts.register_account_with_invite(
        invite_code=invite_code,
        username=username,
        display_name=display_name,
        password=password,
        request_ip=request_ip,
        user_agent=user_agent,
        connect_fn=connect,
        audit_log=None if _active_audit_transaction() else add_audit_log,
        password_hash_fn=password_hash,
        create_account_on_connection_fn=_create_account_record_on_connection,
        normalize_invite_code_fn=normalize_invite_code,
        normalize_username_fn=normalize_username,
        normalization_commit_fn=_commit_registration_normalization,
    )


def _audit_registered_account(
    *, account: dict[str, Any], invite_code: str, request_ip: str = ""
) -> None:
    add_audit_log(
        action="accounts.register",
        target_type="account",
        target_id=str(account.get("username") or ""),
        before={},
        after=account,
        actor="invite:[REDACTED]" if invite_code else "invite",
        request_ip=request_ip,
        backup_path="",
    )


def create_account_record(
    *,
    username: str,
    display_name: str = "",
    password: str = "",
    role: str = ACCOUNT_ROLE_MERCHANT,
    status: str = ACCOUNT_STATUS_ACTIVE,
    note: str = "",
    created_by: int = 0,
) -> tuple[dict[str, Any], str]:
    return accounts.create_account_record(
        username=username,
        display_name=display_name,
        password=password,
        role=role,
        status=status,
        note=note,
        created_by=created_by,
        connect_fn=connect,
        password_hash_fn=password_hash,
        create_account_on_connection_fn=_create_account_record_on_connection,
    )


def update_account_record(
    *,
    account_id: int,
    display_name: str | None = None,
    role: str | None = None,
    status: str | None = None,
    password: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    return accounts.update_account_record(
        account_id=account_id,
        display_name=display_name,
        role=role,
        status=status,
        password=password,
        note=note,
        connect_fn=connect,
        password_hash_fn=password_hash,
        account_summary_row_fn=account_summary_row,
        normalize_account_role_fn=normalize_account_role,
        normalize_account_status_fn=normalize_account_status,
    )


def admin_context_from_row(
    row: sqlite3.Row, *, auth_type: str, token: str = ""
) -> dict[str, Any]:
    return sessions.admin_context_from_row(row, auth_type=auth_type, token=token)


def load_admin_context_from_session(token: str) -> dict[str, Any] | None:
    return sessions.load_admin_context_from_session(
        token,
        connect_fn=connect,
        token_hash_fn=admin_session_token_hash,
        admin_context_from_row_fn=admin_context_from_row,
    )


def load_legacy_admin_context(token: str) -> dict[str, Any] | None:
    return sessions.load_legacy_admin_context(
        token, load_admin_token_fn=load_admin_token
    )


def create_admin_session(
    account_id: int, *, request_ip: str = "", user_agent: str = ""
) -> tuple[str, str]:
    return sessions.create_admin_session(
        account_id,
        request_ip=request_ip,
        user_agent=user_agent,
        connect_fn=connect,
        ttl_days=ADMIN_SESSION_TTL_DAYS,
        token_hash_fn=admin_session_token_hash,
        token_generator=generate_admin_session_token,
    )


def update_account_last_login(account_id: int, request_ip: str = "") -> None:
    with connect() as conn:
        now = utc_now()
        conn.execute(
            "update accounts set last_login_at = ?, last_login_ip = ?, updated_at = ? where id = ?",
            (now, request_ip, now, account_id),
        )
        conn.commit()


def revoke_admin_session(token: str) -> bool:
    return sessions.revoke_admin_session(
        token, connect_fn=connect, token_hash_fn=admin_session_token_hash
    )


def count_accounts() -> int:
    return accounts.count_accounts(connect_fn=connect)


def count_active_super_admins() -> int:
    return accounts.count_active_super_admins(connect_fn=connect)


def auth_status_snapshot() -> dict[str, Any]:
    return sessions.auth_status_snapshot(
        connect_fn=connect,
        load_admin_token_fn=load_admin_token,
        count_accounts_fn=count_accounts,
        count_invites_fn=count_invites,
        ttl_days=ADMIN_SESSION_TTL_DAYS,
    )


def _rate_limit_state() -> security.RateLimitState:
    RATE_LIMIT_STATE.entries = RATE_LIMITS
    RATE_LIMIT_STATE.lock = RATE_LIMIT_LOCK
    return RATE_LIMIT_STATE


def rate_limit_storage_key(scope: str, key: str) -> str:
    return security.rate_limit_storage_key(scope, key)


def rate_limit_check(scope: str, key: str) -> None:
    security.rate_limit_check(
        scope, key, state=_rate_limit_state(), storage_key_fn=rate_limit_storage_key
    )


def rate_limit_record_failure(
    scope: str, key: str, *, limit: int, window_seconds: int, lockout_seconds: int
) -> None:
    security.rate_limit_record_failure(
        scope,
        key,
        limit=limit,
        window_seconds=window_seconds,
        lockout_seconds=lockout_seconds,
        state=_rate_limit_state(),
        storage_key_fn=rate_limit_storage_key,
    )


def rate_limit_clear(scope: str, key: str) -> None:
    security.rate_limit_clear(
        scope, key, state=_rate_limit_state(), storage_key_fn=rate_limit_storage_key
    )


def rate_limit_consume(
    scope: str, key: str, *, limit: int, window_seconds: int, lockout_seconds: int
) -> None:
    security.rate_limit_consume(
        scope,
        key,
        limit=limit,
        window_seconds=window_seconds,
        lockout_seconds=lockout_seconds,
        state=_rate_limit_state(),
        storage_key_fn=rate_limit_storage_key,
        check_fn=rate_limit_check,
    )


def admin_cors_origin_allowed(origin: str) -> bool:
    return security.admin_cors_origin_allowed(
        origin, allowed_origins=ADMIN_CORS_ALLOWED_ORIGINS
    )


def is_admin_request_path(path: str) -> bool:
    return security.is_admin_request_path(path)


def normalize_code_hashes(value: Any) -> list[str]:
    return licenses.normalize_code_hashes(
        value, max_bulk_code_hashes=MAX_BULK_CODE_HASHES
    )


__all__ = [
    "normalize_username",
    "normalize_account_role",
    "normalize_account_status",
    "role_rank",
    "password_hash",
    "verify_password",
    "admin_session_token_hash",
    "generate_admin_session_token",
    "normalize_code_expires",
    "require_confirmation",
    "extract_bearer_token",
    "extract_admin_session_cookie",
    "request_admin_token",
    "admin_session_cookie",
    "account_row_public",
    "get_account_by_username",
    "get_account_by_id",
    "list_account_rows",
    "account_summary_row",
    "normalize_invite_code",
    "generate_invite_code",
    "invite_row_public",
    "count_invites",
    "list_invite_rows",
    "get_invite_by_code",
    "_create_account_record_on_connection",
    "create_invite_record",
    "toggle_invite_record",
    "register_account_with_invite",
    "_audit_registered_account",
    "create_account_record",
    "update_account_record",
    "admin_context_from_row",
    "load_admin_context_from_session",
    "load_legacy_admin_context",
    "create_admin_session",
    "update_account_last_login",
    "revoke_admin_session",
    "count_accounts",
    "count_active_super_admins",
    "auth_status_snapshot",
    "_rate_limit_state",
    "rate_limit_storage_key",
    "rate_limit_check",
    "rate_limit_record_failure",
    "rate_limit_clear",
    "rate_limit_consume",
    "admin_cors_origin_allowed",
    "is_admin_request_path",
    "normalize_code_hashes",
]
