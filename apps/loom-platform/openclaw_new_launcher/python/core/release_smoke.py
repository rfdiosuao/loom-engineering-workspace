"""Non-destructive release-readiness smoke checks for a running LOOM bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


Json = dict[str, Any]
CommandRunner = Callable[[Sequence[str], int], tuple[int, str, str]]


def run_release_smoke(
    cli_path: str,
    *,
    python_executable: str = sys.executable,
    require_provider: bool = False,
    require_matrix: bool = False,
    require_phone_count: int = 0,
    timeout_sec: int = 45,
    command_runner: CommandRunner | None = None,
) -> Json:
    runner = command_runner or _subprocess_runner
    checks: list[Json] = []

    checks.append(_run_check("bridge_status", ["status"], cli_path, python_executable, timeout_sec, runner))
    checks.append(_run_check("media_config", ["media", "config"], cli_path, python_executable, timeout_sec, runner))
    if require_provider:
        checks.append(_run_check("provider_verify", ["wire", "verify"], cli_path, python_executable, timeout_sec, runner))
    if require_matrix:
        checks.append(_run_check("matrix_status", ["matrix", "status"], cli_path, python_executable, timeout_sec, runner))
    if require_phone_count > 0:
        phone_check = _run_check("phone_status", ["phone", "status"], cli_path, python_executable, timeout_sec, runner)
        observed = _phone_count(phone_check.get("payload"))
        phone_check["observedDevices"] = observed
        phone_check["requiredDevices"] = require_phone_count
        if phone_check.get("passed") and observed < require_phone_count:
            phone_check.update({
                "passed": False,
                "error": f"仅检测到 {observed} 台手机，需要至少 {require_phone_count} 台。",
            })
        checks.append(phone_check)

    failed = [item for item in checks if not item.get("passed")]
    return {
        "schema": "loom.release-smoke.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "passed": not failed,
        "summary": {"total": len(checks), "passed": len(checks) - len(failed), "failed": len(failed)},
        "requirements": {
            "provider": require_provider,
            "matrix": require_matrix,
            "phoneCount": require_phone_count,
        },
        "checks": checks,
    }


def write_report(path: str, report: Json) -> str:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return str(target)


def _run_check(
    name: str,
    args: list[str],
    cli_path: str,
    python_executable: str,
    timeout_sec: int,
    runner: CommandRunner,
) -> Json:
    command = [python_executable, cli_path, *args, "--json"]
    try:
        return_code, stdout, stderr = runner(command, timeout_sec)
    except Exception as exc:
        return {"name": name, "passed": False, "error": _safe_text(exc)}
    payload = _parse_payload(stdout)
    passed = return_code == 0 and isinstance(payload, dict) and _business_ok(payload)
    result: Json = {"name": name, "passed": passed, "returnCode": return_code}
    if payload:
        result["payload"] = _public_payload(payload)
    if not passed:
        error = _business_error(payload) if isinstance(payload, dict) else None
        result["error"] = _safe_text(error or stderr or stdout or "命令没有返回有效 JSON。")
    return result


def _subprocess_runner(command: Sequence[str], timeout_sec: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(5, timeout_sec),
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _parse_payload(stdout: str) -> Json:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for candidate in reversed(lines):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _public_payload(payload: Json) -> Json:
    result: Json = {"ok": bool(payload.get("ok")), "command": payload.get("command")}
    data = payload.get("data")
    if isinstance(data, dict):
        result["data"] = _redact(data)
    if isinstance(payload.get("error"), dict):
        result["error"] = _redact(payload["error"])
    return result


def _redact(value: Any, key: str = "") -> Any:
    normalized = "".join(ch for ch in key.casefold() if ch.isalnum())
    if normalized in {"apikey", "token", "authorization", "password", "secret", "bridgetoken"}:
        return "***"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and (value.startswith("sk-") or value.lower().startswith("bearer ")):
        return "***"
    return value


def _phone_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(data.get("result"), dict):
        data = data["result"]
    for key in ("count", "onlineCount", "deviceCount"):
        value = data.get(key)
        if isinstance(value, int):
            return max(0, value)
    for key in ("results", "devices"):
        value = data.get(key)
        if isinstance(value, list):
            return sum(
                1
                for item in value
                if isinstance(item, dict)
                and item.get("ok", True)
                and (not isinstance(item.get("status"), dict) or item["status"].get("online", True))
            )
    return 0


def _business_ok(payload: Json) -> bool:
    if not bool(payload.get("ok")):
        return False
    data = payload.get("data")
    if isinstance(data, dict) and "ok" in data and not bool(data.get("ok")):
        return False
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        result = data["result"]
        if "ok" in result and not bool(result.get("ok")):
            return False
        meta = result.get("_meta")
        if isinstance(meta, dict) and "ok" in meta and not bool(meta.get("ok")):
            return False
    return True


def _business_error(payload: Json) -> Any:
    candidates: list[Any] = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data)
        if isinstance(data.get("result"), dict):
            candidates.append(data["result"])
    for candidate in reversed(candidates):
        if not isinstance(candidate, dict):
            continue
        for key in ("error", "message", "detail"):
            value = candidate.get(key)
            if value:
                return value
    return None


def _safe_text(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return text.replace("\r", " ").replace("\n", " ")[:500]


__all__ = ["run_release_smoke", "write_report"]
