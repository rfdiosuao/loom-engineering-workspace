from __future__ import annotations

import logging
from typing import Any, Callable

from ..domains import relay as relay_domain


Route = Callable[[Any, Any], None]
LOGGER = logging.getLogger("openclaw-license")


def _send_producer_error(handler: Any, error: Exception) -> None:
    headers = (
        {"WWW-Authenticate": 'Bearer realm="loom-relay-producer"'}
        if error.status == 401
        else None
    )
    message = str(error)
    code = error.code
    handler.send_json(
        error.status,
        {
            "ok": False,
            "error": {"message": message, "code": code},
            "message": message,
            "code": code,
        },
        headers=headers,
    )


def _producer_context(handler: Any, authorization: Any) -> dict[str, Any]:
    api = handler.facade
    producer_token = relay_domain.publish_relay_producer_request_token(
        handler.headers
    )
    context = relay_domain.publish_relay_validate_producer_authorization(
        authorization,
        current_entitlement_fn=api.current_account_entitlement,
        producer_token=producer_token,
        settings=api.SETTINGS,
    )
    scope = relay_domain.publish_relay_producer_scope_from_headers(handler.headers)
    if (
        scope["accountId"] != context["accountId"]
        or scope["entitlementVersion"] != context["entitlementVersion"]
        or not api.secrets.compare_digest(
            scope["runtimeConfigDigest"],
            context["runtimeConfigDigest"],
        )
    ):
        raise api.ActivationError(
            "Relay producer authentication required",
            401,
            "RELAY_PRODUCER_AUTH_REQUIRED",
        )
    return context


def _producer_status_record(
    handler: Any,
    packet_id: str,
    scope: dict[str, Any],
) -> dict[str, Any]:
    api = handler.facade
    producer_token = relay_domain.publish_relay_producer_request_token(
        handler.headers
    )
    record = relay_domain.publish_relay_status(
        packet_id,
        include_packet=True,
        account_id=scope["accountId"],
        entitlement_version=scope["entitlementVersion"],
        runtime_config_digest=scope["runtimeConfigDigest"],
        settings=api.SETTINGS,
        defaults=api.DB_DEFAULTS,
        connect_fn=api.connect,
    )
    packet = record.get("packet")
    authorization = packet.get("authorization") if isinstance(packet, dict) else None
    try:
        context = relay_domain.publish_relay_validate_producer_authorization(
            authorization,
            current_entitlement_fn=api.current_account_entitlement,
            producer_token=producer_token,
            settings=api.SETTINGS,
        )
    except api.ActivationError as error:
        if error.status != 401:
            raise
        raise api.ActivationError(
            "Relay packet not found",
            404,
            "RELAY_PACKET_NOT_FOUND",
        ) from None
    if (
        context["accountId"] != scope["accountId"]
        or context["entitlementVersion"] != scope["entitlementVersion"]
        or not api.secrets.compare_digest(
            context["runtimeConfigDigest"],
            scope["runtimeConfigDigest"],
        )
    ):
        raise api.ActivationError(
            "Relay packet not found",
            404,
            "RELAY_PACKET_NOT_FOUND",
        )
    public_record = dict(record)
    if isinstance(packet, dict):
        public_packet = dict(packet)
        public_packet.pop("authorization", None)
        public_record["packet"] = public_packet
    return public_record


def get_api_lumi_relay_health(handler, parsed):
    api = handler.facade
    authorized = api.publish_relay_token_valid(handler.headers)
    handler.send_json(
        200,
        {
            "ok": True,
            "data": {
                "authRequired": api.publish_relay_auth_required(),
                "configured": api.publish_relay_configured(),
                "authenticated": authorized,
                "queue": api.publish_relay_stats() if authorized else None,
                "timestamp": api.utc_now(),
            },
        },
    )


