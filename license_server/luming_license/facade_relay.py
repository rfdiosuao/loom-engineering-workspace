"""Publish relay and license-creation facade adapter blueprints."""

from __future__ import annotations

# Functions in this module are rebound to an owning facade namespace before use.
# ruff: noqa: F821


def publish_relay_backoff_ms(attempts: int) -> int:
    return relay.publish_relay_backoff_ms(attempts)


def publish_relay_packet_id() -> str:
    return relay.publish_relay_packet_id()


def publish_relay_lease_id() -> str:
    return relay.publish_relay_lease_id()


def publish_relay_auth_required() -> bool:
    return relay.publish_relay_auth_required()


def publish_relay_configured() -> bool:
    return relay.publish_relay_configured(settings=SETTINGS)


def publish_relay_request_token(headers: Any) -> str:
    return relay.publish_relay_request_token(headers)


def publish_relay_token_valid(headers: Any) -> bool:
    return relay.publish_relay_token_valid(headers, settings=SETTINGS)


def publish_relay_record_from_row(
    row: sqlite3.Row, include_packet: bool = False
) -> dict[str, Any]:
    return relay.publish_relay_record_from_row(row, include_packet=include_packet)


def publish_relay_fetch(conn: sqlite3.Connection, packet_id: str) -> sqlite3.Row | None:
    return relay.publish_relay_fetch(conn, packet_id)


def publish_relay_enqueue(packet: dict[str, Any]) -> dict[str, Any]:
    return relay.publish_relay_enqueue(
        packet,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        connect_fn=connect,
        packet_id_fn=publish_relay_packet_id,
    )


def publish_relay_claim(
    channel_id: str, client_id: str, lease_ms: int
) -> dict[str, Any] | None:
    return relay.publish_relay_claim(
        channel_id,
        client_id,
        lease_ms,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        connect_fn=lambda: relay.connect_with_optional_timeout(
            connect,
            timeout=relay.PUBLISH_RELAY_CLAIM_CONNECT_TIMEOUT_SECONDS,
        ),
        lease_id_fn=publish_relay_lease_id,
    )


def publish_relay_wait_for_packet(
    channel_id: str, client_id: str, lease_ms: int, wait_ms: int
) -> dict[str, Any] | None:
    return relay.publish_relay_wait_for_packet(
        channel_id,
        client_id,
        lease_ms,
        wait_ms,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        claim_fn=publish_relay_claim,
    )


def publish_relay_complete(body: dict[str, Any]) -> dict[str, Any]:
    return relay.publish_relay_complete(
        body,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        connect_fn=connect,
        backoff_fn=publish_relay_backoff_ms,
    )


def publish_relay_status(packet_id: str, include_packet: bool = True) -> dict[str, Any]:
    return relay.publish_relay_status(
        packet_id,
        include_packet=include_packet,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        connect_fn=connect,
    )


def publish_relay_stats(channel_id: str = "") -> dict[str, Any]:
    return relay.publish_relay_stats(
        channel_id,
        settings=SETTINGS,
        defaults=DB_DEFAULTS,
        connect_fn=connect,
    )


def make_code(edition: str = "PRO") -> str:
    return licenses.make_code(edition)


def is_super_admin_context(context: dict[str, Any] | None) -> bool:
    return licenses.is_super_admin_context(
        context, account_role_super_admin=ACCOUNT_ROLE_SUPER_ADMIN
    )


def context_account_id(context: dict[str, Any] | None) -> int:
    return licenses.context_account_id(context)


def code_row_owned_by_context(row: sqlite3.Row, context: dict[str, Any] | None) -> bool:
    return licenses.code_row_owned_by_context(
        row,
        context,
        is_super_admin_context_fn=is_super_admin_context,
        context_account_id_fn=context_account_id,
    )


def create_code_records(
    *,
    count: int,
    licensee: str,
    edition: str,
    features: list[str],
    expires: str,
    max_activations: int,
    member_mode: bool = False,
    plan: str = "",
    gateway_base_url: str = "",
    gateway_image_base_url: str = "",
    gateway_video_base_url: str = "",
    gateway_token: str = "",
    gateway_image_token: str = "",
    gateway_video_token: str = "",
    gateway_default_model: str = "",
    gateway_image_model: str = "",
    gateway_video_model: str = "",
    gateway_models: list[str] | None = None,
    quotas: dict[str, Any] | None = None,
    owner_account_id: int = 0,
) -> list[str]:
    return licenses.create_code_records(
        count=count,
        licensee=licensee,
        edition=edition,
        features=features,
        expires=expires,
        max_activations=max_activations,
        member_mode=member_mode,
        plan=plan,
        gateway_base_url=gateway_base_url,
        gateway_image_base_url=gateway_image_base_url,
        gateway_video_base_url=gateway_video_base_url,
        gateway_token=gateway_token,
        gateway_image_token=gateway_image_token,
        gateway_video_token=gateway_video_token,
        gateway_default_model=gateway_default_model,
        gateway_image_model=gateway_image_model,
        gateway_video_model=gateway_video_model,
        gateway_models=gateway_models,
        quotas=quotas,
        owner_account_id=owner_account_id,
        connect_fn=connect,
        normalize_code_expires_fn=normalize_code_expires,
        make_code_fn=make_code,
        code_hash_fn=code_hash,
        utc_now_fn=utc_now,
    )


__all__ = [
    "publish_relay_backoff_ms",
    "publish_relay_packet_id",
    "publish_relay_lease_id",
    "publish_relay_auth_required",
    "publish_relay_configured",
    "publish_relay_request_token",
    "publish_relay_token_valid",
    "publish_relay_record_from_row",
    "publish_relay_fetch",
    "publish_relay_enqueue",
    "publish_relay_claim",
    "publish_relay_wait_for_packet",
    "publish_relay_complete",
    "publish_relay_status",
    "publish_relay_stats",
    "make_code",
    "is_super_admin_context",
    "context_account_id",
    "code_row_owned_by_context",
    "create_code_records",
]
