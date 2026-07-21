"""Persistent phone automation scheduler."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

from core.paths import AppPaths


LogCall = Callable[[str], None]
DRAIN_LOCK_STALE_SECONDS = 30 * 60
QUEUE_RW_LOCK_STALE_SECONDS = 5 * 60


class PhoneAutomationScheduler:
    def __init__(self, paths: AppPaths, append_log: LogCall, poll_seconds: int = 30):
        self.paths = paths
        self.append_log = append_log
        self.poll_seconds = max(5, int(poll_seconds or 30))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._drain_lock = threading.Lock()
        self._last_tick: dict[str, Any] = {}
        self._timezone = self._resolve_timezone()

    @property
    def config_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "phone-automation.json")

    @property
    def state_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "phone-automation-scheduler.json")

    @property
    def queue_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "phone-agent-queue.json")

    @property
    def node_drain_lock_path(self) -> str:
        return f"{self.queue_path}.drain.lock"

    @property
    def queue_rw_lock_path(self) -> str:
        return f"{self.queue_path}.rw.lock"

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="phone-automation-scheduler", daemon=True)
            self._thread.start()
        self.append_log("[PhoneScheduler] started\n")
        return self.status()

    def stop(self) -> dict:
        self._stop_event.set()
        self.append_log("[PhoneScheduler] stopping\n")
        return self.status()

    def status(self) -> dict:
        state = self._read_json(self.state_path, {"schedules": {}})
        config = self._read_json(self.config_path, {})
        schedules = config.get("schedules") if isinstance(config, dict) else []
        return {
            "running": bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set()),
            "pollSeconds": self.poll_seconds,
            "configPath": self.config_path,
            "statePath": self.state_path,
            "queuePath": self.queue_path,
            "drainLockPath": self.node_drain_lock_path,
            "scheduleCount": len(schedules) if isinstance(schedules, list) else 0,
            "lastTick": self._last_tick,
            "state": state,
        }

    def tick(self) -> dict:
        with self._state_lock:
            return self._tick_locked()

    def _tick_locked(self) -> dict:
        now = self._now()
        config = self._read_json(self.config_path, {})
        state = self._read_json(self.state_path, {"schema": "openclaw.phone-automation.scheduler.v1", "schedules": {}})
        schedules_state = state.setdefault("schedules", {})
        templates = self._templates_by_id(config)
        devices = self._devices_by_id()
        schedules = config.get("schedules") if isinstance(config, dict) else []
        if not isinstance(schedules, list):
            schedules = []

        enqueued: list[dict] = []
        skipped: list[dict] = []
        for schedule in schedules:
            if not isinstance(schedule, dict):
                continue
            if schedule.get("enabled") is False:
                continue
            schedule_id = str(schedule.get("id") or "").strip()
            template_id = str(schedule.get("templateId") or "").strip()
            if not schedule_id or not template_id:
                continue
            template = templates.get(template_id)
            if not template:
                skipped.append({"scheduleId": schedule_id, "reason": "template_missing"})
                continue
            parsed = self._parse_cadence(str(schedule.get("cadence") or ""))
            if not parsed:
                skipped.append({"scheduleId": schedule_id, "reason": "unsupported_cadence"})
                continue
            if not self._inside_time_window(now, str(schedule.get("timeWindow") or "")):
                skipped.append({"scheduleId": schedule_id, "reason": "outside_time_window"})
                continue

            record = schedules_state.setdefault(schedule_id, {})
            last_run = self._parse_iso(record.get("lastEnqueuedAt"))
            due = self._is_due(now, parsed, last_run)
            record["nextDueAt"] = self._next_due_hint(now, parsed, last_run)
            if not due:
                continue
            if self._drain_running():
                skipped.append({"scheduleId": schedule_id, "reason": "drain_running"})
                continue
            if self._has_active_queue(schedule_id):
                skipped.append({"scheduleId": schedule_id, "reason": "active_queue_exists"})
                continue
            if self._should_require_manual(template, schedule):
                skipped.append({"scheduleId": schedule_id, "reason": "manual_confirmation_required"})
                record["lastSkippedAt"] = now.isoformat()
                record["lastSkipReason"] = "manual_confirmation_required"
                continue

            prompt = self._apply_template(template)
            mode = str(schedule.get("mode") or template.get("mode") or "safe").strip() or "safe"
            if mode in ("dry-run", "dry_run", "preview"):
                skipped.append({"scheduleId": schedule_id, "reason": "dry_run"})
                record["lastSkippedAt"] = now.isoformat()
                record["lastSkipReason"] = "dry_run"
                continue
            schedule_enqueued = 0
            device_ids = [str(item).strip() for item in schedule.get("deviceIds") or [] if str(item).strip()]
            if not device_ids:
                skipped.append({"scheduleId": schedule_id, "reason": "device_missing"})
                record["lastSkippedAt"] = now.isoformat()
                record["lastSkipReason"] = "device_missing"
                continue
            for device_id in device_ids:
                queue_item = self._enqueue(schedule, template, prompt, mode, device_id, devices.get(device_id))
                enqueued.append({"scheduleId": schedule_id, "templateId": template_id, "deviceId": device_id, "queueId": queue_item.get("id")})
                schedule_enqueued += 1
            if schedule_enqueued:
                record["lastEnqueuedAt"] = now.isoformat()
                record["lastResult"] = f"enqueued {schedule_enqueued}"

        state["updatedAt"] = now.isoformat()
        self._write_json(self.state_path, state)
        result = {
            "checkedAt": now.isoformat(),
            "enqueued": enqueued,
            "skipped": skipped[-20:],
        }
        self._last_tick = result
        if enqueued:
            self.append_log(f"[PhoneScheduler] enqueued {len(enqueued)} task(s)\n")
            self._drain_async()
        return result

    def run_once(self, template_id: str, device_ids: list[str], mode: str = "", allow_unattended: bool = False) -> dict:
        with self._state_lock:
            return self._run_once_locked(template_id, device_ids, mode, allow_unattended)

    def _run_once_locked(self, template_id: str, device_ids: list[str], mode: str = "", allow_unattended: bool = False) -> dict:
        now = self._now()
        config = self._read_json(self.config_path, {})
        templates = self._templates_by_id(config)
        devices = self._devices_by_id()
        template = templates.get(str(template_id or "").strip())
        if not template:
            return {"checkedAt": now.isoformat(), "enqueued": [], "skipped": [{"reason": "template_missing", "templateId": template_id}]}
        schedule = {
            "id": f"manual-{int(time.time() * 1000):x}",
            "templateId": template.get("id"),
            "mode": mode or template.get("mode") or "safe",
            "priority": 10,
            "allowUnattended": bool(allow_unattended),
            "maxAttempts": 1,
        }
        if self._should_require_manual(template, schedule):
            return {
                "checkedAt": now.isoformat(),
                "enqueued": [],
                "skipped": [{"reason": "manual_confirmation_required", "templateId": template_id}],
            }
        if self._drain_running():
            return {
                "checkedAt": now.isoformat(),
                "enqueued": [],
                "skipped": [{"reason": "drain_running", "templateId": template_id}],
            }
        run_mode = str(schedule.get("mode") or "safe").strip()
        if run_mode in ("dry-run", "dry_run", "preview"):
            return {
                "checkedAt": now.isoformat(),
                "enqueued": [],
                "skipped": [{"reason": "dry_run", "templateId": template_id}],
            }
        prompt = self._apply_template(template)
        enqueued: list[dict] = []
        skipped: list[dict] = []
        cleaned_device_ids = [str(item).strip() for item in device_ids or [] if str(item).strip()]
        if not cleaned_device_ids:
            skipped.append({"reason": "device_missing", "templateId": template_id})
        for device_id in cleaned_device_ids:
            queue_item = self._enqueue(schedule, template, prompt, str(schedule["mode"]), device_id, devices.get(device_id))
            enqueued.append({"templateId": template.get("id"), "deviceId": device_id, "queueId": queue_item.get("id")})
        result = {"checkedAt": now.isoformat(), "enqueued": enqueued, "skipped": skipped}
        self._last_tick = result
        if enqueued:
            self.append_log(f"[PhoneScheduler] manually enqueued {len(enqueued)} task(s)\n")
            self._drain_async()
        return result

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as error:
                self.append_log(f"[PhoneScheduler] tick failed: {error}\n")
            self._stop_event.wait(self.poll_seconds)

    def _drain_async(self) -> None:
        if not self._drain_lock.acquire(blocking=False):
            return
        thread = threading.Thread(target=self._drain_queue, name="phone-automation-drain", daemon=True)
        thread.start()

    def _drain_queue(self) -> None:
        try:
            script = os.path.join(self.paths.base_path, "scripts", "openclaw-phone-agent.mjs")
            if not os.path.exists(script):
                self.append_log(f"[PhoneScheduler] drain skipped, missing {script}\n")
                return
            env = self.paths.process_env()
            command = [self.paths.node_exe, script, "drain", "--json"]
            completed = subprocess.run(
                command,
                cwd=self.paths.base_path,
                env=env,
                text=True,
                capture_output=True,
                timeout=900,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode == 0:
                self.append_log("[PhoneScheduler] queue drain completed\n")
            else:
                detail = (completed.stderr or completed.stdout or "").strip()[-1000:]
                self.append_log(f"[PhoneScheduler] queue drain failed: {detail}\n")
        except Exception as error:
            self.append_log(f"[PhoneScheduler] queue drain crashed: {error}\n")
        finally:
            self._drain_lock.release()

    def _enqueue(self, schedule: dict, template: dict, prompt: str, mode: str, device_id: str, device: dict | None) -> dict:
        now = self._now().isoformat()
        item = self._queue_item(schedule, template, prompt, mode, device_id, device, now)
        with self._queue_file_lock():
            queue = self._read_json(self.queue_path, {"schema": "openclaw.phone-agent.queue.v1", "items": []})
            items = queue.get("items") if isinstance(queue, dict) else []
            if not isinstance(items, list):
                items = []
            items.append(item)
            self._write_json(self.queue_path, {
                "schema": "openclaw.phone-agent.queue.v1",
                "updatedAt": now,
                "items": self._trim_queue_items(items),
            })
        return item

    def _queue_item(self, schedule: dict, template: dict, prompt: str, mode: str, device_id: str, device: dict | None, now: str) -> dict:
        timeout_sec = int(schedule.get("timeoutSec") or self._template_timeout_sec(template) or 600)
        return {
            "id": f"phone-task-{int(time.time() * 1000):x}-{os.urandom(3).hex()}",
            "status": "pending",
            "priority": int(schedule.get("priority") or 0),
            "createdAt": now,
            "updatedAt": now,
            "attempts": 0,
            "taskId": "",
            "scheduleId": schedule.get("id"),
            "templateId": template.get("id"),
            "prompt": prompt,
            "mode": mode if mode in ("observe", "safe", "full") else "safe",
            "timeoutSec": timeout_sec,
            "maxRounds": int(schedule.get("maxRounds") or self._template_max_rounds(template) or 60),
            "maxWaitSec": int(schedule.get("maxWaitSec") or (timeout_sec + 15)),
            "pollMs": int(schedule.get("pollMs") or 1800),
            "maxAttempts": int(schedule.get("maxAttempts") or 2),
            "deviceId": device_id,
            "phoneUrl": "",
            "phoneToken": "",
            "promptPreview": self._preview(prompt),
            "source": "phone-automation-scheduler",
            "deviceName": (device or {}).get("name") or device_id,
        }

    def _trim_queue_items(self, items: list[dict], completed_limit: int = 200) -> list[dict]:
        active_statuses = {"pending", "running", "submitted", "error"}
        active = [item for item in items if isinstance(item, dict) and str(item.get("status") or "pending") in active_statuses]
        completed = [item for item in items if isinstance(item, dict) and str(item.get("status") or "pending") not in active_statuses]
        remaining = max(0, completed_limit - len(active))
        return active + completed[-remaining:] if remaining else active

    def _templates_by_id(self, config: dict) -> dict[str, dict]:
        templates = config.get("templates") if isinstance(config, dict) else []
        if not isinstance(templates, list):
            return {}
        result = {}
        for template in templates:
            if isinstance(template, dict) and template.get("id"):
                result[str(template.get("id"))] = template
        return result

    def _devices_by_id(self) -> dict[str, dict]:
        store = self._read_json(os.path.join(self.paths.launcher_dir, "phone-agents.json"), {})
        devices = store.get("devices") if isinstance(store, dict) else []
        if not isinstance(devices, list):
            return {}
        return {str(item.get("id")): item for item in devices if isinstance(item, dict) and item.get("id")}

    def _has_active_queue(self, schedule_id: str) -> bool:
        queue = self._read_json(self.queue_path, {})
        items = queue.get("items") if isinstance(queue, dict) else []
        if not isinstance(items, list):
            return False
        active = {"pending", "running", "submitted"}
        return any(str(item.get("scheduleId") or "") == schedule_id and str(item.get("status") or "pending") in active for item in items if isinstance(item, dict))

    def _drain_running(self) -> bool:
        return self._drain_lock.locked() or self._external_drain_lock_active()

    def _external_drain_lock_active(self) -> bool:
        try:
            stat = os.stat(self.node_drain_lock_path)
        except FileNotFoundError:
            return False
        except Exception:
            return True
        lock = self._read_json(self.node_drain_lock_path, {})
        try:
            pid = int(lock.get("pid") or 0) if isinstance(lock, dict) else 0
        except (TypeError, ValueError):
            pid = 0
        age_seconds = max(0.0, time.time() - stat.st_mtime)
        if pid > 0 and self._process_alive(pid):
            return True
        if age_seconds < DRAIN_LOCK_STALE_SECONDS and pid <= 0:
            return True
        if age_seconds >= DRAIN_LOCK_STALE_SECONDS or pid > 0:
            try:
                os.remove(self.node_drain_lock_path)
            except FileNotFoundError:
                pass
            except Exception:
                return True
        return False

    def _process_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    text=True,
                    capture_output=True,
                    timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return completed.returncode == 0 and str(pid) in (completed.stdout or "")
            except Exception:
                return True
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    def _parse_cadence(self, value: str) -> dict | None:
        text = value.strip().lower()
        if not text or text in ("manual", "手动"):
            return None
        match = re.search(r"(?:(?:每隔|每|every)\s*)?(\d+)\s*(分钟|分|m|mins?|minutes?)", text)
        if match:
            minutes = max(1, int(match.group(1)))
            return {"kind": "interval", "seconds": minutes * 60}
        match = re.search(r"(?:(?:每隔|每|every)\s*)?(\d+)\s*(小时|时|h|hours?|hrs?)", text)
        if match:
            hours = max(1, int(match.group(1)))
            return {"kind": "interval", "seconds": hours * 3600}
        match = re.search(r"(\d{1,2}):(\d{2})", text)
        if match and ("每天" in text or "daily" in text):
            hour = min(23, int(match.group(1)))
            minute = min(59, int(match.group(2)))
            return {"kind": "daily", "hour": hour, "minute": minute}
        return None

    def _is_due(self, now: datetime, cadence: dict, last_run: datetime | None) -> bool:
        if cadence.get("kind") == "interval":
            if last_run is None:
                return True
            return (now - last_run).total_seconds() >= int(cadence.get("seconds") or 0)
        if cadence.get("kind") == "daily":
            due_at = now.replace(hour=int(cadence.get("hour") or 0), minute=int(cadence.get("minute") or 0), second=0, microsecond=0)
            if now < due_at:
                return False
            return last_run is None or last_run.date() < now.date()
        return False

    def _next_due_hint(self, now: datetime, cadence: dict, last_run: datetime | None) -> str:
        if cadence.get("kind") == "interval":
            base = last_run or now
            return (base + timedelta(seconds=int(cadence.get("seconds") or 0))).isoformat()
        if cadence.get("kind") == "daily":
            due_at = now.replace(hour=int(cadence.get("hour") or 0), minute=int(cadence.get("minute") or 0), second=0, microsecond=0)
            if due_at <= now:
                due_at = due_at + timedelta(days=1)
            return due_at.isoformat()
        return ""

    def _inside_time_window(self, now: datetime, value: str) -> bool:
        text = value.strip()
        if not text or text in ("不限", "any", "all"):
            return True
        match = re.search(r"(\d{1,2}):(\d{2})\s*[-~至]\s*(\d{1,2}):(\d{2})", text)
        if not match:
            return True
        start = now.replace(hour=min(23, int(match.group(1))), minute=min(59, int(match.group(2))), second=0, microsecond=0)
        end = now.replace(hour=min(23, int(match.group(3))), minute=min(59, int(match.group(4))), second=59, microsecond=999999)
        if end < start:
            return now >= start or now <= end
        return start <= now <= end

    def _should_require_manual(self, template: dict, schedule: dict) -> bool:
        if schedule.get("allowUnattended") is True:
            return False
        if template.get("requiresManualConfirmation") is True:
            return True
        return str(template.get("riskLevel") or "").lower() == "high"

    def _apply_template(self, template: dict) -> str:
        prompt = str(template.get("prompt") or "")
        variables = template.get("variables") if isinstance(template.get("variables"), list) else []
        for variable in variables:
            if not isinstance(variable, dict):
                continue
            key = str(variable.get("key") or "").strip()
            if not key:
                continue
            prompt = re.sub(r"{{\s*" + re.escape(key) + r"\s*}}", str(variable.get("value") or ""), prompt)
        return prompt

    def _template_max_rounds(self, template: dict) -> int:
        return self._template_int_variable(template, "maxRounds")

    def _template_timeout_sec(self, template: dict) -> int:
        prompt = str(template.get("prompt") or "")
        template_id = str(template.get("id") or "")
        is_ad_watch = template_id == "generic-ad-watch-reward" or "OPENCLAW_AD_WATCH" in prompt
        if not is_ad_watch:
            return 0
        max_watch_seconds = self._template_int_variable(template, "maxWatchSeconds")
        if max_watch_seconds <= 0:
            return 0
        return max(60, min(900, max_watch_seconds + 45))

    def _template_int_variable(self, template: dict, key: str) -> int:
        variables = template.get("variables") if isinstance(template.get("variables"), list) else []
        for variable in variables:
            if not isinstance(variable, dict):
                continue
            if str(variable.get("key") or "") == key:
                try:
                    return int(variable.get("value") or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _parse_iso(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=self._timezone)
            return parsed.astimezone(self._timezone)
        except ValueError:
            return None

    def _resolve_timezone(self):
        name = os.environ.get("OPENCLAW_SCHEDULER_TZ", "Asia/Shanghai").strip() or "Asia/Shanghai"
        if ZoneInfo is not None:
            try:
                return ZoneInfo(name)
            except Exception:
                pass
        return datetime.now().astimezone().tzinfo or timezone(timedelta(hours=8))

    def _now(self) -> datetime:
        return datetime.now(self._timezone)

    @contextmanager
    def _queue_file_lock(self):
        os.makedirs(os.path.dirname(self.queue_rw_lock_path), exist_ok=True)
        deadline = time.time() + 10
        fd: int | None = None
        while True:
            try:
                fd = os.open(self.queue_rw_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({
                    "schema": "openclaw.phone-agent.queue-rw-lock.v1",
                    "pid": os.getpid(),
                    "createdAt": self._now().isoformat(),
                }).encode("utf-8"))
                break
            except FileExistsError:
                if self._lockfile_stale(self.queue_rw_lock_path, QUEUE_RW_LOCK_STALE_SECONDS):
                    try:
                        os.remove(self.queue_rw_lock_path)
                    except FileNotFoundError:
                        pass
                    except Exception:
                        time.sleep(0.1)
                    continue
                if time.time() >= deadline:
                    raise RuntimeError("phone queue is busy")
                time.sleep(0.1)
        try:
            yield
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.remove(self.queue_rw_lock_path)
            except FileNotFoundError:
                pass

    def _lockfile_stale(self, path: str, stale_seconds: int) -> bool:
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            return False
        except Exception:
            return False
        return time.time() - stat.st_mtime >= stale_seconds

    def _preview(self, value: str) -> str:
        clean = re.sub(r"\s+", " ", value or "").strip()
        return clean[:157] + "..." if len(clean) > 160 else clean

    def _read_json(self, path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return default
        except Exception:
            return default

    def _write_json(self, path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
