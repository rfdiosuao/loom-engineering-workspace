"""Launcher CLI capability routes.

The UI and future agents call these routes instead of constructing shell
commands. Each entry maps to a known local script and runs through the job
manager so page switches do not lose progress.
"""

from __future__ import annotations

import os
import subprocess
from fastapi import Request

from core.feature_access import feature_for_cli_command
from api.routes_phone import phone_process_env


def _script_path(ctx, script_name: str) -> str:
    for root in getattr(ctx.paths, "script_roots", ()) or ():
        candidate = os.path.join(root, script_name)
        if os.path.exists(candidate):
            return candidate
    scripts_dir = getattr(ctx.paths, "scripts_dir", None)
    if scripts_dir:
        return os.path.join(scripts_dir, script_name)
    return os.path.join(ctx.paths.base_path, "scripts", script_name)


CLI_COMMANDS: dict[str, dict[str, object]] = {
    "phone:agent": {
        "title": "手机 Agent",
        "script": "openclaw-phone-agent.mjs",
        "examples": ["history --limit 10 --json", "run --prompt \"读取当前屏幕\" --mode observe --json"],
    },
    "phone:fleet": {
        "title": "多设备",
        "script": "openclaw-phone-fleet.mjs",
        "examples": ["list --json", "status --json"],
    },
    "phone:vision": {
        "title": "手机视觉",
        "script": "openclaw-phone-vision.mjs",
        "examples": ["status --json", "frame --json"],
    },
    "phone:video": {
        "title": "手机录屏",
        "script": "openclaw-phone-video.mjs",
        "examples": ["status --json", "list --json"],
    },
    "phone:publish": {
        "title": "手机发布",
        "script": "openclaw-publish-phone.mjs",
        "examples": ["--platform xiaohongshu --title \"标题\" --body \"正文\" --json"],
        "visible": False,
    },
    "desktop:agent": {
        "title": "桌面 RPA",
        "script": "openclaw-desktop-agent.mjs",
        "examples": ["status --json", "health --json", "screenshot --json"],
    },
    "desktop:reply": {
        "title": "桌面回复",
        "script": "openclaw-desktop-agent.mjs",
        "prefix": ["reply"],
        "examples": ["observe --json", "once --text \"回复内容\" --confirmed --json"],
    },
}

READ_ONLY_WORDS = {"status", "health", "list", "history", "frame", "capture", "screenshot", "observe", "--help", "-h"}
FORBIDDEN_OPTIONS = {
    "--bridge",
    "--cwd",
    "--env",
    "--eval",
    "--node",
    "--python",
    "--require",
    "--script",
    "--workdir",
    "-e",
}
CONFIRMATION_OPTIONS = {
    "--download",
    "--force",
    "--force-action",
    "--out",
    "--output",
    "--packet-out",
    "--save",
}


def _catalog() -> list[dict[str, object]]:
    return [
        {
            "id": key,
            "title": str(value.get("title") or key),
            "examples": value.get("examples") if isinstance(value.get("examples"), list) else [],
        }
        for key, value in CLI_COMMANDS.items()
        if value.get("visible") is not False
    ]


def _normalize_args(raw_args: object) -> list[str]:
    if raw_args is None:
        return []
    if not isinstance(raw_args, list):
        raise ValueError("参数必须是数组")
    if len(raw_args) > 80:
        raise ValueError("参数过多")
    args: list[str] = []
    for item in raw_args:
        text = str(item)
        if "\x00" in text:
            raise ValueError("参数包含非法字符")
        args.append(text)
    return args


def _strict_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _option_name(value: str) -> str:
    return value.split("=", 1)[0].strip().lower()


def _validate_args(args: list[str], confirmed: bool) -> None:
    for arg in args:
        if not arg.startswith("-"):
            continue
        name = _option_name(arg)
        if name in FORBIDDEN_OPTIONS:
            raise ValueError("该参数不能通过能力中心执行")
        if name in CONFIRMATION_OPTIONS and not confirmed:
            raise PermissionError("该操作需要确认后执行")


