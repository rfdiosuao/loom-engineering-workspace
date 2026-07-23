"""Matrix control plane FastAPI routes."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import threading
import time

from fastapi import Request
from fastapi.responses import StreamingResponse

from api.routes_phone import (
    _PHONE_OBSERVE_TIMEOUT_SEC,
    _PHONE_SCREENSHOT_REQUEST_TIMEOUT_MS,
    _build_phone_task_plan,
    _ensure_phone_event_syncs_for_saved_devices,
    _phone_args_for_device,
    _phone_stdout_payload,
    _run_phone_process_with_matrix_stream,
    _sanitize_cli_output,
    _script_path,
    _submit_phone_job,
)
from api.routes_realtime import (
    consume_stream_ticket,
    stream_cors_headers,
    stream_preflight_response,
    stream_request_subject,
    stream_ticket_from_request,
)
from core.phone_matrix import MatrixControlPlane, MatrixSafetyError, MatrixTargetError
from core.feishu_integration import FeishuAcquisitionIntegration
from core.acquisition_templates import AcquisitionTemplateLibrary


_MATRIX_STREAM_VOLATILE_KEYS = {
    "updatedAt",
    "heartbeatAt",
    "lastEventAt",
    "streamLatencyMs",
}
_MATRIX_DEFAULT_CONCURRENCY = 4
_MATRIX_MAX_CONCURRENCY = 8
_MATRIX_SCREEN_BATCH_LIMIT = 24
_MATRIX_SCREEN_CAPTURE_GATE = threading.BoundedSemaphore(6)
_MATRIX_DEVICE_LOCKS: dict[str, threading.RLock] = {}
_MATRIX_DEVICE_LOCKS_GUARD = threading.RLock()


def _matrix_device_execution_lock(device_id: str) -> threading.RLock:
    with _MATRIX_DEVICE_LOCKS_GUARD:
        return _MATRIX_DEVICE_LOCKS.setdefault(str(device_id or ""), threading.RLock())


def _matrix_stream_fingerprint(payload: dict) -> str:
    def stable(value):
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in value.items()
                if key not in _MATRIX_STREAM_VOLATILE_KEYS
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    return json.dumps(stable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _matrix_concurrency_limit(body: dict, device_count: int) -> int:
    safe_device_count = max(1, int(device_count or 0))
    requested = body.get("concurrency")
    if requested in (None, ""):
        requested = body.get("maxConcurrency")
    if requested in (None, ""):
        requested = _MATRIX_DEFAULT_CONCURRENCY
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = _MATRIX_DEFAULT_CONCURRENCY
    return max(1, min(value, safe_device_count, _MATRIX_MAX_CONCURRENCY))


def _matrix_execution_is_uncertain(result: dict) -> bool:
    error_code = str(result.get("errorCode") or result.get("code") or "").strip().lower()
    return bool(
        result.get("outcomeIndeterminate") is True
        or result.get("executionMayContinue") is True
        or (error_code == "timeout" and str(result.get("taskId") or "").strip())
    )


def register_matrix_routes(app, ctx) -> None:
    @app.api_route("/api/matrix/status", methods=["GET", "POST"])
    async def matrix_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request) if request.method == "POST" else {}
        campaign_id = str(
            body.get("campaignId")
            or request.query_params.get("campaignId")
            or ""
        ).strip()
        _matrix_event_sync_best_effort(ctx)
        return ctx.fastapi_json(_matrix(ctx).status(campaign_id or None))

    @app.get("/api/matrix/devices/{device_id}/screen")
    async def matrix_device_screen(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        known_hash = str(request.query_params.get("knownHash") or "").strip()
        options = _matrix_screen_capture_options(request.query_params, focused=True)
        try:
            screen = await asyncio.to_thread(_capture_matrix_screen, ctx, device_id, **options)
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)
        return ctx.fastapi_json(_matrix_screen_for_known_hash(screen, known_hash))

    @app.post("/api/matrix/screens")
    async def matrix_device_screens(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        requested = body.get("requests") if isinstance(body, dict) else None
        if not isinstance(requested, list) or not requested:
            return ctx.fastapi_json({"error": "requests must contain at least one device"}, 400)
        if len(requested) > _MATRIX_SCREEN_BATCH_LIMIT:
            return ctx.fastapi_json({"error": f"requests cannot exceed {_MATRIX_SCREEN_BATCH_LIMIT} devices"}, 400)

        async def capture(item: object) -> tuple[str, dict]:
            if not isinstance(item, dict):
                return "error", {
                    "deviceId": "",
                    "errorCode": "matrix_screen_request_invalid",
                    "error": "Invalid screenshot request",
                }
            device_id = str(item.get("deviceId") or "").strip()
            if not device_id:
                return "error", {
                    "deviceId": "",
                    "errorCode": "matrix_screen_request_invalid",
                    "error": "deviceId is required",
                }
            options = _matrix_screen_capture_options(item, focused=item.get("focused") is True)
            try:
                screen = await asyncio.to_thread(_capture_matrix_screen, ctx, device_id, **options)
                return "screen", _matrix_screen_for_known_hash(
                    screen,
                    str(item.get("knownHash") or "").strip(),
                )
            except MatrixTargetError as exc:
                return "error", {
                    "deviceId": device_id,
                    "errorCode": exc.code,
                    "error": exc.message,
                }
            except Exception as exc:
                return "error", {
                    "deviceId": device_id,
                    "errorCode": "matrix_screen_unavailable",
                    "error": _redact_matrix_output(str(exc) or "Phone screenshot failed")[:300],
                }

        results = await asyncio.gather(*(capture(item) for item in requested))
        return ctx.fastapi_json({
            "schema": "loom.matrix.screens.v1",
            "screens": [payload for kind, payload in results if kind == "screen"],
            "errors": [payload for kind, payload in results if kind == "error"],
        })

    @app.get("/api/matrix/devices/{device_id}/timeline")
    async def matrix_device_timeline(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            limit = int(request.query_params.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        try:
            return ctx.fastapi_json(_matrix(ctx).timeline(device_id, limit=limit))
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)

    @app.api_route("/api/matrix/devices/{device_id}/lease", methods=["GET", "POST", "DELETE"])
    async def matrix_device_lease(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        matrix = _matrix(ctx)
        try:
            if request.method == "GET":
                return ctx.fastapi_json(matrix.get_lease(device_id))
            body = await ctx.body(request)
            if request.method == "POST":
                device_task_id = str(body.get("deviceTaskId") or "").strip()
                if device_task_id:
                    return ctx.fastapi_json(matrix.takeover_task(device_id, device_task_id, body))
                return ctx.fastapi_json({"lease": matrix.acquire_lease(device_id, body)})
            lease_id = str(body.get("leaseId") or "").strip()
            if not lease_id:
                return ctx.fastapi_json({"error": "leaseId is required", "code": "matrix_invalid_lease"}, 400)
            released = matrix.release_lease(device_id, lease_id)
            resumed_task_id = str(released.get("resumedDeviceTaskId") or "")
            if resumed_task_id:
                job = _submit_matrix_resume_job(ctx, matrix, resumed_task_id)
                released.update({"jobId": job.get("id"), "job": job})
            return ctx.fastapi_json(released)
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)

    @app.post("/api/matrix/devices/{device_id}/control")
    async def matrix_device_control(device_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        matrix = _matrix(ctx)
        try:
            command = _normalize_matrix_control_request(body)
            claim = await asyncio.to_thread(
                _execute_matrix_manual_control_serialized,
                ctx,
                matrix,
                device_id,
                command,
            )
            if not claim["created"]:
                return ctx.fastapi_json(claim["result"])
            completed = claim["result"]
            matrix.append_runtime_event(
                "manual.control",
                device_id,
                f"Manual {command['action']} command {completed.get('status') or 'completed'}",
                source="matrix.control",
                details={
                    "action": command["action"],
                    "clientCommandId": command["clientCommandId"],
                    "status": completed.get("status"),
                },
            )
            return ctx.fastapi_json(completed)
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)

    @app.post("/api/matrix/tasks/{device_task_id}/pause")
    async def matrix_task_pause(device_task_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            body = await ctx.body(request)
            return ctx.fastapi_json(
                _matrix(ctx).pause_task(
                    device_task_id,
                    lease_id=str(body.get("leaseId") or "").strip(),
                )
            )
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)

    @app.post("/api/matrix/tasks/{device_task_id}/resume")
    async def matrix_task_resume(device_task_id: str, request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            matrix = _matrix(ctx)
            resumed = matrix.resume_task(device_task_id)
            job = _submit_matrix_resume_job(ctx, matrix, device_task_id)
            return ctx.fastapi_json({**resumed, "jobId": job.get("id"), "job": job})
        except MatrixTargetError as exc:
            return _matrix_target_error_response(ctx, exc)

    @app.post("/api/matrix/device/register")
    async def matrix_device_register(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device = _matrix(ctx).register_device(body)
        return ctx.fastapi_json({"device": device, "status": _matrix(ctx).status()})

    @app.post("/api/matrix/dispatch")
    async def matrix_dispatch(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        matrix = _matrix(ctx)
        try:
            task = matrix.dispatch(body)
        except MatrixSafetyError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 403)
        except MatrixTargetError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 409)

        def run(job_id: str) -> dict:
            ctx.get_job_mgr().progress(
                job_id,
                "Matrix 任务已开始执行",
                "neutral",
                phase="matrix.dispatch.running",
                commandId="matrix.dispatch",
                campaignId=task.get("campaignId"),
            )
            return _run_matrix_campaign(ctx, matrix, task, body, job_id)

        job = ctx.get_job_mgr().submit_progress(
            "matrix.dispatch",
            "Matrix 任务派发",
            run,
            initial_progress={
                "message": "Matrix 任务已排队",
                "phase": "matrix.dispatch.queued",
                "commandId": "matrix.dispatch",
                "campaignId": task.get("campaignId"),
                **_matrix_job_scope(task),
            },
        )
        return ctx.fastapi_json({"jobId": job.get("id"), "job": job, "task": task, "status": matrix.status()}, 202)

    @app.api_route("/api/matrix/watch", methods=["GET", "POST"])
    async def matrix_watch(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request) if request.method == "POST" else {}
        campaign_id = str(body.get("campaignId") or request.query_params.get("campaignId") or "").strip()
        limit_raw = body.get("limit") or request.query_params.get("limit") or 100
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 100
        return ctx.fastapi_json(_matrix(ctx).watch(campaign_id or None, limit=limit))

    @app.options("/api/matrix/events/stream")
    async def matrix_events_stream_preflight(request: Request):
        return stream_preflight_response(request)

    @app.get("/api/matrix/events/stream")
    async def matrix_events_stream(request: Request):
        once = str(request.query_params.get("once") or "").strip() == "1"
        unified = str(request.query_params.get("unified") or "").strip() == "1"
        try:
            interval_ms = int(request.query_params.get("intervalMs") or 1000)
        except (TypeError, ValueError):
            interval_ms = 1000
        interval_ms = max(300, min(5000, interval_ms))

        ticket = stream_ticket_from_request(request)
        if consume_stream_ticket(
            ctx,
            ticket,
            topic="matrix",
            resource="all",
            subject=stream_request_subject(request),
        ) is None:
            return ctx.fastapi_json(
                {"error": "A valid one-time Matrix stream ticket is required", "code": "stream_ticket_invalid"},
                401,
            )
        _matrix_event_sync_best_effort(ctx)
        try:
            after_seq = max(0, int(request.query_params.get("afterSeq") or 0))
        except (TypeError, ValueError):
            after_seq = 0

        async def event_rows():
            matrix = _matrix(ctx)
            cursor = after_seq
            last_emit_at = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                events = matrix.realtime_events(after_seq=cursor, limit=500)
                now = time.monotonic()
                for event in events:
                    yield _sse_event("matrix", event)
                    cursor = max(cursor, int(event.get("seq") or cursor))
                    last_emit_at = now
                if not events and now - last_emit_at >= 15:
                    yield ": keepalive\n\n"
                    last_emit_at = now
                if once:
                    break
                await asyncio.sleep(interval_ms / 1000)

        return StreamingResponse(
            event_rows(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **stream_cors_headers(request),
            },
        )

    @app.post("/api/matrix/cancel")
    async def matrix_cancel(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        job_manager = ctx.get_job_mgr()
        if body.get("all") is True:
            job_ids = job_manager.cancel_matching(
                lambda job: str(job.get("kind") or "").startswith("matrix.")
            )
            result = _matrix(ctx).cancel_all()
            result["cancelledJobIds"] = job_ids
            return ctx.fastapi_json(result)
        campaign_id = str(body.get("campaignId") or body.get("id") or "").strip()
        if not campaign_id:
            return ctx.fastapi_json({"error": "campaignId is required"}, 400)
        job_ids = job_manager.cancel_matching(
            lambda job: str((job.get("progress") or {}).get("campaignId") or "") == campaign_id
        )
        result = _matrix(ctx).cancel(campaign_id)
        result["cancelledJobIds"] = job_ids
        return ctx.fastapi_json(result)

    @app.post("/api/matrix/emergency-stop")
    async def matrix_emergency_stop(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        scope_keys = [
            key
            for key in ("all", "campaignId", "deviceIds", "deviceTaskIds")
            if key in body
        ]
        if len(scope_keys) != 1:
            return ctx.fastapi_json({"error": "exactly one emergency-stop scope is required"}, 400)

        scope_key = scope_keys[0]
        all_tasks = scope_key == "all" and body.get("all") is True
        campaign_id = str(body.get("campaignId") or "").strip() if scope_key == "campaignId" else ""
        if "campaignAtomic" in body and not isinstance(body.get("campaignAtomic"), bool):
            return ctx.fastapi_json({"error": "campaignAtomic must be a boolean"}, 400)
        campaign_atomic = body.get("campaignAtomic") is True

        def string_set(value) -> set[str]:
            if not isinstance(value, list):
                return set()
            return {item.strip() for item in value if isinstance(item, str) and item.strip()}

        device_ids = string_set(body.get("deviceIds")) if scope_key == "deviceIds" else set()
        device_task_ids = string_set(body.get("deviceTaskIds")) if scope_key == "deviceTaskIds" else set()
        valid_scope = (
            all_tasks
            or bool(campaign_id)
            or bool(device_ids)
            or bool(device_task_ids)
        )
        if not valid_scope:
            return ctx.fastapi_json({"error": "emergency-stop scope must not be empty"}, 400)

        result = _matrix(ctx).emergency_stop(
            all_tasks=all_tasks,
            campaign_id=campaign_id,
            device_ids=device_ids,
            device_task_ids=device_task_ids,
            campaign_atomic=campaign_atomic,
        )
        job_ids = ctx.get_job_mgr().cancel_matching(
            lambda job: _matrix_job_matches_emergency_scope(
                job,
                result,
                scope_key=scope_key,
                campaign_atomic=campaign_atomic,
            ),
            wait_for_workers=False,
        )
        result["scope"] = {
            "all": "all",
            "campaignId": "campaign",
            "deviceIds": "devices",
            "deviceTaskIds": "deviceTasks",
        }[scope_key]
        result["cancelledJobIds"] = sorted(job_ids)
        return ctx.fastapi_json(result)

    @app.post("/api/matrix/retry")
    async def matrix_retry(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        campaign_id = str(body.get("campaignId") or body.get("id") or "").strip()
        if not campaign_id:
            return ctx.fastapi_json({"error": "campaignId is required"}, 400)
        matrix = _matrix(ctx)
        try:
            retry = matrix.retry_failed(campaign_id, body)
        except MatrixSafetyError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 403)
        except MatrixTargetError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 409)
        task = retry.get("task") if isinstance(retry.get("task"), dict) else None
        dispatch_body = retry.get("dispatchBody") if isinstance(retry.get("dispatchBody"), dict) else body
        if not task:
            return ctx.fastapi_json({"retry": retry, "status": matrix.status()})

        def run(job_id: str) -> dict:
            ctx.get_job_mgr().progress(
                job_id,
                "Matrix 重试任务已开始执行",
                "neutral",
                phase="matrix.retry.running",
                commandId="matrix.retry",
                campaignId=task.get("campaignId"),
            )
            return _run_matrix_campaign(ctx, matrix, task, dispatch_body, job_id)

        job = ctx.get_job_mgr().submit_progress(
            "matrix.retry",
            "Matrix 任务重试",
            run,
            initial_progress={
                "message": "Matrix 重试任务已排队",
                "phase": "matrix.retry.queued",
                "commandId": "matrix.retry",
                "campaignId": task.get("campaignId"),
                "retryOf": campaign_id,
                **_matrix_job_scope(task),
            },
        )
        return ctx.fastapi_json({"jobId": job.get("id"), "job": job, "retry": retry, "status": matrix.status()}, 202)

    @app.api_route("/api/matrix/leads", methods=["GET", "POST"])
    async def matrix_leads(request: Request):
        if error := ctx.auth_error(request):
            return error
        matrix = _matrix(ctx)
        if request.method == "GET":
            try:
                limit = int(request.query_params.get("limit") or 100)
            except (TypeError, ValueError):
                limit = 100
            return ctx.fastapi_json(matrix.list_leads(limit=limit))
        body = await ctx.body(request)
        return ctx.fastapi_json({"lead": matrix.record_lead(body), "leads": matrix.list_leads(limit=20)})

    @app.api_route("/api/matrix/acquisition", methods=["GET", "POST"])
    async def matrix_acquisition(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_matrix(ctx).acquisition_snapshot())

    @app.post("/api/matrix/acquisition/demo")
    async def matrix_acquisition_demo(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        matrix = _matrix(ctx)
        flow = matrix.create_acquisition_demo_flow(body)
        return ctx.fastapi_json({"flow": flow, "snapshot": matrix.acquisition_snapshot()}, 201)

    @app.post("/api/matrix/acquisition/import")
    async def matrix_acquisition_import(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        matrix = _matrix(ctx)
        result = matrix.import_acquisition_leads(body)
        return ctx.fastapi_json({"result": result, "snapshot": matrix.acquisition_snapshot()}, 201)

    @app.post("/api/matrix/acquisition/agent/run")
    async def matrix_acquisition_agent_run(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        result = _matrix(ctx).run_acquisition_agent_task(body)
        return ctx.fastapi_json(result, 201)

    @app.post("/api/matrix/acquisition/agent/result")
    async def matrix_acquisition_agent_result(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        agent_result = body.get("agentResult") if isinstance(body.get("agentResult"), dict) else None
        if not agent_result:
            return ctx.fastapi_json({"error": "agentResult is required"}, 400)
        matrix = _matrix(ctx)
        ingest = matrix.ingest_acquisition_agent_result(agent_result, body)
        return ctx.fastapi_json({"ingest": ingest, "snapshot": matrix.acquisition_snapshot()}, 201)

    @app.post("/api/matrix/acquisition/draft/confirm")
    async def matrix_acquisition_draft_confirm(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        draft_id = str(body.get("draftId") or body.get("id") or "").strip()
        if not draft_id:
            return ctx.fastapi_json({"error": "draftId is required"}, 400)
        result = _matrix(ctx).confirm_acquisition_draft(draft_id, body)
        status = 404 if result.get("error") else 200
        return ctx.fastapi_json(result, status)

    @app.post("/api/matrix/acquisition/draft/manual-send")
    async def matrix_acquisition_draft_manual_send(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        draft_id = str(body.get("draftId") or body.get("id") or "").strip()
        if not draft_id:
            return ctx.fastapi_json({"error": "draftId is required"}, 400)
        result = _matrix(ctx).record_acquisition_manual_send(draft_id, body)
        status = 404 if result.get("error") else 200
        return ctx.fastapi_json(result, status)

    @app.api_route("/api/matrix/acquisition/templates", methods=["GET", "POST"])
    async def matrix_acquisition_templates(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_templates(ctx).status())

    @app.post("/api/matrix/acquisition/templates/save")
    async def matrix_acquisition_template_save(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        return ctx.fastapi_json(_templates(ctx).save_from_acquisition(body), 201)

    @app.post("/api/matrix/acquisition/templates/upload")
    async def matrix_acquisition_template_upload(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        template_id = str(body.get("templateId") or body.get("id") or "").strip()
        if not template_id:
            return ctx.fastapi_json({"error": "templateId is required"}, 400)
        return ctx.fastapi_json(_templates(ctx).upload_template(template_id))

    @app.post("/api/matrix/acquisition/templates/retry")
    async def matrix_acquisition_template_retry(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_templates(ctx).retry_pending())

    @app.post("/api/matrix/acquisition/templates/cloud-consent")
    async def matrix_acquisition_template_cloud_consent(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        enabled = body.get("enabled") is True
        library = _templates(ctx)
        status = library.set_cloud_consent(enabled)
        result = {"cloud": status.get("cloud", {}), "status": status}
        if enabled and body.get("retryPending") is True:
            result["retry"] = library.retry_pending()
        return ctx.fastapi_json(result)

    @app.api_route("/api/matrix/acquisition/feishu/doctor", methods=["GET", "POST"])
    async def matrix_acquisition_feishu_doctor(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_feishu(ctx).doctor())

    @app.api_route("/api/matrix/acquisition/feishu/status", methods=["GET", "POST"])
    async def matrix_acquisition_feishu_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_feishu(ctx).status())

    @app.post("/api/matrix/acquisition/feishu/install")
    async def matrix_acquisition_feishu_install(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        if not bool(body.get("confirmed")):
            return ctx.fastapi_json(_feishu(ctx).install_cli(confirmed=False), 202)
        return ctx.fastapi_json(_feishu(ctx).install_cli(confirmed=True))

    @app.post("/api/matrix/acquisition/feishu/login")
    async def matrix_acquisition_feishu_login(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(_feishu(ctx).start_login())
        except RuntimeError as exc:
            return ctx.fastapi_json({"ok": False, "error": str(exc)}, 400)

    @app.post("/api/matrix/acquisition/feishu/bind-table")
    async def matrix_acquisition_feishu_bind_table(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        return ctx.fastapi_json(_feishu(ctx).bind_table(body))

    @app.post("/api/matrix/acquisition/feishu/create-table")
    async def matrix_acquisition_feishu_create_table(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        return ctx.fastapi_json(_feishu(ctx).create_table(confirmed=bool(body.get("confirmed"))))

    @app.post("/api/matrix/acquisition/feishu/test-write")
    async def matrix_acquisition_feishu_test_write(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_feishu(ctx).test_write())

    @app.post("/api/matrix/acquisition/feishu/retry-sync")
    async def matrix_acquisition_feishu_retry_sync(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_feishu(ctx).retry_pending())

    @app.post("/api/matrix/acquisition/feishu/reconcile")
    async def matrix_acquisition_feishu_reconcile(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_feishu(ctx).reconcile())

    @app.post("/api/matrix/template/run")
    async def matrix_template_run(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        template = str(body.get("template") or body.get("templateId") or "read-screen").strip()
        prompt = _template_prompt(template)
        payload = {
            **body,
            "template": template,
            "prompt": str(body.get("prompt") or prompt),
            "mode": str(body.get("mode") or ("observe" if template in {"read-screen", "screen-summary"} else "safe")),
            "profile": str(body.get("profile") or "fast"),
        }
        matrix = _matrix(ctx)
        try:
            task = matrix.dispatch(payload)
        except MatrixSafetyError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 403)
        except MatrixTargetError as exc:
            return ctx.fastapi_json({"error": exc.message, "code": exc.code}, 409)

        def run(job_id: str) -> dict:
            ctx.get_job_mgr().progress(
                job_id,
                "Matrix 模板任务已开始执行",
                "neutral",
                phase="matrix.template.running",
                commandId="matrix.template.run",
                campaignId=task.get("campaignId"),
            )
            return _run_matrix_campaign(ctx, matrix, task, payload, job_id)

        job = ctx.get_job_mgr().submit_progress(
            "matrix.template.run",
            "Matrix 模板任务",
            run,
            initial_progress={
                "message": "Matrix 模板任务已排队",
                "phase": "matrix.template.queued",
                "commandId": "matrix.template.run",
                "campaignId": task.get("campaignId"),
                **_matrix_job_scope(task),
            },
        )
        return ctx.fastapi_json(
            {"jobId": job.get("id"), "job": job, "task": task, "status": matrix.status()},
            202,
        )

    @app.api_route("/api/matrix/experience", methods=["GET", "POST"])
    async def matrix_experience(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(_matrix(ctx).experience_report())


def _matrix_job_matches_emergency_scope(
    job: dict,
    result: dict,
    *,
    scope_key: str,
    campaign_atomic: bool,
) -> bool:
    if not str(job.get("kind") or "").startswith("matrix."):
        return False
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    campaign_id = str(progress.get("campaignId") or "")
    matched_campaign_ids = {
        str(item) for item in result.get("matchedCampaignIds", []) if str(item)
    }
    if scope_key == "all":
        return True
    if scope_key == "campaignId" or campaign_atomic:
        return campaign_id in matched_campaign_ids

    fully_stopped_campaign_ids = {
        str(item) for item in result.get("fullyStoppedCampaignIds", []) if str(item)
    }
    if campaign_id and campaign_id in fully_stopped_campaign_ids:
        return True
    matched_task_ids = {
        str(item) for item in result.get("matchedDeviceTaskIds", []) if str(item)
    }
    if not matched_task_ids:
        matched_task_ids = {
            str(item.get("deviceTaskId") or "")
            for item in result.get("affected", [])
            if isinstance(item, dict) and str(item.get("deviceTaskId") or "")
        }
    raw_job_task_ids = progress.get("matrixDeviceTaskIds")
    job_task_ids = {
        str(item) for item in raw_job_task_ids if str(item)
    } if isinstance(raw_job_task_ids, list) else set()
    if not job_task_ids and str(job.get("kind") or "") == "matrix.resume":
        device_task_id = str(progress.get("deviceTaskId") or "")
        if device_task_id:
            job_task_ids.add(device_task_id)
    return bool(job_task_ids and job_task_ids.issubset(matched_task_ids))


def _matrix(ctx) -> MatrixControlPlane:
    return MatrixControlPlane(ctx.paths)


def _submit_matrix_resume_job(ctx, matrix: MatrixControlPlane, device_task_id: str) -> dict:
    execution = matrix.task_execution_context(device_task_id)

    def run(job_id: str) -> dict:
        return _run_matrix_device_task(
            ctx,
            matrix,
            execution["body"],
            execution["deviceTask"],
            job_id,
        )

    device_id = str(execution["deviceTask"].get("deviceId") or "")
    return ctx.get_job_mgr().submit_progress(
        "matrix.resume",
        "Resume Matrix device task",
        run,
        initial_progress={
            "message": "Matrix device task queued for resume",
            "phase": "matrix.resume.queued",
            "commandId": "matrix.resume",
            "campaignId": execution["campaignId"],
            "deviceTaskId": device_task_id,
            "deviceId": device_id,
            "matrixDeviceTaskIds": [device_task_id],
            "matrixDeviceIds": [device_id],
        },
    )


def _matrix_target_error_response(ctx, exc: MatrixTargetError):
    if exc.code in {"matrix_target_not_found", "matrix_task_not_found"}:
        status = 404
    elif exc.code in {"matrix_invalid_lease", "matrix_invalid_control"}:
        status = 400
    else:
        status = 409
    return ctx.fastapi_json({"error": exc.message, "code": exc.code}, status)


def _normalize_matrix_control_request(raw: dict) -> dict:
    lease_id = str(raw.get("leaseId") or "").strip()
    client_command_id = str(raw.get("clientCommandId") or "").strip()
    action = str(raw.get("action") or "").strip().lower()
    if not lease_id:
        raise MatrixTargetError("matrix_invalid_control", "leaseId is required")
    if not client_command_id:
        raise MatrixTargetError("matrix_invalid_control", "clientCommandId is required")
    if action not in {"tap", "swipe", "input_text", "back", "home", "recent", "screenshot", "rotate"}:
        raise MatrixTargetError("matrix_invalid_control", "Unsupported Matrix control action")
    command = {
        "leaseId": lease_id[:100],
        "clientCommandId": client_command_id[:200],
        "action": action,
    }

    def coordinate(name: str) -> float:
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MatrixTargetError("matrix_invalid_control", f"{name} must be a normalized number")
        number = float(value)
        if number < 0 or number > 1:
            raise MatrixTargetError("matrix_invalid_control", f"{name} must be between 0 and 1")
        return number

    if action in {"tap", "swipe"}:
        command["x"] = coordinate("x")
        command["y"] = coordinate("y")
    if action == "swipe":
        command["endX"] = coordinate("endX")
        command["endY"] = coordinate("endY")
        duration = raw.get("durationMs", 300)
        if isinstance(duration, bool) or not isinstance(duration, int) or not 50 <= duration <= 10_000:
            raise MatrixTargetError("matrix_invalid_control", "durationMs must be an integer from 50 to 10000")
        command["durationMs"] = duration
    if action == "input_text":
        text = raw.get("text")
        if not isinstance(text, str) or not text or len(text) > 2000:
            raise MatrixTargetError("matrix_invalid_control", "text must be a non-empty string of at most 2000 characters")
        command["text"] = text
    return command


def _execute_matrix_manual_control_serialized(
    ctx,
    matrix: MatrixControlPlane,
    device_id: str,
    command: dict,
) -> dict:
    with _matrix_device_execution_lock(device_id):
        lease = matrix.require_lease(
            device_id,
            command["leaseId"],
            holder_type="human",
        )
        claim = matrix.begin_control_command(
            device_id,
            command["clientCommandId"],
            command,
            lease=lease,
        )
        if not claim["created"]:
            return claim
        matrix.require_lease(
            device_id,
            command["leaseId"],
            holder_type="human",
            holder_id=str(lease.get("holderId") or ""),
        )
        result = _execute_matrix_manual_action(ctx, device_id, command)
        completed = matrix.complete_control_command(device_id, command["clientCommandId"], result)
        return {"created": True, "result": completed}


def _execute_matrix_manual_action(ctx, device_id: str, command: dict) -> dict:
    command_id = str(command.get("clientCommandId") or "")
    if command.get("action") == "screenshot":
        try:
            screen = _capture_matrix_screen(ctx, device_id)
        except MatrixTargetError as exc:
            return {
                "status": "failed",
                "commandId": command_id,
                "code": exc.code,
                "error": exc.message,
            }
        return {
            "status": "applied",
            "commandId": command_id,
            "screen": screen,
        }
    action = str(command.get("action") or "")
    if action == "tap":
        action_body = {"action": "tap", "nx": command["x"], "ny": command["y"]}
    elif action == "swipe":
        action_body = {
            "action": "swipe",
            "start": {"nx": command["x"], "ny": command["y"]},
            "end": {"nx": command["endX"], "ny": command["endY"]},
            "durationMs": command["durationMs"],
        }
    elif action in {"back", "home"}:
        action_body = {"action": action}
    elif action == "recent":
        return {
            "status": "failed",
            "commandId": command_id,
            "code": "matrix_control_unsupported",
            "error": "当前手机控制协议暂不支持最近任务，请直接在手机界面操作。",
        }
    elif action == "input_text":
        action_body = {"action": "input_text", "text": command["text"]}
    else:
        action_body = {"action": action}
    if action in {"tap", "swipe"}:
        action_body.update(
            {
                "targetLabel": "manual normalized control",
                "reason": "User holds the active Matrix device lease",
            }
        )
    try:
        plan = _build_phone_task_plan(
            ctx,
            {"mode": "safe", "profile": "fast", "actionBody": action_body},
            device_id=device_id,
        )
        result = _submit_phone_job(
            ctx,
            inline_job_id=f"matrix-control-{command_id}",
            **plan,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "commandId": command_id,
            "error": _redact_matrix_output(str(exc))[:300],
        }
    response = {
        "status": "applied" if result.get("success") is True else "failed",
        "commandId": command_id,
        "result": {
            "success": result.get("success") is True,
            "errorCode": str(result.get("errorCode") or result.get("code") or ""),
            "currentStep": str(result.get("currentStep") or ""),
        },
    }
    if isinstance(result.get("metrics"), dict):
        response["result"]["metrics"] = _redact_matrix_json(result["metrics"])
    if result.get("success") is not True:
        response["error"] = _redact_matrix_output(str(result.get("error") or "Device control failed"))[:300]
    return response


def _matrix_screen_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _matrix_screen_capture_options(source, *, focused: bool) -> dict:
    quality_default = 62 if focused else 48
    long_side_default = 960 if focused else 640
    cache_default = 700 if focused else 1200
    return {
        "quality": _matrix_screen_int(source.get("quality"), default=quality_default, minimum=35, maximum=85),
        "max_long_side": _matrix_screen_int(
            source.get("maxLongSide") or source.get("max_long_side"),
            default=long_side_default,
            minimum=480,
            maximum=1280,
        ),
        "cache_ttl_ms": _matrix_screen_int(
            source.get("cacheTtlMs") or source.get("cache_ttl_ms"),
            default=cache_default,
            minimum=250,
            maximum=5000,
        ),
    }


def _matrix_screen_for_known_hash(screen: dict, known_hash: str) -> dict:
    if known_hash and known_hash == screen.get("screenHash"):
        unchanged = {key: value for key, value in screen.items() if key != "image"}
        unchanged["notModified"] = True
        return unchanged
    return screen


def _capture_matrix_screen(
    ctx,
    device_id: str,
    *,
    quality: int = 62,
    max_long_side: int = 960,
    cache_ttl_ms: int = 700,
) -> dict:
    script_path = _script_path(ctx, "openclaw-phone-vision.mjs")
    node_exe = str(getattr(ctx.paths, "node_exe", "") or "")
    if not os.path.exists(script_path):
        raise MatrixTargetError("matrix_screen_unavailable", "Phone screenshot capability is unavailable")
    if not node_exe or not os.path.exists(node_exe):
        raise MatrixTargetError("matrix_screen_unavailable", "Node.js runtime is unavailable")
    args = _phone_args_for_device(
        [
            "frame",
            "--quality",
            str(_matrix_screen_int(quality, default=62, minimum=35, maximum=85)),
            "--max-long-side",
            str(_matrix_screen_int(max_long_side, default=960, minimum=480, maximum=1280)),
            "--no-grid",
            "--frame-timeout-ms",
            str(_PHONE_SCREENSHOT_REQUEST_TIMEOUT_MS),
            "--cache-ttl-ms",
            str(_matrix_screen_int(cache_ttl_ms, default=700, minimum=250, maximum=5000)),
            "--json",
        ],
        device_id,
    )
    with _MATRIX_SCREEN_CAPTURE_GATE:
        process = _run_phone_process_with_matrix_stream(
            ctx,
            [node_exe, script_path, *args],
            kind="phone.screenshot",
            layer="direct",
            timeout_sec=_PHONE_OBSERVE_TIMEOUT_SEC,
            device_id=device_id,
        )
    if process.get("returncode") != 0:
        error = _redact_matrix_output(process.get("stderr") or "Phone screenshot failed")[:300]
        raise MatrixTargetError("matrix_screen_unavailable", error)
    payload = _last_json_object(process.get("stdout") or "")
    if isinstance(payload.get("data"), dict) and not isinstance(payload.get("frame"), dict):
        payload = payload["data"]
    frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else {}
    image_info = frame.get("image") if isinstance(frame.get("image"), dict) else {}
    encoded_image = str(image_info.get("base64") or "").strip()
    file_path = str(payload.get("filePath") or "").strip()
    if not encoded_image and file_path:
        resolved_path = file_path if os.path.isabs(file_path) else os.path.join(ctx.paths.base_path, file_path)
        try:
            with open(resolved_path, "rb") as handle:
                encoded_image = base64.b64encode(handle.read()).decode("ascii")
        except OSError as exc:
            raise MatrixTargetError("matrix_screen_unavailable", "Captured screen file is unavailable") from exc
    if not encoded_image:
        raise MatrixTargetError("matrix_screen_unavailable", "Phone screenshot did not include an image")
    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (ValueError, TypeError) as exc:
        raise MatrixTargetError("matrix_screen_unavailable", "Phone screenshot image is invalid") from exc
    width = int(frame.get("width") or image_info.get("width") or 0)
    height = int(frame.get("height") or image_info.get("height") or 0)
    if width < 1 or height < 1:
        raise MatrixTargetError("matrix_screen_unavailable", "Phone screenshot dimensions are invalid")
    raw_hash = str(frame.get("screenHash") or payload.get("screenHash") or "").strip()
    screen_hash = raw_hash if raw_hash.startswith("sha256:") else f"sha256:{raw_hash or hashlib.sha256(image_bytes).hexdigest()}"
    _sync_matrix_screen_presence(ctx, device_id, frame)
    return {
        "schema": "loom.matrix.screen.v1",
        "deviceId": str(device_id),
        "capturedAt": str(frame.get("capturedAt") or frame.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        "screenHash": screen_hash,
        "mime": str(image_info.get("mime") or frame.get("mime") or "image/jpeg"),
        "width": width,
        "height": height,
        "image": encoded_image,
        "notModified": False,
    }


def _sync_matrix_screen_presence(ctx, device_id: str, frame: dict) -> None:
    current_screen = frame.get("currentScreen") if isinstance(frame.get("currentScreen"), dict) else {}
    screen = current_screen.get("screen") if isinstance(current_screen.get("screen"), dict) else {}
    current_package = str(
        screen.get("currentPackage")
        or current_screen.get("packageName")
        or current_screen.get("foregroundPackageName")
        or ""
    ).strip()
    foreground_app = str(screen.get("currentApp") or current_screen.get("currentApp") or "").strip()
    if not current_package and not foreground_app:
        return
    now = time.time()
    milliseconds = int(now * 1000) % 1000
    observed_at = f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now))}.{milliseconds:03d}+00:00"
    update = {
        "deviceId": str(device_id),
        "online": True,
        "heartbeatAt": observed_at,
        "lastEventAt": observed_at,
        "presenceObservedAt": observed_at,
    }
    if current_package:
        update["currentPackage"] = current_package
        update["foregroundApp"] = foreground_app
    elif foreground_app:
        update["foregroundApp"] = foreground_app
    try:
        MatrixControlPlane(ctx.paths).register_device(update)
    except Exception:
        return


def _last_json_object(stdout: str) -> dict:
    payload = _phone_stdout_payload(stdout)
    if payload:
        return payload
    raise MatrixTargetError("matrix_screen_unavailable", "Phone screenshot returned no JSON payload")


def _feishu(ctx) -> FeishuAcquisitionIntegration:
    return FeishuAcquisitionIntegration(ctx.paths)


def _templates(ctx) -> AcquisitionTemplateLibrary:
    return AcquisitionTemplateLibrary(ctx.paths)


def _matrix_event_sync_best_effort(ctx) -> dict:
    try:
        return _ensure_phone_event_syncs_for_saved_devices(ctx)
    except Exception as exc:
        return {"started": False, "devices": [], "error": str(exc)[:200]}


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_matrix_campaign(ctx, matrix: MatrixControlPlane, task: dict, body: dict, job_id: str) -> dict:
    started = time.monotonic()
    device_tasks = _matrix_device_tasks(task)
    if not device_tasks:
        return {
            "success": False,
            "task": task,
            "status": matrix.status(),
            "error": "没有可执行的目标手机，请重新检测连接后再发布任务。",
        }
    concurrency = _matrix_concurrency_limit(body, len(device_tasks))
    results_by_index: dict[int, dict] = {}
    ctx.get_job_mgr().progress(
        job_id,
        f"已并发启动 {len(device_tasks)} 台手机",
        "neutral",
        phase="matrix.dispatch.concurrent",
        commandId="matrix.dispatch",
        campaignId=task.get("campaignId"),
        concurrency=concurrency,
        deviceCount=len(device_tasks),
        completedDevices=0,
    )
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="loom-matrix") as executor:
        future_rows = {
            executor.submit(_run_matrix_device_task_if_active, ctx, matrix, body, device_task, job_id): (index, device_task)
            for index, device_task in enumerate(device_tasks)
        }
        completed_count = 0
        for future in as_completed(future_rows):
            index, device_task = future_rows[future]
            device_id = str(device_task.get("deviceId") or "")
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "success": False,
                    "assignmentId": str(device_task.get("assignmentId") or ""),
                    "deviceTaskId": str(device_task.get("deviceTaskId") or ""),
                    "deviceId": device_id,
                    "durationMs": 0,
                    "error": _redact_matrix_output(str(exc))[:300] or "手机矩阵并发执行失败",
                }
            results_by_index[index] = result
            completed_count += 1
            ctx.get_job_mgr().progress(
                job_id,
                f"{device_id or index + 1} 执行完成",
                "success" if result.get("success") else "danger",
                phase="matrix.dispatch.device.done",
                commandId="matrix.dispatch",
                campaignId=task.get("campaignId"),
                deviceTaskId=device_task.get("deviceTaskId"),
                deviceId=device_id,
                concurrency=concurrency,
                deviceCount=len(device_tasks),
                completedDevices=completed_count,
            )
    results = [results_by_index[index] for index in range(len(device_tasks))]
    ok = all(item.get("success") for item in results)
    failed_devices = [
        {
            "deviceId": str(item.get("deviceId") or ""),
            "deviceTaskId": str(item.get("deviceTaskId") or ""),
            "errorCode": str(item.get("errorCode") or "matrix_device_task_failed"),
            "error": _redact_matrix_output(str(item.get("error") or "手机任务执行失败"))[:300],
        }
        for item in results
        if item.get("success") is not True and item.get("cancelled") is not True
    ]
    failure_summary = "；".join(
        f"{item['deviceId'] or '未知设备'}：{item['error']}"
        for item in failed_devices[:3]
    )
    ctx.get_job_mgr().progress(
        job_id,
        "Matrix 任务执行完成" if ok else f"Matrix 任务执行失败：{failure_summary or '任务已取消'}",
        "success" if ok else "danger",
        phase="matrix.dispatch.done" if ok else "matrix.dispatch.failed",
        commandId="matrix.dispatch",
        campaignId=task.get("campaignId"),
    )
    cancelled = ctx.get_job_mgr().is_cancelled(job_id)
    result = {
        "success": ok,
        "task": task,
        "status": {} if cancelled else matrix.status(),
        "results": results,
        "failedDevices": failed_devices,
        "concurrency": concurrency,
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    if cancelled:
        result["cancelled"] = True
    if not ok:
        failed = next((item for item in results if not item.get("success")), {})
        result["error"] = str(failed.get("error") or "手机矩阵任务执行失败，请查看设备连接和任务日志。")
        result["errorCode"] = str(failed.get("errorCode") or "matrix_device_task_failed")
    _record_matrix_task_evidence(body, result, started)
    return result


def _matrix_device_tasks(task: dict) -> list[dict]:
    rows: list[dict] = []
    for mission in task.get("missions", []):
        for device_task in mission.get("deviceTasks", []):
            if isinstance(device_task, dict):
                rows.append(device_task)
    return rows


def _matrix_job_scope(task: dict) -> dict:
    device_tasks = _matrix_device_tasks(task)
    return {
        "matrixDeviceTaskIds": sorted({
            str(item.get("deviceTaskId") or "")
            for item in device_tasks
            if str(item.get("deviceTaskId") or "")
        }),
        "matrixDeviceIds": sorted({
            str(item.get("deviceId") or "")
            for item in device_tasks
            if str(item.get("deviceId") or "")
        }),
    }


def _run_matrix_device_task_if_active(
    ctx,
    matrix: MatrixControlPlane,
    body: dict,
    device_task: dict,
    job_id: str,
) -> dict:
    if ctx.get_job_mgr().is_cancelled(job_id):
        return {
            "success": False,
            "cancelled": True,
            "assignmentId": str(device_task.get("assignmentId") or ""),
            "deviceTaskId": str(device_task.get("deviceTaskId") or ""),
            "deviceId": str(device_task.get("deviceId") or ""),
            "durationMs": 0,
            "errorCode": "cancelled",
            "error": "cancelled",
        }
    return _run_matrix_device_task(ctx, matrix, body, device_task, job_id)


def _wait_for_agent_execution_lease(
    ctx,
    matrix: MatrixControlPlane,
    device_task: dict,
    job_id: str,
) -> dict | None:
    device_id = str(device_task.get("deviceId") or "")
    device_task_id = str(device_task.get("deviceTaskId") or "")
    timeout_sec = max(30, min(int(device_task.get("timeoutSec") or 300), 1200))
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if ctx.get_job_mgr().is_cancelled(job_id) or matrix.task_status(device_task_id) != "queued":
            return None
        try:
            return matrix.acquire_lease(
                device_id,
                {
                    "holderType": "agent",
                    "holderId": device_task_id,
                    "mode": "control",
                },
            )
        except MatrixTargetError as exc:
            if exc.code != "device_lease_conflict":
                raise
            time.sleep(0.1)
    raise MatrixTargetError("device_lease_timeout", f"Timed out waiting for device lease: {device_id}")


def _run_matrix_device_task(
    ctx,
    matrix: MatrixControlPlane,
    body: dict,
    device_task: dict,
    job_id: str,
) -> dict:
    device_task_id = str(device_task.get("deviceTaskId") or "")
    device_id = str(device_task.get("deviceId") or "")
    assignment_id = str(device_task.get("assignmentId") or "")
    started = time.monotonic()
    job_manager = ctx.get_job_mgr()
    execution_lock = _matrix_device_execution_lock(device_id)
    lock_acquired = False
    lease: dict | None = None
    last_lease_renewal = 0.0

    def release_execution_lease() -> None:
        nonlocal lease
        if not lease:
            return
        active_lease = lease
        matrix.release_lease(device_id, str(active_lease.get("leaseId") or ""))
        lease = None

    def cancelled_result() -> dict:
        return {
            "success": False,
            "cancelled": True,
            "assignmentId": assignment_id,
            "deviceTaskId": device_task_id,
            "deviceId": device_id,
            "durationMs": int((time.monotonic() - started) * 1000),
            "errorCode": "cancelled",
            "error": "cancelled",
        }

    if job_manager.is_cancelled(job_id):
        return cancelled_result()
    try:
        lease = _wait_for_agent_execution_lease(ctx, matrix, device_task, job_id)
        if not lease:
            return cancelled_result()
        execution_lock.acquire()
        lock_acquired = True
        if job_manager.is_cancelled(job_id) or matrix.task_status(device_task_id) != "queued":
            return cancelled_result()
        matrix.start_task(device_task_id)
        last_lease_renewal = time.monotonic()

        def task_cancelled() -> bool:
            nonlocal lease, last_lease_renewal
            if job_manager.is_cancelled(job_id):
                return True
            if matrix.task_status(device_task_id) not in {"running", "preflight", "retrying"}:
                return True
            now = time.monotonic()
            if now - last_lease_renewal >= 5 and lease:
                try:
                    lease = matrix.acquire_lease(
                        device_id,
                        {
                            "holderType": "agent",
                            "holderId": device_task_id,
                            "mode": "control",
                            "leaseId": lease.get("leaseId"),
                        },
                    )
                    last_lease_renewal = now
                except MatrixTargetError:
                    return True
            return False

        matrix.mark_step(
            device_task_id,
            str(device_task.get("currentStep") or "step_prepare"),
            status="running",
            message="准备单机执行",
        )
        task_body = dict(body or {})
        for key in (
            "prompt",
            "mode",
            "profile",
            "template",
            "templateId",
            "input",
            "timeoutSec",
            "retryBudget",
            "assignmentId",
            "action",
            "directAction",
            "executionLayer",
        ):
            value = device_task.get(key)
            if value is not None and value != "":
                task_body[key] = value
        plan = _build_phone_task_plan(ctx, task_body, device_id=device_id)
        evidence_body = plan.get("evidence_body") if isinstance(plan.get("evidence_body"), dict) else {}
        evidence_body.update(
            {
                "campaignId": str(body.get("campaignId") or ""),
                "assignmentId": assignment_id,
                "deviceId": device_id,
                "templateId": str(device_task.get("templateId") or ""),
                "input": dict(device_task.get("input") or {}),
                "timeoutSec": int(device_task.get("timeoutSec") or evidence_body.get("timeoutSec") or 0),
                "retryBudget": int(device_task.get("retryBudget") or 0),
            }
        )
        plan["evidence_body"] = evidence_body
        matrix.append_task_event(
            "step",
            device_task_id,
            f"{plan.get('execution_layer') or 'agent'} 路径已选择",
        )
        if job_manager.is_cancelled(job_id):
            return cancelled_result()
        retry_budget = max(0, min(int(device_task.get("retryBudget") or 0), 10))
        attempt = 0
        while True:
            raw_result = _submit_phone_job(
                ctx,
                inline_job_id=job_id,
                should_cancel=task_cancelled,
                **plan,
            )
            if not isinstance(raw_result, dict):
                raise RuntimeError("手机任务执行器未返回有效结果")
            if raw_result.get("cancelled") is True or job_manager.is_cancelled(job_id):
                return cancelled_result()
            if _matrix_execution_is_uncertain(raw_result):
                raw_result["outcomeIndeterminate"] = True
            if (
                raw_result.get("success") is True
                or _matrix_execution_is_uncertain(raw_result)
                or attempt >= retry_budget
            ):
                break
            attempt += 1
            matrix.append_task_event(
                "retrying",
                device_task_id,
                f"Retrying canonical assignment ({attempt}/{retry_budget})",
            )

        stdout = _redact_matrix_output(
            _sanitize_cli_output(ctx, raw_result.get("stdout") or "", kind="phone.task")
        )
        stderr = _redact_matrix_output(
            _sanitize_cli_output(ctx, raw_result.get("stderr") or "", kind="phone.task")
        )
        ok = raw_result.get("success") is True
        error = "" if ok else str(
            raw_result.get("error")
            or raw_result.get("reason")
            or raw_result.get("message")
            or "手机矩阵任务执行失败，请检查设备连接和任务配置。"
        )
        metrics = raw_result.get("metrics") if isinstance(raw_result.get("metrics"), dict) else {}
        duration_ms = int(metrics.get("totalMs") or ((time.monotonic() - started) * 1000))
        release_execution_lease()
        error_code = str(raw_result.get("errorCode") or raw_result.get("code") or "")
        matrix.record_result(
            device_task_id,
            ok=ok,
            duration_ms=duration_ms,
            failure_reason=error,
            failure_code=error_code,
            task_id=str(raw_result.get("taskId") or ""),
            outcome_indeterminate=raw_result.get("outcomeIndeterminate") is True,
            execution_may_continue=raw_result.get("executionMayContinue") is True,
        )
        result = {
            "success": ok,
            "assignmentId": assignment_id,
            "deviceTaskId": device_task_id,
            "deviceId": device_id,
            "attempts": attempt + 1,
            "retryBudget": retry_budget,
            "executionLayer": str(
                raw_result.get("executionLayer")
                or (raw_result.get("execution") or {}).get("layer")
                or plan.get("execution_layer")
                or "agent"
            ),
            "script": str(plan.get("script_name") or ""),
            "durationMs": duration_ms,
            "error": _redact_matrix_output(error)[:500],
            "errorCode": error_code,
            "currentStep": str(raw_result.get("currentStep") or "collect"),
            "stdoutPreview": stdout[:800],
            "stderrPreview": stderr[:800],
            "stdout": stdout,
            "stderr": stderr,
        }
        if metrics:
            result["metrics"] = _redact_matrix_json(metrics)
        if isinstance(raw_result.get("fallback"), dict):
            result["fallback"] = _redact_matrix_json(raw_result["fallback"])
        for key in ("taskId", "outcomeIndeterminate", "executionMayContinue"):
            value = raw_result.get(key)
            if value not in (None, "", False):
                result[key] = _redact_matrix_json(value)
        return result
    except Exception as exc:
        error = _redact_matrix_output(str(exc))[:300]
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            release_execution_lease()
        except Exception:
            pass
        failure_code = str(getattr(exc, "code", "") or "matrix_device_execution_failed")
        matrix.record_result(
            device_task_id,
            ok=False,
            duration_ms=duration_ms,
            failure_reason=error,
            failure_code=failure_code,
        )
        return {
            "success": False,
            "assignmentId": assignment_id,
            "deviceTaskId": device_task_id,
            "deviceId": device_id,
            "durationMs": duration_ms,
            "errorCode": failure_code,
            "error": error,
        }
    finally:
        try:
            release_execution_lease()
        except Exception:
            pass
        if lock_acquired:
            execution_lock.release()

def _redact_matrix_output(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(r'("(?:token|secret|password|apiKey|api_key)"\s*:\s*)"[^"]+"', r'\1"***"', text, flags=re.I)
    return text


def _record_matrix_task_evidence(body: dict, result: dict, started_at: float) -> None:
    try:
        from loom_cli import _write_task_evidence

        ok = result.get("success") is True
        payload = {
            "ok": ok,
            "command": "matrix.dispatch",
            "data": {
                "method": "POST",
                "endpoint": "/api/matrix/dispatch",
                "body": _redact_matrix_json(body),
                "result": _redact_matrix_json(result),
            },
        }
        if not ok:
            payload["error"] = {
                "code": str(result.get("errorCode") or "matrix_dispatch_failed"),
                "message": str(result.get("error") or "Matrix 任务执行失败"),
            }
        evidence_ctx = type("BridgeEvidenceContext", (), {"permission": "control", "source": "bridge"})()
        _write_task_evidence(
            ["matrix.dispatch"],
            "matrix.dispatch",
            evidence_ctx,
            payload,
            (time.monotonic() - started_at) * 1000,
            source="bridge",
        )
    except Exception:
        return


def _redact_matrix_json(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(mark in lowered for mark in ("token", "secret", "password", "apikey", "api_key", "credential")):
                safe[str(key)] = "***"
            else:
                safe[str(key)] = _redact_matrix_json(item)
        return safe
    if isinstance(value, list):
        return [_redact_matrix_json(item) for item in value[:200]]
    if isinstance(value, str):
        return _redact_matrix_output(value)
    return value


def _template_prompt(template: str) -> str:
    if template == "screen-summary":
        return "读取当前页面，返回页面名称和三个可见按钮。"
    if template == "back":
        return "返回上一页"
    if template == "home":
        return "回到桌面"
    if template == "open-settings":
        return "打开系统设置"
    return "读取当前手机屏幕，返回当前页面名称和三个可见内容。"
