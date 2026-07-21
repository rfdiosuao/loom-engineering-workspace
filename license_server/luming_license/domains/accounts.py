from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable
from typing import Any

from .. import db
from ..errors import ActivationError
from ..security import password_hash
from ..timeutils import utc_now


ACCOUNT_ROLE_MERCHANT = "merchant"
ACCOUNT_ROLE_SUPER_ADMIN = "super_admin"
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_DISABLED = "disabled"
INVITE_CODE_STATUS_ACTIVE = "active"
INVITE_CODE_STATUS_DISABLED = "disabled"
INVITE_CODE_STATUS_USED = "used"
INVITE_CODE_STATUS_EXPIRED = "expired"
INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

ConnectFn = Callable[[], sqlite3.Connection]
AuditLogFn = Callable[..., None]
ConnectionCommitFn = Callable[[sqlite3.Connection], None]
PasswordHashFn = Callable[[str], str]
InviteCodeGenerator = Callable[[], str]
AccountRowPublicFn = Callable[[sqlite3.Row | None], dict[str, Any] | None]
AccountCreatorFn = Callable[..., tuple[dict[str, Any], str]]
AccountSummaryFn = Callable[[int], dict[str, Any] | None]
NormalizerFn = Callable[[Any], str]
InviteRowPublicFn = Callable[[sqlite3.Row | None], dict[str, Any] | None]
InviteLookupFn = Callable[[str], sqlite3.Row | None]


def _connection_factory(connect_fn: ConnectFn | None) -> ConnectFn:
    return connect_fn or db.connect


def normalize_username(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_account_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"super", "admin", "super_admin", "superadmin"}:
        return ACCOUNT_ROLE_SUPER_ADMIN
    return ACCOUNT_ROLE_MERCHANT


def normalize_account_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"disabled", "inactive", "false", "0", "off"}:
        return ACCOUNT_STATUS_DISABLED
    return ACCOUNT_STATUS_ACTIVE


def role_rank(role: str, *, normalize_account_role_fn: NormalizerFn = normalize_account_role) -> int:
    return {ACCOUNT_ROLE_MERCHANT: 1, ACCOUNT_ROLE_SUPER_ADMIN: 2}.get(normalize_account_role_fn(role), 0)


def account_row_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    keys = set(row.keys())
    return {
        "accountId": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "note": row["note"] if "note" in keys else "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastLoginAt": row["last_login_at"] if "last_login_at" in keys else "",
        "lastLoginIp": row["last_login_ip"] if "last_login_ip" in keys else "",
        "codeCount": int(row["code_count"]) if "code_count" in keys and row["code_count"] is not None else 0,
        "activeCodeCount": int(row["active_code_count"]) if "active_code_count" in keys and row["active_code_count"] is not None else 0,
        "disabledCodeCount": int(row["disabled_code_count"]) if "disabled_code_count" in keys and row["disabled_code_count"] is not None else 0,
        "memberCodeCount": int(row["member_code_count"]) if "member_code_count" in keys and row["member_code_count"] is not None else 0,
        "usedCodeCount": int(row["used_code_count"]) if "used_code_count" in keys and row["used_code_count"] is not None else 0,
        "activationCount": int(row["activation_count"]) if "activation_count" in keys and row["activation_count"] is not None else 0,
        "activationLimitCount": int(row["activation_limit_count"]) if "activation_limit_count" in keys and row["activation_limit_count"] is not None else 0,
        "lastCodeCreatedAt": row["last_code_created_at"] if "last_code_created_at" in keys else "",
        "lastActivationAt": row["last_activation_at"] if "last_activation_at" in keys else "",
    }


def get_account_by_username(
    username: str,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_username_fn: NormalizerFn = normalize_username,
) -> sqlite3.Row | None:
    normalized = normalize_username_fn(username)
    if not normalized:
        return None
    with _connection_factory(connect_fn)() as conn:
        return conn.execute("select * from accounts where username = ?", (normalized,)).fetchone()


