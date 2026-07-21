"""Phone automation scheduler routes."""

from __future__ import annotations

from anyio import to_thread
from fastapi import Request


def register_phone_automation_routes(app, ctx) -> None:
    @app.api_route("/api/phone-automation/scheduler/status", methods=["GET", "POST"])
    async def scheduler_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(await to_thread.run_sync(ctx.get_phone_scheduler().status))

    @app.api_route("/api/phone-automation/scheduler/start", methods=["POST"])
    async def scheduler_start(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(await to_thread.run_sync(ctx.get_phone_scheduler().start))

    @app.api_route("/api/phone-automation/scheduler/stop", methods=["POST"])
    async def scheduler_stop(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(await to_thread.run_sync(ctx.get_phone_scheduler().stop))

    @app.api_route("/api/phone-automation/scheduler/tick", methods=["POST"])
    async def scheduler_tick(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(await to_thread.run_sync(ctx.get_phone_scheduler().tick))

    @app.api_route("/api/phone-automation/scheduler/run_once", methods=["POST"])
    async def scheduler_run_once(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_ids = body.get("deviceIds") if isinstance(body, dict) else []
        if not isinstance(device_ids, list):
            device_ids = []
        result = await to_thread.run_sync(
            ctx.get_phone_scheduler().run_once,
            str(body.get("templateId") or "") if isinstance(body, dict) else "",
            [str(item) for item in device_ids],
            str(body.get("mode") or "") if isinstance(body, dict) else "",
            bool(body.get("allowUnattended")) if isinstance(body, dict) else False,
        )
        return ctx.fastapi_json(result)
