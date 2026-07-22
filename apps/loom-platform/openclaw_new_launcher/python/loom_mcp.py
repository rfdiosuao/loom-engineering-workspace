"""LOOM stdio MCP server.

MCP is intentionally thin: every tool calls the LOOM CLI dispatcher and does
not copy installer, model, phone, or scheduler business logic.
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
import os
import time
from pathlib import Path
from typing import Any, Dict

from core.paths import AppPaths
from loom_cli import PERMISSION_LEVELS, append_audit_record, dispatch


Json = Dict[str, Any]
DEFAULT_PERMISSION = os.environ.get("LOOM_MCP_PERMISSION", "read").strip().lower() or "read"


def _launcher_package_version() -> str:
    for root in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        package_json = root / "package.json"
        if package_json.is_file():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return "unknown"
            version = str(data.get("version") or "").strip()
            return version or "unknown"
    return "unknown"


SERVER_VERSION = _launcher_package_version()


def _legacy_tool_definitions() -> list[Json]:
    return [
        _tool("loom_status", "读取 LOOM 本地状态。", "read", {}),
        _tool("loom_models", "读取当前模型配置。", "read", {}),
        _tool("loom_agent_list", "读取 Agent 安装状态。", "read", {}),
        _tool("loom_agent_start", "启动已安装 Agent。", "control", {"component": _string_schema("Agent 组件 ID")}),
        _tool("loom_agent_install", "安装 Agent。", "admin", {"component": _string_schema("Agent 组件 ID")}),
        _tool("loom_phone_screenshot", "手机截图。", "read", {}),
        _tool("loom_phone_read", "快速读取手机屏幕。", "read", {"prompt": _string_schema("读取提示")}),
        _tool(
            "loom_phone_quick_task",
            "执行手机快速任务。",
            "control",
            {
                "prompt": _string_schema("任务描述"),
                "mode": {"type": "string", "enum": ["observe", "safe", "standard", "full", "deep"], "required": False},
            },
        ),
        _tool(
            "loom_phone_template_task",
            "执行内置手机模板任务。",
            "read",
            {"template": {"type": "string", "enum": ["read-screen", "screen-summary", "back", "home"], "required": False}},
        ),
        _tool("loom_schedule_list", "读取定时任务。", "read", {}),
        _tool(
            "loom_schedule_add",
            "新增定时任务。",
            "automation",
            {
                "name": _string_schema("任务名称"),
                "command": _string_schema("允许的 LOOM CLI 命令"),
                "at": _string_schema("ISO 时间", required=False),
                "every": _string_schema("重复间隔", required=False),
            },
        ),
        _tool("loom_schedule_run", "立即运行定时任务。", "automation", {"id": _string_schema("任务 ID")}),
        _tool("loom_schedule_cancel", "取消定时任务。", "automation", {"id": _string_schema("任务 ID")}),
        _tool(
            "loom_logs_tail",
            "读取最近日志。",
            "read",
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "required": False},
                "kind": {"type": "string", "enum": ["audit", "ledger"], "required": False},
            },
        ),
        _tool("loom_matrix_status", "读取手机矩阵设备墙和任务状态。", "read", {}),
        _tool(
            "loom_matrix_dispatch",
            "派发 Matrix 手机任务。",
            "control",
            {
                "prompt": _string_schema("任务描述"),
                "deviceId": _string_schema("目标设备 ID", required=False),
                "group": _string_schema("目标设备分组", required=False),
                "mode": {"type": "string", "enum": ["observe", "safe", "full", "deep"], "required": False},
                "confirmed": {"type": "boolean", "description": "批量触达类任务的人工确认。", "required": False},
            },
        ),
        _tool("loom_matrix_watch", "读取 Matrix 任务事件流。", "read", {"campaignId": _string_schema("Campaign ID", required=False)}),
        _tool("loom_matrix_cancel", "取消 Matrix 任务。", "control", {"campaignId": _string_schema("Campaign ID")}),
        _tool("loom_matrix_retry", "重试 Matrix 失败任务。", "control", {"campaignId": _string_schema("Campaign ID")}),
        _tool(
            "loom_lead_list",
            "读取本地合规线索记录。",
            "read",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "required": False}},
        ),
        _tool(
            "loom_lead_record",
            "记录本地合规线索摘要。",
            "control",
            {
                "summary": _string_schema("线索摘要"),
                "deviceId": _string_schema("设备 ID", required=False),
                "campaignId": _string_schema("Campaign ID", required=False),
                "status": _string_schema("线索状态", required=False),
            },
        ),
        _tool(
            "loom_template_run",
            "运行内置手机模板。",
            "read",
            {
                "template": {"type": "string", "enum": ["read-screen", "screen-summary", "back", "home", "open-settings"], "required": False},
                "deviceId": _string_schema("目标设备 ID", required=False),
                "confirmed": {"type": "boolean", "description": "控制类模板的人工确认。", "required": False},
            },
        ),
        _tool("loom_experience_report", "读取 Matrix 经验沉淀报告。", "read", {}),
    ]


def tool_definitions() -> list[Json]:
    return [
        _tool("loom_status", "Read LOOM local status.", "read", {}),
        _tool("loom_doctor", "Inspect packaged LOOM runtimes and helper scripts.", "read", {}),
        _tool("loom_cli_commands", "Read the machine-readable LOOM CLI capability catalog.", "read", {}),
        _tool("loom_models", "Read current model selections.", "read", {}),
        _tool("loom_agent_list", "Read Agent installation status.", "read", {}),
        _tool("loom_agent_start", "Start an installed Agent.", "control", {"component": _string_schema("Agent component ID")}),
        _tool("loom_agent_install", "Install an Agent.", "admin", {"component": _string_schema("Agent component ID")}),
        _tool("loom_agent_detect", "Detect one Agent installation.", "control", {"component": _string_schema("Agent component ID")}),
        _tool("loom_agent_uninstall", "Uninstall one Agent.", "admin", {"component": _string_schema("Agent component ID")}),
        _tool("loom_agent_rollback", "Rollback one Agent installation.", "admin", {"component": _string_schema("Agent component ID")}),
        _tool("loom_agent_model_status", "Read Agent model configuration status.", "read", {"component": _string_schema("Agent component ID")}),
        _tool(
            "loom_agent_model_apply",
            "Apply synced or selected model config to one Agent.",
            "control",
            {"component": _string_schema("Agent component ID"), "model": _string_schema("Model name", required=False)},
        ),
        _tool("loom_agent_model_rollback", "Rollback one Agent model config.", "control", {"component": _string_schema("Agent component ID")}),
        _tool("loom_account_current", "Read current relay account snapshot.", "read", {}),
        _tool("loom_account_send_code", "Send relay account email verification code.", "control", {"email": _string_schema("Email address"), "baseUrl": _string_schema("Relay base URL", required=False)}),
        _tool("loom_account_login_code", "Login relay account with email code.", "control", {"email": _string_schema("Email address"), "code": _string_schema("Verification code"), "baseUrl": _string_schema("Relay base URL", required=False)}),
        _tool("loom_account_login_password", "Login relay account with username/email and password.", "control", {"username": _string_schema("Username or email"), "password": _string_schema("Password"), "baseUrl": _string_schema("Relay base URL", required=False)}),
        _tool("loom_account_sync", "Sync relay account balance and models.", "control", {}),
        _tool("loom_account_subscription", "Read relay account subscription snapshot.", "read", {}),
        _tool(
            "loom_account_select_models",
            "Select LOOM default text, phone, image, and video models.",
            "control",
            {
                "textModel": _string_schema("Main text model", required=False),
                "phoneModel": _string_schema("Phone Agent model", required=False),
                "imageModel": _string_schema("Image model", required=False),
                "videoModel": _string_schema("Video model draft", required=False),
            },
        ),
        _tool("loom_account_logout", "Logout relay account.", "control", {}),
        _tool("loom_wire_current", "Read current model wire config.", "read", {}),
        _tool("loom_wire_sync", "Sync relay model wire config.", "control", {}),
        _tool(
            "loom_wire_custom",
            "Write custom OpenAI-compatible model wire config.",
            "control",
            {
                "baseUrl": _string_schema("OpenAI-compatible base URL"),
                "apiKey": _string_schema("API key"),
                "textModel": _string_schema("Main text model"),
                "provider": _string_schema("Provider label", required=False),
                "phoneModel": _string_schema("Phone Agent model", required=False),
                "imageModel": _string_schema("Image model", required=False),
                "videoModel": _string_schema("Video model draft", required=False),
            },
        ),
        _tool(
            "loom_wire_verify",
            "Verify current or provided OpenAI-compatible model wire config.",
            "read",
            {
                "baseUrl": _string_schema("OpenAI-compatible base URL", required=False),
                "apiKey": _string_schema("API key", required=False),
                "textModel": _string_schema("Main text model", required=False),
                "provider": _string_schema("Provider label", required=False),
            },
        ),
        _tool("loom_wire_rollback", "Rollback previous model wire config.", "control", {}),
        _tool("loom_media_config", "Read image/video generation config.", "read", {}),
        _tool("loom_media_save_image_config", "Save image generation provider config.", "control", {"baseUrl": _string_schema("Image API base URL"), "apiKey": _string_schema("Image API key"), "model": _string_schema("Image model"), "provider": _string_schema("Provider label", required=False)}),
        _tool("loom_media_save_video_config", "Save video generation provider config.", "control", {"baseUrl": _string_schema("Video API base URL"), "apiKey": _string_schema("Video API key"), "model": _string_schema("Video model"), "provider": _string_schema("Provider label", required=False)}),
        _tool("loom_media_test_image", "Test image generation provider config.", "control", {}),
        _tool("loom_media_test_video", "Test video generation provider config.", "control", {}),
        _tool("loom_media_generate_image", "Submit an image generation job.", "control", {"prompt": _string_schema("Image prompt"), "editImage": _string_schema("Optional image path for edit mode", required=False), "sync": {"type": "boolean", "required": False}}),
        _tool("loom_media_generate_video", "Submit a video generation job.", "control", {"prompt": _string_schema("Video prompt"), "image": _string_schema("Optional reference image path", required=False), "sync": {"type": "boolean", "required": False}}),
        _tool(
            "loom_phone_status",
            "Read configured phone status; optionally filter by one device ID.",
            "read",
            {"deviceId": _string_schema("Bound device ID", required=False)},
            target_scope="none",
        ),
        _tool(
            "loom_phone_screenshot",
            "Take a phone screenshot.",
            "read",
            {"deviceId": _string_schema("Bound device ID", required=False)},
            target_scope="single-device-read",
        ),
        _tool(
            "loom_phone_read",
            "Fast phone screen read.",
            "read",
            {
                "prompt": _string_schema("Read prompt"),
                "deviceId": _string_schema("Bound device ID", required=False),
            },
            target_scope="single-device-read",
        ),
        _tool(
            "loom_phone_quick_task",
            "Run a fast phone task.",
            "control",
            {
                "prompt": _string_schema("Task prompt"),
                "mode": {"type": "string", "enum": ["observe", "safe", "standard", "full", "deep"], "required": False},
                "deviceId": _string_schema("Bound device ID", required=False),
            },
            target_scope="single-device-write",
        ),
        _tool(
            "loom_phone_template_task",
            "Run a built-in phone template task.",
            "control",
            {
                "template": {"type": "string", "enum": ["read-screen", "screen-summary", "back", "home"], "required": False},
                "deviceId": _string_schema("Bound device ID", required=False),
            },
            target_scope="single-device-write",
        ),
        _tool("loom_phone_adb_doctor", "Repair common ADB or phone connection issues.", "admin", {
            "serial": _string_schema("Optional adb device serial", required=False),
            "wake": {"type": "boolean", "required": False},
            "launch": {"type": "boolean", "required": False},
            "restartServer": {"type": "boolean", "required": False},
        }),
        _tool("loom_phone_events_start", "Start phone event synchronization.", "read", {
            "deviceId": _string_schema("Bound device ID", required=False),
            "maxSec": {"type": "integer", "minimum": 1, "required": False},
            "maxEvents": {"type": "integer", "minimum": 1, "required": False},
        }),
        _tool("loom_phone_events_status", "Read phone event synchronization status.", "read", {
            "deviceId": _string_schema("Bound device ID", required=False),
        }),
        _tool("loom_phone_events_stop", "Stop phone event synchronization.", "read", {
            "deviceId": _string_schema("Bound device ID", required=False),
        }),
        _tool("loom_acquisition_agent_run", "Prepare or start a compliant acquisition Agent task.", "control", {
            "platform": _string_schema("Target platform", required=False),
            "deviceId": _string_schema("Bound device ID", required=False),
            "taskId": _string_schema("Task ID", required=False),
            "topic": _string_schema("Acquisition topic", required=False),
            "action": _string_schema("Acquisition action", required=False),
            "target": _string_schema("Target customer description", required=False),
            "knowledge": _string_schema("Approved SOP or knowledge", required=False),
            "realRun": {"type": "boolean", "required": False},
            "confirmed": {"type": "boolean", "required": False},
        }, target_scope="single-device-write"),
        _tool("loom_acquisition_agent_result", "Record a compliant acquisition Agent result.", "control", {
            "agentResult": {"type": "object"},
            "platform": _string_schema("Target platform", required=False),
            "deviceId": _string_schema("Bound device ID", required=False),
            "topic": _string_schema("Acquisition topic", required=False),
            "action": _string_schema("Acquisition action", required=False),
        }),
        _tool("loom_feishu_doctor", "Inspect the Feishu integration environment.", "read", {}),
        _tool("loom_feishu_status", "Read Feishu integration status.", "read", {}),
        _tool("loom_feishu_install", "Install the Feishu integration.", "admin", {
            "confirmed": {"type": "boolean", "required": False},
        }),
        _tool("loom_feishu_login", "Login to the Feishu integration.", "control", {}),
        _tool("loom_feishu_bind_table", "Bind a Feishu lead table.", "control", {
            "url": _string_schema("Feishu table URL"),
            "name": _string_schema("Local table label", required=False),
        }),
        _tool("loom_feishu_create_table", "Create a Feishu lead table.", "control", {
            "confirmed": {"type": "boolean", "required": False},
        }),
        _tool("loom_feishu_test_write", "Test writing a lead row to Feishu.", "control", {}),
        _tool("loom_feishu_retry_sync", "Retry pending Feishu synchronization.", "control", {}),
        _tool("loom_feishu_reconcile", "Reconcile local and Feishu synchronization state.", "control", {}),
        _tool("loom_schedule_list", "Read scheduled tasks.", "read", {}),
        _tool(
            "loom_schedule_add",
            "Add scheduled task.",
            "automation",
            {
                "name": _string_schema("Task name"),
                "command": {
                    "type": "string",
                    "description": (
                        "Allowed LOOM CLI command. Supported roots: status, models, logs; "
                        "supported commands: agents list, phone screenshot, phone read, "
                        "phone read-screen, phone quick-task, phone template-task."
                    ),
                    "examples": ["status", "phone screenshot"],
                },
                "at": _string_schema("ISO time", required=False),
                "every": _string_schema("Repeat interval", required=False),
            },
            any_of=[{"required": ["at"]}, {"required": ["every"]}],
        ),
        _tool("loom_schedule_run", "Run scheduled task now.", "automation", {"id": _string_schema("Task ID")}),
        _tool("loom_schedule_cancel", "Cancel scheduled task.", "automation", {"id": _string_schema("Task ID")}),
        _tool("loom_logs_tail", "Read recent logs.", "read", {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "required": False}, "kind": {"type": "string", "enum": ["audit", "ledger"], "required": False}}),
        _tool("loom_matrix_status", "Read phone matrix status.", "read", {}),
        _tool(
            "loom_matrix_dispatch",
            "Dispatch a Matrix phone task.",
            "control",
            {
                "prompt": _string_schema("Task prompt"),
                "deviceId": _string_schema("Target device ID", required=False),
                "group": _string_schema("Target group", required=False),
                "targets": {
                    "type": "object",
                    "properties": {
                        "deviceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "groups": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "allOnline": {"type": "boolean"},
                    },
                    "anyOf": [
                        {"required": ["deviceIds"]},
                        {"required": ["groups"]},
                        {"required": ["allOnline"]},
                    ],
                    "required": False,
                },
                "mode": {"type": "string", "enum": ["observe", "safe", "full", "deep"], "required": False},
                "confirmed": {"type": "boolean", "required": False},
            },
            target_scope="matrix-write",
            any_of=[
                {"required": ["deviceId"]},
                {"required": ["group"]},
                {"required": ["targets"]},
            ],
        ),
        _tool("loom_matrix_watch", "Read Matrix event stream.", "read", {"campaignId": _string_schema("Campaign ID", required=False)}),
        _tool(
            "loom_matrix_cancel",
            "Cancel Matrix task.",
            "control",
            {"campaignId": _string_schema("Campaign ID")},
            target_scope="campaign-write",
        ),
        _tool(
            "loom_matrix_retry",
            "Retry failed Matrix task.",
            "control",
            {"campaignId": _string_schema("Campaign ID")},
            target_scope="campaign-write",
        ),
        _tool("loom_lead_list", "Read local compliant lead records.", "read", {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "required": False}}),
        _tool("loom_lead_record", "Record local compliant lead summary.", "control", {"summary": _string_schema("Lead summary"), "deviceId": _string_schema("Device ID", required=False), "campaignId": _string_schema("Campaign ID", required=False), "status": _string_schema("Lead status", required=False)}),
        _tool(
            "loom_template_run",
            "Run built-in phone template.",
            "control",
            {"template": {"type": "string", "enum": ["read-screen", "screen-summary", "back", "home", "open-settings"], "required": False}, "deviceId": _string_schema("Target device ID"), "confirmed": {"type": "boolean", "required": False}},
            target_scope="single-device-write",
        ),
        _tool("loom_experience_report", "Read Matrix experience report.", "read", {}),
        _tool("loom_job_list", "Read recent background jobs.", "read", {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "required": False}}),
        _tool("loom_job_get", "Read one background job.", "read", {"id": _string_schema("Job ID")}),
        _tool("loom_settings_theme", "Read or set UI theme.", "control", {"theme": _string_schema("Theme ID to set", required=False)}),
        _tool("loom_settings_theme_list", "Read available UI themes.", "read", {}),
        _tool("loom_settings_update_check", "Check launcher update status.", "read", {}),
        _tool("loom_settings_update_install", "Install launcher update.", "admin", {}),
        _tool("loom_diagnostics_run", "Run launcher diagnostics.", "read", {"scope": _string_schema("Diagnostic scope", required=False)}),
        _tool(
            "loom_diagnostics_repair",
            "Run a diagnostic repair action.",
            "admin",
            {"action": {"type": "string", "enum": ["prerequisites"], "description": "Repair action"}},
        ),
        _tool("loom_diagnostics_export", "Export diagnostic bundle.", "read", {}),
        _tool("loom_license_current", "Read current license state.", "read", {}),
        _tool("loom_license_activate", "Activate a license code.", "control", {"code": _string_schema("License code")}),
        _tool("loom_license_authorized", "Read whether current license is authorized.", "read", {}),
    ]


def call_tool(
    name: str,
    arguments: Json | None = None,
    *,
    permission: str | None = None,
    base_path: str | None = None,
    trusted_internal: bool = False,
) -> Json:
    args = arguments if isinstance(arguments, dict) else {}
    granted = _effective_permission(
        permission,
        dry_run=bool(args.get("dryRun")),
        trusted_internal=trusted_internal,
    )
    paths = AppPaths(base_path=os.path.normpath(base_path)) if base_path else AppPaths.discover()
    start = time.perf_counter()
    error = ""
    ok = False
    try:
        argv = _tool_to_cli_args(name, args)
        if args.get("dryRun"):
            argv.append("--dry-run")
        argv.extend(["--json", "--permission", granted])
        code, payload = dispatch(argv, base_path=paths.base_path, source="mcp")
        ok = code == 0 and bool(payload.get("ok"))
        error = "" if ok else str((payload.get("error") or {}).get("code") or "tool_error")
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
            "isError": not ok,
        }
    except Exception as exc:  # pragma: no cover - defensive stdio boundary
        error = str(exc)[:300]
        payload = {"ok": False, "command": name, "error": {"code": "mcp_internal_error", "message": error}}
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
            "isError": True,
        }
    finally:
        _write_audit(paths, name, args, granted, ok, (time.perf_counter() - start) * 1000, error)


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = _handle_rpc_line(line)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def _handle_rpc_line(line: str) -> Json | None:
    try:
        line = _normalize_rpc_line(line)
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return _rpc_result(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "loom-mcp", "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            )
        if method == "tools/list":
            return _rpc_result(request_id, {"tools": tool_definitions()})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            return _rpc_result(request_id, call_tool(name, arguments, permission=DEFAULT_PERMISSION))
        return _rpc_error(request_id, -32601, "Method not found")
    except json.JSONDecodeError:
        return _rpc_error(None, -32700, "Parse error")
    except Exception as exc:  # pragma: no cover - defensive stdio boundary
        return _rpc_error(None, -32603, str(exc)[:300])


def _normalize_rpc_line(line: str) -> str:
    normalized = line.lstrip("\ufeff")
    # Windows stdio can decode a UTF-8 BOM plus the opening "{" through the
    # active ANSI code page, yielding mojibake before the first JSON-RPC object.
    if normalized.startswith("\u9518\u7e36"):
        normalized = "{" + normalized[2:]
    return normalized


def _tool_to_cli_args(name: str, args: Json) -> list[str]:
    if name == "loom_status":
        return ["status"]
    if name == "loom_doctor":
        return ["doctor"]
    if name == "loom_cli_commands":
        return ["commands"]
    if name == "loom_models":
        return ["models"]
    if name == "loom_agent_list":
        return ["agents", "list"]
    if name == "loom_agent_start":
        return ["agents", "start", "--component", _required(args, "component")]
    if name == "loom_agent_install":
        return ["agents", "install", "--component", _required(args, "component")]
    if name == "loom_agent_detect":
        return ["agents", "detect", "--component", _required(args, "component")]
    if name == "loom_agent_uninstall":
        return ["agents", "uninstall", "--component", _required(args, "component")]
    if name == "loom_agent_rollback":
        return ["agents", "rollback", "--component", _required(args, "component")]
    if name == "loom_agent_model_status":
        return ["agents", "model-status", "--component", _required(args, "component")]
    if name == "loom_agent_model_apply":
        argv = ["agents", "model-apply", "--component", _required(args, "component")]
        _append_optional(argv, args, "model", "--model")
        return argv
    if name == "loom_agent_model_rollback":
        return ["agents", "model-rollback", "--component", _required(args, "component")]
    if name == "loom_account_current":
        return ["account", "current"]
    if name == "loom_account_send_code":
        argv = ["account", "send-code", "--email", _required(args, "email")]
        _append_optional(argv, args, "baseUrl", "--base-url")
        return argv
    if name == "loom_account_login_code":
        argv = ["account", "login-code", "--email", _required(args, "email"), "--code", _required(args, "code")]
        _append_optional(argv, args, "baseUrl", "--base-url")
        return argv
    if name == "loom_account_login_password":
        argv = ["account", "login", "--username", _required(args, "username"), "--password", _required(args, "password")]
        _append_optional(argv, args, "baseUrl", "--base-url")
        return argv
    if name == "loom_account_sync":
        return ["account", "sync"]
    if name == "loom_account_subscription":
        return ["account", "subscription"]
    if name == "loom_account_select_models":
        argv = ["account", "select-models"]
        _append_optional(argv, args, "textModel", "--text-model")
        _append_optional(argv, args, "phoneModel", "--phone-model")
        _append_optional(argv, args, "imageModel", "--image-model")
        _append_optional(argv, args, "videoModel", "--video-model")
        return argv
    if name == "loom_account_logout":
        return ["account", "logout"]
    if name == "loom_wire_current":
        return ["wire", "current"]
    if name == "loom_wire_sync":
        return ["wire", "sync"]
    if name == "loom_wire_custom":
        argv = [
            "wire",
            "custom",
            "--base-url",
            _required(args, "baseUrl"),
            "--api-key",
            _required(args, "apiKey"),
            "--text-model",
            _required(args, "textModel"),
        ]
        _append_optional(argv, args, "provider", "--provider")
        _append_optional(argv, args, "phoneModel", "--phone-model")
        _append_optional(argv, args, "imageModel", "--image-model")
        _append_optional(argv, args, "videoModel", "--video-model")
        return argv
    if name == "loom_wire_verify":
        argv = ["wire", "verify"]
        _append_optional(argv, args, "baseUrl", "--base-url")
        _append_optional(argv, args, "apiKey", "--api-key")
        _append_optional(argv, args, "textModel", "--text-model")
        _append_optional(argv, args, "provider", "--provider")
        return argv
    if name == "loom_wire_rollback":
        return ["wire", "rollback"]
    if name == "loom_media_config":
        return ["media", "config"]
    if name == "loom_media_save_image_config":
        argv = [
            "media",
            "save-image",
            "--base-url",
            _required(args, "baseUrl"),
            "--api-key",
            _required(args, "apiKey"),
            "--model",
            _required(args, "model"),
        ]
        _append_optional(argv, args, "provider", "--provider")
        return argv
    if name == "loom_media_save_video_config":
        argv = [
            "media",
            "save-video",
            "--base-url",
            _required(args, "baseUrl"),
            "--api-key",
            _required(args, "apiKey"),
            "--model",
            _required(args, "model"),
        ]
        _append_optional(argv, args, "provider", "--provider")
        return argv
    if name == "loom_media_test_image":
        return ["media", "test-image"]
    if name == "loom_media_test_video":
        return ["media", "test-video"]
    if name == "loom_media_generate_image":
        argv = ["media", "image", "--prompt", _required(args, "prompt")]
        _append_optional(argv, args, "editImage", "--edit-image")
        if args.get("sync"):
            argv.append("--sync")
        return argv
    if name == "loom_media_generate_video":
        argv = ["media", "video", "--prompt", _required(args, "prompt")]
        _append_optional(argv, args, "image", "--image")
        if args.get("sync"):
            argv.append("--sync")
        return argv
    if name == "loom_phone_status":
        argv = ["phone", "status"]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_screenshot":
        argv = ["phone", "screenshot"]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_read":
        argv = ["phone", "read", "--prompt", str(args.get("prompt") or "读取当前屏幕")]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_quick_task":
        argv = ["phone", "quick-task", "--prompt", _required(args, "prompt")]
        if args.get("mode"):
            argv.extend(["--mode", str(args["mode"])])
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_template_task":
        argv = ["phone", "template-task", "--template", str(args.get("template") or "read-screen")]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_adb_doctor":
        argv = ["phone", "adb-doctor"]
        _append_optional(argv, args, "serial", "--serial")
        if args.get("wake") is False:
            argv.append("--no-wake")
        if args.get("launch") is False:
            argv.append("--no-launch")
        if args.get("restartServer") is False:
            argv.append("--no-restart-server")
        return argv
    if name == "loom_phone_events_start":
        argv = ["phone", "events-start"]
        _append_optional(argv, args, "deviceId", "--device-id")
        _append_optional(argv, args, "maxSec", "--max-sec")
        _append_optional(argv, args, "maxEvents", "--max-events")
        return argv
    if name == "loom_phone_events_status":
        argv = ["phone", "events-status"]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_phone_events_stop":
        argv = ["phone", "events-stop"]
        _append_optional(argv, args, "deviceId", "--device-id")
        return argv
    if name == "loom_acquisition_agent_run":
        argv = ["acquisition", "agent-run"]
        for key, flag in (
            ("platform", "--platform"),
            ("deviceId", "--device-id"),
            ("taskId", "--task-id"),
            ("topic", "--topic"),
            ("action", "--action"),
            ("target", "--target"),
            ("knowledge", "--knowledge"),
        ):
            _append_optional(argv, args, key, flag)
        if args.get("realRun"):
            argv.append("--real-run")
        if args.get("confirmed"):
            argv.append("--confirmed")
        return argv
    if name == "loom_acquisition_agent_result":
        result = args.get("agentResult")
        if not isinstance(result, dict):
            raise ValueError("Missing required argument: agentResult")
        argv = [
            "acquisition",
            "agent-result",
            "--agent-result-json",
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        ]
        for key, flag in (
            ("platform", "--platform"),
            ("deviceId", "--device-id"),
            ("topic", "--topic"),
            ("action", "--action"),
        ):
            _append_optional(argv, args, key, flag)
        return argv
    if name == "loom_feishu_doctor":
        return ["integration", "feishu", "doctor"]
    if name == "loom_feishu_status":
        return ["integration", "feishu", "status"]
    if name == "loom_feishu_install":
        argv = ["integration", "feishu", "install"]
        if args.get("confirmed"):
            argv.append("--confirmed")
        return argv
    if name == "loom_feishu_login":
        return ["integration", "feishu", "login"]
    if name == "loom_feishu_bind_table":
        argv = ["integration", "feishu", "bind-table", "--url", _required(args, "url")]
        _append_optional(argv, args, "name", "--name")
        return argv
    if name == "loom_feishu_create_table":
        argv = ["integration", "feishu", "create-table"]
        if args.get("confirmed"):
            argv.append("--confirmed")
        return argv
    if name == "loom_feishu_test_write":
        return ["integration", "feishu", "test-write"]
    if name == "loom_feishu_retry_sync":
        return ["integration", "feishu", "retry-sync"]
    if name == "loom_feishu_reconcile":
        return ["integration", "feishu", "reconcile"]
    if name == "loom_schedule_list":
        return ["schedule", "list"]
    if name == "loom_schedule_add":
        argv = ["schedule", "add", "--name", _required(args, "name"), "--command", _required(args, "command")]
        if args.get("at"):
            argv.extend(["--at", str(args["at"])])
        if args.get("every"):
            argv.extend(["--every", str(args["every"])])
        return argv
    if name == "loom_schedule_run":
        return ["schedule", "run", "--id", _required(args, "id")]
    if name == "loom_schedule_cancel":
        return ["schedule", "cancel", "--id", _required(args, "id")]
    if name == "loom_logs_tail":
        kind = "ledger" if str(args.get("kind") or "").lower() == "ledger" else "tail"
        return ["logs", kind, "--limit", str(args.get("limit") or 100)]
    if name == "loom_matrix_status":
        return ["matrix", "status"]
    if name == "loom_matrix_dispatch":
        argv = ["matrix", "dispatch", "--prompt", _required(args, "prompt")]
        targets = args.get("targets") if isinstance(args.get("targets"), dict) else {}
        device_ids = targets.get("deviceIds") if isinstance(targets.get("deviceIds"), list) else []
        groups = targets.get("groups") if isinstance(targets.get("groups"), list) else []
        if targets.get("allOnline"):
            argv.extend(["--target", "all"])
        elif device_ids:
            argv.extend(["--device", ",".join(str(item) for item in device_ids)])
        elif groups:
            argv.extend(["--group", ",".join(str(item) for item in groups)])
        elif args.get("deviceId"):
            argv.extend(["--device", str(args["deviceId"])])
        elif args.get("group"):
            argv.extend(["--group", str(args["group"])])
        if args.get("mode"):
            argv.extend(["--mode", str(args["mode"])])
        if args.get("confirmed"):
            argv.append("--confirmed")
        return argv
    if name == "loom_matrix_watch":
        argv = ["matrix", "watch"]
        if args.get("campaignId"):
            argv.extend(["--campaign", str(args["campaignId"])])
        return argv
    if name == "loom_matrix_cancel":
        return ["matrix", "cancel", "--campaign", _required(args, "campaignId")]
    if name == "loom_matrix_retry":
        return ["matrix", "retry", "--campaign", _required(args, "campaignId")]
    if name == "loom_lead_list":
        return ["matrix", "leads", "--limit", str(args.get("limit") or 100)]
    if name == "loom_lead_record":
        argv = ["matrix", "record-lead", "--summary", _required(args, "summary")]
        if args.get("deviceId"):
            argv.extend(["--device", str(args["deviceId"])])
        if args.get("campaignId"):
            argv.extend(["--campaign", str(args["campaignId"])])
        if args.get("status"):
            argv.extend(["--status", str(args["status"])])
        return argv
    if name == "loom_template_run":
        argv = ["template", "run", "--template", str(args.get("template") or "read-screen")]
        if args.get("deviceId"):
            argv.extend(["--device", str(args["deviceId"])])
        if args.get("confirmed"):
            argv.append("--confirmed")
        return argv
    if name == "loom_experience_report":
        return ["experience", "report"]
    if name == "loom_job_list":
        return ["jobs", "list", "--limit", str(args.get("limit") or 30)]
    if name == "loom_job_get":
        return ["jobs", "get", "--id", _required(args, "id")]
    if name == "loom_settings_theme":
        argv = ["settings", "theme"]
        _append_optional(argv, args, "theme", "--set")
        return argv
    if name == "loom_settings_theme_list":
        return ["settings", "theme-list"]
    if name == "loom_settings_update_check":
        return ["settings", "update-check"]
    if name == "loom_settings_update_install":
        return ["settings", "update-do"]
    if name == "loom_diagnostics_run":
        argv = ["diagnostics", "run"]
        _append_optional(argv, args, "scope", "--scope")
        return argv
    if name == "loom_diagnostics_repair":
        return ["diagnostics", "repair", "--check", _required(args, "action")]
    if name == "loom_diagnostics_export":
        return ["diagnostics", "export"]
    if name == "loom_license_current":
        return ["license", "current"]
    if name == "loom_license_activate":
        return ["license", "activate", "--code", _required(args, "code")]
    if name == "loom_license_authorized":
        return ["license", "authorized"]
    raise ValueError(f"Unknown tool: {name}")


def _effective_permission(
    permission: str | None,
    *,
    dry_run: bool = False,
    trusted_internal: bool = False,
) -> str:
    requested = (permission or DEFAULT_PERMISSION or "read").lower()
    server_default = DEFAULT_PERMISSION if DEFAULT_PERMISSION in PERMISSION_LEVELS else "read"
    if requested not in PERMISSION_LEVELS:
        requested = "read"
    if dry_run or trusted_internal:
        return requested
    # Never let a per-call value elevate beyond the server-level permission.
    if PERMISSION_LEVELS[requested] > PERMISSION_LEVELS[server_default]:
        return server_default
    return requested


def _write_audit(paths: AppPaths, tool: str, args: Json, permission: str, ok: bool, duration_ms: float, error: str) -> None:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": tool,
        "permission": permission,
        "paramSummary": _param_summary(args),
        "ok": ok,
        "durationMs": round(duration_ms, 2),
        "error": error,
    }
    append_audit_record("mcp-audit.jsonl", record)


def _param_summary(args: Json) -> Json:
    summary: Json = {}
    for key, value in args.items():
        lowered = key.lower()
        if any(mark in lowered for mark in ("token", "secret", "key", "password", "credential")):
            summary[key] = "***"
        elif isinstance(value, str):
            summary[key] = value[:80]
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, list):
            summary[key] = f"list[{len(value)}]"
        elif isinstance(value, dict):
            summary[key] = f"object[{len(value)}]"
        else:
            summary[key] = type(value).__name__
    return summary


def _tool(
    name: str,
    description: str,
    permission: str,
    properties: Json,
    *,
    target_scope: str = "none",
    any_of: Any = None,
) -> Json:
    required = []
    schema_properties = {}
    for key, raw_schema in properties.items():
        schema = dict(raw_schema) if isinstance(raw_schema, dict) else raw_schema
        is_required = not (isinstance(schema, dict) and schema.pop("required", True) is False)
        if is_required:
            required.append(key)
        schema_properties[key] = schema
    schema_properties["dryRun"] = {"type": "boolean", "description": "只返回计划，不执行动作。"}
    risk = {
        "read": "read",
        "control": "control_safe",
        "automation": "critical",
        "admin": "critical",
    }.get(permission, "critical")
    input_schema = {
        "type": "object",
        "properties": schema_properties,
        "required": required,
        "additionalProperties": False,
    }
    if any_of:
        input_schema["anyOf"] = list(any_of)
    return {
        "name": name,
        "description": f"{description} 权限：{permission}。",
        "permission": permission,
        "risk": risk,
        "targetScope": target_scope,
        "inputSchema": input_schema,
    }


def _string_schema(description: str, *, required: bool = True) -> Json:
    return {"type": "string", "description": description, "required": required}


def _append_optional(argv: list[str], args: Json, key: str, flag: str) -> None:
    value = args.get(key)
    if value is None or value == "":
        return
    argv.extend([flag, str(value)])


def _required(args: Json, key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"Missing required argument: {key}")
    return value


def _rpc_result(request_id: Any, result: Json) -> Json:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> Json:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(serve())