def get_api_lumi_relay_poll(handler, parsed):
    api = handler.facade
    if not handler.require_publish_relay_auth():
        return
    query = api.parse_qs(parsed.query)
    channel_id = api.normalize_string(
        (query.get("channelId") or query.get("channel_id") or [""])[0]
    )
    client_id = (
        api.normalize_string(
            (query.get("clientId") or query.get("client_id") or ["default-client"])[0]
        )
        or "default-client"
    )
    lease_ms = api.clamp_int(
        (
            query.get("leaseMs")
            or query.get("lease_ms")
            or [api.PUBLISH_RELAY_DEFAULT_LEASE_MS]
        )[0],
        1000,
        15 * 60000,
        api.PUBLISH_RELAY_DEFAULT_LEASE_MS,
    )
    wait_ms = api.clamp_int(
        (
            query.get("waitMs")
            or query.get("wait_ms")
            or [api.PUBLISH_RELAY_DEFAULT_WAIT_MS]
        )[0],
        0,
        15 * 60000,
        api.PUBLISH_RELAY_DEFAULT_WAIT_MS,
    )
    try:
        record = api.publish_relay_wait_for_packet(
            channel_id, client_id, lease_ms, wait_ms
        )
        if not record:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "data": {
                        "packet": None,
                        "channelId": channel_id,
                        "clientId": client_id,
                        "waitMs": wait_ms,
                        "leaseMs": lease_ms,
                    },
                },
            )
            return
        handler.send_json(
            200,
            {
                "ok": True,
                "data": {
                    "packetId": record["id"],
                    "leaseId": record["leaseId"],
                    "channelId": record["channelId"],
                    "leaseUntil": record["leaseUntil"],
                    "attempts": record["attempts"],
                    "packet": record["packet"],
                },
            },
        )
    except api.ActivationError as error:
        handler.send_json(error.status, {"ok": False, "error": str(error)})
    except Exception:
        LOGGER.exception("Publish relay poll failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def get_api_lumi_relay_status(handler, parsed):
    api = handler.facade
    try:
        query = api.parse_qs(parsed.query)
        packet_id = api.normalize_string(
            (
                query.get("id")
                or query.get("packetId")
                or query.get("packet_id")
                or [""]
            )[0]
        )
        if not packet_id:
            raise api.ActivationError(
                "Missing packetId",
                400,
                "RELAY_PACKET_ID_REQUIRED",
            )
        scope = relay_domain.publish_relay_producer_scope_from_headers(handler.headers)
        handler.send_json(
            200,
            {
                "ok": True,
                "data": _producer_status_record(handler, packet_id, scope),
            },
        )
    except api.ActivationError as error:
        _send_producer_error(handler, error)
    except Exception:
        LOGGER.exception("Publish relay status failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def post_api_lumi_relay_packet(handler, parsed):
    api = handler.facade
    try:
        packet = handler.read_json()
        if not isinstance(packet, dict):
            raise api.ActivationError(
                "Invalid JSON body",
                400,
                "RELAY_PACKET_INVALID",
            )
        producer = _producer_context(handler, packet.get("authorization"))
        record = relay_domain.publish_relay_enqueue(
            packet,
            account_id=producer["accountId"],
            settings=api.SETTINGS,
            defaults=api.DB_DEFAULTS,
            connect_fn=api.connect,
            packet_id_fn=api.publish_relay_packet_id,
        )
        handler.send_json(
            202,
            {
                "ok": True,
                "data": {
                    "packetId": record["id"],
                    "channelId": record["channelId"],
                    "status": record["status"],
                    "attempts": record["attempts"],
                    "createdAt": record["createdAt"],
                    "updatedAt": record["updatedAt"],
                    "statusUrl": f"/api/lumi/relay/status?id={record['id']}",
                },
            },
        )
    except api.ActivationError as error:
        _send_producer_error(handler, error)
    except ValueError:
        handler.send_json(
            400,
            {
                "ok": False,
                "error": "Invalid JSON body",
                "code": "RELAY_PACKET_INVALID",
            },
        )
    except Exception:
        LOGGER.exception("Publish relay enqueue failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def post_api_lumi_relay_complete(handler, parsed):
    api = handler.facade
    if not handler.require_publish_relay_auth():
        return
    try:
        record = api.publish_relay_complete(handler.read_json())
        handler.send_json(200, {"ok": True, "data": record})
    except api.ActivationError as error:
        handler.send_json(error.status, {"ok": False, "error": str(error)})
    except Exception:
        LOGGER.exception("Publish relay completion failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def post_api_lumi_relay_commit_authorize(handler, parsed):
    api = handler.facade
    if not handler.require_publish_relay_auth():
        return
    try:
        data = api.publish_relay_authorize_commit(handler.read_json())
        handler.send_json(200, {"ok": True, "data": data})
    except api.ActivationError as error:
        handler.send_json(
            error.status,
            {"ok": False, "error": str(error), "code": error.code},
        )
    except Exception:
        LOGGER.exception("Publish relay commit authorization failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


GET_ROUTES: dict[str, Route] = {
    "/api/lumi/relay/health": get_api_lumi_relay_health,
    "/api/lumi/publish/health": get_api_lumi_relay_health,
    "/api/lumi/relay/poll": get_api_lumi_relay_poll,
    "/api/lumi/publish/poll": get_api_lumi_relay_poll,
    "/api/lumi/relay/status": get_api_lumi_relay_status,
    "/api/lumi/publish/status": get_api_lumi_relay_status,
}


POST_ROUTES: dict[str, Route] = {
    "/api/lumi/relay/packet": post_api_lumi_relay_packet,
    "/api/lumi/publish/packet": post_api_lumi_relay_packet,
    "/api/lumi/relay/commit-authorize": post_api_lumi_relay_commit_authorize,
    "/api/lumi/publish/commit-authorize": post_api_lumi_relay_commit_authorize,
    "/api/lumi/relay/complete": post_api_lumi_relay_complete,
    "/api/lumi/publish/complete": post_api_lumi_relay_complete,
}
