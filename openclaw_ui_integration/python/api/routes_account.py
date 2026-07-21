"""New API account login routes."""

from __future__ import annotations

from fastapi import Request

from core.newapi_account_manager import NewApiAccountError


def register_account_routes(app, ctx) -> None:
    @app.api_route("/api/account/current", methods=["GET", "POST"])
    async def account_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"account": ctx.get_newapi_account_mgr().public_session()})

    @app.post("/api/account/login")
    async def account_login(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        username = str(body.get("username") or body.get("email") or "").strip()
        password = str(body.get("password") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        api_token = str(body.get("apiToken") or "").strip()
        try:
            session = ctx.get_newapi_account_mgr().login(
                username,
                password,
                base_url=base_url,
                api_token=api_token,
            )
            try:
                ctx.sync_openclaw_models_from_api_profiles()
            except Exception as sync_error:
                ctx.append_log(f"[Account] OpenClaw model sync failed after login: {sync_error}\n")
            return ctx.fastapi_json({
                "account": ctx.get_newapi_account_mgr().public_session(),
                "member": session,
                "syncResults": session.get("lastSyncResults") if isinstance(session.get("lastSyncResults"), list) else [],
            })
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/account/bind-ticket")
    async def account_bind_ticket(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        ticket = str(body.get("ticket") or body.get("code") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        try:
            session = ctx.get_newapi_account_mgr().bind_ticket(
                ticket,
                base_url=base_url,
            )
            try:
                ctx.sync_openclaw_models_from_api_profiles()
            except Exception as sync_error:
                ctx.append_log(f"[Account] OpenClaw model sync failed after website bind: {sync_error}\n")
            return ctx.fastapi_json({
                "account": ctx.get_newapi_account_mgr().public_session(),
                "member": session,
                "syncResults": session.get("lastSyncResults") if isinstance(session.get("lastSyncResults"), list) else [],
            })
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/account/sync")
    async def account_sync(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            session = ctx.get_newapi_account_mgr().refresh_current()
            openclaw_sync = {"target": "openclaw", "ok": True}
            try:
                ctx.sync_openclaw_models_from_api_profiles()
            except Exception as sync_error:
                openclaw_sync = {"target": "openclaw", "ok": False, "error": str(sync_error)}
                ctx.append_log(f"[Account] OpenClaw model sync failed during account sync: {sync_error}\n")
            sync_results = session.get("lastSyncResults") if isinstance(session.get("lastSyncResults"), list) else []
            return ctx.fastapi_json({
                "account": ctx.get_newapi_account_mgr().public_session(),
                "member": session,
                "syncResults": [*sync_results, openclaw_sync],
            })
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
        except Exception as exc:
            return ctx.fastapi_json({"error": str(exc)}, 500)

    @app.post("/api/account/logout")
    async def account_logout(request: Request):
        if error := ctx.auth_error(request):
            return error
        removed = ctx.get_newapi_account_mgr().logout()
        return ctx.fastapi_json({
            "loggedOut": removed,
            "account": ctx.get_newapi_account_mgr().public_session(),
        })
