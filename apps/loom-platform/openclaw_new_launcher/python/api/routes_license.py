"""License FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from api.safe_payload import public_safe_payload
from core.license_manager import LicenseError


def _commercial_status(diagnosis: dict, has_license: bool) -> tuple[str, str]:
    if has_license:
        return "authorized", "AUTHORIZED"
    raw = str(diagnosis.get("code") or "missing").strip().lower()
    if raw == "expired":
        return "expired", "LICENSE_EXPIRED"
    if raw in {"device_id_mismatch", "install_id_mismatch"}:
        return "device_mismatch", "DEVICE_MISMATCH"
    if raw in {"signature_missing", "signature_invalid", "corrupt", "unreadable"}:
        return "unauthorized", "LICENSE_INVALID"
    return "unauthorized", "LICENSE_REQUIRED"


def register_license_routes(app, ctx) -> None:
    @app.api_route("/api/license/current", methods=["GET", "POST"])
    async def license_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        license_manager = ctx.get_license_mgr()
        license_data = license_manager.current_license()
        diagnosis = license_manager.diagnose(include_gateway_profile=False)
        status, code = _commercial_status(diagnosis, isinstance(license_data, dict))
        gateway_profile = license_manager.current_gateway_profile()
        try:
            member = ctx.get_member_mgr().current()
        except Exception:
            member = None
        return ctx.fastapi_json(public_safe_payload({
            "license": license_data,
            "gatewayProfile": gateway_profile,
            "member": member,
            "status": status,
            "code": code,
            "reason": str(diagnosis.get("message") or ""),
            "installId": license_manager.get_install_id(),
            "deviceId": license_manager.device_id(),
        }))

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
            try:
                ctx.sync_openclaw_models_from_api_profiles()
            except Exception as sync_error:
                ctx.append_log(f"[License] Gateway config sync failed after activation: {sync_error}\n")
            theme = ctx.get_theme_mgr().get_current(ctx.get_license_mgr().current_license())
            return ctx.fastapi_json(public_safe_payload({"license": result, "theme": theme}))
        except LicenseError as exc:
            return ctx.fastapi_json({"error": str(exc), "code": exc.code}, 400)
