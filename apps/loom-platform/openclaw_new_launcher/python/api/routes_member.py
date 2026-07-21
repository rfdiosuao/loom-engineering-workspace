"""Member FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from api.safe_payload import public_safe_payload
from core.member_manager import MemberError


def register_member_routes(app, ctx) -> None:
    @app.api_route("/api/member/current", methods=["GET", "POST"])
    async def member_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        member = ctx.get_member_mgr().current()
        usage = ctx.get_member_mgr().current_usage()
        return ctx.fastapi_json(public_safe_payload({
            "member": member,
            "lease": member,
            "usage": usage,
        }))

    @app.post("/api/member/activate")
    async def member_activate(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        code = str(body.get("code", "")).strip()
        if not code:
            return ctx.fastapi_json({"error": "会员码不能为空"}, 400)
        try:
            session = ctx.get_member_mgr().activate(code)
            ctx.sync_openclaw_models_from_api_profiles()
            return ctx.fastapi_json(public_safe_payload({
                "member": session,
                "lease": session,
                "usage": session.get("usage") if isinstance(session, dict) else None,
            }))
        except MemberError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/member/refresh")
    async def member_refresh(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            session = ctx.get_member_mgr().refresh()
            ctx.sync_openclaw_models_from_api_profiles()
            return ctx.fastapi_json(public_safe_payload({
                "member": session,
                "lease": session,
                "usage": session.get("usage") if isinstance(session, dict) else None,
            }))
        except MemberError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/member/usage")
    async def member_usage(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            usage = ctx.get_member_mgr().usage()
            session = ctx.get_member_mgr().current()
            return ctx.fastapi_json(public_safe_payload({
                "member": session,
                "lease": session,
                "usage": usage,
            }))
        except MemberError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
