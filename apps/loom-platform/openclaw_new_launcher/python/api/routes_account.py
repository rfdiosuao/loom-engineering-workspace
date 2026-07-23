"""New API account login routes."""

from __future__ import annotations

import asyncio
import re
import threading

from fastapi import Request

from core.newapi_account_manager import NewApiAccountError


SECRET_RESULT_KEYS = {
    "apiKey",
    "accessToken",
    "gatewayImageAccessToken",
    "gatewayVideoAccessToken",
    "memberToken",
    "sessionCookie",
    "token",
}
PUBLIC_EMAIL_CODE_KEYS = {
    "sent",
    "email",
    "maskedEmail",
    "retryAfter",
    "expiresIn",
    "message",
}


SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|session[_-]?cookie|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})"),
    re.compile(r"\b(sk-[A-Za-z0-9._-]+|sess-[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._=-]+)"),
)


def _account_response(
    *,
    account: dict,
    session: dict | None = None,
    extra_sync_results: list[dict] | None = None,
    sync_pending: bool = False,
) -> dict:
    sync_results = []
    if isinstance(session, dict) and isinstance(session.get("lastSyncResults"), list):
        sync_results.extend(session.get("lastSyncResults") or [])
    if extra_sync_results:
        sync_results.extend(extra_sync_results)
    response = {
        "account": account,
        "syncResults": [_public_sync_result(item) for item in sync_results if isinstance(item, dict)],
    }
    if sync_pending:
        response["syncPending"] = True
    return response


def _start_runtime_sync(manager, session: dict, append_log) -> None:
    def run() -> None:
        try:
            manager.sync_targets(session)
            append_log("[Account] background runtime configuration sync completed.\n")
        except Exception as error:
            append_log(f"[Account] background runtime configuration sync failed: {_redact_secret_text(error)}\n")

    threading.Thread(target=run, name="loom-account-runtime-sync", daemon=True).start()


def _public_sync_result(item: dict) -> dict:
    payload = {
        key: value
        for key, value in item.items()
        if key not in SECRET_RESULT_KEYS and "token" not in key.lower() and "cookie" not in key.lower()
    }
    if isinstance(payload.get("error"), str):
        payload["error"] = _redact_secret_text(payload["error"])
    return payload


def _redact_secret_text(value: str) -> str:
    text = str(value or "")
    for pattern in SECRET_TEXT_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
        elif pattern.groups == 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def _friendly_account_error(value: object, context: str = "") -> str:
    text = _redact_secret_text(str(value or "").strip())
    lower = text.lower()
    context_lower = str(context or "").lower()
    if not text:
        return "账号请求失败，请稍后重试"
    email_taken_markers = (
        "邮箱地址已被占用",
        "邮箱已被占用",
        "邮箱已存在",
        "email already",
        "already exists",
        "already registered",
        "occupied",
    )
    if any(marker.lower() in lower for marker in email_taken_markers):
        if "login" in context_lower:
            return "验证码登录接口返回了注册校验结果。请改用密码登录，或联系管理员开启登录验证码接口。"
        return "这个邮箱已经注册过，请切到验证码登录或密码登录。"
    if "newapi_network_error" in lower or "timed out" in lower or "urlopen error" in lower:
        return "无法连接模型服务，请检查网络后重试"
    if (
        "username or password is incorrect" in lower
        or "invalid username or password" in lower
        or "password" in lower and "incorrect" in lower
    ):
        return "用户名、邮箱或密码错误"
    if "email domain" in lower or "whitelist" in lower or "special symbols" in lower:
        return "邮箱域名未开放或邮箱格式不符合模型服务要求，请换用已允许的邮箱或联系管理员。"
    if "turnstile" in lower or "verification failed" in lower:
        return "模型服务启用了网页人机验证，请使用密码登录，或在浏览器完成邮箱注册。"
    if "verification code" in lower or "email code" in lower:
        return "验证码无效或已过期，请重新发送后再试。"
    if "launcher_token_bridge_no_key" in lower or "no_key" in lower:
        return "模型服务未返回可用模型凭证，请稍后重试或联系管理员"
    if "openclaw_auth_endpoint_unavailable" in lower:
        return "模型账号接口暂不可用，请稍后重试"
    if "not found" in lower or "invalid url" in lower:
        return "模型账号接口暂不可用，请使用密码登录或稍后重试"
    if "http_429" in lower or "too many" in lower:
        return "操作过于频繁，请稍后再试"
    if "http_401" in lower or "unauthorized" in lower:
        return "登录状态已失效，请重新登录"
    return text


def _public_email_code_response(payload: dict, email: str) -> dict:
    result = {
        key: value
        for key, value in (payload or {}).items()
        if key in PUBLIC_EMAIL_CODE_KEYS and value not in ("", None)
    }
    result.setdefault("sent", True)
    result.setdefault("email", email)
    return result


