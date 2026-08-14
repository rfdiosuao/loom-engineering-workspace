"""Installable component routes for the launcher bridge."""

from __future__ import annotations

import threading

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from core.agent_catalog import AgentCatalog
from core.component_catalog import ComponentCatalog, default_component_state_path, default_manifest_path, load_installable_manifest
from core.component_installer import ComponentInstallError, ComponentInstaller
from core.component_state import ComponentState, ComponentStateStore
from core.newapi_account_manager import ACCOUNT_SOURCE, NewApiAccountError
from core.official_codex import (
    CODEX_CLI_COMPONENT_ID,
    CODEX_DESKTOP_COMPONENT_ID,
    virtual_openai_component,
)
from core.release_manifest import ReleaseComponent, default_release_manifest_public_key, load_release_manifest_file
from core.wire_config import WireConfigError


RUNNING_JOB_STATUSES = {"queued", "running"}
DECLARATIVE_AGENT_CATALOG = AgentCatalog()

SIMULATION_COMPONENTS: dict[str, ReleaseComponent] = {
    "codex-desktop": ReleaseComponent(
        component_id="codex-desktop",
        name="Codex Desktop",
        version="Microsoft Store",
        platform="windows",
        arch="x64",
        archive_type="msstore",
        size=0,
        sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        urls=("https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi",),
        install_path="agents/codex-desktop",
        entry=None,
        category="agent",
        official_url="https://openai.com/codex/",
        description="OpenAI 官方 Codex 桌面应用，由 Microsoft Store 安装和更新",
    ),
    "codex-cli": ReleaseComponent(
        component_id="codex-cli",
        name="Codex CLI",
        version="待正式清单",
        platform="windows",
        arch="x64",
        archive_type="tgz",
        size=1,
        sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        urls=(),
        install_path="agents/codex-cli",
        entry="package/bin/codex.js",
        category="agent",
        official_url="https://developers.openai.com/codex/cli/",
        description="OpenAI 官方 Codex 命令行智能体；与桌面应用独立检测和安装",
        install_command=("npm", "install", "-g", "@openai/codex"),
        uninstall_command=("npm", "uninstall", "-g", "@openai/codex"),
    ),
    "claude-code": ReleaseComponent(
        component_id="claude-code",
        name="Claude Code",
        version="待正式清单",
        platform="windows",
        arch="x64",
        archive_type="tgz",
        size=1,
        sha256="123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0",
        urls=(),
        install_path="agents/claude-code",
        entry="claude-code.tgz",
        category="agent",
        description="Anthropic 命令行编程智能体",
    ),
    "opencode": ReleaseComponent(
        component_id="opencode",
        name="opencode",
        version="待正式清单",
        platform="windows",
        arch="x64",
        archive_type="zip",
        size=1,
        sha256="23456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef01",
        urls=(),
        install_path="agents/opencode",
        entry="package/bin/opencode.exe",
        category="agent",
        description="终端优先 AI 编程工具",
    ),
    "openclaw-companion": ReleaseComponent(
        component_id="openclaw-companion",
        name="OpenClaw 兼容运行时",
        version="待正式清单",
        platform="windows",
        arch="x64",
        archive_type="installer",
        size=1,
        sha256="3456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef012",
        urls=(),
        install_path="agents/openclaw-companion",
        entry="package/openclaw.mjs",
        category="agent",
        description="协议兼容组件",
    ),
    "hermes": ReleaseComponent(
        component_id="hermes",
        name="Hermes",
        version="待正式清单",
        platform="windows",
        arch="x64",
        archive_type="installer",
        size=1,
        sha256="456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123",
        urls=(),
        install_path="agents/hermes",
        entry="Hermes-Setup.exe",
        category="agent",
        description="Hermes 智能体运行时",
    ),
}


def _resolve_component_for_action(
    manifest_path: str,
    component_id: str,
    *,
    allow_fallback: bool,
) -> tuple[ReleaseComponent | None, str | None]:
    definition = DECLARATIVE_AGENT_CATALOG.by_id(component_id)
    if definition is not None:
        return definition.to_release_component(), None
    try:
        manifest, _manifest_warning = load_installable_manifest(manifest_path)
        source_id = CODEX_DESKTOP_COMPONENT_ID if component_id in {
            CODEX_DESKTOP_COMPONENT_ID,
            CODEX_CLI_COMPONENT_ID,
        } else component_id
        component = manifest.component_by_id(source_id)
        if component is None:
            return None, f"Unknown component: {component_id}"
        component = virtual_openai_component(component, component_id)
        if component is None:
            return None, f"Unknown component: {component_id}"
        return component, None
    except Exception as manifest_error:
        if allow_fallback:
            component = SIMULATION_COMPONENTS.get(component_id)
            if component is not None:
                return component, f"正式组件清单未就绪：release-manifest.json：{manifest_error}"
        return None, f"正式安装需要 release-manifest.json：{manifest_error}"


