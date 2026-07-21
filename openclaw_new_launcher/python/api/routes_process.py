"""OpenClaw process FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_process_routes(app, ctx) -> None:
    @app.api_route("/api/process/status", methods=["GET", "POST"])
    async def process_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        svc = ctx.get_process_svc()
        return ctx.fastapi_json(svc.status())

    @app.post("/api/process/start")
    async def process_start(request: Request):
        if error := ctx.auth_error(request):
            return error
        if error := ctx.protected_error("/api/process/start"):
            return error

        svc = ctx.get_process_svc()
        if svc.running or getattr(svc, "startup_state", "") == "starting":
            status = svc.status()
            status["status"] = "already_running" if status.get("running") else "starting"
            return ctx.fastapi_json(status)

        try:
            ctx.sync_openclaw_models_from_api_profiles()
        except Exception as sync_error:
            ctx.append_log(f"[OpenClaw] Gateway config sync failed before startup: {sync_error}\n")
            return ctx.fastapi_json({
                "status": "failed",
                "error": f"会员网关配置同步失败：{sync_error}",
            }, 500)

        def on_exit(code: int | None) -> None:
            ctx.append_log(f"\n[OpenClaw] Process ended (exit: {code})\n")

        status = svc.start_background(on_exit=on_exit)
        status["status"] = "starting"
        return ctx.fastapi_json(status)

    @app.post("/api/process/stop")
    async def process_stop(request: Request):
        if error := ctx.auth_error(request):
            return error
        message = ctx.get_process_svc().stop()
        return ctx.fastapi_json({"status": "stopped", "message": message})
