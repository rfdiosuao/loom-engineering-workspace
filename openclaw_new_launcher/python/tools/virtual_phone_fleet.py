"""Lightweight loopback-only APKClaw virtual phone fleet.

The simulator intentionally creates its own deterministic, test-only credentials.
It never reads launcher configuration, environment tokens, or real phone state.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import struct
import threading
import time
import zlib
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit


_EVENTS_PER_DEVICE = 128
_TASKS_PER_DEVICE = 32
_SCREENSHOTS_PER_DEVICE = 2
_MAX_BODY_BYTES = 1024 * 1024
_SCENARIOS = {"normal", "latency", "offline", "failure", "no_progress", "reconnect"}
_CONTROL_ACTIONS = {
    "tap",
    "swipe",
    "drag",
    "long_press",
    "input_text",
    "system_key",
    "open_app",
}


@dataclass(frozen=True)
class VirtualPhone:
    """Connection details for one generated test device."""

    device_id: str
    name: str
    base_url: str
    token: str


@dataclass
class _TaskState:
    task_id: str
    prompt: str
    status: str = "queued"
    progress: int = 0
    polls: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    error_code: str = ""


@dataclass
class _DeviceState:
    index: int
    phone: VirtualPhone
    scenario: str = "normal"
    latency_ms: int = 0
    reconnect_remaining: int = 0
    reconnected: bool = False
    screen_version: int = 0
    sequence: int = 0
    next_task: int = 1
    tasks: OrderedDict[str, _TaskState] = field(default_factory=OrderedDict)
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=_EVENTS_PER_DEVICE))
    screenshots: OrderedDict[int, tuple[bytes, str]] = field(default_factory=OrderedDict)


class VirtualPhoneFleet:
    """Run many APKClaw-compatible virtual phones in one service thread."""

    def __init__(self, device_count: int = 1, *, seed: int = 1, max_concurrency: int = 32):
        if not isinstance(device_count, int) or device_count < 1:
            raise ValueError("device_count must be at least 1")
        if not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.device_count = device_count
        self.seed = int(seed)
        self.max_concurrency = max_concurrency
        self._lock = threading.RLock()
        self._states: list[_DeviceState] = []
        self._states_by_port: dict[int, _DeviceState] = {}
        self._states_by_id: dict[str, _DeviceState] = {}
        for index in range(1, device_count + 1):
            device_id = f"virtual-phone-{index:03d}"
            phone = VirtualPhone(
                device_id=device_id,
                name=f"Virtual Phone {index:03d}",
                base_url="",
                token=self._generated_credential("token", device_id, "vf-test-only-", 24),
            )
            state = _DeviceState(index=index, phone=phone)
            self._states.append(state)
            self._states_by_id[device_id] = state

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._servers: list[asyncio.AbstractServer] = []
        self._handler_tasks: set[asyncio.Task[Any]] = set()
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._active_requests = 0
        self._peak_requests = 0

    @property
    def devices(self) -> tuple[VirtualPhone, ...]:
        with self._lock:
            return tuple(state.phone for state in self._states)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def service_thread_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def __enter__(self) -> "VirtualPhoneFleet":
        return self.start()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()

    def start(self) -> "VirtualPhoneFleet":
        if self._running:
            return self
        ready = threading.Event()
        startup_error: list[BaseException] = []

        def run_service() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._start_servers())
                self._running = True
            except BaseException as exc:  # pragma: no cover - platform bind errors
                startup_error.append(exc)
            finally:
                ready.set()
            if not startup_error:
                loop.run_forever()
            loop.close()

        self._thread = threading.Thread(target=run_service, name="virtual-phone-fleet", daemon=True)
        self._thread.start()
        if not ready.wait(timeout=10):
            raise RuntimeError("virtual phone fleet startup timed out")
        if startup_error:
            self._thread.join(timeout=2)
            raise RuntimeError("virtual phone fleet failed to start") from startup_error[0]
        return self

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if not loop or not thread:
            self._running = False
            return
        if thread.is_alive():
            future = asyncio.run_coroutine_threadsafe(self._stop_servers(), loop)
            future.result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
        self._running = False
        self._loop = None
        self._thread = None

    def identities(self) -> list[dict[str, str]]:
        """Return stable, non-secret identity material independent of listener ports."""
        with self._lock:
            return [
                {
                    "deviceId": state.phone.device_id,
                    "name": state.phone.name,
                    "credentialFingerprint": hashlib.sha256(state.phone.token.encode("ascii")).hexdigest()[:16],
                    "initialScreenHash": self._screen(state, version=0)[1],
                }
                for state in self._states
            ]

    def public_manifest(self) -> dict[str, Any]:
        """Describe listeners without exposing even the generated test credentials."""
        with self._lock:
            return {
                "testOnly": True,
                "binding": "loopback",
                "devices": [
                    {
                        "deviceId": state.phone.device_id,
                        "name": state.phone.name,
                        "baseUrl": state.phone.base_url,
                        "tokenAvailable": True,
                    }
                    for state in self._states
                ],
            }

    def set_scenario(self, device_id: str, scenario: str, **options: Any) -> None:
        if scenario not in _SCENARIOS:
            raise ValueError(f"unsupported scenario: {scenario}")
        with self._lock:
            state = self._state_for_id(device_id)
            state.scenario = scenario
            state.latency_ms = max(0, min(60_000, int(options.get("latency_ms", 0))))
            state.reconnect_remaining = (
                max(0, int(options.get("failures_before_reconnect", 1))) if scenario == "reconnect" else 0
            )
            state.reconnected = False

    def resource_snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "deviceCount": self.device_count,
                "listenerCount": len(self._servers),
                "serviceThreads": 1 if self.service_thread_alive else 0,
                "activeRequests": self._active_requests,
                "peakConcurrentRequests": self._peak_requests,
                "cachedScreenshotBytes": sum(
                    len(image) for state in self._states for image, _screen_hash in state.screenshots.values()
                ),
                "eventsPerDeviceLimit": _EVENTS_PER_DEVICE,
                "tasksPerDeviceLimit": _TASKS_PER_DEVICE,
            }

    async def _start_servers(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        for state in self._states:
            server = await asyncio.start_server(self._client_connected, "127.0.0.1", 0)
            socket = server.sockets[0]
            port = int(socket.getsockname()[1])
            state.phone = replace(state.phone, base_url=f"http://127.0.0.1:{port}")
            self._states_by_port[port] = state
            self._servers.append(server)

    async def _stop_servers(self) -> None:
        servers, self._servers = self._servers, []
        for server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers), return_exceptions=True)
        tasks = tuple(self._handler_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _client_connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self._serve_client(reader, writer))
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)

    async def _serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            assert self._semaphore is not None
            async with self._semaphore:
                with self._lock:
                    self._active_requests += 1
                    self._peak_requests = max(self._peak_requests, self._active_requests)
                try:
                    await self._handle_request(reader, writer)
                finally:
                    with self._lock:
                        self._active_requests -= 1
        except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.LimitOverrunError, asyncio.TimeoutError):
            await self._write_json(writer, 400, self._error("invalid_request", "Invalid HTTP request"))
            return
        if len(header_block) > 64 * 1024:
            await self._write_json(writer, 431, self._error("headers_too_large", "Headers too large"))
            return
        lines = header_block.decode("iso-8859-1").split("\r\n")
        try:
            method, target, _version = lines[0].split(" ", 2)
        except ValueError:
            await self._write_json(writer, 400, self._error("invalid_request", "Invalid request line"))
            return
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > _MAX_BODY_BYTES:
            await self._write_json(writer, 413, self._error("body_too_large", "Request body too large"))
            return
        body_bytes = await reader.readexactly(content_length) if content_length else b""
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._write_json(writer, 400, self._error("invalid_json", "Request body must be JSON"))
            return
        local_port = int(writer.get_extra_info("sockname")[1])
        state = self._states_by_port[local_port]
        status, payload = await self._route(state, method.upper(), target, headers, body)
        await self._write_json(writer, status, payload)

    async def _route(
        self,
        state: _DeviceState,
        method: str,
        target: str,
        headers: dict[str, str],
        body: Any,
    ) -> tuple[int, dict[str, Any]]:
        token = headers.get("x-agent-phone-token") or headers.get("x-apkclaw-token") or ""
        if not hmac.compare_digest(token, state.phone.token):
            return 401, self._error("unauthorized", "Invalid test phone credential")

        parsed = urlsplit(target)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        scenario_error = await self._apply_scenario(state)
        if scenario_error:
            return scenario_error

        if method == "GET" and path == "/api/device/status":
            return 200, self._success(self._device_status(state))
        if method == "GET" and path == "/api/agent/status":
            legacy = self._device_status(state)
            return 200, self._success(json.dumps({
                "taskRunning": legacy["taskRunning"],
                "agentInitialized": True,
                "llmConfigured": True,
                "accessibilityRunning": True,
            }, separators=(",", ":")))
        if method == "POST" and path == "/api/device/wake":
            return 200, self._success({"screenOn": True, "interactive": True})
        if method == "POST" and path == "/api/lumi/security/pair":
            launcher_id = str(body.get("launcherId") if isinstance(body, dict) else "").strip()
            if not launcher_id:
                return 400, self._error("invalid_launcher_id", "launcherId is required")
            secret = self._generated_credential("pair", f"{state.phone.device_id}:{launcher_id}", "vf-pair-test-only-", 32)
            return 200, self._success({"launcherId": launcher_id, "launcherSecret": secret, "testOnly": True})
        if method == "GET" and path == "/api/lumi/device/profile":
            return 200, self._success(self._device_profile(state))
        if method == "GET" and path == "/api/tool/screenshot":
            return 200, self._success(self._screenshot_response(state, self._query_first(query, "knownHash")))
        if method == "GET" and path in {"/api/tool/get_screen_info", "/api/tool/screen_tree"}:
            return 200, self._success(self._screen_info(state))
        if method == "POST" and path.startswith("/api/tool/"):
            action = path.rsplit("/", 1)[-1]
            if action in _CONTROL_ACTIONS:
                return 200, self._success(self._control(state, action, body))
        if method == "POST" and path in {"/api/lumi/agent/tasks", "/api/lumi/agent/execute_task"}:
            if not isinstance(body, dict) or not str(body.get("prompt") or "").strip():
                return 400, self._error("invalid_prompt", "prompt is required")
            task = self._create_task(state, str(body["prompt"]).strip())
            if path.endswith("execute_task"):
                for _step in range(4):
                    if task.status in {"success", "error"}:
                        break
                    self._advance_task(state, task)
                return 200, self._success(self._task_payload(task))
            return 202, self._success(self._task_payload(task))

        task_route = self._parse_task_route(path)
        if task_route:
            task_id, suffix = task_route
            task = state.tasks.get(task_id)
            if not task:
                return 404, self._error("task_not_found", "Virtual task not found")
            if method == "GET" and not suffix:
                self._advance_task(state, task)
                return 200, self._success(self._task_payload(task))
            if method == "GET" and suffix == "events":
                after_seq = self._query_int(query, "afterSeq", 0)
                events = [dict(event) for event in task.events if int(event["seq"]) > after_seq]
                return 200, self._success({
                    "taskId": task.task_id,
                    "events": events,
                    "progressLog": [self._progress_log(event) for event in events],
                    "lastSeq": task.events[-1]["seq"] if task.events else 0,
                })
            if method == "POST" and suffix == "cancel":
                if task.status not in {"success", "error", "cancelled"}:
                    task.status = "cancelled"
                    self._append_event(state, task, "task_cancelled", "Task cancelled", task.progress)
                return 200, self._success(self._task_payload(task))

        return 404, self._error("endpoint_not_found", f"Unsupported simulator endpoint: {path}")

    async def _apply_scenario(self, state: _DeviceState) -> tuple[int, dict[str, Any]] | None:
        with self._lock:
            scenario = state.scenario
            latency_ms = state.latency_ms
            if scenario == "reconnect" and state.reconnect_remaining > 0:
                state.reconnect_remaining -= 1
                return 503, self._error("connection_reset", "Simulated transient disconnect", retryable=True)
            if scenario == "reconnect" and not state.reconnected:
                state.reconnected = True
                self._append_event(state, None, "device_reconnected", "Device reconnected", 0)
        if scenario == "latency" and latency_ms:
            await asyncio.sleep(latency_ms / 1000)
        if scenario == "offline":
            return 503, self._error("device_offline", "Virtual device is offline", retryable=True)
        return None

    def _device_status(self, state: _DeviceState) -> dict[str, Any]:
        with self._lock:
            _image, screen_hash = self._screen(state)
            running = any(task.status in {"queued", "running"} for task in state.tasks.values())
            return {
                "deviceId": state.phone.device_id,
                "name": state.phone.name,
                "version": "virtual-1.0",
                "versionCode": 1,
                "online": True,
                "connectionState": "reconnected" if state.reconnected else "connected",
                "taskRunning": running,
                "agentInitialized": True,
                "llmConfigured": True,
                "accessibilityRunning": True,
                "screenshotSupported": True,
                "screenInfoSupported": True,
                "screenOn": True,
                "interactive": True,
                "deviceLocked": False,
                "batteryPercent": 60 + (state.index * 7 % 39),
                "screenHash": screen_hash,
                "serverPort": int(state.phone.base_url.rsplit(":", 1)[-1]),
            }

    def _device_profile(self, state: _DeviceState) -> dict[str, Any]:
        info = self._screen_info(state)
        return {
            "deviceId": state.phone.device_id,
            "model": "LOOM Virtual Phone",
            "manufacturer": "LOOM Test Lab",
            "currentScreen": info,
            "vision": {"recommended": False, "mode": "accessibility", "reason": "virtual_tree", "confidence": 1.0},
        }

    def _screen_info(self, state: _DeviceState) -> dict[str, Any]:
        with self._lock:
            _image, screen_hash = self._screen(state)
            return {
                "packageName": "com.loom.virtualphone",
                "title": f"Virtual Screen {state.screen_version}",
                "screenWidth": 1080,
                "screenHeight": 2400,
                "nodeCount": 3,
                "textNodeCount": 2,
                "clickableNodeCount": 1,
                "screenHash": screen_hash,
                "nodes": [
                    {"text": state.phone.name, "clickable": False},
                    {"text": f"State {state.screen_version}", "clickable": False},
                    {"text": "Continue", "clickable": True, "bounds": [360, 1800, 720, 1940]},
                ],
            }

    def _screenshot_response(self, state: _DeviceState, known_hash: str) -> dict[str, Any]:
        with self._lock:
            image, screen_hash = self._screen(state)
            captured_at = self._logical_time(state.screen_version)
        if known_hash and hmac.compare_digest(known_hash, screen_hash):
            return {"notModified": True, "screenHash": screen_hash, "capturedAt": captured_at}
        return {
            "mime": "image/png",
            "base64": base64.b64encode(image).decode("ascii"),
            "width": 8,
            "height": 16,
            "orientation": "portrait",
            "screenHash": screen_hash,
            "capturedAt": captured_at,
            "notModified": False,
        }

    def _control(self, state: _DeviceState, action: str, body: Any) -> dict[str, Any]:
        with self._lock:
            _before_image, before_hash = self._screen(state)
            state.screen_version += 1
            _after_image, after_hash = self._screen(state)
            event = self._append_event(state, None, "control_completed", f"{action} completed", 100)
        return {
            "action": action,
            "accepted": True,
            "changed": True,
            "beforeHash": before_hash,
            "afterHash": after_hash,
            "screenHash": after_hash,
            "seq": event["seq"],
            "request": self._safe_control_request(body),
        }

    def _create_task(self, state: _DeviceState, prompt: str) -> _TaskState:
        with self._lock:
            task_id = f"{state.phone.device_id}-task-{state.next_task:04d}"
            state.next_task += 1
            task = _TaskState(task_id=task_id, prompt=prompt[:2000])
            state.tasks[task_id] = task
            while len(state.tasks) > _TASKS_PER_DEVICE:
                state.tasks.popitem(last=False)
            self._append_event(state, task, "task_queued", "Task queued", 0)
            return task

    def _advance_task(self, state: _DeviceState, task: _TaskState) -> None:
        with self._lock:
            if task.status in {"success", "error", "cancelled"}:
                return
            task.polls += 1
            if task.polls == 1:
                task.status = "running"
                task.progress = 20
                self._append_event(state, task, "task_running", "Task started", task.progress)
                return
            if state.scenario == "no_progress":
                return
            if state.scenario == "failure" and task.polls >= 3:
                task.status = "error"
                task.error_code = "simulated_task_failure"
                self._append_event(state, task, "task_failed", "Task failed by scenario", task.progress)
                return
            schedule = {2: 55, 3: 85, 4: 100}
            task.progress = schedule.get(task.polls, 100)
            if task.progress >= 100:
                task.status = "success"
                self._append_event(state, task, "task_completed", "Task completed", 100)
            else:
                self._append_event(state, task, "task_progress", f"Task progress {task.progress}%", task.progress)

    def _task_payload(self, task: _TaskState) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "taskId": task.task_id,
            "id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "currentStep": task.status,
            "events": [dict(event) for event in task.events],
            "progressLog": [self._progress_log(event) for event in task.events],
            "queue": {"queueMs": 0, "queueDepth": 0, "cancelRequested": task.status == "cancelled"},
        }
        if task.status == "success":
            payload["result"] = {"answer": f"Completed: {task.prompt}", "success": True}
        if task.error_code:
            payload.update({"errorCode": task.error_code, "error": "Simulated task failure", "retryable": True})
        return payload

    def _append_event(
        self,
        state: _DeviceState,
        task: _TaskState | None,
        event_type: str,
        message: str,
        progress: int,
    ) -> dict[str, Any]:
        state.sequence += 1
        event = {
            "seq": state.sequence,
            "type": event_type,
            "deviceId": state.phone.device_id,
            "taskId": task.task_id if task else "",
            "message": message,
            "progress": progress,
            "time": self._logical_time(state.sequence),
        }
        state.events.append(event)
        if task is not None:
            task.events.append(event)
            if len(task.events) > 16:
                del task.events[:-16]
        return event

    def _screen(self, state: _DeviceState, *, version: int | None = None) -> tuple[bytes, str]:
        target_version = state.screen_version if version is None else version
        cached = state.screenshots.get(target_version)
        if cached:
            state.screenshots.move_to_end(target_version)
            return cached
        digest = hashlib.sha256(
            f"{self.seed}:{state.phone.device_id}:{target_version}".encode("ascii")
        ).digest()
        image = self._png(8, 16, digest[0], digest[1], digest[2])
        screen_hash = hashlib.sha256(image).hexdigest()
        state.screenshots[target_version] = (image, screen_hash)
        while len(state.screenshots) > _SCREENSHOTS_PER_DEVICE:
            state.screenshots.popitem(last=False)
        return image, screen_hash

    @staticmethod
    def _png(width: int, height: int, red: int, green: int, blue: int) -> bytes:
        signature = b"\x89PNG\r\n\x1a\n"

        def chunk(kind: bytes, data: bytes) -> bytes:
            checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

        row = b"\x00" + bytes((red, green, blue)) * width
        pixels = row * height
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels, 9)) + chunk(b"IEND", b"")

    def _generated_credential(self, purpose: str, identity: str, prefix: str, length: int) -> str:
        material = hashlib.sha256(f"virtual-fleet:{self.seed}:{purpose}:{identity}".encode("utf-8")).hexdigest()
        return prefix + material[:length]

    def _state_for_id(self, device_id: str) -> _DeviceState:
        try:
            return self._states_by_id[device_id]
        except KeyError as exc:
            raise KeyError(f"unknown virtual device: {device_id}") from exc

    @staticmethod
    def _parse_task_route(path: str) -> tuple[str, str] | None:
        prefix = "/api/lumi/agent/tasks/"
        if not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/")
        if not parts[0]:
            return None
        return parts[0], parts[1] if len(parts) > 1 else ""

    @staticmethod
    def _query_first(query: dict[str, list[str]], key: str) -> str:
        values = query.get(key) or query.get(key.lower()) or []
        return str(values[0]) if values else ""

    @staticmethod
    def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
        try:
            return int(VirtualPhoneFleet._query_first(query, key) or default)
        except ValueError:
            return default

    @staticmethod
    def _safe_control_request(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {}
        allowed = {"x", "y", "startX", "startY", "endX", "endY", "duration", "key", "packageName"}
        return {str(key): value for key, value in body.items() if key in allowed and isinstance(value, (str, int, float, bool))}

    @staticmethod
    def _progress_log(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "seq": event["seq"],
            "text": event["message"],
            "progress": event["progress"],
            "time": event["time"],
        }

    @staticmethod
    def _logical_time(offset: int) -> str:
        value = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=max(0, offset))
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _success(data: Any) -> dict[str, Any]:
        return {"success": True, "data": data, "error": None}

    @staticmethod
    def _error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
        return {
            "success": False,
            "data": None,
            "error": message,
            "errorCode": code,
            "retryable": retryable,
        }

    @staticmethod
    async def _write_json(writer: asyncio.StreamWriter, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reason = {
            200: "OK",
            202: "Accepted",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            413: "Payload Too Large",
            431: "Request Header Fields Too Large",
            503: "Service Unavailable",
        }.get(status, "OK")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-store\r\n\r\n"
        ).encode("ascii")
        writer.write(header + body)
        await writer.drain()


def _parse_scenario(value: str) -> tuple[str, str]:
    try:
        device_id, scenario = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scenario must be DEVICE_ID=SCENARIO") from exc
    if scenario not in _SCENARIOS:
        raise argparse.ArgumentTypeError(f"scenario must be one of: {', '.join(sorted(_SCENARIOS))}")
    return device_id, scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a loopback-only APKClaw virtual phone fleet")
    parser.add_argument("--devices", type=int, default=10, help="number of virtual phones")
    parser.add_argument("--seed", type=int, default=1, help="deterministic identity seed")
    parser.add_argument("--max-concurrency", type=int, default=32, help="shared request concurrency bound")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run; 0 waits for Ctrl+C")
    parser.add_argument("--scenario", action="append", type=_parse_scenario, default=[])
    args = parser.parse_args(argv)

    try:
        with VirtualPhoneFleet(args.devices, seed=args.seed, max_concurrency=args.max_concurrency) as fleet:
            for device_id, scenario in args.scenario:
                fleet.set_scenario(device_id, scenario)
            print(json.dumps(fleet.public_manifest(), ensure_ascii=False, indent=2))
            print("Generated credentials are test-only and intentionally omitted from CLI output.")
            if args.duration > 0:
                time.sleep(args.duration)
            else:
                while True:
                    time.sleep(1)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
