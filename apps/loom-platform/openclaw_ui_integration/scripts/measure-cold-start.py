#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure OpenClaw cold start time")
    parser.add_argument("--root", default=str(Path.cwd()), help="Launcher root directory")
    parser.add_argument("--timeout-sec", type=int, default=600, help="Startup timeout in seconds")
    parser.add_argument("--poll-ms", type=int, default=500, help="Startup status poll interval in milliseconds")
    parser.add_argument("--stop-after-measure", action="store_true", help="Stop process after measurement")
    parser.add_argument("--output-path", default="", help="Where to write JSON output")
    parser.add_argument("--budget-ms", type=int, default=30000, help="Expected cold-start budget in milliseconds")
    return parser.parse_args()


def discover_python_root(root: Path) -> Path:
    candidates = [
        root / "python",
        root / "OpenClawFiles" / "_up_" / "python",
        root / "OpenClawFiles" / "python",
        root / "_up_" / "python",
    ]
    for candidate in candidates:
        if (candidate / "core" / "paths.py").exists():
            return candidate
    raise FileNotFoundError(f"Cannot locate launcher python package under {root}")


def load_service(root: Path):
    python_root = discover_python_root(root)
    sys.path.insert(0, str(python_root))

    from core.paths import AppPaths
    from core.constants import APP_PORT
    from services.process import OpenClawProcessService

    paths = AppPaths.discover()
    logs: list[str] = []

    def append_log(text: str) -> None:
        logs.append(text.rstrip("\r\n"))
        print(text, end="")

    def ui_call(*_args, **_kwargs) -> None:
        return None

    return paths, APP_PORT, OpenClawProcessService(paths, append_log, ui_call), logs


def read_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def machine_profile() -> dict:
    profile = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpuCount": os.cpu_count(),
    }
    if os.name == "nt":
        try:
            import ctypes
            import ctypes.wintypes as wintypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            mem = MemoryStatusEx()
            mem.dwLength = ctypes.sizeof(MemoryStatusEx)
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                profile["totalMemoryBytes"] = int(mem.ullTotalPhys)
                profile["availableMemoryBytes"] = int(mem.ullAvailPhys)
        except Exception:
            pass
    return profile


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    os.chdir(root)
    os.environ["OPENCLAW_STARTUP_TIMEOUT_SEC"] = str(args.timeout_sec)

    paths, app_port, service, logs = load_service(root)
    if service._is_port_listening(app_port):
        raise RuntimeError(f"OpenClaw port {app_port} is already listening. Close the running service before measuring cold start.")

    snapshot_path = Path(paths.data_dir) / "logs" / "openclaw-startup-snapshot.json"
    start = time.perf_counter()
    error = ""
    try:
        service.start()
    except Exception as exc:
        error = str(exc)
        service.startup_state = "failed"
        service.startup_error = error

    status = service.status()
    deadline = start + max(args.timeout_sec, 1)
    poll_interval = max(args.poll_ms, 50) / 1000
    while not error and time.perf_counter() < deadline:
        if status.get("portReady") or status.get("startupState") == "failed" or status.get("startupError"):
            break
        time.sleep(poll_interval)
        status = service.status()

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    snapshot = read_json_if_exists(snapshot_path)
    port_ready = bool(status.get("portReady"))
    startup_error = error or status.get("startupError") or snapshot.get("error", "")
    if port_ready and elapsed_ms <= args.budget_ms:
        verdict = "pass"
    elif port_ready:
        verdict = "warn"
    else:
        verdict = "fail"
    result = {
        "root": str(root),
        "pythonRoot": str(discover_python_root(root)),
        "snapshotPath": str(snapshot_path),
        "budgetMs": args.budget_ms,
        "measuredColdStartMs": elapsed_ms,
        "coldStartVerdict": verdict,
        "startupState": status.get("startupState"),
        "startupElapsedSec": status.get("startupElapsedSec"),
        "startupTimeoutSec": status.get("startupTimeoutSec"),
        "startupError": startup_error,
        "startupStage": status.get("startupStage") or (snapshot.get("startupTimeline") or [{}])[-1].get("stage"),
        "pid": status.get("pid"),
        "portReady": status.get("portReady"),
        "running": status.get("running"),
        "processAlive": status.get("processAlive"),
        "machine": machine_profile(),
        "snapshot": snapshot,
        "logsTail": logs[-40:],
    }

    output_path = Path(args.output_path) if args.output_path else Path(paths.data_dir) / "logs" / "cold-start-measurement.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"Cold start measured: {elapsed_ms} ms"
        f" (state={result['startupState']}, ready={result['portReady']}) -> {output_path}"
    )

    if args.stop_after_measure:
        try:
            service.stop()
        except Exception as stop_error:
            print(f"WARNING: failed to stop service: {stop_error}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
