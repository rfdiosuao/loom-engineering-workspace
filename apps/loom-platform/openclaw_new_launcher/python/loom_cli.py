"""LOOM capability CLI.

This module is the stable capability entry for local tools and MCP. It owns
JSON contracts, permissions, dry-runs, and Bridge calls; feature logic remains
in Bridge routes and existing services.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True


def _configure_standard_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


_configure_standard_streams()

import json
import hashlib
import os
import re
import shlex
import subprocess
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict

from core.audit_log import append_jsonl, tail_lines
from core.paths import AppPaths


Json = Dict[str, Any]

PERMISSION_LEVELS = {
    "read": 0,
    "control": 1,
    "automation": 2,
    "admin": 3,
}

DEFAULT_BRIDGE_URL = os.environ.get("LOOM_BRIDGE_URL", "").strip()
DEFAULT_BRIDGE_TOKEN = os.environ.get("LOOM_BRIDGE_TOKEN", "").strip()

IMAGE_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "3:4": "1152x1536",
    "4:3": "1536x1152",
    "9:16": "1152x2048",
    "16:9": "2048x1152",
    "5:2": "2560x1024",
}

PHONE_TEMPLATE_PROMPTS = {
    "read-screen": "读取当前手机屏幕，返回当前页面名称和三个可见内容。",
    "back": "返回上一页",
    "home": "回到桌面",
}

PHONE_TEMPLATE_PROMPTS["screen-summary"] = "读取当前页面，返回页面名称和三个可见按钮。"

SAFE_SCHEDULE_ROOTS = {
    "status",
    "models",
    "logs",
}

SAFE_SCHEDULE_PAIRS = {
    ("agents", "list"),
    ("phone", "screenshot"),
    ("phone", "read"),
    ("phone", "read-screen"),
    ("phone", "quick-task"),
    ("phone", "template-task"),
}

BOOLEAN_OPTIONS = {
    "--all",
    "--confirmed",
    "--dry-run",
    "--help",
    "--json",
    "--no-launch",
    "--no-restart-server",
    "--no-wake",
    "--real-run",
    "--simulate",
    "--sync",
    "-h",
}


@dataclass
class CliContext:
    paths: AppPaths
    json_output: bool
    dry_run: bool
    permission: str
    bridge_url: str
    bridge_token: str
    source: str


class CliError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class PermissionDenied(CliError):
    def __init__(self, required: str, granted: str):
        super().__init__(
            "permission_denied",
            f"该操作需要 {required} 权限，当前为 {granted}。",
            3,
        )
        self.required = required
        self.granted = granted


def dispatch(argv: list[str] | None = None, *, base_path: str | None = None, source: str = "cli") -> tuple[int, Json]:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    command_name = _command_name(raw_argv)
    start = time.perf_counter()
    ctx: CliContext | None = None
    code = 1
    payload: Json
    try:
        ctx, args = _parse_context(raw_argv, base_path=base_path)
        ctx.source = _safe_source(source)
        payload = _dispatch_command(args, ctx)
        code = 0
        result = _success(command_name, payload)
    except CliError as exc:
        code = exc.exit_code
        result = _failure(command_name, exc.code, exc.message)
    except Exception as exc:  # pragma: no cover - defensive boundary
        code = 1
        result = _failure(command_name, "internal_error", _public_error(exc))
    duration_ms = (time.perf_counter() - start) * 1000
    _write_cli_audit(raw_argv, command_name, ctx, result, duration_ms)
    _write_task_evidence(raw_argv, command_name, ctx, result, duration_ms, source=source)
    return code, result


def main(argv: list[str] | None = None) -> int:
    code, payload = dispatch(argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return code


def _command_name(argv: list[str]) -> str:
    words = [item for item in argv if not item.startswith("-")]
    if len(words) >= 2 and words[0] in {
        "account",
        "agents",
        "acquisition",
        "diagnostics",
        "jobs",
        "license",
        "media",
        "phone",
        "schedule",
        "settings",
        "logs",
        "matrix",
        "template",
        "experience",
        "wire",
        "integration",
    }:
        return f"{words[0]} {words[1]}"
    return words[0] if words else "help"


def _parse_context(argv: list[str], *, base_path: str | None) -> tuple[CliContext, list[str]]:
    args: list[str] = []
    json_output = False
    dry_run = False
    permission = os.environ.get("LOOM_CLI_PERMISSION", "read").strip().lower() or "read"
    bridge_url = DEFAULT_BRIDGE_URL
    bridge_token = DEFAULT_BRIDGE_TOKEN

    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--json":
            json_output = True
        elif item == "--dry-run":
            dry_run = True
        elif item == "--permission":
            index += 1
            permission = _require_value(argv, index, "--permission").lower()
        elif item.startswith("--permission="):
            permission = item.split("=", 1)[1].strip().lower()
        elif item == "--bridge-url":
            index += 1
            bridge_url = _require_value(argv, index, "--bridge-url").strip()
        elif item.startswith("--bridge-url="):
            bridge_url = item.split("=", 1)[1].strip()
        elif item == "--bridge-token":
            index += 1
            bridge_token = _require_value(argv, index, "--bridge-token").strip()
        elif item.startswith("--bridge-token="):
            bridge_token = item.split("=", 1)[1].strip()
        else:
            args.append(item)
        index += 1

    if permission not in PERMISSION_LEVELS:
        raise CliError("invalid_permission", "权限只能是 read、control、automation 或 admin。")

    paths = AppPaths(base_path=os.path.normpath(base_path)) if base_path else AppPaths.discover()
    if not bridge_url or not bridge_token:
        session = _load_bridge_session()
        if not bridge_url:
            bridge_url = str(session.get("url") or "").strip()
        if not bridge_token:
            bridge_token = str(session.get("token") or "").strip()
    return (
        CliContext(
            paths=paths,
            json_output=json_output,
            dry_run=dry_run,
            permission=permission,
            bridge_url=bridge_url.rstrip("/"),
            bridge_token=bridge_token,
            source="cli",
        ),
        args,
    )


def _dispatch_command(args: list[str], ctx: CliContext) -> Json:
    if not args or args[0] in {"help", "--help", "-h"}:
        return _help_payload()
    if any(item in {"--help", "-h"} for item in args):
        return _command_help_payload(args)

    command = args[0]
    rest = args[1:]
    if command == "status":
        _require_permission(ctx, "read")
        return _status(ctx)
    if command == "doctor":
        _require_permission(ctx, "read")
        return _doctor(ctx)
    if command in {"commands", "schema"}:
        _require_permission(ctx, "read")
        return _command_catalog(ctx.paths)
    if command == "models":
        _require_permission(ctx, "read")
        return _models(ctx)
    if command == "account":
        return _account(rest, ctx)
    if command == "logs":
        return _logs(rest, ctx)
    if command == "agents":
        return _agents(rest, ctx)
    if command == "acquisition":
        return _acquisition(rest, ctx)
    if command == "media":
        return _media(rest, ctx)
    if command == "wire":
        return _wire(rest, ctx)
    if command == "jobs":
        return _jobs(rest, ctx)
    if command == "settings":
        return _settings(rest, ctx)
    if command == "diagnostics":
        return _diagnostics(rest, ctx)
    if command == "license":
        return _license(rest, ctx)
    if command == "phone":
        return _phone(rest, ctx)
    if command == "matrix":
        return _matrix(rest, ctx)
    if command == "template":
        return _template(rest, ctx)
    if command == "experience":
        return _experience(rest, ctx)
    if command == "integration":
        return _integration(rest, ctx)
    if command == "schedule":
        return _schedule(rest, ctx)

    raise CliError("unknown_command", "未知命令。")


def _help_payload() -> Json:
    catalog = _command_catalog()
    return {
        "commands": [
            "status",
            "doctor",
            "commands|schema",
            "models",
            "account current|send-code|login-code|register|login|bind-ticket|sync|subscription|select-models|logout",
            "wire current|sync|custom|verify|rollback",
            "media config|save-image|save-video|test-image|test-video|image|video",
            "agents list|start|install|detect|uninstall|rollback|model-status|model-apply|model-rollback",
            "phone status|screenshot|read|read-screen|events-start|events-status|events-stop|quick-task|run-task|template-task",
            "phone adb-doctor",
            "acquisition agent-run|agent-result",
            "matrix status|dispatch|watch|cancel|retry|leads|record-lead",
            "integration feishu doctor|status|install|login|bind-table|create-table|test-write|retry-sync|reconcile",
            "template run",
            "experience report",
            "schedule list|add|run|cancel",
            "jobs list|get",
            "settings theme|theme-list|theme-merchant|update-check|update-do|config-read|config-write",
            "diagnostics run|repair|export",
            "license current|activate|authorized",
            "logs tail|ledger",
        ],
        "commandCount": catalog["commandCount"],
        "catalog": "Run `commands --json` for the machine-readable CLI catalog.",
        "doctor": "Run `doctor --json` for concrete CLI/npm/Python/phone environment paths.",
        "usage": catalog["usage"],
        "globalOptions": catalog["globalOptions"],
        "permissions": list(PERMISSION_LEVELS.keys()),
    }


def _command_help_payload(args: list[str]) -> Json:
    words = [item for item in args if item not in {"--help", "-h"}]
    catalog = _command_catalog()
    candidates = [
        command
        for domain in catalog["domains"]
        for command in domain["commands"]
    ]
    matches = [
        command
        for command in candidates
        if words[: len(str(command.get("name") or "").split())]
        == str(command.get("name") or "").split()
    ]
    command = max(matches, key=lambda item: len(str(item.get("name") or "").split()), default=None)
    if command is None:
        raise CliError("unknown_command", "未找到对应命令帮助。")
    name = str(command.get("name") or "")
    usages = {
        "matrix dispatch": "matrix dispatch --target <device[,device]|all> --prompt <text> [--mode observe|safe|full|deep] --permission control --json",
        "matrix watch": "matrix watch [--campaign <campaignId>] [--limit <1-500>] --json",
        "matrix cancel": "matrix cancel (--campaign <campaignId> | --all) --permission control --json",
        "phone status": "phone status [--device-id <deviceId>] --json",
        "phone quick-task": "phone quick-task --device <deviceId> --prompt <text> --permission control --json",
    }
    return {
        "command": name,
        "permission": command.get("permission") or "read",
        "endpoint": command.get("endpoint") or "",
        "usage": usages.get(name) or command.get("example") or f"{name} --json",
        "globalOptions": catalog["globalOptions"],
    }


def _command_catalog(paths: AppPaths | None = None) -> Json:
    paths = paths or AppPaths.discover()
    domains = [
        {
            "domain": "core",
            "summary": "Local status, capability discovery, and model snapshot.",
            "commands": [
                {"name": "status", "permission": "read", "example": "status --json"},
                {"name": "commands", "permission": "read", "example": "commands --json"},
                {"name": "models", "permission": "read", "example": "models --json"},
                {"name": "logs tail", "permission": "read", "example": "logs tail --limit 50 --json"},
            ],
        },
        {
            "domain": "doctor",
            "summary": "Concrete environment discovery for packaged LOOM installs.",
            "commands": [
                {"name": "doctor", "permission": "read", "example": "doctor --json"},
            ],
        },
        {
            "domain": "account",
            "summary": "Relay account login, subscription, balance, and model sync.",
            "commands": [
                {"name": "account current", "permission": "read", "endpoint": "GET /api/account/current"},
                {"name": "account send-code", "permission": "control", "endpoint": "POST /api/account/email-code/send"},
                {"name": "account login-code", "permission": "control", "endpoint": "POST /api/account/email-code/login"},
                {"name": "account login", "permission": "control", "endpoint": "POST /api/account/login"},
                {"name": "account sync", "permission": "control", "endpoint": "POST /api/account/sync"},
                {"name": "account subscription", "permission": "read", "endpoint": "GET /api/account/subscription"},
                {"name": "account select-models", "permission": "control", "endpoint": "POST /api/account/models/select"},
                {"name": "account logout", "permission": "control", "endpoint": "POST /api/account/logout"},
            ],
        },
        {
            "domain": "wire",
            "summary": "OpenAI-compatible model wiring and rollback.",
            "commands": [
                {"name": "wire current", "permission": "read", "endpoint": "GET /api/wire/current"},
                {"name": "wire sync", "permission": "control", "endpoint": "POST /api/wire/sync"},
                {"name": "wire custom", "permission": "control", "endpoint": "POST /api/wire/custom"},
                {"name": "wire verify", "permission": "read", "endpoint": "POST /api/wire/verify"},
                {"name": "wire rollback", "permission": "control", "endpoint": "POST /api/wire/rollback"},
            ],
        },
        {
            "domain": "agents",
            "summary": "Detect, install, start, uninstall, rollback, and model-configure desktop Agents.",
            "commands": [
                {"name": "agents list", "permission": "read", "endpoint": "GET /api/components/status"},
                {"name": "agents detect", "permission": "control", "endpoint": "POST /api/components/detect"},
                {"name": "agents start", "permission": "control", "endpoint": "POST /api/components/start"},
                {"name": "agents install", "permission": "admin", "endpoint": "POST /api/components/install"},
                {"name": "agents uninstall", "permission": "admin", "endpoint": "POST /api/components/uninstall"},
                {"name": "agents rollback", "permission": "admin", "endpoint": "POST /api/components/rollback"},
                {"name": "agents model-status", "permission": "read", "endpoint": "GET /api/components/model-config/status"},
                {"name": "agents model-apply", "permission": "control", "endpoint": "POST /api/components/model-config/apply"},
                {"name": "agents model-rollback", "permission": "control", "endpoint": "POST /api/components/model-config/rollback"},
            ],
        },
        {
            "domain": "phone",
            "summary": "Fast/direct phone status, screenshots, read-screen, and bounded tasks.",
            "commands": [
                {"name": "phone status", "permission": "read", "endpoint": "POST /api/phone/status"},
                {"name": "phone screenshot", "permission": "read", "endpoint": "POST /api/phone/screenshot", "targetScope": "single-device-read"},
                {"name": "phone read", "permission": "read", "endpoint": "POST /api/phone/read", "targetScope": "single-device-read"},
                {"name": "phone events-start", "permission": "read", "endpoint": "POST /api/phone/events/start"},
                {"name": "phone events-status", "permission": "read", "endpoint": "GET /api/phone/events/status"},
                {"name": "phone events-stop", "permission": "read", "endpoint": "POST /api/phone/events/stop"},
                {"name": "phone quick-task", "permission": "control", "endpoint": "POST /api/phone/task", "targetScope": "single-device-write"},
                {"name": "phone template-task", "permission": "read/control", "endpoint": "POST /api/phone/task"},
                {"name": "phone adb-doctor", "permission": "admin", "endpoint": "POST /api/phone/adb-doctor"},
            ],
        },
        {
            "domain": "matrix",
            "summary": "Multi-device Matrix Control Plane dispatch, watch, cancel, retry, and experience reporting.",
            "commands": [
                {"name": "matrix status", "permission": "read", "endpoint": "GET /api/matrix/status"},
                {"name": "matrix dispatch", "permission": "control", "endpoint": "POST /api/matrix/dispatch", "targetScope": "matrix-write"},
                {"name": "matrix watch", "permission": "read", "endpoint": "GET /api/matrix/watch"},
                {"name": "matrix cancel", "permission": "control", "endpoint": "POST /api/matrix/cancel", "targetScope": "campaign-write"},
                {"name": "matrix retry", "permission": "control", "endpoint": "POST /api/matrix/retry", "targetScope": "campaign-write"},
                {"name": "matrix leads", "permission": "read", "endpoint": "GET /api/matrix/leads"},
                {"name": "matrix record-lead", "permission": "control", "endpoint": "POST /api/matrix/leads"},
                {"name": "template run", "permission": "read/control", "endpoint": "POST /api/matrix/template/run"},
                {"name": "experience report", "permission": "read", "endpoint": "GET /api/matrix/experience"},
            ],
        },
        {
            "domain": "acquisition",
            "summary": "Customer acquisition workbench phone-Agent dry-run and result ingestion.",
            "commands": [
                {"name": "acquisition agent-run", "permission": "control", "endpoint": "POST /api/matrix/acquisition/agent/run"},
                {"name": "acquisition agent-result", "permission": "control", "endpoint": "POST /api/matrix/acquisition/agent/result"},
            ],
        },
        {
            "domain": "integration",
            "summary": "Optional external integrations with explicit confirmation gates.",
            "commands": [
                {"name": "integration feishu doctor", "permission": "read", "endpoint": "GET /api/matrix/acquisition/feishu/doctor"},
                {"name": "integration feishu status", "permission": "read", "endpoint": "GET /api/matrix/acquisition/feishu/status"},
                {"name": "integration feishu install", "permission": "admin", "endpoint": "POST /api/matrix/acquisition/feishu/install"},
                {"name": "integration feishu login", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/login"},
                {"name": "integration feishu bind-table", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/bind-table"},
                {"name": "integration feishu create-table", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/create-table"},
                {"name": "integration feishu test-write", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/test-write"},
                {"name": "integration feishu retry-sync", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/retry-sync"},
                {"name": "integration feishu reconcile", "permission": "control", "endpoint": "POST /api/matrix/acquisition/feishu/reconcile"},
            ],
        },
        {
            "domain": "media",
            "summary": "Image and video generation configuration, tests, and job submission.",
            "commands": [
                {"name": "media config", "permission": "read", "endpoint": "GET /api/media/config"},
                {"name": "media save-image", "permission": "control", "endpoint": "POST /api/media/config"},
                {"name": "media save-video", "permission": "control", "endpoint": "POST /api/media/config"},
                {"name": "media test-image", "permission": "control", "endpoint": "POST /api/media/test"},
                {"name": "media test-video", "permission": "control", "endpoint": "POST /api/media/test"},
                {"name": "media image", "permission": "control", "endpoint": "POST /api/image/generate/submit"},
                {"name": "media video", "permission": "control", "endpoint": "POST /api/video/generate/submit"},
            ],
        },
        {
            "domain": "ops",
            "summary": "Jobs, scheduler, settings, diagnostics, updates, and license operations.",
            "commands": [
                {"name": "jobs list", "permission": "read", "endpoint": "GET /api/jobs/list"},
                {"name": "jobs get", "permission": "read", "endpoint": "GET /api/jobs/{id}"},
                {"name": "schedule list", "permission": "read"},
                {"name": "schedule add", "permission": "automation"},
                {"name": "schedule run", "permission": "automation"},
                {"name": "schedule cancel", "permission": "automation"},
                {"name": "settings theme", "permission": "control", "endpoint": "GET/POST /api/theme"},
                {"name": "settings theme-list", "permission": "read", "endpoint": "GET /api/theme/list"},
                {"name": "settings update-check", "permission": "read", "endpoint": "GET /api/update/check"},
                {"name": "settings update-do", "permission": "admin", "endpoint": "POST /api/update/do"},
                {"name": "diagnostics run", "permission": "read", "endpoint": "POST /api/diagnostics/run"},
                {"name": "diagnostics repair", "permission": "admin", "endpoint": "POST /api/diagnostics/repair"},
                {"name": "diagnostics export", "permission": "read", "endpoint": "POST /api/diagnostics/export"},
                {"name": "license current", "permission": "read", "endpoint": "GET /api/license/current"},
                {"name": "license activate", "permission": "control", "endpoint": "POST /api/license/activate"},
                {"name": "license authorized", "permission": "read", "endpoint": "POST /api/license/authorized"},
            ],
        },
    ]
    command_count = sum(len(domain["commands"]) for domain in domains)
    return {
        "schema": "loom.cli.catalog.v1",
        "usage": "python openclaw_new_launcher/python/loom_cli.py <command> [args] --json",
        "globalOptions": [
            {"name": "--json", "summary": "Emit one structured JSON document on stdout."},
            {"name": "--dry-run", "summary": "Return method, endpoint, and redacted body without calling Bridge."},
            {"name": "--permission read|control|automation|admin", "summary": "Set requested permission level."},
            {"name": "--bridge-url", "summary": "Override local Bridge URL."},
            {"name": "--bridge-token", "summary": "Override local Bridge token; never print it."},
        ],
        "permissions": PERMISSION_LEVELS,
        "commandCount": command_count,
        "runtime": _runtime_paths(paths),
        "codexCommandBrain": _codex_command_brain_contract(),
        "domains": domains,
    }


def _codex_command_brain_contract() -> Json:
    return {
        "schema": "loom.codex_command_brain.v1",
        "roles": {
            "codex": "Command Brain",
            "matrix": "Matrix Control Plane",
            "singlePhone": "Phone Worker",
            "device": "Phone Employee",
        },
        "naming": {
            "phoneWorker": "One APKClaw-controlled phone.",
            "matrixControlPlane": "Multi-phone registry, dispatch, event stream, and experience layer.",
            "commandBrain": "Codex or Claude supervising LOOM through CLI/MCP.",
        },
        "workflows": {
            "discover": ["status", "commands", "models", "matrix status", "logs ledger"],
            "singlePhoneRead": ["phone status", "phone screenshot", "phone read"],
            "matrixDispatch": ["matrix status", "matrix dispatch", "matrix watch", "logs ledger", "experience report"],
            "templateFirst": ["template run", "matrix watch", "experience report"],
            "modelWire": ["account current", "models", "wire current", "agents model-status", "agents model-apply"],
        },
        "operatingRules": [
            "Prefer Direct -> Template -> Agent. Do not use deep Agent mode for screenshots, status checks, Back, Home, or read-screen.",
            "During a running phone task, poll matrix watch and logs ledger instead of repeatedly interrupting the worker.",
            "Use screenshots and read-screen to correct direction before retrying a failed task.",
            "Use matrix cancel for clearly wrong or unsafe tasks, then dispatch a narrower corrected task.",
            "Bulk outreach, comments, private messages, publishing, or account-affecting actions require explicit user confirmation.",
        ],
        "recovery": {
            "adb": ["phone adb-doctor", "diagnostics run", "matrix status", "phone status"],
            "stuckTask": ["matrix watch", "phone screenshot", "matrix retry", "matrix cancel"],
            "modelNotConfigured": ["models", "wire current", "account sync", "agents model-apply"],
        },
        "experienceLoop": ["logs ledger", "experience report", "template run", "matrix dispatch"],
    }


HELPER_SCRIPTS = {
    "phone:agent": "openclaw-phone-agent.mjs",
    "phone:vision": "openclaw-phone-vision.mjs",
    "phone:video": "openclaw-phone-video.mjs",
    "phone:image": "openclaw-image-phone.mjs",
    "phone:image:edit": "openclaw-image-phone.mjs",
    "phone:fleet": "openclaw-phone-fleet.mjs",
    "phone:game": "openclaw-phone-game.mjs",
    "phone:publish": "openclaw-publish-phone.mjs",
    "phone:relay": "openclaw-publish-relay.mjs",
    "phone:relay:check": "openclaw-publish-relay-check.mjs",
    "phone:relay:smoke": "openclaw-publish-relay-smoke.mjs",
}


def _runtime_paths(paths: AppPaths) -> Json:
    package_json = os.path.join(paths.npm_root, "package.json")
    package_data = _read_json_if_exists(package_json)
    package_scripts = package_data.get("scripts") if isinstance(package_data.get("scripts"), dict) else {}
    helpers: Json = {}
    for script_name, file_name in HELPER_SCRIPTS.items():
        primary_path = os.path.join(paths.scripts_dir, file_name)
        fallback_paths = [
            os.path.join(root, file_name)
            for root in paths.script_roots
            if os.path.normcase(root) != os.path.normcase(paths.scripts_dir)
        ]
        fallback = next((item for item in fallback_paths if os.path.exists(item)), "")
        helpers[script_name] = {
            "script": file_name,
            "packageScript": str(package_scripts.get(script_name) or package_scripts.get(script_name.replace("phone:", "loom:phone:")) or ""),
            "path": primary_path,
            "exists": os.path.exists(primary_path),
            "fallbackPath": fallback,
            "fallbackExists": bool(fallback),
        }
    return {
        "schema": "loom.runtime_paths.v1",
        "basePath": paths.base_path,
        "payloadRoots": list(paths.payload_roots),
        "npmRoot": paths.npm_root,
        "packageJson": package_json,
        "scriptsRoot": paths.scripts_dir,
        "pythonDir": paths.python_dir,
        "pythonRuntimeDir": paths.python_runtime_dir,
        "pythonExe": paths.python_exe,
        "cliPath": os.path.join(paths.python_dir, "loom_cli.py"),
        "mcpPath": os.path.join(paths.python_dir, "loom_mcp.py"),
        "nodeDir": paths.node_dir,
        "nodeExe": paths.node_exe,
        "adbPath": paths.adb_exe,
        "adbBundled": paths.adb_is_bundled,
        "openclawMjs": paths.openclaw_mjs,
        "helpers": helpers,
    }


def _status(ctx: CliContext) -> Json:
    return {
        "launcher": "LOOM",
        "basePath": ctx.paths.base_path,
        "dataDir": ctx.paths.data_dir,
        "bridgeConfigured": bool(ctx.bridge_url),
        "permission": ctx.permission,
        "time": _now_iso(),
    }


def _doctor(ctx: CliContext) -> Json:
    runtime = _runtime_paths(ctx.paths)
    issues = []
    for name, helper in runtime["helpers"].items():
        command = str(helper.get("packageScript") or "")
        if command and not helper.get("exists"):
            issues.append({
                "code": "missing_helper_script",
                "severity": "error",
                "helper": name,
                "path": helper.get("path"),
                "fallbackPath": helper.get("fallbackPath") or "",
            })
    python_version = _process_version([runtime["pythonExe"], "--version"])
    node_version = _process_version([runtime["nodeExe"], "--version"])
    return {
        "schema": "loom.doctor.v1",
        "time": _now_iso(),
        "paths": runtime,
        "python": {
            "executable": runtime["pythonExe"],
            "version": python_version,
            "minimum": "3.9",
            "bundledRuntimeExists": _bundled_python_exists(runtime),
            "currentExecutable": sys.executable,
            "currentVersion": ".".join(str(item) for item in sys.version_info[:3]),
        },
        "node": {
            "executable": runtime["nodeExe"],
            "version": node_version,
            "exists": os.path.exists(runtime["nodeExe"]),
        },
        "scripts": runtime["helpers"],
        "phone": {
            "bridgeConfigured": bool(ctx.bridge_url),
            "bridgeUrl": _redact_url(ctx.bridge_url),
            "liveStatus": "not_checked",
            "screenRecordingPermission": "system_prompt_may_require_first_manual_approval",
            "adbPath": runtime["adbPath"],
            "adbBundled": runtime["adbBundled"],
            "adbDoctor": "phone adb-doctor --json --permission admin",
        },
        "issues": issues,
        "ok": not any(item["severity"] == "error" for item in issues),
    }


def _bundled_python_exists(runtime: Json) -> bool:
    runtime_dir = str(runtime.get("pythonRuntimeDir") or "")
    if not runtime_dir:
        return False
    names = ("python.exe", "python") if os.name == "nt" else ("bin/python3", "bin/python", "python3", "python")
    return any(os.path.exists(os.path.join(runtime_dir, name)) for name in names)


def _process_version(argv: list[str]) -> str:
    exe = argv[0] if argv else ""
    if not exe or not os.path.exists(exe):
        return ""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or completed.stderr).strip().splitlines()[0] if (completed.stdout or completed.stderr).strip() else ""


def _bridge_session_path() -> str:
    explicit = os.environ.get("LOOM_BRIDGE_SESSION_FILE", "").strip()
    if explicit:
        return explicit
    base_dir = os.environ.get("LOOM_BRIDGE_SESSION_DIR", "").strip()
    if not base_dir:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            base_dir = os.path.join(local_app_data, "LOOM")
        elif sys.platform == "darwin":
            base_dir = os.path.expanduser("~/Library/Application Support/LOOM")
        else:
            base_dir = os.path.expanduser("~/.local/share/loom")
    return os.path.join(base_dir, "bridge-session.json")


def _load_bridge_session() -> Json:
    path = _bridge_session_path()
    if not os.path.exists(path):
        return {}
    data = _read_json_if_exists(path)
    if data.get("schema") != "loom.bridge_session.v1":
        return {}
    url = str(data.get("url") or "").strip().rstrip("/")
    token = str(data.get("token") or "").strip()
    port = data.get("port")
    if not url and isinstance(port, int):
        url = f"http://127.0.0.1:{port}"
    if not url.startswith("http://127.0.0.1:"):
        return {}
    return {"url": url, "token": token}


def _models(ctx: CliContext) -> Json:
    current = _read_json_if_exists(ctx.paths.wire_current)
    last_good = _read_json_if_exists(ctx.paths.wire_last_good)
    source = "wire-current" if current else "wire-last-good" if last_good else "none"
    wire = current or last_good or {}
    models = wire.get("models") if isinstance(wire, dict) else {}
    if not isinstance(models, dict):
        models = {}
    return {
        "source": source,
        "text": models.get("text") or models.get("primary") or "",
        "phone": models.get("phone") or "qwen3.7-plus",
        "image": models.get("image"),
        "video": models.get("video"),
        "available": _safe_model_lists(wire),
    }


def _logs(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "tail"
    if action not in {"tail", "ledger"}:
        raise CliError("unknown_command", "日志命令只开放 tail、ledger。")
    _require_permission(ctx, "read")
    limit = _int_option(args, "--limit", 100, minimum=1, maximum=500)
    if action == "ledger":
        candidates = [audit_log_path("loom-task-ledger.jsonl")]
    else:
        candidates = [
            audit_log_path("loom-cli-audit.jsonl"),
            audit_log_path("mcp-audit.jsonl"),
            os.path.join(ctx.paths.launcher_dir, "bridge-service.log"),
            os.path.join(ctx.paths.data_dir, "logs", "bridge-service.log"),
        ]
    path = next((item for item in candidates if os.path.exists(item)), candidates[0])
    lines = tail_lines(path, limit)
    return {"path": path, "lines": [_redact(line) for line in lines]}


def _account(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "current"
    if action == "current":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/account/current", {})
    if action == "send-code":
        _require_permission(ctx, "control")
        email = _option(args, "--email") or _positional(args, 1)
        if not email:
            raise CliError("missing_email", "请输入邮箱。")
        return _bridge_call(ctx, "POST", "/api/account/email-code/send", _compact_body({
            "email": email,
            "baseUrl": _option(args, "--base-url"),
        }))
    if action == "login-code":
        _require_permission(ctx, "control")
        email = _option(args, "--email") or _positional(args, 1)
        code = _option(args, "--code") or _positional(args, 2)
        if not email or not code:
            raise CliError("missing_email_code", "请输入邮箱和验证码。")
        return _bridge_call(ctx, "POST", "/api/account/email-code/login", _compact_body({
            "email": email,
            "code": code,
            "baseUrl": _option(args, "--base-url"),
        }))
    if action == "register":
        _require_permission(ctx, "control")
        email = _option(args, "--email") or _positional(args, 1)
        password = _option(args, "--password")
        code = _option(args, "--code")
        if not email or not password or not code:
            raise CliError("missing_register_fields", "注册需要邮箱、密码和验证码。")
        return _bridge_call(ctx, "POST", "/api/account/register", _compact_body({
            "email": email,
            "password": password,
            "code": code,
            "baseUrl": _option(args, "--base-url"),
        }))
    if action == "login":
        _require_permission(ctx, "control")
        username = _option(args, "--username") or _option(args, "--email") or _positional(args, 1)
        password = _option(args, "--password")
        api_token = _option(args, "--api-token")
        if not username and not api_token:
            raise CliError("missing_login_identity", "请输入用户名/邮箱，或提供 apiToken。")
        if username and not password and not api_token:
            raise CliError("missing_password", "密码登录需要密码。")
        return _bridge_call(ctx, "POST", "/api/account/login", _compact_body({
            "username": username,
            "password": password,
            "apiToken": api_token,
            "baseUrl": _option(args, "--base-url"),
        }))
    if action == "bind-ticket":
        _require_permission(ctx, "control")
        ticket = _option(args, "--ticket") or _option(args, "--code") or _positional(args, 1)
        if not ticket:
            raise CliError("missing_ticket", "请输入网站绑定码。")
        return _bridge_call(ctx, "POST", "/api/account/bind-ticket", _compact_body({
            "ticket": ticket,
            "baseUrl": _option(args, "--base-url"),
        }))
    if action == "sync":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/account/sync", {})
    if action == "subscription":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/account/subscription", {})
    if action == "select-models":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/account/models/select", _compact_body({
            "textModel": _option(args, "--text") or _option(args, "--text-model"),
            "imageModel": _option(args, "--image") or _option(args, "--image-model"),
            "videoModel": _option(args, "--video") or _option(args, "--video-model"),
        }))
    if action == "logout":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/account/logout", {})
    raise CliError("unknown_command", "账号命令只开放 current、send-code、login-code、register、login、bind-ticket、sync、subscription、select-models、logout。")


def _wire(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "current"
    if action == "current":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/wire/current", {})
    if action == "sync":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/wire/sync", {})
    if action == "custom":
        _require_permission(ctx, "control")
        base_url = _option(args, "--base-url") or _option(args, "--url")
        api_key = _option(args, "--api-key") or _option(args, "--token")
        text_model = _option(args, "--text-model") or _option(args, "--model")
        if not base_url or not api_key or not text_model:
            raise CliError("missing_wire_custom_fields", "自定义模型需要 Base URL、API Key 和文本模型。")
        return _bridge_call(ctx, "POST", "/api/wire/custom", _compact_body({
            "provider": _option(args, "--provider"),
            "baseUrl": base_url,
            "apiKey": api_key,
            "textModel": text_model,
            "imageModel": _option(args, "--image-model"),
            "phoneModel": _option(args, "--phone-model"),
            "videoModel": _option(args, "--video-model"),
        }))
    if action == "verify":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/wire/verify", {})
    if action == "rollback":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/wire/rollback", {})
    raise CliError("unknown_command", "模型中转命令只开放 current、sync、custom、verify、rollback。")


def _media(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "config"
    if action == "config":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/media/config", {})
    if action == "save-image":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/media/config", {"image": _media_image_body(args)})
    if action == "save-video":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/media/config", {"video": _media_video_body(args)})
    if action == "test-image":
        _require_permission(ctx, "control")
        body: Json = {"kind": "image"}
        if _has_any_option(args, ("--base-url", "--api-key", "--model", "--size", "--ratio", "--count")):
            body["image"] = _media_image_body(args)
        return _bridge_call(ctx, "POST", "/api/media/test", body)
    if action == "test-video":
        _require_permission(ctx, "control")
        body = {"kind": "video"}
        if _has_any_option(args, ("--provider", "--provider-id", "--api-base", "--api-key", "--dash-key", "--model")):
            body["video"] = _media_video_body(args)
        return _bridge_call(ctx, "POST", "/api/media/test", body)
    if action == "image":
        _require_permission(ctx, "control")
        prompt = _option(args, "--prompt") or _positional(args, 1)
        if not prompt:
            raise CliError("missing_prompt", "生图需要提示词。")
        body = _media_image_body(args)
        body["prompt"] = prompt
        body["source"] = "cli"
        if edit_path := _option(args, "--edit-image"):
            body["editImagePath"] = edit_path
        endpoint = "/api/image/generate" if _flag(args, "--sync") else "/api/image/generate/submit"
        return _bridge_call(ctx, "POST", endpoint, body)
    if action == "video":
        _require_permission(ctx, "control")
        prompt = _option(args, "--prompt") or _positional(args, 1)
        if not prompt:
            raise CliError("missing_prompt", "生视频需要提示词。")
        body = _media_video_body(args)
        body["prompt"] = prompt
        body["source"] = "cli"
        if image_path := _option(args, "--image"):
            body["imagePath"] = image_path
        endpoint = "/api/video/generate" if _flag(args, "--sync") else "/api/video/generate/submit"
        return _bridge_call(ctx, "POST", endpoint, body)
    raise CliError("unknown_command", "创作命令只开放 config、save-image、save-video、test-image、test-video、image、video。")


def _agents(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "list"
    if action == "list":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/components/status", {})
    if action == "detect":
        _require_permission(ctx, "control")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要检测的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/detect", {"componentId": component})
    if action == "start":
        _require_permission(ctx, "control")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要启动的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/start", {"componentId": component, "confirmed": True})
    if action == "install":
        _require_permission(ctx, "admin")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要安装的 Agent。")
        body = {"componentId": component, "confirmed": True}
        if _flag(args, "--simulate"):
            body.update({"mode": "simulate", "dryRun": True})
        return _bridge_call(ctx, "POST", "/api/components/install", body)
    if action == "uninstall":
        _require_permission(ctx, "admin")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要卸载的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/uninstall", {"componentId": component, "confirmed": True})
    if action == "rollback":
        _require_permission(ctx, "admin")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要回滚的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/rollback", {"componentId": component, "confirmed": True})
    if action == "model-status":
        _require_permission(ctx, "read")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要查看模型配置的 Agent。")
        return _bridge_call(ctx, "GET", f"/api/components/model-config/status?componentId={urllib.parse.quote(component, safe='')}", {})
    if action == "model-apply":
        _require_permission(ctx, "control")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要写入模型配置的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/model-config/apply", _compact_body({
            "componentId": component,
            "model": _option(args, "--model"),
            "confirmed": True,
        }))
    if action == "model-rollback":
        _require_permission(ctx, "control")
        component = _option(args, "--component") or _positional(args, 1)
        if not component:
            raise CliError("missing_component", "请选择要回滚模型配置的 Agent。")
        return _bridge_call(ctx, "POST", "/api/components/model-config/rollback", {"componentId": component, "confirmed": True})
    raise CliError("unknown_command", "Agent 命令只开放 list、start、install。")


def _jobs(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "list"
    if action == "list":
        _require_permission(ctx, "read")
        limit = _option(args, "--limit") or "30"
        return _bridge_call(ctx, "GET", f"/api/jobs/list?limit={urllib.parse.quote(str(limit), safe='')}", {})
    if action == "get":
        _require_permission(ctx, "read")
        job_id = _option(args, "--id") or _option(args, "--job-id") or _positional(args, 1)
        if not job_id:
            raise CliError("missing_job_id", "请输入 jobId。")
        return _bridge_call(ctx, "GET", f"/api/jobs/{urllib.parse.quote(job_id, safe='')}", {})
    raise CliError("unknown_command", "任务命令只开放 list、get。")


def _settings(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "theme"
    if action == "theme":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/theme/current", {})
    if action == "theme-list":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/theme/list", {})
    if action == "theme-merchant":
        _require_permission(ctx, "read")
        merchant_id = _option(args, "--merchant") or _option(args, "--merchant-id") or _positional(args, 1)
        if not merchant_id:
            raise CliError("missing_merchant_id", "请输入 merchantId。")
        return _bridge_call(ctx, "POST", "/api/theme/by_merchant", {"merchantId": merchant_id})
    if action == "update-check":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/update/check", {})
    if action == "update-do":
        _require_permission(ctx, "admin")
        return _bridge_call(ctx, "POST", "/api/update/do", {"confirmed": True})
    if action == "config-read":
        _require_permission(ctx, "admin")
        path = _option(args, "--path") or _positional(args, 1)
        if not path:
            raise CliError("missing_config_path", "请输入配置路径。")
        return _bridge_call(ctx, "POST", "/api/config/read", {"path": path, "default": _json_option(args, "--default", {})})
    if action == "config-write":
        _require_permission(ctx, "admin")
        path = _option(args, "--path") or _positional(args, 1)
        data = _json_option(args, "--data", None)
        if not path or data is None:
            raise CliError("missing_config_write_fields", "写配置需要 --path 和 --data JSON。")
        return _bridge_call(ctx, "POST", "/api/config/write", {"path": path, "data": data})
    raise CliError("unknown_command", "设置命令只开放 theme、theme-list、theme-merchant、update-check、update-do、config-read、config-write。")


def _diagnostics(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "run"
    if action == "run":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/diagnostics/run", {})
    if action == "repair":
        _require_permission(ctx, "admin")
        check_id = _option(args, "--check") or _option(args, "--id") or _positional(args, 1)
        if not check_id:
            raise CliError("missing_check_id", "请输入要修复的检查项。")
        repair_scope = check_id.strip().lower()
        if repair_scope != "prerequisites":
            raise CliError("unsupported_repair_target", "当前仅支持 prerequisites 定向修复。")
        return _bridge_call(ctx, "POST", "/api/diagnostics/repair", {"scope": repair_scope, "confirmed": True})
    if action == "export":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/diagnostics/export", {})
    raise CliError("unknown_command", "诊断命令只开放 run、repair、export。")


def _license(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "current"
    if action == "current":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/license/current", {})
    if action == "activate":
        _require_permission(ctx, "control")
        code = _option(args, "--code") or _positional(args, 1)
        if not code:
            raise CliError("missing_license_code", "请输入授权码。")
        return _bridge_call(ctx, "POST", "/api/license/activate", {"code": code})
    if action == "authorized":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/license/authorized", _compact_body({"feature": _option(args, "--feature") or _positional(args, 1)}))
    raise CliError("unknown_command", "授权命令只开放 current、activate、authorized。")


def _phone(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else ""
    if action == "status":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/phone/status", _compact_body({
            "deviceId": _phone_device_target(args),
        }))
    if action == "screenshot":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/phone/screenshot", _compact_body({
            "deviceId": _phone_device_target(args),
        }))
    if action in {"adb-doctor", "adb-repair"}:
        _require_permission(ctx, "admin")
        return _bridge_call(
            ctx,
            "POST",
            "/api/phone/adb-doctor",
            _compact_body({
                "confirmed": True,
                "serial": _option(args, "--serial") or _option(args, "--device-id"),
                "wake": not _flag(args, "--no-wake"),
                "launch": not _flag(args, "--no-launch"),
                "restartServer": not _flag(args, "--no-restart-server"),
            }),
        )
    if action in {"read", "read-screen"}:
        _require_permission(ctx, "read")
        prompt = _option(args, "--prompt") or PHONE_TEMPLATE_PROMPTS["read-screen"]
        body = {"prompt": prompt, "profile": "fast", "fastPath": "observe_fast"}
        if device_id := _phone_device_target(args):
            body["deviceId"] = device_id
        known_hash = _option(args, "--known-hash") or _option(args, "--screen-hash")
        if known_hash:
            body["knownHash"] = known_hash
        return _bridge_call(ctx, "POST", "/api/phone/read", body)
    if action in {"events-start", "event-start", "stream-start"}:
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/phone/events/start", _compact_body({
            "deviceId": _option(args, "--device-id"),
            "maxSec": _option(args, "--max-sec"),
            "maxEvents": _option(args, "--max-events"),
        }))
    if action in {"events-status", "event-status", "stream-status"}:
        _require_permission(ctx, "read")
        device_id = _option(args, "--device-id")
        endpoint = "/api/phone/events/status"
        if device_id:
            endpoint = f"{endpoint}?deviceId={urllib.parse.quote(device_id, safe='')}"
        return _bridge_call(ctx, "GET", endpoint, {})
    if action in {"events-stop", "event-stop", "stream-stop"}:
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "POST", "/api/phone/events/stop", _compact_body({
            "deviceId": _option(args, "--device-id"),
        }))
    if action in {"quick-task", "run-task"}:
        _require_permission(ctx, "control")
        prompt = _option(args, "--prompt") or ""
        mode = (_option(args, "--mode") or "safe").lower()
        body = _phone_task_body(prompt, mode, args)
        _check_outreach_safety(prompt)
        return _bridge_call(ctx, "POST", "/api/phone/task", body)
    if action == "template-task":
        template = _option(args, "--template") or _positional(args, 1) or "read-screen"
        if template not in PHONE_TEMPLATE_PROMPTS:
            raise CliError("unknown_template", "手机模板任务只开放 read-screen、screen-summary、back、home。")
        if template == "read-screen":
            _require_permission(ctx, "read")
            return _bridge_call(
                ctx,
                "POST",
                "/api/phone/read",
                _compact_body({
                    "prompt": PHONE_TEMPLATE_PROMPTS[template],
                    "profile": "fast",
                    "template": template,
                    "fastPath": "observe_fast",
                    "deviceId": _phone_device_target(args),
                }),
            )
        if template == "screen-summary":
            _require_permission(ctx, "read")
            body = _phone_task_body(PHONE_TEMPLATE_PROMPTS[template], "observe", args)
            body["template"] = template
            body["executionLayer"] = "template"
            return _bridge_call(ctx, "POST", "/api/phone/task", body)
        _require_permission(ctx, "control")
        body = _phone_task_body(PHONE_TEMPLATE_PROMPTS[template], "safe", args)
        body["template"] = template
        body["executionLayer"] = "template"
        return _bridge_call(ctx, "POST", "/api/phone/task", body)
    raise CliError("unknown_command", "手机命令只开放 status、screenshot、read、read-screen、quick-task、run-task、template-task。")


def _schedule(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "list"
    if action == "list":
        _require_permission(ctx, "read")
        return {"tasks": _load_schedule(ctx)}
    if action == "add":
        _require_permission(ctx, "automation")
        name = _option(args, "--name") or "LOOM task"
        command = _option(args, "--command")
        if not command:
            raise CliError("missing_schedule_command", "请填写定时任务命令。")
        if not _is_allowed_scheduled_command(command):
            raise CliError("invalid_schedule_command", "该命令不允许加入定时任务。")
        schedule_at = _option(args, "--at")
        every = _option(args, "--every")
        if not schedule_at and not every:
            raise CliError("missing_schedule_time", "请设置 --at 或 --every。")
        task = {
            "id": f"task-{uuid.uuid4().hex[:12]}",
            "name": name,
            "command": command,
            "at": schedule_at,
            "every": every,
            "enabled": True,
            "createdAt": _now_iso(),
            "lastRunAt": None,
            "lastResult": None,
        }
        if ctx.dry_run:
            return {"task": task, "dryRun": True}
        tasks = _load_schedule(ctx)
        tasks.append(task)
        _save_schedule(ctx, tasks)
        return {"task": task}
    if action == "cancel":
        _require_permission(ctx, "automation")
        task_id = _option(args, "--id") or _positional(args, 1)
        if not task_id:
            raise CliError("missing_task_id", "请提供任务 ID。")
        if ctx.dry_run:
            return {"task": {"id": task_id}, "action": action, "dryRun": True}
        task = _find_task(ctx, task_id)
        task["enabled"] = False
        tasks = _replace_task(ctx, task)
        _save_schedule(ctx, tasks)
        return {"task": task}
    if action == "run":
        _require_permission(ctx, "automation")
        task_id = _option(args, "--id") or _positional(args, 1)
        if not task_id:
            raise CliError("missing_task_id", "请提供任务 ID。")
        if ctx.dry_run:
            return {"task": {"id": task_id}, "action": action, "dryRun": True}
        task = _find_task(ctx, task_id)
        command = str(task.get("command") or "")
        child_code, child_payload = dispatch(
            [*shlex.split(command), "--json", "--permission", ctx.permission],
            base_path=ctx.paths.base_path,
        )
        task["lastRunAt"] = _now_iso()
        task["lastResult"] = {"ok": child_code == 0, "code": child_code}
        _save_schedule(ctx, _replace_task(ctx, task))
        if child_code != 0:
            child_error = child_payload.get("error") if isinstance(child_payload.get("error"), dict) else {}
            raise CliError(
                str(child_error.get("code") or "scheduled_command_failed"),
                str(child_error.get("message") or "定时任务命令执行失败。"),
                child_code,
            )
        return {"task": task, "result": child_payload}
    raise CliError("unknown_command", "定时任务命令只开放 list、add、run、cancel。")


def _acquisition(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "agent-run"
    if action in {"agent-run", "run-agent"}:
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/agent/run", _acquisition_agent_body(args))
    if action in {"agent-result", "ingest-result"}:
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/agent/result", _acquisition_agent_result_body(args))
    raise CliError("unknown_command", "Acquisition command supports agent-run and agent-result.")


def _matrix(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "status"
    if action == "status":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/matrix/status", {})
    if action == "dispatch":
        _require_permission(ctx, "control")
        prompt = _option(args, "--prompt") or _positional(args, 1)
        if prompt and not _flag(args, "--confirmed"):
            _check_outreach_safety(prompt)
        body = _matrix_dispatch_body(args)
        _check_matrix_safety(body)
        return _bridge_call(ctx, "POST", "/api/matrix/dispatch", body)
    if action == "watch":
        _require_permission(ctx, "read")
        campaign_id = _option(args, "--campaign") or _option(args, "--campaign-id") or _positional(args, 1)
        query: list[tuple[str, str]] = []
        if campaign_id:
            query.append(("campaignId", campaign_id))
        if limit := _option(args, "--limit"):
            query.append(("limit", limit))
        endpoint = "/api/matrix/watch"
        if query:
            endpoint = f"{endpoint}?{urllib.parse.urlencode(query)}"
        return _bridge_call(ctx, "GET", endpoint, {})
    if action == "cancel":
        _require_permission(ctx, "control")
        if _flag(args, "--all"):
            return _bridge_call(ctx, "POST", "/api/matrix/cancel", {"all": True})
        campaign_id = _option(args, "--campaign") or _option(args, "--campaign-id") or _positional(args, 1)
        if not campaign_id:
            raise CliError("missing_campaign", "请提供 campaignId。")
        return _bridge_call(ctx, "POST", "/api/matrix/cancel", {"campaignId": campaign_id})
    if action == "retry":
        _require_permission(ctx, "control")
        campaign_id = _option(args, "--campaign") or _option(args, "--campaign-id") or _positional(args, 1)
        if not campaign_id:
            raise CliError("missing_campaign", "请提供 campaignId。")
        body: Json = {"campaignId": campaign_id}
        if prompt := _option(args, "--prompt"):
            body["prompt"] = prompt
        if _flag(args, "--confirmed"):
            body["confirmed"] = True
        return _bridge_call(ctx, "POST", "/api/matrix/retry", body)
    if action == "leads":
        _require_permission(ctx, "read")
        limit = _option(args, "--limit") or "100"
        return _bridge_call(ctx, "GET", f"/api/matrix/leads?limit={urllib.parse.quote(str(limit), safe='')}", {})
    if action == "record-lead":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/leads", _lead_body(args))
    raise CliError("unknown_command", "Matrix 命令只开放 status、dispatch、watch、cancel、retry、leads、record-lead。")


def _template(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "run"
    if action in {"list", "status"}:
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/matrix/acquisition/templates", {})
    if action == "save":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/templates/save", _template_save_body(args))
    if action == "upload":
        _require_permission(ctx, "control")
        template_id = _option(args, "--template-id") or _option(args, "--id") or _positional(args, 1)
        if not template_id:
            raise CliError("missing_template_id", "Provide --template-id for template upload.")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/templates/upload", {"templateId": template_id})
    if action == "retry":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/templates/retry", {})
    if action == "consent":
        _require_permission(ctx, "control")
        enable = _flag(args, "--enable")
        disable = _flag(args, "--disable")
        if enable == disable:
            raise CliError("template_consent_choice_required", "Use exactly one of --enable or --disable.")
        return _bridge_call(
            ctx,
            "POST",
            "/api/matrix/acquisition/templates/cloud-consent",
            {"enabled": enable, "retryPending": enable and _flag(args, "--retry-pending")},
        )
    if action != "run":
        raise CliError("unknown_command", "模板命令只开放 run、list、save、upload、retry、consent。")
    template = _option(args, "--template") or _positional(args, 1) or "read-screen"
    prompt = _option(args, "--prompt") or PHONE_TEMPLATE_PROMPTS.get(template, "")
    permission = "read" if template in {"read-screen", "screen-summary"} else "control"
    _require_permission(ctx, permission)
    target = _matrix_target(args)
    if not target:
        raise CliError("missing_target", "请明确指定 --target、--device、--group 或 --target all，防止模板任务误广播。")
    body: Json = {
        "template": template,
        "prompt": prompt or template,
        "profile": "fast",
        "target": target,
        "executionLayer": "template",
    }
    if _flag(args, "--confirmed"):
        body["confirmed"] = True
    _check_matrix_safety(body)
    return _bridge_call(ctx, "POST", "/api/matrix/template/run", body)


def _template_save_body(args: list[str]) -> Json:
    platform = _option(args, "--platform") or "manual"
    return {
        "name": _option(args, "--name") or _option(args, "--topic") or "获客打法模板",
        "topic": _option(args, "--topic") or _option(args, "--name") or "获客打法模板",
        "industry": _option(args, "--industry") or _option(args, "--category") or "通用获客",
        "platform": platform,
        "platforms": _csv_option(args, "--platforms") or [platform],
        "targetCustomer": _option(args, "--target") or _option(args, "--target-customer") or "",
        "keywords": _csv_option(args, "--keywords"),
        "leadRules": _csv_option(args, "--lead-rules") or _csv_option(args, "--rules"),
        "replyStyle": _option(args, "--reply-style") or _option(args, "--knowledge") or "",
        "knowledge": _option(args, "--knowledge") or _option(args, "--reply-style") or "",
        "source": "loom_cli",
    }


def _acquisition_agent_body(args: list[str]) -> Json:
    platform = _option(args, "--platform") or "tiktok"
    device_id = _option(args, "--device-id") or _option(args, "--device") or "phone-1"
    task_id = _option(args, "--task-id") or f"agent_task_{uuid.uuid4().hex[:10]}"
    real_run = _flag(args, "--real-run")
    confirmed = _flag(args, "--confirmed")
    if real_run and not confirmed:
        raise CliError("confirmation_required", "acquisition agent-run --real-run requires --confirmed and still stops at human confirmation.")
    body: Json = {
        "taskId": task_id,
        "dryRun": not real_run,
        "confirmed": confirmed,
        "platform": platform,
        "topic": _option(args, "--topic") or f"{platform} 手机 Agent 获客任务",
        "action": _option(args, "--action") or "discover_leads",
        "deviceId": device_id,
        "knowledge": _option(args, "--knowledge") or "",
        "target": _option(args, "--target") or "",
        "owner": _option(args, "--owner") or "loom-cli",
    }
    body["phoneTaskPreview"] = _acquisition_phone_task_preview(body, device_id)
    result_json = _option(args, "--agent-result-json")
    if result_json:
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError as exc:
            raise CliError("invalid_agent_result_json", f"Invalid --agent-result-json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise CliError("invalid_agent_result_json", "--agent-result-json must be a JSON object.")
        body["agentResult"] = parsed
    return body


def _acquisition_agent_result_body(args: list[str]) -> Json:
    result_json = _option(args, "--agent-result-json")
    if not result_json:
        raise CliError("missing_agent_result_json", "acquisition agent-result requires --agent-result-json with loom.acquisition.agent_result.v1 payload.")
    try:
        parsed = json.loads(result_json)
    except json.JSONDecodeError as exc:
        raise CliError("invalid_agent_result_json", f"Invalid --agent-result-json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CliError("invalid_agent_result_json", "--agent-result-json must be a JSON object.")
    platform = _option(args, "--platform") or parsed.get("platform") or "tiktok"
    device_id = _option(args, "--device-id") or _option(args, "--device") or parsed.get("deviceId") or "phone-1"
    return {
        "dryRun": True,
        "platform": platform,
        "topic": _option(args, "--topic") or f"{platform} 手机 Agent 获客结果",
        "action": _option(args, "--action") or parsed.get("action") or "discover_leads",
        "deviceId": device_id,
        "knowledge": _option(args, "--knowledge") or "",
        "target": _option(args, "--target") or "",
        "owner": _option(args, "--owner") or "loom-cli",
        "agentResult": parsed,
    }


def _acquisition_phone_task_preview(body: Json, device_id: str) -> Json:
    platform = body.get("platform") or "tiktok"
    topic = body.get("topic") or ""
    prompt = (
        f"在{platform}执行{topic}。只读取可见公开内容，识别潜在线索，生成跟进草稿；"
        "如需触达，只能填草稿并停在人工确认页。"
        f"目标客户：{body.get('target') or ''}。SOP：{body.get('knowledge') or ''}。"
        "返回 JSON 必须符合 loom.acquisition.agent_result.v1，字段包含 taskId、deviceId、platform、action、status、leads、drafts、logs；"
        "禁止自动私信、评论、加好友、加微信或发布。"
    )[:900]
    payload = {
        "schema": "loom.acquisition.phone_task.v1",
        "taskId": body.get("taskId") or f"agent_task_{uuid.uuid4().hex[:10]}",
        "platform": platform,
        "action": body.get("action") or "discover_leads",
        "topic": topic,
        "mode": "safe",
        "profile": "fast",
        "target": {"deviceIds": [device_id]},
        "resultSchema": "loom.acquisition.agent_result.v1",
        "stopAt": "human_confirmation",
        "requiresHumanReview": True,
        "sendEnabled": False,
        "allowedActions": ["open_app", "read_public_content", "summarize_leads", "fill_draft", "capture_screenshot"],
        "forbiddenActions": ["send_dm", "post_comment", "add_friend", "add_wechat", "bulk_outreach", "publish_without_confirmation"],
        "outboundPolicy": ["draft_only", "manual_confirm", "whitelist", "frequency_cap", "audit_log"],
        "prompt": prompt,
    }
    payload["bridgeDispatch"] = {
        "method": "POST",
        "endpoint": "/api/phone/task",
        "body": {
            "taskId": payload["taskId"],
            "prompt": prompt,
            "mode": "safe",
            "profile": "fast",
            "executionLayer": "agent",
            "target": {"deviceIds": [device_id]},
            "template": "",
            "requiresHumanReview": True,
            "sendEnabled": False,
            "resultSchema": "loom.acquisition.agent_result.v1",
            "outboundPolicy": ["draft_only", "manual_confirm", "whitelist", "frequency_cap", "audit_log"],
            "resultCallback": {
                "method": "POST",
                "endpoint": "/api/matrix/acquisition/agent/result",
                "payloadField": "agentResult",
            },
        },
    }
    return payload


def _experience(args: list[str], ctx: CliContext) -> Json:
    action = args[0] if args else "report"
    if action != "report":
        raise CliError("unknown_command", "经验命令只开放 report。")
    _require_permission(ctx, "read")
    return _bridge_call(ctx, "GET", "/api/matrix/experience", {})


def _integration(args: list[str], ctx: CliContext) -> Json:
    provider = args[0] if args else ""
    if provider != "feishu":
        raise CliError("unknown_command", "Integration command currently supports feishu only.")
    action = args[1] if len(args) > 1 else "status"
    rest = args[2:]
    if action == "doctor":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/matrix/acquisition/feishu/doctor", {})
    if action == "status":
        _require_permission(ctx, "read")
        return _bridge_call(ctx, "GET", "/api/matrix/acquisition/feishu/status", {})
    if action == "install":
        _require_permission(ctx, "admin")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/install", {"confirmed": _flag(rest, "--confirmed")})
    if action == "login":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/login", {})
    if action == "bind-table":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/bind-table", _feishu_bind_body(rest))
    if action == "create-table":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/create-table", {"confirmed": _flag(rest, "--confirmed")})
    if action == "test-write":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/test-write", {})
    if action == "retry-sync":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/retry-sync", {})
    if action == "reconcile":
        _require_permission(ctx, "control")
        return _bridge_call(ctx, "POST", "/api/matrix/acquisition/feishu/reconcile", {})
    raise CliError("unknown_command", "Feishu integration supports doctor, status, install, login, bind-table, create-table, test-write, retry-sync, reconcile.")


def _bridge_call(ctx: CliContext, method: str, endpoint: str, body: Json) -> Json:
    if ctx.dry_run:
        return {"method": method, "endpoint": endpoint, "body": _redact_json(body), "dryRun": True}
    if not ctx.bridge_url:
        raise CliError("bridge_not_configured", "Bridge 地址未配置，请先启动 LOOM。", 4)

    url = f"{ctx.bridge_url}{endpoint}"
    data = None if method == "GET" else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    if ctx.bridge_token:
        request.add_header("X-Bridge-Token", ctx.bridge_token)

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise CliError("bridge_http_error", _extract_bridge_error(text) or f"Bridge 返回 {exc.code}。", 4)
    except urllib.error.URLError as exc:
        raise CliError("bridge_unavailable", f"Bridge 暂不可用：{_public_error(exc)}", 4)

    if not text.strip():
        return {"method": method, "endpoint": endpoint, "result": None}
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"raw": _redact(text[:4000])}
    return {"method": method, "endpoint": endpoint, "result": _redact_json(result)}


def _phone_task_body(prompt: str, mode: str, args: list[str] | None = None) -> Json:
    body: Json = {
        "prompt": prompt,
        "mode": "safe",
        "profile": "fast",
        "maxRounds": 12,
    }
    direct = _direct_phone_action_exact(prompt)
    if direct:
        body["action"] = direct
    if mode == "observe":
        body["mode"] = "observe"
        body["profile"] = "fast"
        body["maxRounds"] = 4
    elif mode == "deep":
        body["mode"] = "full"
        body["profile"] = "deep"
        body["maxRounds"] = 30
    elif mode == "full":
        body["mode"] = "full"
        body["profile"] = "standard"
        body["maxRounds"] = 30
    elif mode in {"safe", "standard", "fast"}:
        body["mode"] = "safe"
        body["profile"] = "fast" if mode in {"safe", "fast"} else "standard"
        body["maxRounds"] = 12
    else:
        raise CliError("invalid_phone_mode", "手机任务模式只支持 observe、safe、standard、full、deep。")
    runtime_args = args or []
    if device_id := _phone_device_target(runtime_args):
        body["deviceId"] = device_id
    _apply_phone_task_runtime_options(body, runtime_args)
    return body


def _phone_device_target(args: list[str]) -> str:
    return (
        _option(args, "--device")
        or _option(args, "--device-id")
        or _option(args, "--target")
    ).strip()


def _apply_phone_task_runtime_options(body: Json, args: list[str]) -> None:
    profile = (
        _option(args, "--profile")
        or _option(args, "--performance-profile")
        or _option(args, "--task-profile")
    ).lower()
    profile_aliases = {
        "quick": "fast",
        "demo": "fast",
        "normal": "standard",
        "default": "standard",
        "stable": "standard",
        "slow": "deep",
        "complex": "deep",
    }
    profile = profile_aliases.get(profile, profile)
    if profile:
        if profile not in {"fast", "standard", "deep"}:
            raise CliError("invalid_phone_profile", "Phone profile must be fast, standard, or deep.")
        body["profile"] = profile
    for option, key, minimum, maximum in (
        ("--timeout-sec", "timeoutSec", 30, 1200),
        ("--max-wait-sec", "maxWaitSec", 45, 1260),
        ("--max-rounds", "maxRounds", 1, 120),
        ("--poll-ms", "pollMs", 500, 1200),
    ):
        value = _optional_int_option(args, option, minimum=minimum, maximum=maximum)
        if value is not None:
            body[key] = value


def _matrix_dispatch_body(args: list[str]) -> Json:
    prompt = _option(args, "--prompt") or _positional(args, 1)
    if not prompt:
        raise CliError("missing_prompt", "请填写 Matrix 任务内容。")
    mode = (_option(args, "--mode") or "safe").lower()
    profile = (_option(args, "--profile") or "fast").lower()
    template = _option(args, "--template") or _matrix_template_from_prompt(prompt)
    action = _direct_phone_action_exact(prompt)
    target = _matrix_target(args)
    if not target:
        raise CliError("missing_target", "请明确指定 --target、--device、--group 或 --target all，防止任务误广播。")
    body: Json = {
        "title": _option(args, "--title") or prompt[:40],
        "prompt": prompt,
        "mode": "observe" if mode == "observe" else "full" if mode in {"full", "deep"} else "safe",
        "profile": "deep" if mode == "deep" else profile if profile in {"fast", "standard", "deep"} else "fast",
        "target": target,
        "executionLayer": _matrix_execution_layer(prompt, body_mode=mode, template=template, action=action),
    }
    if template:
        body["template"] = template
    if action:
        body["action"] = action
    if _flag(args, "--confirmed"):
        body["confirmed"] = True
    return body


def _matrix_target(args: list[str]) -> Json:
    target: Json = {}
    devices = (
        _csv_option(args, "--device")
        + _csv_option(args, "--device-id")
        + _csv_option(args, "--target")
    )
    groups = _csv_option(args, "--group")
    devices = list(dict.fromkeys(devices))
    groups = list(dict.fromkeys(groups))
    all_requested = any(value.lower() == "all" for value in devices)
    devices = [value for value in devices if value.lower() != "all"]
    if all_requested and (devices or groups):
        raise CliError("invalid_target", "--target all 不能与具体设备或分组同时使用。")
    if devices and groups:
        raise CliError("invalid_target", "Matrix target cannot mix device and group selectors.")
    if all_requested:
        target["allOnline"] = True
    if devices:
        target["deviceIds"] = devices[:100]
    if groups:
        target["groups"] = groups[:100]
    return target


def _lead_body(args: list[str]) -> Json:
    summary = _option(args, "--summary") or _option(args, "--note") or _positional(args, 1)
    if not summary:
        raise CliError("missing_lead_summary", "请提供线索摘要。")
    body: Json = {
        "summary": summary,
        "source": _option(args, "--source") or "manual",
        "status": _option(args, "--status") or "new",
    }
    for option, key in (
        ("--title", "title"),
        ("--device", "deviceId"),
        ("--device-id", "deviceId"),
        ("--campaign", "campaignId"),
        ("--campaign-id", "campaignId"),
        ("--device-task", "deviceTaskId"),
        ("--device-task-id", "deviceTaskId"),
    ):
        value = _option(args, option)
        if value:
            body[key] = value
    tags = _multi_option(args, "--tag")
    if tags:
        body["tags"] = tags
    return body


def _feishu_bind_body(args: list[str]) -> Json:
    body: Json = {
        "url": _option(args, "--url") or _option(args, "--table-url") or _positional(args, 0),
        "baseToken": _option(args, "--base-token"),
        "tableId": _option(args, "--table-id"),
        "name": _option(args, "--name") or "麓鸣获客线索表",
    }
    if not body["url"] and not (body["baseToken"] and body["tableId"]):
        raise CliError("missing_feishu_table", "Provide a Feishu table URL, or both --base-token and --table-id.")
    return _compact_body(body)


def _matrix_execution_layer(prompt: str, *, body_mode: str, template: str, action: str) -> str:
    if body_mode == "observe" or action:
        return "direct"
    if template:
        return "template"
    if _matrix_template_from_prompt(prompt):
        return "template"
    return "agent"


def _matrix_template_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", "", str(prompt or "").strip().lower())
    if any(token in text for token in {"打开系统设置", "打开设置", "系统设置", "opensettings"}):
        return "open-settings"
    if any(token in text for token in {"读取当前屏幕", "读屏", "screen-summary"}):
        return "read-screen"
    return ""


def _check_matrix_safety(body: Json) -> None:
    prompt = str(body.get("prompt") or "")
    if body.get("confirmed"):
        return
    _check_outreach_safety(prompt)


def _check_outreach_safety(prompt: str) -> None:
    markers = ("批量私信", "私信所有", "自动私信", "批量评论", "自动评论", "自动回复", "批量触达", "群发", "骚扰")
    if any(marker in prompt for marker in markers) or _looks_like_garbled_control_prompt(prompt):
        raise CliError("safety_confirmation_required", "批量触达、私信、评论或自动回复任务需要用户明确确认。", 3)


def _looks_like_garbled_control_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if "\ufffd" in text:
        return True
    return bool(re.search(r"\?{4,}", text))


def _direct_phone_action(prompt: str) -> str | None:
    lowered = prompt.strip().lower()
    if any(word in lowered for word in ("返回", "back", "上一页")):
        return "back"
    if any(word in lowered for word in ("home", "桌面", "主页")):
        return "home"
    return None


def _direct_phone_action_exact(prompt: str) -> str | None:
    lowered = re.sub(r"\s+", "", prompt.strip().lower())
    back_words = {"back", "pressback", "\u8fd4\u56de", "\u8fd4\u56de\u4e0a\u4e00\u9875", "\u4e0a\u4e00\u9875", "\u540e\u9000"}
    if lowered in back_words:
        return "back"
    home_words = {"home", "presshome", "\u56de\u5230\u684c\u9762", "\u8fd4\u56de\u684c\u9762", "\u684c\u9762", "\u4e3b\u9875", "\u56de\u4e3b\u9875"}
    if lowered in home_words:
        return "home"
    return None


def _load_schedule(ctx: CliContext) -> list[Json]:
    path = _schedule_path(ctx)
    data = _read_json_if_exists(path)
    tasks = data.get("tasks") if isinstance(data, dict) else []
    return tasks if isinstance(tasks, list) else []


def _save_schedule(ctx: CliContext, tasks: list[Json]) -> None:
    path = _schedule_path(ctx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"tasks": tasks}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _schedule_path(ctx: CliContext) -> str:
    return os.path.join(ctx.paths.launcher_dir, "scheduler-tasks.json")


def _find_task(ctx: CliContext, task_id: str | None) -> Json:
    if not task_id:
        raise CliError("missing_task_id", "请提供任务 ID。")
    for task in _load_schedule(ctx):
        if task.get("id") == task_id:
            return dict(task)
    raise CliError("task_not_found", "未找到该定时任务。", 4)


def _replace_task(ctx: CliContext, replacement: Json) -> list[Json]:
    tasks = []
    for task in _load_schedule(ctx):
        tasks.append(replacement if task.get("id") == replacement.get("id") else task)
    return tasks


def _is_allowed_scheduled_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    if parts[0] in SAFE_SCHEDULE_ROOTS:
        return True
    if len(parts) >= 2 and (parts[0], parts[1]) in SAFE_SCHEDULE_PAIRS:
        return True
    return False


def _require_permission(ctx: CliContext, required: str) -> None:
    if PERMISSION_LEVELS[ctx.permission] < PERMISSION_LEVELS[required]:
        raise PermissionDenied(required, ctx.permission)


def _success(command: str, data: Json) -> Json:
    return {"ok": True, "command": command, "data": data}


def _failure(command: str, code: str, message: str) -> Json:
    return {"ok": False, "command": command, "error": {"code": code, "message": _redact(message)}}


def _read_json_if_exists(path: str) -> Json:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_model_lists(wire: Json) -> Json:
    models = wire.get("availableModels") if isinstance(wire, dict) else {}
    if not isinstance(models, dict):
        models = {}
    return {
        key: value[:100] if isinstance(value, list) else []
        for key, value in models.items()
        if key in {"text", "image", "video", "phone"}
    }


def _media_image_body(args: list[str]) -> Json:
    ratio = _option(args, "--ratio")
    size = _option(args, "--size") or IMAGE_RATIO_TO_SIZE.get(ratio) or "1024x1024"
    body: Json = {
        "baseUrl": _option(args, "--base-url") or _option(args, "--url"),
        "apiKey": _option(args, "--api-key") or _option(args, "--token"),
        "model": _option(args, "--model") or _option(args, "--image-model"),
        "size": size,
        "ratio": ratio,
    }
    count = _option(args, "--count")
    if count:
        try:
            body["count"] = max(1, min(int(count), 9))
        except ValueError:
            raise CliError("invalid_count", "图片数量必须是数字。")
    return _compact_body(body)


def _media_video_body(args: list[str]) -> Json:
    body: Json = {
        "providerId": _option(args, "--provider") or _option(args, "--provider-id"),
        "apiBase": _option(args, "--api-base") or _option(args, "--base-url") or _option(args, "--url"),
        "apiKey": _option(args, "--api-key") or _option(args, "--dash-key") or _option(args, "--token"),
        "dashKey": _option(args, "--dash-key") or _option(args, "--api-key") or _option(args, "--token"),
        "model": _option(args, "--model") or _option(args, "--video-model"),
        "mode": _option(args, "--mode") or "t2v",
        "resolution": _option(args, "--resolution") or "720P",
        "ratio": _option(args, "--ratio") or "16:9",
    }
    duration = _option(args, "--duration")
    if duration:
        try:
            body["duration"] = max(1, min(int(duration), 30))
        except ValueError:
            raise CliError("invalid_duration", "视频时长必须是数字。")
    return _compact_body(body)


def _compact_body(body: Json) -> Json:
    return {key: value for key, value in body.items() if value not in ("", None, [], {})}


def _has_any_option(args: list[str], names: tuple[str, ...]) -> bool:
    prefixes = tuple(f"{name}=" for name in names)
    return any(item in names or item.startswith(prefixes) for item in args)


def _json_option(args: list[str], name: str, default: Any) -> Any:
    raw = _option(args, name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError("invalid_json", f"{name} 必须是 JSON。") from exc


def _option(args: list[str], name: str) -> str:
    prefix = f"{name}="
    for index, item in enumerate(args):
        if item == name and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(prefix):
            return item.split("=", 1)[1]
    return ""


def _multi_option(args: list[str], name: str) -> list[str]:
    values: list[str] = []
    prefix = f"{name}="
    for index, item in enumerate(args):
        if item == name and index + 1 < len(args):
            values.append(args[index + 1])
        elif item.startswith(prefix):
            values.append(item.split("=", 1)[1])
    return [value for value in values if value]


def _csv_option(args: list[str], name: str) -> list[str]:
    values: list[str] = []
    for raw in _multi_option(args, name):
        values.extend(part.strip() for part in re.split(r"[,，、]", raw) if part.strip())
    return values


def _flag(args: list[str], name: str) -> bool:
    return name in args or any(item == f"{name}=true" for item in args)


def _int_option(args: list[str], name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _option(args, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _optional_int_option(args: list[str], name: str, *, minimum: int, maximum: int) -> int | None:
    raw = _option(args, name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise CliError("invalid_option", f"{name} must be an integer.") from exc
    return max(minimum, min(maximum, value))


def _positional(args: list[str], offset: int) -> str:
    words: list[str] = []
    skip_option_value = False
    for item in args:
        if skip_option_value:
            skip_option_value = False
            continue
        if item.startswith("--"):
            if "=" not in item and item not in BOOLEAN_OPTIONS:
                skip_option_value = True
            continue
        if item.startswith("-"):
            continue
        words.append(item)
    return words[offset] if len(words) > offset else ""


def _require_value(argv: list[str], index: int, name: str) -> str:
    if index >= len(argv):
        raise CliError("missing_option_value", f"{name} 缺少参数。")
    return argv[index]


def _url_component(value: str) -> str:
    return urllib.parse.quote(value.strip(), safe="")


def _redact_url(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return _redact(text)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        netloc = ("***:***@" if ":" in userinfo else "***@") + host
    query_pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    redacted_query = urllib.parse.urlencode([
        (key, "***" if any(mark in key.lower() for mark in ("token", "secret", "key", "password", "credential")) else _redact(value))
        for key, value in query_pairs
    ])
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, redacted_query, parts.fragment))


def _extract_bridge_error(text: str) -> str:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("error", "message", "detail"):
                value = data.get(key)
                if isinstance(value, str):
                    return _redact(value)
    except json.JSONDecodeError:
        pass
    return ""


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Json = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(mark in lowered for mark in ("token", "secret", "key", "password", "credential")):
                redacted[key] = "***"
            else:
                redacted[key] = _redact_json(item)
        return redacted
    if isinstance(value, list):
        return [_redact_json(item) for item in value[:200]]
    if isinstance(value, str):
        return _redact(value)
    return value


_AUDIT_CREDENTIAL_POLICIES = {
    "account login-code": {
        "keys": {"code", "logincode", "verificationcode", "emailcode"},
        "flags": {"--code", "--login-code", "--verification-code", "--email-code"},
        "position": 1,
    },
    "license activate": {
        "keys": {"code", "licensecode"},
        "flags": {"--code", "--license-code"},
        "position": 0,
    },
    "account bind-ticket": {
        "keys": {"code", "ticket", "bindcode", "bindticket"},
        "flags": {"--code", "--ticket", "--bind-code", "--bind-ticket"},
        "position": 0,
    },
}

_AUDIT_CREDENTIAL_TOOL_ALIASES = {
    "loom_account_login_code": "account login-code",
    "loom_license_activate": "license activate",
    "loom_account_bind_ticket": "account bind-ticket",
}


def _redact_audit_record(record: Json) -> Json:
    redacted = _redact_json(record)
    if not isinstance(redacted, dict):
        return redacted
    command = _audit_credential_command(redacted.get("tool"))
    if command:
        redacted["paramSummary"] = _redact_audit_param_summary(
            redacted.get("paramSummary"),
            command,
        )
    return redacted


def _audit_credential_command(tool: Any) -> str:
    text = str(tool or "").strip().lower()
    if ":" in text:
        text = text.split(":", 1)[1]
    text = _AUDIT_CREDENTIAL_TOOL_ALIASES.get(text, text)
    return text if text in _AUDIT_CREDENTIAL_POLICIES else ""


def _redact_audit_param_summary(summary: Any, command: str) -> Any:
    sensitive_keys = _AUDIT_CREDENTIAL_POLICIES[command]["keys"]
    if isinstance(summary, dict):
        return {
            key: "***" if re.sub(r"[^a-z0-9]", "", str(key).lower()) in sensitive_keys else value
            for key, value in summary.items()
        }
    if isinstance(summary, list):
        return _redact_audit_argv(summary, command)
    return summary


def _redact_audit_argv(argv: list[Any], command: str) -> list[Any]:
    redacted = list(argv)
    policy = _AUDIT_CREDENTIAL_POLICIES[command]
    flags = policy["flags"]
    redact_next = False
    for index, item in enumerate(redacted):
        text = str(item)
        lowered = text.lower()
        if redact_next:
            redacted[index] = "***"
            redact_next = False
            continue
        if lowered in flags:
            redact_next = True
            continue
        matching_flag = next((flag for flag in flags if lowered.startswith(f"{flag}=")), "")
        if matching_flag:
            redacted[index] = f"{text.split('=', 1)[0]}=***"

    positional_index = policy["position"]
    command_parts = command.split()
    lowered_argv = [str(item).lower() for item in redacted]
    command_end = next(
        (
            index + len(command_parts)
            for index in range(len(lowered_argv) - len(command_parts) + 1)
            if lowered_argv[index : index + len(command_parts)] == command_parts
        ),
        len(redacted),
    )
    skip_option_value = False
    position = 0
    for index in range(command_end, len(redacted)):
        text = str(redacted[index])
        if skip_option_value:
            skip_option_value = False
            continue
        if text.startswith("--"):
            if "=" not in text and text.lower() not in BOOLEAN_OPTIONS:
                skip_option_value = True
            continue
        if text.startswith("-"):
            continue
        if position == positional_index:
            redacted[index] = "***"
            break
        position += 1
    return redacted


def audit_log_path(filename: str) -> str:
    base_dir = os.environ.get("LOOM_AUDIT_DIR", "").strip()
    if not base_dir:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            base_dir = os.path.join(local_app_data, "LOOM", "logs")
        elif sys.platform == "darwin":
            base_dir = os.path.expanduser("~/Library/Application Support/LOOM/logs")
        else:
            base_dir = os.path.expanduser("~/.local/share/loom/logs")
    return os.path.join(base_dir, filename)


def append_audit_record(filename: str, record: Json) -> str:
    path = audit_log_path(filename)
    line = json.dumps(_redact_audit_record(record), ensure_ascii=False, separators=(",", ":"))
    return append_jsonl(path, line)


def write_json_artifact(filename: str, data: Json) -> str:
    path = audit_log_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(_redact_json(data), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def _write_cli_audit(raw_argv: list[str], command_name: str, ctx: CliContext | None, result: Json, duration_ms: float) -> None:
    try:
        append_audit_record(
            "loom-cli-audit.jsonl",
            {
                "timestamp": _now_iso(),
                "tool": f"cli:{command_name}",
                "permission": ctx.permission if ctx else os.environ.get("LOOM_CLI_PERMISSION", "read"),
                "paramSummary": _argv_summary(raw_argv),
                "ok": bool(result.get("ok")),
                "durationMs": round(duration_ms, 2),
                "error": (result.get("error") or {}).get("code") if isinstance(result.get("error"), dict) else "",
            },
        )
    except Exception:
        # Audit failures must not break stdout JSON contracts.
        return


def _write_task_evidence(
    raw_argv: list[str],
    command_name: str,
    ctx: CliContext | None,
    result: Json,
    duration_ms: float,
    *,
    source: str,
) -> None:
    try:
        effective_source = _safe_source(getattr(ctx, "source", source) if ctx else source)
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        ledger = {
            "schema": "loom.task_ledger.v1",
            "timestamp": _now_iso(),
            "taskId": task_id,
            "source": effective_source,
            "tool": f"{effective_source}:{command_name}",
            "permission": ctx.permission if ctx else os.environ.get("LOOM_CLI_PERMISSION", "read"),
            "paramSummary": _argv_summary(raw_argv),
            "durationMs": round(duration_ms, 2),
            "ok": bool(result.get("ok")),
            "result": _result_summary(result),
            "failureReason": _failure_reason(result),
            "actionTraceId": trace_id,
            "templateCandidate": _template_candidate(command_name, result),
        }
        trace = {
            "schema": "loom.action_trace.v1",
            "timestamp": ledger["timestamp"],
            "taskId": task_id,
            "traceId": trace_id,
            "source": effective_source,
            "tool": ledger["tool"],
            "steps": _action_trace_steps(command_name, result),
            "durationMs": ledger["durationMs"],
            "ok": ledger["ok"],
            "error": ledger["failureReason"],
        }
        append_audit_record("loom-task-ledger.jsonl", ledger)
        append_audit_record("loom-action-trace.jsonl", trace)
        _update_template_optimizer(command_name, result, duration_ms, effective_source, ledger["permission"])
    except Exception:
        # Task evidence is best-effort and must never break CLI/MCP JSON output.
        return


def _result_summary(result: Json) -> Json:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    summary: Json = {
        "command": result.get("command"),
        "ok": bool(result.get("ok")),
    }
    if data:
        for key in ("method", "endpoint", "dryRun", "jobId"):
            if key in data:
                summary[key] = data.get(key)
        body = data.get("body") if isinstance(data.get("body"), dict) else {}
        if body:
            summary["body"] = _body_summary(body)
        bridge_result = data.get("result") if isinstance(data.get("result"), dict) else {}
        if bridge_result:
            for key in ("jobId", "status", "success", "error"):
                if key in bridge_result:
                    summary[key] = bridge_result.get(key)
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    if error:
        summary["error"] = {"code": error.get("code"), "message": error.get("message")}
    return _redact_json(summary)


def _body_summary(body: Json) -> Json:
    allowed = {
        "mode",
        "profile",
        "template",
        "templateId",
        "executionLayer",
        "action",
        "directAction",
        "timeoutSec",
        "maxWaitSec",
        "maxRounds",
        "pollMs",
        "confirmed",
        "leadId",
        "source",
        "status",
        "deviceId",
        "campaignId",
        "deviceTaskId",
        "retryOf",
        "retryCount",
    }
    summary = {key: body.get(key) for key in allowed if key in body}
    if "prompt" in body:
        prompt = str(body.get("prompt") or "").replace("\r", " ").replace("\n", " ").strip()
        summary["promptPreview"] = prompt[:80]
        summary["promptHash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return _redact_json(summary)


def _failure_reason(result: Json) -> str:
    if result.get("ok"):
        return ""
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    return str(error.get("code") or error.get("message") or "unknown_error")[:160]


def _action_trace_steps(command_name: str, result: Json) -> list[Json]:
    steps: list[Json] = [
        {"name": "dispatch", "status": "done", "command": command_name},
    ]
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("endpoint"):
        steps.append(
            {
                "name": "bridge_request",
                "status": "planned" if data.get("dryRun") else "sent",
                "method": data.get("method"),
                "endpoint": data.get("endpoint"),
                "body": _body_summary(data.get("body") if isinstance(data.get("body"), dict) else {}),
            }
        )
    if result.get("ok"):
        steps.append({"name": "result", "status": "success"})
    else:
        steps.append({"name": "result", "status": "failed", "error": _failure_reason(result)})
    return _redact_json(steps)


def _template_candidate(command_name: str, result: Json) -> Json | None:
    if not command_name.startswith("phone ") and not command_name.startswith("phone."):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    endpoint = str(data.get("endpoint") or "")
    if not endpoint.startswith("/api/phone/"):
        return None
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    signature = _template_signature(command_name, endpoint, body)
    return {
        "kind": "phone",
        "signature": signature,
        "command": command_name,
        "endpoint": endpoint,
        "body": _body_summary(body),
    }


def _template_signature(command_name: str, endpoint: str, body: Json) -> str:
    parts = {
        "command": command_name,
        "endpoint": endpoint,
        "mode": body.get("mode"),
        "profile": body.get("profile"),
        "template": body.get("template") or body.get("templateId"),
        "executionLayer": body.get("executionLayer"),
        "action": body.get("action") or body.get("directAction"),
    }
    stable = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def _update_template_optimizer(command_name: str, result: Json, duration_ms: float, source: str, permission: str) -> None:
    candidate = _template_candidate(command_name, result)
    if not candidate:
        return
    path = audit_log_path("loom-template-optimizer.json")
    current = _read_json_if_exists(path)
    if not current:
        current = {"schema": "loom.template_optimizer.v1", "updatedAt": "", "candidates": []}
    candidates = current.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    now = _now_iso()
    signature = candidate["signature"]
    index = next((idx for idx, item in enumerate(candidates) if isinstance(item, dict) and item.get("signature") == signature), -1)
    if index >= 0:
        item = dict(candidates[index])
    else:
        item = {
            "signature": signature,
            "kind": candidate["kind"],
            "command": command_name,
            "endpoint": candidate["endpoint"],
            "source": source,
            "successCount": 0,
            "failureCount": 0,
            "avgDurationMs": 0,
            "firstSeenAt": now,
            "lastSeenAt": now,
            "body": candidate["body"],
        }
    if result.get("ok"):
        item["successCount"] = int(item.get("successCount") or 0) + 1
    else:
        item["failureCount"] = int(item.get("failureCount") or 0) + 1
    previous_avg = float(item.get("avgDurationMs") or 0)
    total_seen = int(item.get("successCount") or 0) + int(item.get("failureCount") or 0)
    item["avgDurationMs"] = round(((previous_avg * max(total_seen - 1, 0)) + duration_ms) / max(total_seen, 1), 2)
    item["lastSeenAt"] = now
    if int(item.get("successCount") or 0) >= 2:
        item["suggestedTemplate"] = _suggested_template(item, permission)
    if index >= 0:
        candidates[index] = item
    else:
        candidates.append(item)
    current["schema"] = "loom.template_optimizer.v1"
    current["updatedAt"] = now
    current["candidates"] = sorted(candidates, key=lambda row: str(row.get("lastSeenAt") or ""), reverse=True)[:200]
    write_json_artifact("loom-template-optimizer.json", current)


def _suggested_template(candidate: Json, permission: str) -> Json:
    body = candidate.get("body") if isinstance(candidate.get("body"), dict) else {}
    mutating = permission in {"control", "automation", "admin"} or bool(body.get("action") or body.get("directAction"))
    return {
        "id": f"tpl_phone_{candidate.get('signature')}",
        "title": "建议固化手机模板",
        "command": candidate.get("command"),
        "endpoint": candidate.get("endpoint"),
        "parameters": body,
        "requiresConfirmation": True if mutating else True,
        "reason": "该手机流程重复成功，可在人工确认后固化为模板。",
    }


def _safe_source(source: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(source or "cli").strip().lower()).strip(".-_:")
    return text or "cli"


def _argv_summary(argv: list[str]) -> list[str]:
    summary: list[str] = []
    redact_next = False
    for item in argv:
        lowered = item.lower()
        if redact_next:
            summary.append("***")
            redact_next = False
            continue
        if lowered in {"--bridge-token", "--token", "--api-key", "--password", "--secret"}:
            summary.append(item)
            redact_next = True
            continue
        if any(mark in lowered for mark in ("token=", "api-key=", "password=", "secret=", "credential=")):
            summary.append(f"{item.split('=', 1)[0]}=***")
            continue
        summary.append(item[:120])
    return summary[:80]


def _redact(text: str) -> str:
    text = str(text)
    text = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-***", text)
    text = re.sub(r"ak-[A-Za-z0-9_\-]{4,}", "ak-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", text)
    text = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    return text


def _public_error(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    return _redact(text).splitlines()[0][:300]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


if __name__ == "__main__":
    raise SystemExit(main())
