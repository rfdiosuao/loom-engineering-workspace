"""Matrix control plane for LOOM phone devices.

The control plane owns registry, orchestration metadata, events, and
experience summaries. Single-device execution remains delegated to the phone
Bridge/APKClaw layer.
"""

from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict

from core.paths import AppPaths
from core.feishu_integration import FeishuAcquisitionIntegration


Json = Dict[str, Any]
DEFAULT_PHONE_MODEL = "qwen3.7-plus"
MATRIX_EVENT_FILE_MAX_BYTES = 5 * 1024 * 1024
MATRIX_EVENT_ARCHIVE_COUNT = 3
MATRIX_EVENT_TAIL_BYTES = 4 * 1024 * 1024
MATRIX_RUNTIME_DEDUPE_WINDOW_MS = 15_000
MATRIX_PRESENCE_UNSTABLE_MS = 7_500
MATRIX_PRESENCE_OFFLINE_MS = 15_000
MATRIX_DISPATCH_SCHEMA = "loom.matrix.dispatch.v2"
MATRIX_CANONICAL_MAX_CONCURRENCY = 8
MATRIX_CANONICAL_MAX_RETRY_BUDGET = 10
MATRIX_LEASE_TTL_SECONDS = 30
MATRIX_CONTROL_COMMAND_LIMIT = 500

_CANONICAL_TEMPLATE_EXECUTION = {
    "screen_read_v1": ("read-screen", "Read the current screen and return a structured result."),
    "read-screen": ("read-screen", "Read the current screen and return a structured result."),
    "screen-summary": ("screen-summary", "Read the current screen and summarize the visible content."),
    "open-settings": ("open-settings", "Open Android Settings."),
    "refresh-screen": ("refresh-screen", "Refresh the current screen."),
}

_STATE_STREAM_EVENT_TYPES = {
    "phone.events.heartbeat",
    "phone.events.hello",
    "phone.events.snapshot",
    "phone.snapshot",
}

_VOLATILE_EVENT_KEYS = {
    "updatedAt",
    "heartbeatAt",
    "lastEventAt",
    "streamLatencyMs",
    "timestamp",
    "eventId",
    "deduplicated",
}

SENSITIVE_KEYS = {
    "token",
    "secret",
    "password",
    "apiKey",
    "api_key",
    "accessToken",
    "launcherSecret",
    "lumiLauncherSecret",
    "lumiLauncherId",
}

OUTREACH_MARKERS = (
    "批量私信",
    "私信所有",
    "自动私信",
    "批量评论",
    "自动评论",
    "自动回复",
    "批量触达",
    "群发",
    "骚扰",
)

_MATRIX_STATE_LOCK = threading.RLock()
_MATRIX_LOCK_DEPTH = threading.local()
_DEVICE_TASK_TERMINAL_STATES = frozenset({"succeeded", "failed", "needs_human", "cancelled"})
_DEVICE_TASK_CANCELLABLE_STATES = frozenset({"queued", "preflight", "running", "retrying", "paused"})
_DEVICE_RUNTIME_FIELDS = frozenset(
    {
        "online",
        "heartbeatAt",
        "lastEventAt",
        "streamStatus",
        "streamLatencyMs",
        "currentTaskId",
        "busy",
        "currentScreenSummary",
        "screenSummary",
        "failureCount",
        "lastResult",
        "currentPackage",
        "foregroundApp",
        "accessibilityRunning",
        "screenOn",
        "deviceLocked",
        "runningTaskCount",
        "currentStep",
        "headline",
        "needsCodex",
        "progressLog",
        "latestProgressText",
    }
)


