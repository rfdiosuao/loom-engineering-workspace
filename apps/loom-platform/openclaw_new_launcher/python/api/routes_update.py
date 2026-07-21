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
        latest, error_message = await asyncio.to_thread(updater.latest_version)
        if error_message:
            return ctx.fastapi_json({"error": error_message, "current": current}, 500)
        return ctx.fastapi_json({"current": current, "latest": latest, "hasUpdate": current != latest})

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
        response_status = 200 if success else (409 if status.get("errorCode") == "update_in_progress" else 500)
        return ctx.fastapi_json(payload, response_status)

    @app.get("/api/update/status")
    async def update_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_app_updater().status())