def register_account_routes(app, ctx) -> None:
    @app.api_route("/api/account/current", methods=["GET", "POST"])
    async def account_current(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"account": ctx.get_newapi_account_mgr().public_session()})

    @app.get("/api/account/capabilities")
    async def account_capabilities(request: Request):
        if error := ctx.auth_error(request):
            return error
        base_url = str(request.query_params.get("baseUrl") or "").strip()
        manager = ctx.get_newapi_account_mgr()
        capabilities = await asyncio.to_thread(manager.auth_capabilities, base_url=base_url)
        return ctx.fastapi_json({"capabilities": capabilities})

    @app.post("/api/account/email-code/send")
    async def account_email_code_send(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        email = str(body.get("email") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        purpose = str(body.get("purpose") or body.get("mode") or body.get("scene") or "login").strip()
        try:
            result = ctx.get_newapi_account_mgr().send_email_code(
                email,
                base_url=base_url,
                purpose=purpose,
            )
            response = _public_email_code_response(result, email)
            if response.get("sent") is False:
                message = _friendly_account_error(response.get("message") or "email code was not sent")
                response["error"] = {
                    "code": "email_code_not_sent",
                    "message": message,
                }
                return ctx.fastapi_json(response, 502)
            return ctx.fastapi_json(response)
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, f"email_code_send:{purpose}")}, 400)

    @app.post("/api/account/email-code/login")
    async def account_email_code_login(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        email = str(body.get("email") or "").strip()
        code = str(body.get("code") or body.get("emailCode") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        try:
            session = ctx.get_newapi_account_mgr().login_with_email_code(
                email,
                code,
                base_url=base_url,
            )
            return ctx.fastapi_json(_account_response(account=ctx.get_newapi_account_mgr().public_session(), session=session))
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, "email_code_login")}, 400)

    @app.post("/api/account/register")
    async def account_register(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        email = str(body.get("email") or body.get("username") or "").strip()
        password = str(body.get("password") or "").strip()
        code = str(body.get("code") or body.get("emailCode") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        try:
            session = ctx.get_newapi_account_mgr().register_with_email_code(
                email,
                password,
                code,
                base_url=base_url,
            )
            return ctx.fastapi_json(_account_response(account=ctx.get_newapi_account_mgr().public_session(), session=session))
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, "register")}, 400)

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
            manager = ctx.get_newapi_account_mgr()
            session = await asyncio.to_thread(
                manager.login,
                username,
                password,
                base_url=base_url,
                api_token=api_token,
                sync_runtime=False,
            )
            account = manager.public_session()
            response = _account_response(account=account, session=session, sync_pending=True)
            _start_runtime_sync(manager, session, ctx.append_log)
            return ctx.fastapi_json(response)
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, "password_login")}, 400)

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
            return ctx.fastapi_json(_account_response(account=ctx.get_newapi_account_mgr().public_session(), session=session))
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, "bind_ticket")}, 400)

    @app.post("/api/account/sync")
    async def account_sync(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            session = ctx.get_newapi_account_mgr().refresh_current()
            return ctx.fastapi_json(
                _account_response(
                    account=ctx.get_newapi_account_mgr().public_session(),
                    session=session,
                )
            )
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc, "sync")}, 400)
        except Exception as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc)}, 500)

    @app.post("/api/account/models/select")
    async def account_select_models(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        phone_model = str(body.get("phoneModel") or body.get("phone") or "").strip()
        model_args = {
            "text_model": str(body.get("textModel") or body.get("text") or "").strip(),
            "image_model": str(body.get("imageModel") or body.get("image") or "").strip(),
            "video_model": str(body.get("videoModel") or body.get("video") or "").strip(),
        }
        if phone_model:
            model_args["phone_model"] = phone_model
        try:
            account = ctx.get_newapi_account_mgr().select_models(**model_args)
            return ctx.fastapi_json({"account": account})
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc)}, 400)

    @app.api_route("/api/account/subscription", methods=["GET", "POST"])
    async def account_subscription(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            subscription = await asyncio.to_thread(ctx.get_newapi_account_mgr().subscription_snapshot)
            return ctx.fastapi_json({"subscription": subscription})
        except NewApiAccountError as exc:
            return ctx.fastapi_json({"error": _friendly_account_error(exc)}, 400)

    @app.post("/api/account/logout")
    async def account_logout(request: Request):
        if error := ctx.auth_error(request):
            return error
        removed = ctx.get_newapi_account_mgr().logout()
        return ctx.fastapi_json({
            "loggedOut": removed,
            "account": ctx.get_newapi_account_mgr().public_session(),
        })
