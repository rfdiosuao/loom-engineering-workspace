"""Theme FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_theme_routes(app, ctx) -> None:
    @app.api_route("/api/theme/current", methods=["GET", "POST"])
    async def theme_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        license_data = ctx.get_license_mgr().current_license()
        theme = ctx.get_theme_mgr().get_current(license_data)
        return ctx.fastapi_json({"theme": theme})

    @app.post("/api/theme/by_merchant")
    async def theme_by_merchant(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        merchant_id = body.get("merchantId", "")
        if not merchant_id:
            return ctx.fastapi_json({"error": "merchantId 不能为空"}, 400)
        theme = ctx.get_theme_mgr().get_by_merchant(merchant_id)
        if theme is None:
            return ctx.fastapi_json({"error": f"未找到商户 {merchant_id} 的主题"}, 404)
        return ctx.fastapi_json({"theme": theme})

    @app.api_route("/api/theme/list", methods=["GET", "POST"])
    async def theme_list(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"themes": ctx.get_theme_mgr().list_themes()})
