from __future__ import annotations

import logging
from typing import Any, Callable


Route = Callable[[Any, Any], None]
LOGGER = logging.getLogger("openclaw-license")


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
    if not handler.require_publish_relay_auth():
        return
    query = api.parse_qs(parsed.query)
    packet_id = api.normalize_string(
        (query.get("id") or query.get("packetId") or query.get("packet_id") or [""])[0]
    )
    channel_id = api.normalize_string(
        (query.get("channelId") or query.get("channel_id") or [""])[0]
    )
    try:
        if packet_id:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "data": api.publish_relay_status(packet_id, include_packet=True),
                },
            )
        else:
            handler.send_json(
                200,
                {"ok": True, "data": {"queue": api.publish_relay_stats(channel_id)}},
            )
    except api.ActivationError as error:
        handler.send_json(error.status, {"ok": False, "error": str(error)})
    except Exception:
        LOGGER.exception("Publish relay status failed")
        handler.send_json(500, {"ok": False, "error": "Internal server error"})


def post_api_lumi_relay_packet(handler, parsed):
    api = handler.facade
    if not handler.require_publish_relay_auth():
        return
    try:
        record = api.publish_relay_enqueue(handler.read_json())
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
        handler.send_json(error.status, {"ok": False, "error": str(error)})
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
    "/api/lumi/relay/complete": post_api_lumi_relay_complete,
    "/api/lumi/publish/complete": post_api_lumi_relay_complete,
}
