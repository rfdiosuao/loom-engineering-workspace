"""HTTP API bridge - bridges Tauri frontend to Python backend modules."""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Ensure the python package root is on sys.path
_python_dir = os.path.dirname(os.path.abspath(__file__))
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

from core.paths import AppPaths
from core.storage import read_json, write_json, update_json
from core.license_manager import LicenseManager
from core.member_manager import MemberManager
from core.newapi_account_manager import NewApiAccountManager
from core.theme_manager import ThemeManager
from services.process import OpenClawProcessService
from services.desktop_agent import DesktopAgentService
from services.image_api import ImageApiClient
from services.video_api import DashScopeVideoClient
from services.updater import OpenClawUpdater
from services.skills import SkillService
from services.jobs import JobManager
from services.phone_scheduler import PhoneAutomationScheduler

paths = AppPaths.discover()
log_buffer: list[str] = []
log_lock = threading.Lock()
DEFAULT_OPENCLAW_TEXT_MODEL = "qwen3.7-plus"
MANAGED_ACCOUNT_SOURCES = {"newapi_account", "heang_account"}

def append_log(text: str) -> None:
    with log_lock:
        log_buffer.append(text)
        if len(log_buffer) > 500:
            log_buffer[:] = log_buffer[-500:]
    try:
        log_dir = os.path.join(paths.data_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "bridge-service.log"), "a", encoding="utf-8") as file:
            file.write(text)
    except Exception:
        pass

def append_log_ui(text: str) -> None:
    append_log(text)

def ui_call(func, *args) -> None:
    func(*args)

# Create service instances
_license_mgr: LicenseManager | None = None
_member_mgr: MemberManager | None = None
_newapi_account_mgr: NewApiAccountManager | None = None
_process_svc: OpenClawProcessService | None = None
_desktop_agent_svc: DesktopAgentService | None = None
_updater: OpenClawUpdater | None = None
_image_client: ImageApiClient | None = None
_video_client: DashScopeVideoClient | None = None
_theme_mgr: ThemeManager | None = None
_skill_svc: SkillService | None = None
_job_mgr: JobManager | None = None
_phone_scheduler: PhoneAutomationScheduler | None = None
_cache_lock = threading.Lock()
_cache_store: dict[str, tuple[float, object]] = {}

PROTECTED_PATHS = {
    "/api/process/start",
    "/api/image/generate",
    "/api/image/generate_job",
    "/api/video/generate",
    "/api/video/generate_job",
}

def _get_license_mgr() -> LicenseManager:
    global _license_mgr
    if _license_mgr is None:
        _license_mgr = LicenseManager(paths)
    return _license_mgr

def _get_member_mgr() -> MemberManager:
    global _member_mgr
    if _member_mgr is None:
        _member_mgr = MemberManager(paths)
    return _member_mgr

def _get_newapi_account_mgr() -> NewApiAccountManager:
    global _newapi_account_mgr
    if _newapi_account_mgr is None:
        _newapi_account_mgr = NewApiAccountManager(paths, append_log)
    return _newapi_account_mgr

def _get_process_svc() -> OpenClawProcessService:
    global _process_svc
    if _process_svc is None:
        _process_svc = OpenClawProcessService(paths, append_log_ui, ui_call)
    return _process_svc

def _get_desktop_agent_svc() -> DesktopAgentService:
    global _desktop_agent_svc
    if _desktop_agent_svc is None:
        _desktop_agent_svc = DesktopAgentService(paths, append_log_ui)
    return _desktop_agent_svc

def _get_updater() -> OpenClawUpdater:
    global _updater
    if _updater is None:
        _updater = OpenClawUpdater(paths)
    return _updater

def _get_image_client() -> ImageApiClient:
    global _image_client
    if _image_client is None:
        _image_client = ImageApiClient()
    return _image_client

def _get_video_client() -> DashScopeVideoClient:
    global _video_client
    if _video_client is None:
        _video_client = DashScopeVideoClient()
    return _video_client

