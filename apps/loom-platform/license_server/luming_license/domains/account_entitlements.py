from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

from .. import audit
from ..config import Settings
from ..errors import ActivationError
from ..timeutils import utc_now


ConnectFn = Callable[[], sqlite3.Connection]
CodeHashFn = Callable[[str], str]
ACTIVATED_PHONE_DEVICE_LIMIT = 1000


def account_redeem_service_configured(
    *, settings: Settings | None = None
) -> bool:
    active_settings = settings or Settings.from_env()
    return bool(active_settings.account_redeem_service_token)


def account_redeem_request_token(headers: Any) -> str:
    authorization = str(headers.get("Authorization", "") or "").strip()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()


def account_redeem_service_token_valid(
    headers: Any,
    *,
    settings: Settings | None = None,
) -> bool:
    active_settings = settings or Settings.from_env()
    expected = active_settings.account_redeem_service_token
    if not expected:
        return False
    provided = account_redeem_request_token(headers)
    return bool(provided) and secrets.compare_digest(provided, expected)


def normalize_account_id(value: Any) -> str:
    if isinstance(value, bool):
        raise ActivationError(
            "Missing or invalid accountId",
            400,
            "ACCOUNT_REDEEM_INVALID_REQUEST",
        )
    account_id = str(value if value is not None else "").strip()
    if (
        not account_id
        or len(account_id) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in account_id)
    ):
        raise ActivationError(
            "Missing or invalid accountId",
            400,
            "ACCOUNT_REDEEM_INVALID_REQUEST",
        )
    return account_id


def _validate_code_status(row: sqlite3.Row) -> None:
    if bool(row["disabled"]):
        raise ActivationError("Authorization code is disabled", 403, "LICENSE_DISABLED")
    try:
        expires = date.fromisoformat(str(row["expires"]))
    except ValueError as error:
        raise ActivationError(
            "Authorization code expiry is invalid",
            500,
            "LICENSE_DATA_INVALID",
        ) from error
    if expires < date.today():
        raise ActivationError("Authorization code is expired", 403, "LICENSE_EXPIRED")


def _parse_features(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError as error:
        raise ActivationError(
            "Authorization code features are invalid",
            500,
            "LICENSE_DATA_INVALID",
        ) from error
    if not isinstance(parsed, list):
        raise ActivationError(
            "Authorization code features are invalid",
            500,
            "LICENSE_DATA_INVALID",
        )
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in parsed
            if isinstance(item, str) and str(item).strip()
        )
    )


def _concurrent_tasks(value: Any) -> int:
    try:
        quotas = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        quotas = {}
    if not isinstance(quotas, dict):
        quotas = {}
    raw = quotas.get("concurrentTasks", quotas.get("concurrent_tasks", 1))
    if isinstance(raw, bool):
        return 1
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, min(parsed, 100))


def _entitlement_from_code(row: sqlite3.Row) -> dict[str, Any]:
    devices = ACTIVATED_PHONE_DEVICE_LIMIT
    concurrent_tasks = min(_concurrent_tasks(row["quotas_json"]), devices)
    return {
        "source": "authorization_code",
        "plan": str(row["plan"] or row["edition"] or "monthly").strip(),
        "features": _parse_features(row["features_json"]),
        "limits": {
            "devices": devices,
            "concurrentTasks": concurrent_tasks,
            "unlimitedDevices": True,
        },
        "expiresAt": str(row["expires"]),
        "codeLabel": str(row["code_label"] or ""),
    }


def _entitlement_from_redemption(row: sqlite3.Row) -> dict[str, Any]:
    try:
        features = json.loads(str(row["features_json"] or "[]"))
    except json.JSONDecodeError as error:
        raise ActivationError(
            "Stored account entitlement is invalid",
            500,
            "LICENSE_DATA_INVALID",
        ) from error
    if not isinstance(features, list):
        raise ActivationError(
            "Stored account entitlement is invalid",
            500,
            "LICENSE_DATA_INVALID",
        )
    return {
        "source": "authorization_code",
        "plan": str(row["plan"] or ""),
        "features": features,
        "limits": {
            "devices": ACTIVATED_PHONE_DEVICE_LIMIT,
            "concurrentTasks": int(row["concurrent_tasks"]),
            "unlimitedDevices": True,
        },
        "expiresAt": str(row["expires_at"] or ""),
        "codeLabel": str(row["code_label"] or ""),
    }


def _write_redemption_audit(
    connection: sqlite3.Connection,
    *,
    code_hash: str,
    account_id: str,
    entitlement: dict[str, Any],
    request_ip: str,
    redeemed_at: str,
    action: str = "account_entitlement.redeem",
) -> None:
    after = audit.audit_public_value(
        {
            "accountId": account_id,
            "codeHash": code_hash,
            "entitlement": entitlement,
        }
    )
    connection.execute(
        """
        insert into audit_logs (
            actor, action, target_type, target_id, before_json, after_json,
            request_ip, backup_path, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, '', ?)
        """,
        (
            "service:account-entitlements",
            action,
            "account_entitlement",
            code_hash,
            audit.audit_json({}),
            audit.audit_json(after),
            str(request_ip or "")[:80],
            redeemed_at,
        ),
    )