def get_account_by_id(account_id: int, *, connect_fn: ConnectFn | None = None) -> sqlite3.Row | None:
    if int(account_id or 0) <= 0:
        return None
    with _connection_factory(connect_fn)() as conn:
        return conn.execute("select * from accounts where id = ?", (int(account_id),)).fetchone()


def list_account_rows(
    *,
    connect_fn: ConnectFn | None = None,
    account_row_public_fn: AccountRowPublicFn = account_row_public,
) -> list[dict[str, Any]]:
    with _connection_factory(connect_fn)() as conn:
        rows = conn.execute(
            """
            select a.*,
                   count(c.code_hash) as code_count,
                   coalesce(sum(case when c.disabled = 0 then 1 else 0 end), 0) as active_code_count,
                   coalesce(sum(case when c.disabled != 0 then 1 else 0 end), 0) as disabled_code_count,
                   coalesce(sum(case when c.member_mode = 1 then 1 else 0 end), 0) as member_code_count,
                   coalesce(sum(case when coalesce(c.activations, 0) > 0 then 1 else 0 end), 0) as used_code_count,
                   coalesce(sum(coalesce(c.activations, 0)), 0) as activation_count,
                   coalesce(sum(coalesce(c.max_activations, 0)), 0) as activation_limit_count,
                   coalesce(max(c.created_at), '') as last_code_created_at,
                   coalesce(max(c.last_activated_at), '') as last_activation_at
            from accounts a
            left join (
                select c.code_hash, c.owner_account_id, c.disabled, c.member_mode,
                       c.max_activations, c.created_at,
                       count(a.id) as activations,
                       max(a.activated_at) as last_activated_at
                from codes c
                left join activations a on a.code_hash = c.code_hash
                group by c.code_hash
            ) c on c.owner_account_id = a.id
            group by a.id
            order by case a.role when ? then 0 else 1 end, a.created_at desc
            """,
            (ACCOUNT_ROLE_SUPER_ADMIN,),
        ).fetchall()
    return [account_row_public_fn(row) for row in rows if account_row_public_fn(row)]


def account_summary_row(account_id: int, *, connect_fn: ConnectFn | None = None) -> dict[str, Any] | None:
    row = get_account_by_id(account_id, connect_fn=connect_fn)
    return account_row_public(row) if row else None


def normalize_invite_code(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def generate_invite_code() -> str:
    return "INV-" + "-".join("".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(4)) for _ in range(4))


def invite_row_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    keys = set(row.keys())
    max_uses = max(1, int(row["max_uses"] or 1))
    used_count = max(0, int(row["used_count"] or 0))
    status = str(row["status"] or INVITE_CODE_STATUS_ACTIVE)
    expires_at = str(row["expires_at"] or "")
    now = utc_now()
    if status == INVITE_CODE_STATUS_ACTIVE:
        if expires_at and expires_at < now:
            status = INVITE_CODE_STATUS_EXPIRED
        elif used_count >= max_uses:
            status = INVITE_CODE_STATUS_USED
    return {
        "inviteId": row["id"], "inviteCode": row["invite_code"], "role": row["role"], "status": status,
        "note": row["note"] if "note" in keys else "", "maxUses": max_uses, "usedCount": used_count,
        "remainingUses": max(0, max_uses - used_count), "createdBy": int(row["created_by"] or 0),
        "createdByUsername": row["created_by_username"] if "created_by_username" in keys else "",
        "createdByDisplayName": row["created_by_display_name"] if "created_by_display_name" in keys else "",
        "createdAt": row["created_at"], "updatedAt": row["updated_at"], "expiresAt": expires_at,
        "lastUsedAt": row["last_used_at"] if "last_used_at" in keys else "",
        "lastUsedIp": row["last_used_ip"] if "last_used_ip" in keys else "",
        "lastUsedUsername": row["last_used_username"] if "last_used_username" in keys else "",
        "lastUsedAccountId": int(row["last_used_account_id"] or 0) if "last_used_account_id" in keys and row["last_used_account_id"] is not None else 0,
    }


