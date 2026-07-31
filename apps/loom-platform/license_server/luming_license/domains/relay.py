from __future__ import annotations

import hashlib
import inspect
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .. import db, security
from ..config import Settings
from ..errors import ActivationError
from ..serialization import clamp_int, normalize_string
from ..timeutils import now_ms, utc_now
from . import relay_storage
from .relay_authorization import (
    CurrentEntitlementFn,
    PUBLISH_RELAY_ENTITLEMENT_KEY_ID,
    PUBLISH_RELAY_ENTITLEMENT_SCHEMA,
    PUBLISH_RELAY_MAX_CLOCK_SKEW_SECONDS,
    PUBLISH_RELAY_PHONE_SEAT_SCHEMA,
    PUBLISH_RELAY_PRODUCER_AUTH_SCHEMA,
    PUBLISH_RELAY_PRODUCER_FEATURES,
    _producer_account_id,
    _producer_auth_unavailable,
    _producer_entitlement_error,
    publish_relay_producer_request_token,
    publish_relay_producer_scope_from_headers,
    publish_relay_validate_current_authorization,
    publish_relay_validate_producer_authorization,
)

PUBLISH_RELAY_BACKOFF_MS = 2_000
PUBLISH_RELAY_MAX_BACKOFF_MS = 5 * 60_000
PUBLISH_RELAY_CLAIM_BUSY_TIMEOUT_MS = 100
PUBLISH_RELAY_CLAIM_CONNECT_TIMEOUT_SECONDS = 0.1
PUBLISH_RELAY_CLAIM_MAX_ATTEMPTS = 3
PUBLISH_RELAY_CLAIM_RETRY_DELAY_MS = 50
PUBLISH_RELAY_COMMIT_TOKEN_TTL_MS = 15_000
PUBLISH_RELAY_COMMIT_INDETERMINATE_ERROR = (
    "Formal publish commit outcome is indeterminate; automatic retry is blocked"
)

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


publish_relay_ensure_state_columns = relay_storage.ensure_state_columns
_packet_json = relay_storage.packet_json
_formal_publish_packet = relay_storage.is_formal_publish_packet
_strict_commit_policy = relay_storage.has_strict_commit_policy
publish_relay_record_from_row = relay_storage.record_from_row
publish_relay_fetch = relay_storage.fetch


