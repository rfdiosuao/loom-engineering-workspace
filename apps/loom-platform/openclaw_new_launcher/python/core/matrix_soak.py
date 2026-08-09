"""Read-only matrix polling and explicitly virtual lifecycle soak reporting."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


Json = dict[str, Any]
HttpCall = Callable[[str, str, Json | None, int], Json]


def run_matrix_soak(
    call: HttpCall,
    *,
    duration_sec: float = 300,
    interval_sec: float = 5,
    min_devices: int = 1,
    capture_screens: bool = True,
    max_failure_rate: float = 0.05,
    max_p95_ms: float = 30000,
    timeout_sec: int = 45,
    max_iterations: int | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    profile: str = "read-only",
    commit: str | None = None,
    artifact_hashes: Json | None = None,
    source_identity: Json | None = None,
) -> Json:
    if profile != "read-only":
        raise ValueError("run_matrix_soak only supports the read-only profile")
    started = monotonic()
    rounds: list[Json] = []
    latencies: list[float] = []
    total_operations = 0
    failed_operations = 0
    minimum_observed: int | None = None
    observed_devices: dict[str, bool] = {}
    identity_anomalies: list[Json] = []

    while True:
        if max_iterations is not None and len(rounds) >= max(1, max_iterations):
            break
        if max_iterations is None and rounds and monotonic() - started >= max(1.0, duration_sec):
            break

        round_started = monotonic()
        record: Json = {"index": len(rounds) + 1, "status": "passed", "onlineDevices": 0}
        try:
            status_started = monotonic()
            status = call("GET", "/api/matrix/status", None, timeout_sec)
            status_ms = max(0.0, (monotonic() - status_started) * 1000)
            latencies.append(status_ms)
            total_operations += 1
            devices = status.get("devices") if isinstance(status, dict) else None
            round_states: dict[str, list[bool]] = {}
            if isinstance(devices, list):
                for item in devices:
                    if not isinstance(item, dict):
                        continue
                    device_id = str(item.get("deviceId") or "").strip()
                    if device_id:
                        round_states.setdefault(device_id, []).append(item.get("online") is True)
            online_ids = sorted(
                device_id for device_id, states in round_states.items() if any(states)
            )
            for device_id, states in round_states.items():
                observed_devices[device_id] = any(states)
            duplicate_ids = sorted(device_id for device_id, states in round_states.items() if len(states) > 1)
            conflicting_ids = sorted(
                device_id for device_id, states in round_states.items() if len(set(states)) > 1
            )
            if duplicate_ids:
                anomaly = {
                    "round": record["index"],
                    "duplicateDeviceIds": duplicate_ids,
                    "conflictingDeviceIds": conflicting_ids,
                }
                identity_anomalies.append(anomaly)
                failed_operations += 1
                record.update({
                    "status": "failed",
                    "deviceIdentityAnomaly": anomaly,
                    "error": "设备清单包含重复 deviceId，不能用于门禁计数。",
                })
            record.update({"onlineDevices": len(online_ids), "statusLatencyMs": round(status_ms, 2)})
            minimum_observed = len(online_ids) if minimum_observed is None else min(minimum_observed, len(online_ids))
            if len(online_ids) < min_devices:
                failed_operations += 1
                record.update({"status": "failed", "error": f"在线设备 {len(online_ids)} 台，低于门槛 {min_devices} 台。"})

            if capture_screens and online_ids:
                screen_success = 0
                screen_failures = 0
                for chunk in _chunks(online_ids, 24):
                    screen_started = monotonic()
                    payload = call(
                        "POST",
                        "/api/matrix/screens",
                        {"requests": [{"deviceId": device_id} for device_id in chunk]},
                        timeout_sec,
                    )
                    screen_ms = max(0.0, (monotonic() - screen_started) * 1000)
                    latencies.append(screen_ms)
                    total_operations += len(chunk)
                    screens = payload.get("screens") if isinstance(payload, dict) else []
                    errors = payload.get("errors") if isinstance(payload, dict) else []
                    successful_ids = {
                        str(item.get("deviceId") or "")
                        for item in screens if isinstance(item, dict)
                    }
                    error_ids = {
                        str(item.get("deviceId") or "")
                        for item in errors if isinstance(item, dict)
                    }
                    screen_success += sum(1 for device_id in chunk if device_id in successful_ids)
                    chunk_failures = sum(1 for device_id in chunk if device_id in error_ids or device_id not in successful_ids)
                    screen_failures += chunk_failures
                    failed_operations += chunk_failures
                record.update({"screenSuccess": screen_success, "screenFailures": screen_failures})
                if screen_failures:
                    record["status"] = "failed"
        except Exception as exc:
            total_operations += 1
            failed_operations += 1
            record.update({"status": "failed", "error": _safe_error(exc)})
        record["durationMs"] = round(max(0.0, (monotonic() - round_started) * 1000), 2)
        rounds.append(record)

        if max_iterations is None:
            remaining = max(0.0, duration_sec - (monotonic() - started))
            if remaining <= 0:
                break
            sleep(min(max(0.0, interval_sec), remaining))

    failure_rate = failed_operations / max(1, total_operations)
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    passed = (
        bool(rounds)
        and (minimum_observed or 0) >= min_devices
        and failure_rate <= max(0.0, max_failure_rate)
        and p95 <= max(1.0, max_p95_ms)
        and not identity_anomalies
    )
    audited_source = _audit_source_identity(commit, source_identity)
    return {
        "schema": "loom.matrix.soak.v1",
        "harnessVersion": "6.0.1",
        "promptVersion": "LOOM-COMMANDER-6.0.1",
        "protocolVersion": "6.0",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "commit": audited_source["commit"],
        "sourceIdentity": audited_source["sourceIdentity"],
        "profile": "read-only",
        "artifactHashes": dict(artifact_hashes or {"launcher": "unknown"}),
        "devices": [
            {
                "deviceId": device_id,
                "kind": "observed",
                "provenance": "unknown",
                "virtual": None,
                "realDeviceEligible": False,
                "online": observed_devices[device_id],
            }
            for device_id in sorted(observed_devices)
        ],
        "provenanceSummary": {
            "unknown": len(observed_devices),
            "virtual": 0,
            "physicalAttested": 0,
        },
        "realDeviceEligibility": {
            "eligibleCount": 0,
            "eligibleDeviceIds": [],
            "gateProven": False,
            "reason": "No trusted hardware attestation contract is available.",
        },
        "identityAnomalies": identity_anomalies,
        "passed": passed,
        "requirements": {
            "minDevices": min_devices,
            "captureScreens": capture_screens,
            "maxFailureRate": max_failure_rate,
            "maxP95Ms": max_p95_ms,
        },
        "summary": {
            "rounds": len(rounds),
            "operations": total_operations,
            "failedOperations": failed_operations,
            "failureRate": round(failure_rate, 6),
            "minimumObservedDevices": minimum_observed or 0,
            "p50Ms": round(p50, 2),
            "p95Ms": round(p95, 2),
        },
        "rounds": rounds,
    }


def run_lifecycle_soak(
    fixture: Json | None,
    *,
    task_timeout_ms: float = 30000,
    no_progress_timeout_ms: float = 30000,
    max_resource_growth_mb: float = 64,
    max_handle_growth: float = 128,
    max_thread_growth: float = 8,
    commit: str | None = None,
    artifact_hashes: Json | None = None,
    source_identity: Json | None = None,
) -> Json:
    """Evaluate an explicit, side-effect-free virtual lifecycle event fixture.

    This function deliberately has no HTTP/call argument.  Lifecycle evidence is
    replayed from a declared virtual fixture, so selecting the profile can never
    submit work to a connected phone by accident.
    """
    _validate_lifecycle_fixture(fixture)
    assert isinstance(fixture, dict)
    events = fixture.get("events")
    devices_spec = fixture.get("devices")
    assert isinstance(events, list)
    assert isinstance(devices_spec, list)

    device_ids = [
        str(item.get("deviceId") or "").strip()
        for item in devices_spec
        if isinstance(item, dict)
    ]
    devices: dict[str, Json] = {
        device_id: {
            "deviceId": device_id,
            "kind": "virtual",
            "provenance": "virtual",
            "virtual": True,
            "realDeviceEligible": False,
            "safe": True,
            "online": None,
            "epoch": None,
            "pid": None,
            "offlineAtMs": None,
            "recoveryPending": False,
            "recoveryAwaitingProgress": False,
            "recoveryTaskBaselines": {},
            "reconnectedAtMs": None,
        }
        for device_id in device_ids
    }
    tasks: dict[str, Json] = {}
    stages = {
        "submit": 0,
        "progress": 0,
        "terminal": 0,
        "cancelRequested": 0,
        "cancelConfirmed": 0,
        "restartCheckpoint": 0,
        "restartReconcile": 0,
        "metadataSamples": 0,
        "resourceSamples": 0,
    }
    failures: list[Json] = []
    failure_keys: set[tuple[str, str]] = set()
    recovery_attempted = 0
    recovery_succeeded = 0
    recovery_durations: list[float] = []
    task_latencies: list[float] = []
    false_timeout_ids: list[str] = []
    resource_samples: dict[tuple[str, int], list[Json]] = {}
    metadata_evidence: list[Json] = []
    resource_evidence: list[Json] = []
    queue_violations: list[Json] = []
    cancel_requested: set[str] = set()
    cancel_confirmed: set[str] = set()
    restart_checkpoints: dict[str, Json] = {}
    restart_by_device: dict[str, Json] = {}
    restart_lost: set[str] = set()
    restart_recovered: set[str] = set()
    restart_durations: list[float] = []
    restart_succeeded = 0
    restart_pid_changed = False
    task_outcomes = {"succeeded": 0, "failed": 0, "cancelled": 0, "lateTerminal": 0}

    def add_failure(kind: str, *, task_id: str = "", detail: str = "") -> None:
        key = (kind, task_id)
        if key in failure_keys:
            return
        failure_keys.add(key)
        item: Json = {"kind": kind}
        if task_id:
            item["taskId"] = task_id
        if detail:
            item["detail"] = detail
        failures.append(item)

    def task_event_matches(task: Json, event: Json, *, require_epoch: bool) -> bool:
        task_id = str(task.get("taskId") or "")
        matches = True
        if event.get("deviceId") != task.get("deviceId"):
            add_failure("task-device-mismatch", task_id=task_id)
            matches = False
        if require_epoch and event.get("epoch") != task.get("epoch"):
            add_failure("task-epoch-mismatch", task_id=task_id)
            matches = False
        current_device = devices.get(str(task.get("deviceId") or ""))
        if isinstance(current_device, dict) and current_device.get("epoch") != task.get("epoch"):
            add_failure("epoch-change-requires-reconcile", task_id=task_id)
            matches = False
        return matches

    valid_events: list[Json] = []
    epoch_event_types = {
        "device",
        "submit",
        "progress",
        "terminal",
        "cancel-request",
        "restart-checkpoint",
        "restart-reconcile",
        "metadata",
        "resource",
    }
    for index, item in enumerate(events):
        if not isinstance(item, dict):
            add_failure("invalid-event", detail=f"event[{index}] is not an object")
            continue
        at_ms = _nonnegative_finite_number(item.get("atMs"))
        if at_ms is None:
            add_failure("event-time-invalid", detail=f"event[{index}].atMs")
            continue
        event = dict(item)
        event["atMs"] = at_ms
        event_type = str(event.get("type") or "").strip()
        if event_type in epoch_event_types:
            epoch = _normalize_epoch(event.get("epoch"))
            if epoch is None:
                add_failure("epoch-invalid", detail=f"event[{index}].epoch")
                if event_type == "cancel-request":
                    add_failure(
                        "cancel-epoch-mismatch",
                        task_id=str(event.get("taskId") or "").strip(),
                    )
                continue
            event["epoch"] = epoch
        if event_type == "restart-reconcile":
            previous_epoch = _normalize_epoch(event.get("previousEpoch"))
            if previous_epoch is None:
                add_failure("epoch-invalid", detail=f"event[{index}].previousEpoch")
                continue
            event["previousEpoch"] = previous_epoch
        valid_events.append(event)
    ordered_events = sorted(valid_events, key=lambda item: item["atMs"])
    fixture_end_ms = max((float(item["atMs"]) for item in ordered_events), default=0.0)
    for event in ordered_events:
        event_type = str(event.get("type") or "").strip()
        at_ms = float(event["atMs"])
        device_id = str(event.get("deviceId") or "").strip()
        device = devices.get(device_id)
        if device is None:
            add_failure("unknown-device", detail=device_id or "missing deviceId")
            continue

        if event_type == "device":
            device_pid = _nonnegative_integer(event.get("pid"))
            if device_pid is None:
                add_failure("device-pid-invalid", detail=device_id)
                continue
            online = event.get("online") is True
            was_online = device.get("online") is True
            active = [
                task for task in tasks.values()
                if task.get("deviceId") == device_id and task.get("terminalAtMs") is None
            ]
            previous_epoch = device.get("epoch")
            if was_online and online and active and previous_epoch is not None and event.get("epoch") != previous_epoch:
                for task in active:
                    add_failure("epoch-change-requires-reconcile", task_id=str(task.get("taskId") or ""))
            if was_online and not online and active:
                recovery_attempted += 1
                device["offlineAtMs"] = at_ms
                device["recoveryPending"] = True
                device["recoveryAwaitingProgress"] = False
                device["recoveryTaskBaselines"] = {
                    str(task["taskId"]): task.get("lastProgress") for task in active
                }
            if online and device.get("recoveryPending"):
                same_epoch = all(task.get("epoch") == event.get("epoch") for task in active)
                if active and same_epoch:
                    device["recoveryAwaitingProgress"] = True
                    device["reconnectedAtMs"] = at_ms
                else:
                    add_failure("reconnect-state-mismatch")
                    device["recoveryPending"] = False
            device.update({
                "online": online,
                "epoch": event.get("epoch"),
                "pid": device_pid,
            })
            continue

        if event_type == "submit":
            task_id = str(event.get("taskId") or "").strip()
            if device.get("online") is not True:
                add_failure("offline-before-submit", task_id=task_id)
                continue
            if event.get("epoch") is None or event.get("epoch") != device.get("epoch"):
                add_failure("submit-epoch-mismatch", task_id=task_id)
                continue
            if not task_id or task_id in tasks:
                add_failure("duplicate-or-missing-task-id", task_id=task_id)
                continue
            tasks[task_id] = {
                "taskId": task_id,
                "deviceId": device_id,
                "epoch": event.get("epoch"),
                "submittedAtMs": at_ms,
                "lastProgress": None,
                "lastProgressAtMs": at_ms,
                "validProgressCount": 0,
                "terminalAtMs": None,
                "terminalStatus": None,
                "cancelAccepted": False,
            }
            stages["submit"] += 1
            continue

        if event_type == "progress":
            task_id = str(event.get("taskId") or "").strip()
            task = tasks.get(task_id)
            if task is None:
                add_failure("progress-without-submit", task_id=task_id)
                continue
            if not task_event_matches(task, event, require_epoch=True):
                continue
            if task.get("terminalAtMs") is not None:
                add_failure("progress-after-terminal", task_id=task_id)
                continue
            progress = _nonnegative_finite_number(event.get("progress"))
            heartbeat = _nonnegative_finite_number(event.get("heartbeat"))
            if progress is None or progress > 100 or heartbeat is None:
                add_failure("progress-field-invalid", task_id=task_id)
                continue
            stages["progress"] += 1
            previous = task.get("lastProgress")
            baselines = device.get("recoveryTaskBaselines")
            if (
                device.get("recoveryPending")
                and device.get("recoveryAwaitingProgress")
                and isinstance(baselines, dict)
                and task_id in baselines
                and event.get("epoch") == task.get("epoch")
            ):
                baseline = baselines[task_id]
                if baseline is None or progress > _number(baseline):
                    del baselines[task_id]
                    if not baselines:
                        recovery_succeeded += 1
                        recovery_durations.append(max(0.0, at_ms - _number(device.get("offlineAtMs"))))
                        device["recoveryPending"] = False
                        device["recoveryAwaitingProgress"] = False
                        device["offlineAtMs"] = None
            if previous is not None and progress < _number(previous):
                add_failure("progress-regression", task_id=task_id)
            elif previous is not None and progress == _number(previous):
                stalled_for = at_ms - _number(task.get("lastProgressAtMs"))
                if stalled_for > max(0.0, no_progress_timeout_ms):
                    add_failure("no-progress", task_id=task_id)
            elif previous is None or progress > _number(previous):
                task["lastProgress"] = progress
                task["lastProgressAtMs"] = at_ms
                task["validProgressCount"] = int(task.get("validProgressCount") or 0) + 1
            continue

        if event_type == "terminal":
            stages["terminal"] += 1
            task_id = str(event.get("taskId") or "").strip()
            task = tasks.get(task_id)
            if task is None:
                add_failure("terminal-without-submit", task_id=task_id)
                continue
            if not task_event_matches(task, event, require_epoch=True):
                continue
            if task.get("terminalAtMs") is not None:
                add_failure("duplicate-terminal", task_id=task_id)
                continue
            task["terminalAtMs"] = at_ms
            status = str(event.get("status") or "").strip().lower()
            task["terminalStatus"] = status
            elapsed = max(0.0, at_ms - _number(task.get("submittedAtMs")))
            task_latencies.append(elapsed)
            stalled_success = (
                status == "succeeded"
                and (
                    at_ms - _number(task.get("lastProgressAtMs")) > max(0.0, no_progress_timeout_ms)
                    or ("no-progress", task_id) in failure_keys
                )
            )
            missing_progress = status == "succeeded" and int(task.get("validProgressCount") or 0) < 1
            regressed_progress = status == "succeeded" and ("progress-regression", task_id) in failure_keys
            if missing_progress:
                add_failure("progress-missing", task_id=task_id)
            if elapsed > max(0.0, task_timeout_ms):
                false_timeout_ids.append(task_id)
                task_outcomes["lateTerminal"] += 1
                add_failure("false-timeout", task_id=task_id)
            elif stalled_success:
                add_failure("no-progress", task_id=task_id)
            elif missing_progress:
                pass
            elif regressed_progress:
                pass
            elif status == "succeeded":
                task_outcomes["succeeded"] += 1
            elif status == "failed":
                task_outcomes["failed"] += 1
                add_failure("failed-terminal", task_id=task_id)
            elif status == "cancelled":
                task_outcomes["cancelled"] += 1
                if not task.get("cancelAccepted"):
                    add_failure("unexpected-cancel", task_id=task_id)
            else:
                add_failure("invalid-terminal", task_id=task_id, detail=status)
            if status == "cancelled" and task.get("cancelAccepted"):
                cancel_confirmed.add(task_id)
                stages["cancelConfirmed"] += 1
            continue

        if event_type == "cancel-request":
            stages["cancelRequested"] += 1
            task_id = str(event.get("taskId") or "").strip()
            task = tasks.get(task_id)
            if task is None:
                add_failure("cancel-without-submit", task_id=task_id)
                continue
            if not task_event_matches(task, event, require_epoch=False):
                continue
            if (
                event.get("epoch") is None
                or event.get("epoch") != task.get("epoch")
                or event.get("epoch") != device.get("epoch")
            ):
                add_failure("cancel-epoch-mismatch", task_id=task_id)
                continue
            if task.get("terminalAtMs") is not None:
                add_failure("cancel-after-terminal", task_id=task_id)
                continue
            if event.get("accepted") is True:
                task["cancelAccepted"] = True
                cancel_requested.add(task_id)
            else:
                add_failure("cancel-rejected", task_id=task_id)
            continue

        if event_type == "restart-checkpoint":
            stages["restartCheckpoint"] += 1
            checkpoint_valid = True
            if event.get("epoch") is None or event.get("epoch") != device.get("epoch"):
                add_failure("restart-epoch-mismatch")
                checkpoint_valid = False
            checkpoint_pid = _nonnegative_integer(event.get("pid"))
            if checkpoint_pid is None or checkpoint_pid != device.get("pid"):
                add_failure("restart-checkpoint-pid-mismatch")
                checkpoint_valid = False
            declared_task_ids = _string_set(event.get("taskIds"))
            checkpoint_task_ids: set[str] = set()
            for task_id in declared_task_ids:
                task = tasks.get(task_id)
                if (
                    task is None
                    or task.get("deviceId") != device_id
                    or task.get("epoch") != event.get("epoch")
                    or task.get("terminalAtMs") is not None
                ):
                    add_failure("restart-checkpoint-task-mismatch", task_id=task_id)
                else:
                    checkpoint_task_ids.add(task_id)
            active_task_ids = {
                task_id for task_id, task in tasks.items()
                if task.get("deviceId") == device_id
                and task.get("epoch") == event.get("epoch")
                and task.get("terminalAtMs") is None
            }
            omitted_task_ids = active_task_ids - checkpoint_task_ids
            for task_id in sorted(omitted_task_ids):
                add_failure("restart-checkpoint-incomplete", task_id=task_id)
            if not checkpoint_valid:
                continue
            restart_checkpoints[device_id] = {
                "pid": checkpoint_pid,
                "epoch": event.get("epoch"),
                "taskIds": sorted(checkpoint_task_ids),
                "omittedTaskIds": sorted(omitted_task_ids),
                "atMs": at_ms,
            }
            continue

        if event_type == "restart-reconcile":
            stages["restartReconcile"] += 1
            restart_checkpoint = restart_checkpoints.get(device_id)
            if restart_checkpoint is None:
                add_failure("restart-without-checkpoint")
                continue
            reconcile_valid = True
            reconcile_epoch = event.get("epoch")
            previous_epoch = event.get("previousEpoch", reconcile_epoch)
            if (
                reconcile_epoch is None
                or previous_epoch != restart_checkpoint.get("epoch")
                or device.get("epoch") != restart_checkpoint.get("epoch")
            ):
                add_failure("restart-epoch-mismatch")
                reconcile_valid = False
            reconcile_pid = _nonnegative_integer(event.get("pid"))
            if (
                reconcile_pid is None
                or reconcile_pid == restart_checkpoint.get("pid")
                or reconcile_pid == device.get("pid")
            ):
                add_failure("restart-pid-boundary-missing")
                reconcile_valid = False
            if not reconcile_valid:
                continue
            expected = set(restart_checkpoint["taskIds"])
            declared_actual = _string_set(event.get("taskIds"))
            actual: set[str] = set()
            for task_id in declared_actual:
                task = tasks.get(task_id)
                if (
                    task is None
                    or task_id not in expected
                    or task.get("deviceId") != device_id
                    or task.get("epoch") != restart_checkpoint.get("epoch")
                    or task.get("terminalAtMs") is not None
                ):
                    add_failure("restart-reconcile-task-mismatch", task_id=task_id)
                else:
                    actual.add(task_id)
            lost = (expected - actual) | set(restart_checkpoint.get("omittedTaskIds") or [])
            recovered = expected & actual
            restart_lost.update(lost)
            restart_recovered.update(recovered)
            restart_pid_changed = True
            device["pid"] = reconcile_pid
            device["epoch"] = reconcile_epoch
            for task_id in recovered:
                tasks[task_id]["epoch"] = reconcile_epoch
            if not lost:
                restart_succeeded += 1
                restart_durations.append(max(0.0, at_ms - _number(restart_checkpoint.get("atMs"))))
            restart_by_device[device_id] = {
                "deviceId": device_id,
                "epoch": reconcile_epoch,
                "checkpointEpoch": restart_checkpoint.get("epoch"),
                "reconcileEpoch": reconcile_epoch,
                "checkpointPid": restart_checkpoint.get("pid"),
                "reconcilePid": reconcile_pid,
                "pidChanged": True,
                "recoveredTaskIds": sorted(recovered),
                "lostTaskIds": sorted(lost),
                "durationMs": round(max(0.0, at_ms - _number(restart_checkpoint.get("atMs"))), 2),
                "succeeded": not lost,
            }
            for task_id in sorted(lost):
                add_failure("restart-lost-state", task_id=task_id)
            continue

        if event_type == "metadata":
            depth_value = event.get("queueDepth")
            raw_queue_value = event.get("queueTaskIds")
            metadata_pid = _nonnegative_integer(event.get("pid"))
            metadata_valid = (
                isinstance(depth_value, int)
                and not isinstance(depth_value, bool)
                and depth_value >= 0
                and isinstance(raw_queue_value, list)
                and all(isinstance(item, str) and bool(item.strip()) for item in raw_queue_value)
            )
            if not metadata_valid:
                add_failure("metadata-field-invalid")
            if metadata_pid is None:
                add_failure("metadata-pid-invalid")
                metadata_valid = False
            elif metadata_pid != device.get("pid"):
                add_failure("metadata-pid-mismatch", detail=f"event={metadata_pid}, current={device.get('pid')}")
                metadata_valid = False
            if event.get("epoch") != device.get("epoch"):
                add_failure("metadata-epoch-mismatch", detail=f"event={event.get('epoch')}, current={device.get('epoch')}")
                metadata_valid = False
            if not metadata_valid:
                continue
            stages["metadataSamples"] += 1
            assert isinstance(raw_queue_value, list)
            raw_queue_ids = (
                [str(item).strip() for item in raw_queue_value if str(item).strip()]
                if isinstance(raw_queue_value, list) else []
            )
            queue_ids = set(raw_queue_ids)
            depth = int(depth_value)
            metadata_evidence.append({
                "atMs": at_ms,
                "deviceId": device_id,
                "epoch": event.get("epoch"),
                "pid": metadata_pid,
                "queueDepth": depth,
                "queueTaskIds": raw_queue_ids,
            })
            expected = {
                task_id for task_id, task in tasks.items()
                if task.get("deviceId") == device_id and task.get("terminalAtMs") is None
            }
            reasons: list[str] = []
            if len(raw_queue_ids) != len(queue_ids):
                reasons.append("duplicate-task-ids")
            if depth != len(raw_queue_ids):
                reasons.append("depth-does-not-match-ids")
            if queue_ids != expected:
                reasons.append("ids-do-not-match-active-tasks")
            if reasons:
                queue_violations.append({
                    "atMs": at_ms,
                    "deviceId": device_id,
                    "queueDepth": depth,
                    "queueTaskIds": raw_queue_ids,
                    "expectedTaskIds": sorted(expected),
                    "reasons": reasons,
                })
                add_failure("queue-inconsistent")
            continue

        if event_type == "resource":
            resource_valid = True
            pid_value = _nonnegative_integer(event.get("pid"))
            if pid_value is None or pid_value != device.get("pid"):
                add_failure("resource-pid-mismatch")
                resource_valid = False
            if event.get("epoch") is None or event.get("epoch") != device.get("epoch"):
                add_failure("resource-epoch-mismatch")
                resource_valid = False
            metrics: dict[str, float] = {}
            for metric in ("rssMb", "handles", "threads", "heartbeat"):
                value = _nonnegative_finite_number(event.get(metric))
                if value is None:
                    add_failure("resource-field-invalid", detail=metric)
                    resource_valid = False
                else:
                    metrics[metric] = value
            if not resource_valid:
                continue
            stages["resourceSamples"] += 1
            assert pid_value is not None
            pid = pid_value
            sample = {
                "atMs": at_ms,
                **metrics,
            }
            prior_samples = resource_samples.get((device_id, pid), [])
            if prior_samples and metrics["heartbeat"] < prior_samples[-1]["heartbeat"]:
                add_failure("heartbeat-regression", detail=f"pid {pid}")
            resource_samples.setdefault((device_id, pid), []).append(sample)
            resource_evidence.append({
                "deviceId": device_id,
                "epoch": event.get("epoch"),
                "pid": pid,
                **sample,
            })
            continue

        add_failure("unknown-event", detail=event_type)

    for device in devices.values():
        if device.get("recoveryPending"):
            if device.get("recoveryAwaitingProgress"):
                add_failure("reconnect-no-progress")
            else:
                add_failure("offline-mid-task")
    if stages["submit"] < 1:
        add_failure("lifecycle-flow-missing")
    for task_id, task in tasks.items():
        if task.get("terminalAtMs") is None and task_id not in cancel_requested:
            add_failure("terminal-missing", task_id=task_id)
            if (
                task.get("lastProgress") is not None
                and fixture_end_ms - _number(task.get("lastProgressAtMs")) > max(0.0, no_progress_timeout_ms)
            ):
                add_failure("no-progress", task_id=task_id)
    unconfirmed_cancel_ids = sorted(cancel_requested - cancel_confirmed)
    for task_id in unconfirmed_cancel_ids:
        add_failure("cancel-unconfirmed", task_id=task_id)

    growth_by_pid: list[Json] = []
    leak_pids: set[int] = set()
    rss_leak_pids: set[int] = set()
    handle_leak_pids: set[int] = set()
    thread_leak_pids: set[int] = set()
    for (device_id, pid), samples in sorted(resource_samples.items()):
        first = samples[0]["rssMb"]
        last = samples[-1]["rssMb"]
        growth = round(last - first, 3)
        peak_growth = round(max(item["rssMb"] for item in samples) - first, 3)
        handle_peak_growth = max(item["handles"] for item in samples) - samples[0]["handles"]
        thread_peak_growth = max(item["threads"] for item in samples) - samples[0]["threads"]
        rss_leak = peak_growth > max(0.0, max_resource_growth_mb)
        handle_leak = handle_peak_growth > max(0.0, max_handle_growth)
        thread_leak = thread_peak_growth > max(0.0, max_thread_growth)
        leak = rss_leak or handle_leak or thread_leak
        if rss_leak:
            rss_leak_pids.add(pid)
            leak_pids.add(pid)
            add_failure("resource-growth", detail=f"pid {pid}: {peak_growth} MB")
        if handle_leak:
            handle_leak_pids.add(pid)
            leak_pids.add(pid)
            add_failure("handle-growth", detail=f"pid {pid}: {handle_peak_growth} handles")
        if thread_leak:
            thread_leak_pids.add(pid)
            leak_pids.add(pid)
            add_failure("thread-growth", detail=f"pid {pid}: {thread_peak_growth} threads")
        growth_by_pid.append({
            "deviceId": device_id,
            "pid": pid,
            "samples": len(samples),
            "startRssMb": first,
            "endRssMb": last,
            "growthMb": growth,
            "peakGrowthMb": peak_growth,
            "trends": {
                metric: _trend(samples, metric)
                for metric in ("rssMb", "handles", "threads", "heartbeat")
            },
            "leakSignal": leak,
        })

    operations = sum(stages.values())
    failure_rate = len(failures) / max(1, operations)
    p50 = _percentile(task_latencies, 0.50)
    p95 = _percentile(task_latencies, 0.95)
    fixture_hash = "sha256:" + hashlib.sha256(
        json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    hashes = dict(artifact_hashes or {"fixture": fixture_hash, "launcher": "unknown"})
    audited_source = _audit_source_identity(commit, source_identity)
    return {
        "schema": "loom.matrix.soak.v2",
        "harnessVersion": "6.0.1",
        "promptVersion": "LOOM-COMMANDER-6.0.1",
        "protocolVersion": "6.0",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "commit": audited_source["commit"],
        "sourceIdentity": audited_source["sourceIdentity"],
        "profile": "lifecycle",
        "evidenceMode": "virtual",
        "artifactHashes": hashes,
        "fixture": {
            "schema": fixture["schema"],
            "name": str(fixture.get("name") or "unnamed-virtual-fixture"),
            "virtual": True,
            "safe": True,
            "sideEffectFree": True,
            "sha256": fixture_hash,
        },
        "devices": [
            {
                key: value for key, value in device.items()
                if key not in {
                    "offlineAtMs",
                    "recoveryPending",
                    "recoveryAwaitingProgress",
                    "recoveryTaskBaselines",
                    "reconnectedAtMs",
                }
            }
            for device in devices.values()
        ],
        "provenanceSummary": {
            "unknown": 0,
            "virtual": len(devices),
            "physicalAttested": 0,
        },
        "realDeviceEligibility": {
            "eligibleCount": 0,
            "eligibleDeviceIds": [],
            "gateProven": False,
            "reason": "Lifecycle evidence is an explicit virtual fixture.",
        },
        "passed": not failures,
        "stages": stages,
        "summary": {
            "events": len(ordered_events),
            "operations": operations,
            "failures": len(failures),
            "failureRate": round(failure_rate, 6),
            "p50Ms": round(p50, 2),
            "p95Ms": round(p95, 2),
        },
        "taskOutcomes": task_outcomes,
        "falseTimeout": {"count": len(false_timeout_ids), "taskIds": sorted(false_timeout_ids)},
        "recovery": {
            "attempted": recovery_attempted,
            "succeeded": recovery_succeeded,
            "successRate": round(recovery_succeeded / max(1, recovery_attempted), 6),
            "durationsMs": [round(item, 2) for item in recovery_durations],
        },
        "resourceGrowth": {
            "maxAllowedMb": max_resource_growth_mb,
            "thresholds": {
                "rssMb": max_resource_growth_mb,
                "handles": max_handle_growth,
                "threads": max_thread_growth,
            },
            "byPid": growth_by_pid,
            "leakSignalPids": sorted(leak_pids),
            "rssLeakSignalPids": sorted(rss_leak_pids),
            "handleLeakSignalPids": sorted(handle_leak_pids),
            "threadLeakSignalPids": sorted(thread_leak_pids),
        },
        "cancelConfirmation": {
            "requested": len(cancel_requested),
            "confirmed": len(cancel_confirmed),
            "unconfirmedTaskIds": unconfirmed_cancel_ids,
        },
        "restartReconcile": {
            "checkpoints": stages["restartCheckpoint"],
            "reconciliations": stages["restartReconcile"],
            "pidChanged": restart_pid_changed,
            "lostTaskIds": sorted(restart_lost),
            "recoveredTaskIds": sorted(restart_recovered),
            "succeeded": restart_succeeded,
            "durationsMs": [round(item, 2) for item in restart_durations],
            "byDevice": [restart_by_device[key] for key in sorted(restart_by_device)],
        },
        "queueConsistency": {"consistent": not queue_violations, "violations": queue_violations},
        "samples": {"metadata": metadata_evidence, "resources": resource_evidence},
        "failureKinds": sorted({str(item["kind"]) for item in failures}),
        "failures": failures,
        "realDeviceGate": {
            "executed": False,
            "notExecuted": ["2-device/20-round", "10-device/7200-second"],
            "note": "Virtual lifecycle evidence is not a real-device release gate.",
        },
    }


def _validate_lifecycle_fixture(fixture: Json | None) -> None:
    if not isinstance(fixture, dict) or fixture.get("virtual") is not True or fixture.get("safe") is not True:
        raise ValueError("lifecycle fixture must be explicitly virtual and safe")
    if fixture.get("schema") != "loom.matrix.lifecycle-fixture.v1":
        raise ValueError("lifecycle fixture must be explicitly virtual and safe with schema loom.matrix.lifecycle-fixture.v1")
    if fixture.get("sideEffectFree") is not True:
        raise ValueError("lifecycle fixture must be explicitly side-effect-free")
    if not isinstance(fixture.get("devices"), list) or not fixture["devices"]:
        raise ValueError("lifecycle fixture must declare at least one virtual safe device")
    device_ids = [
        str(item.get("deviceId") or "").strip()
        for item in fixture["devices"]
        if isinstance(item, dict)
    ]
    if len(device_ids) != len(fixture["devices"]) or not all(device_ids) or len(set(device_ids)) != len(device_ids):
        raise ValueError("lifecycle fixture virtual safe deviceIds must be present and unique")
    if not isinstance(fixture.get("events"), list):
        raise ValueError("lifecycle fixture must contain virtual safe events")


def _audit_commit(value: str | None) -> str:
    return str(value or os.environ.get("LOOM_COMMIT") or "unknown").strip() or "unknown"


def _audit_source_identity(commit: str | None, source_identity: Json | None) -> Json:
    audited_commit = _audit_commit(commit)
    identity = source_identity if isinstance(source_identity, dict) else {}
    head_commit = str(identity.get("headCommit") or audited_commit.removesuffix("+dirty")).strip() or "unknown"
    dirty = identity.get("dirty") is True
    fingerprint = str(identity.get("fingerprint") or "unknown").strip() or "unknown"
    report_commit = f"{head_commit}+dirty" if dirty else audited_commit
    return {
        "commit": report_commit,
        "sourceIdentity": {
            "headCommit": head_commit,
            "dirty": dirty,
            "fingerprint": fingerprint,
        },
    }


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _nonnegative_finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _normalize_epoch(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _trend(samples: list[Json], metric: str) -> Json:
    start = _number(samples[0].get(metric))
    end = _number(samples[-1].get(metric))
    return {
        "start": _compact_number(start),
        "end": _compact_number(end),
        "delta": _compact_number(end - start),
    }


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ")[:500]


__all__ = ["run_lifecycle_soak", "run_matrix_soak"]