def count_invites(*, active_only: bool = False, connect_fn: ConnectFn | None = None) -> int:
    with _connection_factory(connect_fn)() as conn:
        if active_only:
            row = conn.execute(
                "select count(*) from invite_codes where status = ? and used_count < max_uses and (expires_at = '' or expires_at > ?)",
                (INVITE_CODE_STATUS_ACTIVE, utc_now()),
            ).fetchone()
        else:
            row = conn.execute("select count(*) from invite_codes").fetchone()
    return int(row[0] or 0)


def list_invite_rows(
    *,
    connect_fn: ConnectFn | None = None,
    invite_row_public_fn: InviteRowPublicFn = invite_row_public,
) -> list[dict[str, Any]]:
    with _connection_factory(connect_fn)() as conn:
        rows = conn.execute(
            """
            select i.*, coalesce(acc.username, '') as created_by_username,
                   coalesce(acc.display_name, '') as created_by_display_name
            from invite_codes i left join accounts acc on acc.id = i.created_by
            order by i.created_at desc
            """
        ).fetchall()
    invites: list[dict[str, Any]] = []
    for row in rows:
        public = invite_row_public_fn(row)
        if public:
            invites.append(public)
    return invites


def get_invite_by_code(
    invite_code: str,
    *,
    connect_fn: ConnectFn | None = None,
    normalize_invite_code_fn: NormalizerFn = normalize_invite_code,
) -> sqlite3.Row | None:
    normalized = normalize_invite_code_fn(invite_code)
    if not normalized:
        return None
    with _connection_factory(connect_fn)() as conn:
        return conn.execute("select * from invite_codes where invite_code = ?", (normalized,)).fetchone()


def _create_account_record_on_connection(
    conn: sqlite3.Connection,
    *, username: str, display_name: str = "", password: str = "", role: str = ACCOUNT_ROLE_MERCHANT,
    status: str = ACCOUNT_STATUS_ACTIVE, note: str = "", created_by: int = 0, password_hash_fn: PasswordHashFn = password_hash,
    account_row_public_fn: AccountRowPublicFn = account_row_public,
    normalize_username_fn: NormalizerFn = normalize_username,
    normalize_account_role_fn: NormalizerFn = normalize_account_role,
    normalize_account_status_fn: NormalizerFn = normalize_account_status,
) -> tuple[dict[str, Any], str]:
    normalized_username = normalize_username_fn(username)
    if not normalized_username:
        raise ActivationError("\u7528\u6237\u540d\u4e0d\u80fd\u4e3a\u7a7a")
    normalized_role = normalize_account_role_fn(role)
    normalized_status = normalize_account_status_fn(status)
    visible_name = str(display_name or "").strip() or normalized_username
    provided_password = str(password or "").strip()
    if provided_password and len(provided_password) < 8:
        raise ActivationError("\u5bc6\u7801\u81f3\u5c11\u9700\u8981 8 \u4e2a\u5b57\u7b26")
    clear_password = provided_password or secrets.token_urlsafe(10)
    hashed_password = password_hash_fn(clear_password)
    now = utc_now()
    if conn.execute("select id from accounts where username = ?", (normalized_username,)).fetchone():
        raise ActivationError("\u7528\u6237\u540d\u5df2\u5b58\u5728", 409)
    conn.execute(
        """insert into accounts (username, display_name, password_hash, role, status, note,
           created_by, created_at, updated_at, last_login_at, last_login_ip)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')""",
        (normalized_username, visible_name, hashed_password, normalized_role, normalized_status, note[:500], int(created_by or 0), now, now),
    )
    row = conn.execute("select * from accounts where username = ?", (normalized_username,)).fetchone()
    if not row:
        raise ActivationError("\u521b\u5efa\u8d26\u53f7\u5931\u8d25", 500)
    return account_row_public_fn(row) or {}, "" if provided_password else clear_password