def _get_theme_mgr() -> ThemeManager:
    global _theme_mgr
    if _theme_mgr is None:
        _theme_mgr = ThemeManager(paths)
    return _theme_mgr

def _get_skill_svc() -> SkillService:
    global _skill_svc
    if _skill_svc is None:
        _skill_svc = SkillService(paths)
    return _skill_svc

def _get_job_mgr() -> JobManager:
    global _job_mgr
    if _job_mgr is None:
        _job_mgr = JobManager(append_log)
    return _job_mgr

def _get_phone_scheduler() -> PhoneAutomationScheduler:
    global _phone_scheduler
    if _phone_scheduler is None:
        _phone_scheduler = PhoneAutomationScheduler(paths, append_log)
    return _phone_scheduler

def _cached(key: str, ttl: float, builder: Callable[[], object]) -> object:
    now = time.time()
    with _cache_lock:
        item = _cache_store.get(key)
        if item and item[0] > now:
            return copy.deepcopy(item[1])
    value = builder()
    with _cache_lock:
        _cache_store[key] = (now + max(0.1, ttl), copy.deepcopy(value))
    return value

def _invalidate_cache(prefix: str = "") -> None:
    with _cache_lock:
        if not prefix:
            _cache_store.clear()
            return
        for key in list(_cache_store):
            if key.startswith(prefix):
                _cache_store.pop(key, None)


