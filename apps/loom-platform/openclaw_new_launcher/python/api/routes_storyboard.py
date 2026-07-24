"""Storyboard (全案九步) FastAPI routes."""

from __future__ import annotations

from fastapi import Request

from core.loom_model_client import ModelGatewayError


def _model_error_payload(stage: str, error: ModelGatewayError) -> tuple[dict, int]:
    if error.code == "AGENT_ACCOUNT_LOGIN_REQUIRED":
        return {
            "errorCode": error.code,
            "error": "请先登录模型账号，再使用全案九步生成内容。",
            "retryable": False,
            "remediation": [
                "打开“模型账号”完成登录",
                "登录成功后返回“全案九步”重新生成",
            ],
            "stage": stage,
        }, 401
    if error.code == "AGENT_ACCOUNT_RELOGIN_REQUIRED":
        return {
            "errorCode": error.code,
            "error": "模型账号登录已失效，请重新登录后再生成。",
            "retryable": False,
            "remediation": [
                "打开“模型账号”重新登录",
                "确认模型可用后返回“全案九步”重试",
            ],
            "stage": stage,
        }, 401
    return {
        "errorCode": error.code,
        "error": "模型暂时无法完成全案生成，请检查模型账号和服务配置。",
        "retryable": bool(error.recoverable),
        "remediation": [
            "打开“模型账号”检查登录和模型配置",
            "确认模型服务可用后重新生成",
        ],
        "stage": stage,
    }, error.status_code if error.status_code and 400 <= error.status_code < 600 else 502


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
        try:
            result = svc.generate(stage, project, model_client)
        except ModelGatewayError as exc:
            payload, status_code = _model_error_payload(stage, exc)
            ctx.append_log(
                f"[Storyboard] generation blocked stage={stage} code={exc.code} "
                f"status={status_code} action=model_account_check\n"
            )
            return ctx.fastapi_json(payload, status_code)
        return ctx.fastapi_json(result)
