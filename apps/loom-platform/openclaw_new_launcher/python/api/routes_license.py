"""License FastAPI routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import Request

from api.safe_payload import public_safe_payload
from core.license_manager import LicenseError
from core.newapi_account_manager import NewApiAccountError


def _commercial_status(diagnosis: dict, has_license: bool) -> tuple[str, str]:
    if has_license:
        return "authorized", "AUTHORIZED"
    raw = str(diagnosis.get("code") or "missing").strip().lower()
    if raw == "expired" or "expired" in raw:
        return "expired", "LICENSE_EXPIRED"
    if raw in {"device_id_mismatch", "install_id_mismatch"}:
        return "device_mismatch", "DEVICE_MISMATCH"
    if raw in {"signature_missing", "signature_invalid", "corrupt", "unreadable"}:
        return "unauthorized", "LICENSE_INVALID"
    return "unauthorized", "LICENSE_REQUIRED"


def _epoch_iso(value) -> str | None:
    if type(value) is not int or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _account_license_payload(state: dict, license_manager) -> dict | None:
    if not state.get("authorized"):
        return None
    lease = state.get("lease") if isinstance(state.get("lease"), dict) else {}
    limits = state.get("limits") if isinstance(state.get("limits"), dict) else {}
    expires_at = _epoch_iso(state.get("expiresAt"))
    device_id = str(
        lease.get("hostDeviceId")
        or lease.get("deviceId")
        or license_manager.device_id()
    )
    return {
        "licensee": str(lease.get("accountId") or "LOOM account"),
        "edition": str(state.get("plan") or "activated"),
        "plan": str(state.get("plan") or "activated"),
        "expires": expires_at,
        "expiresAt": expires_at,
        "features": list(state.get("features") or []),
        "installId": str(lease.get("installId") or license_manager.get_install_id()),
        "deviceId": device_id,
        "deviceLimit": limits.get("devices"),
        "signature": str(lease.get("signature") or ""),
        "status": "offline_grace" if state.get("offline") else "authorized",
        "code": "OFFLINE_GRACE" if state.get("offline") else "AUTHORIZED",
        "memberId": str(lease.get("accountId") or ""),
        "activationCodeLabel": str(lease.get("codeLabel") or ""),
    }


def register_license_routes(app, ctx) -> None:
    @app.api_route("/api/license/current", methods=["GET", "POST"])
    async def license_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        license_manager = ctx.get_license_mgr()
        entitlement_getter = getattr(ctx, "get_entitlement_mgr", None)
        entitlement_state = (
            entitlement_getter().current_state("matrix.devices")
            if callable(entitlement_getter)
            else {}
        )
        use_account_entitlement = bool(
            isinstance(entitlement_state, dict)
            and (
                entitlement_state.get("source") == "account_entitlement"
                or entitlement_state.get("accountLeaseSeen")
            )
        )
        if use_account_entitlement:
            license_data = _account_license_payload(entitlement_state, license_manager)
            diagnosis = {
                "code": entitlement_state.get("code") or (
                    "ok" if entitlement_state.get("authorized") else "entitlement_required"
                ),
                "message": entitlement_state.get("message") or "",
            }
            status, code = _commercial_status(
                diagnosis,
                isinstance(license_data, dict),
            )
            if isinstance(license_data, dict) and entitlement_state.get("offline"):
                status, code = "offline_grace", "OFFLINE_GRACE"
            source = "account_entitlement"
        else:
            license_data = license_manager.current_license()
            diagnosis = license_manager.diagnose(include_gateway_profile=False)
            status, code = _commercial_status(diagnosis, isinstance(license_data, dict))
            source = "legacy_license" if isinstance(license_data, dict) else "none"
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
            "source": source,
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
        entitlement_getter = getattr(ctx, "get_entitlement_mgr", None)
        authorizer = entitlement_getter() if callable(entitlement_getter) else ctx.get_license_mgr()
        return ctx.fastapi_json({"authorized": authorizer.is_authorized(body.get("feature"))})

    @app.post("/api/license/activate")
    async def license_activate(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        code = body.get("code", "")
        if not code:
            return ctx.fastapi_json({"error": "授权码不能为空"}, 400)
        account_manager_getter = getattr(ctx, "get_newapi_account_mgr", None)
        account_manager = account_manager_getter() if callable(account_manager_getter) else None
        public_account = account_manager.public_session() if account_manager is not None else {}
        if isinstance(public_account, dict) and public_account.get("loggedIn"):
            try:
                await asyncio.to_thread(account_manager.redeem_entitlement_code, str(code))
                entitlement_getter = getattr(ctx, "get_entitlement_mgr", None)
                entitlement_state = (
                    entitlement_getter().current_state("matrix.devices")
                    if callable(entitlement_getter)
                    else {}
                )
                license_data = _account_license_payload(
                    entitlement_state,
                    ctx.get_license_mgr(),
                )
                if not isinstance(license_data, dict):
                    return ctx.fastapi_json(
                        {"error": "账号授权已提交，但未返回可信权益租约，请刷新账号后重试。"},
                        502,
                    )
                return ctx.fastapi_json(public_safe_payload({
                    "license": license_data,
                    "account": account_manager.public_session(),
                    "status": "authorized",
                    "code": "AUTHORIZED",
                    "source": "account_entitlement",
                }))
            except NewApiAccountError as exc:
                status_code = exc.status_code if exc.status_code in {400, 401, 403, 409, 429, 502, 503} else 400
                return ctx.fastapi_json({"error": str(exc)}, status_code)
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
