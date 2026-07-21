"""OpenClaw update FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_update_routes(app, ctx) -> None:
    @app.api_route("/api/update/check", methods=["GET", "POST"])
    async def update_check(request: Request):
        if error := ctx.auth_error(request):
            return error
        updater = ctx.get_updater()
        current = updater.current_version()
        latest, error_message = updater.latest_version()
        if error_message:
            return ctx.fastapi_json({
                "current": current,
                "latest": current,
                "hasUpdate": False,
                "error": error_message,
            })
        return ctx.fastapi_json({"current": current, "latest": latest, "hasUpdate": current != latest})

    @app.post("/api/update/do")
    async def update_do(request: Request):
        if error := ctx.auth_error(request):
            return error

        updater = ctx.get_updater()
        success, current, output = updater.install_latest()
        for line in output:
            ctx.append_log(line)
        return ctx.fastapi_json({"success": success, "current_version": current, "log": output}, 200 if success else 500)
