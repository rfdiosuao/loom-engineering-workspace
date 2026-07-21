"""FastAPI surface for the LOOM central agent workbench."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from typing import Any, Awaitable, Callable

from fastapi import Request
from fastapi.responses import StreamingResponse

from api.routes_realtime import (
    consume_stream_ticket,
    stream_cors_headers,
    stream_preflight_response,
    stream_request_subject,
    stream_ticket_from_request,
)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class AgentServiceUnavailable(RuntimeError):
    pass


def _service(ctx: Any) -> Any:
    getter = getattr(ctx, "get_agent_service", None)
    if callable(getter):
        service = getter()
        if service is not None:
            return service
    service = getattr(ctx, "agent_service", None)
    if service is not None:
        return service
    raise AgentServiceUnavailable("central agent service is not initialized")


async def _invoke(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    value = await asyncio.to_thread(method, *args, **kwargs)
    return await value if inspect.isawaitable(value) else value


def _id(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"invalid {label}")
    return normalized


def _query_int(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {name}") from error
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _error_response(ctx: Any, error: Exception):
    if isinstance(error, KeyError):
        return ctx.fastapi_json({"error": "agent resource not found", "code": "AGENT_NOT_FOUND"}, 404)
    if isinstance(error, AgentServiceUnavailable):
        return ctx.fastapi_json({"error": str(error), "code": "AGENT_SERVICE_UNAVAILABLE"}, 503)
    if isinstance(error, ValueError):
        message = str(error)
        status = 409 if any(token in message.casefold() for token in ("conflict", "transition", "already")) else 400
        return ctx.fastapi_json({"error": message, "code": "AGENT_CONFLICT" if status == 409 else "AGENT_INVALID_REQUEST"}, status)
    return ctx.fastapi_json({"error": "agent operation failed", "code": "AGENT_OPERATION_FAILED"}, 500)


def _sse_event(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: agent\ndata: {payload}\n\n"


def register_agent_routes(app, ctx) -> None:
    async def protected(request: Request, action: Callable[[], Any]):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(await _invoke(action))
        except Exception as error:  # Route boundary maps domain errors to stable responses.
            return _error_response(ctx, error)

    @app.get("/api/agent/bootstrap")
    async def agent_bootstrap(request: Request):
        return await protected(request, lambda: _service(ctx).bootstrap())

    @app.get("/api/agent/sessions")
    async def agent_sessions(request: Request):
        try:
            limit = _query_int(request, "limit", 50, 1, 200)
        except ValueError as error:
            return _error_response(ctx, error)

        def list_visible_sessions():
            page = _service(ctx).list_sessions(
                query=request.query_params.get("query") or None,
                cursor=request.query_params.get("cursor") or None,
                limit=limit,
            )
            return {
                **page,
                "sessions": [
                    session
                    for session in page.get("sessions", [])
                    if isinstance(session, dict) and session.get("status") == "active"
                ],
            }

        return await protected(
            request,
            list_visible_sessions,
        )

    @app.post("/api/agent/sessions")
    async def agent_session_create(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        if not body.get("title"):
            body["title"] = "新对话"
        try:
            session = await _invoke(_service(ctx).create_session, body)
            return ctx.fastapi_json({"session": session})
        except Exception as error:
            return _error_response(ctx, error)

    @app.patch("/api/agent/sessions/{session_id}")
    async def agent_session_update(session_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        try:
            session = await _invoke(_service(ctx).update_session, _id(session_id, "sessionId"), body)
            return ctx.fastapi_json({"session": session})
        except Exception as error:
            return _error_response(ctx, error)

    @app.get("/api/agent/sessions/{session_id}")
    async def agent_session_detail(session_id: str, request: Request):
        try:
            limit = _query_int(request, "limit", 100, 1, 500)
        except ValueError as error:
            return _error_response(ctx, error)
        return await protected(
            request,
            lambda: _service(ctx).session_detail(
                _id(session_id, "sessionId"),
                cursor=request.query_params.get("cursor") or None,
                limit=limit,
            ),
        )

    @app.post("/api/agent/sessions/{session_id}/messages")
    async def agent_send_message(session_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        if not str(body.get("clientMessageId") or "").strip():
            return ctx.fastapi_json({"error": "clientMessageId is required", "code": "AGENT_INVALID_REQUEST"}, 400)
        if not str(body.get("text") or "").strip() and not body.get("attachments"):
            return ctx.fastapi_json({"error": "message text or attachment is required", "code": "AGENT_INVALID_REQUEST"}, 400)
        try:
            result = await _invoke(_service(ctx).send_message, _id(session_id, "sessionId"), body)
            return ctx.fastapi_json(result)
        except Exception as error:
            return _error_response(ctx, error)

    @app.get("/api/agent/runs/{run_id}")
    async def agent_run(run_id: str, request: Request):
        async def action():
            return {"run": await _invoke(_service(ctx).get_run, _id(run_id, "runId"))}

        return await protected(request, action)

    @app.get("/api/agent/runs/{run_id}/trace")
    async def agent_run_trace(run_id: str, request: Request):
        return await protected(request, lambda: _service(ctx).get_trace(_id(run_id, "runId")))

    async def mutate_run(run_id: str, request: Request, method_name: str):
        async def action():
            method = getattr(_service(ctx), method_name)
            return {"run": await _invoke(method, _id(run_id, "runId"))}

        return await protected(request, action)

    @app.post("/api/agent/runs/{run_id}/pause")
    async def agent_run_pause(run_id: str, request: Request):
        return await mutate_run(run_id, request, "pause_run")

    @app.post("/api/agent/runs/{run_id}/resume")
    async def agent_run_resume(run_id: str, request: Request):
        return await mutate_run(run_id, request, "resume_run")

    @app.post("/api/agent/runs/{run_id}/cancel")
    async def agent_run_cancel(run_id: str, request: Request):
        return await mutate_run(run_id, request, "cancel_run")

    @app.post("/api/agent/approvals/{approval_id}")
    async def agent_approval_resolve(approval_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        decision = str(body.get("decision") or "").strip().lower()
        decision = {"approve": "approved", "reject": "rejected"}.get(decision, decision)
        if decision not in {"approved", "rejected"}:
            return ctx.fastapi_json({"error": "decision must approve or reject the action", "code": "AGENT_INVALID_REQUEST"}, 400)
        body["decision"] = decision
        try:
            service = _service(ctx)
            resolver = getattr(service, "queue_approval_resolution", None)
            if not callable(resolver):
                resolver = service.resolve_approval
            result = await _invoke(resolver, _id(approval_id, "approvalId"), body)
            return ctx.fastapi_json(result)
        except Exception as error:
            return _error_response(ctx, error)

    @app.options("/api/agent/events/stream")
    async def agent_events_stream_preflight(request: Request):
        return stream_preflight_response(request)

    @app.get("/api/agent/events/stream")
    async def agent_events_stream(request: Request):
        try:
            session_id = _id(str(request.query_params.get("sessionId") or ""), "sessionId")
            after_seq = _query_int(request, "afterSeq", 0, 0, 2_147_483_647)
        except ValueError as error:
            return _error_response(ctx, error)
        ticket = stream_ticket_from_request(request)
        if consume_stream_ticket(
            ctx,
            ticket,
            topic="agent",
            resource=session_id,
            subject=stream_request_subject(request),
        ) is None:
            return ctx.fastapi_json({"error": "invalid or expired stream ticket"}, 401)
        once = request.query_params.get("once") == "1"

        async def rows():
            committed = after_seq
            last_keepalive = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    events = await _invoke(
                        _service(ctx).events_after,
                        session_id=session_id,
                        after_seq=committed,
                    )
                except Exception:
                    events = []
                if isinstance(events, dict):
                    events = events.get("events", [])
                for event in events if isinstance(events, list) else []:
                    if not isinstance(event, dict):
                        continue
                    seq = int(event.get("seq") or 0)
                    if seq <= committed:
                        continue
                    yield _sse_event(event)
                    committed = seq
                    last_keepalive = time.monotonic()
                if once:
                    break
                if time.monotonic() - last_keepalive >= 15:
                    yield ": keepalive\n\n"
                    last_keepalive = time.monotonic()
                await asyncio.sleep(0.5)

        return StreamingResponse(
            rows(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **stream_cors_headers(request),
            },
        )