def _provider_id_from_base_url(base_url: str, fallback: str) -> str:
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    host = parsed.netloc or parsed.path or fallback
    host = host.split("@")[-1].split(":")[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or fallback
    return f"custom-{slug}"


def _model_definition(model_id: str) -> dict:
    # Qwen thinking over OpenAI-compatible gateways may require provider-specific
    # limits. Mark it as plain text here so OpenClaw does not emit an invalid
    # thinking_budget/max_completion_tokens pair by default.
    is_reasoning = model_id.startswith(("claude", "o1", "o3", "o4", "deepseek-reasoner"))
    context_window = 200000 if model_id.startswith("claude") else 128000
    max_tokens = 32000
    if model_id.startswith("qwen3"):
        context_window = 16000000
        max_tokens = 4096000
    return {
        "id": model_id,
        "name": f"{model_id} (Custom Provider)",
        "reasoning": is_reasoning,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": context_window,
        "maxTokens": max_tokens,
        "api": "openai-completions",
    }


def _looks_like_non_text_model(model_id: str) -> bool:
    text = model_id.lower()
    markers = (
        "image",
        "dall-e",
        "gpt-image",
        "flux",
        "midjourney",
        "mj-",
        "stable-diffusion",
        "sd-",
        "imagen",
        "seedream",
        "video",
        "veo",
        "sora",
        "seedance",
        "kling",
        "wan",
        "hailuo",
        "runway",
        "pika",
        "luma",
        "happyhorse",
    )
    return any(marker in text for marker in markers)


def _text_model_ids(raw_models: list, default_model: str = "") -> list[str]:
    model_ids: list[str] = []
    for item in raw_models:
        model_id = item.get("id") if isinstance(item, dict) else item
        if isinstance(model_id, str):
            model_id = model_id.strip()
            if model_id and not _looks_like_non_text_model(model_id) and model_id not in model_ids:
                model_ids.append(model_id)
    default_model = default_model.strip()
    if default_model and not _looks_like_non_text_model(default_model):
        model_ids = [default_model] + [model_id for model_id in model_ids if model_id != default_model]
    if DEFAULT_OPENCLAW_TEXT_MODEL in model_ids:
        model_ids = [DEFAULT_OPENCLAW_TEXT_MODEL] + [model_id for model_id in model_ids if model_id != DEFAULT_OPENCLAW_TEXT_MODEL]
    elif not model_ids:
        model_ids = [DEFAULT_OPENCLAW_TEXT_MODEL]
    return model_ids


def _repair_openclaw_config_contract() -> dict:
    """Remove launcher-only fields that OpenClaw core config validation rejects."""
    oc = read_json(paths.openclaw_config, {})
    if not isinstance(oc, dict):
        return {}
    if "launcherPreview" in oc:
        del oc["launcherPreview"]
        write_json(paths.openclaw_config, oc)
    return oc


def _sync_openclaw_models_from_api_profiles() -> None:
    """Keep launcher API settings compatible with OpenClaw 2026.5+ model config."""
    _repair_openclaw_config_contract()
    gateway_profile = _get_license_mgr().current_gateway_profile()
    if gateway_profile:
        base_url = str(gateway_profile.get("baseUrl") or "").strip().rstrip("/")
        api_key = str(gateway_profile.get("apiKey") or "").strip()
        default_model = str(gateway_profile.get("defaultModel") or "").strip()
        model_ids = _text_model_ids(gateway_profile.get("models") or [], default_model)
        if not base_url or not api_key or not model_ids:
            return

        provider_id = _provider_id_from_base_url(base_url, "member")
        primary_model = default_model or model_ids[0]
        if primary_model not in model_ids:
            primary_model = model_ids[0]
        managed_by = str(gateway_profile.get("managedBy") or gateway_profile.get("source") or "").strip()
        model_ref = f"{provider_id}/{primary_model}"
        provider_config = {
            "baseUrl": base_url,
            "apiKey": api_key,
            "api": "openai-completions",
            "models": [_model_definition(model_id) for model_id in model_ids],
        }
        if managed_by in MANAGED_ACCOUNT_SOURCES:
            provider_config["managedBy"] = managed_by

        agent_dir = os.path.dirname(paths.auth_profiles)
        models_path = os.path.join(agent_dir, "models.json")
        models_json = read_json(models_path, {"providers": {}})
        if not isinstance(models_json, dict):
            models_json = {"providers": {}}
        models_json.setdefault("providers", {})
        models_json["providers"][provider_id] = provider_config
        write_json(models_path, models_json)

        profiles = read_json(paths.auth_profiles, {"models": {"providers": {}}})
        if not isinstance(profiles, dict):
            profiles = {"models": {"providers": {}}}
        profiles.setdefault("models", {})
        profiles["models"].setdefault("providers", {})
        profiles["models"]["providers"]["member_gateway"] = {
            "id": "member_gateway",
            "name": "会员托管",
            "authMode": "member",
            "mode": "member",
            "providerId": provider_id,
            "baseUrl": base_url,
            "apiKey": api_key,
            "api": "openai-completions",
            "models": model_ids,
            "defaultModel": primary_model,
            "gatewayDefaultModel": primary_model,
            "gatewayImageModel": str(gateway_profile.get("imageModel") or "").strip(),
            "gatewayVideoModel": str(gateway_profile.get("videoModel") or "").strip(),
        }
        if managed_by in MANAGED_ACCOUNT_SOURCES:
            profiles["models"]["providers"]["member_gateway"]["managedBy"] = managed_by
        profiles["models"]["primary"] = "member_gateway"
        write_json(paths.auth_profiles, profiles)

        oc = _repair_openclaw_config_contract()
        oc.setdefault("models", {})
        oc["models"]["mode"] = "merge"
        oc["models"].setdefault("providers", {})
        oc["models"]["providers"][provider_id] = provider_config

        oc.setdefault("agents", {})
        oc["agents"].setdefault("defaults", {})
        defaults = oc["agents"]["defaults"]
        defaults.setdefault("model", {})
        defaults["model"]["primary"] = model_ref
        defaults.setdefault("models", {})
        defaults["models"][model_ref] = {"alias": primary_model}
        write_json(paths.openclaw_config, oc)
        return

    profiles = read_json(paths.auth_profiles, {"models": {"providers": {}}})
    profile_models = profiles.get("models") if isinstance(profiles, dict) else {}
    providers = profile_models.get("providers") if isinstance(profile_models, dict) else {}
    if not isinstance(providers, dict) or not providers:
        return

    primary_key = profile_models.get("primary") if isinstance(profile_models, dict) else None
    provider = providers.get(primary_key) if primary_key else None
    if not isinstance(provider, dict):
        provider = next((p for p in providers.values() if isinstance(p, dict)), None)
    if not provider:
        return

    api_key = (provider.get("apiKey") or "").strip()
    base_url = (provider.get("baseUrl") or provider.get("url") or "").strip().rstrip("/")
    if not api_key or not base_url:
        return

    raw_models = provider.get("models") if isinstance(provider.get("models"), list) else []
    model_ids = _text_model_ids(raw_models, str(provider.get("defaultModel") or ""))
    for default_model in (DEFAULT_OPENCLAW_TEXT_MODEL, "claude-opus-4-7-medium", "kimi-k2.5", "gpt-4o"):
        if default_model not in model_ids:
            model_ids.append(default_model)
    if not model_ids:
        return

    provider_id = _provider_id_from_base_url(base_url, primary_key or "api")
    model_ref = f"{provider_id}/{model_ids[0]}"
    provider_config = {
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": "openai-completions",
        "models": [_model_definition(model_id) for model_id in model_ids],
    }

    agent_dir = os.path.dirname(paths.auth_profiles)
    models_path = os.path.join(agent_dir, "models.json")
    models_json = read_json(models_path, {"providers": {}})
    if not isinstance(models_json, dict):
        models_json = {"providers": {}}
    models_json.setdefault("providers", {})
    models_json["providers"][provider_id] = provider_config
    write_json(models_path, models_json)

    oc = _repair_openclaw_config_contract()
    oc.setdefault("models", {})
    oc["models"]["mode"] = "merge"
    oc["models"].setdefault("providers", {})
    oc["models"]["providers"][provider_id] = provider_config

    oc.setdefault("agents", {})
    oc["agents"].setdefault("defaults", {})
    defaults = oc["agents"]["defaults"]
    defaults.setdefault("model", {})
    defaults["model"]["primary"] = model_ref
    defaults.setdefault("models", {})
    defaults["models"][model_ref] = {"alias": model_ids[0]}
    write_json(paths.openclaw_config, oc)


def _has_configured_api_profile() -> bool:
    if _get_license_mgr().has_gateway_profile():
        return True
    profiles = read_json(paths.auth_profiles, {"models": {"providers": {}}})
    models = profiles.get("models") if isinstance(profiles, dict) else {}
    providers = models.get("providers") if isinstance(models, dict) else {}
    if not isinstance(providers, dict):
        return False
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        api_key = str(provider.get("apiKey") or "").strip()
        base_url = str(provider.get("baseUrl") or provider.get("url") or "").strip()
        if api_key and base_url:
            return True
    return False


def _diagnostic_summary(checks: list[dict]) -> dict:
    failed = sum(1 for item in checks if item.get("status") == "fail")
    warnings = sum(1 for item in checks if item.get("status") == "warn")
    ok = sum(1 for item in checks if item.get("status") == "ok")
    status = "fail" if failed else ("warn" if warnings else "ok")
    return {"status": status, "ok": ok, "warnings": warnings, "failed": failed, "total": len(checks)}


SENSITIVE_KEYS = {
    "apiKey",
    "api_key",
    "apikey",
    "key",
    "token",
    "accessToken",
    "access_token",
    "password",
    "secret",
    "signature",
    "dashKey",
    "appSecret",
}


def _mask_secret(value: object) -> str:
    text = str(value)
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}***{text[-4:]}"


