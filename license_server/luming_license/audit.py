from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from . import db
from .serialization import load_json_value
from .timeutils import utc_now


AUDIT_SECRET_KEYS = {
    "fullcode",
    "code",
    "accesstoken",
    "imageaccesstoken",
    "videoaccesstoken",
    "imagetoken",
    "videotoken",
    "gatewaytoken",
    "gatewayimagetoken",
    "gatewayvideotoken",
    "gatewayaccesstoken",
    "gatewayimageaccesstoken",
    "gatewayvideoaccesstoken",
    "apikey",
    "sessiontoken",
    "token",
    "invitecode",
    "rawinvitecode",
}

_INVITE_ANNOTATION_RE = re.compile(
    r"(\binvite\s*:\s*)[^\s,;|}\]]+", re.IGNORECASE
)
_RAW_INVITE_RE = re.compile(
    r"\bINV-(?:[A-Z0-9]{4}-){3}[A-Z0-9]{4}\b", re.IGNORECASE
)

ConnectFn = Callable[[], sqlite3.Connection]
UtcNowFn = Callable[[], str]
AuditJsonFn = Callable[[Any], str]
AuditPublicValueFn = Callable[..., Any]
JsonValueLoader = Callable[[Any, Any], Any]
CommitFn = Callable[[Any], None]


def _connection_factory(connect_fn: ConnectFn | None) -> ConnectFn:
    return connect_fn or db.connect


def audit_json(value: Any) -> str:
    return json.dumps({} if value is None else value, ensure_ascii=False, sort_keys=True)


def masked_code_label(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return f"\u2022\u2022\u2022\u2022-{text[-8:]}" if text else "[REDACTED]"


def _redact_invite_credentials(value: str) -> str:
    redacted = _INVITE_ANNOTATION_RE.sub(r"\1[REDACTED]", value)
    return _RAW_INVITE_RE.sub("[REDACTED]", redacted)


def audit_public_value(value: Any, *, key: str = "") -> Any:
    normalized_key = "".join(ch for ch in key.lower() if ch.isalnum())
    if normalized_key in AUDIT_SECRET_KEYS:
        return masked_code_label(value) if normalized_key in {"fullcode", "code"} else "[REDACTED]"
    if normalized_key == "codes" and isinstance(value, list):
        return [masked_code_label(item) for item in value]
    if isinstance(value, dict):
        return {str(k): audit_public_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [audit_public_value(item, key=key) for item in value]
    if isinstance(value, str):
        return _redact_invite_credentials(value)
    return value


def add_audit_log(
    *,
    action: str,
    target_type: str = "",
    target_id: str = "",
    before: Any = None,
    after: Any = None,
    actor: str = "",
    request_ip: str = "",
    backup_path: str = "",
    connect_fn: ConnectFn | None = None,
    utc_now_fn: UtcNowFn = utc_now,
    audit_json_fn: AuditJsonFn = audit_json,
    audit_public_value_fn: AuditPublicValueFn = audit_public_value,
    commit_fn: CommitFn | None = None,
) -> None:
    with _connection_factory(connect_fn)() as conn:
        conn.execute(
            """
            insert into audit_logs (
                actor, action, target_type, target_id, before_json, after_json,
                request_ip, backup_path, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _redact_invite_credentials(actor)[:128],
                action[:80],
                target_type[:80],
                _redact_invite_credentials(target_id)[:256],
                audit_json_fn(audit_public_value_fn(before)),
                audit_json_fn(audit_public_value_fn(after)),
                request_ip[:80],
                backup_path,
                utc_now_fn(),
            ),
        )
        if commit_fn:
            commit_fn(conn)
        else:
            conn.commit()


def masked_secret(value: Any) -> str:
    return "\u5df2\u914d\u7f6e" if str(value or "").strip() else ""


def get_audit_rows(
    limit: int = 100,
    *,
    connect_fn: ConnectFn | None = None,
    load_json_value_fn: JsonValueLoader = load_json_value,
    audit_public_value_fn: AuditPublicValueFn = audit_public_value,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    with _connection_factory(connect_fn)() as conn:
        rows = conn.execute(
            """
            select id, actor, action, target_type, target_id, before_json, after_json,
                   request_ip, backup_path, created_at
            from audit_logs
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "actor": row["actor"],
            "action": row["action"],
            "targetType": row["target_type"],
            "targetId": row["target_id"],
            "before": audit_public_value_fn(load_json_value_fn(row["before_json"], {})),
            "after": audit_public_value_fn(load_json_value_fn(row["after_json"], {})),
            "requestIp": row["request_ip"],
            "backupPath": row["backup_path"],
            "backupFile": os.path.basename(row["backup_path"]) if row["backup_path"] else "",
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
