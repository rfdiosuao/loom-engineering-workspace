"""LOOM desktop RPA sidecar FastAPI routes."""

from __future__ import annotations

from fastapi import Request


def _strict_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _needs_risky_policy_confirmation(body: dict) -> bool:
    policy = body.get("policy") if isinstance(body.get("policy"), dict) else {}
    wechat = body.get("wechat") if isinstance(body.get("wechat"), dict) else {}
    return (
        _strict_bool(policy.get("allowClick"))
        or _strict_bool(policy.get("allowType"))
        or _strict_bool(policy.get("allowWechatSend"))
        or str(wechat.get("sendMode") or "").strip() == "auto_enter"
    )


def _proxy_json(ctx, path: str, body: dict):
    try:
        return ctx.fastapi_json(ctx.get_desktop_agent_svc().proxy(path, body))
    except PermissionError as exc:
        return ctx.fastapi_json({"ok": False, "success": False, "error": str(exc), "blocked": True}, 403)
    except Exception as exc:
        ctx.append_log(f"[Desktop Agent] proxy failed: {path}: {exc}\n")
        return ctx.fastapi_json({"ok": False, "success": False, "error": "桌面组件请求失败，详情已写入运行日志"}, 500)


def register_desktop_agent_routes(app, ctx) -> None:
    @app.api_route("/api/desktop-agent/status", methods=["GET", "POST"])
    async def desktop_agent_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_desktop_agent_svc().status())

    @app.post("/api/desktop-agent/config")
    async def desktop_agent_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        if _needs_risky_policy_confirmation(body):
            if not _strict_bool(body.get("confirmed")):
                return ctx.fastapi_json({"error": "该策略会允许桌面操作，需要确认后保存"}, 403)
        return ctx.fastapi_json({"config": ctx.get_desktop_agent_svc().write_config(body)})

    @app.post("/api/desktop-agent/start")
    async def desktop_agent_start(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(ctx.get_desktop_agent_svc().start())
        except Exception as exc:
            ctx.append_log(f"[Desktop Agent] start failed: {exc}\n")
            return ctx.fastapi_json({"error": "桌面组件启动失败，详情已写入运行日志"}, 500)

    @app.post("/api/desktop-agent/stop")
    async def desktop_agent_stop(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_desktop_agent_svc().stop())

    @app.api_route("/api/desktop-agent/health", methods=["GET", "POST"])
    async def desktop_agent_health(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(ctx.get_desktop_agent_svc().health())

    @app.post("/api/desktop-agent/screenshot")
    async def desktop_agent_screenshot(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _proxy_json(ctx, "/screenshot", await ctx.body(request))

    @app.post("/api/desktop-agent/click")
    async def desktop_agent_click(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _proxy_json(ctx, "/click", await ctx.body(request))

    @app.post("/api/desktop-agent/type")
    async def desktop_agent_type(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _proxy_json(ctx, "/type", await ctx.body(request))

    @app.post("/api/desktop-agent/wechat/send")
    async def desktop_agent_wechat_send(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _proxy_json(ctx, "/wechat/send", await ctx.body(request))

    @app.post("/api/desktop-agent/wechat/unread")
    async def desktop_agent_wechat_unread(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _proxy_json(ctx, "/wechat/unread", await ctx.body(request))
