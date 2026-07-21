from __future__ import annotations

import json
import os
import shutil
import subprocess
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


class NoAutoDrainScheduler(PhoneAutomationScheduler):
    def __init__(self, paths: AppPaths, logs: list[str]):
        super().__init__(paths, logs.append, poll_seconds=5)
        self.drain_requested = 0

    def _drain_async(self) -> None:
        self.drain_requested += 1


class FakePhoneServer:
    def __init__(self):
        self.requests: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "FakePhoneServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=3)

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
                outer.requests.append({"method": "POST", "path": self.path, "body": parsed})
                if self.path == "/api/lumi/security/pair":
                    self._json(200, {"success": True, "data": {"launcherId": "fake-launcher", "launcherSecret": "fake-secret"}})
                    return
                if self.path == "/api/lumi/agent/tasks":
                    self._json(200, {"success": True, "data": {"taskId": "fake-task-1", "status": "running"}})
                    return
                self._json(404, {"success": False, "error": "not_found"})

            def do_GET(self) -> None:
                outer.requests.append({"method": "GET", "path": self.path, "body": None})
                if self.path == "/api/lumi/agent/tasks/fake-task-1":
                    self._json(200, {"success": True, "data": {"taskId": "fake-task-1", "status": "success", "result": {"answer": "ok"}}})
                    return
                self._json(404, {"success": False, "error": "not_found"})

        return Handler


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_root() -> tuple[Path, TestPaths]:
    root = Path(tempfile.mkdtemp(prefix="openclaw-phone-scheduler-"))
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("openclaw-phone-agent.mjs", "openclaw-phone-secure.mjs"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    return root, TestPaths(str(root))


def install_config(root: Path, server_url: str, schedules: list[dict], templates: list[dict] | None = None) -> None:
    launcher = root / "data" / ".openclaw" / "launcher"
    write_json(
        launcher / "phone-agents.json",
        {
            "schema": "openclaw.launcher.phone-agents.v1",
            "selectedDeviceId": "phone-a",
            "devices": [
                {"id": "phone-a", "name": "Phone A", "baseUrl": server_url, "token": "fake-token"},
                {"id": "phone-b", "name": "Phone B", "baseUrl": server_url, "token": "fake-token"},
            ],
        },
    )
    write_json(
        launcher / "phone-automation.json",
        {
            "schema": "openclaw.launcher.phone-automation.v1",
            "templates": templates
            or [
                {
                    "id": "tpl-safe",
                    "title": "Safe",
                    "prompt": "run {{name}}",
                    "mode": "safe",
                    "riskLevel": "low",
                    "requiresManualConfirmation": False,
                    "variables": [{"key": "name", "value": "smoke"}],
                }
            ],
            "schedules": schedules,
        },
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def active_queue_count(paths: AppPaths) -> int:
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    if not queue_path.exists():
        return 0
    queue = read_json(queue_path)
    return len(queue.get("items") or [])


def mark_queue_completed(paths: AppPaths) -> None:
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    queue = read_json(queue_path)
    for item in queue.get("items") or []:
        item["status"] = "completed"
    write_json(queue_path, queue)


def backdate_schedule(paths: AppPaths, schedule_id: str, minutes: int) -> None:
    state_path = Path(paths.launcher_dir) / "phone-automation-scheduler.json"
    state = read_json(state_path)
    state.setdefault("schedules", {}).setdefault(schedule_id, {})["lastEnqueuedAt"] = (
        datetime.now() - timedelta(minutes=minutes)
    ).isoformat()
    write_json(state_path, state)


def test_scheduler_stress(paths: TestPaths, server_url: str) -> None:
    schedules = [
        {
            "id": "sch-fast",
            "label": "Fast",
            "templateId": "tpl-safe",
            "deviceIds": ["phone-a", "phone-b"],
            "cadence": "every 1 minutes",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
            "maxWaitSec": 3,
            "pollMs": 500,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules)
    logs: list[str] = []
    scheduler = NoAutoDrainScheduler(paths, logs)

    first = scheduler.tick()
    assert_true(len(first["enqueued"]) == 2, f"expected two device queue entries, got {first}")
    assert_true(active_queue_count(paths) == 2, "first tick did not write two queue items")
    first_queue = read_json(Path(paths.launcher_dir) / "phone-agent-queue.json")
    assert_true(all(item.get("maxAttempts") == 2 for item in first_queue.get("items") or []), "scheduled queue items must cap retries")
    assert_true(scheduler.drain_requested == 1, "scheduler did not request drain after enqueue")

    for _ in range(20):
        repeat = scheduler.tick()
        assert_true(not repeat["enqueued"], f"repeat tick should not enqueue while active: {repeat}")
    assert_true(active_queue_count(paths) == 2, "repeat ticks created duplicate active queue entries")

    mark_queue_completed(paths)
    backdate_schedule(paths, "sch-fast", minutes=2)
    second = scheduler.tick()
    assert_true(len(second["enqueued"]) == 2, f"expected second interval enqueue, got {second}")
    assert_true(active_queue_count(paths) == 4, "second interval did not add two more queue items")


def test_concurrent_tick_dedup(paths: TestPaths, server_url: str) -> None:
    schedules = [
        {
            "id": "sch-concurrent",
            "label": "Concurrent",
            "templateId": "tpl-safe",
            "deviceIds": ["phone-a", "phone-b"],
            "cadence": "every 1 minutes",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
            "maxWaitSec": 3,
            "pollMs": 500,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules)
    scheduler = NoAutoDrainScheduler(paths, [])

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _index: scheduler.tick(), range(12)))

    total_enqueued = sum(len(result.get("enqueued") or []) for result in results)
    assert_true(total_enqueued == 2, f"concurrent ticks duplicated queue entries: {results}")
    assert_true(active_queue_count(paths) == 2, "concurrent ticks wrote duplicate queue items")
    assert_true(scheduler.drain_requested == 1, "concurrent ticks requested multiple drains")


def test_drain_running_blocks_queue_writes(paths: TestPaths, server_url: str) -> None:
    schedules = [
        {
            "id": "sch-drain-busy",
            "label": "Drain Busy",
            "templateId": "tpl-safe",
            "deviceIds": ["phone-a"],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules)
    scheduler = NoAutoDrainScheduler(paths, [])
    assert_true(scheduler._drain_lock.acquire(blocking=False), "test could not acquire drain lock")
    try:
        tick_result = scheduler.tick()
        run_result = scheduler.run_once("tpl-safe", ["phone-a"], "safe", True)
    finally:
        scheduler._drain_lock.release()

    tick_reasons = [item.get("reason") for item in tick_result.get("skipped") or []]
    run_reasons = [item.get("reason") for item in run_result.get("skipped") or []]
    assert_true("drain_running" in tick_reasons, f"tick did not defer while drain was running: {tick_result}")
    assert_true("drain_running" in run_reasons, f"run_once did not defer while drain was running: {run_result}")
    assert_true(active_queue_count(paths) == 0, "scheduler wrote queue while drain lock was held")


def test_external_drain_lock_blocks_scheduler_writes(paths: TestPaths, server_url: str) -> None:
    schedules = [
        {
            "id": "sch-node-drain-busy",
            "label": "Node Drain Busy",
            "templateId": "tpl-safe",
            "deviceIds": ["phone-a"],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules)
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    write_json(
        Path(f"{queue_path}.drain.lock"),
        {
            "schema": "openclaw.phone-agent.drain-lock.v1",
            "pid": os.getpid(),
            "createdAt": datetime.now().isoformat(),
        },
    )
    scheduler = NoAutoDrainScheduler(paths, [])
    tick_result = scheduler.tick()
    run_result = scheduler.run_once("tpl-safe", ["phone-a"], "safe", True)

    tick_reasons = [item.get("reason") for item in tick_result.get("skipped") or []]
    run_reasons = [item.get("reason") for item in run_result.get("skipped") or []]
    assert_true("drain_running" in tick_reasons, f"tick ignored external drain lock: {tick_result}")
    assert_true("drain_running" in run_reasons, f"run_once ignored external drain lock: {run_result}")
    assert_true(active_queue_count(paths) == 0, "scheduler wrote queue while external drain lock was held")
    assert_true(scheduler.drain_requested == 0, "scheduler requested drain while external drain lock was held")


def test_dry_run_never_enqueues(paths: TestPaths, server_url: str) -> None:
    schedules = [
        {
            "id": "sch-dry",
            "label": "Dry",
            "templateId": "tpl-safe",
            "deviceIds": ["phone-a"],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "dry-run",
            "enabled": True,
            "allowUnattended": True,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules)
    scheduler = NoAutoDrainScheduler(paths, [])
    tick_result = scheduler.tick()
    run_result = scheduler.run_once("tpl-safe", ["phone-a"], "dry-run", True)
    tick_reasons = [item.get("reason") for item in tick_result.get("skipped") or []]
    run_reasons = [item.get("reason") for item in run_result.get("skipped") or []]
    assert_true("dry_run" in tick_reasons, f"scheduled dry-run was not reported: {tick_result}")
    assert_true("dry_run" in run_reasons, f"manual dry-run was not reported: {run_result}")
    assert_true(active_queue_count(paths) == 0, "dry-run unexpectedly wrote phone queue")
    assert_true(scheduler.drain_requested == 0, "dry-run unexpectedly requested drain")


def test_queue_trim_preserves_active(paths: TestPaths, server_url: str) -> None:
    install_config(Path(paths.base_path), server_url, [])
    scheduler = NoAutoDrainScheduler(paths, [])
    active = [{"id": f"active-{index}", "status": "pending"} for index in range(250)]
    completed = [{"id": f"done-{index}", "status": "completed"} for index in range(300)]
    trimmed = scheduler._trim_queue_items(active + completed)
    trimmed_ids = {item["id"] for item in trimmed}
    assert_true(all(item["id"] in trimmed_ids for item in active), "active queue items were trimmed")
    assert_true(len([item for item in trimmed if item["status"] == "completed"]) == 0, "completed items should not displace active items")

    trimmed = scheduler._trim_queue_items(completed)
    assert_true(len(trimmed) == 200, f"expected 200 retained completed items, got {len(trimmed)}")
    assert_true(trimmed[0]["id"] == "done-100" and trimmed[-1]["id"] == "done-299", "completed retention did not keep newest items")


def test_guardrails(paths: TestPaths, server_url: str) -> None:
    templates = [
        {"id": "tpl-safe", "title": "Safe", "prompt": "safe", "mode": "safe", "riskLevel": "low", "variables": []},
        {
            "id": "tpl-risk",
            "title": "Risk",
            "prompt": "publish",
            "mode": "safe",
            "riskLevel": "high",
            "requiresManualConfirmation": True,
            "variables": [],
        },
    ]
    schedules = [
        {
            "id": "sch-risk",
            "templateId": "tpl-risk",
            "deviceIds": ["phone-a"],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
        },
        {
            "id": "sch-empty",
            "templateId": "tpl-safe",
            "deviceIds": [],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
        },
    ]
    install_config(Path(paths.base_path), server_url, schedules, templates)
    scheduler = NoAutoDrainScheduler(paths, [])
    result = scheduler.tick()
    reasons = {item["scheduleId"]: item["reason"] for item in result["skipped"]}
    assert_true(reasons.get("sch-risk") == "manual_confirmation_required", f"risk guard failed: {result}")
    assert_true(reasons.get("sch-empty") == "device_missing", f"missing-device guard failed: {result}")
    state = read_json(Path(paths.launcher_dir) / "phone-automation-scheduler.json")
    assert_true("lastEnqueuedAt" not in state["schedules"].get("sch-empty", {}), "missing-device schedule was marked enqueued")


def test_ad_watch_template_runtime(paths: TestPaths, server_url: str) -> None:
    templates = [
        {
            "id": "generic-ad-watch-reward",
            "title": "广告等待",
            "prompt": "OPENCLAW_AD_WATCH。最短等待 {{minWatchSeconds}} 秒，最长等待 {{maxWatchSeconds}} 秒。",
            "mode": "safe",
            "riskLevel": "medium",
            "requiresManualConfirmation": False,
            "variables": [
                {"key": "minWatchSeconds", "value": "30"},
                {"key": "maxWatchSeconds", "value": "90"},
            ],
        }
    ]
    schedules = [
        {
            "id": "sch-ad-watch",
            "templateId": "generic-ad-watch-reward",
            "deviceIds": ["phone-a"],
            "cadence": "1m",
            "timeWindow": "any",
            "mode": "safe",
            "enabled": True,
            "allowUnattended": True,
        }
    ]
    install_config(Path(paths.base_path), server_url, schedules, templates)
    scheduler = NoAutoDrainScheduler(paths, [])
    result = scheduler.tick()
    assert_true(len(result["enqueued"]) == 1, f"ad watch schedule did not enqueue: {result}")
    queue = read_json(Path(paths.launcher_dir) / "phone-agent-queue.json")
    item = queue["items"][0]
    assert_true(item["timeoutSec"] == 135, f"ad watch timeout should follow maxWatchSeconds + buffer: {item}")
    assert_true(item["maxWaitSec"] == 150, f"ad watch maxWaitSec should track timeoutSec: {item}")
    assert_true("最长等待 90 秒" in item["prompt"], f"ad watch variables were not rendered: {item['prompt']}")


def test_drain_sends_command(paths: TestPaths, server: FakePhoneServer) -> None:
    install_config(Path(paths.base_path), server.url, [])
    scheduler = NoAutoDrainScheduler(paths, [])
    result = scheduler.run_once("tpl-safe", ["phone-a"], "safe", True)
    assert_true(len(result["enqueued"]) == 1, f"send test did not enqueue: {result}")
    assert_true(scheduler._drain_lock.acquire(blocking=False), "test could not acquire drain lock")
    scheduler._drain_queue()
    queue = read_json(Path(paths.launcher_dir) / "phone-agent-queue.json")
    item = queue["items"][0]
    assert_true(item["status"] == "completed", f"drain did not complete queue item: {item}")
    paths_seen = [request["path"] for request in server.requests]
    assert_true("/api/lumi/security/pair" in paths_seen, f"pair request was not sent: {paths_seen}")
    assert_true("/api/lumi/agent/tasks" in paths_seen, f"agent task POST was not sent: {paths_seen}")
    task_posts = [request for request in server.requests if request["method"] == "POST" and request["path"] == "/api/lumi/agent/tasks"]
    assert_true(task_posts and "run smoke" in task_posts[0]["body"]["prompt"], f"prompt was not sent through CLI: {task_posts}")


def test_drain_retry_cap(paths: TestPaths, server: FakePhoneServer) -> None:
    install_config(Path(paths.base_path), server.url, [])
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    write_json(
        queue_path,
        {
            "schema": "openclaw.phone-agent.queue.v1",
            "items": [
                {
                    "id": "retry-capped",
                    "status": "error",
                    "attempts": 2,
                    "maxAttempts": 2,
                    "prompt": "must not send",
                    "mode": "safe",
                    "deviceId": "phone-a",
                    "timeoutSec": 30,
                    "maxRounds": 1,
                    "maxWaitSec": 3,
                    "pollMs": 500,
                }
            ],
        },
    )
    before = len(server.requests)
    script = Path(paths.base_path) / "scripts" / "openclaw-phone-agent.mjs"
    completed = subprocess.run(
        [paths.node_exe, str(script), "drain", "--json"],
        cwd=paths.base_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert_true(completed.returncode == 0, completed.stderr or completed.stdout)
    payload = json.loads(completed.stdout)
    assert_true(payload.get("count") == 0, f"retry-capped item should not be a drain candidate: {payload}")
    assert_true(len(server.requests) == before, "retry-capped drain still contacted phone server")


def test_drain_process_lock(paths: TestPaths, server: FakePhoneServer) -> None:
    install_config(Path(paths.base_path), server.url, [])
    queue_path = Path(paths.launcher_dir) / "phone-agent-queue.json"
    write_json(
        queue_path,
        {
            "schema": "openclaw.phone-agent.queue.v1",
            "items": [
                {
                    "id": "lock-held",
                    "status": "pending",
                    "attempts": 0,
                    "maxAttempts": 2,
                    "prompt": "must wait",
                    "mode": "safe",
                    "deviceId": "phone-a",
                    "timeoutSec": 30,
                    "maxRounds": 1,
                    "maxWaitSec": 3,
                    "pollMs": 500,
                }
            ],
        },
    )
    write_json(
        Path(f"{queue_path}.drain.lock"),
        {
            "schema": "openclaw.phone-agent.drain-lock.v1",
            "pid": os.getpid(),
            "createdAt": datetime.now().isoformat(),
        },
    )
    before = len(server.requests)
    script = Path(paths.base_path) / "scripts" / "openclaw-phone-agent.mjs"
    completed = subprocess.run(
        [paths.node_exe, str(script), "drain", "--json"],
        cwd=paths.base_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert_true(completed.returncode == 0, completed.stderr or completed.stdout)
    payload = json.loads(completed.stdout)
    assert_true(payload.get("lockBusy") is True, f"drain did not report lock busy: {payload}")
    assert_true(payload.get("count") == 0, f"locked drain should not process tasks: {payload}")
    assert_true(len(server.requests) == before, "locked drain still contacted phone server")


def main() -> None:
    server = FakePhoneServer().start()
    roots: list[Path] = []
    try:
        for test in (
            test_scheduler_stress,
            test_concurrent_tick_dedup,
            test_drain_running_blocks_queue_writes,
            test_external_drain_lock_blocks_scheduler_writes,
            test_dry_run_never_enqueues,
            test_queue_trim_preserves_active,
            test_guardrails,
            test_ad_watch_template_runtime,
        ):
            root, paths = make_root()
            roots.append(root)
            test(paths, server.url)
        root, paths = make_root()
        roots.append(root)
        test_drain_sends_command(paths, server)
        root, paths = make_root()
        roots.append(root)
        test_drain_retry_cap(paths, server)
        root, paths = make_root()
        roots.append(root)
        test_drain_process_lock(paths, server)
    finally:
        server.stop()
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)
    print("[phone-scheduler-smoke] ok stress=repeat-tick concurrent-dedup=true drain-lock=true external-drain-lock=true dry-run=true queue-trim=true guardrails=true drain-sent=true retry-cap=true process-lock=true")


if __name__ == "__main__":
    main()