def _arg_value(args: list[str], name: str) -> str:
    normalized = name.lower()
    for index, arg in enumerate(args):
        lowered = arg.lower()
        if lowered == normalized and index + 1 < len(args):
            return args[index + 1].strip().lower()
        if lowered.startswith(f"{normalized}="):
            return lowered.split("=", 1)[1].strip().lower()
    return ""


def _is_read_only(args: list[str], prefix: list[str], command_id: str = "") -> bool:
    words = [arg for arg in args if not arg.startswith("--")]
    prefix_words = [arg for arg in prefix if not arg.startswith("--")]
    while prefix_words and words and words[0].lower() == prefix_words[0].lower():
        words.pop(0)
        prefix_words.pop(0)
    if not words:
        return False
    action = words[0].lower()
    if command_id == "phone:agent" and action == "run":
        return _arg_value(args, "--mode") == "observe"
    return action in READ_ONLY_WORDS


def _clip(text: str, limit: int = 12000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def register_cli_routes(app, ctx) -> None:
    @app.api_route("/api/cli/catalog", methods=["GET", "POST"])
    async def cli_catalog(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"commands": _catalog()})

    @app.post("/api/cli/run")
    async def cli_run(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        command_id = str(body.get("command") or "").strip()
        command = CLI_COMMANDS.get(command_id)
        if not command:
            return ctx.fastapi_json({"error": "未知能力命令"}, 400)
        if feature_for_cli_command(command_id):
            if error := ctx.protected_error("/api/phone"):
                return error

        try:
            args = _normalize_args(body.get("args") or [])
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

        prefix = [str(item) for item in command.get("prefix")] if isinstance(command.get("prefix"), list) else []
        full_args = prefix + args
        confirmed = _strict_bool(body.get("confirmed"))
        try:
            _validate_args(full_args, confirmed)
        except PermissionError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 403)
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

        read_only = _is_read_only(full_args, prefix, command_id)
        if not read_only and not confirmed:
            return ctx.fastapi_json({"error": "该操作需要确认后执行"}, 403)

        script_path = _script_path(ctx, str(command["script"]))
        if not os.path.exists(script_path):
            return ctx.fastapi_json({"error": "能力脚本缺失"}, 404)
        if not os.path.exists(ctx.paths.node_exe):
            return ctx.fastapi_json({"error": "Node.js 运行时缺失"}, 500)

        try:
            timeout_sec = int(body.get("timeoutSec") or 300)
        except (TypeError, ValueError):
            timeout_sec = 300
        timeout_sec = max(5, min(timeout_sec, 1800))

        def target(job_id: str) -> dict:
            ctx.get_job_mgr().progress(job_id, "正在执行能力命令", "neutral")
            try:
                completed = subprocess.run(
                    [ctx.paths.node_exe, script_path, *full_args],
                    cwd=ctx.paths.base_path,
                    env=phone_process_env(ctx) if command_id.startswith("phone:") else {
                        **os.environ,
                        "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8",
                    },
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_sec,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                stdout = ctx.sanitize_text(_clip(exc.stdout if isinstance(exc.stdout, str) else ""))
                stderr = ctx.sanitize_text(_clip(exc.stderr if isinstance(exc.stderr, str) else ""))
                return {
                    "success": False,
                    "code": "timeout",
                    "error": "能力命令执行超时，详情已写入运行日志",
                    "stdout": stdout,
                    "stderr": stderr,
                }
            stdout = ctx.sanitize_text(_clip(completed.stdout or ""))
            stderr = ctx.sanitize_text(_clip(completed.stderr or ""))
            if completed.returncode != 0:
                return {
                    "success": False,
                    "code": completed.returncode,
                    "error": "能力命令执行失败，详情已写入运行日志",
                    "stdout": stdout,
                    "stderr": stderr,
                }
            return {
                "success": True,
                "code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }

        job = ctx.get_job_mgr().submit_progress("cli", str(command.get("title") or command_id), target)
        return ctx.fastapi_json({"jobId": job["id"], "job": job})
