"""Runtime wire contract routes."""

from __future__ import annotations

from fastapi import Request

from core.wire_config import WireConfigError


def register_wire_routes(app, ctx) -> None:
    @app.api_route("/api/wire/current", methods=["GET", "POST"])
    async def wire_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"wire": ctx.get_wire_svc().current_public()})

    @app.post("/api/wire/sync")
    async def wire_sync(request: Request):
        if error := ctx.auth_error(request):
            return error
        session = ctx.get_newapi_account_mgr().current()
        if not session:
            return ctx.fastapi_json({"error": "尚未登录模型账号"}, 400)
        result = ctx.get_wire_svc().sync_from_session(session)
        return ctx.fastapi_json(result)

    @app.post("/api/wire/custom")
    async def wire_custom(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        target_args = {}
        if isinstance(body.get("targets"), list):
            target_args["targets"] = tuple(str(item or "").strip() for item in body["targets"] if str(item or "").strip())
        try:
            return ctx.fastapi_json(ctx.get_wire_svc().sync_custom_provider(
                provider=str(body.get("provider") or "").strip(),
                base_url=str(body.get("baseUrl") or body.get("url") or "").strip(),
                api_key=str(body.get("apiKey") or body.get("token") or "").strip(),
                text_model=str(body.get("textModel") or body.get("model") or "").strip(),
                image_model=str(body.get("imageModel") or "").strip(),
                phone_model=str(body.get("phoneModel") or "").strip(),
                video_model=str(body.get("videoModel") or "").strip(),
                **target_args,
            ))
        except WireConfigError as exc:
            return ctx.fastapi_json({"error": str(exc), "wire": ctx.get_wire_svc().current_public()}, 400)

    @app.post("/api/wire/verify")
    async def wire_verify(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        candidate_fields = {
            "provider": str(body.get("provider") or "").strip(),
            "base_url": str(body.get("baseUrl") or body.get("url") or "").strip(),
            "api_key": str(body.get("apiKey") or body.get("token") or "").strip(),
            "text_model": str(body.get("textModel") or body.get("model") or "").strip(),
        }
        if any(candidate_fields.values()):
            try:
                return ctx.fastapi_json(ctx.get_wire_svc().verify_candidate(**candidate_fields))
            except WireConfigError as exc:
                return ctx.fastapi_json({"error": str(exc)}, 400)
        return ctx.fastapi_json(ctx.get_wire_svc().verify())

    @app.post("/api/wire/rollback")
    async def wire_rollback(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(ctx.get_wire_svc().rollback())
        except WireConfigError as exc:
            return ctx.fastapi_json({"error": str(exc), "wire": ctx.get_wire_svc().current_public()}, 400)