def _sanitize_payload(value: object) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in SENSITIVE_KEYS or key_text.lower().endswith(("key", "token", "secret", "password", "signature")):
                result[key_text] = _mask_secret(item) if item else ""
            else:
                result[key_text] = _sanitize_payload(item)
        return result
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def _sanitize_text(value: str) -> str:
    value = re.sub(r"\bsk-[A-Za-z0-9_\-]{12,}\b", "sk-***", value)
    value = re.sub(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)", r"\1\2***", value)
    return value


def _startup_snapshot_path() -> str:
    return os.path.join(paths.data_dir, "logs", "openclaw-startup-snapshot.json")


def _startup_snapshot_text(snapshot: dict) -> str:
    if not isinstance(snapshot, dict):
        return ""

    lines: list[str] = []
    for key in ("timestamp", "status", "error", "exitCode", "pid", "portReady", "command", "cwd"):
        value = snapshot.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        lines.append(f"{key}={value}")

    output_tail = snapshot.get("outputTail")
    if isinstance(output_tail, list):
        lines.extend(str(line) for line in output_tail[-40:] if str(line).strip())

    return "\n".join(lines)


def _classify_startup_failure(text: str) -> list[str]:
    lower = text.lower()
    patterns = [
        ("权限拒绝", ("permission denied", "access is denied", "拒绝访问", "eacces", "eperm")),
        ("文件缺失", ("no such file", "cannot find", "找不到", "not found", "filenotfounderror", "modulenotfounderror")),
        ("端口占用", ("eaddrinuse", "address already in use", "端口占用", "port already", "listen eaddrinuse")),
        ("进程异常退出", ("process ended", "process exited", "startup did not become ready", "exited before the port became ready", "exitcode=")),
        ("Python/Bridge 缺失", ("no module named 'fastapi'", 'no module named "fastapi"', "no module named fastapi", "no module named 'uvicorn'", 'no module named "uvicorn"', "python runtime missing", "bridge dependency")),
        ("Node/OpenClaw 缺失", ("cannot find node", "找不到 node", "node.js missing", "node runtime missing", "openclaw.mjs not found", "start.js not found", "找不到启动脚本")),
        ("WebView2 缺失", ("webview2", "edgewebview")),
        ("OpenClaw 配置错误", ("invalid config", "openclaw.json", "plugin manifest", "validation", "schema")),
        ("模型参数错误", ("thinking_budget", "max_completion_tokens", "invalidparameter", "request schema")),
    ]
    hits: list[str] = []
    for label, keywords in patterns:
        if any(keyword in lower for keyword in keywords):
            hits.append(label)
    return list(dict.fromkeys(hits))