def create_invite_record(
    *,
    note: str = "",
    max_uses: int = 1,
    expires_at: str = "",
    created_by: int = 0,
    connect_fn: ConnectFn | None = None,
    invite_code_generator: InviteCodeGenerator = generate_invite_code,
    invite_row_public_fn: InviteRowPublicFn = invite_row_public,
) -> tuple[dict[str, Any], str]:
    normalized_note = str(note or "").strip()
    normalized_expires_at = str(expires_at or "").strip()
    normalized_max_uses = max(1, min(int(max_uses or 1), 100))
    if normalized_expires_at and normalized_expires_at < utc_now():
        raise ActivationError("\u5230\u671f\u65f6\u95f4\u4e0d\u80fd\u65e9\u4e8e\u5f53\u524d\u65f6\u95f4")
    now = utc_now()
    with _connection_factory(connect_fn)() as conn:
        for _ in range(8):
            invite_code = invite_code_generator()
            try:
                conn.execute(
                    """insert into invite_codes (invite_code, role, status, max_uses, used_count, note,
                       created_by, created_at, updated_at, expires_at, last_used_at, last_used_ip,
                       last_used_username, last_used_account_id)
                       values (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, '', '', '', 0)""",
                    (invite_code, ACCOUNT_ROLE_MERCHANT, INVITE_CODE_STATUS_ACTIVE, normalized_max_uses,
                     normalized_note[:500], int(created_by or 0), now, now, normalized_expires_at),
                )
                conn.commit()
                row = conn.execute(
                    """select i.*, coalesce(acc.username, '') as created_by_username,
                       coalesce(acc.display_name, '') as created_by_display_name from invite_codes i
                       left join accounts acc on acc.id = i.created_by where i.invite_code = ?""",
                    (invite_code,),
                ).fetchone()
                return invite_row_public_fn(row) or {}, invite_code
            except sqlite3.IntegrityError:
                conn.rollback()
    raise ActivationError("\u751f\u6210\u9080\u8bf7\u7801\u5931\u8d25", 500)


def toggle_invite_record(
    invite_id: int,
    *,
    connect_fn: ConnectFn | None = None,
    invite_row_public_fn: InviteRowPublicFn = invite_row_public,
    get_invite_by_code_fn: InviteLookupFn | None = None,
) -> dict[str, Any] | None:
    factory = _connection_factory(connect_fn)
    with factory() as conn:
        existing = conn.execute("select * from invite_codes where id = ?", (int(invite_id),)).fetchone()
        if not existing:
            return None
        now = utc_now()
        current_status = str(existing["status"] or INVITE_CODE_STATUS_ACTIVE)
        if current_status == INVITE_CODE_STATUS_USED:
            raise ActivationError("\u9080\u8bf7\u7801\u5df2\u7528\u5b8c\uff0c\u4e0d\u80fd\u518d\u6b21\u542f\u7528")
        if current_status == INVITE_CODE_STATUS_EXPIRED:
            raise ActivationError("\u9080\u8bf7\u7801\u5df2\u8fc7\u671f\uff0c\u4e0d\u80fd\u76f4\u63a5\u542f\u7528")
        next_status = INVITE_CODE_STATUS_DISABLED if current_status == INVITE_CODE_STATUS_ACTIVE else INVITE_CODE_STATUS_ACTIVE
        conn.execute("update invite_codes set status = ?, updated_at = ? where id = ?", (next_status, now, int(invite_id)))
        conn.commit()
    if get_invite_by_code_fn:
        row = get_invite_by_code_fn(str(existing["invite_code"]))
    else:
        row = get_invite_by_code(str(existing["invite_code"]), connect_fn=factory)
    return invite_row_public_fn(row)