def _matrix_state_guard(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        with _MATRIX_STATE_LOCK:
            instance = args[0]
            lock_path = os.path.join(instance.paths.launcher_dir, ".matrix-state.lock")
            depths = getattr(_MATRIX_LOCK_DEPTH, "paths", {})
            depth = int(depths.get(lock_path) or 0)
            if depth:
                depths[lock_path] = depth + 1
                _MATRIX_LOCK_DEPTH.paths = depths
                try:
                    return method(*args, **kwargs)
                finally:
                    depths[lock_path] -= 1
            with _interprocess_file_lock(lock_path):
                depths[lock_path] = 1
                _MATRIX_LOCK_DEPTH.paths = depths
                try:
                    return method(*args, **kwargs)
                finally:
                    depths.pop(lock_path, None)

    return guarded


@contextmanager
def _interprocess_file_lock(path: str, timeout_sec: float = 15.0):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        fd = -1
    if fd >= 0:
        try:
            os.write(fd, b"\0")
        finally:
            os.close(fd)
    deadline = time.monotonic() + max(1.0, timeout_sec)
    while True:
        try:
            if os.path.getsize(path) >= 1:
                break
        except OSError:
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Matrix state lock initialization timeout: {path}")
        time.sleep(0.01)
    handle = open(path, "r+b")
    try:
        while True:
            try:
                _lock_file_handle(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Matrix state lock timeout: {path}")
                time.sleep(0.02)
        try:
            yield
        finally:
            _unlock_file_handle(handle)
    finally:
        handle.close()


def _lock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class MatrixSafetyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class MatrixTargetError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class MatrixControlPlane:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    @property
    def devices_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-devices.json")

    @property
    def phone_devices_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "phone-agents.json")

    @property
    def tasks_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-tasks.json")

    @property
    def events_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-events.jsonl")

    @property
    def event_sequence_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-event-sequence.json")

    @property
    def experience_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-experience.jsonl")

    @property
    def leads_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-leads.jsonl")

    @property
    def acquisition_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-acquisition.json")

    @property
    def leases_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-device-leases.json")

    @property
    def control_commands_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "matrix-control-commands.json")

    @_matrix_state_guard
    def register_device(self, raw: Json) -> Json:
        devices = self._load_registered_devices()
        device_id = _device_id(raw.get("deviceId") or raw.get("id") or raw.get("name") or "phone-1")
        existing = next((item for item in devices if item.get("deviceId") == device_id), {})
        raw_groups = raw.get("groups") if isinstance(raw.get("groups"), list) else None
        groups = raw_groups if raw_groups is not None else list(existing.get("groups") or [])
        group = str(
            raw.get("group")
            or existing.get("group")
            or (groups[0] if groups else "")
            or "default"
        ).strip() or "default"
        has_runtime_update = any(key in raw for key in _DEVICE_RUNTIME_FIELDS)
        incoming_observed_at = _clip(
            raw.get("presenceObservedAt")
            or raw.get("observedAt")
            or raw.get("lastEventAt")
            or raw.get("heartbeatAt")
            or (_now_iso() if has_runtime_update else ""),
            64,
        )
        existing_observed_at = _clip(
            existing.get("presenceObservedAt")
            or existing.get("lastEventAt")
            or existing.get("heartbeatAt"),
            64,
        )
        incoming_epoch_ms = _timestamp_epoch_ms(incoming_observed_at)
        existing_epoch_ms = _timestamp_epoch_ms(existing_observed_at)
        accept_runtime_update = (
            not existing
            or incoming_epoch_ms < 0
            or existing_epoch_ms < 0
            or incoming_epoch_ms >= existing_epoch_ms
        )
        runtime = raw if accept_runtime_update else {}

        def runtime_value(key: str, default: Any = None) -> Any:
            return runtime[key] if key in runtime else existing.get(key, default)

        progress_log = _matrix_progress_log(
            runtime.get("progressLog")
            if isinstance(runtime.get("progressLog"), list)
            else existing.get("progressLog")
        )
        if "currentScreenSummary" in runtime:
            current_screen_summary = runtime.get("currentScreenSummary")
        elif "screenSummary" in runtime:
            current_screen_summary = runtime.get("screenSummary")
        else:
            current_screen_summary = existing.get("currentScreenSummary")
        if "latestProgressText" in runtime:
            latest_progress_text = runtime.get("latestProgressText")
        elif "progressLog" in runtime:
            latest_progress_text = progress_log[-1].get("text") if progress_log else ""
        else:
            latest_progress_text = existing.get("latestProgressText")
        device = {
            **existing,
            "deviceId": device_id,
            "name": _clip(raw.get("name") or existing.get("name") or device_id, 80),
            "group": group,
            "groups": sorted({group, *[_clip(item, 80) for item in groups if str(item or "").strip()]}),
            "online": bool(runtime_value("online", False)),
            "heartbeatAt": _clip(runtime_value("heartbeatAt", incoming_observed_at), 64),
            "presenceObservedAt": incoming_observed_at if accept_runtime_update else existing_observed_at,
            "currentTaskId": _clip(runtime_value("currentTaskId", ""), 80),
            "busy": bool(runtime_value("busy", False)),
            "currentScreenSummary": _clip(current_screen_summary, 300),
            "failureCount": _int(runtime_value("failureCount"), _int(existing.get("failureCount"), 0)),
            "model": _clip(raw.get("model") or existing.get("model") or DEFAULT_PHONE_MODEL, 120),
            "lastResult": _clip(runtime_value("lastResult", ""), 300),
            "lastEventAt": _clip(runtime_value("lastEventAt", ""), 64),
            "streamStatus": _clip(runtime_value("streamStatus", ""), 40),
            "streamLatencyMs": _int(runtime_value("streamLatencyMs"), _int(existing.get("streamLatencyMs"), 0)),
            "currentPackage": _clip(runtime_value("currentPackage", ""), 160),
            "foregroundApp": _clip(runtime_value("foregroundApp", ""), 120),
            "accessibilityRunning": _optional_bool(runtime_value("accessibilityRunning"), existing.get("accessibilityRunning")),
            "screenOn": _optional_bool(runtime_value("screenOn"), existing.get("screenOn")),
            "deviceLocked": _optional_bool(runtime_value("deviceLocked"), existing.get("deviceLocked")),
            "runningTaskCount": _int(runtime_value("runningTaskCount"), _int(existing.get("runningTaskCount"), 0)),
            "currentStep": _safe_lead_summary(runtime_value("currentStep", ""), limit=160),
            "headline": _safe_lead_summary(runtime_value("headline", ""), limit=240),
            "needsCodex": bool(runtime_value("needsCodex", False)),
            "progressLog": progress_log,
            "latestProgressText": _safe_lead_summary(latest_progress_text, limit=240),
            "updatedAt": _now_iso(),
        }
        next_devices = [item for item in devices if item.get("deviceId") != device_id]
        next_devices.append(device)
        self._write_json(self.devices_path, {"schema": "loom.matrix.devices.v1", "devices": next_devices})
        return _public_device(device)

    @_matrix_state_guard
    def unregister_device(self, device_id: str) -> Json:
        safe_id = _device_id(device_id)
        devices = self._load_registered_devices()
        next_devices = [item for item in devices if item.get("deviceId") != safe_id]
        removed = len(next_devices) != len(devices)
        if removed:
            self._write_json(self.devices_path, {"schema": "loom.matrix.devices.v1", "devices": next_devices})
        return {"removed": removed, "deviceId": safe_id}

    def status(self, campaign_id: str | None = None) -> Json:
        devices = [_public_device(item) for item in self._load_devices()]
        tasks = self._load_tasks().get("campaigns", [])
        selected_campaign_id = str(campaign_id or "").strip()
        campaigns = (
            [
                item
                for item in tasks
                if isinstance(item, dict)
                and str(item.get("campaignId") or "") == selected_campaign_id
            ]
            if selected_campaign_id
            else tasks[-20:]
        )
        return {
            "schema": "loom.matrix.v1",
            "updatedAt": _now_iso(),
            "devices": devices,
            "summary": {
                "total": len(devices),
                "online": sum(1 for item in devices if item.get("online")),
                "busy": sum(1 for item in devices if item.get("busy")),
                "failed": sum(1 for item in devices if int(item.get("failureCount") or 0) > 0),
            },
            "campaigns": _redact_json(campaigns),
        }

    @_matrix_state_guard
    def dispatch(self, raw: Json) -> Json:
        if _is_canonical_dispatch(raw):
            return self._dispatch_canonical(raw)
        return self._dispatch_legacy(raw)

    def _dispatch_legacy(self, raw: Json) -> Json:
        target = raw
        if "target" in raw:
            nested_target = raw.get("target")
            top_level_selectors = sorted(
                key
                for key in ("deviceIds", "devices", "deviceId", "groups", "group", "allOnline")
                if key in raw
            )
            if not isinstance(nested_target, dict) or top_level_selectors:
                detail = f": {', '.join(top_level_selectors)}" if top_level_selectors else ""
                raise MatrixTargetError(
                    "matrix_invalid_target",
                    f"Use either target or one top-level Matrix selector, never both{detail}",
                )
            target = nested_target
        prompt = _clip(raw.get("prompt"), 2000)
        title = _clip(raw.get("title") or prompt[:40] or "Matrix task", 120)
        confirmed = _truthy(raw.get("confirmed"))
        self._check_safety(prompt, confirmed=confirmed)
        profile = _profile(raw.get("profile"))
        mode = _mode(raw.get("mode"))
        template = _template(raw.get("template") or raw.get("templateId") or _template_from_prompt(prompt))
        action = _direct_action(raw.get("action") or raw.get("directAction"), prompt)
        layer = _execution_layer(mode=mode, action=action, template=template, prompt=prompt)
        devices = self._target_devices(target)
        now = _now_iso()
        campaign_id = f"campaign_{uuid.uuid4().hex[:12]}"
        mission_id = f"mission_{uuid.uuid4().hex[:12]}"
        device_tasks = []
        retry_of = _clip(raw.get("retryOf") or raw.get("retry_of"), 80)
        self._append_event("queued", campaign_id, mission_id, "", "", "任务已进入 Matrix 队列")
        for device in devices:
            device_task_id = f"deviceTask_{uuid.uuid4().hex[:12]}"
            device_tasks.append(
                {
                    "deviceTaskId": device_task_id,
                    "deviceId": device["deviceId"],
                    "status": "queued",
                    "executionLayer": layer,
                    "mode": mode,
                    "profile": profile,
                    "template": template,
                    "directAction": action,
                    "currentStep": _steps_for_layer(layer)[0]["stepId"],
                    "steps": _steps_for_layer(layer),
                    "createdAt": now,
                    "updatedAt": now,
                    "promptHash": _hash_prompt(prompt),
                }
            )
            self._append_event("assigned", campaign_id, mission_id, device_task_id, device["deviceId"], f"已分配到 {device['deviceId']}")
        campaign = {
            "campaignId": campaign_id,
            "title": title,
            "status": "queued",
            "safety": {"confirmationRequired": _needs_confirmation(prompt), "confirmed": confirmed},
            "retryOf": retry_of,
            "retryCount": _int(raw.get("retryCount"), 0),
            "retryBody": _retry_body_snapshot(
                prompt=prompt,
                mode=mode,
                profile=profile,
                template=template,
                action=action,
                devices=devices,
            ),
            "createdAt": now,
            "updatedAt": now,
            "missions": [
                {
                    "missionId": mission_id,
                    "status": "queued",
                    "createdAt": now,
                    "updatedAt": now,
                    "deviceTasks": device_tasks,
                }
            ],
        }
        tasks = self._load_tasks()
        campaigns = tasks.get("campaigns") if isinstance(tasks.get("campaigns"), list) else []
        campaigns.append(campaign)
        self._write_json(self.tasks_path, {"schema": "loom.matrix.tasks.v1", "campaigns": campaigns[-500:]})
        return _redact_json(campaign)

    def _dispatch_canonical(self, raw: Json) -> Json:
        allowed_request_keys = {
            "schema",
            "campaignId",
            "concurrency",
            "mode",
            "profile",
            "deviceAssignments",
        }
        extra_request_keys = sorted(set(raw) - allowed_request_keys)
        if raw.get("schema") != MATRIX_DISPATCH_SCHEMA or extra_request_keys:
            detail = f": {', '.join(extra_request_keys)}" if extra_request_keys else ""
            raise MatrixTargetError(
                "matrix_invalid_dispatch",
                f"Canonical Matrix dispatch requires the exact {MATRIX_DISPATCH_SCHEMA} schema{detail}",
            )

        campaign_id = _canonical_id(raw.get("campaignId"), field="campaignId")
        concurrency = _canonical_int(
            raw.get("concurrency"),
            field="concurrency",
            minimum=1,
            maximum=MATRIX_CANONICAL_MAX_CONCURRENCY,
        )
        mode = _canonical_choice(raw.get("mode"), field="mode", default="safe", values={"observe", "safe", "full"})
        profile = _canonical_choice(
            raw.get("profile"),
            field="profile",
            default="fast",
            values={"fast", "standard", "deep"},
        )
        raw_assignments = raw.get("deviceAssignments")
        if not isinstance(raw_assignments, list) or not raw_assignments:
            raise MatrixTargetError("matrix_invalid_dispatch", "deviceAssignments must contain at least one assignment")
        if len(raw_assignments) > 100:
            raise MatrixTargetError("matrix_unsupported_assignment", "At most 100 canonical assignments are supported")

        allowed_assignment_keys = {
            "assignmentId",
            "deviceId",
            "prompt",
            "templateId",
            "input",
            "timeoutSec",
            "retryBudget",
        }
        assignments: list[Json] = []
        assignment_ids: set[str] = set()
        device_ids: set[str] = set()
        for index, raw_assignment in enumerate(raw_assignments):
            if not isinstance(raw_assignment, dict):
                raise MatrixTargetError("matrix_invalid_dispatch", f"deviceAssignments[{index}] must be an object")
            extra_assignment_keys = sorted(set(raw_assignment) - allowed_assignment_keys)
            if extra_assignment_keys:
                raise MatrixTargetError(
                    "matrix_invalid_dispatch",
                    f"deviceAssignments[{index}] has unsupported fields: {', '.join(extra_assignment_keys)}",
                )
            assignment_id = _canonical_id(raw_assignment.get("assignmentId"), field=f"deviceAssignments[{index}].assignmentId")
            device_id = _canonical_id(raw_assignment.get("deviceId"), field=f"deviceAssignments[{index}].deviceId")
            if assignment_id in assignment_ids:
                raise MatrixTargetError("matrix_invalid_dispatch", f"Duplicate assignmentId: {assignment_id}")
            if device_id in device_ids:
                raise MatrixTargetError("matrix_unsupported_assignment", f"Only one assignment per device is supported: {device_id}")

            prompt_value = raw_assignment.get("prompt")
            template_value = raw_assignment.get("templateId")
            prompt = _canonical_optional_text(
                prompt_value,
                field=f"deviceAssignments[{index}].prompt",
                maximum=2000,
            )
            template_id = _canonical_optional_text(
                template_value,
                field=f"deviceAssignments[{index}].templateId",
                maximum=80,
            )
            if not prompt and not template_id:
                raise MatrixTargetError(
                    "matrix_invalid_dispatch",
                    f"deviceAssignments[{index}] requires prompt or templateId",
                )
            execution_template = ""
            if template_id:
                template_contract = _CANONICAL_TEMPLATE_EXECUTION.get(template_id)
                if not template_contract:
                    raise MatrixTargetError(
                        "matrix_unsupported_assignment",
                        f"Unsupported canonical templateId: {template_id}",
                    )
                execution_template, template_prompt = template_contract
                if not prompt:
                    prompt = template_prompt
            input_value = raw_assignment.get("input")
            if not isinstance(input_value, dict):
                raise MatrixTargetError(
                    "matrix_invalid_dispatch",
                    f"deviceAssignments[{index}].input must be an object",
                )
            timeout_sec = _canonical_int(
                raw_assignment.get("timeoutSec"),
                field=f"deviceAssignments[{index}].timeoutSec",
                minimum=30,
                maximum=1200,
            )
            retry_budget = _canonical_int(
                raw_assignment.get("retryBudget"),
                field=f"deviceAssignments[{index}].retryBudget",
                minimum=0,
                maximum=MATRIX_CANONICAL_MAX_RETRY_BUDGET,
            )
            self._check_safety(prompt, confirmed=False)
            assignment_ids.add(assignment_id)
            device_ids.add(device_id)
            assignments.append(
                {
                    "assignmentId": assignment_id,
                    "deviceId": device_id,
                    "prompt": prompt,
                    "templateId": template_id,
                    "template": execution_template,
                    "input": dict(input_value),
                    "timeoutSec": timeout_sec,
                    "retryBudget": retry_budget,
                }
            )

        tasks = self._load_tasks()
        campaigns = tasks.get("campaigns") if isinstance(tasks.get("campaigns"), list) else []
        if any(str(item.get("campaignId") or "") == campaign_id for item in campaigns if isinstance(item, dict)):
            raise MatrixTargetError("matrix_campaign_exists", f"campaignId already exists: {campaign_id}")
        self._exact_canonical_devices([assignment["deviceId"] for assignment in assignments])

        now = _now_iso()
        mission_id = f"mission_{uuid.uuid4().hex[:12]}"
        device_tasks: list[Json] = []
        for assignment in assignments:
            prompt = assignment["prompt"]
            template = assignment["template"]
            layer = _execution_layer(mode=mode, action="", template=template, prompt=prompt)
            steps = _steps_for_layer(layer)
            device_task_id = f"deviceTask_{uuid.uuid4().hex[:12]}"
            device_task = {
                **assignment,
                "deviceTaskId": device_task_id,
                "jobId": None,
                "status": "queued",
                "attempt": 0,
                "executionLayer": layer,
                "mode": mode,
                "profile": profile,
                "directAction": "",
                "currentStep": steps[0]["stepId"],
                "steps": steps,
                "createdAt": now,
                "updatedAt": now,
                "promptHash": _hash_prompt(prompt),
            }
            device_tasks.append(device_task)

        # Validation and exact-device resolution are complete before the first state mutation.
        self._append_event("queued", campaign_id, mission_id, "", "", "Canonical Matrix task queued")
        for device_task in device_tasks:
            device_id = str(device_task["deviceId"])
            assignment_id = str(device_task["assignmentId"])
            device_task_id = str(device_task["deviceTaskId"])
            self._append_event(
                "assigned",
                campaign_id,
                mission_id,
                device_task_id,
                device_id,
                f"Assigned to {device_id}",
                assignment_id=assignment_id,
            )

        title_seed = str(device_tasks[0].get("prompt") or device_tasks[0].get("templateId") or campaign_id)
        campaign = {
            "requestSchema": MATRIX_DISPATCH_SCHEMA,
            "campaignId": campaign_id,
            "title": _clip(title_seed, 120),
            "status": "queued",
            "concurrency": concurrency,
            "safety": {"confirmationRequired": False, "confirmed": False},
            "createdAt": now,
            "updatedAt": now,
            "missions": [
                {
                    "missionId": mission_id,
                    "status": "queued",
                    "createdAt": now,
                    "updatedAt": now,
                    "deviceTasks": device_tasks,
                }
            ],
        }
        campaigns.append(campaign)
        self._write_json(self.tasks_path, {"schema": "loom.matrix.tasks.v1", "campaigns": campaigns[-500:]})
        return _redact_json(campaign)

    def _exact_canonical_devices(self, device_ids: list[str]) -> list[Json]:
        devices = [_public_device(item) for item in self._load_devices()]
        devices_by_id = {str(device.get("deviceId") or ""): device for device in devices}
        missing = [device_id for device_id in device_ids if device_id not in devices_by_id]
        if missing:
            raise MatrixTargetError("matrix_target_not_found", f"Canonical devices not found: {', '.join(missing)}")
        offline = [device_id for device_id in device_ids if not devices_by_id[device_id].get("online")]
        if offline:
            raise MatrixTargetError("matrix_target_offline", f"Canonical devices are offline: {', '.join(offline)}")
        return [devices_by_id[device_id] for device_id in device_ids]

    @_matrix_state_guard
    def retry_failed(self, campaign_id: str, raw: Json | None = None) -> Json:
        body = raw if isinstance(raw, dict) else {}
        tasks = self._load_tasks()
        campaign = next((item for item in tasks.get("campaigns", []) if item.get("campaignId") == campaign_id), None)
        if not isinstance(campaign, dict):
            raise MatrixTargetError("matrix_campaign_not_found", f"Matrix campaign not found: {campaign_id}")
        failed = []
        indeterminate = []
        for mission in campaign.get("missions", []):
            for device_task in mission.get("deviceTasks", []):
                if not isinstance(device_task, dict):
                    continue
                if (
                    device_task.get("outcomeIndeterminate") is True
                    or device_task.get("executionMayContinue") is True
                    or device_task.get("status") == "needs_human"
                ):
                    indeterminate.append(device_task)
                elif device_task.get("status") == "failed":
                    failed.append(device_task)
        if indeterminate:
            return {
                "retried": False,
                "campaignId": campaign_id,
                "code": "matrix_retry_blocked_indeterminate",
                "reason": (
                    "Execution outcome is indeterminate and may still continue. "
                    "Check the actual device and task status before retrying."
                ),
                "retryable": False,
                "outcomeIndeterminate": True,
                "executionMayContinue": any(
                    item.get("executionMayContinue") is True for item in indeterminate
                ),
                "deviceTaskIds": [
                    str(item.get("deviceTaskId") or "")
                    for item in indeterminate
                    if str(item.get("deviceTaskId") or "")
                ],
            }
        if not failed:
            return {
                "retried": False,
                "campaignId": campaign_id,
                "code": "matrix_retry_not_available",
                "reason": (
                    "No failed device tasks are available to retry. "
                    "Refresh the campaign status and inspect its device tasks."
                ),
                "retryable": True,
            }
        failure_reasons = [
            {
                "deviceTaskId": str(item.get("deviceTaskId") or ""),
                "deviceId": str(item.get("deviceId") or ""),
                "code": str(item.get("failureCode") or ""),
                "reason": str(
                    item.get("failureReason")
                    or "Review the device task logs before retrying."
                ),
            }
            for item in failed
        ]
        if campaign.get("requestSchema") == MATRIX_DISPATCH_SCHEMA:
            retry_payload: Json = {
                "schema": MATRIX_DISPATCH_SCHEMA,
                "campaignId": f"retry_{uuid.uuid4().hex[:16]}",
                "concurrency": max(
                    1,
                    min(int(campaign.get("concurrency") or 1), len(failed), MATRIX_CANONICAL_MAX_CONCURRENCY),
                ),
                "mode": str(failed[0].get("mode") or "safe"),
                "profile": str(failed[0].get("profile") or "fast"),
                "deviceAssignments": [
                    {
                        "assignmentId": str(item.get("assignmentId") or ""),
                        "deviceId": str(item.get("deviceId") or ""),
                        "prompt": str(item.get("prompt") or ""),
                        **({"templateId": str(item.get("templateId"))} if item.get("templateId") else {}),
                        "input": dict(item.get("input") or {}),
                        "timeoutSec": int(item.get("timeoutSec") or 0),
                        "retryBudget": int(item.get("retryBudget") or 0),
                    }
                    for item in failed
                ],
            }
            task = self.dispatch(retry_payload)
            self._append_event(
                "retry",
                campaign_id,
                "",
                "",
                "",
                f"Canonical retry queued: {task.get('campaignId')}",
            )
            return {
                "retried": True,
                "retryOf": campaign_id,
                "task": task,
                "dispatchBody": _redact_json(retry_payload),
                "failureReasons": _redact_json(failure_reasons),
            }
        retry_body = campaign.get("retryBody") if isinstance(campaign.get("retryBody"), dict) else {}
        prompt = _clip(body.get("prompt") or retry_body.get("promptPreview") or campaign.get("title") or "重试手机任务", 2000)
        retry_payload: Json = {
            "title": _clip(body.get("title") or f"重试 {campaign.get('title') or campaign_id}", 120),
            "prompt": prompt,
            "mode": _mode(body.get("mode") or retry_body.get("mode")),
            "profile": _profile(body.get("profile") or retry_body.get("profile")),
            "target": {"deviceIds": [str(item.get("deviceId") or "") for item in failed if str(item.get("deviceId") or "")][:100]},
            "retryOf": campaign_id,
            "retryCount": _int(campaign.get("retryCount"), 0) + 1,
            "confirmed": _truthy(body.get("confirmed")),
        }
        template = _template(body.get("template") or retry_body.get("template"))
        action = _direct_action(body.get("action") or retry_body.get("directAction"), prompt)
        if template:
            retry_payload["template"] = template
        if action:
            retry_payload["action"] = action
        task = self.dispatch(retry_payload)
        self._append_event(
            "retry",
            campaign_id,
            "",
            "",
            "",
            f"已生成重试任务 {task.get('campaignId')}",
        )
        return {
            "retried": True,
            "retryOf": campaign_id,
            "task": task,
            "dispatchBody": _redact_json(retry_payload),
            "failureReasons": _redact_json(failure_reasons),
        }

    def record_lead(self, raw: Json) -> Json:
        lead = {
            "schema": "loom.matrix.lead.v1",
            "leadId": f"lead_{uuid.uuid4().hex[:12]}",
            "createdAt": _now_iso(),
            "updatedAt": _now_iso(),
            "source": _lead_source(raw.get("source")),
            "status": _lead_status(raw.get("status")),
            "deviceId": _clip(raw.get("deviceId"), 80),
            "campaignId": _clip(raw.get("campaignId"), 80),
            "deviceTaskId": _clip(raw.get("deviceTaskId"), 80),
            "title": _clip(raw.get("title") or "手机线索", 120),
            "summary": _safe_lead_summary(raw.get("summary") or raw.get("note") or raw.get("description")),
            "tags": _safe_tags(raw.get("tags")),
        }
        self._append_jsonl(self.leads_path, lead)
        return _redact_json(lead)

    def list_leads(self, *, limit: int = 100) -> Json:
        rows = self._read_jsonl(self.leads_path)
        bounded = max(1, min(int(limit or 100), 500))
        return {"schema": "loom.matrix.leads.v1", "leads": _redact_json(rows[-bounded:])}

    def acquisition_snapshot(self) -> Json:
        state = self._load_acquisition_state()
        drafts = [item for item in state["drafts"] if isinstance(item, dict)]
        feishu = FeishuAcquisitionIntegration(self.paths).status()
        return _redact_json(
            {
                "schema": "loom.customer_acquisition.v1",
                "updatedAt": state.get("updatedAt") or _now_iso(),
                "contentTasks": state["contentTasks"][-50:],
                "leads": state["leads"][-100:],
                "customers": state["customers"][-100:],
                "drafts": drafts[-100:],
                "agentRuns": state.get("agentRuns", [])[-50:],
                "sop": state["sop"],
                "logs": state["logs"][-100:],
                "stats": {
                    "contentTasks": len(state["contentTasks"]),
                    "leads": len(state["leads"]),
                    "customers": len(state["customers"]),
                    "agentRuns": len(state.get("agentRuns", [])),
                    "draftsPending": sum(1 for item in drafts if item.get("status") == "pending_manual_review"),
                    "approvedDrafts": sum(1 for item in drafts if item.get("status") == "approved_pending_manual_send"),
                    "pendingSync": sum(
                        1
                        for item in state["leads"]
                        if item.get("syncStatus") in {"pending_sync", "sync_failed", "sync_conflict"}
                    ),
                },
                "outboundPolicy": _acquisition_policy(),
                "integrations": {
                    "feishu": feishu,
                },
            }
        )

    def create_acquisition_demo_flow(self, raw: Json) -> Json:
        state = self._load_acquisition_state()
        now = _now_iso()
        topic = _clip(raw.get("topic") or "AI 矩阵获客内容", 120)
        platform = _acquisition_platform(raw.get("platform"))
        channel = _acquisition_channel(raw.get("channel"))
        knowledge = _safe_lead_summary(raw.get("knowledge") or "先判断客户意图，再给出案例和人工跟进入口。", limit=320)
        lead_summary = _safe_lead_summary(
            raw.get("leadSummary") or raw.get("summary") or "评论区出现潜在线索，适合进入人工跟进。",
            limit=320,
        )
        content_task = {
            "taskId": f"content_{uuid.uuid4().hex[:10]}",
            "createdAt": now,
            "title": topic,
            "platform": platform,
            "status": "draft_ready",
            "assetPlan": [
                "短视频脚本",
                "评论区线索观察",
                "人工确认后跟进",
            ],
        }
        lead = {
            "leadId": f"lead_{uuid.uuid4().hex[:12]}",
            "createdAt": now,
            "updatedAt": now,
            "source": "demo_flow",
            "platform": platform,
            "channel": channel,
            "status": "qualified",
            "title": f"{topic} 线索",
            "summary": lead_summary,
            "tags": ["mvp-demo", channel, platform],
        }
        customer = {
            "customerId": f"customer_{uuid.uuid4().hex[:12]}",
            "createdAt": now,
            "updatedAt": now,
            "leadId": lead["leadId"],
            "name": f"{platform.upper()} 潜在客户",
            "stage": "needs_follow_up",
            "summary": lead_summary,
            "allowedChannels": [channel],
        }
        draft = {
            "draftId": f"draft_{uuid.uuid4().hex[:12]}",
            "createdAt": now,
            "updatedAt": now,
            "leadId": lead["leadId"],
            "customerId": customer["customerId"],
            "channel": channel,
            "status": "pending_manual_review",
            "requiresHumanReview": True,
            "sendEnabled": False,
            "policy": _acquisition_policy(),
            "body": _safe_lead_summary(
                f"您好，看到您关注「{topic}」。{knowledge} 如果方便，我可以先整理一份方案草稿，您确认后再继续沟通。",
                limit=500,
            ),
        }
        sync = FeishuAcquisitionIntegration(self.paths).sync_lead(
            {
                **lead,
                "sourceTask": content_task["title"],
                "draft": draft["body"],
                "recommendedAction": "人工确认后跟进",
                "logId": lead["leadId"],
            }
        )
        lead["syncStatus"] = sync.get("syncStatus") or "pending_sync"
        lead["syncError"] = sync.get("syncError") or ""
        lead["feishuRecordId"] = sync.get("recordId") or ""
        state["contentTasks"].append(content_task)
        state["leads"].append(lead)
        state["customers"].append(customer)
        state["drafts"].append(draft)
        state["logs"].extend(
            [
                _acquisition_log("content_task.created", f"内容任务已生成：{topic}", now),
                _acquisition_log("lead.qualified", f"线索进入线索池：{lead['title']}", now),
                _acquisition_log("customer.created", "线索已沉淀到客户池", now),
                _acquisition_log("draft.created", "跟进草稿已生成，等待人工确认，不会自动发送", now),
            ]
        )
        state["updatedAt"] = now
        self._write_acquisition_state(state)
        return _redact_json({"contentTask": content_task, "lead": lead, "customer": customer, "draft": draft})

    @_matrix_state_guard
    def import_acquisition_leads(self, raw: Json) -> Json:
        state = self._load_acquisition_state()
        now = _now_iso()
        topic = _clip(raw.get("topic") or "真实线索导入", 120)
        platform = _acquisition_platform(raw.get("platform"))
        channel = _acquisition_channel(raw.get("channel"))
        knowledge = _safe_lead_summary(raw.get("knowledge") or "先确认客户需求，再给人工跟进方案。", limit=360)
        owner = _clip(raw.get("owner") or "", 80)
        source = _acquisition_source(raw.get("source"))
        agent_task_id = _clip(raw.get("agentTaskId") or raw.get("taskId"), 80)
        device_id = _clip(raw.get("deviceId"), 80)
        action_status = _clip(raw.get("actionStatus") or raw.get("status"), 80)
        rows = _parse_acquisition_import_rows(raw)
        existing_keys = {
            str(item.get("dedupeKey") or "")
            for item in state["leads"]
            if isinstance(item, dict) and str(item.get("dedupeKey") or "")
        }
        seen: set[str] = set()
        content_task = {
            "taskId": f"content_{uuid.uuid4().hex[:10]}",
            "createdAt": now,
            "title": topic,
            "platform": platform,
            "status": "imported",
            "assetPlan": ["真实线索导入", "规则意向评分", "飞书线索表写入", "人工确认跟进草稿"],
        }
        imported_leads: list[Json] = []
        imported_customers: list[Json] = []
        imported_drafts: list[Json] = []
        duplicate_count = 0
        sync_ok = 0
        sync_pending = 0
        sync_failed = 0
        feishu = FeishuAcquisitionIntegration(self.paths)

        for row in rows:
            safe_platform = _acquisition_platform(row.get("platform") or platform)
            safe_channel = _acquisition_channel(row.get("channel") or channel)
            title = _clip(row.get("title") or row.get("nickname") or row.get("account") or "潜在线索", 120)
            summary = _safe_lead_summary(
                row.get("summary") or row.get("rawContent") or row.get("content") or row.get("description") or title,
                limit=360,
            )
            profile_url = _safe_lead_url(row.get("profileUrl") or row.get("主页链接") or row.get("url"))
            content_url = _safe_lead_url(row.get("contentUrl") or row.get("内容链接") or "")
            dedupe_key = _acquisition_dedupe_key(safe_platform, profile_url or content_url, title, summary)
            if not summary or dedupe_key in existing_keys or dedupe_key in seen:
                duplicate_count += 1
                continue
            seen.add(dedupe_key)
            qualification = _qualify_acquisition_lead(summary, topic=topic, target=raw.get("target") or raw.get("targetCustomer"))
            lead = {
                "leadId": f"lead_{uuid.uuid4().hex[:12]}",
                "createdAt": now,
                "updatedAt": now,
                "source": source,
                "sourceTask": content_task["title"],
                "agentTaskId": agent_task_id,
                "deviceId": device_id,
                "actionStatus": action_status,
                "platform": safe_platform,
                "channel": safe_channel,
                "status": "qualified" if qualification["score"] >= 50 else "new",
                "title": title,
                "nickname": _clip(row.get("nickname") or title, 120),
                "summary": summary,
                "rawContent": summary,
                "profileUrl": profile_url,
                "contentUrl": content_url,
                "need": qualification["need"],
                "intentLevel": qualification["intentLevel"],
                "intentScore": qualification["score"],
                "qualificationSource": "rules",
                "qualificationReasons": qualification["reasons"],
                "recommendedAction": qualification["recommendedAction"],
                "owner": owner,
                "dedupeKey": dedupe_key,
                "tags": ["real-import", safe_channel, safe_platform, qualification["intentLevel"]],
            }
            customer = {
                "customerId": f"customer_{uuid.uuid4().hex[:12]}",
                "createdAt": now,
                "updatedAt": now,
                "leadId": lead["leadId"],
                "name": title,
                "stage": "needs_follow_up" if qualification["score"] >= 50 else "needs_qualification",
                "summary": summary,
                "intentLevel": qualification["intentLevel"],
                "owner": owner,
                "allowedChannels": [safe_channel],
            }
            draft_body = _safe_lead_summary(row.get("draftBody"), limit=500) or _build_acquisition_followup_draft(lead, knowledge)
            draft = {
                "draftId": f"draft_{uuid.uuid4().hex[:12]}",
                "createdAt": now,
                "updatedAt": now,
                "leadId": lead["leadId"],
                "customerId": customer["customerId"],
                "agentTaskId": agent_task_id,
                "deviceId": device_id,
                "channel": safe_channel,
                "status": "pending_manual_review",
                "requiresHumanReview": True,
                "sendEnabled": False,
                "policy": _acquisition_policy(),
                "body": draft_body,
            }
            sync = feishu.sync_lead({**lead, "draft": draft_body, "logId": lead["leadId"]})
            lead["syncStatus"] = sync.get("syncStatus") or "pending_sync"
            lead["syncError"] = sync.get("syncError") or ""
            lead["feishuRecordId"] = sync.get("recordId") or ""
            if lead["syncStatus"] == "synced":
                sync_ok += 1
            elif lead["syncStatus"] in {"sync_failed", "sync_conflict"}:
                sync_failed += 1
            else:
                sync_pending += 1
            imported_leads.append(lead)
            imported_customers.append(customer)
            imported_drafts.append(draft)

        if imported_leads:
            state["contentTasks"].append(content_task)
            state["leads"].extend(imported_leads)
            state["customers"].extend(imported_customers)
            state["drafts"].extend(imported_drafts)
        state["logs"].extend(
            [
                _acquisition_log("lead.imported", f"真实线索导入 {len(imported_leads)} 条，去重 {duplicate_count} 条", now),
                _acquisition_log("lead.qualified", f"规则评分完成 {len(imported_leads)} 条，等待人工确认草稿", now),
                _acquisition_log("feishu.sync", f"飞书已同步 {sync_ok} 条，待同步 {sync_pending} 条，失败 {sync_failed} 条", now),
            ]
        )
        state["updatedAt"] = now
        self._write_acquisition_state(state)
        return _redact_json(
            {
                "imported": len(imported_leads),
                "duplicates": duplicate_count,
                "leads": imported_leads,
                "customers": imported_customers,
                "drafts": imported_drafts,
                "contentTask": content_task if imported_leads else None,
                "summary": f"导入 {len(imported_leads)} 条，去重 {duplicate_count} 条，飞书已同步 {sync_ok} 条，待同步 {sync_pending} 条，失败 {sync_failed} 条",
            }
        )

    def run_acquisition_agent_task(self, raw: Json) -> Json:
        dry_run = _truthy(raw.get("dryRun", True))
        if not dry_run and not _truthy(raw.get("confirmed")):
            return _redact_json(
                {
                    "error": "acquisition_agent_confirmation_required",
                    "executed": False,
                    "message": "Real phone Agent runs require confirmed=true and must still stop at human confirmation.",
                    "policy": _acquisition_policy(),
                }
            )
        agent_result = raw.get("agentResult") if isinstance(raw.get("agentResult"), dict) else {}
        if agent_result:
            ingest = self.ingest_acquisition_agent_result(agent_result, raw)
        else:
            ingest = {
                "imported": 0,
                "duplicates": 0,
                "leads": [],
                "customers": [],
                "drafts": [],
                "contentTask": None,
                "summary": "手机 Agent 任务已生成，等待真实回传入库",
            }
        agent_run = {
            "schema": "loom.acquisition.agent_run.v1",
            "dryRun": dry_run,
            "taskId": _clip(agent_result.get("taskId") or raw.get("taskId") or f"agent_task_{uuid.uuid4().hex[:10]}", 80),
            "deviceId": _clip(agent_result.get("deviceId") or raw.get("deviceId") or raw.get("device") or "phone-1", 80),
            "platform": _acquisition_platform(agent_result.get("platform") or raw.get("platform")),
            "action": _clip(agent_result.get("action") or raw.get("action") or "discover_leads", 80),
            "status": _clip(agent_result.get("status") or "pending_human_confirm", 80),
            "requiresHumanReview": True,
            "sendEnabled": False,
        }
        agent_run["phoneTask"] = _acquisition_phone_task_payload(raw, agent_run)
        state = self._load_acquisition_state()
        state["agentRuns"].append(agent_run)
        state["logs"].append(
            _acquisition_log(
                "agent.task_prepared",
                f"手机 Agent 获客任务已准备：{agent_run['taskId']} / {agent_run['platform']} / {agent_run['deviceId']}",
                _now_iso(),
            )
        )
        state["updatedAt"] = _now_iso()
        self._write_acquisition_state(state)
        return _redact_json({"agentRun": agent_run, "ingest": ingest, "snapshot": self.acquisition_snapshot()})

    def ingest_acquisition_agent_result(self, agent_result: Json, raw: Json | None = None) -> Json:
        body = raw if isinstance(raw, dict) else {}
        task_id = _clip(agent_result.get("taskId") or body.get("taskId") or f"agent_task_{uuid.uuid4().hex[:10]}", 80)
        device_id = _clip(agent_result.get("deviceId") or body.get("deviceId") or "", 80)
        platform = _acquisition_platform(agent_result.get("platform") or body.get("platform"))
        action = _clip(agent_result.get("action") or body.get("action") or "discover_leads", 80)
        status = _clip(agent_result.get("status") or "pending_human_confirm", 80)
        drafts = agent_result.get("drafts") if isinstance(agent_result.get("drafts"), list) else []
        draft = next((item for item in drafts if isinstance(item, dict)), {})
        policy_clamped = _agent_result_has_unsafe_outbound(agent_result)
        leads = []
        for item in agent_result.get("leads") if isinstance(agent_result.get("leads"), list) else []:
            if not isinstance(item, dict):
                continue
            leads.append(
                {
                    **item,
                    "platform": item.get("platform") or platform,
                    "channel": item.get("channel") or draft.get("channel") or "comment",
                    "draftBody": item.get("draftBody") or draft.get("body") or "",
                }
            )
        ingest = self.import_acquisition_leads(
            {
                "topic": body.get("topic") or f"{platform} 手机 Agent 获客任务",
                "platform": platform,
                "channel": draft.get("channel") or body.get("channel") or "comment",
                "knowledge": body.get("knowledge") or "手机 Agent 已返回线索，后续只生成草稿并等待人工确认。",
                "target": body.get("target") or "",
                "owner": body.get("owner") or "phone-agent",
                "leads": leads,
                "source": "phone_agent",
                "agentTaskId": task_id,
                "deviceId": device_id,
                "actionStatus": status,
                "status": status,
            }
        )
        state = self._load_acquisition_state()
        if policy_clamped:
            state["logs"].append(
                _acquisition_log(
                    "agent.result_policy_clamped",
                    f"手机 Agent 回传包含外发意图，已强制钳制为草稿/人工确认：{task_id}",
                    _now_iso(),
                )
            )
        state["logs"].append(_acquisition_log("agent.result_ingested", f"手机 Agent 结果已入库：{task_id} / {action} / {status}", _now_iso()))
        state["updatedAt"] = _now_iso()
        self._write_acquisition_state(state)
        return ingest

    def confirm_acquisition_draft(self, draft_id: str, raw: Json | None = None) -> Json:
        state = self._load_acquisition_state()
        body = raw if isinstance(raw, dict) else {}
        safe_id = _clip(draft_id, 80)
        now = _now_iso()
        for draft in state["drafts"]:
            if not isinstance(draft, dict) or draft.get("draftId") != safe_id:
                continue
            draft["status"] = "approved_pending_manual_send"
            draft["updatedAt"] = now
            draft["approvedBy"] = _clip(body.get("operator") or "human", 80)
            draft["sendEnabled"] = False
            draft["requiresHumanReview"] = True
            state["logs"].append(_acquisition_log("draft.approved", "草稿已人工确认，仍需在白名单和频控下手动发送", now))
            state["updatedAt"] = now
            self._write_acquisition_state(state)
            return _redact_json({"draft": draft, "snapshot": self.acquisition_snapshot()})
        return {"error": "draft not found", "draftId": safe_id}

    def record_acquisition_manual_send(self, draft_id: str, raw: Json | None = None) -> Json:
        state = self._load_acquisition_state()
        body = raw if isinstance(raw, dict) else {}
        safe_id = _clip(draft_id, 80)
        now = _now_iso()
        outcome = _manual_send_outcome(body.get("outcome"))
        for draft in state["drafts"]:
            if not isinstance(draft, dict) or draft.get("draftId") != safe_id:
                continue
            draft["status"] = "manual_sent" if outcome != "failed" else "manual_send_failed"
            draft["updatedAt"] = now
            draft["sendEnabled"] = False
            draft["requiresHumanReview"] = True
            draft["manualSend"] = {
                "outcome": outcome,
                "operator": _clip(body.get("operator") or "human", 80),
                "recordedAt": now,
                "reply": _safe_lead_summary(body.get("reply"), limit=320),
                "note": _safe_lead_summary(body.get("note"), limit=320),
                "nextFollowUpAt": _clip(body.get("nextFollowUpAt"), 80),
            }
            for customer in state["customers"]:
                if isinstance(customer, dict) and customer.get("customerId") == draft.get("customerId"):
                    customer["stage"] = "replied" if draft["manualSend"]["reply"] else ("contact_failed" if outcome == "failed" else "contacted")
                    customer["lastReply"] = draft["manualSend"]["reply"]
                    customer["nextFollowUpAt"] = draft["manualSend"]["nextFollowUpAt"]
                    customer["updatedAt"] = now
            for lead in state["leads"]:
                if isinstance(lead, dict) and lead.get("leadId") == draft.get("leadId"):
                    lead["status"] = "contact_failed" if outcome == "failed" else "contacted"
                    lead["updatedAt"] = now
            state["logs"].append(
                _acquisition_log(
                    "draft.manual_sent",
                    f"已记录人工触达：{safe_id} / {outcome}；系统未自动发送评论、私信或加好友。",
                    now,
                )
            )
            state["updatedAt"] = now
            self._write_acquisition_state(state)
            return _redact_json({"draft": draft, "snapshot": self.acquisition_snapshot()})
        return {"error": "draft not found", "draftId": safe_id}

    @_matrix_state_guard
    def acquire_lease(self, device_id: str, raw: Json) -> Json:
        safe_device_id = _device_id(device_id)
        self._require_device(safe_device_id, writable=True)
        holder_type = str(raw.get("holderType") or "").strip().lower()
        holder_id = _clip(raw.get("holderId"), 200)
        mode = str(raw.get("mode") or "control").strip().lower()
        requested_lease_id = _clip(raw.get("leaseId"), 100)
        if holder_type not in {"agent", "human"}:
            raise MatrixTargetError("matrix_invalid_lease", "holderType must be agent or human")
        if not holder_id:
            raise MatrixTargetError("matrix_invalid_lease", "holderId is required")
        if mode != "control":
            raise MatrixTargetError("matrix_invalid_lease", "mode must be control")

        state = self._load_leases()
        active = self._active_lease(state, safe_device_id)
        if active:
            same_holder = (
                active.get("holderType") == holder_type
                and active.get("holderId") == holder_id
            )
            lease_matches = not requested_lease_id or requested_lease_id == active.get("leaseId")
            if not same_holder or not lease_matches:
                raise MatrixTargetError(
                    "device_lease_conflict",
                    "Device is controlled by another active lease",
                )
            lease = active
        else:
            lease = {
                "schema": "loom.matrix.device_lease.v1",
                "leaseId": f"lease_{uuid.uuid4().hex[:16]}",
                "deviceId": safe_device_id,
                "holderType": holder_type,
                "holderId": holder_id,
                "mode": "control",
                "expiresAt": "",
            }
            state["leases"] = [
                item
                for item in state["leases"]
                if isinstance(item, dict) and item.get("deviceId") != safe_device_id
            ]
            state["leases"].append(lease)
        lease["expiresAt"] = _future_iso(MATRIX_LEASE_TTL_SECONDS)
        self._write_leases(state)
        return _redact_json(dict(lease))

    @_matrix_state_guard
    def takeover_task(self, device_id: str, device_task_id: str, raw: Json) -> Json:
        safe_device_id = _device_id(device_id)
        safe_task_id = _clip(device_task_id, 200)
        self._require_device(safe_device_id, writable=True)
        holder_type = str(raw.get("holderType") or "").strip().lower()
        holder_id = _clip(raw.get("holderId"), 200)
        mode = str(raw.get("mode") or "control").strip().lower()
        agent_lease_id = _clip(raw.get("leaseId"), 100)
        if holder_type != "human":
            raise MatrixTargetError("matrix_invalid_lease", "Task takeover requires a human lease holder")
        if not holder_id:
            raise MatrixTargetError("matrix_invalid_lease", "holderId is required")
        if mode != "control":
            raise MatrixTargetError("matrix_invalid_lease", "mode must be control")
        if not safe_task_id or not agent_lease_id:
            raise MatrixTargetError(
                "matrix_invalid_lease",
                "deviceTaskId and the active agent leaseId are required for takeover",
            )

        tasks = self._load_tasks()
        found = self._find_device_task(safe_task_id, tasks=tasks)
        if not found:
            raise MatrixTargetError("matrix_task_not_found", "Device task was not found")
        device_task = found["deviceTask"]
        if str(device_task.get("deviceId") or "") != safe_device_id:
            raise MatrixTargetError(
                "device_lease_conflict",
                "The requested task does not belong to the target device",
            )

        lease_state = self._load_leases()
        active = self._active_lease(lease_state, safe_device_id)
        lease_matches = bool(active) and (
            active.get("leaseId") == agent_lease_id
            and active.get("holderType") == "agent"
            and active.get("holderId") == safe_task_id
        )
        if not lease_matches:
            raise MatrixTargetError(
                "device_lease_conflict",
                "The active agent lease does not belong to the requested device task",
            )

        found, previous_status = self._apply_task_transition(
            tasks,
            safe_task_id,
            expected={"queued", "running"},
            status="paused",
        )
        lease = {
            "schema": "loom.matrix.device_lease.v1",
            "leaseId": f"lease_{uuid.uuid4().hex[:16]}",
            "deviceId": safe_device_id,
            "holderType": "human",
            "holderId": holder_id,
            "mode": "control",
            "expiresAt": _future_iso(MATRIX_LEASE_TTL_SECONDS),
            "pausedDeviceTaskId": safe_task_id,
        }
        original_lease_state = {
            "schema": str(lease_state.get("schema") or "loom.matrix.device_leases.v1"),
            "leases": [dict(item) for item in lease_state.get("leases", []) if isinstance(item, dict)],
        }
        lease_state["leases"] = [
            item
            for item in lease_state["leases"]
            if isinstance(item, dict) and item.get("deviceId") != safe_device_id
        ]
        lease_state["leases"].append(lease)

        self._write_leases(lease_state)
        try:
            self._write_json(self.tasks_path, tasks)
        except Exception:
            self._write_leases(original_lease_state)
            raise

        campaign = found["campaign"]
        mission = found["mission"]
        device_task = found["deviceTask"]
        self._append_event(
            "paused",
            str(campaign.get("campaignId") or ""),
            str(mission.get("missionId") or ""),
            safe_task_id,
            safe_device_id,
            "Device task paused for human takeover",
            assignment_id=str(device_task.get("assignmentId") or ""),
        )
        self._update_device(safe_device_id, {"currentTaskId": ""})
        return {
            "status": "applied",
            "previousStatus": previous_status,
            "campaign": _redact_json(campaign),
            "deviceTask": _redact_json(device_task),
            "lease": _redact_json(dict(lease)),
            "releasedAgentLeaseDeviceIds": [safe_device_id],
        }

    @_matrix_state_guard
    def get_lease(self, device_id: str) -> Json:
        safe_device_id = _device_id(device_id)
        self._require_device(safe_device_id)
        state = self._load_leases()
        lease = self._active_lease(state, safe_device_id)
        if not lease:
            self._write_leases(state)
            return {"lease": None, "remainingTtlMs": 0}
        return {
            "lease": _redact_json(dict(lease)),
            "remainingTtlMs": _remaining_ttl_ms(lease.get("expiresAt")),
        }

    @_matrix_state_guard
    def release_lease(self, device_id: str, lease_id: str) -> Json:
        safe_device_id = _device_id(device_id)
        safe_lease_id = _clip(lease_id, 100)
        state = self._load_leases()
        released_lease = next(
            (
                item
                for item in state["leases"]
                if isinstance(item, dict)
                and item.get("deviceId") == safe_device_id
                and item.get("leaseId") == safe_lease_id
            ),
            None,
        )
        original_lease_state = {
            "schema": str(state.get("schema") or "loom.matrix.device_leases.v1"),
            "leases": [dict(item) for item in state.get("leases", []) if isinstance(item, dict)],
        }
        state["leases"] = [
            item
            for item in state["leases"]
            if not (
                isinstance(item, dict)
                and item.get("deviceId") == safe_device_id
                and item.get("leaseId") == safe_lease_id
            )
        ]

        transition: tuple[Json, str] | None = None
        tasks: Json | None = None
        paused_task_id = ""
        if isinstance(released_lease, dict) and released_lease.get("holderType") == "human":
            paused_task_id = _clip(released_lease.get("pausedDeviceTaskId"), 200)
        if paused_task_id:
            tasks = self._load_tasks()
            found = self._find_device_task(paused_task_id, tasks=tasks)
            if (
                found
                and str(found["deviceTask"].get("deviceId") or "") == safe_device_id
                and str(found["deviceTask"].get("status") or "") == "paused"
            ):
                transition = self._apply_task_transition(
                    tasks,
                    paused_task_id,
                    expected={"paused"},
                    status="queued",
                )

        self._write_leases(state)
        if transition and tasks is not None:
            try:
                self._write_json(self.tasks_path, tasks)
            except Exception:
                self._write_leases(original_lease_state)
                raise

        result = {
            "released": released_lease is not None,
            "deviceId": safe_device_id,
            "lease": None,
        }
        if transition:
            found, previous_status = transition
            campaign = found["campaign"]
            mission = found["mission"]
            device_task = found["deviceTask"]
            self._append_event(
                "resumed",
                str(campaign.get("campaignId") or ""),
                str(mission.get("missionId") or ""),
                paused_task_id,
                safe_device_id,
                "Device task queued after human takeover",
                assignment_id=str(device_task.get("assignmentId") or ""),
            )
            result.update(
                {
                    "previousStatus": previous_status,
                    "resumedDeviceTaskId": paused_task_id,
                    "campaign": _redact_json(campaign),
                    "deviceTask": _redact_json(device_task),
                }
            )
        return result

    @_matrix_state_guard
    def require_lease(
        self,
        device_id: str,
        lease_id: str,
        *,
        holder_type: str | None = None,
        holder_id: str | None = None,
    ) -> Json:
        safe_device_id = _device_id(device_id)
        self._require_device(safe_device_id, writable=True)
        state = self._load_leases()
        lease = self._active_lease(state, safe_device_id)
        lease_matches = bool(lease) and lease.get("leaseId") == _clip(lease_id, 100)
        if holder_type is not None:
            lease_matches = lease_matches and lease.get("holderType") == str(holder_type).strip().lower()
        if holder_id is not None:
            lease_matches = lease_matches and lease.get("holderId") == _clip(holder_id, 200)
        if not lease_matches:
            self._write_leases(state)
            raise MatrixTargetError(
                "device_lease_conflict",
                "A valid device write lease is required",
            )
        return _redact_json(dict(lease))

    @_matrix_state_guard
    def begin_control_command(
        self,
        device_id: str,
        client_command_id: str,
        request: Json,
        *,
        lease: Json | None = None,
    ) -> Json:
        safe_device_id = _device_id(device_id)
        safe_command_id = _clip(client_command_id, 200)
        if not safe_command_id:
            raise MatrixTargetError("matrix_invalid_control", "clientCommandId is required")
        state = self._load_control_commands()
        lease_binding = {
            "leaseId": _clip((lease or {}).get("leaseId"), 100),
            "holderType": str((lease or {}).get("holderType") or "").strip().lower(),
            "holderId": _clip((lease or {}).get("holderId"), 200),
        } if lease is not None else None
        fingerprint = hashlib.sha256(
            json.dumps(_redact_json(request), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for command in state["commands"]:
            if not isinstance(command, dict):
                continue
            if command.get("deviceId") != safe_device_id or command.get("clientCommandId") != safe_command_id:
                continue
            if command.get("fingerprint") != fingerprint:
                raise MatrixTargetError(
                    "matrix_command_id_conflict",
                    "clientCommandId was already used for another command",
                )
            if lease_binding is not None and command.get("leaseBinding") != lease_binding:
                raise MatrixTargetError(
                    "device_lease_conflict",
                    "Manual control command belongs to another device lease holder",
                )
            return {"created": False, "result": _redact_json(command.get("result") or {"status": "requested", "commandId": safe_command_id})}
        command = {
            "deviceId": safe_device_id,
            "clientCommandId": safe_command_id,
            "fingerprint": fingerprint,
            "createdAt": _now_iso(),
            "result": {"status": "requested", "commandId": safe_command_id},
        }
        if lease_binding is not None:
            command["leaseBinding"] = lease_binding
        state["commands"].append(command)
        self._write_control_commands(state)
        return {"created": True, "result": {"status": "requested", "commandId": safe_command_id}}

    @_matrix_state_guard
    def complete_control_command(self, device_id: str, client_command_id: str, result: Json) -> Json:
        safe_device_id = _device_id(device_id)
        safe_command_id = _clip(client_command_id, 200)
        state = self._load_control_commands()
        safe_result = _redact_json(result)
        for command in state["commands"]:
            if (
                isinstance(command, dict)
                and command.get("deviceId") == safe_device_id
                and command.get("clientCommandId") == safe_command_id
            ):
                command["result"] = safe_result
                command["completedAt"] = _now_iso()
                break
        self._write_control_commands(state)
        return safe_result

    def timeline(self, device_id: str, *, limit: int = 100) -> Json:
        safe_device_id = _device_id(device_id)
        events = [
            event
            for event in self._load_events()
            if str(event.get("deviceId") or "") == safe_device_id
        ]
        return {
            "schema": "loom.matrix.device_timeline.v1",
            "deviceId": safe_device_id,
            "events": _redact_json(events[-max(1, min(int(limit), 500)):]),
        }

    @_matrix_state_guard
    def pause_task(self, device_task_id: str, *, lease_id: str = "") -> Json:
        safe_lease_id = _clip(lease_id, 100)
        if safe_lease_id:
            found = self._find_device_task(device_task_id)
            if not found:
                raise MatrixTargetError("matrix_task_not_found", "Device task was not found")
            device_id = str(found["deviceTask"].get("deviceId") or "")
            lease_state = self._load_leases()
            active = self._active_lease(lease_state, device_id)
            if not (
                active
                and active.get("leaseId") == safe_lease_id
                and active.get("holderType") == "agent"
                and active.get("holderId") == device_task_id
            ):
                raise MatrixTargetError(
                    "device_lease_conflict",
                    "The active agent lease does not belong to the requested device task",
                )
        result = self._transition_task(
            device_task_id,
            expected={"queued", "running"},
            status="paused",
            event_type="paused",
        )
        device_id = str((result.get("deviceTask") or {}).get("deviceId") or "")
        result["releasedAgentLeaseDeviceIds"] = self._release_agent_leases(
            {device_id},
            holder_ids={device_task_id},
            lease_ids={safe_lease_id} if safe_lease_id else None,
        ) if device_id else []
        if device_id:
            self._update_device(device_id, {"currentTaskId": ""})
        return result

    @_matrix_state_guard
    def start_task(self, device_task_id: str) -> Json:
        result = self._transition_task(
            device_task_id,
            expected={"queued"},
            status="running",
            event_type="running",
        )
        device_task = result.get("deviceTask") if isinstance(result.get("deviceTask"), dict) else {}
        device_id = str(device_task.get("deviceId") or "")
        if device_id:
            self._update_device(device_id, {"currentTaskId": device_task_id})
        return result

    @_matrix_state_guard
    def resume_task(self, device_task_id: str) -> Json:
        return self._transition_task(device_task_id, expected={"paused"}, status="queued", event_type="resumed")

    @_matrix_state_guard
    def task_status(self, device_task_id: str) -> str:
        found = self._find_device_task(device_task_id)
        if not found:
            return ""
        return str(found["deviceTask"].get("status") or "")

    @_matrix_state_guard
    def task_execution_context(self, device_task_id: str) -> Json:
        found = self._find_device_task(device_task_id)
        if not found:
            raise MatrixTargetError("matrix_task_not_found", "Device task was not found")
        campaign = found["campaign"]
        device_task = found["deviceTask"]
        retry_body = campaign.get("retryBody") if isinstance(campaign.get("retryBody"), dict) else {}
        body = {
            "campaignId": str(campaign.get("campaignId") or ""),
            "prompt": str(device_task.get("prompt") or retry_body.get("promptPreview") or campaign.get("title") or ""),
            "mode": str(device_task.get("mode") or retry_body.get("mode") or "safe"),
            "profile": str(device_task.get("profile") or retry_body.get("profile") or "fast"),
            "template": str(device_task.get("template") or retry_body.get("template") or ""),
            "templateId": str(device_task.get("templateId") or ""),
            "action": str(device_task.get("directAction") or retry_body.get("directAction") or ""),
            "concurrency": 1,
        }
        return {
            "campaignId": str(campaign.get("campaignId") or ""),
            "body": _redact_json(body),
            "deviceTask": _redact_json(device_task),
        }

    def watch(self, campaign_id: str | None = None, *, limit: int = 100) -> Json:
        events, truncation = self._load_events_with_truncation()
        if campaign_id:
            events = [event for event in events if event.get("campaignId") == campaign_id]
        requested_limit = max(1, min(limit, 500))
        if len(events) > requested_limit:
            truncation["omittedEvents"] += len(events) - requested_limit
            if "request_limit" not in truncation["reasons"]:
                truncation["reasons"].append("request_limit")
        visible_events = events[-requested_limit:]
        truncation["reason"] = truncation["reasons"][0] if truncation["reasons"] else ""
        return {
            "schema": "loom.matrix.events.v1",
            "events": _redact_json(visible_events),
            "truncated": bool(truncation["omittedBytes"] or truncation["omittedEvents"]),
            "truncation": truncation,
        }

    def realtime_events(self, *, after_seq: int = 0, limit: int = 500) -> list[Json]:
        events = self._load_events()
        envelopes: list[Json] = []
        for index, event in enumerate(events, start=1):
            seq = _int(event.get("seq"), index)
            if seq <= after_seq:
                continue
            entity_id = str(
                event.get("deviceTaskId")
                or event.get("campaignId")
                or event.get("deviceId")
                or event.get("eventId")
                or "matrix"
            )
            envelopes.append(
                {
                    "schema": "loom.realtime.event.v1",
                    "eventId": str(event.get("eventId") or f"matrix_{seq}"),
                    "seq": seq,
                    "timestamp": str(event.get("timestamp") or _now_iso()),
                    "topic": "matrix",
                    "entityId": entity_id,
                    "type": str(event.get("type") or "matrix.updated"),
                    "data": _redact_json(event),
                }
            )
        return envelopes[-max(1, min(int(limit), 500)):]

    @_matrix_state_guard
    def append_runtime_event(
        self,
        event_type: str,
        device_id: str,
        message: str,
        *,
        source: str = "runtime",
        details: Json | None = None,
    ) -> Json:
        safe_type = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(event_type or "runtime").strip()).strip(".-_")[:80] or "runtime"
        safe_details = _redact_json(details) if isinstance(details, dict) and details else None
        fingerprint_payload = {
            "type": safe_type,
            "deviceId": _device_id(device_id) if str(device_id or "").strip() else "",
            "source": _clip(source, 80) or "runtime",
            "message": _clip(message, 320),
            "details": safe_details or {},
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                _without_volatile_event_fields(fingerprint_payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        recent_events = self._load_events()[-50:]
        if safe_type in _STATE_STREAM_EVENT_TYPES:
            for existing in reversed(recent_events):
                if str(existing.get("type") or "") != safe_type:
                    continue
                if str(existing.get("deviceId") or "") != fingerprint_payload["deviceId"]:
                    continue
                if str(existing.get("fingerprint") or "") == fingerprint:
                    return _redact_json({**existing, "deduplicated": True})
                break
        else:
            for existing in reversed(recent_events):
                if str(existing.get("fingerprint") or "") != fingerprint:
                    continue
                age_ms = _timestamp_age_ms(existing.get("timestamp") or "")
                if age_ms < 0 or age_ms > MATRIX_RUNTIME_DEDUPE_WINDOW_MS:
                    break
                return _redact_json({**existing, "deduplicated": True})

        event = {
            "schema": "loom.matrix.event.v1",
            "eventId": f"evt_{uuid.uuid4().hex[:12]}",
            "seq": self._next_event_seq(),
            "timestamp": _now_iso(),
            "type": safe_type,
            "campaignId": "",
            "missionId": "",
            "deviceTaskId": "",
            "deviceId": _device_id(device_id) if str(device_id or "").strip() else "",
            "source": _clip(source, 80) or "runtime",
            "message": _clip(message, 320),
            "fingerprint": fingerprint,
        }
        if safe_details:
            event["details"] = safe_details
        self._append_jsonl(self.events_path, event)
        return _redact_json(event)

    @_matrix_state_guard
    def append_task_event(self, event_type: str, device_task_id: str, message: str) -> Json:
        found = self._find_device_task(device_task_id)
        if not found:
            return {"ok": False, "error": "deviceTask not found"}
        device_task = found["deviceTask"]
        task_status = str(device_task.get("status") or "")
        if task_status in _DEVICE_TASK_TERMINAL_STATES:
            return {
                "ok": False,
                "terminal": True,
                "ignored": True,
                "status": task_status,
                "deviceTaskId": device_task_id,
            }
        self._append_event(
            event_type,
            str(found["campaign"].get("campaignId") or ""),
            str(found["mission"].get("missionId") or ""),
            device_task_id,
            str(found["deviceTask"].get("deviceId") or ""),
            _clip(message, 240),
            assignment_id=str(found["deviceTask"].get("assignmentId") or ""),
        )
        return {"ok": True}

    @_matrix_state_guard
    def mark_step(self, device_task_id: str, step_id: str, *, status: str, message: str = "") -> Json:
        tasks = self._load_tasks()
        found = self._find_device_task(device_task_id, tasks=tasks)
        if not found:
            return {"ok": False, "error": "deviceTask not found"}
        device_task = found["deviceTask"]
        task_status = str(device_task.get("status") or "")
        if task_status in _DEVICE_TASK_TERMINAL_STATES:
            return {
                "ok": False,
                "terminal": True,
                "ignored": True,
                "status": task_status,
                "deviceTaskId": device_task_id,
            }
        now = _now_iso()
        device_task["currentStep"] = step_id
        device_task["updatedAt"] = now
        for step in device_task.get("steps", []):
            if step.get("stepId") == step_id:
                step["status"] = status
                step["updatedAt"] = now
        found["campaign"]["updatedAt"] = now
        found["mission"]["updatedAt"] = now
        self._write_json(self.tasks_path, tasks)
        self._append_event(
            "step",
            str(found["campaign"].get("campaignId") or ""),
            str(found["mission"].get("missionId") or ""),
            device_task_id,
            str(device_task.get("deviceId") or ""),
            message or step_id,
            assignment_id=str(device_task.get("assignmentId") or ""),
        )
        return {"ok": True}

    def _cancel_matching_tasks(
        self,
        tasks: Json,
        predicate: Callable[[str, Json], bool],
        *,
        message: str,
    ) -> Json:
        affected: list[Json] = []
        cancelled_ids: list[str] = []
        now = _now_iso()
        for campaign in tasks.get("campaigns", []):
            if not isinstance(campaign, dict):
                continue
            campaign_id = str(campaign.get("campaignId") or "")
            if not campaign_id:
                continue
            campaign_affected: list[Json] = []
            for mission in campaign.get("missions", []):
                if not isinstance(mission, dict):
                    continue
                mission_changed = False
                mission_id = str(mission.get("missionId") or "")
                for device_task in mission.get("deviceTasks", []):
                    if not isinstance(device_task, dict):
                        continue
                    previous_status = str(device_task.get("status") or "")
                    if (
                        previous_status not in _DEVICE_TASK_CANCELLABLE_STATES
                        or not predicate(campaign_id, device_task)
                    ):
                        continue
                    device_task["status"] = "cancelled"
                    device_task["updatedAt"] = now
                    mission_changed = True
                    row = {
                        "campaignId": campaign_id,
                        "missionId": mission_id,
                        "assignmentId": str(device_task.get("assignmentId") or ""),
                        "deviceTaskId": str(device_task.get("deviceTaskId") or ""),
                        "deviceId": str(device_task.get("deviceId") or ""),
                        "previousStatus": previous_status,
                        "status": "cancelled",
                    }
                    campaign_affected.append(row)
                    self._append_event(
                        "cancelled",
                        campaign_id,
                        mission_id,
                        row["deviceTaskId"],
                        row["deviceId"],
                        message,
                        assignment_id=row["assignmentId"],
                    )
                    self._update_device(row["deviceId"], {"currentTaskId": ""})
                if mission_changed:
                    mission["updatedAt"] = now
            if campaign_affected:
                campaign["updatedAt"] = now
                cancelled_ids.append(campaign_id)
                affected.extend(campaign_affected)
        if affected:
            for affected_campaign_id in cancelled_ids:
                self._refresh_campaign_status(tasks, affected_campaign_id)
            self._write_json(self.tasks_path, tasks)
        affected.sort(key=lambda item: (
            str(item.get("campaignId") or ""),
            str(item.get("missionId") or ""),
            str(item.get("deviceId") or ""),
            str(item.get("deviceTaskId") or ""),
        ))
        fully_stopped_campaign_ids = sorted(
            campaign_id
            for campaign_id in cancelled_ids
            if not any(
                isinstance(device_task, dict)
                and str(device_task.get("status") or "") in _DEVICE_TASK_CANCELLABLE_STATES
                for campaign in tasks.get("campaigns", [])
                if isinstance(campaign, dict) and str(campaign.get("campaignId") or "") == campaign_id
                for mission in campaign.get("missions", [])
                if isinstance(mission, dict)
                for device_task in mission.get("deviceTasks", [])
            )
        )
        return {
            "cancelled": bool(affected),
            "cancelledCount": len(cancelled_ids),
            "campaignIds": sorted(cancelled_ids),
            "fullyStoppedCampaignIds": fully_stopped_campaign_ids,
            "affectedTaskCount": len(affected),
            "affectedDeviceCount": len({str(item.get("deviceId") or "") for item in affected}),
            "affected": affected,
        }

    def _cancel_campaigns(self, tasks: Json, campaign_ids: set[str], *, message: str) -> Json:
        return self._cancel_matching_tasks(
            tasks,
            lambda campaign_id, _device_task: campaign_id in campaign_ids,
            message=message,
        )

    @_matrix_state_guard
    def cancel(self, campaign_id: str) -> Json:
        tasks = self._load_tasks()
        campaign = next(
            (
                item
                for item in tasks.get("campaigns", [])
                if isinstance(item, dict)
                and str(item.get("campaignId") or "") == campaign_id
            ),
            None,
        )
        if not isinstance(campaign, dict):
            raise MatrixTargetError("matrix_campaign_not_found", f"Matrix campaign not found: {campaign_id}")
        already_terminal = str(campaign.get("status") or "") in _DEVICE_TASK_TERMINAL_STATES
        result = self._cancel_campaigns(tasks, {campaign_id}, message="任务已取消")
        result.update({
            "alreadyTerminal": already_terminal,
            "campaignId": campaign_id,
            "status": str(campaign.get("status") or ""),
        })
        return result

    @_matrix_state_guard
    def cancel_all(self) -> Json:
        tasks = self._load_tasks()
        campaign_ids = {
            str(campaign.get("campaignId") or "")
            for campaign in tasks.get("campaigns", [])
            if isinstance(campaign, dict)
        }
        return self._cancel_campaigns(tasks, campaign_ids, message="任务已批量取消")

    @_matrix_state_guard
    def emergency_stop(
        self,
        *,
        all_tasks: bool = False,
        campaign_id: str = "",
        device_ids: set[str] | None = None,
        device_task_ids: set[str] | None = None,
        campaign_atomic: bool = False,
    ) -> Json:
        tasks = self._load_tasks()
        safe_device_ids = {str(item) for item in (device_ids or set()) if str(item)}
        safe_task_ids = {str(item) for item in (device_task_ids or set()) if str(item)}
        selected_campaign_ids: set[str] = set()
        lease_device_ids: set[str] | None = None if all_tasks else set(safe_device_ids)
        for campaign in tasks.get("campaigns", []):
            if not isinstance(campaign, dict):
                continue
            current_campaign_id = str(campaign.get("campaignId") or "")
            if not current_campaign_id:
                continue
            if all_tasks or (campaign_id and current_campaign_id == campaign_id):
                selected_campaign_ids.add(current_campaign_id)
                if lease_device_ids is not None:
                    lease_device_ids.update(
                        str(device_task.get("deviceId") or "")
                        for mission in campaign.get("missions", [])
                        if isinstance(mission, dict)
                        for device_task in mission.get("deviceTasks", [])
                        if isinstance(device_task, dict) and str(device_task.get("deviceId") or "")
                    )
                continue
            for mission in campaign.get("missions", []):
                if not isinstance(mission, dict):
                    continue
                if lease_device_ids is not None:
                    lease_device_ids.update(
                        str(device_task.get("deviceId") or "")
                        for device_task in mission.get("deviceTasks", [])
                        if isinstance(device_task, dict)
                        and str(device_task.get("deviceTaskId") or "") in safe_task_ids
                        and str(device_task.get("deviceId") or "")
                    )
                if any(
                    isinstance(device_task, dict)
                    and (
                        str(device_task.get("deviceId") or "") in safe_device_ids
                        or str(device_task.get("deviceTaskId") or "") in safe_task_ids
                    )
                    for device_task in mission.get("deviceTasks", [])
                ):
                    selected_campaign_ids.add(current_campaign_id)
                    break
        if campaign_atomic and lease_device_ids is not None:
            lease_device_ids.update(
                str(device_task.get("deviceId") or "")
                for campaign in tasks.get("campaigns", [])
                if isinstance(campaign, dict)
                and str(campaign.get("campaignId") or "") in selected_campaign_ids
                for mission in campaign.get("missions", [])
                if isinstance(mission, dict)
                for device_task in mission.get("deviceTasks", [])
                if isinstance(device_task, dict) and str(device_task.get("deviceId") or "")
            )
        matched_device_task_ids: set[str] = set()
        matched_device_ids: set[str] = set()
        for campaign in tasks.get("campaigns", []):
            if not isinstance(campaign, dict):
                continue
            current_campaign_id = str(campaign.get("campaignId") or "")
            campaign_wide = (
                (all_tasks or bool(campaign_id) or campaign_atomic)
                and current_campaign_id in selected_campaign_ids
            )
            for mission in campaign.get("missions", []):
                if not isinstance(mission, dict):
                    continue
                for device_task in mission.get("deviceTasks", []):
                    if not isinstance(device_task, dict):
                        continue
                    task_id = str(device_task.get("deviceTaskId") or "")
                    device_id = str(device_task.get("deviceId") or "")
                    if not campaign_wide and device_id not in safe_device_ids and task_id not in safe_task_ids:
                        continue
                    if task_id:
                        matched_device_task_ids.add(task_id)
                    if device_id:
                        matched_device_ids.add(device_id)
        if not (all_tasks or campaign_id or campaign_atomic):
            result = self._cancel_matching_tasks(
                tasks,
                lambda _campaign_id, device_task: (
                    str(device_task.get("deviceId") or "") in safe_device_ids
                    or str(device_task.get("deviceTaskId") or "") in safe_task_ids
                ),
                message="Matrix task emergency-stopped",
            )
            result["schema"] = "loom.matrix.emergency_stop.v1"
            result["matchedCampaignIds"] = sorted(selected_campaign_ids)
            result["matchedDeviceTaskIds"] = sorted(matched_device_task_ids)
            result["matchedDeviceIds"] = sorted(matched_device_ids)
            result["campaignAtomic"] = False
            result["releasedAgentLeaseDeviceIds"] = self._release_agent_leases(lease_device_ids)
            return result
        result = self._cancel_campaigns(tasks, selected_campaign_ids, message="任务已紧急停止")
        result["schema"] = "loom.matrix.emergency_stop.v1"
        result["matchedCampaignIds"] = sorted(selected_campaign_ids)
        result["matchedDeviceTaskIds"] = sorted(matched_device_task_ids)
        result["matchedDeviceIds"] = sorted(matched_device_ids)
        result["campaignAtomic"] = True
        result["releasedAgentLeaseDeviceIds"] = self._release_agent_leases(lease_device_ids)
        return result

    @_matrix_state_guard
    def record_result(
        self,
        device_task_id: str,
        *,
        ok: bool,
        duration_ms: int,
        failure_reason: str = "",
        failure_code: str = "",
        task_id: str = "",
        outcome_indeterminate: bool = False,
        execution_may_continue: bool = False,
    ) -> Json:
        tasks = self._load_tasks()
        found: Json | None = None
        campaign_id = ""
        mission_id = ""
        for campaign in tasks.get("campaigns", []):
            for mission in campaign.get("missions", []):
                for device_task in mission.get("deviceTasks", []):
                    if device_task.get("deviceTaskId") == device_task_id:
                        found = device_task
                        campaign_id = str(campaign.get("campaignId") or "")
                        mission_id = str(mission.get("missionId") or "")
                        break
        if found is None:
            return {"ok": False, "error": "deviceTask not found"}
        task_status = str(found.get("status") or "")
        if task_status in _DEVICE_TASK_TERMINAL_STATES or task_status == "paused":
            return {
                "ok": False,
                "terminal": task_status in _DEVICE_TASK_TERMINAL_STATES,
                "cancelled": task_status == "cancelled",
                "paused": task_status == "paused",
                "status": task_status,
                "deviceTaskId": device_task_id,
            }
        found["status"] = (
            "succeeded"
            if ok
            else "needs_human"
            if outcome_indeterminate or execution_may_continue
            else "failed"
        )
        found["durationMs"] = int(duration_ms)
        found["failureCode"] = "" if ok else _clip(failure_code, 100)
        found["failureReason"] = _clip(failure_reason, 200)
        if not ok:
            if task_id:
                found["taskId"] = _clip(task_id, 160)
            if outcome_indeterminate:
                found["outcomeIndeterminate"] = True
            if execution_may_continue:
                found["executionMayContinue"] = True
        found["updatedAt"] = _now_iso()
        for step in found.get("steps", []):
            if step.get("status") == "running":
                step["status"] = "succeeded" if ok else "failed"
                step["updatedAt"] = found["updatedAt"]
        self._refresh_campaign_status(tasks, campaign_id)
        self._write_json(self.tasks_path, tasks)
        event_type = "result" if ok else "error"
        self._append_event(
            event_type,
            campaign_id,
            mission_id,
            device_task_id,
            str(found.get("deviceId") or ""),
            "任务完成" if ok else "任务失败",
            assignment_id=str(found.get("assignmentId") or ""),
        )
        self._update_device(
            str(found.get("deviceId") or ""),
            {
                "currentTaskId": "",
                "lastResult": "成功" if ok else (failure_reason or "失败"),
                "failureCount": 0 if ok else None,
            },
            increment_failure=not ok,
        )
        record = {
            "schema": "loom.matrix.experience_record.v1",
            "timestamp": _now_iso(),
            "assignmentId": found.get("assignmentId"),
            "deviceTaskId": device_task_id,
            "deviceId": found.get("deviceId"),
            "executionLayer": found.get("executionLayer"),
            "profile": found.get("profile"),
            "mode": found.get("mode"),
            "ok": bool(ok),
            "durationMs": int(duration_ms),
            "failureCode": "" if ok else _clip(failure_code, 100),
            "failureReason": _clip(failure_reason, 200),
            "promptHash": found.get("promptHash"),
        }
        if not ok and task_id:
            record["taskId"] = _clip(task_id, 160)
        if not ok and outcome_indeterminate:
            record["outcomeIndeterminate"] = True
        if not ok and execution_may_continue:
            record["executionMayContinue"] = True
        self._append_jsonl(self.experience_path, record)
        return {"ok": True, "record": _redact_json(record)}

    def _find_device_task(self, device_task_id: str, *, tasks: Json | None = None) -> Json | None:
        tasks = tasks if isinstance(tasks, dict) else self._load_tasks()
        for campaign in tasks.get("campaigns", []):
            for mission in campaign.get("missions", []):
                for device_task in mission.get("deviceTasks", []):
                    if device_task.get("deviceTaskId") == device_task_id:
                        return {"campaign": campaign, "mission": mission, "deviceTask": device_task}
        return None

    def _transition_task(
        self,
        device_task_id: str,
        *,
        expected: set[str],
        status: str,
        event_type: str,
    ) -> Json:
        tasks = self._load_tasks()
        found, previous_status = self._apply_task_transition(
            tasks,
            device_task_id,
            expected=expected,
            status=status,
        )
        device_task = found["deviceTask"]
        mission = found["mission"]
        campaign = found["campaign"]
        self._write_json(self.tasks_path, tasks)
        self._append_event(
            event_type,
            str(campaign.get("campaignId") or ""),
            str(mission.get("missionId") or ""),
            str(device_task.get("deviceTaskId") or ""),
            str(device_task.get("deviceId") or ""),
            f"Device task {status}",
            assignment_id=str(device_task.get("assignmentId") or ""),
        )
        return {
            "status": "applied",
            "previousStatus": previous_status,
            "campaign": _redact_json(campaign),
            "deviceTask": _redact_json(device_task),
        }

    def _apply_task_transition(
        self,
        tasks: Json,
        device_task_id: str,
        *,
        expected: set[str],
        status: str,
    ) -> tuple[Json, str]:
        found = self._find_device_task(device_task_id, tasks=tasks)
        if not found:
            raise MatrixTargetError("matrix_task_not_found", "Device task was not found")
        device_task = found["deviceTask"]
        previous_status = str(device_task.get("status") or "")
        if previous_status not in expected:
            raise MatrixTargetError(
                "matrix_invalid_task_transition",
                f"Cannot transition device task from {previous_status or 'unknown'} to {status}",
            )
        now = _now_iso()
        device_task["status"] = status
        device_task["updatedAt"] = now
        mission = found["mission"]
        campaign = found["campaign"]
        child_statuses = {
            str(item.get("status") or "")
            for item in mission.get("deviceTasks", [])
            if isinstance(item, dict)
        }
        if child_statuses and child_statuses.issubset({"paused"}):
            mission["status"] = "paused"
        elif child_statuses and child_statuses.issubset({"queued"}):
            mission["status"] = "queued"
        else:
            mission["status"] = "running"
        mission["updatedAt"] = now
        mission_statuses = {
            str(item.get("status") or "")
            for item in campaign.get("missions", [])
            if isinstance(item, dict)
        }
        if mission_statuses and mission_statuses.issubset({"paused"}):
            campaign["status"] = "paused"
        elif mission_statuses and mission_statuses.issubset({"queued"}):
            campaign["status"] = "queued"
        else:
            campaign["status"] = "running"
        campaign["updatedAt"] = now
        return found, previous_status

    def _require_device(self, device_id: str, *, writable: bool = False) -> Json:
        device = next(
            (item for item in self._load_devices() if str(item.get("deviceId") or "") == device_id),
            None,
        )
        if not isinstance(device, dict):
            raise MatrixTargetError("matrix_target_not_found", "Device was not found")
        if writable and not bool(device.get("online")):
            raise MatrixTargetError("device_offline", "Device is offline")
        return device

    def _load_leases(self) -> Json:
        if not os.path.exists(self.leases_path):
            return {"schema": "loom.matrix.device_leases.v1", "leases": []}
        try:
            with open(self.leases_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MatrixTargetError(
                "matrix_lease_ledger_unavailable",
                "Device lease ledger is unavailable",
            ) from exc
        if not isinstance(state, dict) or not isinstance(state.get("leases"), list):
            raise MatrixTargetError(
                "matrix_lease_ledger_unavailable",
                "Device lease ledger is invalid",
            )
        if any(not isinstance(item, dict) for item in state["leases"]):
            raise MatrixTargetError(
                "matrix_lease_ledger_unavailable",
                "Device lease ledger contains invalid entries",
            )
        return state

    def _write_leases(self, state: Json) -> None:
        state["schema"] = "loom.matrix.device_leases.v1"
        state["leases"] = [
            item
            for item in state.get("leases", [])
            if isinstance(item, dict) and _remaining_ttl_ms(item.get("expiresAt")) > 0
        ]
        self._write_json(self.leases_path, state)

    def _active_lease(self, state: Json, device_id: str) -> Json | None:
        active = None
        retained = []
        for lease in state.get("leases", []):
            if not isinstance(lease, dict) or _remaining_ttl_ms(lease.get("expiresAt")) <= 0:
                continue
            retained.append(lease)
            if lease.get("deviceId") == device_id:
                active = lease
        state["leases"] = retained
        return active

    def _load_control_commands(self) -> Json:
        state = self._read_json(
            self.control_commands_path,
            {"schema": "loom.matrix.control_commands.v1", "commands": []},
        )
        if not isinstance(state.get("commands"), list):
            state["commands"] = []
        return state

    def _write_control_commands(self, state: Json) -> None:
        state["schema"] = "loom.matrix.control_commands.v1"
        state["commands"] = [
            item for item in state.get("commands", []) if isinstance(item, dict)
        ][-MATRIX_CONTROL_COMMAND_LIMIT:]
        self._write_json(self.control_commands_path, state)

    def _release_agent_leases(
        self,
        device_ids: set[str] | None,
        *,
        holder_ids: set[str] | None = None,
        lease_ids: set[str] | None = None,
    ) -> list[str]:
        state = self._load_leases()
        released: set[str] = set()
        retained: list[Json] = []
        for lease in state["leases"]:
            device_id = str(lease.get("deviceId") or "")
            matches_scope = device_ids is None or device_id in device_ids
            matches_holder = holder_ids is None or str(lease.get("holderId") or "") in holder_ids
            matches_lease = lease_ids is None or str(lease.get("leaseId") or "") in lease_ids
            if lease.get("holderType") == "agent" and matches_scope and matches_holder and matches_lease:
                released.add(device_id)
                continue
            retained.append(lease)
        state["leases"] = retained
        self._write_leases(state)
        return sorted(released)

    def _refresh_campaign_status(self, tasks: Json, campaign_id: str) -> None:
        now = _now_iso()
        for campaign in tasks.get("campaigns", []):
            if campaign.get("campaignId") != campaign_id:
                continue
            mission_statuses = []
            for mission in campaign.get("missions", []):
                device_tasks = [item for item in mission.get("deviceTasks", []) if isinstance(item, dict)]
                statuses = {str(item.get("status") or "") for item in device_tasks}
                if not device_tasks:
                    mission["status"] = "queued"
                elif statuses.issubset({"queued"}):
                    mission["status"] = "queued"
                elif statuses.issubset({"paused"}):
                    mission["status"] = "paused"
                elif statuses.issubset({"succeeded"}):
                    mission["status"] = "succeeded"
                elif statuses and statuses.issubset({"failed", "needs_human", "succeeded", "cancelled"}):
                    mission["status"] = (
                        "failed"
                        if statuses & {"failed", "needs_human"}
                        else "cancelled"
                    )
                else:
                    mission["status"] = "running"
                mission["updatedAt"] = now
                mission_statuses.append(mission["status"])
            if mission_statuses and all(status == "succeeded" for status in mission_statuses):
                campaign["status"] = "succeeded"
            elif any(status == "failed" for status in mission_statuses):
                campaign["status"] = "failed"
            elif any(status == "running" for status in mission_statuses):
                campaign["status"] = "running"
            elif mission_statuses and all(status == "paused" for status in mission_statuses):
                campaign["status"] = "paused"
            elif any(status == "queued" for status in mission_statuses):
                campaign["status"] = "queued"
            elif any(status == "cancelled" for status in mission_statuses):
                campaign["status"] = "cancelled"
            campaign["updatedAt"] = now
            return

    def experience_report(self) -> Json:
        rows = self._read_jsonl(self.experience_path)
        total = len(rows)
        success = sum(1 for item in rows if item.get("ok") is True)
        durations = [int(item.get("durationMs") or 0) for item in rows if int(item.get("durationMs") or 0) > 0]
        by_layer: dict[str, Json] = {}
        for item in rows:
            layer = str(item.get("executionLayer") or "unknown")
            bucket = by_layer.setdefault(layer, {"total": 0, "success": 0, "failures": 0})
            bucket["total"] += 1
            if item.get("ok") is True:
                bucket["success"] += 1
            else:
                bucket["failures"] += 1
        suggestions = []
        for layer, bucket in by_layer.items():
            if bucket["success"] >= 1:
                suggestions.append(
                    {
                        "id": f"matrix_tpl_{layer}",
                        "executionLayer": layer,
                        "reason": "该路径已有成功记录，可在人工确认后固化为模板。",
                        "requiresConfirmation": True,
                    }
                )
        return {
            "schema": "loom.matrix.experience.v1",
            "summary": {
                "total": total,
                "success": success,
                "failure": total - success,
                "successRate": round(success / total, 4) if total else 0,
                "avgDurationMs": round(sum(durations) / len(durations), 2) if durations else 0,
            },
            "byLayer": by_layer,
            "templateSuggestions": suggestions,
        }

    def _target_devices(self, target: Json) -> list[Json]:
        devices = [_public_device(item) for item in self._load_devices()]
        raw_ids = target.get("deviceIds") or target.get("devices") or target.get("deviceId")
        if isinstance(raw_ids, str):
            wanted_ids = {_device_id(raw_ids)} if raw_ids.strip() else set()
        elif isinstance(raw_ids, list):
            wanted_ids = {_device_id(item) for item in raw_ids if str(item or "").strip()}
        else:
            wanted_ids = set()
        raw_groups = target.get("groups") or target.get("group")
        if isinstance(raw_groups, str):
            wanted_groups = {raw_groups}
        elif isinstance(raw_groups, list):
            wanted_groups = {str(item) for item in raw_groups}
        else:
            wanted_groups = set()
        selector_count = sum((bool(wanted_ids), bool(wanted_groups), _truthy(target.get("allOnline"))))
        if selector_count > 1:
            raise MatrixTargetError(
                "matrix_invalid_target",
                "deviceIds、groups 和 allOnline 只能选择一种目标方式。",
            )
        if wanted_ids:
            matched = [item for item in devices if item.get("deviceId") in wanted_ids]
            matched_ids = {str(item.get("deviceId") or "") for item in matched}
            missing_ids = sorted(wanted_ids - matched_ids)
            if missing_ids:
                raise MatrixTargetError("matrix_target_not_found", f"未找到目标手机：{', '.join(missing_ids)}")
        elif wanted_groups:
            matched = [
                item
                for item in devices
                if item.get("group") in wanted_groups or wanted_groups.intersection(set(item.get("groups") or []))
            ]
            if not matched:
                raise MatrixTargetError("matrix_target_not_found", f"未找到目标手机分组：{', '.join(sorted(wanted_groups))}")
        elif _truthy(target.get("allOnline")):
            matched = [item for item in devices if item.get("online")]
        else:
            raise MatrixTargetError("matrix_no_target", "请明确指定目标手机、手机分组或 allOnline，防止任务误广播。")

        if not matched:
            raise MatrixTargetError("matrix_no_online_devices", "没有可执行的在线手机，请先在手机页完成连接检测。")
        offline_ids = [str(item.get("deviceId") or "") for item in matched if not item.get("online")]
        if len(offline_ids) == len(matched):
            raise MatrixTargetError("matrix_no_online_devices", "所选手机均已离线，请重新检测连接后再发布任务。")
        if offline_ids:
            raise MatrixTargetError("matrix_target_offline", f"所选手机包含离线设备：{', '.join(offline_ids)}")
        return matched

    def _check_safety(self, prompt: str, *, confirmed: bool) -> None:
        if _needs_confirmation(prompt) and not confirmed:
            raise MatrixSafetyError("safety_confirmation_required", "批量触达、私信、评论或自动回复任务需要用户明确确认。")

    def _update_device(self, device_id: str, patch: Json, *, increment_failure: bool = False) -> None:
        if not device_id:
            return
        devices = self._load_registered_devices()
        found = False
        for device in devices:
            if device.get("deviceId") != device_id:
                continue
            for key, value in patch.items():
                if value is not None:
                    device[key] = value
            if increment_failure:
                device["failureCount"] = int(device.get("failureCount") or 0) + 1
            device["updatedAt"] = _now_iso()
            found = True
            break
        if not found:
            device = {
                "deviceId": device_id,
                "name": device_id,
                "group": "default",
                "groups": ["default"],
                "online": False,
                "heartbeatAt": "",
                "currentTaskId": "",
                "currentScreenSummary": "",
                "failureCount": 0,
                "model": DEFAULT_PHONE_MODEL,
                "lastResult": "",
                "updatedAt": _now_iso(),
            }
            for key, value in patch.items():
                if value is not None:
                    device[key] = value
            if increment_failure:
                device["failureCount"] = int(device.get("failureCount") or 0) + 1
            devices.append(device)
        self._write_json(self.devices_path, {"schema": "loom.matrix.devices.v1", "devices": devices})

    def _append_event(
        self,
        event_type: str,
        campaign_id: str,
        mission_id: str,
        device_task_id: str,
        device_id: str,
        message: str,
        *,
        assignment_id: str = "",
    ) -> None:
        event = {
            "schema": "loom.matrix.event.v1",
            "eventId": f"evt_{uuid.uuid4().hex[:12]}",
            "seq": self._next_event_seq(),
            "timestamp": _now_iso(),
            "type": event_type,
            "campaignId": campaign_id,
            "missionId": mission_id,
            "deviceTaskId": device_task_id,
            "deviceId": device_id,
            "message": message,
        }
        if assignment_id:
            event["assignmentId"] = assignment_id
        self._append_jsonl(
            self.events_path,
            event,
        )

    def _next_event_seq(self) -> int:
        state = self._read_json(
            self.event_sequence_path,
            {"schema": "loom.matrix.event_sequence.v1", "lastSeq": 0},
        )
        last_seq = max(0, _int(state.get("lastSeq"), 0))
        if last_seq == 0:
            last_seq = max(
                (_int(event.get("seq"), index) for index, event in enumerate(self._load_events(), start=1)),
                default=0,
            )
        next_seq = last_seq + 1
        self._write_json(
            self.event_sequence_path,
            {"schema": "loom.matrix.event_sequence.v1", "lastSeq": next_seq},
        )
        return next_seq

    def _load_devices(self) -> list[Json]:
        phone_devices, phone_config_is_authoritative = self._load_phone_config_inventory()
        registered_devices = self._load_registered_devices()
        merged: dict[str, Json] = {}
        order: list[str] = []
        for device in phone_devices:
            device_id = str(device.get("deviceId") or "")
            if not device_id:
                continue
            merged[device_id] = device
            order.append(device_id)
        for device in registered_devices:
            device_id = str(device.get("deviceId") or "")
            if not device_id:
                continue
            base = merged.get(device_id, {})
            if phone_config_is_authoritative and not base:
                continue
            merged_device = {
                **base,
                **device,
                "source": "matrix-registry" if not base else base.get("source", "phone-config"),
                "selected": bool(base.get("selected")),
            }
            if base:
                # Phone configuration owns stable identity. Runtime heartbeats may
                # update presence and task state, but must never rename siblings.
                for key in ("name", "group", "groups", "configSource"):
                    if key in base:
                        merged_device[key] = base[key]
            merged[device_id] = merged_device
            if device_id not in order:
                order.append(device_id)
        return [merged[device_id] for device_id in order if device_id in merged]

    def _load_registered_devices(self) -> list[Json]:
        data = self._read_json(self.devices_path, {"devices": []})
        devices = data.get("devices") if isinstance(data, dict) else []
        return [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else []

    def _load_phone_config_inventory(self) -> tuple[list[Json], bool]:
        data = self._read_json(
            self.phone_devices_path,
            {"selectedDeviceId": "", "devices": None},
            quarantine=False,
        )
        devices = data.get("devices") if isinstance(data, dict) else []
        if not isinstance(devices, list):
            return [], False
        selected_id = _device_id(data.get("selectedDeviceId") or "")
        model = self._phone_model()
        rows: list[Json] = []
        for index, item in enumerate(devices, start=1):
            if not isinstance(item, dict):
                continue
            device_id = _device_id(item.get("id") or item.get("deviceId") or item.get("name") or f"phone-{index}")
            name = _clip(item.get("name") or item.get("id") or device_id, 80)
            last_seen = _clip(item.get("lastSeenAt") or item.get("lastCheckedAt") or "", 64)
            rows.append(
                {
                    "deviceId": device_id,
                    "name": name,
                    "group": _clip(item.get("group") or "本机手机", 80),
                    "groups": ["本机手机"],
                    "online": False,
                    "heartbeatAt": last_seen,
                    "currentTaskId": "",
                    "currentScreenSummary": "已保存手机连接配置",
                    "failureCount": 0,
                    "model": model,
                    "lastResult": "",
                    "updatedAt": last_seen,
                    "source": "phone-config",
                    "configSource": self.phone_devices_path,
                    "selected": device_id == selected_id or (not selected_id and index == 1),
                }
            )
        return rows, True

    def _phone_model(self) -> str:
        wire_path = getattr(self.paths, "wire_current", "")
        data = self._read_json(wire_path, {}, quarantine=False) if wire_path else {}
        models = data.get("models") if isinstance(data, dict) else {}
        if isinstance(models, dict):
            model = _clip(models.get("phone"), 120)
            if model:
                return model
        return DEFAULT_PHONE_MODEL

    def _load_tasks(self) -> Json:
        data = self._read_json(self.tasks_path, {"schema": "loom.matrix.tasks.v1", "campaigns": []})
        if not isinstance(data, dict):
            return {"schema": "loom.matrix.tasks.v1", "campaigns": []}
        if not isinstance(data.get("campaigns"), list):
            data["campaigns"] = []
        return data

    def _load_acquisition_state(self) -> Json:
        data = self._read_json(
            self.acquisition_path,
            {
                "schema": "loom.customer_acquisition.v1",
                "updatedAt": "",
                "contentTasks": [],
                "leads": [],
                "customers": [],
                "drafts": [],
                "agentRuns": [],
                "logs": [],
                "sop": _default_acquisition_sop(),
            },
        )
        for key in ("contentTasks", "leads", "customers", "drafts", "agentRuns", "logs"):
            if not isinstance(data.get(key), list):
                data[key] = []
        if not isinstance(data.get("sop"), list):
            data["sop"] = _default_acquisition_sop()
        data["schema"] = "loom.customer_acquisition.v1"
        return data

    def _write_acquisition_state(self, state: Json) -> None:
        state["schema"] = "loom.customer_acquisition.v1"
        state["contentTasks"] = state.get("contentTasks", [])[-200:]
        state["leads"] = state.get("leads", [])[-500:]
        state["customers"] = state.get("customers", [])[-500:]
        state["drafts"] = state.get("drafts", [])[-500:]
        state["agentRuns"] = state.get("agentRuns", [])[-200:]
        state["logs"] = state.get("logs", [])[-500:]
        self._write_json(self.acquisition_path, state)

    def _load_events(self) -> list[Json]:
        events, _truncation = self._load_events_with_truncation()
        return events

    def _load_events_with_truncation(self) -> tuple[list[Json], Json]:
        paths = [
            f"{self.events_path}.{index}"
            for index in range(MATRIX_EVENT_ARCHIVE_COUNT, 0, -1)
        ]
        paths.append(self.events_path)
        rows: list[Json] = []
        reasons: list[str] = []
        omitted_bytes = 0
        omitted_events = 0
        for path in paths:
            path_rows, path_truncation = self._read_jsonl_with_truncation(path)
            rows.extend(path_rows)
            omitted_bytes += int(path_truncation.get("omittedBytes") or 0)
            omitted_events += int(path_truncation.get("omittedEvents") or 0)
            for reason in path_truncation.get("reasons") or []:
                if reason not in reasons:
                    reasons.append(reason)
        if len(rows) > 1000:
            omitted_events += len(rows) - 1000
            if "internal_event_limit" not in reasons:
                reasons.append("internal_event_limit")
            rows = rows[-1000:]
        return rows, {
            "reason": reasons[0] if reasons else "",
            "reasons": reasons,
            "omittedBytes": omitted_bytes,
            "omittedEvents": omitted_events,
        }

    @_matrix_state_guard
    def _read_json(self, path: str, default: Json, *, quarantine: bool = True) -> Json:
        if not os.path.exists(path):
            return dict(default)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else dict(default)
        except (UnicodeError, json.JSONDecodeError):
            if quarantine:
                self._quarantine_corrupt_json(path)
            return dict(default)
        except OSError:
            return dict(default)

    def _quarantine_corrupt_json(self, path: str) -> None:
        suffix = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        try:
            os.replace(path, f"{path}.corrupt-{suffix}")
        except OSError:
            return

    @_matrix_state_guard
    def _write_json(self, path: str, data: Json) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}-", suffix=".tmp", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_redact_json(data), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    @_matrix_state_guard
    def _append_jsonl(self, path: str, data: Json) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(_redact_json(data), ensure_ascii=False, separators=(",", ":")) + "\n"
        if path == self.events_path:
            self._rotate_jsonl_if_needed(path, len(line.encode("utf-8")))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)

    def _rotate_jsonl_if_needed(self, path: str, incoming_bytes: int) -> None:
        try:
            current_bytes = os.path.getsize(path)
        except OSError:
            current_bytes = 0
        if current_bytes <= 0 or current_bytes + incoming_bytes <= MATRIX_EVENT_FILE_MAX_BYTES:
            return
        oldest = f"{path}.{MATRIX_EVENT_ARCHIVE_COUNT}"
        try:
            if os.path.exists(oldest):
                os.remove(oldest)
            for index in range(MATRIX_EVENT_ARCHIVE_COUNT - 1, 0, -1):
                source = f"{path}.{index}"
                if os.path.exists(source):
                    os.replace(source, f"{path}.{index + 1}")
            if os.path.exists(path):
                os.replace(path, f"{path}.1")
        except OSError:
            # Logging must never break task execution; the next append may retry rotation.
            return

    @_matrix_state_guard
    def _read_jsonl(self, path: str) -> list[Json]:
        rows, _truncation = self._read_jsonl_with_truncation(path)
        return rows

    def _read_jsonl_with_truncation(self, path: str) -> tuple[list[Json], Json]:
        if not os.path.exists(path):
            return [], {"reasons": [], "omittedBytes": 0, "omittedEvents": 0}
        rows: list[Json] = []
        omitted_bytes = 0
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as handle:
                if size > MATRIX_EVENT_TAIL_BYTES:
                    requested_start = max(0, size - MATRIX_EVENT_TAIL_BYTES)
                    handle.seek(requested_start - 1)
                    previous = handle.read(1)
                    handle.seek(requested_start)
                    if previous not in {b"\n", b"\r"}:
                        handle.readline()
                    omitted_bytes = handle.tell()
                payload = handle.read()
        except OSError:
            return [], {"reasons": [], "omittedBytes": 0, "omittedEvents": 0}
        for raw_line in payload.splitlines():
            try:
                line = raw_line.decode("utf-8", errors="replace")
            except AttributeError:
                line = str(raw_line)
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        omitted_events = max(0, len(rows) - 1000)
        reasons: list[str] = []
        if omitted_bytes:
            reasons.append("jsonl_tail_limit")
        if omitted_events:
            reasons.append("internal_event_limit")
        return rows[-1000:], {
            "reasons": reasons,
            "omittedBytes": omitted_bytes,
            "omittedEvents": omitted_events,
        }


def _without_volatile_event_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile_event_fields(item)
            for key, item in value.items()
            if key not in _VOLATILE_EVENT_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile_event_fields(item) for item in value]
    return value


def _public_device(device: Json) -> Json:
    current_task_id = str(device.get("currentTaskId") or "")
    running_task_count = _int(device.get("runningTaskCount"), 0)
    failure_count = int(device.get("failureCount") or 0)
    online = bool(device.get("online"))
    stream_status = str(device.get("streamStatus") or ("connected" if online else "offline"))
    stream_latency_ms = _int(device.get("streamLatencyMs"), 0)
    presence_age_ms = _timestamp_age_ms(
        device.get("presenceObservedAt") or device.get("lastEventAt") or device.get("heartbeatAt") or ""
    )
    if online and presence_age_ms >= 0:
        stream_latency_ms = max(stream_latency_ms, presence_age_ms)
        if presence_age_ms > MATRIX_PRESENCE_OFFLINE_MS:
            online = False
            stream_status = "offline"
        elif presence_age_ms > MATRIX_PRESENCE_UNSTABLE_MS and stream_status == "connected":
            stream_status = "unstable"
    if not online:
        current_task_id = ""
        running_task_count = 0
    busy = bool(device.get("busy") or current_task_id or running_task_count) and online
    return {
        "deviceId": str(device.get("deviceId") or ""),
        "name": str(device.get("name") or device.get("deviceId") or ""),
        "group": str(device.get("group") or "default"),
        "groups": [str(item) for item in (device.get("groups") or []) if str(item or "").strip()][:20],
        "online": online,
        "busy": busy,
        "heartbeatAt": str(device.get("heartbeatAt") or ""),
        "presenceObservedAt": str(device.get("presenceObservedAt") or ""),
        "lastEventAt": str(device.get("lastEventAt") or ""),
        "streamStatus": stream_status,
        "streamLatencyMs": stream_latency_ms,
        "currentPackage": str(device.get("currentPackage") or ""),
        "foregroundApp": str(device.get("foregroundApp") or ""),
        "accessibilityRunning": device.get("accessibilityRunning") if isinstance(device.get("accessibilityRunning"), bool) else None,
        "screenOn": device.get("screenOn") if isinstance(device.get("screenOn"), bool) else None,
        "deviceLocked": device.get("deviceLocked") if isinstance(device.get("deviceLocked"), bool) else None,
        "runningTaskCount": running_task_count,
        "currentStep": str(device.get("currentStep") or ""),
        "headline": str(device.get("headline") or ""),
        "needsCodex": bool(device.get("needsCodex")),
        "progressLog": _matrix_progress_log(device.get("progressLog")),
        "latestProgressText": str(device.get("latestProgressText") or ""),
        "currentTaskId": current_task_id,
        "currentScreenSummary": str(device.get("currentScreenSummary") or ""),
        "failureCount": failure_count,
        "model": str(device.get("model") or DEFAULT_PHONE_MODEL),
        "lastResult": str(device.get("lastResult") or ""),
        "updatedAt": str(device.get("updatedAt") or ""),
        "source": str(device.get("source") or "matrix-registry"),
        "configSource": str(device.get("configSource") or ""),
        "selected": bool(device.get("selected")),
        "platform": str(device.get("platform") or device.get("group") or "手机"),
        "account": str(device.get("account") or ""),
        "progress": _int(device.get("progress"), 10 if current_task_id else 0),
        "queue": _int(device.get("queue"), 0),
        "elapsedMs": _int(device.get("elapsedMs"), 0),
    }


def _steps_for_layer(layer: str) -> list[Json]:
    if layer == "direct":
        return [
            {"stepId": "step_direct", "kind": "direct", "label": "Direct 快路径", "status": "running", "timeoutSec": 8},
            {"stepId": "step_result", "kind": "result", "label": "收集结果", "status": "queued", "timeoutSec": 8},
        ]
    if layer == "template":
        return [
            {"stepId": "step_template", "kind": "template", "label": "Template 固化流程", "status": "running", "timeoutSec": 12},
            {"stepId": "step_result", "kind": "result", "label": "收集结果", "status": "queued", "timeoutSec": 12},
        ]
    return [
        {"stepId": "step_agent", "kind": "agent", "label": "Agent 推理执行", "status": "running", "timeoutSec": 20},
        {"stepId": "step_result", "kind": "result", "label": "收集结果", "status": "queued", "timeoutSec": 15},
    ]


def _execution_layer(*, mode: str, action: str, template: str, prompt: str) -> str:
    if mode == "observe" or action:
        return "direct"
    if template:
        return "template"
    if _template_from_prompt(prompt):
        return "template"
    return "agent"


def _direct_action(value: Any, prompt: str) -> str:
    text = re.sub(r"\s+", "", str(value or prompt or "").strip().lower())
    if text in {"back", "pressback", "返回", "返回上一页", "上一页", "后退"}:
        return "back"
    if text in {"home", "presshome", "回到桌面", "返回桌面", "桌面", "主页", "回主页"}:
        return "home"
    return ""


def _template_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", "", str(prompt or "").strip().lower())
    if any(token in text for token in {"打开系统设置", "打开设置", "系统设置", "opensettings"}):
        return "open-settings"
    if any(token in text for token in {"读取当前屏幕", "读屏", "screen-summary"}):
        return "read-screen"
    return ""


def _needs_confirmation(prompt: str) -> bool:
    return any(marker in str(prompt or "") for marker in OUTREACH_MARKERS)


def _parse_acquisition_import_rows(raw: Json) -> list[Json]:
    rows = raw.get("leads") or raw.get("rows") or raw.get("items")
    if isinstance(rows, list):
        return [_normalize_acquisition_row(item) for item in rows if isinstance(item, dict)][:200]
    summary = _safe_lead_summary(raw.get("leadSummary") or raw.get("summary"), limit=360)
    if summary:
        return [_normalize_acquisition_row({"summary": summary, "title": raw.get("title") or raw.get("topic")})]
    text = str(raw.get("sourceText") or raw.get("text") or "").strip()
    if not text:
        return []
    parsed = _try_parse_acquisition_json_rows(text)
    if parsed:
        return parsed[:200]
    csv_rows = _try_parse_acquisition_csv_rows(text)
    if csv_rows:
        return csv_rows[:200]
    return [
        _normalize_acquisition_row({"summary": line.strip(), "title": line.strip()[:40]})
        for line in text.splitlines()
        if line.strip()
    ][:200]


def _try_parse_acquisition_json_rows(text: str) -> list[Json]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        rows = data.get("comments") or data.get("leads") or data.get("items") or data.get("rows")
        if isinstance(rows, list):
            return [_normalize_acquisition_row(item) for item in rows if isinstance(item, dict)]
        return [_normalize_acquisition_row(data)]
    if isinstance(data, list):
        return [_normalize_acquisition_row(item) for item in data if isinstance(item, dict)]
    return []


def _try_parse_acquisition_csv_rows(text: str) -> list[Json]:
    sample = text.lstrip("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(sample))
        if reader.fieldnames and len(reader.fieldnames) > 1:
            rows = [_normalize_acquisition_row(dict(row)) for row in reader if any(str(value or "").strip() for value in row.values())]
            if rows:
                return rows
        plain_reader = csv.reader(io.StringIO(sample))
        return [
            _normalize_acquisition_row({"title": row[0] if row else "", "summary": " ".join(cell for cell in row if cell)})
            for row in plain_reader
            if row and any(cell.strip() for cell in row)
        ]
    except csv.Error:
        return []


def _normalize_acquisition_row(row: Json) -> Json:
    def pick(*keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    return {
        "platform": pick("platform", "平台", "来源平台", "sourcePlatform"),
        "channel": pick("channel", "渠道", "来源渠道"),
        "title": pick("title", "客户昵称/账号", "客户昵称", "昵称", "账号", "nickname", "account", "author"),
        "nickname": pick("nickname", "客户昵称/账号", "客户昵称", "昵称", "账号", "author"),
        "summary": pick("summary", "线索内容", "原始线索内容", "评论内容", "内容", "comment", "rawContent", "description"),
        "draftBody": pick("draftBody", "跟进话术草稿", "草稿", "draft", "reply", "body"),
        "profileUrl": pick("profileUrl", "主页链接", "主页或内容链接", "主页", "profile", "url"),
        "contentUrl": pick("contentUrl", "内容链接", "作品链接", "noteUrl"),
    }


def _matrix_progress_log(value: Any) -> list[Json]:
    items: list[Json] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        item_type = _clip(raw.get("type"), 32).lower()
        if item_type not in {"thinking", "tool", "success", "error", "status"}:
            continue
        item: Json = {
            "round": max(0, _int(raw.get("round"), 0)),
            "type": item_type,
            "text": _safe_lead_summary(raw.get("text"), limit=240),
        }
        tool_id = _clip(raw.get("toolId"), 80).lower()
        if re.fullmatch(r"[a-z0-9_.-]+", tool_id):
            item["toolId"] = tool_id
        raw_time = raw.get("time")
        if isinstance(raw_time, (int, float)) and raw_time >= 0:
            item["time"] = raw_time
        items.append(item)
    return items[-3:]


def _qualify_acquisition_lead(summary: str, *, topic: Any = "", target: Any = "") -> Json:
    text = f"{summary} {topic or ''} {target or ''}".lower()
    high_tokens = ["报价", "价格", "预算", "合作", "预约", "方案", "案例", "获客", "加微信", "私域", "线索", "客户"]
    medium_tokens = ["了解", "咨询", "怎么", "如何", "需要", "想看", "有没有", "可以吗"]
    score = 30
    reasons: list[str] = []
    for token in high_tokens:
        if token.lower() in text:
            score += 15
            reasons.append(f"命中高意向词：{token}")
    for token in medium_tokens:
        if token.lower() in text:
            score += 8
            reasons.append(f"命中咨询词：{token}")
    score = max(0, min(score, 100))
    if score >= 70:
        level = "high"
        action = "优先人工确认跟进草稿，并记录行业、城市、预算和时间窗口。"
    elif score >= 50:
        level = "medium"
        action = "进入客户池，先用低压开场白确认场景和需求。"
    else:
        level = "low"
        action = "先保留为线索，等待更多互动信号后再跟进。"
    return {
        "score": score,
        "intentLevel": level,
        "need": _safe_lead_summary(summary, limit=220),
        "recommendedAction": action,
        "reasons": reasons[:6] or ["未命中强意向词，按普通线索保留"],
    }


def _build_acquisition_followup_draft(lead: Json, knowledge: str) -> str:
    title = _safe_lead_summary(lead.get("nickname") or lead.get("title") or "您好", limit=60)
    need = _safe_lead_summary(lead.get("need") or lead.get("summary") or "", limit=180)
    action = _safe_lead_summary(lead.get("recommendedAction") or "先确认需求，再人工跟进。", limit=140)
    return _safe_lead_summary(
        f"{title}，看到您提到“{need}”。我先不打扰您做决定，可以根据您的行业和城市整理一版试跑思路：{knowledge} 下一步建议：{action}",
        limit=500,
    )


def _acquisition_dedupe_key(platform: str, url: str, title: str, summary: str) -> str:
    source = "|".join([platform, url, title, summary[:160]]).lower()
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _safe_lead_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, flags=re.I):
        return ""
    return _safe_lead_summary(text, limit=260)


def _acquisition_source(value: Any) -> str:
    text = str(value or "manual_import").strip().lower()
    if text in {"manual_import", "phone_agent", "demo_flow", "agent_result", "csv_import"}:
        return text
    return "manual_import"


def _acquisition_phone_task_payload(raw: Json, agent_run: Json) -> Json:
    device_id = _clip(agent_run.get("deviceId") or raw.get("deviceId") or raw.get("device") or "phone-1", 80) or "phone-1"
    platform = _acquisition_platform(agent_run.get("platform") or raw.get("platform"))
    topic = _clip(raw.get("topic") or f"{platform} 手机 Agent 获客任务", 120)
    action = _clip(agent_run.get("action") or raw.get("action") or "discover_leads", 80)
    target = _safe_lead_summary(raw.get("target") or raw.get("targetCustomer") or "", limit=180)
    knowledge = _safe_lead_summary(raw.get("knowledge") or "", limit=240)
    prompt = _safe_lead_summary(
        f"在{platform}执行{topic}。只读取可见公开内容，识别潜在线索，生成跟进草稿；如需触达，只能填草稿并停在人工确认页。目标客户：{target}。SOP：{knowledge}。返回 JSON 必须符合 loom.acquisition.agent_result.v1，字段包含 taskId、deviceId、platform、action、status、leads、drafts、logs；禁止自动私信、评论、加好友、加微信或发布。",
        limit=900,
    )
    payload = {
        "schema": "loom.acquisition.phone_task.v1",
        "taskId": agent_run.get("taskId"),
        "platform": platform,
        "action": action,
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
        "outboundPolicy": _acquisition_policy(),
        "prompt": prompt,
    }
    payload["bridgeDispatch"] = _acquisition_phone_bridge_dispatch(payload, device_id)
    return payload


def _acquisition_phone_bridge_dispatch(phone_task: Json, device_id: str) -> Json:
    return {
        "method": "POST",
        "endpoint": "/api/phone/task",
        "body": {
            "taskId": phone_task.get("taskId") or "",
            "prompt": phone_task.get("prompt") or "",
            "mode": "safe",
            "profile": phone_task.get("profile") or "fast",
            "executionLayer": "agent",
            "target": {"deviceIds": [device_id]},
            "template": "",
            "requiresHumanReview": True,
            "sendEnabled": False,
            "resultSchema": "loom.acquisition.agent_result.v1",
            "outboundPolicy": _acquisition_policy(),
            "resultCallback": {
                "method": "POST",
                "endpoint": "/api/matrix/acquisition/agent/result",
                "payloadField": "agentResult",
            },
        },
    }

def _mode(value: Any) -> str:
    text = str(value or "safe").strip().lower()
    if text in {"observe", "safe", "full"}:
        return text
    return "safe"


def _is_canonical_dispatch(raw: Any) -> bool:
    return isinstance(raw, dict) and ("schema" in raw or "deviceAssignments" in raw)


def _canonical_optional_text(value: Any, *, field: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise MatrixTargetError("matrix_invalid_dispatch", f"{field} must be a non-empty string")
    if "\x00" in value or len(value) > maximum:
        raise MatrixTargetError("matrix_unsupported_assignment", f"{field} is not supported by this executor")
    return value


def _canonical_id(value: Any, *, field: str) -> str:
    return _canonical_optional_text(value, field=field, maximum=200)


def _canonical_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MatrixTargetError("matrix_invalid_dispatch", f"{field} must be an integer")
    if value < minimum:
        raise MatrixTargetError("matrix_invalid_dispatch", f"{field} must be at least {minimum}")
    if value > maximum:
        raise MatrixTargetError("matrix_unsupported_assignment", f"{field} exceeds the supported maximum of {maximum}")
    return value


def _canonical_choice(value: Any, *, field: str, default: str, values: set[str]) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or value not in values:
        raise MatrixTargetError("matrix_invalid_dispatch", f"{field} must be one of: {', '.join(sorted(values))}")
    return value


def _profile(value: Any) -> str:
    text = str(value or "fast").strip().lower()
    if text in {"fast", "standard", "deep"}:
        return text
    return "fast"


def _template(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_.-]+", "-", text).strip(".-_")[:80]


def _retry_body_snapshot(*, prompt: str, mode: str, profile: str, template: str, action: str, devices: list[Json]) -> Json:
    return {
        "promptPreview": _safe_lead_summary(prompt, limit=240),
        "promptHash": _hash_prompt(prompt),
        "mode": mode,
        "profile": profile,
        "template": template,
        "directAction": action,
        "target": {"deviceIds": [str(device.get("deviceId") or "") for device in devices if str(device.get("deviceId") or "")][:100]},
    }


def _lead_source(value: Any) -> str:
    text = str(value or "manual").strip().lower()
    if text in {"manual", "task", "template", "agent", "import"}:
        return text
    return "manual"


def _lead_status(value: Any) -> str:
    text = str(value or "new").strip().lower()
    if text in {"new", "qualified", "follow-up", "ignored", "closed"}:
        return text
    return "new"


def _acquisition_platform(value: Any) -> str:
    text = str(value or "douyin").strip().lower()
    aliases = {
        "抖音": "douyin",
        "小红书": "xiaohongshu",
        "微信": "wechat",
        "视频号": "wechat",
        "快手": "kuaishou",
        "海外小红书": "rednote",
        "小红书海外版": "rednote",
        "red note": "rednote",
        "海外版小红书": "rednote",
    }
    text = aliases.get(text, text)
    if text in {"douyin", "xiaohongshu", "wechat", "bilibili", "kuaishou", "tiktok", "rednote", "lemon8", "manual"}:
        return text
    return "manual"


def _acquisition_channel(value: Any) -> str:
    text = str(value or "comment").strip().lower()
    aliases = {
        "评论": "comment",
        "评论区": "comment",
        "私信": "dm",
        "微信": "wechat",
        "电话": "phone",
        "手动": "manual",
    }
    text = aliases.get(text, text)
    if text in {"comment", "dm", "wechat", "phone", "manual"}:
        return text
    return "manual"


def _manual_send_outcome(value: Any) -> str:
    text = str(value or "sent").strip().lower()
    if text in {"sent", "replied", "no_reply", "failed"}:
        return text
    aliases = {
        "已发送": "sent",
        "已回复": "replied",
        "无回复": "no_reply",
        "失败": "failed",
    }
    return aliases.get(text, "sent")


def _acquisition_policy() -> list[str]:
    return ["draft_only", "manual_confirm", "whitelist", "frequency_cap", "audit_log"]


def _agent_result_has_unsafe_outbound(agent_result: Json) -> bool:
    forbidden = {"send_dm", "post_comment", "add_friend", "add_wechat", "bulk_outreach", "publish_without_confirmation"}
    if _truthy(agent_result.get("sendEnabled")):
        return True
    if str(agent_result.get("status") or "").strip().lower() in {"ready_to_send", "sent", "published", "auto_sent"}:
        return True
    actions = agent_result.get("requestedActions")
    if isinstance(actions, list):
        for item in actions:
            if str(item or "").strip().lower() in forbidden:
                return True
    drafts = agent_result.get("drafts")
    if isinstance(drafts, list):
        for item in drafts:
            if not isinstance(item, dict):
                continue
            if _truthy(item.get("sendEnabled")):
                return True
            if item.get("requiresHumanReview") is False:
                return True
    return False


def _default_acquisition_sop() -> list[Json]:
    return [
        {
            "id": "qualify",
            "title": "识别意图",
            "text": "先确认客户场景、预算和时间窗口，不承诺效果。",
        },
        {
            "id": "reply",
            "title": "回复草稿",
            "text": "所有评论、私信和微信跟进先生成草稿，人工确认后再处理。",
        },
        {
            "id": "risk",
            "title": "频控留痕",
            "text": "真实触达必须走白名单、频控和日志留痕。",
        },
    ]


def _acquisition_log(event_type: str, message: str, timestamp: str | None = None) -> Json:
    return {
        "logId": f"log_{uuid.uuid4().hex[:12]}",
        "timestamp": timestamp or _now_iso(),
        "type": event_type,
        "message": _safe_lead_summary(message, limit=260),
    }


def _safe_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        text = re.sub(r"\s+", " ", str(item or "").strip())[:40]
        if text:
            tags.append(text)
    return tags[:20]


def _safe_lead_summary(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", text)
    text = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    return text[:limit]


def _device_id(value: Any) -> str:
    text = str(value or "phone-1").strip()
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", text).strip(".-_")
    return text[:80] or "phone-1"


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:16]


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        safe: Json = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if str(key) in SENSITIVE_KEYS or any(mark in lowered for mark in ("token", "secret", "password", "apikey", "api_key")):
                continue
            safe[key] = _redact_json(item)
        return safe
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-***", value)
        value = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", value, flags=re.I)
        return value
    return value


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_bool(value: Any, fallback: Any = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(fallback, bool):
        return fallback
    return None


def _timestamp_age_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return -1
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    if re.search(r"[+-]\d{4}$", text):
        text = f"{text[:-5]}{text[-5:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return -1
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds() * 1000))


def _future_iso(seconds: int) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _remaining_ttl_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        expires_at = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining = expires_at.astimezone(timezone.utc) - datetime.now(timezone.utc)
    return max(0, int(remaining.total_seconds() * 1000))


def _timestamp_epoch_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return -1
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    if re.search(r"[+-]\d{4}$", text):
        text = f"{text[:-5]}{text[-5:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return -1
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "confirmed"}


def _now_iso() -> str:
    now = time.time()
    milliseconds = int(now * 1000) % 1000
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now))}.{milliseconds:03d}+00:00"