def publish_relay_enqueue(
    packet: dict[str, Any],
    *,
    account_id: str = "",
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

    normalized_account_id = normalize_string(account_id)
    if normalized_account_id:
        normalized_account_id = _producer_account_id(normalized_account_id)
        if schema == "openclaw.publish.packet.v1":
            if not isinstance(packet.get("draftOnly"), bool):
                raise ActivationError(
                    "Publish packet must declare draftOnly",
                    400,
                    "RELAY_PACKET_MODE_REQUIRED",
                )
            if not _strict_commit_policy(packet):
                raise ActivationError(
                    "Publish packet commit policy is incomplete",
                    400,
                    "RELAY_COMMIT_POLICY_REQUIRED",
                )

    packet_id = packet_id_fn()
    timestamp = utc_now()
    with (connect_fn or (lambda: _connect(settings, defaults)))() as conn:
        publish_relay_ensure_state_columns(conn)
        conn.execute(
            """
            insert into publish_relay_packets (
                packet_id, account_id, channel_id, packet_json, status, attempts,
                created_at, updated_at, leased_by, lease_id, lease_until_ms,
                next_available_at_ms, completed_at, result_json, last_error
            )
            values (?, ?, ?, ?, 'pending', 0, ?, ?, '', '', 0, 0, '', '', '')
            """,
            (
                packet_id,
                normalized_account_id,
                channel_id,
                json.dumps(packet, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
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
    current_entitlement_fn: CurrentEntitlementFn | None = None,
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
                publish_relay_ensure_state_columns(conn)
                conn.execute(f"pragma busy_timeout = {PUBLISH_RELAY_CLAIM_BUSY_TIMEOUT_MS}")
                rows = conn.execute(
                    """
                    select * from publish_relay_packets
                    where channel_id = ? and status not in ('done', 'failed')
                        and (status != 'leased' or lease_until_ms <= ?)
                        and next_available_at_ms <= ?
                    order by seq asc
                    """,
                    (channel_id, current_ms, current_ms),
                ).fetchall()
                for row in rows:
                    if normalize_string(row["commit_state"]) == "authorized":
                        timestamp = utc_now()
                        conn.execute(
                            """
                            update publish_relay_packets
                            set status = 'failed', updated_at = ?, completed_at = ?,
                                outcome_indeterminate = 1,
                                commit_state = 'indeterminate', last_error = ?
                            where packet_id = ? and status not in ('done', 'failed')
                                and commit_state = 'authorized'
                                and lease_until_ms <= ?
                            """,
                            (
                                timestamp,
                                timestamp,
                                PUBLISH_RELAY_COMMIT_INDETERMINATE_ERROR,
                                row["packet_id"],
                                current_ms,
                            ),
                        )
                        continue

                    if normalize_string(row["account_id"]):
                        if current_entitlement_fn is None:
                            raise _producer_auth_unavailable()
                        try:
                            packet = _packet_json(row)
                            context = publish_relay_validate_current_authorization(
                                packet.get("authorization"),
                                current_entitlement_fn=current_entitlement_fn,
                                settings=active_settings,
                            )
                            if context["accountId"] != normalize_string(row["account_id"]):
                                raise _producer_entitlement_error()
                            if (
                                context["selectedDeviceInstanceId"]
                                != client_id
                            ):
                                continue
                        except ActivationError as error:
                            if error.status >= 500:
                                raise
                            timestamp = utc_now()
                            conn.execute(
                                """
                                update publish_relay_packets
                                set status = 'failed', updated_at = ?, completed_at = ?,
                                    commit_state = 'denied',
                                    last_error = 'Relay authorization is no longer active'
                                where packet_id = ? and status not in ('done', 'failed')
                                    and (status != 'leased' or lease_until_ms <= ?)
                                """,
                                (timestamp, timestamp, row["packet_id"], current_ms),
                            )
                            continue

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


def publish_relay_authorize_commit(
    body: dict[str, Any],
    *,
    current_entitlement_fn: CurrentEntitlementFn,
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
    token_fn: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ActivationError("Invalid JSON body", 400, "RELAY_COMMIT_INVALID")
    packet_id = normalize_string(body.get("packetId") or body.get("id"))
    lease_id = normalize_string(body.get("leaseId") or body.get("lease_id"))
    client_id = normalize_string(body.get("clientId") or body.get("client_id"))
    if not packet_id or not lease_id or not client_id:
        raise ActivationError(
            "Commit authorization requires packetId, leaseId and clientId",
            400,
            "RELAY_COMMIT_INVALID",
        )

    active_settings = _settings(settings)
    with (connect_fn or (lambda: _connect(active_settings, defaults)))() as conn:
        conn.execute("BEGIN IMMEDIATE")
        publish_relay_ensure_state_columns(conn)
        row = publish_relay_fetch(conn, packet_id)
        current_ms = now_ms()
        if (
            row is None
            or normalize_string(row["status"]) != "leased"
            or normalize_string(row["lease_id"]) != lease_id
            or normalize_string(row["leased_by"]) != client_id
            or int(row["lease_until_ms"] or 0) <= current_ms
        ):
            raise ActivationError(
                "Relay lease is no longer current",
                409,
                "RELAY_COMMIT_LEASE_STALE",
            )
        if normalize_string(row["commit_state"]):
            raise ActivationError(
                "Publish commit was already authorized or denied",
                409,
                "RELAY_COMMIT_ALREADY_DECIDED",
            )

        packet = _packet_json(row)
        if not _formal_publish_packet(packet) or not _strict_commit_policy(packet):
            raise ActivationError(
                "Packet is not eligible for formal publish commit",
                409,
                "RELAY_COMMIT_NOT_ALLOWED",
            )
        context = publish_relay_validate_current_authorization(
            packet.get("authorization"),
            current_entitlement_fn=current_entitlement_fn,
            settings=active_settings,
        )
        if context["accountId"] != normalize_string(row["account_id"]):
            raise _producer_entitlement_error()
        if context["selectedDeviceInstanceId"] != client_id:
            raise ActivationError(
                "Relay lease does not belong to the selected phone",
                409,
                "RELAY_COMMIT_DEVICE_MISMATCH",
            )

        token = normalize_string(token_fn())
        if len(token) < 32:
            raise ActivationError(
                "Commit authorization unavailable",
                503,
                "RELAY_COMMIT_UNAVAILABLE",
            )
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        timestamp = utc_now()
        expires_at_ms = current_ms + PUBLISH_RELAY_COMMIT_TOKEN_TTL_MS
        changed = conn.execute(
            """
            update publish_relay_packets
            set commit_token_hash = ?, commit_authorized_at = ?,
                commit_expires_at_ms = ?, commit_lease_id = ?,
                commit_client_id = ?, commit_state = 'authorized',
                updated_at = ?
            where packet_id = ? and status = 'leased'
                and lease_id = ? and leased_by = ? and lease_until_ms > ?
                and commit_state = ''
            """,
            (
                token_hash,
                timestamp,
                expires_at_ms,
                lease_id,
                client_id,
                timestamp,
                packet_id,
                lease_id,
                client_id,
                current_ms,
            ),
        )
        if changed.rowcount != 1:
            raise ActivationError(
                "Relay lease is no longer current",
                409,
                "RELAY_COMMIT_LEASE_STALE",
            )
        conn.commit()
        return {
            "packetId": packet_id,
            "leaseId": lease_id,
            "clientId": client_id,
            "commitToken": token,
            "expiresAt": expires_at_ms,
        }


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
        publish_relay_ensure_state_columns(conn)
        row = publish_relay_fetch(conn, packet_id)
        if row is None:
            raise ActivationError(f"Packet not found: {packet_id}", 404)

        result = body.get("result", body.get("response"))
        result_json = json.dumps(result, ensure_ascii=False) if result is not None else ""
        error = "" if success else normalize_string(body.get("error") or body.get("message"))
        current_ms = now_ms()
        timestamp = utc_now()
        packet = _packet_json(row)
        formal_publish = _formal_publish_packet(packet) and bool(
            normalize_string(row["account_id"])
        )
        commit_token = normalize_string(body.get("commitToken") or body.get("commit_token"))
        stored_commit_hash = normalize_string(row["commit_token_hash"])
        commit_matches = bool(commit_token and stored_commit_hash) and secrets.compare_digest(
            hashlib.sha256(commit_token.encode("utf-8")).hexdigest(),
            stored_commit_hash,
        )
        commit_expired = (
            normalize_string(row["commit_state"]) == "authorized"
            and int(row["commit_expires_at_ms"] or 0) <= current_ms
        )
        if success and formal_publish and (
            normalize_string(row["commit_state"]) != "authorized"
            or normalize_string(row["commit_lease_id"]) != lease_id
            or normalize_string(row["commit_client_id"]) != client_id
            or not commit_matches
        ):
            raise ActivationError(
                "Formal publish completion requires its one-time commit token",
                409,
                "RELAY_COMMIT_TOKEN_REQUIRED",
            )
        if success and formal_publish and commit_expired:
            raise ActivationError(
                "Formal publish commit token expired before completion",
                409,
                "RELAY_COMMIT_TOKEN_EXPIRED",
            )
        if success:
            changed = conn.execute(
                """
                update publish_relay_packets
                set status = 'done', updated_at = ?, completed_at = ?,
                    lease_id = '', leased_by = '', lease_until_ms = 0,
                    next_available_at_ms = 0, result_json = ?, last_error = '',
                    commit_token_hash = '',
                    commit_state = case when commit_state = 'authorized'
                        then 'consumed' else commit_state end
                where packet_id = ? and status = 'leased'
                    and lease_id = ? and leased_by = ?
                """,
                (timestamp, timestamp, result_json, packet_id, lease_id, client_id),
            )
        else:
            attempts = int(row["attempts"] or 0)
            commit_authorized = normalize_string(row["commit_state"]) == "authorized"
            retryable = (
                attempts < active_settings.publish_relay_max_attempts
                and not commit_authorized
            )
            terminal_error = (
                PUBLISH_RELAY_COMMIT_INDETERMINATE_ERROR
                if commit_authorized
                else error
            )
            changed = conn.execute(
                """
                update publish_relay_packets
                set status = ?, updated_at = ?, completed_at = ?,
                    lease_id = '', leased_by = '', lease_until_ms = 0,
                    next_available_at_ms = ?, result_json = ?, last_error = ?,
                    outcome_indeterminate = ?,
                    commit_state = case when commit_state = 'authorized'
                        then 'indeterminate' else commit_state end
                where packet_id = ? and status = 'leased'
                    and lease_id = ? and leased_by = ?
                """,
                (
                    "pending" if retryable else "failed",
                    timestamp,
                    "" if retryable else timestamp,
                    current_ms + backoff_fn(attempts) if retryable else 0,
                    result_json,
                    terminal_error,
                    1 if commit_authorized else 0,
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
    account_id: str = "",
    entitlement_version: int | None = None,
    runtime_config_digest: str = "",
    settings: Settings | None = None,
    defaults: dict[str, Any] | None = None,
    connect_fn: ConnectFn | None = None,
) -> dict[str, Any]:
    packet_id = normalize_string(packet_id)
    if not packet_id:
        raise ActivationError("Missing packetId", 400)
    normalized_account_id = normalize_string(account_id)
    if normalized_account_id:
        normalized_account_id = _producer_account_id(normalized_account_id)
    with (connect_fn or (lambda: _connect(settings, defaults)))() as conn:
        if normalized_account_id:
            publish_relay_ensure_state_columns(conn)
        row = publish_relay_fetch(
            conn,
            packet_id,
            account_id=normalized_account_id,
        )
        if row is None:
            raise ActivationError(
                "Relay packet not found",
                404,
                "RELAY_PACKET_NOT_FOUND",
            )
        record = publish_relay_record_from_row(row, include_packet=include_packet)
        if normalized_account_id:
            packet = record.get("packet")
            authorization = (
                packet.get("authorization") if isinstance(packet, dict) else None
            )
            expected_digest = normalize_string(runtime_config_digest).lower()
            actual_digest = (
                normalize_string(authorization.get("runtimeConfigDigest")).lower()
                if isinstance(authorization, dict)
                else ""
            )
            actual_version = (
                authorization.get("entitlementVersion")
                if isinstance(authorization, dict)
                else None
            )
            metadata_matches = (
                isinstance(actual_version, int)
                and not isinstance(actual_version, bool)
                and actual_version == entitlement_version
                and bool(expected_digest)
                and bool(actual_digest)
                and secrets.compare_digest(actual_digest, expected_digest)
            )
            if not metadata_matches:
                raise ActivationError(
                    "Relay packet not found",
                    404,
                    "RELAY_PACKET_NOT_FOUND",
                )
        return record


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