def _component_error_status(error: str | None) -> int:
    return 404 if str(error or "").startswith("Unknown component") else 400


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _model_config_error_payload(error: Exception, *, custom_provider: bool = False) -> dict[str, str]:
    detail = str(error or "").strip()
    if detail.startswith("selected_model_not_listed"):
        return {
            "error": "所选模型已不在当前账号最新的可用目录中，配置未写入。模型目录已刷新，请重新选择后再试。",
            "code": "selected_model_not_listed",
            "action": "choose_compatible_model",
        }
    if "responses_tool_call_missing" in detail:
        return {
            "error": "该模型能够返回文字，但不能返回 Codex 所需的原生工具调用，配置没有写入。请选择支持 Responses API 与 function_call 的模型。",
            "code": "codex_responses_tool_call_missing",
            "action": "choose_compatible_model",
        }
    if detail.startswith("codex_model_responses_unsupported"):
        return {
            "error": "该模型已出现在模型列表中，但不能通过 Codex 必需的 Responses API 执行工具调用，配置未写入。请选择标注支持 Codex / Responses API 的文本模型。",
            "code": "codex_model_responses_unsupported",
            "action": "choose_compatible_model",
        }
    if detail.startswith("codex_responses_endpoint_unavailable"):
        return {
            "error": "当前模型站没有为所选模型提供 Codex 必需的 Responses API，配置未写入。请更换兼容模型，或联系模型站开通 /v1/responses。",
            "code": "codex_responses_endpoint_unavailable",
            "action": "choose_compatible_model",
        }
    if detail.startswith("codex_responses_auth_failed"):
        return {
            "error": "模型站拒绝了当前 API Key，配置未写入。请重新登录模型账号或检查密钥是否有效。",
            "code": "codex_responses_auth_failed",
            "action": "review_api_key" if custom_provider else "open_model_account",
        }
    if detail.startswith("codex_responses_permission_denied"):
        return {
            "error": "当前账号没有调用该模型或 Responses API 的权限，配置未写入。请更换有权限的模型或账号。",
            "code": "codex_responses_permission_denied",
            "action": "choose_compatible_model",
        }
    if detail.startswith("codex_responses_rate_limited"):
        return {
            "error": "模型站当前限流，配置未写入。请稍后重试；若持续出现，请检查账号额度。",
            "code": "codex_responses_rate_limited",
            "action": "retry_model_config",
        }
    if detail.startswith("codex_responses_service_unavailable"):
        return {
            "error": "模型站或上游服务暂时不可用，配置未写入。请稍后重试或更换模型。",
            "code": "codex_responses_service_unavailable",
            "action": "retry_model_config",
        }
    if detail.startswith("codex_responses_network_failed"):
        return {
            "error": "无法连接模型站，配置未写入。请检查网络、代理和 Base URL 后重试。",
            "code": "codex_responses_network_failed",
            "action": "retry_model_config",
        }
    if detail.startswith("remote_responses_probe_failed"):
        return {
            "error": "模型连接验证失败，配置没有写入。该模型未通过 Codex Responses API 与原生工具调用验证，请更换兼容模型；完整原因已写入系统日志。",
            "code": "codex_responses_probe_failed",
            "action": "choose_compatible_model",
        }
    if detail.startswith("codex_config_busy"):
        return {
            "error": "另一个 Codex 配置任务正在执行，请稍后再试。",
            "code": "codex_config_busy",
            "action": "retry_model_config",
        }
    if detail.startswith(("codex_windows_sandbox_unusable", "codex_windows_sandbox_invalid")):
        return {
            "error": "Codex 当前的 Windows 沙盒无法创建。麓鸣没有写入模型配置；请在 Codex 设置中恢复可用的 Windows 沙盒模式后重试。",
            "code": "codex_windows_sandbox_unusable",
            "action": "review_codex_sandbox",
        }
    if detail.startswith("codex_config_recovery_required"):
        return {
            "error": "Codex 配置失败且自动恢复未完成，请保留日志并重新启动麓鸣后再试。",
            "code": "codex_config_recovery_required",
            "action": "restart_loom",
        }
    if detail.startswith("claude_config_recovery_required"):
        return {
            "error": "Claude Code 配置失败且自动恢复未完成，请保留日志并重新启动麓鸣后再试。",
            "code": "claude_config_recovery_required",
            "action": "restart_loom",
        }
    if detail.startswith("codex_official_restore_unmanaged_config"):
        return {
            "error": "检测到不属于麓鸣的 Codex 配置，为避免覆盖你的设置，已停止恢复。",
            "code": "codex_official_restore_unmanaged_config",
            "action": "review_system_log",
        }
    if detail.startswith(("codex_session_preservation_failed", "claude_session_preservation_failed")):
        return {
            "error": "检测到原有会话目录或会话数量发生变化，模型配置已停止并已自动回滚。请确认会话目录可访问后重试。",
            "code": "agent_session_preservation_failed",
            "action": "review_system_log",
        }
    return {
        "error": detail or "模型配置写入失败",
        "code": "model_config_write_failed",
        "action": "retry_model_config",
    }


