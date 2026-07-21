"""Automation reliability helpers for diagnostics, jobs, and support bundles."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from typing import Any, Tuple


FailureRule = Tuple[str, str, bool, str, str, Tuple[str, ...]]

FAILURE_RULES: tuple[FailureRule, ...] = (
    (
        "auth_signature",
        "授权/签名失效",
        False,
        "danger",
        "重新保存设备 token，确认启动器只通过安全 CLI 调 APKClaw，不直接拼接口。",
        ("invalid lumi signature", "signature", "401", "403", "unauthorized", "forbidden", "token", "auth"),
    ),
    (
        "device_offline",
        "设备离线/网络不可达",
        True,
        "warn",
        "先重新探测设备和端口；恢复后可安全重试同一个任务。",
        ("fetch failed", "econnrefused", "enotfound", "network", "offline", "unreachable", "无法连接", "离线"),
    ),
    (
        "timeout",
        "任务超时",
        True,
        "warn",
        "缩小任务范围或增加等待窗口；重试前先读取最近屏幕快照。",
        ("timeout", "timed out", "超时", "deadline", "aborterror"),
    ),
    (
        "task_busy",
        "设备任务忙",
        True,
        "warn",
        "等待当前任务完成，或先取消卡住任务再 drain 本地队列。",
        ("already running", "task is already running", "busy", "已有任务", "queue locked"),
    ),
    (
        "permission",
        "权限/无障碍不可用",
        False,
        "danger",
        "打开手机端无障碍、截图、悬浮窗或桌面端控制权限后再执行。",
        ("accessibility", "screen tree", "node tree", "permission", "denied", "无障碍", "权限"),
    ),
    (
        "service_crash",
        "服务崩溃/连接重置",
        True,
        "danger",
        "重启对应服务并导出诊断包；若连续出现，检查杀软、端口和 runtime 文件完整性。",
        ("crash", "crashed", "worker exited", "service died", "connection reset", "socket hang up", "崩溃"),
    ),
    (
        "openclaw_startup",
        "OpenClaw 启动失败",
        True,
        "danger",
        "运行环境修复，确认 node_modules/openclaw/openclaw.mjs、openclaw.json 和端口未被占用。",
        ("openclaw startup failed", "openclaw process exited", "openclaw.mjs", "openclaw.json", "gateway"),
    ),
    (
        "rate_limit",
        "模型/供应商限流",
        True,
        "warn",
        "等待 retry-after 或换模型/网关后重试；不要立即高频重放。",
        ("rate limit", "429", "too many requests", "quota", "retry-after", "限流"),
    ),
    (
        "disk",
        "磁盘/文件写入问题",
        False,
        "danger",
        "清理空间并确认便携目录可写；不要在只读 U 盘状态下执行任务。",
        ("no space", "disk", "readonly", "read-only", "permissionerror", "enospc", "空间", "只读"),
    ),
)


def classify_failure(value: Any) -> dict[str, Any]:
    text = _failure_text(value)
    if not text:
        return _unknown("")
    folded = text.lower()
    for failure_class, label, retryable, severity, suggestion, patterns in FAILURE_RULES:
        if any(pattern in folded for pattern in patterns):
            return {
                "class": failure_class,
                "label": label,
                "retryable": retryable,
                "severity": severity,
                "suggestion": suggestion,
                "evidence": _evidence(text),
            }
    return _unknown(text)


def build_reliability_snapshot(ctx, limit: int = 30) -> dict[str, Any]:
    jobs = _safe_call(lambda: ctx.get_job_mgr().list(limit), [])
    failed_jobs = []
    for job in jobs:
        if str(job.get("status") or "").lower() in {"failed", "error", "cancelled", "canceled"} or job.get("error"):
            failed_jobs.append(_job_failure_entry(job))

    phone_history = _read_phone_history(ctx, limit)
    failed_phone = [_phone_failure_entry(item) for item in phone_history if _phone_failed(item)]
    queue = _read_json(os.path.join(ctx.paths.launcher_dir, "phone-agent-queue.json"), {})
    queue_items = queue.get("items") if isinstance(queue, dict) else []
    queue_items = queue_items if isinstance(queue_items, list) else []
    active_queue = [
        {
            "id": str(item.get("id") or ""),
            "status": str(item.get("status") or "pending"),
            "failureClass": str(item.get("failureClass") or ""),
            "updatedAt": item.get("updatedAt") or item.get("finishedAt") or item.get("createdAt"),
            "prompt": _short(item.get("prompt") or item.get("promptPreview") or "", 140),
        }
        for item in queue_items
        if str(item.get("status") or "pending").lower() in {"pending", "running", "submitted", "error"}
    ][:limit]

    startup_snapshot = _read_json(os.path.join(ctx.paths.data_dir, "logs", "openclaw-startup-snapshot.json"), {})
    startup_failure = {}
    if isinstance(startup_snapshot, dict) and startup_snapshot.get("error"):
        startup_failure = classify_failure(startup_snapshot)

    failures = [entry["failure"] for entry in failed_jobs + failed_phone if entry.get("failure")]
    if startup_failure:
        failures.append(startup_failure)
    counts = Counter(str(item.get("class") or "unknown") for item in failures)
    retryable = sum(1 for item in failures if item.get("retryable"))
    danger = sum(1 for item in failures if item.get("severity") == "danger")

    return {
        "schema": "openclaw.launcher.reliability.v1",
        "updatedAt": _iso_now(),
        "summary": {
            "recentFailures": len(failures),
            "retryableFailures": retryable,
            "dangerFailures": danger,
            "activeQueuedPhoneTasks": len(active_queue),
            "classes": dict(counts),
        },
        "failedJobs": failed_jobs[:limit],
        "failedPhoneTasks": failed_phone[:limit],
        "phoneQueue": {
            "updatedAt": queue.get("updatedAt") if isinstance(queue, dict) else None,
            "active": active_queue,
        },
        "startupFailure": startup_failure,
    }


def _job_failure_entry(job: dict[str, Any]) -> dict[str, Any]:
    failure = classify_failure(job)
    return {
        "id": str(job.get("id") or ""),
        "kind": str(job.get("kind") or ""),
        "label": str(job.get("label") or ""),
        "status": str(job.get("status") or ""),
        "updatedAt": job.get("updatedAt"),
        "finishedAt": job.get("finishedAt"),
        "error": _short(job.get("error") or "", 300),
        "failure": failure,
    }


def _phone_failure_entry(item: dict[str, Any]) -> dict[str, Any]:
    failure = classify_failure(item)
    return {
        "status": str(item.get("status") or ""),
        "taskId": str(item.get("taskId") or item.get("id") or "")[:32],
        "deviceId": str(item.get("deviceId") or ""),
        "finishedAt": item.get("finishedAt") or item.get("updatedAt") or item.get("submittedAt"),
        "prompt": _short(item.get("prompt") or item.get("promptPreview") or "", 140),
        "error": _short(item.get("error") or "", 300),
        "failureClass": str(item.get("failureClass") or failure.get("class") or ""),
        "failure": failure,
    }


def _phone_failed(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    return status in {"error", "failed", "cancelled", "canceled"} or bool(item.get("error") or item.get("failureClass"))


def _read_phone_history(ctx, limit: int) -> list[dict[str, Any]]:
    path = os.path.join(ctx.paths.data_dir, ".openclaw", "logs", "phone-agent-history.jsonl")
    if not os.path.exists(path):
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-max(1, min(limit * 3, 200)) :]
    except Exception:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except Exception:
            rows.append({"raw": line})
    return rows[-limit:]


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except Exception:
        return default


def _safe_call(target, default):
    try:
        return target()
    except Exception:
        return default


def _failure_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("status", "error", "message", "traceback", "failureClass"):
            if value.get(key):
                parts.append(str(value.get(key)))
        for key in ("result", "data", "task", "failure"):
            if isinstance(value.get(key), (dict, list, str)):
                parts.append(_failure_text(value.get(key)))
        if isinstance(value.get("events"), list):
            parts.extend(_failure_text(item) for item in value.get("events", []))
        return "\n".join(part for part in parts if part)
    if isinstance(value, list):
        return "\n".join(_failure_text(item) for item in value)
    return str(value)


def _unknown(text: str) -> dict[str, Any]:
    return {
        "class": "unknown" if text else "",
        "label": "未知失败" if text else "",
        "retryable": bool(text),
        "severity": "warn" if text else "ok",
        "suggestion": "导出诊断包并查看 job、启动日志和手机 Agent 历史。" if text else "",
        "evidence": _evidence(text),
    }


def _evidence(text: str) -> str:
    return _short(re.sub(r"\s+", " ", text).strip(), 220)


def _short(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
