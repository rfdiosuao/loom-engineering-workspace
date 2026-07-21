"""License FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from core.license_manager import LicenseError


def register_license_routes(app, ctx) -> None:
    @app.api_route("/api/license/current", methods=["GET", "POST"])
    async def license_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        def build_payload():
            license_data = ctx.get_license_mgr().current_license()
            gateway_profile = ctx.get_license_mgr().current_gateway_profile()
            try:
                member = ctx.get_member_mgr().current()
            except Exception:
                member = None
            return {
                "license": license_data,
                "gatewayProfile": gateway_profile,
                "member": member,
            }

        return ctx.fastapi_json(ctx.cached("license.current", 5, build_payload))

    @app.get("/api/license/client-config")
    async def license_client_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_license_mgr().client_config())

    @app.post("/api/license/authorized")
    async def license_authorized(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        return ctx.fastapi_json({"authorized": ctx.get_license_mgr().is_authorized(body.get("feature"))})

    @app.post("/api/license/activate")
    async def license_activate(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        code = body.get("code", "")
        if not code:
            return ctx.fastapi_json({"error": "授权码不能为空"}, 400)
        try:
            result = ctx.get_license_mgr().activate(code)
            ctx.invalidate_cache("license.")
            try:
                ctx.sync_openclaw_models_from_api_profiles()
            except Exception as sync_error:
                ctx.append_log(f"[License] Gateway config sync failed after activation: {sync_error}\n")
            theme = ctx.get_theme_mgr().get_current(ctx.get_license_mgr().current_license())
            return ctx.fastapi_json({"license": result, "theme": theme})
        except LicenseError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