def _license_check() -> dict:
    diagnosis = _get_license_mgr().diagnose()
    code = str(diagnosis.get("code") or "unknown")
    return {
        "id": "license",
        "label": "授权状态",
        "status": "ok" if diagnosis.get("ok") else "fail",
        "message": str(diagnosis.get("message") or "授权状态未知"),
        "detail": f"{diagnosis.get('detail') or paths.license_file}；code={code}",
        "repairable": False,
    }


def _startup_failure_summary_check() -> dict:
    snapshot_path = _startup_snapshot_path()
    snapshot = read_json(snapshot_path, {}) if os.path.exists(snapshot_path) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot_status = str(snapshot.get("status") or "").lower()
    snapshot_text = _sanitize_text(_startup_snapshot_text(snapshot))

    with log_lock:
        recent_log = "".join(log_buffer[-160:])
    sanitized = _sanitize_text(recent_log)

    if snapshot_status == "fail":
        combined = "\n".join(text for text in (snapshot_text, sanitized) if text.strip())
        hits = _classify_startup_failure(combined)
        tail_lines = [line.strip() for line in combined.splitlines() if line.strip()][-12:]
        error_text = _sanitize_text(str(snapshot.get("error") or "OpenClaw 启动失败"))
        message = "最近一次核心服务启动失败"
        if hits:
            message += "，疑似：" + "、".join(hits)

        detail_lines = [
            f"snapshot={snapshot_path}",
            f"error={error_text}",
            f"exitCode={snapshot.get('exitCode')}; pid={snapshot.get('pid')}; portReady={snapshot.get('portReady')}",
        ]
        if tail_lines:
            detail_lines.append("--- captured tail ---")
            detail_lines.extend(tail_lines)

        return {
            "id": "startup_failure_summary",
            "label": "启动失败原因摘要",
            "status": "fail",
            "message": message,
            "detail": "\n".join(detail_lines),
            "repairable": True,
        }

    hits = _classify_startup_failure(sanitized)

    if not sanitized.strip():
        return {
            "id": "startup_failure_summary",
            "label": "启动失败原因摘要",
            "status": "ok",
            "message": "暂无启动失败日志",
            "detail": "最近日志为空",
            "repairable": False,
        }

    tail_lines = [line.strip() for line in sanitized.splitlines() if line.strip()][-8:]
    if hits:
        return {
            "id": "startup_failure_summary",
            "label": "启动失败原因摘要",
            "status": "warn",
            "message": "最近日志疑似包含：" + "、".join(dict.fromkeys(hits)),
            "detail": "\n".join(tail_lines),
            "repairable": False,
        }
    return {
        "id": "startup_failure_summary",
        "label": "启动失败原因摘要",
        "status": "ok",
        "message": "最近日志未匹配到常见启动失败特征",
        "detail": "\n".join(tail_lines),
        "repairable": False,
    }


