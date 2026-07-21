"""System information FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_system_routes(app, ctx) -> None:
    @app.api_route("/api/system/info", methods=["GET", "POST"])
    async def system_info(request: Request):
        if error := ctx.auth_error(request):
            return error
        def build_payload():
            updater = ctx.get_updater()
            return {
                "node_path": ctx.paths.node_exe,
                "base_path": ctx.paths.base_path,
                "openclaw_version": updater.current_version(),
            }

        return ctx.fastapi_json(ctx.cached("system.info", 10, build_payload))
