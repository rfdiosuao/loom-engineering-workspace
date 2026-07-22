"""OpenClaw update FastAPI routes."""

from __future__ import annotations

import asyncio

from fastapi import Request


def register_update_routes(app, ctx) -> None:
    @app.api_route("/api/update/check", methods=["GET", "POST"])
    async def update_check(request: Request):
        if error := ctx.auth_error(request):
            return error
        updater = ctx.get_app_updater()
        current = updater.current_version()
        release, error_message = await asyncio.to_thread(updater.latest_release)
        if error_message or release is None:
            return ctx.fastapi_json({"error": error_message, "current": current}, 500)
        return ctx.fastapi_json({
            "current": current,
            "latest": release.version,
            "hasUpdate": updater.is_newer_version(release.version),
            "notes": release.notes,
            "publishedAt": release.published_at,
            "releaseUrl": release.release_url,
            "size": release.size,
        })

    @app.post("/api/update/do")
    async def update_do(request: Request):
        if error := ctx.auth_error(request):
            return error

        updater = ctx.get_app_updater()
        request_status = {}

        def capture_status(status: dict) -> None:
            request_status.clear()
            request_status.update(status)

        success, current, output = await asyncio.to_thread(
            updater.install_latest,
            progress_callback=capture_status,
        )
        for line in output:
            ctx.append_log(line)
        status = request_status or updater.status()
        installer_path = updater.last_installer_path if success else ""
        phase = str(status.get("phase") or "")
        if success and phase == "current":
            outcome = "already_current"
        elif success and installer_path:
            outcome = "ready"
        elif success:
            success = False
            outcome = "failed"
            status = {
                **status,
                "message": "更新结果缺少已验证的安装包路径",
                "errorCode": "update_contract_error",
                "retryable": True,
                "remediation": ["请重新检查更新后再试；若仍失败，请导出诊断日志。"],
            }
        else:
            outcome = "failed"
        payload = {
            "success": success,
            "outcome": outcome,
            "current_version": current,
            "log": output,
            "installer_path": installer_path if outcome == "ready" else "",
            "errorCode": status.get("errorCode") or "",
            "retryable": bool(status.get("retryable")),
            "remediation": list(status.get("remediation") or []),
        }
        if not success:
            payload["error"] = status.get("message") or (output[0] if output else "更新失败")
        if status.get("errorCode") == "update_cancelled":
            payload["outcome"] = "cancelled"
            payload.pop("error", None)
        response_status = 200 if success or payload["outcome"] == "cancelled" else (
            409 if status.get("errorCode") == "update_in_progress" else 500
        )
        return ctx.fastapi_json(payload, response_status)

    @app.get("/api/update/status")
    async def update_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_app_updater().status())

    @app.post("/api/update/cancel")
    async def update_cancel(request: Request):
        if error := ctx.auth_error(request):
            return error
        updater = ctx.get_app_updater()
        requested = updater.cancel_update()
        return ctx.fastapi_json({"cancelRequested": requested, "status": updater.status()})

    @app.get("/api/update/result")
    async def update_result(request: Request):
        if error := ctx.auth_error(request):
            return error
        updater = ctx.get_app_updater()
        pending = updater.has_pending_update_result()
        result = updater.consume_update_result() if pending else None
        return ctx.fastapi_json({"pending": pending, "result": result})
