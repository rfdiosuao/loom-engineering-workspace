"""Persistent job runner for long launcher tasks."""

from __future__ import annotations

import json
import os
import copy
import hashlib
import tempfile
import threading
import time
import traceback
import uuid
from typing import Callable

from core.reliability import classify_failure


MATRIX_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024


class JobManager:
    def __init__(
        self,
        append_log: Callable[[str], None],
        max_jobs: int = 100,
        state_path: str | None = None,
        *,
        max_age_seconds: int = 7 * 24 * 60 * 60,
        max_state_bytes: int = 16 * 1024 * 1024,
        max_artifact_bytes: int = 8 * 1024 * 1024,
        matrix_artifact_max_bytes: int = MATRIX_ARTIFACT_MAX_BYTES,
    ):
        self.append_log = append_log
        self.max_jobs = max_jobs
        self.state_path = state_path
        self.max_age_seconds = max(60, int(max_age_seconds or 0))
        self.max_state_bytes = max(4096, int(max_state_bytes or 0))
        self.max_artifact_bytes = max(64 * 1024, int(max_artifact_bytes or 0))
        self.matrix_artifact_max_bytes = min(
            MATRIX_ARTIFACT_MAX_BYTES,
            max(64 * 1024, int(matrix_artifact_max_bytes or 0)),
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._runtime_dir = os.path.join(
            os.path.dirname(self.state_path) if self.state_path else tempfile.gettempdir(),
            f".loom-job-runtime-{os.getpid()}",
        )
        self._load_persisted_jobs()

    def submit(self, kind: str, label: str, target: Callable[[], dict]) -> dict:
        return self.submit_progress(kind, label, lambda _job_id: target())

    def submit_progress(self, kind: str, label: str, target: Callable[[str], dict], initial_progress: dict | None = None) -> dict:
        job_id = f"job_{uuid.uuid4().hex}"
        now = time.time()
        initial_progress = dict(initial_progress or {})
        initial_message = str(initial_progress.pop("message", "queued") or "queued")
        initial_tone = str(initial_progress.pop("tone", "neutral") or "neutral")
        initial_phase = str(initial_progress.get("phase") or "queued")
        initial_entry = {"message": initial_message, "tone": initial_tone, "updatedAt": now}
        job = {
            "id": job_id,
            "kind": kind,
            "type": kind,
            "label": label,
            "status": "queued",
            "phase": initial_phase,
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "result": None,
            "error": None,
            "failure": None,
            "attempt": 1,
            "message": initial_message,
            "progress": {
                **initial_progress,
                **initial_entry,
                "history": [initial_entry] if initial_progress else [],
                "updatedAt": now,
            },
        }
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = threading.Event()
            self._remove_cancel_file(job_id)
            self._prune_locked()
            self._persist_locked()

        queued_snapshot = dict(job)
        thread = threading.Thread(target=self._run, args=(job_id, target), daemon=True)
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return queued_snapshot

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            if self._prune_expired_locked():
                self._persist_locked()
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit: int = 30) -> list[dict]:
        with self._lock:
            if self._prune_expired_locked():
                self._persist_locked()
            jobs = sorted(self._jobs.values(), key=lambda item: float(item.get("createdAt") or 0), reverse=True)
            return [dict(item) for item in jobs[: max(1, min(int(limit or 0), 1000))]]

    def cancel_file(self, job_id: str) -> str:
        safe_id = "".join(character for character in str(job_id or "") if character.isalnum() or character in "-_")
        return os.path.join(self._runtime_dir, f"{safe_id or 'job'}.cancel")

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
            job = self._jobs.get(job_id)
            return bool((event and event.is_set()) or (job and job.get("status") == "cancelled"))

    def cancel(self, job_id: str, *, wait_for_worker: bool = True) -> bool:
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or str(job.get("status") or "") in {"succeeded", "failed", "cancelled", "needs_manual"}:
                return False
            event = self._cancel_events.setdefault(job_id, threading.Event())
            event.set()
            worker = self._threads.get(job_id)
        os.makedirs(self._runtime_dir, exist_ok=True)
        with open(self.cancel_file(job_id), "w", encoding="ascii") as handle:
            handle.write("cancelled\n")
        if wait_for_worker and worker and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update({
                    "status": "cancelled",
                    "phase": "cancelled",
                    "message": "cancelled",
                    "finishedAt": now,
                    "updatedAt": time.time(),
                })
                self._persist_locked()
        return True

    def cancel_matching(
        self,
        predicate: Callable[[dict], bool],
        *,
        wait_for_workers: bool = True,
    ) -> list[str]:
        with self._lock:
            job_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if str(job.get("status") or "") not in {"succeeded", "failed", "cancelled", "needs_manual"}
                and predicate(dict(job))
            ]
        return [
            job_id
            for job_id in job_ids
            if self.cancel(job_id, wait_for_worker=wait_for_workers)
        ]

    def progress(self, job_id: str, message: str, tone: str = "neutral", **extra) -> None:
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if str(job.get("status") or "") == "cancelled":
                return
            current = job.get("progress") if isinstance(job.get("progress"), dict) else {}
            history = current.get("history") if isinstance(current.get("history"), list) else []
            entry = {"message": str(message or ""), "tone": str(tone or "neutral"), "updatedAt": now}
            merged_progress = {**current, **extra}
            component_keys = ("componentId", "targetComponentId", "component")
            previous_component = next((current.get(key) for key in component_keys if current.get(key)), "")
            next_component = next((merged_progress.get(key) for key in component_keys if merged_progress.get(key)), "")
            previous_phase = str(current.get("phase") or "")
            next_phase = str(merged_progress.get("phase") or "")
            previous_entry = history[-1] if history and isinstance(history[-1], dict) else {}
            repeated = bool(history) and (
                str(previous_entry.get("message") or "") == entry["message"]
                and str(previous_entry.get("tone") or "neutral") == entry["tone"]
                and str(previous_component or "") == str(next_component or "")
                and previous_phase == next_phase
            )
            if not repeated:
                history = [*history, entry][-30:]
            job["message"] = entry["message"]
            if "phase" in extra:
                job["phase"] = str(extra.get("phase") or "")
            job["progress"] = {
                **current,
                **extra,
                **entry,
                "history": history,
            }
            job["updatedAt"] = now
            self._persist_locked()

    def _run(self, job_id: str, target: Callable[[str], dict]) -> None:
        self._patch(job_id, status="running", phase="running", startedAt=time.time(), updatedAt=time.time(), message="running")
        if self.is_cancelled(job_id):
            with self._lock:
                self._threads.pop(job_id, None)
            return
        log_prefix = self._job_log_prefix(job_id)
        self.append_log(f"{log_prefix} started\n")
        try:
            result = target(job_id)
            if self.is_cancelled(job_id):
                self.append_log(f"{log_prefix} cancelled\n")
                return
            if isinstance(result, dict) and result.get("manualRequired") is True:
                self._patch(
                    job_id,
                    status="needs_manual",
                    phase="needs_manual",
                    message=str(result.get("message") or "等待用户补充信息"),
                    result=result,
                    error=None,
                    failure=None,
                    finishedAt=time.time(),
                    updatedAt=time.time(),
                )
                self.append_log(f"{log_prefix} needs manual input\n")
                return
            if isinstance(result, dict) and result.get("success") is False:
                failure = _public_failure(classify_failure(result))
                error_text = str(result.get("error") or result.get("message") or failure.get("evidence") or "job_result_failed")
                self._patch(
                    job_id,
                    status="failed",
                    result=result,
                    error=error_text,
                    failure=failure,
                    finishedAt=time.time(),
                    updatedAt=time.time(),
                )
                self.append_log(f"{log_prefix} failed: {error_text}\n")
                return
            self._patch(
                job_id,
                status="succeeded",
                result=result,
                error=None,
                failure=None,
                finishedAt=time.time(),
                updatedAt=time.time(),
            )
            self.append_log(f"{log_prefix} succeeded\n")
        except Exception as error:
            if self.is_cancelled(job_id):
                self.append_log(f"{log_prefix} cancelled\n")
                return
            technical = f"{type(error).__name__}: {error}"
            self.append_log(f"{log_prefix} failed: {technical}\n{traceback.format_exc()}\n")
            self._patch(
                job_id,
                status="failed",
                result=None,
                error="任务执行失败，详情已写入运行日志",
                failure=_public_failure(classify_failure({"error": technical})),
                traceback=None,
                finishedAt=time.time(),
                updatedAt=time.time(),
            )
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    def _job_log_prefix(self, job_id: str) -> str:
        with self._lock:
            job = self._jobs.get(job_id) or {}
            kind = str(job.get("kind") or "unknown")
            label = str(job.get("label") or kind)
        kind = " ".join(kind.replace("]", "").split())[:80] or "unknown"
        label = " ".join(label.replace("]", "").split())[:120] or kind
        return f"[Job:{kind}] {label} ({job_id})"

    def _patch(self, job_id: str, **updates) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if str(job.get("status") or "") == "cancelled" and updates.get("status") != "cancelled":
                return
            result = updates.get("result")
            if result is not None:
                result_bytes = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
                artifact_limit = self._artifact_limit_for_job(job)
                if len(result_bytes) > artifact_limit:
                    error_code = "job_result_exceeded_artifact_limit"
                    updates["status"] = "failed"
                    updates["result"] = {
                        "success": False,
                        "errorCode": error_code,
                        "truncated": True,
                        "originalBytes": len(result_bytes),
                        "maxArtifactBytes": artifact_limit,
                    }
                    updates["error"] = error_code
                    updates["failure"] = _public_failure(classify_failure({"error": error_code}))
            job.update(updates)
            self._prune_locked()
            self._persist_locked()

    def _artifact_limit_for_job(self, job: dict) -> int:
        if str(job.get("kind") or "").startswith("matrix."):
            return self.matrix_artifact_max_bytes
        return self.max_artifact_bytes

    def _prune_locked(self) -> bool:
        changed = self._prune_expired_locked()
        terminal_states = {"succeeded", "failed", "cancelled", "needs_manual"}
        terminal_jobs = sorted(
            (
                job for job in self._jobs.values()
                if str(job.get("status") or "") in terminal_states
            ),
            key=lambda item: float(item.get("finishedAt") or item.get("updatedAt") or item.get("createdAt") or 0),
        )
        if len(terminal_jobs) > self.max_jobs:
            for job in terminal_jobs[: len(terminal_jobs) - self.max_jobs]:
                self._remove_job_locked(str(job.get("id") or ""))
                changed = True
        while len(self._jobs) > 1 and self._persisted_size_locked() > self.max_state_bytes:
            terminal_jobs = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if str(job.get("status") or "") in terminal_states
                ),
                key=lambda item: float(item.get("finishedAt") or item.get("updatedAt") or item.get("createdAt") or 0),
            )
            if not terminal_jobs:
                break
            self._remove_job_locked(str(terminal_jobs[0].get("id") or ""))
            changed = True
        return changed

    def _prune_expired_locked(self) -> bool:
        changed = False
        cutoff = time.time() - self.max_age_seconds
        for job_id, job in list(self._jobs.items()):
            if str(job.get("status") or "") not in {"succeeded", "failed", "cancelled", "needs_manual"}:
                continue
            timestamp = float(job.get("finishedAt") or job.get("updatedAt") or job.get("createdAt") or 0)
            if timestamp and timestamp < cutoff:
                self._remove_job_locked(job_id)
                changed = True
        return changed

    def _persisted_size_locked(self) -> int:
        return len(
            json.dumps(
                self._state_payload_locked(),
                indent=2,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ) + 1

    def _state_payload_locked(self) -> dict:
        return {
            "schemaVersion": 1,
            "updatedAt": time.time(),
            "jobs": {
                job_id: self._job_for_persistence_locked(job_id, job)
                for job_id, job in sorted(self._jobs.items())
            },
        }

    def _job_for_persistence_locked(self, job_id: str, job: dict) -> dict:
        persisted = copy.deepcopy(job)
        result = persisted.get("result")
        if result is None:
            return persisted
        result_bytes = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
        threshold = max(2048, self.max_state_bytes // 2)
        if len(result_bytes) <= threshold or not self.state_path:
            return persisted
        artifact_path, artifact_bytes, artifact_sha256 = self._write_result_artifact(
            job_id,
            result,
            result_bytes,
        )
        persisted["result"] = None
        persisted["resultArtifact"] = os.path.basename(artifact_path)
        persisted["resultArtifactBytes"] = artifact_bytes
        persisted["resultArtifactSha256"] = artifact_sha256
        return persisted

    def _write_result_artifact(self, job_id: str, result, encoded: bytes) -> tuple[str, int, str]:
        artifact_payload = encoded + b"\n"
        artifact_sha256 = hashlib.sha256(artifact_payload).hexdigest()
        directory = self._artifact_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{job_id}.json")
        fd, temp_path = tempfile.mkstemp(prefix=f".{job_id}-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(artifact_payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
        return path, len(artifact_payload), artifact_sha256

    def _artifact_dir(self) -> str:
        return f"{self.state_path}.artifacts" if self.state_path else ""

    def _load_result_artifact(
        self,
        artifact_name: str,
        *,
        expected_bytes: int | None = None,
        expected_sha256: str = "",
    ):
        if not self.state_path or not artifact_name:
            return None
        path = os.path.join(self._artifact_dir(), os.path.basename(artifact_name))
        try:
            with open(path, "rb") as handle:
                payload = handle.read()
            if expected_bytes is not None and len(payload) != expected_bytes:
                raise ValueError("artifact byte length mismatch")
            if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
                raise ValueError("artifact digest mismatch")
            return json.loads(payload.decode("utf-8"))
        except FileNotFoundError:
            reason = "artifact_missing"
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            reason = "artifact_corrupt"
        return {
            "success": False,
            "resultUnavailable": True,
            "error": "job_result_unavailable",
            "reason": reason,
        }

    def _remove_job_locked(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._cancel_events.pop(job_id, None)
        self._remove_cancel_file(job_id)
        if self.state_path:
            try:
                os.unlink(os.path.join(self._artifact_dir(), f"{job_id}.json"))
            except OSError:
                pass

    def _remove_cancel_file(self, job_id: str) -> None:
        try:
            os.unlink(self.cancel_file(job_id))
        except OSError:
            pass

    def _load_persisted_jobs(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._quarantine_corrupt_state()
            return
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if isinstance(raw_jobs, dict):
            jobs = [item for item in raw_jobs.values() if isinstance(item, dict)]
        elif isinstance(raw_jobs, list):
            jobs = [item for item in raw_jobs if isinstance(item, dict)]
        else:
            return

        now = time.time()
        changed = False
        with self._lock:
            for raw_job in jobs:
                job_id = str(raw_job.get("id") or "").strip()
                if not job_id:
                    continue
                job = dict(raw_job)
                if artifact_name := str(job.pop("resultArtifact", "") or ""):
                    expected_bytes_raw = job.pop("resultArtifactBytes", None)
                    try:
                        expected_bytes = int(expected_bytes_raw) if expected_bytes_raw is not None else None
                    except (TypeError, ValueError):
                        expected_bytes = -1
                    expected_sha256 = str(job.pop("resultArtifactSha256", "") or "")
                    job["result"] = self._load_result_artifact(
                        artifact_name,
                        expected_bytes=expected_bytes,
                        expected_sha256=expected_sha256,
                    )
                    if isinstance(job["result"], dict) and job["result"].get("resultUnavailable"):
                        job["status"] = "failed"
                        job["error"] = "job_result_unavailable"
                        job["failure"] = _public_failure(classify_failure({"error": "job_result_unavailable"}))
                        changed = True
                status = str(job.get("status") or "")
                if status in {"queued", "running"}:
                    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
                    history = progress.get("history") if isinstance(progress.get("history"), list) else []
                    entry = {
                        "message": "任务已中断，请重试",
                        "tone": "warning",
                        "updatedAt": now,
                    }
                    job.update({
                        "status": "failed",
                        "phase": "interrupted",
                        "message": entry["message"],
                        "error": entry["message"],
                        "finishedAt": now,
                        "updatedAt": now,
                        "failure": {
                            "class": "interrupted",
                            "label": "任务已中断",
                            "retryable": True,
                            "severity": "warn",
                            "suggestion": "请重新执行该操作",
                        },
                        "progress": {
                            **progress,
                            **entry,
                            "phase": "interrupted",
                            "history": [*history, entry][-30:],
                        },
                    })
                    changed = True
                self._jobs[job_id] = job
                self._cancel_events[job_id] = threading.Event()
            if self._prune_locked():
                changed = True
            if changed:
                self._persist_locked()

    def _quarantine_corrupt_state(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        destination = f"{self.state_path}.corrupt-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        try:
            os.replace(self.state_path, destination)
        except OSError:
            pass

    def _persist_locked(self) -> None:
        if not self.state_path:
            return
        payload = self._state_payload_locked()
        directory = os.path.dirname(self.state_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".jobs-state-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
                handle.write("\n")
            try:
                os.replace(temp_path, self.state_path)
            except PermissionError:
                with open(self.state_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
                    handle.write("\n")
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise


def _public_failure(failure: dict) -> dict:
    return {
        "class": failure.get("class") or "",
        "label": failure.get("label") or "",
        "retryable": bool(failure.get("retryable")),
        "severity": failure.get("severity") or "warn",
        "suggestion": failure.get("suggestion") or "",
    }
