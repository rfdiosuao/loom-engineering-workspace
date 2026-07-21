"""Configuration FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_config_routes(app, ctx) -> None:
    @app.post("/api/config/read")
    async def config_read(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        safe = ctx.safe_config_path(body.get("path", ""))
        if safe is None:
            return ctx.fastapi_json({"error": "路径不在允许的范围内"}, 403)
        return ctx.fastapi_json({"data": ctx.read_json(safe, body.get("default", {}))})

    @app.post("/api/config/write")
    async def config_write(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        file_path = body.get("path", "")
        safe = ctx.safe_config_path(file_path)
        if safe is None:
            return ctx.fastapi_json({"error": "路径不在允许的范围内"}, 403)
        if "data" not in body:
            return ctx.fastapi_json({"error": "data field is required"}, 400)
        ctx.write_json(safe, body["data"])
        if file_path.replace("\\", "/").endswith(("auth-profiles.json", "openclaw.json")):
            ctx.sync_openclaw_models_from_api_profiles()
        return ctx.fastapi_json({"status": "ok"})

    @app.api_route("/api/auth/profiles", methods=["GET", "POST", "PUT"])
    async def auth_profiles(request: Request):
        if error := ctx.auth_error(request):
            return error
        if request.method == "PUT":
            body = await ctx.body(request)
            profiles = ctx.read_json(ctx.paths.auth_profiles, {"models": {"providers": {}}})
            profiles.update(body)
            ctx.write_json(ctx.paths.auth_profiles, profiles)
            ctx.sync_openclaw_models_from_api_profiles()
            return ctx.fastapi_json({"status": "ok"})
        return ctx.fastapi_json({"profiles": ctx.read_json(ctx.paths.auth_profiles, {})})