def _redeem_code_row(
    connection: sqlite3.Connection,
    *,
    code_row: sqlite3.Row,
    code_hash: str,
    account_id: str,
    request_ip: str,
    utc_now_fn: Callable[[], str],
    audit_action: str = "account_entitlement.redeem",
) -> dict[str, Any]:
    existing = connection.execute(
        """
        select code_hash, account_id, plan, features_json, devices,
               concurrent_tasks, expires_at, code_label, redeemed_at
        from account_entitlement_redemptions where code_hash = ?
        """,
        (code_hash,),
    ).fetchone()
    if existing is not None:
        if str(existing["account_id"]) != account_id:
            raise ActivationError(
                "Authorization code is already bound to another account",
                409,
                "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED",
            )
        entitlement = _entitlement_from_code(code_row)
        connection.execute(
            """
            update account_entitlement_redemptions
            set plan = ?, features_json = ?, devices = ?,
                concurrent_tasks = ?, expires_at = ?, code_label = ?
            where code_hash = ?
            """,
            (
                entitlement["plan"],
                json.dumps(entitlement["features"], ensure_ascii=False),
                entitlement["limits"]["devices"],
                entitlement["limits"]["concurrentTasks"],
                entitlement["expiresAt"],
                entitlement["codeLabel"],
                code_hash,
            ),
        )
        connection.commit()
        return entitlement

    entitlement = _entitlement_from_code(code_row)
    redeemed_at = utc_now_fn()
    connection.execute(
        """
        insert into account_entitlement_redemptions (
            code_hash, account_id, plan, features_json, devices,
            concurrent_tasks, expires_at, code_label, redeemed_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code_hash,
            account_id,
            entitlement["plan"],
            json.dumps(entitlement["features"], ensure_ascii=False),
            entitlement["limits"]["devices"],
            entitlement["limits"]["concurrentTasks"],
            entitlement["expiresAt"],
            entitlement["codeLabel"],
            redeemed_at,
        ),
    )
    _write_redemption_audit(
        connection,
        code_hash=code_hash,
        account_id=account_id,
        entitlement=entitlement,
        request_ip=request_ip,
        redeemed_at=redeemed_at,
        action=audit_action,
    )
    connection.commit()
    return entitlement


def redeem_account_entitlement(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn,
    code_hash_fn: CodeHashFn,
    request_ip: str = "",
    utc_now_fn: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ActivationError(
            "Invalid JSON body",
            400,
            "ACCOUNT_REDEEM_INVALID_REQUEST",
        )
    raw_code = body.get("code")
    if not isinstance(raw_code, str) or not raw_code.strip() or len(raw_code.strip()) > 256:
        raise ActivationError(
            "Missing or invalid authorization code",
            400,
            "ACCOUNT_REDEEM_INVALID_REQUEST",
        )
    account_id = normalize_account_id(body.get("accountId"))
    code_hash = code_hash_fn(raw_code.strip().upper())

    with connect_fn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        code_row = connection.execute(
            """
            select code_hash, code_label, edition, features_json, expires,
                   max_activations, disabled, plan, quotas_json
            from codes where code_hash = ?
            """,
            (code_hash,),
        ).fetchone()
        if code_row is None:
            raise ActivationError(
                "Authorization code does not exist",
                404,
                "LICENSE_INVALID",
            )
        _validate_code_status(code_row)

        return _redeem_code_row(
            connection,
            code_row=code_row,
            code_hash=code_hash,
            account_id=account_id,
            request_ip=request_ip,
            utc_now_fn=utc_now_fn,
        )


def migrate_legacy_account_entitlement(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn,
    request_ip: str = "",
    settings: Settings | None = None,
    utc_now_fn: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    del body, connect_fn, request_ip, settings, utc_now_fn
    raise ActivationError(
        "Legacy migration is disabled; bind the original authorization code",
        410,
        "LEGACY_MIGRATION_DISABLED",
    )


def current_account_entitlement(
    account_id: Any,
    *,
    connect_fn: ConnectFn,
) -> dict[str, Any]:
    normalized_account_id = normalize_account_id(account_id)
    with connect_fn() as connection:
        rows = connection.execute(
            """
            select r.rowid as redemption_rowid, r.code_hash, r.account_id,
                   r.redeemed_at,
                   c.code_hash as current_code_hash, c.code_label, c.edition,
                   c.features_json, c.expires, c.max_activations, c.disabled,
                   c.plan, c.quotas_json
            from account_entitlement_redemptions r
            left join codes c on c.code_hash = r.code_hash
            where r.account_id = ?
            order by r.redeemed_at desc, r.rowid desc
            """,
            (normalized_account_id,),
        ).fetchall()
    if not rows:
        raise ActivationError(
            "Account entitlement was not found",
            404,
            "ACCOUNT_ENTITLEMENT_NOT_FOUND",
        )

    candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    failures: list[ActivationError] = []
    for row in rows:
        if row["current_code_hash"] is None:
            failures.append(
                ActivationError(
                    "Account entitlement has been revoked",
                    410,
                    "ACCOUNT_ENTITLEMENT_REVOKED",
                )
            )
            continue
        try:
            _validate_code_status(row)
            entitlement = _entitlement_from_code(row)
        except ActivationError as error:
            failures.append(error)
            continue
        candidates.append(
            (
                (
                    len(entitlement["features"]),
                    int(entitlement["limits"]["concurrentTasks"]),
                    date.fromisoformat(entitlement["expiresAt"]).toordinal(),
                    str(row["redeemed_at"] or ""),
                    int(row["redemption_rowid"]),
                ),
                entitlement,
            )
        )

    if candidates:
        return max(candidates, key=lambda candidate: candidate[0])[1]
    raise failures[0]


__all__ = [
    "account_redeem_request_token",
    "account_redeem_service_configured",
    "account_redeem_service_token_valid",
    "current_account_entitlement",
    "migrate_legacy_account_entitlement",
    "normalize_account_id",
    "redeem_account_entitlement",
]