def _append_runtime_checks(payload: dict) -> dict:
    checks = list(payload.get("checks", []))

    checks.append(_license_check())
    checks.append(_startup_failure_summary_check())

    api_configured = _has_configured_api_profile()
    checks.append({
        "id": "api_config",
        "label": "API 配置",
        "status": "ok" if api_configured else "warn",
        "message": "已配置模型 API" if api_configured else "未配置 API，AI 生图/视频会不可用",
        "detail": paths.auth_profiles,
        "repairable": False,
    })

    payload["checks"] = checks
    payload["summary"] = _diagnostic_summary(checks)
    payload["repairAvailable"] = any(item.get("repairable") for item in checks)
    return payload


def _build_diagnostics_payload() -> dict:
    return _append_runtime_checks(_get_process_svc().diagnose_environment())


def _read_sanitized_json(path: str, default: object = None) -> object:
    default = {} if default is None else default
    return _sanitize_payload(read_json(path, default))


class Handler(BaseHTTPRequestHandler):
    """Compatibility service used only when FastAPI is unavailable."""

    bridge_token: str | None = None

    def do_GET(self) -> None:
        self._unavailable()

    def do_POST(self) -> None:
        self._unavailable()

    def do_PUT(self) -> None:
        self._unavailable()

    def _unavailable(self) -> None:
        if Handler.bridge_token:
            req_token = self.headers.get("X-Bridge-Token")
            if req_token != Handler.bridge_token:
                self._send_json(401, {"error": "未授权的请求"})
                return
        self._send_json(
            503,
            {"error": "FastAPI bridge dependencies are required. Run pip install -r python/requirements.txt."},
        )

    def _send_json(self, code: int, data: dict) -> None:
        payload = _bridge_response_payload(data, code)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://tauri.localhost")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        pass  # Suppress default HTTP logging


def find_port(start: int = 18791, end: int = 18950) -> int:
    """Find an available port in the given range."""
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
            return port
        except OSError:
            pass
    return 0


def _legacy_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-Bridge-Token",
    }


def _bridge_response_payload(data: dict, status_code: int) -> dict:
    """Add a stable response metadata block without changing legacy fields."""
    payload = dict(data) if isinstance(data, dict) else {"data": data}
    is_ok = 200 <= status_code < 400 and "error" not in payload
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    meta = {
        **meta,
        "ok": is_ok,
        "status": status_code,
    }
    if not is_ok:
        message = str(payload.get("error") or "")
        meta["error"] = {
            "code": status_code,
            "message": message,
        }
    else:
        meta.pop("error", None)
    payload["_meta"] = meta
    return payload


def _safe_config_path(file_path: str) -> str | None:
    """Validate that the resolved path stays within allowed directories."""
    if not file_path:
        return None
    if not os.path.isabs(file_path):
        file_path = os.path.join(paths.base_path, file_path)
    real_path = os.path.realpath(file_path)
    allowed_roots = (os.path.realpath(paths.base_path), os.path.realpath(paths.data_dir))
    for root in allowed_roots:
        try:
            if os.path.commonpath([real_path, root]) == root:
                return real_path
        except ValueError:
            continue
    return None


def _fastapi_json(data: dict, status_code: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content=_bridge_response_payload(data, status_code),
        headers=_legacy_headers(),
    )


def _fastapi_auth_error(request):
    if Handler.bridge_token:
        req_token = request.headers.get("X-Bridge-Token")
        if req_token != Handler.bridge_token:
            return _fastapi_json({"error": "未授权的请求"}, 401)
    return None


