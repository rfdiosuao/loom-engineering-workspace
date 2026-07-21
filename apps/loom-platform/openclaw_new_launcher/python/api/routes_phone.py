"""Phone demo configuration routes.

These endpoints only manage the launcher-side APKClaw connection store. They
never return phone tokens to the frontend.
"""

from __future__ import annotations

import os
import re
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Request

from core.secret_store import DPAPI_PROVIDER, SECRET_MARKER, protect_secret, unprotect_secret


_DEVICE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_PHONE_SCRIPT_TIMEOUT_SEC = 240
_DEFAULT_PHONE_PORT = 9527
_PHONE_TASK_MODES = {"observe", "safe", "full"}
_PHONE_TASK_PROFILES = {"fast", "standard", "deep"}
_PHONE_DIRECT_STEP_TIMEOUT_SEC = 8
_PHONE_TEMPLATE_STEP_TIMEOUT_SEC = 12
_PHONE_AGENT_STEP_TIMEOUT_SEC = 15
_PHONE_OBSERVE_STEP_TIMEOUT_SEC = 30
_PHONE_OBSERVE_TIMEOUT_SEC = 45
_PHONE_SCREENSHOT_REQUEST_TIMEOUT_MS = max(5_000, (_PHONE_OBSERVE_TIMEOUT_SEC - 5) * 1000)
_PHONE_CANCEL_GRACE_SEC = 5.0
_PHONE_SCREENSHOT_CACHE_TTL_MS = 1200
_PHONE_READ_CACHE_TTL_SEC = 30
_PHONE_REF_PREFERRED_ACTIONS = {
    "click_text",
    "tap_text",
    "click_node",
    "tap_node",
    "click_element",
    "tap_element",
    "click_description",
    "tap_description",
}
_PHONE_ACTION_FAST_ACTIONS = {
    "back",
    "home",
    "open_app",
    "refresh",
    "wait_element",
    "click_ref",
    "click_text",
    "tap_text",
    "click_node",
    "tap_node",
    "click_element",
    "tap_element",
    "click_description",
    "tap_description",
    "input",
    "input_text",
    "scroll",
}
_PHONE_READ_CACHE_LOCK = threading.Lock()
_PHONE_READ_CACHE: dict[str, dict] = {}
_PHONE_SCREENSHOT_CACHE_LOCK = threading.Lock()
_PHONE_SCREENSHOT_CACHE: dict[str, dict] = {}
_PHONE_EVENT_SYNC_LOCK = threading.Lock()
_PHONE_EVENT_SYNC_STATE: dict[str, dict] = {}
_PHONE_EVENT_SYNC_DISABLED_DEVICE_IDS: set[str] = set()
_PHONE_ACTIVE_TASK_STATUSES = frozenset(
    {"queued", "pending", "submitted", "accepted", "running", "executing", "in_progress", "in-progress"}
)
_PHONE_TASK_ROUND_CAPS = {
    "observe": 4,
    "safe": 12,
    "full": 30,
}
_PHONE_TASK_EXPLICIT_ROUND_CAPS = {
    "observe": 4,
    "safe": 120,
    "full": 120,
}
_PHONE_TASK_PROFILE_DEFAULTS = {
    "fast": {
        "observe": (45, 60, 4, 500),
        "safe": (120, 135, 12, 500),
        "full": (300, 315, 30, 500),
    },
    "standard": {
        "observe": (90, 105, 1, 800),
        "safe": (240, 260, 12, 800),
        "full": (600, 620, 30, 800),
    },
    "deep": {
        "observe": (180, 210, 1, 1200),
        "safe": (600, 630, 12, 1200),
        "full": (900, 930, 30, 1200),
    },
}
_SYNC_SECRET_KEYS = {
    "apiKey",
    "api_key",
    "accessToken",
    "access_token",
    "memberToken",
    "sessionCookie",
    "launcherToken",
    "password",
    "secret",
    "token",
}
_PHONE_STORE_SECRET_FIELDS = ("token", "launcherSecret")
_PHONE_RUNTIME_CONFIG_ENV = "LOOM_PHONE_RUNTIME_CONFIG_JSON"

OPENCLAW_ROOT = Path(__file__).resolve().parents[2]


def _phone_store_path(ctx) -> str:
    return os.path.join(ctx.paths.launcher_dir, "phone-agents.json")


def _phone_store_secret_is_protected(value: object) -> bool:
    return isinstance(value, dict) and value.get(SECRET_MARKER) == DPAPI_PROVIDER


def _decode_phone_store_secrets(store: dict) -> dict:
    decoded = {**store}
    devices: list[dict] = []
    for raw_device in store.get("devices", []):
        if not isinstance(raw_device, dict):
            continue
        device = {**raw_device}
        for field in _PHONE_STORE_SECRET_FIELDS:
            value = device.get(field)
            try:
                device[field] = unprotect_secret(value) if value else ""
            except (OSError, ValueError, TypeError):
                # DPAPI values copied from another Windows profile are not
                # usable on this machine. Keep them unavailable in memory.
                device[field] = ""
        devices.append(device)
    decoded["devices"] = devices
    return decoded


def _encode_phone_store_secrets(store: dict) -> dict:
    encoded = {**store}
    devices: list[dict] = []
    for raw_device in store.get("devices", []):
        if not isinstance(raw_device, dict):
            continue
        device = {**raw_device}
        for field in _PHONE_STORE_SECRET_FIELDS:
            value = device.get(field)
            if value and not _phone_store_secret_is_protected(value):
                device[field] = protect_secret(value)
        devices.append(device)
    encoded["devices"] = devices
    return encoded


def _write_phone_store(ctx, store: dict) -> None:
    ctx.write_json(_phone_store_path(ctx), _encode_phone_store_secrets(store))


def _clip(value: object, limit: int = 256) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _normalize_url(value: object) -> str:
    text = _clip(value, 512).rstrip("/")
    if not text:
        return ""
    text = (
        text.replace("：", ":")
        .replace("﹕", ":")
        .replace("꞉", ":")
        .replace("／", "/")
        .replace("⁄", "/")
        .replace("。", ".")
        .replace("．", ".")
        .replace("｡", ".")
    )
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^http:/(?!/)", "http://", text, flags=re.I)
    text = re.sub(r"^https:/(?!/)", "https://", text, flags=re.I)
    if text.startswith("//"):
        text = f"http:{text}"
    if "://" not in text:
        text = f"http://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("请输入手机 IP，例如 192.168.1.78（LOOM 会自动使用 9527 端口）")
    if parsed.username or parsed.password:
        raise ValueError("手机地址不需要用户名或密码，请只输入手机 IP")
    host = parsed.hostname or ""
    if not host or any(ch.isspace() for ch in host):
        raise ValueError("手机 IP 格式不正确")
    try:
        port = parsed.port or _DEFAULT_PHONE_PORT
    except ValueError as exc:
        raise ValueError("手机端口格式不正确") from exc
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{parsed.scheme}://{host_part}:{port}"


def _normalize_device_id(value: object, fallback: str = "phone-1") -> str:
    text = _clip(value, 80)
    text = _DEVICE_ID_RE.sub("-", text).strip(".-_")
    return text or fallback


def _public_device(device: dict) -> dict:
    token = str(device.get("token") or "").strip()
    launcher_id = str(device.get("launcherId") or "").strip()
    launcher_secret = str(device.get("launcherSecret") or "").strip()
    return {
        "id": str(device.get("id") or "").strip(),
        "name": str(device.get("name") or "").strip(),
        "baseUrl": str(device.get("baseUrl") or "").strip().rstrip("/"),
        "tokenAvailable": bool(token),
        "paired": bool(launcher_id and launcher_secret),
        "album": str(device.get("album") or "").strip(),
        "lastSeenAt": str(device.get("lastSeenAt") or "").strip(),
    }


def _public_store(store: dict) -> dict:
    devices = [item for item in store.get("devices", []) if isinstance(item, dict)]
    selected = str(store.get("selectedDeviceId") or "").strip()
    if not any(str(item.get("id") or "").strip() == selected for item in devices):
        selected = str(devices[0].get("id") or "").strip() if devices else ""
    return {
        "selectedDeviceId": selected,
        "devices": [_public_device(item) for item in devices],
        "configured": any(str(item.get("baseUrl") or "").strip() and str(item.get("token") or "").strip() for item in devices),
    }


def _script_path(ctx, script_name: str) -> str:
    for root in getattr(ctx.paths, "script_roots", ()) or ():
        candidate = os.path.join(root, script_name)
        if os.path.exists(candidate):
            return candidate
    scripts_dir = getattr(ctx.paths, "scripts_dir", None)
    if scripts_dir:
        return os.path.join(scripts_dir, script_name)
    return os.path.join(ctx.paths.base_path, "scripts", script_name)


def _resolve_openclaw_root(base_root: str | os.PathLike[str] | None = None) -> Path:
    return Path(base_root).resolve() if base_root else OPENCLAW_ROOT