def register_account_with_invite(
    *, invite_code: str, username: str, display_name: str = "", password: str = "", request_ip: str = "", user_agent: str = "",
    connect_fn: ConnectFn | None = None, audit_log: AuditLogFn | None = None, password_hash_fn: PasswordHashFn = password_hash,
    create_account_on_connection_fn: AccountCreatorFn | None = None,
    normalize_invite_code_fn: NormalizerFn = normalize_invite_code,
    normalize_username_fn: NormalizerFn = normalize_username,
    normalization_commit_fn: ConnectionCommitFn | None = None,
) -> tuple[dict[str, Any], str, str]:
    normalized_invite_code = normalize_invite_code_fn(invite_code)
    if not normalized_invite_code:
        raise ActivationError("\u8bf7\u8f93\u5165\u9080\u8bf7\u7801")
    normalized_username = normalize_username_fn(username)
    if not normalized_username:
        raise ActivationError("\u7528\u6237\u540d\u4e0d\u80fd\u4e3a\u7a7a")
    normalized_display_name = str(display_name or "").strip() or normalized_username
    provided_password = str(password or "").strip()
    if len(provided_password) < 8:
        raise ActivationError("\u5bc6\u7801\u81f3\u5c11\u9700\u8981 8 \u4e2a\u5b57\u7b26")
    now = utc_now()
    with _connection_factory(connect_fn)() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite_row = conn.execute("select * from invite_codes where invite_code = ?", (normalized_invite_code,)).fetchone()
        if not invite_row:
            raise ActivationError("\u9080\u8bf7\u7801\u4e0d\u5b58\u5728", 404)
        if str(invite_row["status"] or INVITE_CODE_STATUS_ACTIVE) == INVITE_CODE_STATUS_DISABLED:
            raise ActivationError("\u9080\u8bf7\u7801\u5df2\u505c\u7528", 403)
        if str(invite_row["expires_at"] or "") and str(invite_row["expires_at"]) < now:
            conn.execute("update invite_codes set status = ?, updated_at = ? where id = ?", (INVITE_CODE_STATUS_EXPIRED, now, int(invite_row["id"])))
            (normalization_commit_fn or (lambda connection: connection.commit()))(conn)
            raise ActivationError("\u9080\u8bf7\u7801\u5df2\u8fc7\u671f", 403)
        max_uses = max(1, int(invite_row["max_uses"] or 1))
        used_count = max(0, int(invite_row["used_count"] or 0))
        if used_count >= max_uses:
            conn.execute("update invite_codes set status = ?, updated_at = ? where id = ?", (INVITE_CODE_STATUS_USED, now, int(invite_row["id"])))
            (normalization_commit_fn or (lambda connection: connection.commit()))(conn)
            raise ActivationError("\u9080\u8bf7\u7801\u5df2\u4f7f\u7528", 403)
        creator = create_account_on_connection_fn or _create_account_record_on_connection
        creation_kwargs = {
            "username": normalized_username,
            "display_name": normalized_display_name,
            "password": provided_password,
            "role": ACCOUNT_ROLE_MERCHANT,
            "status": ACCOUNT_STATUS_ACTIVE,
            "note": f"invite:{normalized_invite_code}",
            "created_by": int(invite_row["created_by"] or 0),
        }
        if create_account_on_connection_fn is None:
            creation_kwargs["password_hash_fn"] = password_hash_fn
        account, _ = creator(conn, **creation_kwargs)
        account_id = int(account.get("accountId") or 0)
        if account_id <= 0:
            raise ActivationError("\u521b\u5efa\u8d26\u53f7\u5931\u8d25", 500)
        next_used_count = used_count + 1
        next_status = INVITE_CODE_STATUS_USED if next_used_count >= max_uses else INVITE_CODE_STATUS_ACTIVE
        conn.execute(
            """update invite_codes set used_count = ?, status = ?, last_used_at = ?, last_used_ip = ?,
               last_used_username = ?, last_used_account_id = ?, updated_at = ? where id = ?""",
            (next_used_count, next_status, now, request_ip[:80], normalized_username[:80], account_id, now, int(invite_row["id"])),
        )
        conn.commit()
    if audit_log:
        audit_log(action="accounts.register", target_type="account", target_id=normalized_username, before={}, after=account,
                  actor="invite:[REDACTED]", request_ip=request_ip, backup_path="")
    return account, normalized_invite_code, ""


