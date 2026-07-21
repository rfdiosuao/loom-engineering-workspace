from __future__ import annotations

import inspect
import json
import logging
import secrets
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .. import db
from ..config import Settings
from ..errors import ActivationError
from ..serialization import clamp_int, normalize_string
from ..timeutils import now_ms, utc_now


LOGGER = logging.getLogger("openclaw-license")
PUBLISH_RELAY_BACKOFF_MS = 2_000
PUBLISH_RELAY_MAX_BACKOFF_MS = 5 * 60_000
PUBLISH_RELAY_CLAIM_BUSY_TIMEOUT_MS = 100
PUBLISH_RELAY_CLAIM_CONNECT_TIMEOUT_SECONDS = 0.1
PUBLISH_RELAY_CLAIM_MAX_ATTEMPTS = 3
PUBLISH_RELAY_CLAIM_RETRY_DELAY_MS = 50

ConnectFn = Callable[[], sqlite3.Connection]
ClaimFn = Callable[[str, str, int], dict[str, Any] | None]
PacketIdFn = Callable[[], str]
LeaseIdFn = Callable[[], str]
BackoffFn = Callable[[int], int]


def _settings(settings: Settings | None) -> Settings:
    return settings or Settings.from_env()


def _connect(
    settings: Settings | None,
    defaults: dict[str, Any] | None,
    *,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    return db.connect(settings=_settings(settings), defaults=defaults, timeout=timeout)


def connect_with_optional_timeout(
    connect_fn: Callable[..., sqlite3.Connection],
    *,
    timeout: float,
) -> sqlite3.Connection:
    try:
        signature = inspect.signature(connect_fn)
    except (TypeError, ValueError):
        return connect_fn(timeout=timeout)
    try:
        signature.bind_partial(timeout=timeout)
    except TypeError:
        return connect_fn()
    return connect_fn(timeout=timeout)


def publish_relay_backoff_ms(attempts: int) -> int:
    factor = max(1, 2 ** max(0, attempts - 1))
    return min(PUBLISH_RELAY_MAX_BACKOFF_MS, PUBLISH_RELAY_BACKOFF_MS * factor)


def publish_relay_packet_id() -> str:
    return f"relay_{secrets.token_hex(6)}"


def publish_relay_lease_id() -> str:
    return f"lease_{secrets.token_hex(6)}"


def publish_relay_auth_required() -> bool:
    return True


def publish_relay_configured(*, settings: Settings | None = None) -> bool:
    return bool(_settings(settings).publish_relay_token)


def publish_relay_request_token(headers: Any) -> str:
    direct = normalize_string(headers.get("X-OpenClaw-Relay-Token", ""))
    if direct:
        return direct
    auth = normalize_string(headers.get("Authorization", ""))
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def publish_relay_token_valid(headers: Any, *, settings: Settings | None = None) -> bool:
    token = _settings(settings).publish_relay_token
    if not token:
        return False
    provided = publish_relay_request_token(headers)
    return bool(provided) and secrets.compare_digest(provided, token)


def publish_relay_record_from_row(row: sqlite3.Row, include_packet: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row["packet_id"],
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
    }
    if include_packet:
        try:
            payload["packet"] = json.loads(row["packet_json"] or "{}")
        except json.JSONDecodeError as error:
            LOGGER.warning("Invalid publish relay packet JSON for %s: %s", row["packet_id"], error)
            payload["packet"] = {}
    if row["result_json"]:
        try:
            payload["result"] = json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError as error:
            LOGGER.warning("Invalid publish relay result JSON for %s: %s", row["packet_id"], error)
            payload["result"] = row["result_json"]
    return payload


def publish_relay_fetch(conn: sqlite3.Connection, packet_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from publish_relay_packets where packet_id = ?",
        (packet_id,),
    ).fetchone()


def publish_relay_enqueue(
    packet: dict[str, Any],
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
    packet_id_fn: PacketIdFn = publish_relay_packet_id,
) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ActivationError("Invalid JSON body", 400)
    channel_id = normalize_string(packet.get("channelId") or packet.get("channel_id"))
    if not channel_id:
        raise ActivationError("Missing required field: channelId", 400)
    schema = normalize_string(packet.get("schema"))
    if schema not in {"openclaw.publish.packet.v1", "openclaw.phone.screenshot.v1"}:
        raise ActivationError("Unsupported packet schema", 400)

    packet_id = packet_id_fn()
    timestamp = utc_now()
    with (connect_fn or (lambda: _connect(settings, defaults)))() as conn:
        conn.execute(
            """
            insert into publish_relay_packets (
                packet_id, channel_id, packet_json, status, attempts,
                created_at, updated_at, leased_by, lease_id, lease_until_ms,
                next_available_at_ms, completed_at, result_json, last_error
            )
            values (?, ?, ?, 'pending', 0, ?, ?, '', '', 0, 0, '', '', '')
            """,
            (packet_id, channel_id, json.dumps(packet, ensure_ascii=False), timestamp, timestamp),
        )
        conn.commit()
        row = publish_relay_fetch(conn, packet_id)
        assert row is not None
        return publish_relay_record_from_row(row, include_packet=True)


def publish_relay_claim(
    channel_id: str,
    client_id: str,
    lease_ms: int,
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
    lease_id_fn: LeaseIdFn = publish_relay_lease_id,
) -> dict[str, Any] | None:
    active_settings = _settings(settings)
    channel_id = normalize_string(channel_id)
    client_id = normalize_string(client_id) or "default-client"
    lease_ms = clamp_int(lease_ms, 1_000, 15 * 60_000, active_settings.publish_relay_default_lease_ms)
    if not channel_id:
        raise ActivationError("Missing channelId", 400)

    connect = connect_fn or (lambda: _connect(
        active_settings,
        defaults,
        timeout=PUBLISH_RELAY_CLAIM_CONNECT_TIMEOUT_SECONDS,
    ))
    for attempt in range(PUBLISH_RELAY_CLAIM_MAX_ATTEMPTS):
        try:
            current_ms = now_ms()
            with connect() as conn:
                conn.execute(f"pragma busy_timeout = {PUBLISH_RELAY_CLAIM_BUSY_TIMEOUT_MS}")
                rows = conn.execute(
                    """
                    select packet_id, attempts from publish_relay_packets
                    where channel_id = ? and status not in ('done', 'failed')
                        and (status != 'leased' or lease_until_ms <= ?)
                        and next_available_at_ms <= ?
                    order by seq asc
                    """,
                    (channel_id, current_ms, current_ms),
                ).fetchall()
                for row in rows:
                    if int(row["attempts"] or 0) >= active_settings.publish_relay_max_attempts:
                        timestamp = utc_now()
                        conn.execute(
                            """
                            update publish_relay_packets
                            set status = 'failed', updated_at = ?, completed_at = ?,
                                last_error = case when last_error = '' then 'Max retry attempts reached' else last_error end
                            where packet_id = ? and status not in ('done', 'failed')
                                and attempts >= ?
                                and (status != 'leased' or lease_until_ms <= ?)
                                and next_available_at_ms <= ?
                            """,
                            (
                                timestamp,
                                timestamp,
                                row["packet_id"],
                                active_settings.publish_relay_max_attempts,
                                current_ms,
                                current_ms,
                            ),
                        )
                        continue

                    lease_id = lease_id_fn()
                    updated = conn.execute(
                        """
                        update publish_relay_packets
                        set status = 'leased', attempts = attempts + 1, leased_by = ?,
                            lease_id = ?, lease_until_ms = ?, updated_at = ?
                        where packet_id = ? and status not in ('done', 'failed')
                            and attempts < ?
                            and (status != 'leased' or lease_until_ms <= ?)
                            and next_available_at_ms <= ?
                        """,
                        (
                            client_id,
                            lease_id,
                            current_ms + lease_ms,
                            utc_now(),
                            row["packet_id"],
                            active_settings.publish_relay_max_attempts,
                            current_ms,
                            current_ms,
                        ),
                    )
                    if updated.rowcount != 1:
                        continue
                    conn.commit()
                    claimed = publish_relay_fetch(conn, row["packet_id"])
                    assert claimed is not None
                    return publish_relay_record_from_row(claimed, include_packet=True)
                return None
        except sqlite3.OperationalError as error:
            error_code = getattr(error, "sqlite_errorcode", None)
            lock_contention = error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            if not lock_contention and "locked" not in str(error).lower():
                raise
            if attempt + 1 >= PUBLISH_RELAY_CLAIM_MAX_ATTEMPTS:
                raise ActivationError(
                    "Publish relay temporarily unavailable",
                    503,
                    "SERVICE_UNAVAILABLE",
                ) from None
            time.sleep(PUBLISH_RELAY_CLAIM_RETRY_DELAY_MS / 1000.0)
    raise AssertionError("unreachable")


def publish_relay_wait_for_packet(
    channel_id: str,
    client_id: str,
    lease_ms: int,
    wait_ms: int,
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    claim_fn: ClaimFn | None = None,
) -> dict[str, Any] | None:
    active_settings = _settings(settings)
    wait_ms = clamp_int(wait_ms, 0, 15 * 60_000, active_settings.publish_relay_default_wait_ms)
    deadline = now_ms() + wait_ms
    claim = claim_fn or (lambda channel, client, lease: publish_relay_claim(
        channel,
        client,
        lease,
        settings=active_settings,
        defaults=defaults,
    ))
    while True:
        claimed = claim(channel_id, client_id, lease_ms)
        if claimed:
            return claimed
        if wait_ms <= 0 or now_ms() >= deadline:
            return None
        time.sleep(min(0.5, max(0.25, (deadline - now_ms()) / 1000.0)))


def publish_relay_complete(
    body: dict[str, Any],
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
    backoff_fn: BackoffFn = publish_relay_backoff_ms,
) -> dict[str, Any]:
    active_settings = _settings(settings)
    packet_id = normalize_string(body.get("packetId") or body.get("id"))
    lease_id = normalize_string(body.get("leaseId") or body.get("lease_id"))
    client_id = normalize_string(body.get("clientId") or body.get("client_id"))
    success = bool(body.get("success"))
    if not packet_id:
        raise ActivationError("Missing packetId", 400)
    if not lease_id:
        raise ActivationError("Missing leaseId", 400)
    if not client_id:
        raise ActivationError("Missing clientId", 400)

    with (connect_fn or (lambda: _connect(active_settings, defaults)))() as conn:
        row = publish_relay_fetch(conn, packet_id)
        if row is None:
            raise ActivationError(f"Packet not found: {packet_id}", 404)

        result = body.get("result", body.get("response"))
        result_json = json.dumps(result, ensure_ascii=False) if result is not None else ""
        error = "" if success else normalize_string(body.get("error") or body.get("message"))
        current_ms = now_ms()
        timestamp = utc_now()
        if success:
            changed = conn.execute(
                """
                update publish_relay_packets
                set status = 'done', updated_at = ?, completed_at = ?,
                    lease_id = '', leased_by = '', lease_until_ms = 0,
                    next_available_at_ms = 0, result_json = ?, last_error = ''
                where packet_id = ? and status = 'leased'
                    and lease_id = ? and leased_by = ?
                """,
                (timestamp, timestamp, result_json, packet_id, lease_id, client_id),
            )
        else:
            attempts = int(row["attempts"] or 0)
            retryable = attempts < active_settings.publish_relay_max_attempts
            changed = conn.execute(
                """
                update publish_relay_packets
                set status = ?, updated_at = ?, completed_at = ?,
                    lease_id = '', leased_by = '', lease_until_ms = 0,
                    next_available_at_ms = ?, result_json = ?, last_error = ?
                where packet_id = ? and status = 'leased'
                    and lease_id = ? and leased_by = ?
                """,
                (
                    "pending" if retryable else "failed",
                    timestamp,
                    "" if retryable else timestamp,
                    current_ms + backoff_fn(attempts) if retryable else 0,
                    result_json,
                    error,
                    packet_id,
                    lease_id,
                    client_id,
                ),
            )
        if changed.rowcount != 1:
            raise ActivationError("Lease is no longer current", 409)
        conn.commit()
        updated = publish_relay_fetch(conn, packet_id)
        assert updated is not None
        return publish_relay_record_from_row(updated)


def publish_relay_status(
    packet_id: str,
    include_packet: bool = True,
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
) -> dict[str, Any]:
    packet_id = normalize_string(packet_id)
    if not packet_id:
        raise ActivationError("Missing packetId", 400)
    with (connect_fn or (lambda: _connect(settings, defaults)))() as conn:
        row = publish_relay_fetch(conn, packet_id)
        if row is None:
            raise ActivationError(f"Packet not found: {packet_id}", 404)
        return publish_relay_record_from_row(row, include_packet=include_packet)


def publish_relay_stats(
    channel_id: str = "",
    *,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
) -> dict[str, Any]:
    channel_id = normalize_string(channel_id)
    current_ms = now_ms()
    params: tuple[Any, ...] = ()
    where = ""
    if channel_id:
        where = "where channel_id = ?"
        params = (channel_id,)
    with (connect_fn or (lambda: _connect(settings, defaults)))() as conn:
        rows = conn.execute(
            f"select status, lease_until_ms, next_available_at_ms from publish_relay_packets {where}", params
        ).fetchall()
    pending = 0
    leased = 0
    done = 0
    failed = 0
    for row in rows:
        status = row["status"]
        if status == "done":
            done += 1
        elif status == "failed":
            failed += 1
        elif status == "leased" and int(row["lease_until_ms"] or 0) > current_ms:
            leased += 1
        elif int(row["next_available_at_ms"] or 0) <= current_ms:
            pending += 1
    return {
        "channelId": channel_id or None,
        "total": len(rows),
        "pending": pending,
        "leased": leased,
        "done": done,
        "failed": failed,
    }
