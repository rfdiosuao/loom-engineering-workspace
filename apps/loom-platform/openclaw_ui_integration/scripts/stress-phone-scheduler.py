from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from core.paths import AppPaths  # noqa: E402
from services.phone_scheduler import PhoneAutomationScheduler  # noqa: E402


class TestPaths(AppPaths):
    @property
    def node_exe(self) -> str:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node executable not found on PATH")
        return node


class SoakPhoneServer:
    def __init__(self):
        self.requests: list[dict] = []
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "SoakPhoneServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=3)

    def task_post_count(self) -> int:
        with self.lock:
            return len([item for item in self.requests if item["method"] == "POST" and item["path"] == "/api/lumi/agent/tasks"])

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args) -> None:
                return

            def _json(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else ""
                try:
                    parsed = json.loads(body) if body else None
                except json.JSONDecodeError:
                    parsed = body
                with outer.lock:
                    outer.requests.append({"method": "POST", "path": self.path, "body": parsed})
                if self.path == "/api/lumi/security/pair":
                    self._json(200, {"success": True, "data": {"launcherId": "soak-launcher", "launcherSecret": "soak-secret"}})
                    return
                if self.path == "/api/lumi/agent/tasks":
                    with outer.lock:
                        task_id = f"soak-task-{len(outer.tasks) + 1}"
                        outer.tasks[task_id] = {"polls": 0, "prompt": (parsed or {}).get("prompt", "")}
                    self._json(200, {"success": True, "data": {"taskId": task_id, "status": "running"}})
                    return
                self._json(404, {"success": False, "error": "not_found"})

            def do_GET(self) -> None:
                with outer.lock:
                    outer.requests.append({"method": "GET", "path": self.path, "body": None})
                prefix = "/api/lumi/agent/tasks/"
                if self.path.startswith(prefix):
                    task_id = self.path[len(prefix) :]
                    with outer.lock:
                        task = outer.tasks.setdefault(task_id, {"polls": 0, "prompt": ""})
                        task["polls"] += 1
                        polls = task["polls"]
                    if polls < 2:
                        self._json(200, {"success": True, "data": {"taskId": task_id, "status": "running"}})
                    else:
                        self._json(
                            200,
                            {
                                "success": True,
                                "data": {
                                    "taskId": task_id,
                                    "status": "success",
                                    "result": {"answer": f"ok after {polls} polls"},
                                },
                            },
                        )
                    return
                self._json(404, {"success": False, "error": "not_found"})

        return Handler


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(data: dict) -> Path:
    candidates = [
        ROOT / "data" / "logs" / "phone-scheduler-soak.json",
        Path(tempfile.gettempdir()) / "openclaw-phone-scheduler-soak.json",
    ]
    last_error: Exception | None = None
    for path in candidates:
        try:
            write_json(path, data)
            return path
        except Exception as error:
            last_error = error
    raise RuntimeError(f"failed to write soak report: {last_error}")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_root() -> tuple[Path, TestPaths]:
    root = Path(tempfile.mkdtemp(prefix="openclaw-phone-soak-"))
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("openclaw-phone-agent.mjs", "openclaw-phone-secure.mjs"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    return root, TestPaths(str(root))


def install_config(root: Path, server_url: str) -> None:
    launcher = root / "data" / ".openclaw" / "launcher"
    devices = [
        {"id": "phone-a", "name": "Phone A", "baseUrl": server_url, "token": "fake-token"},
        {"id": "phone-b", "name": "Phone B", "baseUrl": server_url, "token": "fake-token"},
    ]
    write_json(
        launcher / "phone-agents.json",
        {
            "schema": "openclaw.launcher.phone-agents.v1",
            "selectedDeviceId": "phone-a",
            "devices": devices,
        },
    )
    write_json(
        launcher / "phone-automation.json",
        {
            "schema": "openclaw.launcher.phone-automation.v1",
            "templates": [
                {
                    "id": "tpl-soak",
                    "title": "Soak Safe Task",
                    "prompt": "soak cycle {{cycle}}",
                    "mode": "safe",
                    "riskLevel": "low",
                    "requiresManualConfirmation": False,
                    "variables": [{"key": "cycle", "value": "scheduled"}],
                }
            ],
            "schedules": [
                {
                    "id": "sch-soak",
                    "label": "Soak",
                    "templateId": "tpl-soak",
                    "deviceIds": [item["id"] for item in devices],
                    "cadence": "1m",
                    "timeWindow": "any",
                    "mode": "safe",
                    "enabled": True,
                    "allowUnattended": True,
                    "timeoutSec": 30,
                    "maxRounds": 2,
                    "maxWaitSec": 8,
                    "pollMs": 500,
                    "maxAttempts": 2,
                }
            ],
        },
    )


def queue_items(paths: AppPaths) -> list[dict]:
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    if not queue_path.exists():
        return []
    queue = read_json(queue_path)
    return list(queue.get("items") or [])


def active_items(paths: AppPaths) -> list[dict]:
    return [item for item in queue_items(paths) if item.get("status") in {"pending", "running", "submitted", "error"}]


def backdate_schedule(paths: AppPaths) -> None:
    state_path = Path(paths.launcher_dir) / "phone-automation-scheduler.json"
    state = read_json(state_path) if state_path.exists() else {"schema": "openclaw.phone-automation.scheduler.v1", "schedules": {}}
    state.setdefault("schedules", {}).setdefault("sch-soak", {})["lastEnqueuedAt"] = (
        datetime.now() - timedelta(minutes=2)
    ).isoformat()
    write_json(state_path, state)


def wait_for_idle(scheduler: PhoneAutomationScheduler, paths: AppPaths, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not scheduler._drain_lock.locked() and not Path(f"{paths.launcher_dir}/phone-agent-queue.json.drain.lock").exists():
            if not active_items(paths):
                return
        time.sleep(0.1)
    raise AssertionError(f"scheduler did not become idle; active={active_items(paths)}")


def assert_queue_integrity(paths: AppPaths, expected_total: int) -> None:
    items = queue_items(paths)
    ids = [item.get("id") for item in items]
    if len(ids) != len(set(ids)):
        raise AssertionError("queue contains duplicate item ids")
    expected_retained = min(expected_total, 200)
    if len(items) != expected_retained:
        raise AssertionError(f"expected {expected_retained} retained queue items from {expected_total} total, got {len(items)}")
    bad = [item for item in items if item.get("status") != "completed"]
    if bad:
        raise AssertionError(f"queue has non-completed items: {bad[:3]}")
    attempts = [int(item.get("attempts") or 0) for item in items]
    if any(value != 1 for value in attempts):
        raise AssertionError(f"unexpected attempts in successful soak run: {attempts[:10]}")


def run_manual_storm(scheduler: PhoneAutomationScheduler, workers: int) -> dict:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(
            executor.map(
                lambda index: scheduler.run_once("tpl-soak", ["phone-a"], "safe", True),
                range(workers),
            )
        )
    enqueued = sum(len(result.get("enqueued") or []) for result in results)
    skipped_reasons = [
        item.get("reason")
        for result in results
        for item in (result.get("skipped") or [])
    ]
    if enqueued != 1:
        raise AssertionError(f"manual run_once storm should accept exactly one task, got {enqueued}: {results}")
    if skipped_reasons.count("drain_running") != workers - 1:
        raise AssertionError(f"manual run_once storm should reject duplicates as drain_running, got {skipped_reasons}: {results}")
    return {"accepted": enqueued, "rejected": workers - enqueued}


def run_soak(duration_sec: int, max_cycles: int, storm_workers: int) -> dict:
    server = SoakPhoneServer().start()
    root, paths = make_root()
    logs: list[str] = []
    started = time.monotonic()
    cycles = 0
    manual_runs = 0
    manual_storms = 0
    manual_rejections = 0
    try:
        install_config(root, server.url)
        scheduler = PhoneAutomationScheduler(paths, logs.append, poll_seconds=5)
        while cycles < max_cycles and time.monotonic() - started < duration_sec:
            if cycles % 3 == 0:
                with ThreadPoolExecutor(max_workers=storm_workers) as executor:
                    results = list(executor.map(lambda _index: scheduler.tick(), range(storm_workers)))
                enqueued = sum(len(result.get("enqueued") or []) for result in results)
                if enqueued != 2:
                    raise AssertionError(f"tick storm should enqueue exactly two tasks, got {enqueued}: {results}")
            else:
                result = scheduler.tick()
                if len(result.get("enqueued") or []) != 2:
                    raise AssertionError(f"tick should enqueue two tasks, got {result}")
            wait_for_idle(scheduler, paths, timeout_sec=20)
            cycles += 1
            expected_total = cycles * 2 + manual_runs
            assert_queue_integrity(paths, expected_total)
            if server.task_post_count() != expected_total:
                raise AssertionError(f"expected {expected_total} task POSTs, got {server.task_post_count()}")

            if cycles % 5 == 0:
                result = scheduler.run_once("tpl-soak", ["phone-a"], "safe", True)
                if len(result.get("enqueued") or []) != 1:
                    raise AssertionError(f"manual run_once should enqueue one task, got {result}")
                wait_for_idle(scheduler, paths, timeout_sec=20)
                manual_runs += 1
                expected_total = cycles * 2 + manual_runs
                assert_queue_integrity(paths, expected_total)
                if server.task_post_count() != expected_total:
                    raise AssertionError(f"expected {expected_total} task POSTs after manual run, got {server.task_post_count()}")

            if cycles % 17 == 0:
                storm = run_manual_storm(scheduler, storm_workers)
                wait_for_idle(scheduler, paths, timeout_sec=30)
                manual_runs += storm["accepted"]
                manual_rejections += storm["rejected"]
                manual_storms += 1
                expected_total = cycles * 2 + manual_runs
                assert_queue_integrity(paths, expected_total)
                if server.task_post_count() != expected_total:
                    raise AssertionError(f"expected {expected_total} task POSTs after manual storm, got {server.task_post_count()}")

            backdate_schedule(paths)

        elapsed = time.monotonic() - started
        report = {
            "ok": True,
            "elapsedSec": round(elapsed, 3),
            "cycles": cycles,
            "manualRuns": manual_runs,
            "manualStorms": manual_storms,
            "manualRejections": manual_rejections,
            "taskPosts": server.task_post_count(),
            "queueItems": len(queue_items(paths)),
            "requestCount": len(server.requests),
            "logsTail": logs[-20:],
        }
        report_path = write_report(report)
        report["reportPath"] = str(report_path)
        return report
    finally:
        server.stop()
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local phone scheduler soak test against a fake APKClaw server.")
    parser.add_argument("--duration-sec", type=int, default=120)
    parser.add_argument("--max-cycles", type=int, default=120)
    parser.add_argument("--storm-workers", type=int, default=8)
    args = parser.parse_args()
    report = run_soak(max(1, args.duration_sec), max(1, args.max_cycles), max(2, args.storm_workers))
    print(
        "[phone-scheduler-soak] ok "
        f"cycles={report['cycles']} manual={report['manualRuns']} "
        f"manualStorms={report['manualStorms']} manualRejected={report['manualRejections']} "
        f"taskPosts={report['taskPosts']} elapsed={report['elapsedSec']}s "
        f"report={report['reportPath']}"
    )


if __name__ == "__main__":
    main()