def create_account_record(
    *, username: str, display_name: str = "", password: str = "", role: str = ACCOUNT_ROLE_MERCHANT,
    status: str = ACCOUNT_STATUS_ACTIVE, note: str = "", created_by: int = 0, connect_fn: ConnectFn | None = None,
    password_hash_fn: PasswordHashFn = password_hash,
    create_account_on_connection_fn: AccountCreatorFn | None = None,
) -> tuple[dict[str, Any], str]:
    with _connection_factory(connect_fn)() as conn:
        creator = create_account_on_connection_fn or _create_account_record_on_connection
        creation_kwargs = {
            "username": username,
            "display_name": display_name,
            "password": password,
            "role": role,
            "status": status,
            "note": note,
            "created_by": created_by,
        }
        if create_account_on_connection_fn is None:
            creation_kwargs["password_hash_fn"] = password_hash_fn
        account, temp_password = creator(conn, **creation_kwargs)
        conn.commit()
    return account, temp_password


def update_account_record(
    *, account_id: int, display_name: str | None = None, role: str | None = None, status: str | None = None,
    password: str | None = None, note: str | None = None, connect_fn: ConnectFn | None = None,
    password_hash_fn: PasswordHashFn = password_hash,
    account_summary_row_fn: AccountSummaryFn | None = None,
    normalize_account_role_fn: NormalizerFn = normalize_account_role,
    normalize_account_status_fn: NormalizerFn = normalize_account_status,
) -> dict[str, Any] | None:
    factory = _connection_factory(connect_fn)
    with factory() as conn:
        existing = conn.execute("select * from accounts where id = ?", (int(account_id),)).fetchone()
        if not existing:
            return None
        new_display_name = str(display_name).strip() if display_name is not None else str(existing["display_name"] or "")
        new_role = normalize_account_role_fn(role) if role is not None else str(existing["role"] or ACCOUNT_ROLE_MERCHANT)
        new_status = normalize_account_status_fn(status) if status is not None else str(existing["status"] or ACCOUNT_STATUS_ACTIVE)
        new_note = str(note).strip() if note is not None else str(existing["note"] or "")
        new_password_hash = str(existing["password_hash"] or "")
        if password is not None and str(password).strip():
            clear_password = str(password).strip()
            if len(clear_password) < 8:
                raise ActivationError("\u5bc6\u7801\u81f3\u5c11\u9700\u8981 8 \u4e2a\u5b57\u7b26")
            new_password_hash = password_hash_fn(clear_password)
        conn.execute(
            """update accounts set display_name = ?, password_hash = ?, role = ?, status = ?, note = ?, updated_at = ?
               where id = ?""",
            (new_display_name or str(existing["username"] or ""), new_password_hash, new_role, new_status, new_note[:500], utc_now(), int(account_id)),
        )
        conn.commit()
    if account_summary_row_fn:
        return account_summary_row_fn(int(account_id))
    return account_summary_row(int(account_id), connect_fn=factory)


def count_accounts(*, connect_fn: ConnectFn | None = None) -> int:
    with _connection_factory(connect_fn)() as conn:
        return int(conn.execute("select count(*) from accounts").fetchone()[0] or 0)


def count_active_super_admins(*, connect_fn: ConnectFn | None = None) -> int:
    with _connection_factory(connect_fn)() as conn:
        return int(conn.execute("select count(*) from accounts where role = ? and status = ?", (ACCOUNT_ROLE_SUPER_ADMIN, ACCOUNT_STATUS_ACTIVE)).fetchone()[0] or 0)
