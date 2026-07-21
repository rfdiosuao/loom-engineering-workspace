"""Small in-memory job runner for long launcher tasks."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable

from core.reliability import classify_failure


class JobManager:
    def __init__(self, append_log: Callable[[str], None], max_jobs: int = 100):
        self.append_log = append_log
        self.max_jobs = max_jobs
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def submit(self, kind: str, label: str, target: Callable[[], dict]) -> dict:
        return self.submit_progress(kind, label, lambda _job_id: target())

    def submit_progress(self, kind: str, label: str, target: Callable[[str], dict]) -> dict:
        job_id = f"job_{uuid.uuid4().hex}"
        now = time.time()
        job = {
            "id": job_id,
            "kind": kind,
            "label": label,
            "status": "queued",
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "result": None,
            "error": None,
            "failure": None,
            "attempt": 1,
            "message": "queued",
            "progress": {
                "message": "queued",
                "tone": "neutral",
                "history": [],
                "updatedAt": now,
            },
        }
        with self._lock:
            self._jobs[job_id] = job
            self._prune_locked()

        thread = threading.Thread(target=self._run, args=(job_id, target), daemon=True)
        thread.start()
        return self.get(job_id) or job

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit: int = 30) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: float(item.get("createdAt") or 0), reverse=True)
            return [dict(item) for item in jobs[: max(1, min(limit, self.max_jobs))]]

    def progress(self, job_id: str, message: str, tone: str = "neutral", **extra) -> None:
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            current = job.get("progress") if isinstance(job.get("progress"), dict) else {}
            history = current.get("history") if isinstance(current.get("history"), list) else []
            entry = {"message": str(message or ""), "tone": str(tone or "neutral"), "updatedAt": now}
            history = [*history, entry][-30:]
            job["message"] = entry["message"]
            job["progress"] = {
                **current,
                **extra,
                **entry,
                "history": history,
            }
            job["updatedAt"] = now

    def _run(self, job_id: str, target: Callable[[str], dict]) -> None:
        self._patch(job_id, status="running", startedAt=time.time(), updatedAt=time.time(), message="running")
        self.append_log(f"[Job] {job_id} started\n")
        try:
            result = target(job_id)
            if isinstance(result, dict) and result.get("success") is False:
                failure = classify_failure(result)
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
                self.append_log(f"[Job] {job_id} failed: {error_text}\n")
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
            self.append_log(f"[Job] {job_id} succeeded\n")
        except Exception as error:
            self._patch(
                job_id,
                status="failed",
                result=None,
                error=str(error),
                failure=classify_failure({"error": str(error), "traceback": traceback.format_exc()}),
                traceback=traceback.format_exc(),
                finishedAt=time.time(),
                updatedAt=time.time(),
            )
            self.append_log(f"[Job] {job_id} failed: {error}\n")

    def _patch(self, job_id: str, **updates) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(updates)

    def _prune_locked(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        jobs = sorted(self._jobs.values(), key=lambda item: float(item.get("createdAt") or 0))
        for job in jobs[: len(self._jobs) - self.max_jobs]:
            self._jobs.pop(str(job.get("id")), None)
