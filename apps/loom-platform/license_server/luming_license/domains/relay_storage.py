from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from .. import db
from ..errors import ActivationError
from ..serialization import normalize_string


LOGGER = logging.getLogger("openclaw-license")


def ensure_state_columns(conn: sqlite3.Connection) -> None:
    for name, definition in (
        ("account_id", "text not null default ''"),
        ("commit_token_hash", "text not null default ''"),
        ("commit_authorized_at", "text not null default ''"),
        ("commit_expires_at_ms", "integer not null default 0"),
        ("commit_lease_id", "text not null default ''"),
        ("commit_client_id", "text not null default ''"),
        ("commit_state", "text not null default ''"),
        ("outcome_indeterminate", "integer not null default 0"),
    ):
        try:
            db.ensure_column(conn, "publish_relay_packets", name, definition)
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise


def packet_json(row: sqlite3.Row) -> dict[str, Any]:
    try:
        packet = json.loads(row["packet_json"] or "{}")
    except json.JSONDecodeError as error:
        raise ActivationError(
            "Relay packet is invalid",
            409,
            "RELAY_PACKET_INVALID",
        ) from error
    if not isinstance(packet, dict):
        raise ActivationError(
            "Relay packet is invalid",
            409,
            "RELAY_PACKET_INVALID",
        )
    return packet


def is_formal_publish_packet(packet: dict[str, Any]) -> bool:
    return (
        normalize_string(packet.get("schema")) == "openclaw.publish.packet.v1"
        and packet.get("draftOnly") is False
    )


def has_strict_commit_policy(packet: dict[str, Any]) -> bool:
    policy = packet.get("executionPolicy")
    return (
        isinstance(policy, dict)
        and policy.get("requireSignedEntitlementAtDequeue") is True
        and policy.get("requireSignedEntitlementBeforeCommit") is True
        and policy.get("denyCommitOnRevocation") is True
    )


def record_from_row(
    row: sqlite3.Row,
    include_packet: bool = False,
) -> dict[str, Any]:
    row_keys = set(row.keys())
    payload: dict[str, Any] = {
        "id": row["packet_id"],
        "accountId": row["account_id"] if "account_id" in row_keys else "",
        "channelId": row["channel_id"],
        "status": row["status"],
        "attempts": row["attempts"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "leasedBy": row["leased_by"],
        "leaseId": row["lease_id"],
        "leaseUntil": row["lease_until_ms"] or None,
        "nextAvailableAt": row["next_available_at_ms"] or None,
        "completedAt": row["completed_at"] or None,
        "lastError": row["last_error"] or "",
        "commitState": row["commit_state"] if "commit_state" in row_keys else "",
        "commitAuthorizedAt": (
            row["commit_authorized_at"] or ""
            if "commit_authorized_at" in row_keys
            else ""
        ),
        "commitExpiresAt": (
            row["commit_expires_at_ms"] or None
            if "commit_expires_at_ms" in row_keys
            else None
        ),
        "outcomeIndeterminate": (
            bool(row["outcome_indeterminate"])
            if "outcome_indeterminate" in row_keys
            else False
        ),
    }
    if include_packet:
        try:
            payload["packet"] = json.loads(row["packet_json"] or "{}")
        except json.JSONDecodeError as error:
            LOGGER.warning(
                "Invalid publish relay packet JSON for %s: %s",
                row["packet_id"],
                error,
            )
            payload["packet"] = {}
    if row["result_json"]:
        try:
            payload["result"] = json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError as error:
            LOGGER.warning(
                "Invalid publish relay result JSON for %s: %s",
                row["packet_id"],
                error,
            )
            payload["result"] = row["result_json"]
    return payload


def fetch(
    conn: sqlite3.Connection,
    packet_id: str,
    *,
    account_id: str = "",
) -> sqlite3.Row | None:
    if account_id:
        return conn.execute(
            """
            select * from publish_relay_packets
            where packet_id = ? and account_id = ?
            """,
            (packet_id, account_id),
        ).fetchone()
    return conn.execute(
        "select * from publish_relay_packets where packet_id = ?",
        (packet_id,),
    ).fetchone()