def node_executable(base_root: str | os.PathLike[str] | None = None, *, explicit: str | None = None) -> str:
    explicit_value = str(explicit or "").strip()
    if explicit_value:
        return explicit_value
    env_value = str(os.environ.get("OPENCLAW_NODE_EXE") or "").strip()
    if env_value:
        return env_value
    root = _resolve_openclaw_root(base_root)
    binary_name = "node.exe" if os.name == "nt" else "node"
    candidates = (
        root / "node" / binary_name,
        root / "_up_" / "node" / binary_name,
        root / "SystemData" / ".core" / "node" / binary_name,
        root / "runtime" / "node" / binary_name,
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return binary_name


def _phone_daemon_runtime_path(base_root: str | os.PathLike[str] | None = None) -> Path:
    return _resolve_openclaw_root(base_root) / "data" / ".openclaw" / "runtime" / "phone-daemon.json"


def _phone_daemon_health(runtime: dict) -> dict | None:
    port = runtime.get("port")
    token = str(runtime.get("token") or "").strip()
    if not isinstance(port, int) or port <= 0:
        return None
    if not token:
        return None
    try:
        request = UrlRequest(
            f"http://127.0.0.1:{port}/health",
            headers={"X-LOOM-PHONE-DAEMON-TOKEN": token},
            method="GET",
        )
        with urlopen(request, timeout=3) as response:
            text = response.read().decode("utf-8", errors="replace")
        payload = json.loads(text) if text else {}
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("ok") is not False else None


def build_phone_agent_command(
    payload: dict,
    *,
    base_root: str | os.PathLike[str] | None = None,
    node_path: str | None = None,
) -> list[str]:
    safe_payload = payload if isinstance(payload, dict) else {}
    root = _resolve_openclaw_root(base_root)
    cmd = [
        node_executable(root, explicit=node_path),
        str(root / "scripts" / "openclaw-phone-agent.mjs"),
        "run",
        "--daemon",
        str(safe_payload.get("daemon") or "auto"),
    ]
    prompt = safe_payload.get("prompt")
    if prompt:
        cmd.extend(["--prompt", str(prompt)])
    mode = str(safe_payload.get("mode") or "").strip()
    if mode:
        cmd.extend(["--mode", mode])
    option_pairs = (
        ("timeoutSec", "--timeout-sec"),
        ("maxWaitSec", "--max-wait-sec"),
        ("maxRounds", "--max-rounds"),
        ("pollMs", "--poll-ms"),
        ("executionLayer", "--execution-layer"),
        ("stepTimeoutSec", "--step-timeout-sec"),
        ("campaignId", "--campaign-id"),
        ("assignmentId", "--assignment-id"),
        ("assignmentTemplateId", "--assignment-template-id"),
        ("retryBudget", "--retry-budget"),
    )
    for key, flag in option_pairs:
        value = safe_payload.get(key)
        if value not in (None, ""):
            cmd.extend([flag, str(value)])
    template_name = safe_payload.get("template") or safe_payload.get("templateName")
    if template_name:
        cmd.extend(["--template", str(template_name)])
    assignment_input = safe_payload.get("input")
    if isinstance(assignment_input, dict):
        cmd.extend([
            "--input-json",
            json.dumps(assignment_input, ensure_ascii=False, separators=(",", ":")),
        ])
    if safe_payload.get("json", True):
        cmd.append("--json")
    return cmd


def start_phone_daemon(
    *,
    base_root: str | os.PathLike[str] | None = None,
    node_path: str | None = None,
    runtime_config_json: str = "",
) -> dict:
    root = _resolve_openclaw_root(base_root)
    current = phone_daemon_status(base_root=root)
    if current.get("running"):
        result = dict(current)
        result.update({"ok": True, "running": True, "state": "running", "alreadyRunning": True})
        return result
    daemon_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if runtime_config_json:
        daemon_env[_PHONE_RUNTIME_CONFIG_ENV] = runtime_config_json
    proc = subprocess.Popen(
        [node_executable(root, explicit=node_path), str(root / "scripts" / "openclaw-phone-daemon.mjs")],
        cwd=str(root),
        env=daemon_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"ok": True, "pid": proc.pid, "running": True, "state": "starting"}


def read_phone_daemon_runtime(*, base_root: str | os.PathLike[str] | None = None) -> dict:
    path = _phone_daemon_runtime_path(base_root)
    return json.loads(path.read_text(encoding="utf-8"))


def phone_daemon_status(*, base_root: str | os.PathLike[str] | None = None) -> dict:
    try:
        runtime = read_phone_daemon_runtime(base_root=base_root)
    except FileNotFoundError:
        return {"ok": True, "running": False, "state": "stopped"}
    health = _phone_daemon_health(runtime)
    if not health:
        return {
            "ok": True,
            "running": False,
            "state": "stopped",
            "pid": runtime.get("pid"),
            "port": runtime.get("port"),
        }
    return {
        "ok": True,
        "running": True,
        "state": "running",
        "pid": runtime.get("pid"),
        "port": runtime.get("port"),
        "startedAt": runtime.get("startedAt"),
        "sessions": health.get("sessions"),
    }


def stop_phone_daemon(*, base_root: str | os.PathLike[str] | None = None) -> dict:
    try:
        runtime = read_phone_daemon_runtime(base_root=base_root)
    except FileNotFoundError:
        return {"ok": True, "running": False, "state": "stopped", "stopped": False, "reason": "not_running"}
    port = runtime.get("port")
    if not isinstance(port, int) or port <= 0:
        return {"ok": True, "running": False, "state": "stopped", "stopped": False, "reason": "invalid_runtime"}
    request = UrlRequest(
        f"http://127.0.0.1:{port}/shutdown",
        data=b"{}",
        method="POST",
        headers={
            "X-LOOM-PHONE-DAEMON-TOKEN": str(runtime.get("token") or ""),
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            text = response.read().decode("utf-8", errors="replace")
        payload = json.loads(text) if text else {}
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return {"ok": True, "running": False, "state": "stopped", "stopped": False, "reason": "not_running"}
    return {
        "ok": True,
        "running": False,
        "state": "stopped",
        "stopped": bool(payload.get("ok", True)),
    }


def _safe_prompt(value: object) -> str:
    text = str(value or "").strip()
    if "\x00" in text:
        raise ValueError("任务内容包含非法字符")
    return text[:2000]


def _phone_task_mode(value: object) -> str:
    mode = str(value or "safe").strip().lower()
    aliases = {
        "read": "observe",
        "readonly": "observe",
        "read_only": "observe",
        "observe_only": "observe",
        "confirm": "safe",
        "safe_action": "safe",
        "auto": "full",
        "full_access": "full",
    }
    mode = aliases.get(mode, mode)
    if mode not in _PHONE_TASK_MODES:
        raise ValueError("手机任务模式不支持，请选择 observe / safe / full")
    return mode


def _phone_task_profile(value: object) -> str:
    profile = str(value or "fast").strip().lower()
    aliases = {
        "quick": "fast",
        "demo": "fast",
        "normal": "standard",
        "default": "standard",
        "stable": "standard",
        "slow": "deep",
        "complex": "deep",
    }
    profile = aliases.get(profile, profile)
    if profile not in _PHONE_TASK_PROFILES:
        raise ValueError("手机任务性能档位不支持，请选择 fast / standard / deep")
    return profile


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _body_has_value(body: dict, *names: str) -> bool:
    return any(body.get(name) not in (None, "") for name in names)


def _body_first_value(body: dict, *names: str) -> object:
    for name in names:
        value = body.get(name)
        if value not in (None, ""):
            return value
    return None


def _phone_task_tuning(mode: str, profile: str, body: dict) -> tuple[int, int, int, int, bool, bool]:
    timeout_default, max_wait_default, rounds_default, poll_default = _PHONE_TASK_PROFILE_DEFAULTS[profile][mode]
    explicit_max_wait = _body_has_value(body, "maxWaitSec", "max_wait_sec")
    explicit_max_rounds = _body_has_value(body, "maxRounds", "max_rounds")
    round_cap = _PHONE_TASK_EXPLICIT_ROUND_CAPS[mode] if explicit_max_rounds else _PHONE_TASK_ROUND_CAPS[mode]
    timeout_sec = _bounded_int(
        _body_first_value(body, "timeoutSec", "timeout_sec"),
        default=timeout_default,
        minimum=30,
        maximum=1200,
    )
    max_wait_sec = _bounded_int(
        _body_first_value(body, "maxWaitSec", "max_wait_sec"),
        default=max_wait_default,
        minimum=45,
        maximum=1260,
    )
    max_rounds = _bounded_int(
        _body_first_value(body, "maxRounds", "max_rounds"),
        default=rounds_default,
        minimum=1,
        maximum=round_cap,
    )
    poll_ms = _bounded_int(
        _body_first_value(body, "pollMs", "poll_ms"),
        default=poll_default,
        minimum=500,
        maximum=1200,
    )
    return timeout_sec, max_wait_sec, max_rounds, poll_ms, explicit_max_wait, explicit_max_rounds


def _phone_direct_action(value: object, prompt: str = "") -> str:
    action = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", str(prompt or "").strip().lower())
    if not action:
        if re.fullmatch(r"(back|pressback|返回|返回上一页|上一页|后退)", text or ""):
            action = "back"
        elif re.fullmatch(r"(home|presshome|回到桌面|返回桌面|桌面|主页|回主页)", text or ""):
            action = "home"
    aliases = {
        "press_back": "back",
        "返回": "back",
        "上一页": "back",
        "press_home": "home",
        "桌面": "home",
        "主页": "home",
    }
    action = aliases.get(action, action)
    return action if action in {"back", "home"} else ""


def _phone_explicit_action_body(ctx, body: dict) -> dict:
    if "actionBody" in body:
        raw = body.get("actionBody")
    else:
        raw = body.get("action_body")
    if raw in (None, ""):
        return _phone_cached_selector_action_body(ctx, body)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("actionBody 必须是 JSON 对象") from exc
    if not isinstance(raw, dict):
        raise ValueError("actionBody 必须是 JSON 对象")
    action = _phone_action_body_name(raw.get("action") or raw.get("type"))
    if not action:
        raise ValueError("actionBody 必须包含 action")
    action_body = {**raw, "action": action}
    _phone_apply_action_body_overrides(action_body, body)
    return action_body


def _phone_cached_selector_action_body(ctx, body: dict) -> dict:
    selector_index = _phone_selector_index(body)
    if selector_index is None:
        return {}
    fast_path = _clip(body.get("fastPath") or body.get("fast_path") or "observe_fast", 40) or "observe_fast"
    key = _phone_read_cache_key(ctx, body, fast_path)
    now = time.monotonic()
    with _PHONE_READ_CACHE_LOCK:
        item = _PHONE_READ_CACHE.get(key)
        if not item:
            raise ValueError("selectorIndex requires a recent /api/phone/read result")
        if now - float(item.get("updatedAt") or 0) > _PHONE_READ_CACHE_TTL_SEC:
            _PHONE_READ_CACHE.pop(key, None)
            raise ValueError("cached selectors expired; read screen again")
        expected_hash = _clip(body.get("screenHash") or body.get("screen_hash") or body.get("knownHash") or body.get("known_hash"), 80)
        cached_hash = str(item.get("screenHash") or "").strip()
        if expected_hash and cached_hash and expected_hash != cached_hash:
            raise ValueError("selectorIndex screenHash mismatch; read screen again")
        selectors = item.get("selectors") if isinstance(item.get("selectors"), list) else []
        if selector_index < 0 or selector_index >= len(selectors):
            raise ValueError("selectorIndex out of range; read screen again")
        selector = selectors[selector_index]
    if not isinstance(selector, dict):
        raise ValueError("cached selector is invalid; read screen again")
    action_body = _phone_compact_action_body(selector.get("actionBody") if isinstance(selector.get("actionBody"), dict) else selector, selector)
    if not action_body:
        raise ValueError("cached selector has no actionBody; read screen again")
    _phone_apply_action_body_overrides(action_body, body)
    return action_body


def _phone_apply_action_body_overrides(action_body: dict, request_body: dict) -> None:
    if "observeAfter" in request_body or "observe_after" in request_body:
        raw = request_body.get("observeAfter", request_body.get("observe_after"))
        action_body["observeAfter"] = _phone_bool(raw)


def _phone_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _phone_selector_index(body: dict) -> int | None:
    if "selectorIndex" in body or "selector_index" in body:
        raw = body.get("selectorIndex", body.get("selector_index"))
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError("selectorIndex must be an integer") from None
    if "selectorNumber" in body or "selector_number" in body:
        raw = body.get("selectorNumber", body.get("selector_number"))
        try:
            return int(raw) - 1
        except (TypeError, ValueError):
            raise ValueError("selectorNumber must be an integer") from None
    return None


def _phone_prompt_for_action_body(action_body: dict) -> str:
    action = _clip(action_body.get("action"), 40) or "action_fast"
    target = _clip(
        action_body.get("text")
        or action_body.get("contentDescription")
        or action_body.get("resourceId")
        or action_body.get("targetLabel")
        or action_body.get("ref")
        or action_body.get("nodeId"),
        120,
    )
    return f"{action} {target}".strip()


def _phone_action_body_name(value: object) -> str:
    text = _clip(value, 40).strip()
    if not text:
        return ""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    aliases = {
        "click_selector": "click_ref",
        "selector_click": "click_ref",
        "ref_click": "click_ref",
        "tap_ref": "click_ref",
        "wait_element": "wait_element",
        "wait_for_element": "wait_element",
        "wait_until_element": "wait_element",
        "wait_text": "wait_element",
        "wait_for_text": "wait_element",
        "click_text": "click_text",
        "tap_text": "tap_text",
        "click_node": "click_node",
        "tap_node": "tap_node",
        "input_text": "input_text",
    }
    return aliases.get(text, text)


def _phone_template_name(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9_.-]+", "-", text).strip(".-_")
    return text[:80]


def _phone_template_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", "", str(prompt or "").strip().lower())
    if not text:
        return ""
    if any(token in text for token in {"打开系统设置", "打开设置", "系统设置", "settings首页", "opensettings"}):
        return "open-settings"
    if any(token in text for token in {"刷新页面", "下拉刷新", "refreshscreen"}):
        return "refresh-screen"
    return ""


def _phone_execution_layer(*, direct_action: str, template_name: str) -> str:
    if direct_action:
        return "direct"
    if template_name:
        return "template"
    return "agent"


def _phone_step_timeout_sec(layer: str, profile: str) -> int:
    if layer == "direct":
        return _PHONE_DIRECT_STEP_TIMEOUT_SEC
    if layer == "template":
        return _PHONE_TEMPLATE_STEP_TIMEOUT_SEC
    if profile == "deep":
        # Deep tasks regularly include screenshot/tree collection that can take
        # longer than 20 seconds on busy phones. Keep this aligned with the
        # executor cap so a slow poll does not outlive an otherwise healthy task.
        return 30
    return _PHONE_AGENT_STEP_TIMEOUT_SEC


def _phone_max_wait_for_layer(
    layer: str,
    profile: str,
    max_wait_sec: int,
    max_rounds: int,
    step_timeout_sec: int,
    *,
    explicit_max_wait: bool = False,
) -> int:
    if layer == "direct":
        return min(max_wait_sec, step_timeout_sec + 6)
    if layer == "template":
        return min(max_wait_sec, 25)
    if profile == "fast" and not explicit_max_wait:
        return min(max_wait_sec, max(30, min(75, max_rounds * 5 + step_timeout_sec)))
    return max_wait_sec


def _phone_execution_steps(layer: str) -> list[dict]:
    if layer == "direct":
        return [
            {"id": "prepare", "label": "准备连接", "timeoutSec": _PHONE_DIRECT_STEP_TIMEOUT_SEC},
            {"id": "execute", "label": "直连执行", "timeoutSec": _PHONE_DIRECT_STEP_TIMEOUT_SEC},
            {"id": "collect", "label": "收集结果", "timeoutSec": _PHONE_DIRECT_STEP_TIMEOUT_SEC},
        ]
    if layer == "template":
        return [
            {"id": "prepare", "label": "准备模板", "timeoutSec": _PHONE_TEMPLATE_STEP_TIMEOUT_SEC},
            {"id": "execute", "label": "模板执行", "timeoutSec": _PHONE_TEMPLATE_STEP_TIMEOUT_SEC},
            {"id": "collect", "label": "收集结果", "timeoutSec": _PHONE_TEMPLATE_STEP_TIMEOUT_SEC},
        ]
    return [
        {"id": "prepare", "label": "准备 Agent", "timeoutSec": _PHONE_AGENT_STEP_TIMEOUT_SEC},
        {"id": "execute", "label": "提交并轮询", "timeoutSec": _PHONE_AGENT_STEP_TIMEOUT_SEC},
        {"id": "collect", "label": "收集结果", "timeoutSec": _PHONE_AGENT_STEP_TIMEOUT_SEC},
    ]


def _phone_execution_contract(
    *,
    layer: str,
    profile: str = "fast",
    mode: str = "safe",
    timeout_sec: int = 0,
    max_wait_sec: int = 0,
    max_rounds: int = 0,
    poll_ms: int = 0,
    step_timeout_sec: int = 0,
    direct_action: str = "",
    template_name: str = "",
) -> dict:
    step_timeout_sec = max(5, min(int(step_timeout_sec or _phone_step_timeout_sec(layer, profile)), 30))
    steps = []
    for step in _phone_execution_steps(layer):
        next_step = dict(step)
        next_step["timeoutSec"] = min(int(next_step.get("timeoutSec") or step_timeout_sec), step_timeout_sec)
        steps.append(next_step)
    return {
        "layer": layer,
        "profile": profile,
        "mode": mode,
        "directAction": direct_action,
        "template": template_name,
        "stepTimeoutSec": step_timeout_sec,
        "steps": steps,
        "budget": {
            "timeoutSec": int(timeout_sec or 0),
            "maxWaitSec": int(max_wait_sec or timeout_sec or 0),
            "maxRounds": int(max_rounds or 0),
            "pollMs": int(poll_ms or 0),
        },
    }


def _phone_agent_run_args(
    *,
    prompt: str,
    mode: str,
    timeout_sec: int,
    max_wait_sec: int,
    max_rounds: int,
    poll_ms: int,
    execution_layer: str,
    step_timeout_sec: int,
    template_name: str = "",
    campaign_id: str = "",
    assignment_id: str = "",
    assignment_template_id: str = "",
    assignment_input: dict | None = None,
    retry_budget: int | None = None,
) -> list[str]:
    return build_phone_agent_command(
        {
            "prompt": prompt,
            "mode": mode,
            "daemon": "auto",
            "timeoutSec": timeout_sec,
            "maxWaitSec": max_wait_sec,
            "maxRounds": max_rounds,
            "pollMs": poll_ms,
            "executionLayer": execution_layer,
            "stepTimeoutSec": step_timeout_sec,
            "template": template_name,
            "campaignId": campaign_id,
            "assignmentId": assignment_id,
            "assignmentTemplateId": assignment_template_id,
            "input": assignment_input,
            "retryBudget": retry_budget,
            "json": True,
        }
    )[2:]


def _phone_args_for_device(args: list[str], device_id: str = "") -> list[str]:
    safe_args = list(args or [])
    normalized_device_id = _normalize_device_id(device_id) if str(device_id or "").strip() else ""
    if not normalized_device_id or "--device-id" in safe_args:
        return safe_args
    if not safe_args:
        return ["--device-id", normalized_device_id]
    return [safe_args[0], "--device-id", normalized_device_id, *safe_args[1:]]


def _build_phone_task_plan(ctx, body: dict, *, device_id: str = "") -> dict:
    task_body = dict(body or {})
    if device_id:
        task_body["deviceId"] = _normalize_device_id(device_id)
    canonical_assignment_id = str(task_body.get("assignmentId") or "")
    canonical_assignment = (
        task_body.get("schema") == "loom.matrix.dispatch.v2"
        and bool(canonical_assignment_id)
    )
    raw_prompt = task_body.get("prompt") or ""
    prompt = _safe_prompt(raw_prompt)
    if canonical_assignment:
        prompt = str(raw_prompt)
    mode = _phone_task_mode(task_body.get("mode"))
    profile = _phone_task_profile(
        task_body.get("profile")
        or task_body.get("performanceProfile")
        or task_body.get("taskProfile")
    )
    (
        timeout_sec,
        max_wait_sec,
        max_rounds,
        poll_ms,
        explicit_max_wait,
        _explicit_max_rounds,
    ) = _phone_task_tuning(mode, profile, task_body)
    explicit_action_body = _phone_explicit_action_body(ctx, task_body)
    if mode == "observe" and explicit_action_body:
        raise ValueError("observe 模式不允许执行 actionBody")
    explicit_action = str(explicit_action_body.get("action") or "")
    if not prompt and explicit_action_body:
        prompt = _phone_prompt_for_action_body(explicit_action_body)
    direct_action = explicit_action or (
        "" if mode == "observe" else _phone_direct_action(task_body.get("action") or task_body.get("directAction"), prompt)
    )
    template_name = _phone_template_name(task_body.get("template") or task_body.get("templateId"))
    if not template_name and mode == "safe":
        template_name = _phone_template_from_prompt(prompt)
    execution_layer = "direct" if explicit_action_body else _phone_execution_layer(
        direct_action=direct_action,
        template_name=template_name,
    )
    observe_known_hash = ""
    if mode == "observe":
        observe_known_hash = _clip(
            task_body.get("knownHash")
            or task_body.get("known_hash")
            or task_body.get("screenHash")
            or _phone_cached_screen_hash(ctx, task_body, "observe_fast"),
            80,
        )
    step_timeout_sec = _phone_step_timeout_sec(execution_layer, profile)
    max_wait_sec = _phone_max_wait_for_layer(
        execution_layer,
        profile,
        max_wait_sec,
        max_rounds,
        step_timeout_sec,
        explicit_max_wait=explicit_max_wait,
    )
    if not prompt:
        raise ValueError("请输入要手机执行的任务内容")

    evidence_body = {
        "prompt": prompt,
        "mode": mode,
        "profile": profile,
        "template": template_name,
        "executionLayer": execution_layer,
        "action": direct_action,
        "timeoutSec": timeout_sec,
        "maxWaitSec": max_wait_sec,
        "maxRounds": max_rounds,
        "pollMs": poll_ms,
    }
    if device_id:
        evidence_body["deviceId"] = _normalize_device_id(device_id)
    if explicit_action_body:
        evidence_body["actionBody"] = explicit_action_body

    def plan(
        *,
        script_name: str,
        args: list[str],
        timeout: int,
        layer: str,
        step_timeout: int,
        execution: dict,
        fallback_script_name: str = "",
        fallback_args: list[str] | None = None,
        fallback_execution: dict | None = None,
        fallback_timeout_sec: int = 0,
        exact_timeout: bool = False,
    ) -> dict:
        return {
            "kind": "phone.task",
            "label": "手机 Agent",
            "script_name": script_name,
            "args": _phone_args_for_device(args, device_id),
            "timeout_sec": timeout,
            "execution_layer": layer,
            "step_timeout_sec": step_timeout,
            "execution": execution,
            "evidence_body": evidence_body,
            "fallback_script_name": fallback_script_name,
            "fallback_args": _phone_args_for_device(fallback_args or [], device_id) if fallback_script_name else [],
            "fallback_execution": fallback_execution or {},
            "fallback_timeout_sec": fallback_timeout_sec,
            "device_id": device_id,
            "exact_timeout": exact_timeout,
        }

    if canonical_assignment:
        campaign_id = str(task_body.get("campaignId") or "")
        assignment_template_id = str(task_body.get("templateId") or "")
        assignment_input = task_body.get("input")
        if not campaign_id or not device_id or not isinstance(assignment_input, dict):
            raise ValueError("Canonical Matrix assignment context is incomplete")
        retry_budget = max(0, min(int(task_body.get("retryBudget") or 0), 10))
        execution = _phone_execution_contract(
            layer=execution_layer,
            profile=profile,
            mode=mode,
            timeout_sec=timeout_sec,
            max_wait_sec=timeout_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=step_timeout_sec,
            direct_action=direct_action,
            template_name=template_name,
        )
        return plan(
            script_name="openclaw-phone-agent.mjs",
            args=_phone_agent_run_args(
                prompt=prompt,
                mode=mode,
                timeout_sec=timeout_sec,
                max_wait_sec=timeout_sec,
                max_rounds=max_rounds,
                poll_ms=poll_ms,
                execution_layer=execution_layer,
                step_timeout_sec=step_timeout_sec,
                template_name=template_name,
                campaign_id=campaign_id,
                assignment_id=canonical_assignment_id,
                assignment_template_id=assignment_template_id,
                assignment_input=dict(assignment_input),
                retry_budget=retry_budget,
            ),
            timeout=timeout_sec,
            layer=execution_layer,
            step_timeout=step_timeout_sec,
            execution=execution,
            exact_timeout=True,
        )

    if mode == "observe":
        observe_args = ["read", "--prompt", prompt, "--fast-path", "observe_fast"]
        if observe_known_hash:
            observe_args.extend(["--known-hash", observe_known_hash])
            evidence_body["knownHash"] = observe_known_hash
        observe_args.append("--json")
        execution = _phone_execution_contract(
            layer="direct",
            profile=profile,
            mode=mode,
            timeout_sec=min(max_wait_sec, 25),
            max_wait_sec=min(max_wait_sec, 25),
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=_PHONE_TEMPLATE_STEP_TIMEOUT_SEC,
            template_name=template_name,
        )
        return plan(
            script_name="openclaw-phone-vision.mjs",
            args=observe_args,
            timeout=min(max_wait_sec, 25),
            layer="direct",
            step_timeout=_PHONE_TEMPLATE_STEP_TIMEOUT_SEC,
            execution=execution,
        )

    if explicit_action_body:
        execution = _phone_execution_contract(
            layer="direct",
            profile=profile,
            mode=mode,
            timeout_sec=max_wait_sec,
            max_wait_sec=max_wait_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=step_timeout_sec,
            direct_action=direct_action,
            template_name=template_name,
        )
        action_args = ["action"]
        if explicit_action in _PHONE_ACTION_FAST_ACTIONS:
            action_args.extend(["--fast-path", "action_fast"])
        action_args.extend(
            [
                "--force-action",
                "--action-body",
                json.dumps(explicit_action_body, ensure_ascii=False),
                "--json",
            ]
        )
        return plan(
            script_name="openclaw-phone-vision.mjs",
            args=action_args,
            timeout=max_wait_sec,
            layer="direct",
            step_timeout=step_timeout_sec,
            execution=execution,
        )

    if direct_action:
        action_body = {
            "action": direct_action,
            "targetLabel": "system navigation",
            "reason": "LOOM fast-path simple phone action",
        }
        _phone_apply_action_body_overrides(action_body, task_body)
        execution = _phone_execution_contract(
            layer="direct",
            profile=profile,
            mode=mode,
            timeout_sec=max_wait_sec,
            max_wait_sec=max_wait_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=step_timeout_sec,
            direct_action=direct_action,
            template_name=template_name,
        )
        return plan(
            script_name="openclaw-phone-vision.mjs",
            args=[
                "action",
                "--fast-path",
                "action_fast",
                "--force-action",
                "--allow-unknown-target",
                "--action-body",
                json.dumps(action_body, ensure_ascii=False),
                "--json",
            ],
            timeout=max_wait_sec,
            layer="direct",
            step_timeout=step_timeout_sec,
            execution=execution,
        )

    if template_name in {"open-settings", "refresh-screen"}:
        if template_name == "open-settings":
            action_body = {
                "action": "open_app",
                "packageName": "com.android.settings",
                "targetLabel": "Android Settings",
                "reason": "LOOM deterministic open-settings template",
            }
            action_flags = ["--allow-unknown-target"]
            direct_template_action = "open_app"
        else:
            action_body = {
                "action": "scroll",
                "direction": "up",
                "durationMs": 450,
                "targetLabel": "pull-to-refresh gesture",
                "reason": "LOOM deterministic refresh-screen template",
            }
            action_flags = []
            direct_template_action = "scroll"
        _phone_apply_action_body_overrides(action_body, task_body)
        fallback_step_timeout_sec = _phone_step_timeout_sec("agent", profile)
        execution = _phone_execution_contract(
            layer="template",
            profile=profile,
            mode=mode,
            timeout_sec=max_wait_sec,
            max_wait_sec=max_wait_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=step_timeout_sec,
            direct_action=direct_template_action,
            template_name=template_name,
        )
        fallback_execution = _phone_execution_contract(
            layer="agent",
            profile=profile,
            mode=mode,
            timeout_sec=max_wait_sec,
            max_wait_sec=max_wait_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=fallback_step_timeout_sec,
        )
        return plan(
            script_name="openclaw-phone-vision.mjs",
            args=[
                "action",
                "--fast-path",
                "action_fast",
                "--force-action",
                *action_flags,
                "--action-body",
                json.dumps(action_body, ensure_ascii=False),
                "--json",
            ],
            timeout=max_wait_sec,
            layer="template",
            step_timeout=step_timeout_sec,
            execution=execution,
            fallback_script_name="openclaw-phone-agent.mjs",
            fallback_args=_phone_agent_run_args(
                prompt=prompt,
                mode=mode,
                timeout_sec=timeout_sec,
                max_wait_sec=max_wait_sec,
                max_rounds=max_rounds,
                poll_ms=poll_ms,
                execution_layer="agent",
                step_timeout_sec=fallback_step_timeout_sec,
            ),
            fallback_execution=fallback_execution,
            fallback_timeout_sec=max_wait_sec + 5,
        )

    if template_name in {"read-screen", "screen-summary"}:
        template_known_hash = _clip(
            task_body.get("knownHash")
            or task_body.get("known_hash")
            or task_body.get("screenHash")
            or _phone_cached_screen_hash(ctx, task_body, "observe_fast"),
            80,
        )
        template_read_args = ["read", "--prompt", prompt, "--fast-path", "observe_fast"]
        if template_known_hash:
            template_read_args.extend(["--known-hash", template_known_hash])
            evidence_body["knownHash"] = template_known_hash
        template_read_args.append("--json")
        execution = _phone_execution_contract(
            layer="template",
            profile=profile,
            mode=mode,
            timeout_sec=min(max_wait_sec, 25),
            max_wait_sec=min(max_wait_sec, 25),
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            step_timeout_sec=step_timeout_sec,
            template_name=template_name,
        )
        return plan(
            script_name="openclaw-phone-vision.mjs",
            args=template_read_args,
            timeout=min(max_wait_sec, 25),
            layer="template",
            step_timeout=step_timeout_sec,
            execution=execution,
        )

    execution = _phone_execution_contract(
        layer=execution_layer,
        profile=profile,
        mode=mode,
        timeout_sec=timeout_sec,
        max_wait_sec=max_wait_sec,
        max_rounds=max_rounds,
        poll_ms=poll_ms,
        step_timeout_sec=step_timeout_sec,
        direct_action=direct_action,
        template_name=template_name,
    )
    return plan(
        script_name="openclaw-phone-agent.mjs",
        args=_phone_agent_run_args(
            prompt=prompt,
            mode=mode,
            timeout_sec=timeout_sec,
            max_wait_sec=max_wait_sec,
            max_rounds=max_rounds,
            poll_ms=poll_ms,
            execution_layer=execution_layer,
            step_timeout_sec=step_timeout_sec,
            template_name=template_name,
        ),
        timeout=max_wait_sec + 5,
        layer=execution_layer,
        step_timeout=step_timeout_sec,
        execution=execution,
    )


def _phone_progress_fields(kind: str, execution: dict, step_id: str, message: str) -> dict:
    layer = str(execution.get("layer") or "agent")
    step_timeout = int(execution.get("stepTimeoutSec") or _PHONE_AGENT_STEP_TIMEOUT_SEC)
    return {
        "message": message,
        "tone": "neutral",
        "phase": f"{kind}.{layer}.{step_id}",
        "commandId": kind,
        "executionLayer": layer,
        "currentStep": step_id,
        "stepTimeoutSec": step_timeout,
        "execution": execution,
    }


def _phone_read_cache_key(ctx, body: dict | None, fast_path: str) -> str:
    body = body or {}
    base_path = str(getattr(getattr(ctx, "paths", None), "base_path", "") or "")
    device_id = str(
        body.get("deviceId")
        or body.get("device_id")
        or body.get("phoneDeviceId")
        or "default"
    ).strip() or "default"
    return f"{base_path}|{device_id}|{fast_path or 'observe_fast'}"


def _phone_cached_screen_hash(ctx, body: dict | None, fast_path: str) -> str:
    key = _phone_read_cache_key(ctx, body, fast_path)
    now = time.monotonic()
    with _PHONE_READ_CACHE_LOCK:
        item = _PHONE_READ_CACHE.get(key)
        if not item:
            return ""
        if now - float(item.get("updatedAt") or 0) > _PHONE_READ_CACHE_TTL_SEC:
            _PHONE_READ_CACHE.pop(key, None)
            return ""
        return str(item.get("screenHash") or "").strip()


def _phone_screenshot_cache_key(ctx, body: dict | None) -> str:
    body = body or {}
    screen_hash = _clip(
        body.get("screenHash")
        or body.get("screen_hash")
        or body.get("knownHash")
        or body.get("known_hash"),
        80,
    )
    if not screen_hash:
        return ""
    base_path = str(getattr(getattr(ctx, "paths", None), "base_path", "") or "")
    device_id = str(
        body.get("deviceId")
        or body.get("device_id")
        or body.get("phoneDeviceId")
        or "default"
    ).strip() or "default"
    return f"{base_path}|{device_id}|{screen_hash}"


def _phone_screenshot_cache_body(ctx, body: dict | None) -> dict:
    next_body = dict(body or {})
    screen_hash = _clip(
        next_body.get("screenHash")
        or next_body.get("screen_hash")
        or next_body.get("knownHash")
        or next_body.get("known_hash"),
        80,
    )
    if not screen_hash:
        cached_hash = _phone_cached_screen_hash(ctx, next_body, "observe_fast")
        if cached_hash:
            next_body["screenHash"] = cached_hash
            next_body["screenHashSource"] = "read_cache"
    return next_body


def _phone_cached_screenshot_result(ctx, body: dict | None) -> dict:
    key = _phone_screenshot_cache_key(ctx, body)
    if not key:
        return {}
    now = time.monotonic()
    ttl_sec = max(0.1, _PHONE_SCREENSHOT_CACHE_TTL_MS / 1000)
    with _PHONE_SCREENSHOT_CACHE_LOCK:
        item = _PHONE_SCREENSHOT_CACHE.get(key)
        if not item:
            return {}
        if now - float(item.get("updatedAt") or 0) > ttl_sec:
            _PHONE_SCREENSHOT_CACHE.pop(key, None)
            return {}
        try:
            return json.loads(json.dumps(item.get("result") or {}, ensure_ascii=False))
        except (TypeError, json.JSONDecodeError):
            return dict(item.get("result") or {})


def _phone_mark_cached_screenshot_result(result: dict, started_at: float, screen_hash: str = "") -> dict:
    cached = dict(result or {})
    metrics = dict(cached.get("metrics") if isinstance(cached.get("metrics"), dict) else {})
    metrics["mode"] = "screenshot"
    metrics["cacheHit"] = True
    metrics["screenshotMs"] = 0
    metrics["totalMs"] = max(0, int((time.monotonic() - started_at) * 1000))
    metrics.setdefault("toolCallMs", 0)
    metrics.setdefault("screenTreeMs", 0)
    metrics.setdefault("llmRoundMs", 0)
    metrics.setdefault("rounds", 0)
    if screen_hash:
        metrics["screenHash"] = screen_hash
        cached["screenHash"] = screen_hash
    cached["metrics"] = metrics
    cached["success"] = True
    cached["cacheHit"] = True
    cached["currentStep"] = "cache"
    return cached


def _remember_phone_screenshot_result(ctx, body: dict | None, result: dict) -> None:
    if not isinstance(result, dict) or result.get("success") is False:
        return
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    if metrics.get("cacheHit") is True:
        return
    cache_body = dict(body or {})
    screen_hash = _clip(
        cache_body.get("screenHash")
        or cache_body.get("screen_hash")
        or cache_body.get("knownHash")
        or cache_body.get("known_hash")
        or result.get("screenHash")
        or metrics.get("screenHash"),
        80,
    )
    if screen_hash:
        cache_body["screenHash"] = screen_hash
        result.setdefault("screenHash", screen_hash)
        metrics["screenHash"] = screen_hash
        result["metrics"] = metrics
        read_cache_key = _phone_read_cache_key(ctx, cache_body, "observe_fast")
        with _PHONE_READ_CACHE_LOCK:
            _PHONE_READ_CACHE[read_cache_key] = {
                "screenHash": screen_hash,
                "selectors": [],
                "updatedAt": time.monotonic(),
            }
    key = _phone_screenshot_cache_key(ctx, cache_body)
    if not key:
        return
    with _PHONE_SCREENSHOT_CACHE_LOCK:
        _PHONE_SCREENSHOT_CACHE[key] = {
            "updatedAt": time.monotonic(),
            "result": result,
        }


def _extract_screen_hash_from_stdout(stdout: str) -> str:
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for candidate in (
        payload.get("screenHash"),
        payload.get("screen_hash"),
        data.get("screenHash"),
        data.get("screen_hash"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text[:80]
    return ""


def _phone_observation_fields_from_stdout(stdout: str) -> dict:
    payload = _phone_stdout_payload(stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    fields: dict[str, object] = {}
    for key in ("screenHash", "summary", "currentPackage", "activity"):
        value = payload.get(key)
        if value in (None, ""):
            value = data.get(key)
        text = str(value or "").strip()
        if text:
            fields[key] = text[:1000] if key == "summary" else text[:160]
    selectors = _phone_compact_selectors_from_payload(payload, data)
    if selectors:
        fields["selectors"] = selectors
        fields["selectorCount"] = len(selectors)
    return fields


def _selected_phone_matrix_device(ctx) -> dict:
    try:
        store = _load_store(ctx)
    except Exception:
        return {}
    if not isinstance(store, dict):
        return {}
    devices = store.get("devices")
    if not isinstance(devices, list):
        return {}
    selected_id = str(store.get("selectedDeviceId") or "").strip()
    selected = next(
        (
            item
            for item in devices
            if isinstance(item, dict) and str(item.get("id") or item.get("deviceId") or "").strip() == selected_id
        ),
        None,
    )
    if selected is None:
        selected = next((item for item in devices if isinstance(item, dict)), None)
    return dict(selected or {})


def _phone_matrix_presence_time() -> str:
    now = time.time()
    milliseconds = int(now * 1000) % 1000
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now))}.{milliseconds:03d}+00:00"


def _phone_event_observed_at(event: dict) -> str:
    received_at = _clip(event.get("receivedAt"), 64)
    if received_at:
        return received_at
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    raw = data.get("timestampMs")
    if raw in (None, ""):
        raw = event.get("timestampMs") or event.get("time")
    try:
        timestamp_ms = float(raw)
    except (TypeError, ValueError):
        return _phone_matrix_presence_time()
    now_ms = time.time() * 1000
    if timestamp_ms <= 0 or abs(now_ms - timestamp_ms) > 5 * 60 * 1000:
        return _phone_matrix_presence_time()
    seconds = timestamp_ms / 1000
    milliseconds = int(timestamp_ms) % 1000
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(seconds))}.{milliseconds:03d}+00:00"


def _phone_matrix_last_result(result: dict) -> str:
    report = result.get("agentReport") if isinstance(result.get("agentReport"), dict) else {}
    headline = _clip(report.get("headline"), 120)
    if headline:
        return headline
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    mode = str(result.get("mode") or metrics.get("mode") or result.get("executionLayer") or "").strip()
    total_ms = metrics.get("totalMs")
    if isinstance(total_ms, (int, float)):
        return f"{mode or 'phone'} {int(total_ms)}ms"
    return mode or str(result.get("currentStep") or "phone")[:80]


def _phone_matrix_screen_summary(kind: str, result: dict, payload: dict) -> str:
    if kind == "phone.status":
        return ""
    report = result.get("agentReport") if isinstance(result.get("agentReport"), dict) else {}
    headline = _clip(report.get("headline"), 300)
    if headline:
        return headline
    summary = _clip(result.get("summary") or payload.get("summary") or payload.get("backendSummary"), 300)
    if summary:
        return summary
    frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else {}
    current_screen = frame.get("currentScreen") if isinstance(frame.get("currentScreen"), dict) else {}
    package_name = _clip(
        result.get("currentPackage")
        or payload.get("currentPackage")
        or current_screen.get("packageName")
        or current_screen.get("foregroundPackageName"),
        80,
    )
    node_count = current_screen.get("nodeCount")
    if package_name and isinstance(node_count, (int, float)):
        return f"{package_name} · {int(node_count)} nodes"
    return package_name or "手机任务已返回结果"


def _phone_status_matrix_summary(status: dict, fallback: str = "") -> str:
    if not status:
        return fallback or "手机连接状态未知"
    parts = []
    if status.get("online") is True:
        parts.append("在线")
    elif status.get("online") is False:
        parts.append("离线")
    if status.get("accessibilityRunning") is True:
        parts.append("无障碍运行")
    elif status.get("accessibilityRunning") is False:
        parts.append("无障碍未运行")
    if status.get("screenOn") is True:
        parts.append("屏幕亮")
    if status.get("deviceLocked") is True:
        parts.append("已锁屏")
    return " · ".join(parts) or fallback or "手机状态已更新"


def _sync_phone_matrix_presence(ctx, kind: str, result: dict, device_id: str = "") -> None:
    if not isinstance(result, dict):
        return
    try:
        from core.phone_matrix import MatrixControlPlane

        matrix = MatrixControlPlane(ctx.paths)
        payload = _phone_stdout_payload(str(result.get("stdout") or ""))
        updates: list[dict] = []
        if kind == "phone.status":
            selected_id = _clip(payload.get("selectedDeviceId"), 100)
            rows = payload.get("results")
            if isinstance(rows, list):
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    device = item.get("device") if isinstance(item.get("device"), dict) else {}
                    status = item.get("status") if isinstance(item.get("status"), dict) else {}
                    device_id = _clip(device.get("id") or device.get("deviceId") or selected_id, 100)
                    if not device_id:
                        continue
                    ok = item.get("ok")
                    online = bool(status.get("online")) if "online" in status else bool(ok)
                    presence_time = _phone_matrix_presence_time()
                    status_busy = bool(
                        status.get("busy") is True
                        or status.get("taskRunning") is True
                        or status.get("agentBusy") is True
                    )
                    updates.append({
                        "deviceId": device_id,
                        "name": _clip(device.get("name") or device_id, 80),
                        "group": _clip(device.get("group") or "本机手机", 80),
                        "online": online,
                        "heartbeatAt": presence_time,
                        "lastEventAt": presence_time,
                        "presenceObservedAt": presence_time,
                        "streamStatus": "connected" if online else "offline",
                        "busy": status_busy,
                        "currentTaskId": _clip(status.get("currentTaskId"), 120) if status_busy else "",
                        "runningTaskCount": 1 if status_busy else 0,
                        "currentScreenSummary": _phone_status_matrix_summary(status, _clip(item.get("error"), 200)),
                        "failureCount": 0 if online else 1,
                        "lastResult": _phone_matrix_last_result(result),
                    })
            if not updates:
                selected = _selected_phone_matrix_device(ctx)
                presence_time = _phone_matrix_presence_time()
                resolved_device_id = _clip(
                    device_id
                    or selected.get("id")
                    or selected.get("deviceId")
                    or selected.get("name")
                    or "phone-1",
                    100,
                )
                failure_summary = _clip(
                    result.get("error")
                    or result.get("reason")
                    or result.get("stderr")
                    or "device_offline",
                    200,
                )
                updates.append({
                    "deviceId": resolved_device_id,
                    "name": _clip(selected.get("name") or resolved_device_id, 80),
                    "group": _clip(selected.get("group") or "local phones", 80),
                    "online": False,
                    "heartbeatAt": presence_time,
                    "lastEventAt": presence_time,
                    "presenceObservedAt": presence_time,
                    "streamStatus": "offline",
                    "busy": False,
                    "currentTaskId": "",
                    "runningTaskCount": 0,
                    "currentStep": "",
                    "headline": "",
                    "needsCodex": False,
                    "progressLog": [],
                    "latestProgressText": "",
                    "currentScreenSummary": failure_summary,
                    "failureCount": 1,
                    "lastResult": failure_summary,
                })
        elif kind in {"phone.read", "phone.screenshot", "phone.task"} and result.get("success") is True:
            selected = _selected_phone_matrix_device(ctx)
            presence_time = _phone_matrix_presence_time()
            resolved_device_id = _clip(
                device_id
                or selected.get("id")
                or selected.get("deviceId")
                or selected.get("name")
                or "phone-1",
                100,
            )
            updates.append({
                "deviceId": resolved_device_id,
                "name": _clip(selected.get("name") if not device_id else resolved_device_id, 80),
                "group": _clip(selected.get("group") or "本机手机", 80),
                "online": True,
                "heartbeatAt": presence_time,
                "lastEventAt": presence_time,
                "presenceObservedAt": presence_time,
                "streamStatus": "connected",
                "busy": False,
                "currentTaskId": "",
                "runningTaskCount": 0,
                "currentStep": "",
                "headline": "",
                "needsCodex": False,
                "progressLog": [],
                "latestProgressText": "",
                "currentScreenSummary": _phone_matrix_screen_summary(kind, result, payload),
                "failureCount": 0,
                "lastResult": _phone_matrix_last_result(result),
            })
        for update in updates:
            matrix.register_device(update)
    except Exception:
        return


def _parse_phone_sse_events(lines) -> list[dict]:
    events: list[dict] = []
    current: dict[str, object] = {"event": "message"}
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current, data_lines
        if not data_lines and current == {"event": "message"}:
            return
        data_text = "\n".join(data_lines)
        data_value: object = data_text
        if data_text.strip():
            try:
                data_value = json.loads(data_text)
            except json.JSONDecodeError:
                data_value = data_text
        event = dict(current)
        event["data"] = data_value
        events.append(event)
        current = {"event": "message"}
        data_lines = []

    for raw in lines:
        line = str(raw or "").rstrip("\r\n")
        if line == "":
            flush()
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            current["event"] = value or "message"
        elif field == "id":
            current["id"] = value
        elif field == "retry":
            try:
                current["retry"] = int(value)
            except ValueError:
                current["retry"] = value
    flush()
    return events


def _phone_progress_log(events: object = None, existing: object = None, limit: int = 3) -> list[dict]:
    safe_limit = max(1, min(20, _bounded_int(limit, default=3, minimum=1, maximum=20)))
    existing_items = []
    if isinstance(existing, list):
        for value in existing:
            item = _phone_safe_progress_item(value)
            if item:
                existing_items.append(item)
    if existing_items:
        return existing_items[-safe_limit:]

    items: list[dict] = []
    for event in events if isinstance(events, list) else []:
        item = _phone_progress_item_from_event(event)
        if not item:
            continue
        if not items or _phone_progress_key(items[-1]) != _phone_progress_key(item):
            items.append(item)
    return items[-safe_limit:]


def _phone_task_progress_log(task: object, limit: int = 3) -> list[dict]:
    if not isinstance(task, dict):
        return []
    events = task.get("events") if isinstance(task.get("events"), list) else []
    report = task.get("agentReport") if isinstance(task.get("agentReport"), dict) else {}
    if not events and isinstance(report.get("lastEvent"), dict):
        events = [report.get("lastEvent")]
    return _phone_progress_log(events, task.get("progressLog"), limit)


def _phone_progress_item_from_event(event: object) -> dict:
    if not isinstance(event, dict):
        return {}
    event_type = _clip(event.get("type"), 80).lower()
    round_number = _phone_progress_round(event.get("round"))
    tool_id = _phone_progress_tool_id(event.get("toolId"))
    if event_type == "loop_start":
        item_type, text = "thinking", _phone_stage_text(round_number, "分析下一步")
    elif event_type == "tool_call":
        item_type, text = "tool", _phone_stage_text(round_number, _phone_tool_label(tool_id))
    elif event_type == "tool_result":
        if event.get("success") is not False:
            return {}
        item_type, text = "error", _phone_stage_text(round_number, f"{_phone_tool_label(tool_id)}失败")
    elif event_type in {"complete", "success"}:
        item_type, text = "success", "任务执行完成"
    elif event_type in {"error", "failed"}:
        item_type, text = "error", "任务执行失败，请查看电脑端诊断"
    elif event_type == "timeout":
        item_type, text = "error", "任务执行超时，请查看电脑端诊断"
    elif event_type in {"cancelled", "canceled"}:
        item_type, text = "status", "任务已取消"
    elif event_type == "system_dialog_blocked":
        item_type, text = "error", "系统弹窗阻止了任务执行"
    elif event_type in {"submitted", "queued"}:
        item_type, text = "status", "任务已进入执行队列"
    elif event_type == "running":
        item_type, text = "status", "任务正在执行"
    elif event_type == "cancel_requested":
        item_type, text = "status", "正在取消任务"
    elif event_type == "template_fallback":
        item_type, text = "status", "正在切换执行方案"
    else:
        return {}
    return _phone_progress_item(
        round_number,
        item_type,
        tool_id if event_type in {"tool_call", "tool_result"} else "",
        text,
        event.get("time"),
    )


def _phone_safe_progress_item(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    round_number = _phone_progress_round(value.get("round"))
    item_type = _clip(value.get("type"), 32).lower()
    tool_id = _phone_progress_tool_id(value.get("toolId"))
    if item_type == "thinking":
        text = _phone_stage_text(round_number, "分析下一步")
    elif item_type == "tool":
        text = _phone_stage_text(round_number, _phone_tool_label(tool_id))
    elif item_type == "success":
        text = "任务执行完成"
    elif item_type == "error":
        text = _phone_stage_text(round_number, f"{_phone_tool_label(tool_id)}失败") if tool_id else "任务执行异常，请查看电脑端诊断"
    elif item_type == "status":
        candidate = _clip(value.get("text"), 80)
        text = candidate if candidate in {"任务已取消", "任务已进入执行队列", "任务正在执行", "正在取消任务", "正在切换执行方案"} else "任务状态已更新"
    else:
        return {}
    return _phone_progress_item(round_number, item_type, tool_id, text, value.get("time"))


def _phone_progress_item(round_number: int, item_type: str, tool_id: str, text: str, raw_time: object) -> dict:
    item: dict[str, object] = {"round": round_number, "type": item_type, "text": text}
    if tool_id:
        item["toolId"] = tool_id
    if isinstance(raw_time, (int, float)) and raw_time >= 0:
        item["time"] = raw_time
    return item


def _phone_progress_round(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _phone_progress_tool_id(value: object) -> str:
    tool_id = _clip(value, 80).lower()
    return tool_id if re.fullmatch(r"[a-z0-9_.-]+", tool_id) else ""


def _phone_tool_label(tool_id: str) -> str:
    return {
        "open_app": "打开应用",
        "get_screen_info": "读取当前页面",
        "tap": "点击页面元素",
        "click": "点击页面元素",
        "input_text": "输入文本",
        "type_text": "输入文本",
        "swipe": "滚动查找内容",
        "scroll_to_find": "滚动查找内容",
        "system_key": "执行系统按键",
        "press_key": "执行系统按键",
        "screenshot": "截取当前页面",
        "take_screenshot": "截取当前页面",
        "finish": "整理执行结果",
        "collect_list_items": "收集页面列表",
        "wait_element": "等待页面元素",
    }.get(tool_id, "执行手机操作")


def _phone_stage_text(round_number: int, action: str) -> str:
    return f"第 {round_number} 阶段：{action}" if round_number > 0 else action


def _phone_progress_key(item: dict) -> str:
    return f"{item.get('type')}|{item.get('toolId', '')}|{item.get('text')}"


def _phone_event_progress_log(event: object) -> list[dict]:
    if not isinstance(event, dict):
        return []
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    running = [task for task in tasks if isinstance(task, dict) and str(task.get("status") or "") == "running"]
    task = running[0] if running else next((task for task in tasks if isinstance(task, dict)), {})
    return _phone_task_progress_log(task)


def _phone_event_matrix_patch(event: dict, device: dict | str | None = None) -> dict:
    if not isinstance(event, dict):
        return {}
    name = _clip(event.get("event") or event.get("type"), 80)
    data = event.get("data")
    if name not in {"snapshot", "heartbeat"} or not isinstance(data, dict):
        return {}
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    if isinstance(device, str):
        device_info = {"id": device}
    else:
        device_info = dict(device or {})
    device_id = _clip(device_info.get("id") or device_info.get("deviceId") or event.get("deviceId") or "phone-1", 100)
    package_name = _clip(status.get("currentPackage") or status.get("packageName"), 120)
    app_name = _clip(status.get("currentApp") or status.get("appName"), 120)
    parts = []
    if app_name or package_name:
        parts.append(app_name or package_name)
    if package_name and app_name and package_name != app_name:
        parts.append(package_name)
    if status.get("accessibilityRunning") is True:
        parts.append("accessibility on")
    elif status.get("accessibilityRunning") is False:
        parts.append("accessibility off")
    if status.get("screenOn") is True:
        parts.append("screen on")
    if status.get("deviceLocked") is True:
        parts.append("locked")
    active_tasks = [
        item
        for item in tasks
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() in _PHONE_ACTIVE_TASK_STATUSES
    ]
    primary_task = active_tasks[0] if active_tasks else {}
    task_reports = [
        item.get("agentReport")
        for item in active_tasks
        if isinstance(item, dict) and isinstance(item.get("agentReport"), dict)
    ]
    primary_report = task_reports[0] if task_reports else {}
    progress_log = _phone_task_progress_log(primary_task)
    latest_progress_text = _phone_public_text(progress_log[-1].get("text"), 240) if progress_log else ""
    if latest_progress_text:
        parts.insert(0, latest_progress_text)
    if task_reports:
        headline = _phone_public_text(primary_report.get("headline"), 180)
        if headline:
            parts.insert(0, headline)
    if active_tasks:
        parts.append(f"{len(active_tasks)} active task")
    status_busy = bool(
        status.get("busy") is True
        or status.get("taskRunning") is True
        or status.get("agentBusy") is True
    )
    event_online = bool(status.get("online", True))
    current_task_id = _clip(
        (status.get("currentTaskId") if status_busy else "")
        or primary_task.get("taskId")
        or primary_task.get("id")
        or primary_task.get("currentTaskId"),
        120,
    )
    current_step = _phone_public_text(
        primary_report.get("currentStep")
        or primary_task.get("currentStep")
        or primary_task.get("status"),
        160,
    )
    headline = _phone_public_text(primary_report.get("headline"), 240)
    needs_codex = any(
        isinstance(report, dict) and report.get("needsCodex") is True
        for report in task_reports
    )
    busy = event_online and bool(status_busy or active_tasks)
    if not busy:
        current_task_id = ""
    total_ms = metrics.get("totalMs")
    latency_ms = _phone_event_latency_ms(event, data)
    last_result = f"event_stream {name}"
    if isinstance(total_ms, (int, float)):
        last_result = f"{last_result} {int(total_ms)}ms"
    observed_at = _phone_event_observed_at(event)
    patch = {
        "deviceId": device_id,
        "name": _clip(device_info.get("name") or device_id, 80),
        "group": _clip(device_info.get("group") or "local phones", 80),
        "online": event_online,
        "heartbeatAt": observed_at,
        "lastEventAt": observed_at,
        "presenceObservedAt": observed_at,
        "streamStatus": "connected" if event_online else "offline",
        "streamLatencyMs": latency_ms,
        "currentPackage": package_name,
        "foregroundApp": app_name,
        "accessibilityRunning": status.get("accessibilityRunning") if isinstance(status.get("accessibilityRunning"), bool) else None,
        "screenOn": status.get("screenOn") if isinstance(status.get("screenOn"), bool) else None,
        "deviceLocked": status.get("deviceLocked") if isinstance(status.get("deviceLocked"), bool) else None,
        "runningTaskCount": len(active_tasks),
        "currentScreenSummary": " | ".join(parts) or "phone event stream alive",
        "failureCount": 0 if event_online else 1,
        "lastResult": last_result,
        "busy": busy,
        "currentTaskId": current_task_id,
        "currentStep": current_step if busy else "",
        "headline": headline if busy else "",
        "needsCodex": needs_codex if busy else False,
        "progressLog": progress_log if busy else [],
        "latestProgressText": latest_progress_text if busy else "",
    }
    return patch


def _phone_event_latency_ms(event: dict, data: dict) -> int:
    raw = data.get("timestampMs")
    if raw in (None, ""):
        raw = event.get("timestampMs")
    try:
        timestamp_ms = float(raw)
    except (TypeError, ValueError):
        return 0
    if timestamp_ms <= 0:
        return 0
    return max(0, int(time.time() * 1000 - timestamp_ms))


def _apply_phone_event_to_matrix(ctx, event: dict, device: dict | None = None) -> None:
    patch = _phone_event_matrix_patch(event, device or _selected_phone_matrix_device(ctx))
    if not patch:
        return
    try:
        from core.phone_matrix import MatrixControlPlane

        matrix = MatrixControlPlane(ctx.paths)
        matrix.register_device(patch)
        event_name = _clip(event.get("event") or event.get("type") or "runtime", 80) or "runtime"
        message = _clip(
            patch.get("headline")
            or patch.get("currentStep")
            or patch.get("currentScreenSummary")
            or f"phone event {event_name}",
            320,
        )
        matrix.append_runtime_event(
            f"phone.events.{event_name}",
            _clip(patch.get("deviceId"), 100),
            message,
            source=f"phone.events.{event_name}",
            details={
                "streamStatus": patch.get("streamStatus"),
                "streamLatencyMs": patch.get("streamLatencyMs"),
                "currentPackage": patch.get("currentPackage"),
                "foregroundApp": patch.get("foregroundApp"),
                "runningTaskCount": patch.get("runningTaskCount"),
                "busy": patch.get("busy"),
            },
        )
    except Exception:
        return


def _mark_phone_event_stream_offline(ctx, device_id: str) -> None:
    raw_device_id = str(device_id or "").strip()
    if not raw_device_id:
        return
    safe_device_id = _normalize_device_id(raw_device_id, "")
    if not safe_device_id:
        return
    try:
        from core.phone_matrix import MatrixControlPlane

        observed_at = _phone_matrix_presence_time()
        MatrixControlPlane(ctx.paths).register_device(
            {
                "deviceId": safe_device_id,
                "online": False,
                "streamStatus": "offline",
                "presenceObservedAt": observed_at,
            }
        )
    except Exception:
        return


def _phone_event_sync_key(device_id: str = "") -> str:
    return _normalize_device_id(device_id, "__default__")


def _phone_event_sync_public(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {"running": False}
    process = state.get("process")
    running = bool(process is not None and getattr(process, "poll", lambda: 1)() is None)
    state_name = "running" if running else ("stopped" if state.get("finishedAt") or state.get("returncode") is not None else "starting")
    last_event_at = state.get("lastEventAt")
    last_heartbeat_at = state.get("lastHeartbeatAt")
    last_summary = state.get("lastSummary") if isinstance(state.get("lastSummary"), dict) else {}
    stopped_by = _clip(last_summary.get("stoppedBy") or state.get("stoppedBy"), 80)
    stale = bool(
        running
        and isinstance(last_event_at, (int, float))
        and time.time() - float(last_event_at) > 15
    )
    last_event = state.get("lastEvent") if isinstance(state.get("lastEvent"), dict) else {}
    progress_log = _phone_event_progress_log(last_event)
    public = {
        "running": running,
        "state": state_name,
        "restartable": not running,
        "stale": stale,
        "deviceId": state.get("deviceId") or "",
        "startedAt": state.get("startedAt") or "",
        "finishedAt": state.get("finishedAt") or "",
        "eventCount": int(state.get("eventCount") or 0),
        "lastEvent": _phone_public_event(last_event) if last_event else None,
        "lastEventAt": last_event_at if isinstance(last_event_at, (int, float)) else None,
        "lastHeartbeatAt": last_heartbeat_at if isinstance(last_heartbeat_at, (int, float)) else None,
        "lastError": _clip(state.get("lastError"), 500),
        "lastSummary": _secret_safe_payload(last_summary),
        "stoppedBy": stopped_by,
        "returncode": state.get("returncode"),
        "maxSec": int(state.get("maxSec") or 0),
        "maxEvents": int(state.get("maxEvents") or 0),
    }
    if progress_log:
        public["progressLog"] = progress_log
        public["latestProgressText"] = progress_log[-1].get("text") or ""
    return public


def _phone_event_sync_status(device_id: str = "") -> dict:
    key = _phone_event_sync_key(device_id)
    with _PHONE_EVENT_SYNC_LOCK:
        return _phone_event_sync_public(_PHONE_EVENT_SYNC_STATE.get(key))


def _close_phone_event_process_pipes(process) -> None:
    for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass


def _record_phone_event_sync_event(ctx, key: str, state: dict, event: dict) -> None:
    if event.get("type") == "phone_event_sync_summary":
        with _PHONE_EVENT_SYNC_LOCK:
            state["lastSummary"] = _secret_safe_payload(event)
            state["stoppedBy"] = _clip(event.get("stoppedBy"), 80)
            state["lastEventAt"] = time.time()
        return
    selected = _selected_phone_matrix_device(ctx)
    if state.get("deviceId"):
        selected["id"] = state.get("deviceId")
    elif event.get("deviceId"):
        selected["id"] = event.get("deviceId")
    event_device_id = _normalize_device_id(selected.get("id") or key)
    with _PHONE_EVENT_SYNC_LOCK:
        if event_device_id in _PHONE_EVENT_SYNC_DISABLED_DEVICE_IDS:
            return
    _apply_phone_event_to_matrix(ctx, event, selected)
    with _PHONE_EVENT_SYNC_LOCK:
        events = state.setdefault("events", [])
        events.append(event)
        del events[:-50]
        state["eventCount"] = int(state.get("eventCount") or 0) + 1
        state["lastEvent"] = event
        state["lastEventAt"] = time.time()
        state["resolvedDeviceId"] = event_device_id
        if str(event.get("event") or event.get("type") or "") in {"snapshot", "heartbeat", "hello"}:
            state["lastHeartbeatAt"] = state["lastEventAt"]


def _start_phone_event_sync(ctx, *, device_id: str = "", max_sec: int = 3600, max_events: int = 0) -> dict:
    key = _phone_event_sync_key(device_id)
    with _PHONE_EVENT_SYNC_LOCK:
        existing = _PHONE_EVENT_SYNC_STATE.get(key)
        if existing and existing.get("process") is not None and existing["process"].poll() is None:
            return _phone_event_sync_public(existing)
        if existing and isinstance(existing.get("finishedEpoch"), (int, float)):
            if time.time() - float(existing.get("finishedEpoch") or 0) < 5:
                return _phone_event_sync_public(existing)
    script_path = _script_path(ctx, "openclaw-phone-agent.mjs")
    if not os.path.exists(script_path):
        return {"running": False, "error": "phone event sync script missing"}
    node_exe = str(getattr(ctx.paths, "node_exe", "") or "")
    if not node_exe or not os.path.exists(node_exe):
        return {"running": False, "error": "Node.js runtime missing"}
    args = ["events-sync", "--json", "--max-sec", str(max_sec), "--max-events", str(max_events)]
    if device_id:
        args.extend(["--device-id", device_id])
    process = subprocess.Popen(
        [node_exe, script_path, *args],
        cwd=ctx.paths.base_path,
        env=phone_process_env(ctx),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    state = {
        "process": process,
        "deviceId": device_id,
        "startedAt": _phone_matrix_presence_time(),
        "finishedAt": "",
        "eventCount": 0,
        "events": [],
        "lastEvent": None,
        "lastError": "",
        "returncode": None,
        "maxSec": max_sec,
        "maxEvents": max_events,
    }
    with _PHONE_EVENT_SYNC_LOCK:
        _PHONE_EVENT_SYNC_STATE[key] = state

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            for raw in process.stdout:
                line = _sanitize_cli_output(ctx, raw.strip(), kind="phone.events")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    for parsed in _parse_phone_sse_events(line.splitlines()):
                        _record_phone_event_sync_event(ctx, key, state, parsed)
                    continue
                if isinstance(event, dict):
                    _record_phone_event_sync_event(ctx, key, state, event)
        except Exception as exc:
            with _PHONE_EVENT_SYNC_LOCK:
                state["lastError"] = str(exc)[:500]

    def read_stderr() -> None:
        try:
            assert process.stderr is not None
            stderr_parts: list[str] = []
            for raw in process.stderr:
                text = _sanitize_cli_output(ctx, raw.strip(), kind="phone.events")
                if text:
                    stderr_parts.append(text)
                    del stderr_parts[:-20]
                    with _PHONE_EVENT_SYNC_LOCK:
                        state["lastError"] = "\n".join(stderr_parts)[-2000:]
        except Exception:
            return

    def wait_process() -> None:
        code = process.wait()
        _close_phone_event_process_pipes(process)
        mark_offline = False
        with _PHONE_EVENT_SYNC_LOCK:
            state["returncode"] = code
            state["finishedAt"] = _phone_matrix_presence_time()
            state["finishedEpoch"] = time.time()
            mark_offline = _PHONE_EVENT_SYNC_STATE.get(key) is state
        if mark_offline:
            _mark_phone_event_stream_offline(
                ctx,
                str(state.get("resolvedDeviceId") or state.get("deviceId") or device_id),
            )

    threading.Thread(target=read_stdout, name=f"PhoneEventSyncStdout-{key}", daemon=True).start()
    threading.Thread(target=read_stderr, name=f"PhoneEventSyncStderr-{key}", daemon=True).start()
    wait_thread = threading.Thread(target=wait_process, name=f"PhoneEventSyncWait-{key}", daemon=True)
    state["waitThread"] = wait_thread
    wait_thread.start()
    return _phone_event_sync_public(state)


def _ensure_phone_event_syncs_for_saved_devices(
    ctx,
    *,
    device_ids: list[str] | None = None,
    max_sec: int = 86400,
    max_events: int = 0,
) -> dict:
    try:
        store = _load_store(ctx)
    except Exception as exc:
        return {"started": False, "devices": [], "error": str(exc)[:200]}
    devices = [item for item in store.get("devices", []) if isinstance(item, dict)]
    normalized_ids = {
        _normalize_device_id(item)
        for item in (device_ids or [])
        if str(item or "").strip()
    }
    statuses: list[dict] = []
    for device in devices:
        device_id = _normalize_device_id(device.get("id") or device.get("deviceId") or device.get("name"))
        if normalized_ids and device_id not in normalized_ids:
            continue
        if not str(device.get("baseUrl") or "").strip() or not str(device.get("token") or "").strip():
            continue
        status = _start_phone_event_sync(ctx, device_id=device_id, max_sec=max_sec, max_events=max_events)
        statuses.append(status)
    return {
        "started": any(bool(item.get("running")) for item in statuses),
        "devices": statuses,
    }


def _stop_phone_event_sync(device_id: str = "") -> dict:
    key = _phone_event_sync_key(device_id)
    with _PHONE_EVENT_SYNC_LOCK:
        state = _PHONE_EVENT_SYNC_STATE.get(key)
        if not state:
            return {"running": False}
        process = state.get("process")
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    if process is not None:
        _close_phone_event_process_pipes(process)
    wait_thread = state.get("waitThread")
    if isinstance(wait_thread, threading.Thread) and wait_thread is not threading.current_thread():
        wait_thread.join(timeout=2)
    with _PHONE_EVENT_SYNC_LOCK:
        state["finishedAt"] = _phone_matrix_presence_time()
        state["returncode"] = process.poll() if process is not None else None
        return _phone_event_sync_public(state)


def _phone_compact_selectors_from_payload(payload: dict, data: dict) -> list[dict]:
    source = payload.get("selectors")
    if not isinstance(source, list):
        source = data.get("selectors")
    if not isinstance(source, list):
        source = payload.get("keyNodes")
    if not isinstance(source, list):
        source = data.get("keyNodes")
    if not isinstance(source, list):
        return []
    selectors: list[dict] = []
    for item in source[:40]:
        if not isinstance(item, dict):
            continue
        action_body = _phone_compact_action_body(item.get("actionBody") if isinstance(item.get("actionBody"), dict) else item, item)
        if not action_body:
            continue
        selector = {
            "nodeId": _clip(item.get("nodeId") or item.get("node_id") or item.get("id"), 80),
            "label": _clip(
                item.get("label")
                or item.get("text")
                or item.get("description")
                or item.get("contentDescription")
                or item.get("resourceId"),
                120,
            ),
            "actionBody": action_body,
        }
        ref = _clip(item.get("ref") or item.get("selectorRef") or item.get("selector_ref") or action_body.get("ref"), 100)
        if ref:
            selector["ref"] = ref
        selectors.append(
            selector
        )
    return selectors


def _phone_compact_action_body(value: object, source: object | None = None) -> dict:
    if not isinstance(value, dict):
        return {}
    source_dict = source if isinstance(source, dict) else {}
    action = _phone_action_body_name(
        value.get("action")
        or value.get("type")
        or value.get("name")
        or source_dict.get("action")
        or source_dict.get("type")
        or source_dict.get("name")
    )
    if not action:
        return {}
    ref = _clip(
        value.get("ref")
        or value.get("selectorRef")
        or value.get("selector_ref")
        or source_dict.get("ref")
        or source_dict.get("selectorRef")
        or source_dict.get("selector_ref"),
        100,
    )
    if ref and action in _PHONE_REF_PREFERRED_ACTIONS:
        action = "click_ref"
    body: dict[str, object] = {"action": action}
    if ref:
        body["ref"] = ref
    text = _clip(
        value.get("text")
        or value.get("targetText")
        or value.get("target_text")
        or value.get("label")
        or source_dict.get("text")
        or source_dict.get("targetText")
        or source_dict.get("target_text")
        or source_dict.get("label"),
        160,
    )
    if text:
        body["text"] = text
    content_description = _clip(
        value.get("contentDescription")
        or value.get("content_description")
        or value.get("description")
        or value.get("targetDescription")
        or source_dict.get("contentDescription")
        or source_dict.get("content_description")
        or source_dict.get("description")
        or source_dict.get("targetDescription")
        or source_dict.get("target_description")
        or value.get("target_description"),
        160,
    )
    if content_description:
        body["contentDescription"] = content_description
    target_label = _clip(
        value.get("targetLabel")
        or value.get("target_label")
        or source_dict.get("targetLabel")
        or source_dict.get("target_label")
        or value.get("label")
        or source_dict.get("label")
        or text
        or content_description,
        160,
    )
    if target_label:
        body["targetLabel"] = target_label
    resource_id = _clip(
        value.get("resourceId")
        or value.get("resource_id")
        or value.get("viewId")
        or value.get("view_id")
        or source_dict.get("resourceId")
        or source_dict.get("resource_id")
        or source_dict.get("viewId")
        or source_dict.get("view_id"),
        200,
    )
    if resource_id:
        body["resourceId"] = resource_id
    node_id = _clip(value.get("nodeId") or value.get("node_id") or value.get("id") or source_dict.get("nodeId") or source_dict.get("node_id") or source_dict.get("id"), 100)
    if node_id:
        body["nodeId"] = node_id
    direction = _clip(value.get("direction") or source_dict.get("direction"), 24)
    if direction:
        body["direction"] = direction
    for key in ("timeoutMs", "durationMs"):
        raw = value.get(key, source_dict.get(key))
        if isinstance(raw, int):
            body[key] = raw
    return body


def _phone_progress_result_fields_from_stdout(stdout: str) -> dict:
    payload = _phone_stdout_payload(stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    fields: dict[str, object] = {}
    report = _phone_agent_report_from_payload(payload, data)
    if report:
        fields["agentReport"] = report
    for key in ("mode", "action", "currentStep"):
        value = payload.get(key)
        if value in (None, ""):
            value = data.get(key)
        if value in (None, "") and key == "currentStep" and report:
            value = report.get("currentStep")
        text = str(value or "").strip()
        if text:
            fields[key] = text[:160]
    if report and "currentStep" not in fields:
        text = _clip(report.get("currentStep"), 160)
        if text:
            fields["currentStep"] = text
    if report.get("needsCodex") is True:
        fields["needsCodex"] = True
    events = payload.get("events")
    if not isinstance(events, list):
        events = data.get("events")
    if isinstance(events, list):
        fields["events"] = events[:30]
    existing_progress = payload.get("progressLog")
    if not isinstance(existing_progress, list):
        existing_progress = data.get("progressLog")
    progress_log = _phone_progress_log(events, existing_progress)
    if progress_log:
        fields["progressLog"] = progress_log
    queue = _phone_queue_fields_from_payload(payload, data)
    if queue:
        fields["queue"] = queue
    return fields


def _phone_agent_report_from_payload(payload: dict, data: dict) -> dict:
    candidates: list[dict] = []
    for value in (
        payload,
        data,
        payload.get("result") if isinstance(payload.get("result"), dict) else {},
        data.get("result") if isinstance(data.get("result"), dict) else {},
        payload.get("task") if isinstance(payload.get("task"), dict) else {},
        data.get("task") if isinstance(data.get("task"), dict) else {},
    ):
        if isinstance(value, dict):
            candidates.append(value)
    for source in candidates:
        report = source.get("agentReport")
        if isinstance(report, dict):
            return _phone_agent_report_public(report)
    return {}


def _phone_agent_report_public(report: dict) -> dict:
    safe = _secret_safe_payload(report)
    if not isinstance(safe, dict):
        return {}
    allowed = {
        "schema",
        "status",
        "headline",
        "currentStep",
        "completed",
        "needsCodex",
        "completedSummary",
        "message",
        "fixHint",
        "queueMs",
        "queueDepth",
        "queuePosition",
        "exception",
    }
    public = {key: value for key, value in safe.items() if key in allowed}
    for key in ("schema", "status", "headline", "currentStep", "completedSummary", "message", "fixHint"):
        if key in public:
            public[key] = _phone_public_text(public[key], 600 if key == "fixHint" else 240)
    if isinstance(safe.get("lastEvent"), dict):
        public["lastEvent"] = _phone_public_event(safe.get("lastEvent"))
    if isinstance(public.get("exception"), dict):
        exception = public["exception"]
        public["exception"] = {
            "code": _phone_public_text(exception.get("code"), 120),
            "message": _phone_public_text(exception.get("message"), 500),
            "repairTarget": _phone_public_text(exception.get("repairTarget"), 120),
            "codexInstruction": _phone_public_text(exception.get("codexInstruction"), 500),
        }
    return public


def _phone_public_event(event: object) -> dict:
    if not isinstance(event, dict):
        return {}
    public: dict[str, object] = {}
    for key in ("type", "event", "id", "round", "time", "toolId", "toolName", "success", "retry"):
        value = event.get(key)
        if value not in (None, ""):
            public[key] = _secret_safe_payload(value)
    message = _phone_public_text(event.get("message"), 240)
    if message:
        public["message"] = message
    data = event.get("data")
    if isinstance(data, dict):
        compact_data: dict[str, object] = {}
        for key in ("schema", "timestampMs", "version"):
            if key in data:
                compact_data[key] = _secret_safe_payload(data.get(key))
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        if status:
            compact_data["status"] = {
                key: _secret_safe_payload(status.get(key))
                for key in ("busy", "currentTaskId", "currentPackage", "accessibilityRunning", "screenOn", "deviceLocked")
                if key in status
            }
        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        compact_tasks = []
        for task in tasks[:5]:
            if not isinstance(task, dict):
                continue
            compact_task: dict[str, object] = {}
            for key in ("taskId", "id", "status", "currentStep"):
                value = task.get(key)
                if value not in (None, ""):
                    compact_task[key] = _phone_public_text(value, 160)
            report = task.get("agentReport") if isinstance(task.get("agentReport"), dict) else {}
            headline = _phone_public_text(report.get("headline"), 240)
            if headline:
                compact_task["headline"] = headline
            if report.get("needsCodex") is True:
                compact_task["needsCodex"] = True
            progress_log = _phone_task_progress_log(task)
            if progress_log:
                compact_task["progressLog"] = progress_log
            if compact_task:
                compact_tasks.append(compact_task)
        if compact_tasks:
            compact_data["tasks"] = compact_tasks
        if compact_data:
            public["data"] = compact_data
    return public


def _phone_public_text(value: object, limit: int = 240) -> str:
    text = _clip(value, limit)
    if not text:
        return ""
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]{8,}", "[redacted-secret]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    text = re.sub(r"\b\d{7,}\b", "[redacted-number]", text)
    return text[:limit]


def _phone_queue_fields_from_payload(payload: dict, data: dict | None = None) -> dict:
    data = data if isinstance(data, dict) else {}
    candidates: list[dict] = []
    for value in (
        payload.get("queue"),
        data.get("queue"),
        payload.get("final"),
        data.get("final"),
    ):
        if isinstance(value, dict):
            candidates.append(value)
            nested = value.get("result") if isinstance(value.get("result"), dict) else {}
            if nested:
                candidates.append(nested)
            nested_data = value.get("data") if isinstance(value.get("data"), dict) else {}
            if nested_data:
                candidates.append(nested_data)
            nested_queue = value.get("queue") if isinstance(value.get("queue"), dict) else {}
            if nested_queue:
                candidates.append(nested_queue)
    candidates.extend([payload, data])

    queue: dict[str, object] = {}
    for source in candidates:
        for key in ("queueMs", "queueDepth", "queuePosition"):
            if key in queue:
                continue
            parsed = _non_negative_int(source.get(key))
            if parsed is not None:
                queue[key] = parsed
        if "currentTaskId" not in queue:
            current_task_id = str(source.get("currentTaskId") or "").strip()
            if current_task_id:
                queue["currentTaskId"] = current_task_id[:160]
        if "cancelRequested" not in queue and isinstance(source.get("cancelRequested"), bool):
            queue["cancelRequested"] = bool(source.get("cancelRequested"))
    return queue


def _non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _phone_payload_failure(stdout: str) -> dict:
    payload = _phone_stdout_payload(stdout)
    if not payload:
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    failed_result = next(
        (
            item
            for item in payload.get("results", [])
            if isinstance(item, dict) and (item.get("ok") is False or item.get("success") is False)
        ),
        {},
    ) if isinstance(payload.get("results"), list) else {}
    if (
        payload.get("success") is not False
        and payload.get("ok") is not False
        and data.get("success") is not False
        and data.get("ok") is not False
        and not failed_result
    ):
        return {}
    error_code = str(
        payload.get("errorCode")
        or payload.get("error_code")
        or data.get("errorCode")
        or data.get("error_code")
        or failed_result.get("errorCode")
        or failed_result.get("error_code")
        or failed_result.get("error")
        or "phone_payload_failed"
    ).strip() or "phone_payload_failed"
    reason = str(
        payload.get("reason")
        or payload.get("error")
        or payload.get("message")
        or data.get("reason")
        or data.get("error")
        or data.get("message")
        or failed_result.get("reason")
        or failed_result.get("message")
        or failed_result.get("error")
        or error_code
    ).strip() or error_code
    failure = {"errorCode": error_code[:120], "reason": reason[:500]}
    details = (
        payload.get("details")
        or data.get("details")
        or failed_result.get("details")
    )
    if isinstance(details, dict):
        failure["details"] = details
        if details.get("executionMayContinue") is True:
            failure["executionMayContinue"] = True
    remediation = failed_result.get("remediation") or payload.get("remediation") or data.get("remediation")
    if isinstance(remediation, list):
        failure["remediation"] = [_clip(item, 300) for item in remediation if _clip(item, 300)][:5]
    return failure


def _phone_stdout_payload(stdout: str) -> dict:
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        payload = _phone_first_json_object(stdout)
    return payload if isinstance(payload, dict) else {}


def _phone_first_json_object(text: str) -> dict:
    value = str(text or "")
    for start, char in enumerate(value):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(value)):
            current = value[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = value[start : index + 1]
                    try:
                        payload = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return payload if isinstance(payload, dict) else {}
    return {}


def _phone_metrics_mode(kind: str, execution: dict | None = None) -> str:
    execution = execution or {}
    layer = str(execution.get("layer") or "").strip().lower()
    direct_action = str(execution.get("directAction") or "").strip()
    if kind == "phone.metrics":
        return "metrics"
    if kind == "phone.screenshot":
        return "screenshot"
    if kind == "phone.read" or (layer == "direct" and str(execution.get("mode") or "") == "observe"):
        return "observe_fast"
    if layer == "template" and direct_action:
        return "template/action_fast"
    if layer == "template":
        return "template"
    if layer == "direct" and direct_action:
        return "action_fast"
    if layer == "agent":
        return "agent_fallback"
    return kind.split(".", 1)[-1]


def _phone_result_metrics(kind: str, stdout: str, started_at: float, execution: dict | None = None) -> dict:
    elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
    payload = _phone_stdout_payload(stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    source_metrics = payload.get("metrics")
    if not isinstance(source_metrics, dict) and isinstance(data.get("metrics"), dict):
        source_metrics = data.get("metrics")

    metrics = dict(source_metrics or {})
    metrics.setdefault("totalMs", elapsed_ms)
    execution = execution or {}

    if kind == "phone.metrics":
        metrics.setdefault("mode", "metrics")
        return metrics

    if kind == "phone.screenshot":
        frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else {}
        cached = bool(payload.get("cached") or frame.get("cached"))
        metrics.update({
            "mode": "screenshot",
            "cacheHit": cached,
            "screenshotMs": 0 if cached else elapsed_ms,
            "toolCallMs": metrics.get("toolCallMs", elapsed_ms),
            "screenTreeMs": metrics.get("screenTreeMs", 0),
            "llmRoundMs": metrics.get("llmRoundMs", 0),
            "rounds": metrics.get("rounds", 0),
        })
        screen_hash = (
            payload.get("screenHash")
            or payload.get("screen_hash")
            or frame.get("screenHash")
            or frame.get("screen_hash")
        )
        if screen_hash:
            metrics["screenHash"] = str(screen_hash)[:80]
        return metrics

    if kind in {"phone.read", "phone.task"}:
        layer = str(execution.get("layer") or "").strip().lower()
        direct_action = str(execution.get("directAction") or "").strip()
        budget = execution.get("budget") if isinstance(execution.get("budget"), dict) else {}
        if "mode" not in metrics:
            metrics["mode"] = _phone_metrics_mode(kind, execution)
        metrics.setdefault("rounds", 0 if layer in {"direct", "template"} else int(budget.get("maxRounds") or 0))
        metrics.setdefault("toolCallMs", elapsed_ms)
        metrics.setdefault("screenTreeMs", 0)
        metrics.setdefault("llmRoundMs", 0)
        metrics.setdefault("screenshotMs", 0)
        metrics.setdefault("cacheHit", bool(payload.get("cacheHit") or data.get("cacheHit")))
        screen_hash = _extract_screen_hash_from_stdout(stdout)
        if screen_hash:
            metrics.setdefault("screenHash", screen_hash)
        return metrics

    if metrics:
        return metrics
    return {}


def _phone_promote_metrics_fields(result: dict, metrics: dict) -> None:
    mode = str(metrics.get("mode") or "").strip()
    if mode:
        result.setdefault("mode", mode[:160])
    if "cacheHit" in metrics:
        result.setdefault("cacheHit", bool(metrics.get("cacheHit")))


def _remember_phone_read_screen_hash(ctx, kind: str, body: dict | None, stdout: str) -> None:
    if kind not in {"phone.read", "phone.task"}:
        return
    body = body or {}
    fast_path = str(body.get("fastPath") or body.get("fast_path") or "observe_fast")
    screen_hash = _extract_screen_hash_from_stdout(stdout)
    if not screen_hash:
        return
    payload = _phone_stdout_payload(stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    selectors = _phone_compact_selectors_from_payload(payload, data)
    key = _phone_read_cache_key(ctx, body, fast_path)
    with _PHONE_READ_CACHE_LOCK:
        previous = _PHONE_READ_CACHE.get(key)
        if (
            not selectors
            and isinstance(previous, dict)
            and str(previous.get("screenHash") or "").strip() == screen_hash
        ):
            previous_selectors = previous.get("selectors")
            if isinstance(previous_selectors, list):
                selectors = previous_selectors
        _PHONE_READ_CACHE[key] = {
            "screenHash": screen_hash,
            "selectors": selectors,
            "updatedAt": time.monotonic(),
        }


def _with_phone_execution(payload: dict, execution: dict) -> dict:
    return {
        **payload,
        "executionLayer": execution.get("layer") or payload.get("executionLayer") or "",
        "execution": execution,
    }


def _sanitize(ctx, text: str) -> str:
    sanitizer = getattr(ctx, "sanitize_text", None)
    if callable(sanitizer):
        return sanitizer(text)
    return text


def _sanitize_cli_output(ctx, text: str, *, kind: str) -> str:
    cleaned = _drop_embedded_images(text, kind=kind)
    return _sanitize(ctx, _redact_cli_secrets(cleaned))


def _redact_cli_secrets(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    value = re.sub(
        r'(?i)("?(?:api[_-]?key|apikey|token|access[_-]?token|authorization|password|secret|x-lumi-signature)"?\s*:\s*")([^"]+)(")',
        r'\1[redacted]\3',
        value,
    )
    value = re.sub(
        r'''(?i)("?(?:api[_-]?key|apikey|token|access[_-]?token|authorization|password|secret|x-lumi-signature)"?)(\s*=\s*)(?:(["'])(.*?)\3|([^\s,;"']+))''',
        lambda match: (
            f"{match.group(1)}{match.group(2)}"
            f"{match.group(3) or ''}[redacted]{match.group(3) or ''}"
        ),
        value,
    )
    value = re.sub(
        r'''(?i)(--[A-Za-z0-9_-]*(?:key|token|secret|password))(\s+)(?:(["'])(.*?)\3|([^\s,;"']+))''',
        lambda match: (
            f"{match.group(1)}{match.group(2)}"
            f"{match.group(3) or ''}[redacted]{match.group(3) or ''}"
        ),
        value,
    )
    value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", value)
    return value


def _phone_cli_failure_message(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if "accessibility_stale" in text or "stale_enabled_not_bound" in text:
        return "手机无障碍开关已开启，但 APKClaw 服务未重新绑定。请打开 APKClaw 到前台，必要时重新开关一次无障碍。"
    if "agent_not_initialized" in text:
        return "手机 Agent 服务尚未就绪，请在手机端打开 APKClaw 并保持前台运行。"
    if "phone_locked" in text or "锁屏" in text or "熄屏" in text:
        return "手机处于锁屏或熄屏状态，请先解锁并保持亮屏。"
    if "accessibility_off" in text or "无障碍" in text:
        return "手机无障碍服务未开启，请在手机端开启 APKClaw 无障碍。"
    if "model_not_configured" in text or "模型" in text and "配置" in text:
        return "手机 Agent 模型尚未配置，请先登录模型账号并同步手机模型。"
    if "task_busy" in text or "busy" in text or "已有任务" in text:
        return "APKClaw 正在执行其他任务，请稍后重试。"
    if "signature" in text or "unauthorized" in text or "forbidden" in text or "403" in text:
        return "已连接到手机端 APKClaw，但连接令牌无效或已经变更。请重新复制并保存 LAN Config 中的当前连接令牌。"
    if "device_offline" in text or "econnrefused" in text or "fetch failed" in text or "offline" in text:
        return "无法连接手机端 APKClaw，请确认手机和电脑在同一网络，且 APKClaw 已启动。"
    return "手机任务执行失败，请检查手机连接和诊断日志"


def _phone_cli_failure_code(stdout: str, stderr: str, code: object = "") -> str:
    if str(code or "").lower() == "timeout":
        return "timeout"
    text = f"{stdout}\n{stderr}".lower()
    if "accessibility_stale" in text or "stale_enabled_not_bound" in text:
        return "accessibility_stale"
    if "agent_not_initialized" in text:
        return "agent_not_initialized"
    if "phone_locked" in text or "锁屏" in text or "熄屏" in text:
        return "phone_locked"
    if "accessibility_off" in text or "无障碍" in text:
        return "accessibility_off"
    if "model_not_configured" in text or ("模型" in text and "配置" in text):
        return "model_not_configured"
    if "task_busy" in text or "busy" in text or "已有任务" in text:
        return "task_busy"
    if "signature" in text or "unauthorized" in text or "forbidden" in text or "403" in text:
        return "auth_failed"
    if "device_offline" in text or "econnrefused" in text or "fetch failed" in text or "offline" in text:
        return "device_offline"
    return "phone_task_failed"


def _phone_failure_result(
    kind: str,
    *,
    code: object,
    reason: str,
    stdout: str,
    stderr: str,
    execution: dict,
    started_at: float,
) -> dict:
    elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
    metrics = _phone_result_metrics(kind, stdout, started_at, execution)
    error_code = _phone_cli_failure_code(stdout, stderr, code)
    if not metrics:
        metrics = {
            "mode": _phone_metrics_mode(kind, execution),
            "totalMs": elapsed_ms,
            "toolCallMs": elapsed_ms,
            "screenTreeMs": 0,
            "llmRoundMs": 0,
            "screenshotMs": 0,
            "cacheHit": False,
            "rounds": 0,
        }
    result = {
        "success": False,
        "code": code,
        "errorCode": error_code,
        "reason": reason,
        "error": reason,
        "stdout": stdout,
        "stderr": stderr,
        "metrics": metrics,
        "currentStep": "failed",
        "agentReport": _phone_failure_agent_report(error_code, reason),
    }
    _phone_promote_metrics_fields(result, metrics)
    return _with_phone_execution(result, execution)


def _phone_failure_agent_report(error_code: str, reason: str) -> dict:
    code = _clip(error_code or "phone_task_failed", 120)
    repair_target = _phone_failure_repair_target(code)
    instruction = _phone_failure_codex_instruction(repair_target)
    return {
        "schema": "apkclaw.agent_report.v1",
        "status": "error",
        "headline": f"exception: {_clip(reason, 180)}",
        "currentStep": "failed",
        "completed": True,
        "needsCodex": True,
        "completedSummary": "Task stopped before completion",
        "exception": {
            "code": code,
            "message": _clip(reason, 500),
            "repairTarget": repair_target,
            "codexInstruction": instruction,
        },
        "fixHint": f"{instruction} Last error: {_clip(reason, 240)}",
    }


def _phone_failure_repair_target(error_code: str) -> str:
    return {
        "accessibility_off": "apkclaw_accessibility",
        "model_not_configured": "phone_model_config",
        "model_not_ready": "phone_model_config",
        "task_busy": "phone_task_queue",
        "timeout": "phone_task_timeout",
        "fallback_timeout": "phone_task_timeout",
        "phone_locked": "phone_lock_state",
        "auth_failed": "lumi_pairing",
        "device_offline": "phone_network",
        "agent_not_initialized": "apkclaw_agent_runtime",
    }.get(error_code, "apkclaw_agent_runtime")


def _phone_failure_codex_instruction(repair_target: str) -> str:
    return {
        "apkclaw_accessibility": "Inspect APKClaw accessibility binding, stale enabled state, keep-alive, and background kill recovery.",
        "phone_model_config": "Check LOOM phone model sync and APKClaw LLM configuration.",
        "phone_task_queue": "Inspect running task, queue depth, cancellation, and retry policy.",
        "phone_task_timeout": "Inspect slow step, blocked screen, Agent loop budget, and timeout settings.",
        "phone_lock_state": "Ask user to unlock the phone; do not bypass secure lock screens.",
        "lumi_pairing": "Repair Lumi pairing/signature headers without changing token semantics.",
        "phone_network": "Check phone URL, LAN reachability, server keep-alive, and process survival.",
    }.get(repair_target, "Inspect APKClaw Agent runtime logs, crash logs, metrics, and last task events.")


def _drop_embedded_images(text: object, *, kind: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _redact_inline_image_payloads(raw)
    safe = _safe_cli_payload(payload, screenshot_only=(kind == "phone.screenshot"))
    return json.dumps(safe, ensure_ascii=False)


def _safe_cli_payload(value, *, screenshot_only: bool = False):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            lower = key_text.lower()
            if lower in {"base64", "dataurl", "data_url", "imagedata", "image_data"}:
                safe[key_text] = "[image omitted]"
                continue
            if lower in {"image", "screenshot"} and isinstance(item, (dict, str)):
                safe[key_text] = _image_summary(item)
                continue
            if screenshot_only and lower == "frame" and isinstance(item, dict):
                frame = _safe_cli_payload(item, screenshot_only=True)
                if isinstance(frame, dict):
                    frame.pop("image", None)
                    frame["imageOmitted"] = True
                safe[key_text] = frame
                continue
            safe[key_text] = _safe_cli_payload(item, screenshot_only=screenshot_only)
        return safe
    if isinstance(value, list):
        return [_safe_cli_payload(item, screenshot_only=screenshot_only) for item in value]
    if isinstance(value, str):
        return _redact_inline_image_payloads(value)
    return value


def _image_summary(value) -> dict:
    if isinstance(value, dict):
        return {
            "omitted": True,
            "mime": str(value.get("mime") or value.get("type") or "").strip(),
            "width": value.get("width"),
            "height": value.get("height"),
        }
    return {"omitted": True}


def _redact_inline_image_payloads(text: str) -> str:
    text = re.sub(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\r\n]+", "[image omitted]", text, flags=re.I)
    return re.sub(r'"base64"\s*:\s*"[^"]+"', '"base64":"[image omitted]"', text, flags=re.I)


def _phone_matrix_runtime_device_id(ctx, explicit_device_id: str = "") -> str:
    if str(explicit_device_id or "").strip():
        return _normalize_device_id(explicit_device_id)
    selected = _selected_phone_matrix_device(ctx)
    return _normalize_device_id(
        selected.get("id")
        or selected.get("deviceId")
        or selected.get("name")
        or "phone-1"
    )


def _append_phone_matrix_runtime_log(
    ctx,
    *,
    kind: str,
    layer: str,
    stream: str,
    line: str,
    device_id: str = "",
) -> None:
    message = _clip(line, 320)
    if not message:
        return
    try:
        from core.phone_matrix import MatrixControlPlane

        event_kind = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(kind or "phone.task")).strip(".-_") or "phone.task"
        stream_name = "stderr" if stream == "stderr" else "stdout"
        MatrixControlPlane(ctx.paths).append_runtime_event(
            f"phone.events.{event_kind}.{stream_name}",
            _phone_matrix_runtime_device_id(ctx, device_id),
            message,
            source=f"{event_kind}.{stream_name}",
            details={
                "executionLayer": _clip(layer, 40),
                "stream": stream_name,
            },
        )
    except Exception:
        return


def _phone_runtime_config_json(ctx) -> str:
    if not callable(getattr(ctx, "read_json", None)):
        return ""
    if not str(getattr(getattr(ctx, "paths", None), "launcher_dir", "") or "").strip():
        return ""
    store = _load_store(ctx)
    devices: list[dict] = []
    for item in store.get("devices", []):
        if not isinstance(item, dict):
            continue
        devices.append({
            key: item.get(key)
            for key in ("id", "name", "baseUrl", "token", "launcherId", "launcherSecret", "album", "tags", "priority")
            if item.get(key) not in (None, "")
        })
    return json.dumps(
        {"selectedDeviceId": store.get("selectedDeviceId") or "", "devices": devices},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def phone_process_env(ctx) -> dict[str, str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    runtime_config = _phone_runtime_config_json(ctx)
    if runtime_config:
        env[_PHONE_RUNTIME_CONFIG_ENV] = runtime_config
    return env


def _run_phone_process_with_matrix_stream(
    ctx,
    command: list[str],
    *,
    kind: str,
    layer: str,
    timeout_sec: int,
    device_id: str = "",
    on_heartbeat=None,
    should_cancel=None,
    cooperative_cancel: bool = False,
) -> dict:
    def cancellation_requested() -> bool:
        if not callable(should_cancel):
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False

    if cancellation_requested():
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "",
            "timedOut": False,
            "cancelled": True,
            "processId": None,
            "termination": "not_started",
        }
    process = subprocess.Popen(
        command,
        cwd=ctx.paths.base_path,
        env=phone_process_env(ctx),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    output_lock = threading.Lock()

    def read_stream(stream_name: str, stream, parts: list[str]) -> None:
        try:
            for raw in stream:
                with output_lock:
                    parts.append(raw)
                safe_line = _sanitize_cli_output(ctx, str(raw or "").rstrip("\r\n"), kind=kind)
                if safe_line:
                    _append_phone_matrix_runtime_log(
                        ctx,
                        kind=kind,
                        layer=layer,
                        stream=stream_name,
                        line=safe_line,
                        device_id=device_id,
                    )
        except Exception:
            return

    threads = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout, stdout_parts), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr, stderr_parts), daemon=True),
    ]
    for thread in threads:
        thread.start()

    started_at = time.monotonic()
    timed_out = False
    cancelled = False
    cancel_deadline = 0.0
    termination = "none"
    while process.poll() is None:
        elapsed = time.monotonic() - started_at
        if callable(on_heartbeat):
            try:
                on_heartbeat(elapsed)
            except Exception:
                pass
        if elapsed >= timeout_sec:
            timed_out = True
            process.kill()
            break
        if cancellation_requested():
            cancelled = True
            if cancel_deadline <= 0:
                grace_sec = _PHONE_CANCEL_GRACE_SEC if cooperative_cancel else 0.0
                cancel_deadline = time.monotonic() + grace_sec
            elif time.monotonic() >= cancel_deadline:
                process.terminate()
                termination = "terminated"
                break
        time.sleep(0.1)
    if not cancelled and cancellation_requested():
        cancelled = True
        termination = "cooperative"
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        termination = "killed"
        if not cancelled:
            timed_out = True
        process.wait(timeout=2)
    if cancelled and termination == "none":
        termination = "cooperative"
    # The child has exited, so both pipes will reach EOF. Drain every line before
    # closing them; runtime event persistence can take longer than one second for
    # a pretty-printed Agent result and must not truncate the structured payload.
    for thread in threads:
        thread.join()
    for stream in (process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    with output_lock:
        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
    return {
        "returncode": int(process.returncode if process.returncode is not None else 1),
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "cancelled": cancelled,
        "processId": process.pid,
        "termination": termination,
    }


def _submit_phone_job(
    ctx,
    *,
    kind: str,
    label: str,
    script_name: str,
    args: list[str],
    timeout_sec: int = _PHONE_SCRIPT_TIMEOUT_SEC,
    execution_layer: str = "",
    step_timeout_sec: int = 15,
    execution: dict | None = None,
    evidence_body: dict | None = None,
    fallback_script_name: str = "",
    fallback_args: list[str] | None = None,
    fallback_execution: dict | None = None,
    fallback_timeout_sec: int = 0,
    device_id: str = "",
    exact_timeout: bool = False,
    inline_job_id: str = "",
    should_cancel=None,
):
    script_path = _script_path(ctx, script_name)
    fallback_script_path = _script_path(ctx, fallback_script_name) if fallback_script_name else ""
    if not os.path.exists(script_path):
        if inline_job_id:
            raise RuntimeError("手机能力脚本缺失")
        return ctx.fastapi_json({"error": "手机能力脚本缺失"}, 404)
    node_exe = str(getattr(ctx.paths, "node_exe", "") or "")
    if not node_exe or not os.path.exists(node_exe):
        if inline_job_id:
            raise RuntimeError("Node.js 运行时缺失，无法执行手机任务")
        return ctx.fastapi_json({"error": "Node.js 运行时缺失，无法执行手机任务"}, 500)
    timeout_sec = max(5, min(int(timeout_sec or _PHONE_SCRIPT_TIMEOUT_SEC), 1800))
    layer = execution_layer or ("direct" if script_name == "openclaw-phone-vision.mjs" else "agent")
    step_timeout_sec = max(5, min(int(step_timeout_sec or 15), 30))
    if not exact_timeout:
        if layer == "direct":
            timeout_sec = min(timeout_sec, step_timeout_sec + 7)
        elif layer == "template":
            timeout_sec = min(timeout_sec, 25)
    execution = dict(execution or _phone_execution_contract(
        layer=layer,
        profile="fast",
        mode="safe",
        timeout_sec=timeout_sec,
        max_wait_sec=timeout_sec,
        max_rounds=0,
        poll_ms=0,
        step_timeout_sec=step_timeout_sec,
    ))
    fallback_args = list(fallback_args or [])
    fallback_execution = dict(fallback_execution or {})
    fallback_timeout_sec = max(5, min(int(fallback_timeout_sec or timeout_sec), 1800))

    def target_with_progress(job_id: str) -> dict:
        job_manager = ctx.get_job_mgr()
        cancel_file = job_manager.cancel_file(job_id)

        def cancellation_requested() -> bool:
            if job_manager.is_cancelled(job_id):
                return True
            if not callable(should_cancel):
                return False
            try:
                return bool(should_cancel())
            except Exception:
                return True

        def cancellable_args(script: str, values: list[str]) -> list[str]:
            if os.path.basename(script).lower() != "openclaw-phone-agent.mjs":
                return list(values)
            return [*values, "--cancel-file", cancel_file]

        ctx.get_job_mgr().progress(
            job_id,
            "手机任务已开始",
            "neutral",
            phase=f"{kind}.{layer}.prepare",
            commandId=kind,
            executionLayer=layer,
            currentStep="prepare",
            stepTimeoutSec=step_timeout_sec,
            execution=execution,
        )
        started_at = time.monotonic()

        def record_evidence(result: dict) -> None:
            _sync_phone_matrix_presence(ctx, kind, result, device_id)
            if not inline_job_id:
                _record_phone_task_evidence(ctx, kind, evidence_body, result, started_at)

        def run_agent_fallback(previous_result: dict) -> dict:
            if not fallback_script_path or not fallback_args or not fallback_execution:
                return previous_result
            fallback_info = {
                "from": _phone_metrics_mode(kind, execution),
                "errorCode": str(previous_result.get("errorCode") or previous_result.get("code") or "phone_task_failed"),
                "reason": str(previous_result.get("reason") or previous_result.get("error") or "")[:500],
            }
            ctx.get_job_mgr().progress(
                job_id,
                "手机任务进入 Agent 兜底",
                "neutral",
                phase=f"{kind}.agent.fallback",
                commandId=kind,
                executionLayer="agent",
                currentStep="agent_fallback",
                stepTimeoutSec=int(fallback_execution.get("stepTimeoutSec") or _PHONE_AGENT_STEP_TIMEOUT_SEC),
                fallback=fallback_info,
                execution=fallback_execution,
            )
            fallback_started_at = time.monotonic()
            fallback_completed = _run_phone_process_with_matrix_stream(
                ctx,
                [node_exe, fallback_script_path, *cancellable_args(fallback_script_path, fallback_args)],
                kind=kind,
                layer="agent",
                timeout_sec=fallback_timeout_sec,
                device_id=_phone_matrix_runtime_device_id(ctx, device_id),
                should_cancel=cancellation_requested,
                cooperative_cancel=os.path.basename(fallback_script_path).lower() == "openclaw-phone-agent.mjs",
            )
            if fallback_completed.get("cancelled"):
                return {"success": False, "cancelled": True, "errorCode": "cancelled", "error": "cancelled"}
            if fallback_completed.get("timedOut"):
                stdout = _sanitize_cli_output(ctx, fallback_completed.get("stdout") or "", kind=kind)
                stderr = _sanitize_cli_output(ctx, fallback_completed.get("stderr") or "", kind=kind)
                result = _phone_failure_result(
                    kind,
                    code="fallback_timeout",
                    reason="phone agent fallback timed out",
                    stdout=stdout,
                    stderr=stderr,
                    execution=fallback_execution,
                    started_at=fallback_started_at,
                )
                result["fallback"] = fallback_info
                return result

            fallback_returncode = int(fallback_completed.get("returncode") if fallback_completed.get("returncode") is not None else 1)
            stdout = _sanitize_cli_output(ctx, fallback_completed.get("stdout") or "", kind=kind)
            stderr = _sanitize_cli_output(ctx, fallback_completed.get("stderr") or "", kind=kind)
            if fallback_returncode != 0:
                result = _phone_failure_result(
                    kind,
                    code=fallback_returncode,
                    reason=_phone_cli_failure_message(stdout, stderr),
                    stdout=stdout,
                    stderr=stderr,
                    execution=fallback_execution,
                    started_at=fallback_started_at,
                )
                result["fallback"] = fallback_info
                return result
            payload_failure = _phone_payload_failure(stdout)
            if payload_failure:
                result = _phone_failure_result(
                    kind,
                    code="fallback_payload_failed",
                    reason=str(payload_failure.get("reason") or "phone fallback payload failed"),
                    stdout=stdout,
                    stderr=stderr,
                    execution=fallback_execution,
                    started_at=fallback_started_at,
                )
                result["errorCode"] = str(payload_failure.get("errorCode") or result.get("errorCode") or "phone_payload_failed")
                if payload_failure.get("remediation"):
                    result["remediation"] = payload_failure["remediation"]
                result["fallback"] = fallback_info
                return result
            result_payload = {
                "success": True,
                "code": fallback_returncode,
                "stdout": stdout,
                "stderr": stderr,
                "fallback": fallback_info,
            }
            result_payload.update(_phone_progress_result_fields_from_stdout(stdout))
            result_payload.update(_phone_observation_fields_from_stdout(stdout))
            result_payload.setdefault("currentStep", "collect")
            metrics = _phone_result_metrics(kind, stdout, fallback_started_at, fallback_execution)
            if metrics:
                result_payload["metrics"] = metrics
                _phone_promote_metrics_fields(result_payload, metrics)
            return _with_phone_execution(result_payload, fallback_execution)

        heartbeat = 0

        def heartbeat_progress(elapsed: float) -> None:
            nonlocal heartbeat
            next_heartbeat = int(elapsed)
            if next_heartbeat <= heartbeat:
                return
            heartbeat = next_heartbeat
            ctx.get_job_mgr().progress(
                job_id,
                "手机任务执行中",
                "neutral",
                phase=f"{kind}.{layer}.running",
                commandId=kind,
                executionLayer=layer,
                currentStep="execute",
                elapsedMs=int(elapsed * 1000),
                stepTimeoutSec=step_timeout_sec,
                execution=execution,
            )

        completed = _run_phone_process_with_matrix_stream(
            ctx,
            [node_exe, script_path, *cancellable_args(script_path, args)],
            kind=kind,
            layer=layer,
            timeout_sec=timeout_sec,
            device_id=_phone_matrix_runtime_device_id(ctx, device_id),
            on_heartbeat=heartbeat_progress,
            should_cancel=cancellation_requested,
            cooperative_cancel=os.path.basename(script_path).lower() == "openclaw-phone-agent.mjs",
        )
        stdout = _sanitize_cli_output(ctx, completed.get("stdout") or "", kind=kind)
        stderr = _sanitize_cli_output(ctx, completed.get("stderr") or "", kind=kind)
        if completed.get("cancelled"):
            return {
                "success": False,
                "cancelled": True,
                "errorCode": "cancelled",
                "error": "cancelled",
                "stdout": stdout,
                "stderr": stderr,
                "executionLayer": layer,
                "execution": execution,
            }
        if completed.get("timedOut"):
            result = {
                "success": False,
                "code": "timeout",
                "error": "手机任务执行超时，请检查手机连接状态",
                "stdout": stdout,
                "stderr": stderr,
                "executionLayer": layer,
                "execution": execution,
            }
            result = _phone_failure_result(
                kind,
                code="timeout",
                reason=str(result.get("error") or "phone task timed out"),
                stdout=stdout,
                stderr=stderr,
                execution=execution,
                started_at=started_at,
            )
            result = run_agent_fallback(result)
            record_evidence(result)
            return result
        returncode = int(completed.get("returncode") if completed.get("returncode") is not None else 1)
        if returncode != 0:
            result = _phone_failure_result(
                kind,
                code=returncode,
                reason=_phone_cli_failure_message(stdout, stderr),
                stdout=stdout,
                stderr=stderr,
                execution=execution,
                started_at=started_at,
            )
            result = run_agent_fallback(result)
            record_evidence(result)
            return result
        payload_failure = _phone_payload_failure(stdout)
        if payload_failure:
            result = _phone_failure_result(
                kind,
                code="payload_failed",
                reason=str(payload_failure.get("reason") or "phone payload failed"),
                stdout=stdout,
                stderr=stderr,
                execution=execution,
                started_at=started_at,
            )
            result["errorCode"] = str(payload_failure.get("errorCode") or result.get("errorCode") or "phone_payload_failed")
            if isinstance(payload_failure.get("details"), dict):
                result["details"] = payload_failure["details"]
            if payload_failure.get("executionMayContinue") is True:
                result["executionMayContinue"] = True
            result = run_agent_fallback(result)
            record_evidence(result)
            return result
        ctx.get_job_mgr().progress(
            job_id,
            "手机任务已返回结果",
            "success",
            phase=f"{kind}.{layer}.done",
            commandId=kind,
            executionLayer=layer,
            currentStep="collect",
            stepTimeoutSec=step_timeout_sec,
            execution=execution,
        )
        _remember_phone_read_screen_hash(ctx, kind, evidence_body, stdout)
        result_payload = {
            "success": True,
            "code": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        result_payload.update(_phone_progress_result_fields_from_stdout(stdout))
        result_payload.update(_phone_observation_fields_from_stdout(stdout))
        result_payload.setdefault("currentStep", "collect")
        metrics = _phone_result_metrics(kind, stdout, started_at, execution)
        if metrics:
            result_payload["metrics"] = metrics
            _phone_promote_metrics_fields(result_payload, metrics)
        result = _with_phone_execution(result_payload, execution)
        if kind == "phone.screenshot":
            _remember_phone_screenshot_result(ctx, evidence_body, result)
        record_evidence(result)
        return result

    if inline_job_id:
        return target_with_progress(inline_job_id)

    job = ctx.get_job_mgr().submit_progress(
        kind,
        label,
        target_with_progress,
        initial_progress=_phone_progress_fields(kind, execution, "prepare", "手机任务已排队，正在准备"),
    )
    return ctx.fastapi_json({"jobId": job["id"], "job": job})


def _record_phone_task_evidence(ctx, kind: str, body: dict | None, result: dict, started_at: float) -> None:
    try:
        from loom_cli import _write_task_evidence

        endpoint = f"/api/phone/{kind.split('.', 1)[1]}" if kind.startswith("phone.") else f"/api/{kind.replace('.', '/')}"
        ok = result.get("success") is True
        payload = {
            "ok": ok,
            "command": kind,
            "data": {
                "method": "POST",
                "endpoint": endpoint,
                "body": _secret_safe_payload(body or {}),
                "result": _secret_safe_payload(result),
            },
        }
        if not ok:
            payload["error"] = {
                "code": str(result.get("code") or "phone_task_failed"),
                "message": str(result.get("error") or "")[:300],
            }
        permission = "read" if kind in {"phone.status", "phone.screenshot", "phone.read", "phone.history", "phone.metrics"} else "control"
        evidence_ctx = type("BridgeEvidenceContext", (), {"permission": permission, "source": "bridge"})()
        _write_task_evidence(
            [kind],
            kind,
            evidence_ctx,
            payload,
            (time.monotonic() - started_at) * 1000,
            source="bridge",
        )
    except Exception:
        return


def _secret_safe_payload(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            text_key = str(key)
            lower_key = text_key.lower()
            if text_key in _SYNC_SECRET_KEYS or lower_key.endswith("secret") or lower_key.endswith("token"):
                if text_key == "tokenMasked":
                    safe[text_key] = _clip(item, 80)
                continue
            safe[text_key] = _secret_safe_payload(item)
        return safe
    if isinstance(value, list):
        return [_secret_safe_payload(item) for item in value]
    return value


def _current_account_session(ctx) -> dict | None:
    manager_getter = getattr(ctx, "get_newapi_account_mgr", None)
    if not callable(manager_getter):
        return None
    manager = manager_getter()
    current = getattr(manager, "current", None)
    if not callable(current):
        return None
    session = current()
    return session if isinstance(session, dict) else None


def _sync_failed(sync_result: dict) -> bool:
    results = sync_result.get("syncResults")
    if not isinstance(results, list):
        return False
    return any(isinstance(item, dict) and item.get("ok") is False for item in results)


def _configured_phone_device_count(ctx) -> int:
    try:
        store = _load_store(ctx)
    except Exception:
        return 0
    devices = store.get("devices") if isinstance(store, dict) else []
    if not isinstance(devices, list):
        return 0
    return sum(
        1
        for device in devices
        if isinstance(device, dict)
        and str(device.get("baseUrl") or "").strip()
        and str(device.get("token") or "").strip()
    )


def _push_phone_model_to_device(ctx) -> dict:
    if _configured_phone_device_count(ctx) <= 0:
        return {
            "attempted": False,
            "success": True,
            "message": "No configured phone device; model will be pushed before the next task.",
        }
    node_exe = str(getattr(ctx.paths, "node_exe", "") or "")
    script_path = _script_path(ctx, "openclaw-phone-agent.mjs")
    if not node_exe or not os.path.exists(node_exe) or not os.path.exists(script_path):
        return {
            "attempted": False,
            "success": True,
            "message": "Phone model saved locally; phone sync helper is unavailable in this runtime.",
        }
    try:
        completed = subprocess.run(
            [node_exe, script_path, "config-sync", "--json"],
            cwd=ctx.paths.base_path,
            env=phone_process_env(ctx),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "attempted": True,
            "success": False,
            "error": "手机模型已保存，但下发到手机超时，请确认手机在线后重试。",
            "stdout": _sanitize_cli_output(ctx, exc.stdout if isinstance(exc.stdout, str) else "", kind="phone.sync_model"),
            "stderr": _sanitize_cli_output(ctx, exc.stderr if isinstance(exc.stderr, str) else "", kind="phone.sync_model"),
        }
    stdout = _sanitize_cli_output(ctx, completed.stdout or "", kind="phone.sync_model")
    stderr = _sanitize_cli_output(ctx, completed.stderr or "", kind="phone.sync_model")
    if completed.returncode != 0:
        return {
            "attempted": True,
            "success": False,
            "error": _phone_cli_failure_message(stdout, stderr),
            "stdout": stdout,
            "stderr": stderr,
        }
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout": stdout}
    return {
        "attempted": True,
        "success": bool(payload.get("ok", True)),
        "model": payload.get("model") or "",
        "phone": payload.get("phone") if isinstance(payload.get("phone"), dict) else {},
        "status": payload.get("status") if isinstance(payload.get("status"), dict) else {},
    }


def _load_store(ctx) -> dict:
    raw_store = ctx.read_json(_phone_store_path(ctx), {"selectedDeviceId": "", "devices": []})
    if not isinstance(raw_store, dict):
        return {"selectedDeviceId": "", "devices": []}
    raw_devices = raw_store.get("devices")
    needs_migration = isinstance(raw_devices, list) and any(
        isinstance(device, dict)
        and any(device.get(field) and not _phone_store_secret_is_protected(device.get(field)) for field in _PHONE_STORE_SECRET_FIELDS)
        for device in raw_devices
    )
    store = _decode_phone_store_secrets(raw_store)
    devices = store.get("devices")
    if not isinstance(devices, list):
        store["devices"] = []
    if needs_migration:
        _write_phone_store(ctx, store)
    return store


def _upsert_device(store: dict, body: dict) -> dict:
    devices = [item for item in store.get("devices", []) if isinstance(item, dict)]
    raw_id = body.get("id") or body.get("deviceId") or body.get("name") or "phone-1"
    device_id = _normalize_device_id(raw_id)
    existing = next((item for item in devices if str(item.get("id") or "").strip() == device_id), {})
    base_url = _normalize_url(body.get("baseUrl") or body.get("phoneUrl") or existing.get("baseUrl") or "")
    token = _clip(body.get("token"), 4096) or str(existing.get("token") or "").strip()
    if not base_url:
        raise ValueError("请输入手机 IP，例如 192.168.1.78")
    if not token:
        raise ValueError("请输入 APKClaw 连接令牌")
    next_device = {
        **existing,
        "id": device_id,
        "name": _clip(body.get("name") or existing.get("name") or "Android Phone", 80),
        "baseUrl": base_url,
        "token": token,
        "album": _clip(body.get("album") or existing.get("album") or "LOOM", 80),
    }
    replaced = False
    next_devices: list[dict] = []
    for item in devices:
        if str(item.get("id") or "").strip() == device_id:
            next_devices.append(next_device)
            replaced = True
        else:
            next_devices.append(item)
    if not replaced:
        next_devices.append(next_device)
    selected = _normalize_device_id(body.get("selectedDeviceId") or store.get("selectedDeviceId") or device_id, device_id)
    if not any(str(item.get("id") or "").strip() == selected for item in next_devices):
        selected = device_id
    return {
        **store,
        "selectedDeviceId": selected,
        "devices": next_devices,
    }


def _phone_sync_model_result(ctx) -> dict:
    wire_getter = getattr(ctx, "get_wire_svc", None)
    if not callable(wire_getter):
        return {
            "success": False,
            "error": "模型同步服务不可用，请重启 LOOM 后再试。",
        }

    wire_svc = wire_getter()
    session = _current_account_session(ctx)
    if session:
        result = wire_svc.sync_from_session(session, targets=("phone",))
    else:
        wire = wire_svc.current()
        if not wire:
            return {
                "success": False,
                "error": "尚未登录模型账号，也没有可同步的模型配置。请先登录，或在模型账号页配置第三方 Provider。",
            }
        result = {
            "wire": wire_svc.current_public(),
            "syncResults": wire_svc.apply_wire(wire, targets=("phone",)),
        }

    public_result = _secret_safe_payload(result)
    if _sync_failed(public_result):
        return {
            "success": False,
            "error": "手机模型同步失败，请查看诊断日志。",
            **public_result,
        }
    phone_import = _push_phone_model_to_device(ctx)
    if phone_import.get("attempted") and not phone_import.get("success"):
        return {
            "success": False,
            "error": "手机模型已保存，但下发到手机失败，请确认手机在线后重试。",
            "phoneImport": phone_import,
            **public_result,
        }
    return {
        "success": True,
        "message": "手机模型已同步",
        "phoneImport": phone_import,
        **public_result,
    }


def register_phone_routes(app, ctx) -> None:
    @app.api_route("/api/phone/config", methods=["GET", "POST"])
    async def phone_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        store = _load_store(ctx)
        return ctx.fastapi_json(_public_store(store))

    @app.post("/api/phone/config/device")
    async def phone_config_device(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        try:
            store = _upsert_device(_load_store(ctx), body)
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
        _write_phone_store(ctx, store)
        public = _public_store(store)
        selected_id = _normalize_device_id(public.get("selectedDeviceId") or body.get("deviceId") or body.get("id"))
        with _PHONE_EVENT_SYNC_LOCK:
            _PHONE_EVENT_SYNC_DISABLED_DEVICE_IDS.discard(selected_id)
        public["eventSync"] = _ensure_phone_event_syncs_for_saved_devices(ctx, device_ids=[selected_id])
        return ctx.fastapi_json(public)

    @app.delete("/api/phone/config/device/{device_id}")
    async def phone_config_device_delete(request: Request, device_id: str):
        if error := ctx.auth_error(request):
            return error
        safe_id = _normalize_device_id(device_id)
        store = _load_store(ctx)
        devices = [item for item in store.get("devices", []) if isinstance(item, dict)]
        if not any(_normalize_device_id(item.get("id")) == safe_id for item in devices):
            return ctx.fastapi_json({"error": "phone device not found", "deviceId": safe_id}, 404)

        # Block late process output before terminating the stream, so deleted
        # credentials cannot be re-registered by an in-flight heartbeat.
        with _PHONE_EVENT_SYNC_LOCK:
            _PHONE_EVENT_SYNC_DISABLED_DEVICE_IDS.add(safe_id)
        sync_status = _stop_phone_event_sync(safe_id)
        with _PHONE_EVENT_SYNC_LOCK:
            _PHONE_EVENT_SYNC_STATE.pop(_phone_event_sync_key(safe_id), None)

        remaining = [item for item in devices if _normalize_device_id(item.get("id")) != safe_id]
        selected_id = _normalize_device_id(store.get("selectedDeviceId") or "", "")
        if selected_id == safe_id or not any(_normalize_device_id(item.get("id")) == selected_id for item in remaining):
            selected_id = _normalize_device_id(remaining[0].get("id"), "") if remaining else ""
        next_store = {**store, "selectedDeviceId": selected_id, "devices": remaining}
        _write_phone_store(ctx, next_store)

        try:
            from core.phone_matrix import MatrixControlPlane

            MatrixControlPlane(ctx.paths).unregister_device(safe_id)
        except Exception:
            pass

        public = _public_store(next_store)
        public["deletedDeviceId"] = safe_id
        public["eventSync"] = {**sync_status, "running": False}
        return ctx.fastapi_json(public)

    @app.post("/api/phone/sync-model")
    async def phone_sync_model(request: Request):
        if error := ctx.auth_error(request):
            return error

        def target(job_id: str) -> dict:
            ctx.get_job_mgr().progress(
                job_id,
                "正在同步手机模型配置",
                "neutral",
                phase="phone.sync_model",
                commandId="phone.sync_model",
            )
            return _phone_sync_model_result(ctx)

        job = ctx.get_job_mgr().submit_progress("phone.sync_model", "手机模型同步", target)
        return ctx.fastapi_json({"jobId": job["id"], "job": job})

    @app.api_route("/api/phone/devices", methods=["GET", "POST"])
    async def phone_devices(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _submit_phone_job(
            ctx,
            kind="phone.devices",
            label="手机设备",
            script_name="openclaw-phone-fleet.mjs",
            args=["list", "--json"],
            timeout_sec=25,
            execution_layer="direct",
            step_timeout_sec=_PHONE_DIRECT_STEP_TIMEOUT_SEC,
            evidence_body={},
        )

    @app.api_route("/api/phone/status", methods=["GET", "POST"])
    async def phone_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request) if request.method == "POST" else {}
        device_id = str(
            body.get("deviceId")
            or body.get("device_id")
            or request.query_params.get("deviceId")
            or request.query_params.get("device_id")
            or ""
        ).strip()
        return _submit_phone_job(
            ctx,
            kind="phone.status",
            label="手机连接",
            script_name="openclaw-phone-fleet.mjs",
            args=["status", *(["--target", _normalize_device_id(device_id)] if device_id else []), "--json"],
            timeout_sec=20,
            execution_layer="direct",
            step_timeout_sec=_PHONE_DIRECT_STEP_TIMEOUT_SEC,
            evidence_body={"deviceId": device_id} if device_id else {},
            device_id=device_id,
        )

    @app.api_route("/api/phone/metrics", methods=["GET", "POST"])
    async def phone_metrics(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _submit_phone_job(
            ctx,
            kind="phone.metrics",
            label="手机运行指标",
            script_name="openclaw-phone-agent.mjs",
            args=["metrics", "--json"],
            timeout_sec=20,
            execution_layer="direct",
            step_timeout_sec=_PHONE_DIRECT_STEP_TIMEOUT_SEC,
        )

    @app.post("/api/phone/adb-doctor")
    async def phone_adb_doctor(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        if not _phone_bool(body.get("confirmed")):
            return ctx.fastapi_json({"error": "ADB 修复需要明确确认"}, 403)
        wake = True if "wake" not in body else _phone_bool(body.get("wake"))
        launch = True if "launch" not in body else _phone_bool(body.get("launch"))
        restart_server = True if "restartServer" not in body and "restart_server" not in body else _phone_bool(
            body.get("restartServer", body.get("restart_server"))
        )
        result = ctx.get_process_svc().phone_adb_doctor(
            serial=_clip(body.get("serial") or body.get("deviceId") or body.get("device_id"), 120),
            wake=wake,
            launch=launch,
            restart_server=restart_server,
        )
        return ctx.fastapi_json(result)

    @app.post("/api/phone/events/start")
    async def phone_events_start(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_id = _clip(body.get("deviceId") or body.get("device_id"), 100)
        max_sec = _bounded_int(body.get("maxSec") or body.get("max_sec"), default=3600, minimum=1, maximum=86400)
        max_events = _bounded_int(body.get("maxEvents") or body.get("max_events"), default=0, minimum=0, maximum=100000)
        return ctx.fastapi_json(_start_phone_event_sync(ctx, device_id=device_id, max_sec=max_sec, max_events=max_events))

    @app.get("/api/phone/events/status")
    async def phone_events_status(request: Request):
        if error := ctx.auth_error(request):
            return error
        device_id = _clip(request.query_params.get("deviceId") or request.query_params.get("device_id"), 100)
        return ctx.fastapi_json(_phone_event_sync_status(device_id))

    @app.post("/api/phone/events/stop")
    async def phone_events_stop(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_id = _clip(body.get("deviceId") or body.get("device_id"), 100)
        return ctx.fastapi_json(_stop_phone_event_sync(device_id))

    @app.get("/api/phone/daemon/status")
    async def phone_daemon_status_route(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(phone_daemon_status(base_root=ctx.paths.base_path))

    @app.post("/api/phone/daemon/start")
    async def phone_daemon_start_route(request: Request):
        if error := ctx.auth_error(request):
            return error
        try:
            result = start_phone_daemon(
                base_root=ctx.paths.base_path,
                node_path=ctx.paths.node_exe,
                runtime_config_json=_phone_runtime_config_json(ctx),
            )
        except OSError as exc:
            return ctx.fastapi_json({"ok": False, "error": str(exc)}, 500)
        return ctx.fastapi_json(result)

    @app.post("/api/phone/daemon/stop")
    async def phone_daemon_stop_route(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json(stop_phone_daemon(base_root=ctx.paths.base_path))

    @app.post("/api/phone/screenshot")
    async def phone_screenshot(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_id = str(body.get("deviceId") or body.get("device_id") or "").strip()
        screenshot_body = _phone_screenshot_cache_body(ctx, body)
        cached_result = _phone_cached_screenshot_result(ctx, screenshot_body)
        if cached_result:
            execution = _phone_execution_contract(
                layer="direct",
                profile="fast",
                mode="observe",
                timeout_sec=1,
                max_wait_sec=1,
                max_rounds=0,
                poll_ms=0,
                step_timeout_sec=_PHONE_DIRECT_STEP_TIMEOUT_SEC,
            )

            def target(job_id: str) -> dict:
                started_at = time.monotonic()
                ctx.get_job_mgr().progress(
                    job_id,
                    "手机截图缓存命中",
                    "success",
                    phase="phone.screenshot.direct.cached",
                    commandId="phone.screenshot",
                    executionLayer="direct",
                    currentStep="cache",
                    execution=execution,
                )
                screen_hash = _clip(
                    screenshot_body.get("screenHash")
                    or screenshot_body.get("screen_hash")
                    or screenshot_body.get("knownHash")
                    or screenshot_body.get("known_hash"),
                    80,
                )
                return _phone_mark_cached_screenshot_result(cached_result, started_at, screen_hash)

            job = ctx.get_job_mgr().submit_progress(
                "phone.screenshot",
                "手机截图",
                target,
                initial_progress=_phone_progress_fields(
                    "phone.screenshot",
                    execution,
                    "cache",
                    "手机截图缓存已命中",
                ),
            )
            return ctx.fastapi_json({"jobId": job["id"], "job": job})
        return _submit_phone_job(
            ctx,
            kind="phone.screenshot",
            label="手机截图",
            script_name="openclaw-phone-vision.mjs",
            args=_phone_args_for_device([
                "frame",
                "--quality",
                "62",
                "--max-long-side",
                "960",
                "--no-grid",
                "--frame-timeout-ms",
                str(_PHONE_SCREENSHOT_REQUEST_TIMEOUT_MS),
                "--cache-ttl-ms",
                str(_PHONE_SCREENSHOT_CACHE_TTL_MS),
                "--json",
            ], device_id),
            timeout_sec=_PHONE_OBSERVE_TIMEOUT_SEC,
            execution_layer="direct",
            step_timeout_sec=_PHONE_OBSERVE_STEP_TIMEOUT_SEC,
            evidence_body={**screenshot_body, "deviceId": device_id} if device_id else screenshot_body,
            device_id=device_id,
            exact_timeout=True,
        )

    @app.post("/api/phone/read")
    async def phone_read(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_id = str(body.get("deviceId") or body.get("device_id") or "").strip()
        try:
            prompt = _safe_prompt(body.get("prompt") or "只读取当前手机屏幕，不要点击、输入或滑动。")
            fast_path = _clip(body.get("fastPath") or body.get("fast_path") or "observe_fast", 40) or "observe_fast"
            known_hash = _clip(
                body.get("knownHash")
                or body.get("known_hash")
                or body.get("screenHash")
                or _phone_cached_screen_hash(ctx, body, fast_path),
                80,
            )
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
        read_args = [
            "read",
            "--prompt",
            prompt,
            "--fast-path",
            fast_path,
        ]
        if known_hash:
            read_args.extend(["--known-hash", known_hash])
        read_args = _phone_args_for_device([*read_args, "--json"], device_id)
        return _submit_phone_job(
            ctx,
            kind="phone.read",
            label="读取屏幕",
            script_name="openclaw-phone-vision.mjs",
            args=read_args,
            timeout_sec=_PHONE_OBSERVE_TIMEOUT_SEC,
            execution_layer="direct",
            step_timeout_sec=_PHONE_OBSERVE_STEP_TIMEOUT_SEC,
            evidence_body={"prompt": prompt, "fastPath": fast_path, "knownHash": known_hash, "deviceId": device_id},
            device_id=device_id,
            exact_timeout=True,
        )

    @app.post("/api/phone/task")
    async def phone_task(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        device_id = str(body.get("deviceId") or body.get("device_id") or "").strip()
        try:
            plan = _build_phone_task_plan(ctx, body, device_id=device_id)
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
        return _submit_phone_job(ctx, **plan)

    @app.post("/api/phone/history")
    async def phone_history(request: Request):
        if error := ctx.auth_error(request):
            return error
        return _submit_phone_job(
            ctx,
            kind="phone.history",
            label="手机最近任务",
            script_name="openclaw-phone-agent.mjs",
            args=["history", "--limit", "10", "--json"],
            timeout_sec=60,
        )
