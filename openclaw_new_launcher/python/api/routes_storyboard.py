"""Storyboard (全案九步) FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def register_storyboard_routes(app, ctx) -> None:

    @app.get("/api/storyboard/param-config")
    async def get_param_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        svc = ctx.get_storyboard_svc()
        return ctx.fastapi_json({"config": svc.get_param_config()})

    @app.post("/api/storyboard/import-param-config")
    async def import_param_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        payload = body.get("config", body)
        if not isinstance(payload, dict):
            return ctx.fastapi_json({"error": "config 必须是对象"}, 400)
        svc = ctx.get_storyboard_svc()
        result = svc.import_param_config(payload)
        return ctx.fastapi_json(result)

    @app.post("/api/storyboard/generate")
    async def generate(request: Request):
        if error := ctx.protected_error(request.url.path):
            return error
        body = await ctx.body(request)
        stage = str(body.get("stage") or "").strip()
        if stage not in ("script", "storyboard", "videoPrompt"):
            return ctx.fastapi_json({"error": "stage 必须是 script/storyboard/videoPrompt"}, 400)
        project = body.get("project")
        if not isinstance(project, dict):
            return ctx.fastapi_json({"error": "project 必须是对象"}, 400)
        svc = ctx.get_storyboard_svc()
        model_client = ctx.get_agent_service().model_client
        result = svc.generate(stage, project, model_client)
        return ctx.fastapi_json(result)
