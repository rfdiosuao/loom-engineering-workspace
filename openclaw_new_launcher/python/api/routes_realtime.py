"""Authenticated, short-lived tickets for direct realtime streams."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request, Response

from core.stream_tickets import StreamTicketGrant, StreamTicketIssuer


_ALLOWED_TOPICS = {"agent", "matrix"}
_STREAM_URLS = {
    "agent": "/api/agent/events/stream",
    "matrix": "/api/matrix/events/stream",
}
_MATRIX_RESOURCE = "all"
_AGENT_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TRUSTED_STREAM_HOSTS = {"tauri.localhost", "localhost", "127.0.0.1", "::1"}


def _issuer(ctx: Any) -> StreamTicketIssuer:
    issuer = getattr(ctx, "stream_ticket_issuer", None)
    if isinstance(issuer, StreamTicketIssuer):
        return issuer
    issuer = StreamTicketIssuer(ttl_seconds=30)
    setattr(ctx, "stream_ticket_issuer", issuer)
    return issuer


def stream_request_subject(request: Request) -> str:
    return f"local-ui:{request.client.host if request.client else 'local'}"


def stream_ticket_from_request(request: Request) -> str:
    scheme, separator, credential = str(request.headers.get("authorization") or "").partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return credential.strip()


def stream_cors_headers(request: Request) -> dict[str, str]:
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return {}
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return {}
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold()
    if (
        scheme not in {"http", "https", "tauri"}
        or host not in _TRUSTED_STREAM_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (scheme == "tauri" and (host != "localhost" or port is not None))
    ):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


def stream_preflight_response(request: Request) -> Response:
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Accept",
            "Access-Control-Max-Age": "600",
            **stream_cors_headers(request),
        },
    )


def consume_stream_ticket(
    ctx: Any,
    ticket: str,
    *,
    topic: str,
    resource: str,
    subject: str,
) -> StreamTicketGrant | None:
    """Consume one fully-bound ticket. Streams call this before yielding data."""

    if not ticket or topic not in _ALLOWED_TOPICS or not resource or not subject:
        return None
    return _issuer(ctx).consume(
        ticket,
        topic=topic,
        resource=resource,
        subject=subject,
    )


def register_realtime_routes(app, ctx) -> None:
    @app.post("/api/realtime/tickets")
    async def issue_realtime_ticket(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        topic = str(body.get("topic") or "").strip().lower()
        if topic not in _ALLOWED_TOPICS:
            return ctx.fastapi_json({"error": "topic must be agent or matrix"}, 400)
        resource = str(body.get("resource") or "").strip()
        if topic == "agent" and _AGENT_RESOURCE.fullmatch(resource) is None:
            return ctx.fastapi_json({"error": "resource must be the Agent sessionId"}, 400)
        if topic == "matrix" and resource != _MATRIX_RESOURCE:
            return ctx.fastapi_json({"error": "Matrix resource must be all"}, 400)

        subject = stream_request_subject(request)
        ticket = _issuer(ctx).issue(topic=topic, resource=resource, subject=subject)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        return ctx.fastapi_json(
            {
                "ticket": ticket,
                "expiresAt": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "streamUrl": _STREAM_URLS[topic],
            }
        )