def _fastapi_protected_error(path: str):
    if path in PROTECTED_PATHS and not _get_license_mgr().is_authorized():
        return _fastapi_json({"error": "需要有效的许可证才能使用此功能"}, 403)
    return None


async def _fastapi_body(request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _data_url_to_temp_file(data_url: str) -> tuple[str, str]:
    try:
        header, b64_data = data_url.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0]
        image_bytes = base64.b64decode(b64_data)
        ext = mime_type.split("/")[-1].split("+")[0]
        if ext not in ("png", "jpeg", "jpg", "webp"):
            ext = "png"
        fd, temp_file = tempfile.mkstemp(suffix=f".{ext}")
        with os.fdopen(fd, "wb") as file:
            file.write(image_bytes)
        return temp_file, temp_file
    except Exception as exc:
        raise ValueError(f"图片数据解码失败: {exc}") from exc


def _build_fastapi_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        append_log=append_log,
        append_runtime_checks=_append_runtime_checks,
        auth_error=_fastapi_auth_error,
        body=_fastapi_body,
        build_diagnostics_payload=_build_diagnostics_payload,
        cached=_cached,
        data_url_to_temp_file=_data_url_to_temp_file,
        fastapi_json=_fastapi_json,
        get_image_client=_get_image_client,
        get_desktop_agent_svc=_get_desktop_agent_svc,
        get_job_mgr=_get_job_mgr,
        get_license_mgr=_get_license_mgr,
        get_member_mgr=_get_member_mgr,
        get_newapi_account_mgr=_get_newapi_account_mgr,
        get_process_svc=_get_process_svc,
        get_phone_scheduler=_get_phone_scheduler,
        get_skill_svc=_get_skill_svc,
        get_theme_mgr=_get_theme_mgr,
        get_updater=_get_updater,
        get_video_client=_get_video_client,
        log_buffer=log_buffer,
        log_lock=log_lock,
        paths=paths,
        protected_error=_fastapi_protected_error,
        read_json=read_json,
        invalidate_cache=_invalidate_cache,
        read_sanitized_json=_read_sanitized_json,
        safe_config_path=_safe_config_path,
        sanitize_text=_sanitize_text,
        sync_openclaw_models_from_api_profiles=_sync_openclaw_models_from_api_profiles,
        write_json=write_json,
    )


def _serve_fastapi(port: int, token: str) -> None:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn

    from api.fastapi_routes import register_fastapi_routes

    app = FastAPI(
        title="OpenClaw Bridge",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(tauri\.localhost|localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "X-Bridge-Token"],
        allow_credentials=False,
    )
    register_fastapi_routes(app, _build_fastapi_context())
    _get_phone_scheduler().start()

    print(f"BRIDGE_PORT={port}", flush=True)
    print(f"BRIDGE_TOKEN={token}", flush=True)
    print("BRIDGE_IMPL=fastapi", flush=True)
    append_log(f"[Bridge] Started on port {port} (fastapi)\n")

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()

def _serve_dependency_error(port: int, token: str) -> None:
    Handler.bridge_token = token
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    actual_port = int(server.server_address[1])
    print(f"BRIDGE_PORT={actual_port}", flush=True)
    print(f"BRIDGE_TOKEN={token}", flush=True)
    print("BRIDGE_IMPL=dependency-error", flush=True)
    append_log(f"[Bridge] Started dependency error service on port {actual_port}\n")
    server.serve_forever()


def main() -> None:
    port = find_port()
    token = secrets.token_hex(32)
    Handler.bridge_token = token

    require_fastapi = os.environ.get("OPENCLAW_BRIDGE_REQUIRE_FASTAPI") == "1"

    try:
        _serve_fastapi(port, token)
        return
    except ModuleNotFoundError as error:
        if require_fastapi:
            raise
        append_log(f"[Bridge] FastAPI unavailable: {error}\n")

    _serve_dependency_error(port, token)


if __name__ == "__main__":
    main()
