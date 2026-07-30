"""Launcher CLI capability routes.

The UI and future agents call these routes instead of constructing shell
commands. Each entry maps to a known local script and runs through the job
manager so page switches do not lose progress.
"""

from __future__ import annotations

import os
import subprocess
import time
from fastapi import Request

from core.feature_access import feature_for_cli_command
from core.account_entitlement import AccountEntitlementError
from api.routes_phone import (
    _account_task_slot,
    _authorize_phone_cleanup_scope,
    _authorize_phone_entitlement,
    _claimed_phone_local_device_ids,
    _normalize_device_id,
    _phone_entitlement_job_metadata,
    phone_process_env,
)
from core.job_ownership import public_job_snapshot


_PHONE_CLI_ENTITLEMENT_HEARTBEAT_SEC = 5.0


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
        "cooperativeCancel": True,
        "examples": ["history --limit 10 --json", "run --prompt \"读取当前屏幕\" --mode observe --json"],
    },
    "phone:fleet": {
        "title": "多设备",
        "script": "openclaw-phone-fleet.mjs",
        "cooperativeCancel": True,
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
        "cooperativeCancel": True,
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
PHONE_DIRECT_CREDENTIAL_OPTIONS = {
    "--phone-token",
    "--phone-url",
}
PHONE_DIRECT_RELAY_OPTIONS = {
    "--channel",
    "--channel-id",
    "--relay-token",
    "--relay-url",
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


def _phone_target_ids(args: list[str]) -> list[str]:
    values: list[str] = []
    options = {
        "--device",
        "--device-id",
        "--device-ids",
        "--devices",
        "--target",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        name = _option_name(arg)
        value = ""
        if name in options:
            if "=" in arg:
                value = arg.split("=", 1)[1]
            elif index + 1 < len(args):
                value = args[index + 1]
                index += 1
        if value:
            values.extend(value.split(","))
        index += 1
    return sorted(
        {
            _normalize_device_id(value, "")
            for value in values
            if str(value or "").strip().lower() not in {"all", "current"}
        }
    )


def _is_exact_phone_cleanup(
    command_id: str,
    args: list[str],
) -> bool:
    words = [arg.lower() for arg in args if not arg.startswith("-")]
    return (
        command_id == "phone:video"
        and bool(words)
        and words[0] == "stop"
        and bool(_phone_target_ids(args))
    )


def _entitlement_error(ctx, error: AccountEntitlementError):
    return ctx.fastapi_json(error.payload(), error.status_code)


def _stop_process(process) -> None:
    try:
        if process.poll() is not None:
            return
    except Exception:
        return
    try:
        process.terminate()
    except Exception:
        try:
            process.kill()
        except Exception:
            return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return
    try:
        process.kill()
    except Exception:
        return
    try:
        process.wait(timeout=2)
    except (subprocess.TimeoutExpired, Exception):
        return


def _collect_stopped_process(process) -> tuple[str, str]:
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        try:
            return process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            return "", "子进程已终止，但输出管道未能及时关闭。"
        except Exception:
            return "", "子进程已终止，但无法读取剩余输出。"
    except Exception:
        return "", "子进程已终止，但无法读取剩余输出。"


def _close_process_pipes(process) -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(process, name, None)
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                continue


def _write_phone_cli_cancel_signal(cancel_file: str) -> None:
    safe_path = str(cancel_file or "").strip()
    if not safe_path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(safe_path)), exist_ok=True)
    with open(safe_path, "w", encoding="ascii") as handle:
        handle.write("cancelled\n")


def _run_phone_cli_process(
    ctx,
    *,
    argv: list[str],
    allowed_device_ids: list[str],
    operation: str,
    timeout_sec: int,
    safety_cleanup: bool,
    should_cancel=None,
    cancel_file: str = "",
    cooperative_cancel: bool = False,
) -> dict:
    def cancellation_requested() -> bool:
        if not callable(should_cancel):
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return True

    if cancellation_requested():
        return {
            "success": False,
            "code": "cancelled",
            "error": "能力命令已取消",
            "cancelled": True,
            "stdout": "",
            "stderr": "",
        }
    entitlement: dict = {}
    if not safety_cleanup:
        try:
            entitlement = _authorize_phone_entitlement(
                ctx,
                allowed_device_ids,
                operation,
            )
        except AccountEntitlementError as error:
            return {
                "success": False,
                "code": error.code,
                "error": str(error),
                "action": error.action,
                "details": error.details,
                "stdout": "",
                "stderr": "",
            }
        except Exception:
            return {
                "success": False,
                "code": "phone_entitlement_check_failed",
                "error": "手机权益复验失败，已停止能力命令",
                "action": "retry",
                "stdout": "",
                "stderr": "",
            }

    process_argv = list(argv)
    if (
        cooperative_cancel
        and cancel_file
        and "--cancel-file" not in process_argv
    ):
        process_argv.extend(["--cancel-file", cancel_file])

    def stop_with_signal(process) -> tuple[str, str]:
        try:
            _write_phone_cli_cancel_signal(cancel_file)
        except OSError:
            pass
        if cooperative_cancel:
            try:
                process.wait(timeout=0.35)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
        _stop_process(process)
        return _collect_stopped_process(process)

    def execute_process() -> dict:
        process = None
        try:
            process = subprocess.Popen(
                process_argv,
                cwd=ctx.paths.base_path,
                env=phone_process_env(ctx, allowed_device_ids),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + timeout_sec
            while True:
                if cancellation_requested():
                    stdout, stderr = stop_with_signal(process)
                    return {
                        "success": False,
                        "code": "cancelled",
                        "error": "能力命令已取消",
                        "cancelled": True,
                        "stdout": ctx.sanitize_text(_clip(stdout)),
                        "stderr": ctx.sanitize_text(_clip(stderr)),
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stdout, stderr = stop_with_signal(process)
                    return {
                        "success": False,
                        "code": "timeout",
                        "error": "能力命令执行超时，详情已写入运行日志",
                        "stdout": ctx.sanitize_text(_clip(stdout)),
                        "stderr": ctx.sanitize_text(_clip(stderr)),
                    }
                wait_sec = min(
                    remaining,
                    _PHONE_CLI_ENTITLEMENT_HEARTBEAT_SEC,
                )
                try:
                    stdout, stderr = process.communicate(timeout=wait_sec)
                    break
                except subprocess.TimeoutExpired:
                    if safety_cleanup:
                        continue
                    try:
                        _authorize_phone_entitlement(
                            ctx,
                            allowed_device_ids,
                            operation,
                        )
                    except AccountEntitlementError as error:
                        stdout, stderr = stop_with_signal(process)
                        return {
                            "success": False,
                            "code": error.code,
                            "error": str(error),
                            "action": error.action,
                            "details": error.details,
                            "stdout": ctx.sanitize_text(_clip(stdout)),
                            "stderr": ctx.sanitize_text(_clip(stderr)),
                        }
                    except Exception:
                        stdout, stderr = stop_with_signal(process)
                        return {
                            "success": False,
                            "code": "phone_entitlement_check_failed",
                            "error": "手机权益复验失败，已停止能力命令",
                            "action": "retry",
                            "stdout": ctx.sanitize_text(_clip(stdout)),
                            "stderr": ctx.sanitize_text(_clip(stderr)),
                        }
            stdout = ctx.sanitize_text(_clip(stdout or ""))
            stderr = ctx.sanitize_text(_clip(stderr or ""))
            if process.returncode != 0:
                return {
                    "success": False,
                    "code": process.returncode,
                    "error": "能力命令执行失败，详情已写入运行日志",
                    "stdout": stdout,
                    "stderr": stderr,
                }
            return {
                "success": True,
                "code": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        finally:
            if process is not None:
                _stop_process(process)
                _close_process_pipes(process)

    if safety_cleanup:
        return execute_process()
    try:
        with _account_task_slot(
            ctx,
            entitlement,
            operation,
            cancelled=cancellation_requested,
            device_ids=allowed_device_ids,
        ):
            return execute_process()
    except AccountEntitlementError as error:
        return {
            "success": False,
            "code": error.code,
            "error": str(error),
            "action": error.action,
            "details": error.details,
            "stdout": "",
            "stderr": "",
        }


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

        try:
            args = _normalize_args(body.get("args") or [])
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)
        is_phone_command = command_id.startswith("phone:")
        if is_phone_command and any(
            _option_name(arg) in PHONE_DIRECT_CREDENTIAL_OPTIONS
            for arg in args
            if arg.startswith("-")
        ):
            return ctx.fastapi_json(
                {
                    "code": "phone_direct_credentials_forbidden",
                    "error": "手机地址与令牌由 LOOM 当前账号和已领取设备统一注入，不能通过能力参数覆盖。",
                },
                400,
            )
        if command_id == "phone:publish" and (
            any(
                _option_name(arg) in PHONE_DIRECT_RELAY_OPTIONS
                for arg in args
                if arg.startswith("-")
            )
            or _arg_value(args, "--transport") == "reverse"
        ):
            return ctx.fastapi_json(
                {
                    "code": "phone_direct_relay_forbidden",
                    "error": "发布中继由 LOOM 当前账号和服务端授权统一选择，不能通过能力参数覆盖。",
                },
                400,
            )
        if feature_for_cli_command(command_id, args):
            if error := ctx.protected_error("/api/phone"):
                return error

        prefix = [str(item) for item in command.get("prefix")] if isinstance(command.get("prefix"), list) else []
        full_args = prefix + args
        safety_cleanup = _is_exact_phone_cleanup(command_id, full_args)
        allowed_phone_device_ids: list[str] = []
        if is_phone_command:
            try:
                requested_phone_device_ids = _phone_target_ids(full_args)
                if safety_cleanup:
                    allowed_phone_device_ids = _authorize_phone_cleanup_scope(
                        ctx,
                        requested_phone_device_ids,
                    )
                else:
                    claimed_phone_device_ids = _claimed_phone_local_device_ids(ctx)
                    if not claimed_phone_device_ids:
                        raise AccountEntitlementError(
                            "当前账号尚未领取任何手机席位。",
                            code="phone_seat_required",
                            action="pair_phone",
                            status_code=403,
                        )
                    unclaimed = sorted(
                        set(requested_phone_device_ids).difference(
                            claimed_phone_device_ids
                        )
                    )
                    if unclaimed:
                        raise AccountEntitlementError(
                            "指定手机不属于当前账号的有效席位。",
                            code="phone_seat_not_claimed",
                            action="select_claimed_phone",
                            details={"phoneDeviceIds": unclaimed},
                            status_code=409,
                        )
                    allowed_phone_device_ids = (
                        requested_phone_device_ids
                        or claimed_phone_device_ids
                    )
                    _authorize_phone_entitlement(
                        ctx,
                        allowed_phone_device_ids,
                        f"cli.{command_id}",
                    )
            except AccountEntitlementError as error:
                return _entitlement_error(ctx, error)
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
            if is_phone_command:
                cancel_file_getter = getattr(
                    ctx.get_job_mgr(),
                    "cancel_file",
                    None,
                )
                return _run_phone_cli_process(
                    ctx,
                    argv=[ctx.paths.node_exe, script_path, *full_args],
                    allowed_device_ids=allowed_phone_device_ids,
                    operation=f"cli.{command_id}",
                    timeout_sec=timeout_sec,
                    safety_cleanup=safety_cleanup,
                    should_cancel=lambda: ctx.get_job_mgr().is_cancelled(job_id),
                    cancel_file=(
                        str(cancel_file_getter(job_id) or "")
                        if callable(cancel_file_getter)
                        else ""
                    ),
                    cooperative_cancel=bool(
                        command.get("cooperativeCancel")
                    ),
                )
            try:
                completed = subprocess.run(
                    [ctx.paths.node_exe, script_path, *full_args],
                    cwd=ctx.paths.base_path,
                    env={
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

        job = ctx.get_job_mgr().submit_progress(
            "cli",
            str(command.get("title") or command_id),
            target,
            initial_progress=(
                {
                    "message": "手机能力命令已排队",
                    "phase": f"cli.{command_id}.queued",
                    "commandId": f"cli.{command_id}",
                    **_phone_entitlement_job_metadata(
                        ctx,
                        allowed_phone_device_ids,
                    ),
                }
                if is_phone_command
                else None
            ),
        )
        return ctx.fastapi_json(
            {"jobId": job["id"], "job": public_job_snapshot(job)}
        )
