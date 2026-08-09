"""Low-latency phone video proxy with local one-time stream tickets."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import quote, urlsplit
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Request
from fastapi.responses import StreamingResponse

from api.routes_phone import (
    _account_entitlement_error_response,
    _authorize_phone_entitlement,
    _current_entitlement_account_id,
    _normalize_device_id,
    _normalize_url,
    _phone_pairing_signed_headers,
    _phone_runtime_snapshot,
)
from api.routes_realtime import (
    _issuer,
    consume_stream_ticket,
    stream_cors_headers,
    stream_preflight_response,
    stream_request_subject,
    stream_ticket_from_request,
)
from core.account_entitlement import AccountEntitlementError


_CLIENT_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PHONE_RESPONSE_LIMIT = 64 * 1024
_UPSTREAM_CONNECT_TIMEOUT_SECONDS = 8
_STREAM_CHUNK_SIZE = 64 * 1024
_GRANTS_LOCK = threading.RLock()
_UPSTREAM_GRANTS: dict[tuple[str, str], dict[str, Any]] = {}


def _default_authorizer(ctx, device_ids: list[str], operation: str) -> None:
    _authorize_phone_entitlement(ctx, device_ids, operation)


def _runtime_device(
    ctx,
    device_id: str,
    runtime_resolver: Callable[[Any, list[str] | None], tuple[dict, str]],
) -> dict:
    runtime, _member_token = runtime_resolver(ctx, [device_id])
    devices = runtime.get("devices") if isinstance(runtime, dict) else None
    for device in devices if isinstance(devices, list) else []:
        if isinstance(device, dict) and _normalize_device_id(device.get("id"), "") == device_id:
            required = ("baseUrl", "launcherId", "launcherSecret")
            if all(str(device.get(key) or "").strip() for key in required):
                return device
    raise ValueError("phone_stream_device_unavailable")


def _phone_headers(device: dict, method: str, path: str, body: bytes) -> dict[str, str]:
    headers = _phone_pairing_signed_headers(
        method,
        path,
        body,
        launcher_id=str(device.get("launcherId") or ""),
        launcher_secret=str(device.get("launcherSecret") or ""),
    )
    token = str(device.get("phoneToken") or "")
    if token:
        headers["X-AGENT-PHONE-TOKEN"] = token
        headers["X-APKCLAW-TOKEN"] = token
    return headers


def _phone_json_request(device: dict, path: str, payload: dict, *, phone_open) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = UrlRequest(
        f"{_normalize_url(str(device.get('baseUrl') or ''))}{path}",
        data=body,
        method="POST",
        headers={
            **_phone_headers(device, "POST", path, body),
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with phone_open(request, timeout=_UPSTREAM_CONNECT_TIMEOUT_SECONDS) as response:
        raw = response.read(_PHONE_RESPONSE_LIMIT + 1)
        status = int(getattr(response, "status", 200) or 200)
    if len(raw) > _PHONE_RESPONSE_LIMIT:
        raise ValueError("phone_stream_response_too_large")
    try:
        envelope = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ValueError("phone_stream_invalid_response") from exc
    if not isinstance(envelope, dict):
        raise ValueError("phone_stream_invalid_response")
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else envelope
    if status >= 400 or envelope.get("success") is False:
        code = str(envelope.get("errorCode") or data.get("errorCode") or "phone_stream_upstream_failed")
        raise ValueError(code)
    return data


def _transport_label(device: dict) -> str:
    host = (urlsplit(str(device.get("baseUrl") or "")).hostname or "").casefold()
    return "usb-forward" if host in {"127.0.0.1", "localhost", "::1"} else "lan"


def _public_session(data: dict, *, transport: str) -> dict:
    state = str(data.get("state") or "unavailable").strip().lower()
    result = {
        "schema": "luming.phone.stream.session.v1",
        "state": state,
        "transport": transport,
        "fallback": "snapshot" if state != "active" else "none",
        "requiresUserConsent": data.get("requiresUserConsent") is True,
        "codec": str(data.get("codec") or "avc1.42E01F"),
        "width": int(data.get("width") or 0),
        "height": int(data.get("height") or 0),
        "fps": int(data.get("fps") or 0),
        "message": str(data.get("message") or "")[:240],
    }
    return result


def register_phone_stream_routes(
    app,
    ctx,
    *,
    phone_open=urlopen,
    runtime_resolver=_phone_runtime_snapshot,
    entitlement_authorizer=_default_authorizer,
    account_id_resolver=_current_entitlement_account_id,
) -> None:
    @app.post("/api/phone-stream/devices/{device_id}/session")
    async def start_phone_stream(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        normalized_id = _normalize_device_id(device_id, "")
        body = await ctx.body(request)
        client_session_id = str(body.get("clientSessionId") or "").strip()
        if not normalized_id or _CLIENT_SESSION_ID.fullmatch(client_session_id) is None:
            return ctx.fastapi_json({"error": "clientSessionId is invalid", "code": "phone_stream_input_invalid"}, 400)
        try:
            entitlement_authorizer(ctx, [normalized_id], "phone.stream.start")
            device = _runtime_device(ctx, normalized_id, runtime_resolver)
            data = _phone_json_request(
                device,
                "/api/lumi/stream/session",
                {
                    "clientSessionId": client_session_id,
                    "fps": max(10, min(20, int(body.get("fps") or 15))),
                    "maxLongSide": max(480, min(1600, int(body.get("maxLongSide") or 1280))),
                    "bitRate": max(600_000, min(8_000_000, int(body.get("bitRate") or 2_400_000))),
                },
                phone_open=phone_open,
            )
        except AccountEntitlementError as exc:
            return _account_entitlement_error_response(ctx, exc)
        except (OSError, TimeoutError, ValueError) as exc:
            code = str(exc) if str(exc).startswith("phone_stream_") else "phone_stream_unavailable"
            return ctx.fastapi_json({
                "error": "手机低延迟画面通道暂不可用，已继续使用截图。",
                "code": code,
                "fallback": "snapshot",
                "retryable": True,
            }, 502)

        public = _public_session(data, transport=_transport_label(device))
        if public["state"] != "active":
            return ctx.fastapi_json(public)
        phone_session_id = str(data.get("sessionId") or "").strip()
        stream_token = str(data.get("streamToken") or "").strip()
        if not phone_session_id or not stream_token:
            return ctx.fastapi_json({
                "error": "手机视频会话未返回短期凭据，已继续使用截图。",
                "code": "phone_stream_session_invalid",
                "fallback": "snapshot",
                "retryable": True,
            }, 502)
        account_id = str(account_id_resolver(ctx) or "").strip()
        key = (account_id, normalized_id)
        with _GRANTS_LOCK:
            _UPSTREAM_GRANTS[key] = {
                "sessionId": phone_session_id,
                "streamToken": stream_token,
                "expiresAtEpochMs": int(data.get("tokenExpiresAtEpochMs") or (time.time() * 1000 + 30_000)),
            }
        subject = stream_request_subject(request)
        ticket = _issuer(ctx).issue(topic="phone_stream", resource=normalized_id, subject=subject)
        return ctx.fastapi_json({
            **public,
            "ticket": ticket,
            "streamUrl": f"/api/phone-stream/devices/{quote(normalized_id, safe='')}/h264",
        })

    @app.options("/api/phone-stream/devices/{device_id}/h264")
    async def phone_stream_preflight(device_id: str, request: Request):
        _ = device_id
        return stream_preflight_response(request)

    @app.get("/api/phone-stream/devices/{device_id}/h264")
    async def proxy_phone_stream(device_id: str, request: Request):
        normalized_id = _normalize_device_id(device_id, "")
        ticket = stream_ticket_from_request(request)
        if consume_stream_ticket(
            ctx,
            ticket,
            topic="phone_stream",
            resource=normalized_id,
            subject=stream_request_subject(request),
        ) is None:
            return ctx.fastapi_json({"error": "A valid one-time phone stream ticket is required", "code": "stream_ticket_invalid"}, 401)
        try:
            entitlement_authorizer(ctx, [normalized_id], "phone.stream.read")
            device = _runtime_device(ctx, normalized_id, runtime_resolver)
        except AccountEntitlementError as exc:
            return _account_entitlement_error_response(ctx, exc)
        except ValueError:
            return ctx.fastapi_json({"error": "手机视频设备不可用", "code": "phone_stream_device_unavailable"}, 404)
        account_id = str(account_id_resolver(ctx) or "").strip()
        with _GRANTS_LOCK:
            grant = dict(_UPSTREAM_GRANTS.get((account_id, normalized_id)) or {})
        if not grant or int(grant.get("expiresAtEpochMs") or 0) < int(time.time() * 1000):
            return ctx.fastapi_json({"error": "手机视频短期凭据已过期", "code": "phone_stream_grant_expired"}, 409)

        phone_path = f"/api/lumi/stream/h264?sessionId={quote(str(grant['sessionId']), safe='')}"
        upstream_request = UrlRequest(
            f"{_normalize_url(str(device.get('baseUrl') or ''))}{phone_path}",
            method="GET",
            headers={
                **_phone_headers(device, "GET", phone_path, b""),
                "Accept": "application/vnd.luming.h264",
                "X-LUMI-STREAM-TOKEN": str(grant["streamToken"]),
            },
        )

        def chunks():
            try:
                with phone_open(upstream_request, timeout=_UPSTREAM_CONNECT_TIMEOUT_SECONDS) as upstream:
                    while True:
                        chunk = upstream.read(_STREAM_CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk
            except (OSError, TimeoutError):
                return

        return StreamingResponse(
            chunks(),
            media_type="application/vnd.luming.h264",
            headers={
                "Cache-Control": "no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **stream_cors_headers(request),
            },
        )

    @app.delete("/api/phone-stream/devices/{device_id}/session")
    async def stop_phone_stream(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        normalized_id = _normalize_device_id(device_id, "")
        try:
            device = _runtime_device(ctx, normalized_id, runtime_resolver)
        except ValueError:
            return ctx.fastapi_json({"stopped": False, "fallback": "snapshot"})
        account_id = str(account_id_resolver(ctx) or "").strip()
        with _GRANTS_LOCK:
            grant = _UPSTREAM_GRANTS.pop((account_id, normalized_id), None)
        if grant:
            try:
                _phone_json_request(
                    device,
                    "/api/lumi/stream/stop",
                    {"sessionId": grant["sessionId"], "streamToken": grant["streamToken"]},
                    phone_open=phone_open,
                )
            except (OSError, TimeoutError, ValueError):
                pass
        return ctx.fastapi_json({"stopped": bool(grant), "fallback": "snapshot"})
