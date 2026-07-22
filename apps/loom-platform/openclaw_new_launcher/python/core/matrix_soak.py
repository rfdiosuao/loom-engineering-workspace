"""Read-only multi-phone matrix soak testing and reporting."""

from __future__ import annotations

import math
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
) -> Json:
    started = monotonic()
    rounds: list[Json] = []
    latencies: list[float] = []
    total_operations = 0
    failed_operations = 0
    minimum_observed: int | None = None

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
            online_ids = [
                str(item.get("deviceId") or "").strip()
                for item in devices if isinstance(item, dict) and item.get("online")
            ] if isinstance(devices, list) else []
            online_ids = [item for item in online_ids if item]
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
    )
    return {
        "schema": "loom.matrix.soak.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
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


__all__ = ["run_matrix_soak"]