def _model_config_error_text(error: Exception) -> str:
    return _model_config_error_payload(error)["error"]


def _provider_probe_error_payload(error: WireConfigError) -> tuple[dict, int]:
    detail = error.to_dict()
    code = str(detail.get("code") or "provider_probe_failed")
    status_code = detail.get("statusCode")
    if type(status_code) is not int or not 400 <= status_code <= 599:
        status_code = 503 if detail.get("retryable") is True else 400
    if code in {"authentication_failed", "provider_auth_failed"}:
        action = "review_api_key"
    elif code in {"protocol_endpoint_not_found", "selected_model_not_listed"}:
        action = "review_provider_settings"
    else:
        action = "retry_provider_probe"
    return ({
        "error": str(detail.get("messageZh") or "Provider 兼容性探测失败，请检查配置后重试。"),
        "code": code,
        "action": action,
        "retryable": detail.get("retryable") is True,
        "statusCode": detail.get("statusCode"),
    }, status_code)


def _log_model_config_failure(ctx, component_id: str, error: Exception) -> None:
    append_log = getattr(ctx, "append_log", None)
    if callable(append_log):
        append_log(f"[ModelConfig] {component_id} validation failed: {error}\n")


def register_component_routes(app, ctx) -> None:
    start_jobs_lock = threading.Lock()
    active_start_jobs: dict[str, str] = {}

    @app.api_route("/api/components/status", methods=["GET", "POST"])
    async def components_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        _reconcile_orphaned_start_states(ctx)
        return ctx.fastapi_json(_component_catalog(ctx).status())

    @app.get("/api/components/model-config/status")
    async def components_model_config_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        component_id = str(request.query_params.get("componentId") or request.query_params.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        status = _model_config_status(ctx, component_id)
        return ctx.fastapi_json({"status": status})

    @app.post("/api/components/model-config/probe-provider")
    async def components_model_config_probe_provider(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        provider = str(body.get("provider") or "").strip()
        base_url = str(body.get("baseUrl") or "").strip()
        api_key = str(body.get("apiKey") or "").strip()
        preferred_model = str(
            body.get("preferredModel") or body.get("model") or ""
        ).strip()
        if not base_url or not api_key:
            return ctx.fastapi_json({
                "error": "请填写 Provider Base URL 和 API Key。",
                "code": "provider_probe_input_required",
                "action": "review_provider_settings",
            }, 400)
        try:
            probe = await run_in_threadpool(
                ctx.get_wire_svc().probe_provider_compatibility,
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                preferred_model=preferred_model,
            )
        except WireConfigError as exc:
            payload, status_code = _provider_probe_error_payload(exc)
            return ctx.fastapi_json(payload, status_code)
        return ctx.fastapi_json({"probe": probe})

    @app.post("/api/components/model-config/apply")
    async def components_model_config_apply(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        model = str(body.get("model") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "写入模型配置需要确认"}, 403)
        current = _model_config_status(ctx, component_id)
        if current.get("installed") is False:
            return ctx.fastapi_json({"error": "请先安装或检测该智能体", "status": current}, 400)
        managed_account_model_verified = False
        account_manager_getter = getattr(ctx, "get_newapi_account_mgr", None)
        if callable(account_manager_getter):
            try:
                account_manager = account_manager_getter()
                account_session = account_manager.current()
                if isinstance(account_session, dict) and account_session.get("source") == ACCOUNT_SOURCE:
                    await run_in_threadpool(
                        account_manager.ensure_launcher_token,
                        force_refresh=True,
                    )
                    current = _model_config_status(ctx, component_id)
                    available_models = [
                        str(item).strip()
                        for item in current.get("availableModels", [])
                        if str(item).strip()
                    ]
                    if model and available_models:
                        matched_model = next(
                            (
                                item
                                for item in available_models
                                if item.casefold() == model.casefold()
                            ),
                            "",
                        )
                        if not matched_model:
                            return ctx.fastapi_json({
                                "error": (
                                    "所选模型已不在当前账号最新的可用目录中，配置未写入。"
                                    "模型目录已刷新，请重新选择后再试。"
                                ),
                                "code": "selected_model_not_listed",
                                "action": "choose_compatible_model",
                                "status": current,
                            }, 409)
                        model = matched_model
                        managed_account_model_verified = True
            except NewApiAccountError as exc:
                append_log = getattr(ctx, "append_log", None)
                if callable(append_log):
                    append_log(f"[ModelConfig] launcher API Key preparation failed: {exc}\n")
                error_text = str(exc or "").strip().lower()
                upstream_status = getattr(exc, "status_code", None)
                relogin_required = any(token in error_text for token in (
                    "requires re-login",
                    "permission_contract_invalid",
                    "not_logged_in",
                    "missing_api_token",
                    "http_401",
                    "http_403",
                )) or upstream_status in {401, 403}
                rate_limited = upstream_status == 429 or "http_429" in error_text
                upstream_unavailable = (
                    upstream_status in {502, 503, 504}
                    or any(token in error_text for token in (
                        "http_502",
                        "http_503",
                        "http_504",
                        "network_error",
                        "timed out",
                        "timeout",
                    ))
                )
                cached_models = [
                    str(item).strip()
                    for item in current.get("availableModels", [])
                    if str(item).strip()
                ]
                cached_model = next(
                    (
                        item
                        for item in cached_models
                        if model and item.casefold() == model.casefold()
                    ),
                    "",
                )
                use_cached_catalog = bool(upstream_unavailable and cached_model)
                if use_cached_catalog:
                    model = cached_model
                    managed_account_model_verified = True
                    if callable(append_log):
                        append_log(
                            "[ModelConfig] transient catalog refresh failure; "
                            f"validating cached model remotely: {model}\n"
                        )
                if rate_limited:
                    response_error = "模型目录刷新受到限流，原配置未修改。请稍后重试。"
                    response_code = "model_catalog_rate_limited"
                    response_action = "retry_model_config"
                    response_status = 429
                elif upstream_unavailable:
                    response_error = "模型站或上游服务暂时不可用，模型目录无法刷新，原配置未修改。请稍后重试。"
                    response_code = "model_catalog_refresh_unavailable"
                    response_action = "retry_model_config"
                    response_status = 503
                elif relogin_required:
                    response_error = "模型账号登录状态已过期或版本过旧，配置未写入。请重新登录模型账号后再试"
                    response_code = "account_relogin_required"
                    response_action = "open_model_account"
                    response_status = 400
                else:
                    response_error = "无法自动创建可用 API Key，配置未写入。请检查模型账号后重试"
                    response_code = "api_key_unavailable"
                    response_action = "retry_model_config"
                    response_status = 400
                if not use_cached_catalog:
                    return ctx.fastapi_json({
                        "error": response_error,
                        "code": response_code,
                        "action": response_action,
                        "status": current,
                    }, response_status)
        try:
            wire_service = ctx.get_wire_svc()
            status = await run_in_threadpool(
                wire_service.sync_agent_model_config,
                component_id,
                model=model,
                validate_remote=(
                    component_id in {"codex-desktop", "pi", "grok-build"}
                    and not managed_account_model_verified
                ),
            )
        except WireConfigError as exc:
            error_payload = _model_config_error_payload(exc)
            error_text = error_payload["error"]
            _log_model_config_failure(ctx, component_id, exc)
            failed = _model_config_status(ctx, component_id)
            failed["status"] = "failed"
            failed["message"] = error_text
            return ctx.fastapi_json({**error_payload, "status": failed}, 400)
        status = dict(status)
        status["installed"] = current.get("installed")
        status["componentStatus"] = current.get("componentStatus")
        return ctx.fastapi_json({"status": status})

    @app.post("/api/components/model-config/rollback")
    async def components_model_config_rollback(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "回滚模型配置需要确认"}, 403)
        try:
            status = ctx.get_wire_svc().rollback_agent_model_config(component_id)
        except WireConfigError as exc:
            failed = _model_config_status(ctx, component_id)
            failed["status"] = "failed"
            failed["message"] = str(exc)
            return ctx.fastapi_json({"error": str(exc), "status": failed}, 400)
        return ctx.fastapi_json({"status": _with_install_state(ctx, component_id, status)})

    @app.post("/api/components/model-config/apply-custom")
    async def components_model_config_apply_custom(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "写入自定义模型配置需要确认"}, 403)
        current = _model_config_status(ctx, component_id)
        if current.get("installed") is False:
            return ctx.fastapi_json({"error": "请先安装或检测该智能体", "status": current}, 400)
        try:
            status = await run_in_threadpool(
                ctx.get_wire_svc().sync_custom_agent_model_config,
                component_id,
                provider=str(body.get("provider") or "").strip(),
                base_url=str(body.get("baseUrl") or "").strip(),
                api_key=str(body.get("apiKey") or "").strip(),
                model=str(body.get("model") or "").strip(),
            )
        except WireConfigError as exc:
            error_payload = _model_config_error_payload(exc, custom_provider=True)
            error_text = error_payload["error"]
            _log_model_config_failure(ctx, component_id, exc)
            failed = dict(current)
            failed["status"] = "failed"
            failed["message"] = error_text
            return ctx.fastapi_json({**error_payload, "status": failed}, 400)
        status = dict(status)
        status["installed"] = current.get("installed")
        status["componentStatus"] = current.get("componentStatus")
        return ctx.fastapi_json({"status": status})

    @app.post("/api/components/model-config/disable")
    async def components_model_config_disable(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "恢复 OpenAI 官方渠道需要确认"}, 403)
        current = _model_config_status(ctx, component_id)
        try:
            status = await run_in_threadpool(
                ctx.get_wire_svc().disable_agent_model_config,
                component_id,
            )
        except WireConfigError as exc:
            error_text = _model_config_error_text(exc)
            failed = dict(current)
            failed["status"] = "failed"
            failed["message"] = error_text
            return ctx.fastapi_json({"error": error_text, "status": failed}, 400)
        status = dict(status)
        status["installed"] = current.get("installed")
        status["componentStatus"] = current.get("componentStatus")
        return ctx.fastapi_json({"status": status})

    @app.post("/api/components/install")
    async def components_install(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        mode = str(body.get("mode") or "").strip().lower()
        simulate = bool(body.get("dryRun")) or mode == "simulate"
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not simulate and not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "安装组件需要确认"}, 403)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        state_store = _component_state_store(ctx)
        existing_state = state_store.load().get(component_id)
        if existing_state and existing_state.job_id:
            existing_job = ctx.get_job_mgr().get(existing_state.job_id)
            if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                return ctx.fastapi_json({
                    "jobId": existing_state.job_id,
                    "job": existing_job,
                    "state": existing_state.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }, 202)

        try:
            component, manifest_error = _resolve_component_for_action(
                manifest_path,
                component_id,
                allow_fallback=simulate,
            )
            if component is None:
                return ctx.fastapi_json({"error": manifest_error or f"Unknown component: {component_id}"}, _component_error_status(manifest_error))

            definition = DECLARATIVE_AGENT_CATALOG.by_id(component_id)
            if not simulate and definition is not None and definition.install_locked:
                return ctx.fastapi_json(
                    {
                        "error": f"{definition.name} 当前仅支持安全探测；请通过官方入口完成安装后重新检测。",
                        "code": "official_manual_install_required",
                        "officialUrl": definition.official_url,
                        "catalog": _component_catalog(ctx).status(),
                    },
                    409,
                )

            if not simulate:
                state_store.mark(component.component_id, "resolving_manifest", version=component.version)
            job_mgr = ctx.get_job_mgr()

            def run(job_id: str) -> dict:
                def on_progress(message: str, tone: str = "neutral") -> None:
                    job_mgr.progress(job_id, message, tone, componentId=component.component_id)
                    ctx.append_log(f"[Components] {component.component_id}: {message}\n")

                installer = _component_installer(ctx)
                try:
                    state = installer.install(component, simulate=simulate, job_id=job_id, on_progress=on_progress)
                except ComponentInstallError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        **exc.to_payload(),
                        "catalog": _component_catalog(ctx).status(),
                    }
                if state.status == "manual_install_required":
                    return {
                        "success": False,
                        "manualRequired": True,
                        "message": state.error_message or f"请完成 {component.name} 的外部安装步骤",
                        "state": state.to_json(),
                        "catalog": _component_catalog(ctx).status(),
                    }
                return {
                    "success": True,
                    "state": state.to_json(),
                    "catalog": _component_catalog(ctx).status(state_overrides=[state] if simulate else []),
                }

            job_kind = "component.install.simulate" if simulate else "component.install"
            job_label = f"Dry run install {component.name}" if simulate else f"Install {component.name}"
            job = job_mgr.submit_progress(job_kind, job_label, run)
            current_state = ComponentState(component.component_id, "resolving_manifest", version=component.version, job_id=str(job.get("id") or "")) if simulate else state_store.load().get(component.component_id)
            if not simulate and current_state and current_state.status == "resolving_manifest":
                current_state = state_store.mark(component.component_id, "resolving_manifest", version=component.version, job_id=str(job.get("id") or ""))
            return ctx.fastapi_json({
                "jobId": job.get("id"),
                "job": job,
                "state": current_state.to_json() if current_state else None,
                "catalog": _component_catalog(ctx).status(),
            }, 202)
        except ComponentInstallError as exc:
            return ctx.fastapi_json(
                {
                    "error": str(exc),
                    **exc.to_payload(),
                    "catalog": _component_catalog(ctx).status(),
                },
                500,
            )
        except Exception as exc:
            ctx.append_log(f"[Components] install failed: {exc}\n")
            return ctx.fastapi_json({"error": str(exc)}, 500)

    @app.post("/api/components/detect")
    async def components_detect(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        force_external_probe = _truthy(body.get("force"))
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        component, manifest_error = _resolve_component_for_action(manifest_path, component_id, allow_fallback=False)
        if component is None:
            return ctx.fastapi_json({"error": manifest_error or f"Unknown component: {component_id}"}, _component_error_status(manifest_error))

        job_mgr = ctx.get_job_mgr()

        def run(job_id: str) -> dict:
            def on_progress(message: str, tone: str = "neutral") -> None:
                job_mgr.progress(job_id, message, tone, componentId=component.component_id)
                ctx.append_log(f"[Components] {component.component_id}: {message}\n")

            installer = _component_installer(ctx)
            try:
                state = installer.detect(
                    component,
                    job_id=job_id,
                    on_progress=on_progress,
                    force_external_probe=force_external_probe,
                )
            except ComponentInstallError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "catalog": _component_catalog(ctx).status(),
                }
            return {
                "success": True,
                "state": state.to_json(),
                "catalog": _component_catalog(ctx).status(),
                "manifestWarning": manifest_error,
            }

        job = job_mgr.submit_progress("component.detect", f"Detect {component.name}", run)
        current_state = ComponentState(component.component_id, "health_checking", version=component.version, job_id=str(job.get("id") or ""))
        return ctx.fastapi_json({
            "jobId": job.get("id"),
            "job": job,
            "state": current_state.to_json(),
            "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
            "manifestWarning": manifest_error,
        }, 202)

    @app.post("/api/components/start")
    async def components_start(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "启动组件需要确认"}, 403)

        job_mgr = ctx.get_job_mgr()
        state_store = _component_state_store(ctx)
        with start_jobs_lock:
            existing_state = state_store.load().get(component_id)
            existing_job_id = active_start_jobs.get(component_id) or (existing_state.job_id if existing_state else None)
            if existing_job_id:
                existing_job = job_mgr.get(existing_job_id)
                if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                    return ctx.fastapi_json({
                        "jobId": existing_job_id,
                        "job": existing_job,
                        "state": existing_state.to_json() if existing_state else None,
                        "catalog": _component_catalog(ctx).status(),
                    }, 202)
                active_start_jobs.pop(component_id, None)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        component, manifest_error = _resolve_component_for_action(manifest_path, component_id, allow_fallback=False)
        if component is None:
            return ctx.fastapi_json({"error": manifest_error or f"Unknown component: {component_id}"}, _component_error_status(manifest_error))

        registration_finished = threading.Event()
        registration_committed = threading.Event()

        def run(job_id: str) -> dict:
            registration_finished.wait()
            if not registration_committed.is_set():
                return {
                    "success": False,
                    "error": "组件启动注册失败，未执行启动",
                    "catalog": _component_catalog(ctx).status(),
                }
            try:
                job_mgr.progress(job_id, f"启动 {component.name}", "neutral", componentId=component.component_id)
                ctx.append_log(f"[Components] {component.component_id}: 启动 {component.name}\n")
                try:
                    launch = _component_installer(ctx).launch(component, job_id=job_id)
                except ComponentInstallError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        "catalog": _component_catalog(ctx).status(),
                    }
                return {
                    "success": True,
                    "launch": launch,
                    "catalog": _component_catalog(ctx).status(),
                    "manifestWarning": manifest_error,
                }
            finally:
                with start_jobs_lock:
                    if active_start_jobs.get(component_id) == job_id:
                        active_start_jobs.pop(component_id, None)

        with start_jobs_lock:
            existing_job_id = active_start_jobs.get(component_id)
            existing_state = state_store.load().get(component_id)
            if not existing_job_id and existing_state and existing_state.job_id:
                existing_job_id = existing_state.job_id
            if existing_job_id:
                existing_job = job_mgr.get(existing_job_id)
                if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                    current_state = existing_state or ComponentState(
                        component.component_id,
                        "starting",
                        version=component.version,
                        job_id=existing_job_id,
                    )
                    return ctx.fastapi_json({
                        "jobId": existing_job_id,
                        "job": existing_job,
                        "state": current_state.to_json(),
                        "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
                    }, 202)
                active_start_jobs.pop(component_id, None)

            job = job_mgr.submit_progress("component.start", f"Start {component.name}", run)
            job_id = str(job.get("id") or "")
            active_start_jobs[component_id] = job_id
            try:
                persisted_status = existing_state.status if existing_state else "not_installed"
                state_store.mark(
                    component.component_id,
                    persisted_status,
                    version=existing_state.version if existing_state else component.version,
                    job_id=job_id,
                )
                current_state = ComponentState(
                    component.component_id,
                    "starting",
                    version=existing_state.version if existing_state else component.version,
                    job_id=job_id,
                )
                registration_committed.set()
            finally:
                registration_finished.set()
        return ctx.fastapi_json({
            "jobId": job_id,
            "job": job,
            "state": current_state.to_json(),
            "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
            "manifestWarning": manifest_error,
        }, 202)

    @app.post("/api/components/uninstall")
    async def components_uninstall(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "卸载组件需要确认"}, 403)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        component, manifest_error = _resolve_component_for_action(manifest_path, component_id, allow_fallback=False)
        if component is None:
            return ctx.fastapi_json({"error": manifest_error or f"Unknown component: {component_id}"}, _component_error_status(manifest_error))

        state_store = _component_state_store(ctx)
        existing_state = state_store.load().get(component_id)
        if existing_state and existing_state.job_id:
            existing_job = ctx.get_job_mgr().get(existing_state.job_id)
            if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                return ctx.fastapi_json({
                    "jobId": existing_state.job_id,
                    "job": existing_job,
                    "state": existing_state.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }, 202)

        job_mgr = ctx.get_job_mgr()

        def run(job_id: str) -> dict:
            def on_progress(message: str, tone: str = "neutral") -> None:
                job_mgr.progress(job_id, message, tone, componentId=component.component_id)
                ctx.append_log(f"[Components] {component.component_id}: {message}\n")

            try:
                state = _component_installer(ctx).uninstall(component, job_id=job_id, on_progress=on_progress)
            except ComponentInstallError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "catalog": _component_catalog(ctx).status(),
                }
            return {
                "success": True,
                "state": state.to_json(),
                "catalog": _component_catalog(ctx).status(),
                "manifestWarning": manifest_error,
            }

        job = job_mgr.submit_progress("component.uninstall", f"Uninstall {component.name}", run)
        current_state = state_store.mark(component.component_id, "uninstalling", version=component.version, job_id=str(job.get("id") or ""))
        return ctx.fastapi_json({
            "jobId": job.get("id"),
            "job": job,
            "state": current_state.to_json(),
            "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
            "manifestWarning": manifest_error,
        }, 202)

    @app.post("/api/components/restart")
    async def components_restart(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "重启组件需要确认"}, 403)

        manifest_path = default_manifest_path(ctx.paths.base_path)
        component, manifest_error = _resolve_component_for_action(manifest_path, component_id, allow_fallback=False)
        if component is None:
            return ctx.fastapi_json({"error": manifest_error or f"Unknown component: {component_id}"}, _component_error_status(manifest_error))

        state_store = _component_state_store(ctx)
        existing_state = state_store.load().get(component_id)
        if existing_state is None or existing_state.status not in {"ready", "started"}:
            return ctx.fastapi_json({"error": "Codex 尚未就绪，请先重新检测"}, 400)

        job_mgr = ctx.get_job_mgr()
        registration_finished = threading.Event()
        registration_committed = threading.Event()

        def run(job_id: str) -> dict:
            registration_finished.wait()
            if not registration_committed.is_set():
                return {
                    "success": False,
                    "error": "组件重启注册失败，未执行重启",
                    "catalog": _component_catalog(ctx).status(),
                }
            try:
                job_mgr.progress(job_id, f"重启 {component.name}", "neutral", componentId=component.component_id)
                ctx.append_log(f"[Components] {component.component_id}: 重启 {component.name}\n")
                try:
                    result = _component_installer(ctx).restart(component, job_id=job_id)
                except ComponentInstallError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        "catalog": _component_catalog(ctx).status(),
                    }
                return {
                    "success": True,
                    "restart": result,
                    "catalog": _component_catalog(ctx).status(),
                    "manifestWarning": manifest_error,
                }
            finally:
                with start_jobs_lock:
                    if active_start_jobs.get(component_id) == job_id:
                        active_start_jobs.pop(component_id, None)

        with start_jobs_lock:
            existing_job_id = active_start_jobs.get(component_id)
            latest_state = state_store.load().get(component_id) or existing_state
            if not existing_job_id and latest_state.job_id:
                existing_job_id = latest_state.job_id
            if existing_job_id:
                existing_job = job_mgr.get(existing_job_id)
                if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                    return ctx.fastapi_json({
                        "jobId": existing_job_id,
                        "job": existing_job,
                        "state": latest_state.to_json(),
                        "catalog": _component_catalog(ctx).status(),
                    }, 202)
                active_start_jobs.pop(component_id, None)

            job = job_mgr.submit_progress("component.restart", f"Restart {component.name}", run)
            job_id = str(job.get("id") or "")
            active_start_jobs[component_id] = job_id
            try:
                state_store.mark(
                    component.component_id,
                    latest_state.status,
                    version=latest_state.version,
                    job_id=job_id,
                )
                current_state = ComponentState(
                    component.component_id,
                    "starting",
                    version=latest_state.version,
                    job_id=job_id,
                )
                registration_committed.set()
            finally:
                registration_finished.set()
        return ctx.fastapi_json({
            "jobId": job_id,
            "job": job,
            "state": current_state.to_json(),
            "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
            "manifestWarning": manifest_error,
        }, 202)

    @app.post("/api/components/rollback")
    async def components_rollback(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        component_id = str(body.get("componentId") or body.get("id") or "").strip()
        if not component_id:
            return ctx.fastapi_json({"error": "componentId is required"}, 400)
        if not _truthy(body.get("confirmed")):
            return ctx.fastapi_json({"error": "回滚组件需要确认"}, 403)

        state_store = _component_state_store(ctx)
        existing_state = state_store.load().get(component_id)
        if existing_state and existing_state.job_id:
            existing_job = ctx.get_job_mgr().get(existing_state.job_id)
            if existing_job and str(existing_job.get("status") or "").lower() in RUNNING_JOB_STATUSES:
                return ctx.fastapi_json({
                    "jobId": existing_state.job_id,
                    "job": existing_job,
                    "state": existing_state.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }, 202)

        job_mgr = ctx.get_job_mgr()

        def run(job_id: str) -> dict:
            job_mgr.progress(job_id, f"回滚 {component_id}", "neutral", phase="rollback", componentId=component_id)
            ctx.append_log(f"[Components] {component_id}: 回滚\n")
            try:
                state = _component_installer(ctx).rollback(component_id)
            except ComponentInstallError as exc:
                failed = state_store.mark(
                    component_id,
                    "rollback_failed",
                    job_id=job_id,
                    error_code="rollback_failed",
                    error_message=str(exc),
                )
                return {
                    "success": False,
                    "error": str(exc),
                    "state": failed.to_json(),
                    "catalog": _component_catalog(ctx).status(),
                }
            return {
                "success": True,
                "state": state.to_json(),
                "catalog": _component_catalog(ctx).status(),
            }

        job = job_mgr.submit_progress("component.rollback", f"Rollback {component_id}", run)
        current_state = state_store.mark(component_id, "rolling_back", job_id=str(job.get("id") or ""))
        return ctx.fastapi_json({
            "jobId": job.get("id"),
            "job": job,
            "state": current_state.to_json(),
            "catalog": _component_catalog(ctx).status(state_overrides=[current_state]),
        }, 202)


def _component_catalog(ctx) -> ComponentCatalog:
    return ComponentCatalog(
        manifest_path=default_manifest_path(ctx.paths.base_path),
        state_store=_component_state_store(ctx),
        fallback_components=SIMULATION_COMPONENTS.values(),
    )


def _component_installer(ctx) -> ComponentInstaller:
    return ComponentInstaller(
        base_path=ctx.paths.base_path,
        state_store=_component_state_store(ctx),
        sync_user_experience=True,
    )


def _component_state_store(ctx) -> ComponentStateStore:
    return ComponentStateStore(default_component_state_path(ctx.paths.base_path))


def _reconcile_orphaned_start_states(ctx) -> None:
    state_store = _component_state_store(ctx)
    states = state_store.load()
    job_manager_getter = getattr(ctx, "get_job_mgr", None)
    job_manager = job_manager_getter() if callable(job_manager_getter) else None
    append_log = getattr(ctx, "append_log", None)
    interrupted_states = {
        "starting": (
            "start_failed",
            "start_interrupted",
            "上次启动任务已中断，请重新检测后再次启动",
        ),
        "resolving_manifest": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "downloading": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "verifying": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "extracting": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "configuring": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "health_checking": (
            "download_failed",
            "install_interrupted",
            "上次安装任务已中断，请重新检测后再次安装",
        ),
        "uninstalling": (
            "uninstall_failed",
            "uninstall_interrupted",
            "上次卸载任务已中断，请重新检测后再次卸载",
        ),
        "rolling_back": (
            "rollback_failed",
            "rollback_interrupted",
            "上次回滚任务已中断，请重新检测后再次回滚",
        ),
    }
    for state in states.values():
        recovery = interrupted_states.get(state.status)
        if recovery is None:
            continue
        job = job_manager.get(state.job_id) if job_manager is not None and state.job_id else None
        job_status = str((job or {}).get("status") or "").lower()
        if job_status in RUNNING_JOB_STATUSES:
            continue
        detail = str((job or {}).get("error") or (job or {}).get("message") or "").strip()
        failed_status, error_code, default_message = recovery
        message = detail or default_message
        state_store.mark(
            state.component_id,
            failed_status,
            version=state.version,
            job_id=state.job_id,
            error_code=error_code,
            error_message=message,
        )
        if callable(append_log):
            append_log(f"[Components] recovered orphaned state for {state.component_id}: {message}\n")


def _model_config_status(ctx, component_id: str) -> dict:
    status = ctx.get_wire_svc().agent_model_config_status(component_id)
    return _with_install_state(ctx, component_id, status)


def _with_install_state(ctx, component_id: str, status: dict) -> dict:
    item = _component_by_id(ctx, component_id)
    component_status = str((item or {}).get("status") or "not_installed")
    installed = component_status in {"ready", "started", "starting", "start_failed", "upgrade_available"}
    result = dict(status)
    result["installed"] = installed
    result["componentStatus"] = component_status
    if result.get("supported") and not installed:
        result["configured"] = False
        result["status"] = "not_installed"
        result["message"] = "请先安装或检测该智能体"
    return result


def _component_by_id(ctx, component_id: str) -> dict | None:
    try:
        for item in _component_catalog(ctx).status().get("components", []):
            if item.get("id") == component_id:
                return item
    except Exception:
        return None
    return None
