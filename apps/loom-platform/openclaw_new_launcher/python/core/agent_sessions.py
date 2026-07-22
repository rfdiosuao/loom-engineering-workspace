"""Durable file-backed storage for central agent sessions."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


JsonObject = Dict[str, Any]
_LOCKS_GUARD = threading.Lock()
_LOCKS: Dict[str, threading.RLock] = {}
_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "authtoken",
    "bridgetoken",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "password",
    "privatecontent",
    "privatefilecontent",
    "privatekey",
    "refreshToken".casefold(),
    "secret",
    "sessioncookie",
    "token",
}
_SENSITIVE_SUFFIXES = ("apikey", "password", "privatekey", "secret", "token")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PROVIDER_KEY_PATTERN = re.compile(r"(?i)\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|cookie)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


class RepositoryConflictError(RuntimeError):
    """Raised when a repository compare-and-swap observes stale state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_lock(path: str) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _atomic_write_json(path: str, value: Any) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_file_with_retry(temporary, path)
    finally:
        if os.path.exists(temporary):
            _remove_file_with_retry(temporary)


def _is_retryable_windows_file_error(error: OSError) -> bool:
    return os.name == "nt" and getattr(error, "winerror", None) in {5, 32, 33}


def _replace_file_with_retry(source: str, destination: str) -> None:
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if not _is_retryable_windows_file_error(error) or attempt == 7:
                raise
            time.sleep(0.025 * (attempt + 1))


def _remove_file_with_retry(path: str) -> None:
    for attempt in range(8):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            if not _is_retryable_windows_file_error(error) or attempt == 7:
                raise
            time.sleep(0.025 * (attempt + 1))


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def sanitize_for_storage(value: Any) -> Any:
    """Return a deep redacted copy suitable for durable logs and state."""
    if isinstance(value, dict):
        sanitized: JsonObject = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES):
                sanitized[str(key)] = _REDACTED
            else:
                sanitized[str(key)] = sanitize_for_storage(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, str):
        redacted = _BEARER_PATTERN.sub("Bearer " + _REDACTED, value)
        redacted = _PROVIDER_KEY_PATTERN.sub(_REDACTED, redacted)
        return _ASSIGNMENT_PATTERN.sub(lambda match: match.group(1) + match.group(2) + _REDACTED, redacted)
    return copy.deepcopy(value)


def _read_jsonl(path: str) -> list[JsonObject]:
    records: list[JsonObject] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        pass
    return records


def _append_jsonl(path: str, value: JsonObject) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _file_signature(path: str) -> tuple[int, int]:
    try:
        stat = os.stat(path)
    except OSError:
        return (0, 0)
    return (int(stat.st_size), int(stat.st_mtime_ns))


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeError, base64.binascii.Error) as error:
        raise ValueError("invalid cursor") from error
    if value < 0:
        raise ValueError("invalid cursor")
    return value


class AgentSessionRepository:
    """Owns the ``data/agent`` session tree and its rebuildable index."""

    INDEX_SCHEMA = "loom.agent.sessions-index.v1"

    def __init__(self, data_root: Any) -> None:
        root = getattr(data_root, "data_dir", data_root)
        root = os.fspath(root)
        self.root = root if os.path.basename(os.path.normpath(root)) == "agent" else os.path.join(root, "agent")
        self.sessions_root = os.path.join(self.root, "sessions")
        self.index_path = os.path.join(self.root, "sessions-index.json")
        self._lock = _path_lock(self.root)
        self._event_states: dict[
            str,
            tuple[tuple[int, int], int, dict[str, JsonObject], list[JsonObject]],
        ] = {}
        with self._lock:
            os.makedirs(self.sessions_root, exist_ok=True)
            index = self._load_index_unlocked()
            self._recover_message_transactions_unlocked(index)

    def create_session(
        self,
        title: str = "New conversation",
        runtime_profile_id: str = "default",
        model_id: str = "",
        session_id: Optional[str] = None,
    ) -> JsonObject:
        if not str(title).strip():
            raise ValueError("session title is required")
        session_id = session_id or "session_" + uuid.uuid4().hex
        now = _utc_now()
        safe_title = str(sanitize_for_storage(str(title).strip()))
        safe_runtime_profile_id = str(sanitize_for_storage(runtime_profile_id or "default"))
        safe_model_id = str(sanitize_for_storage(str(model_id or "").strip()))
        session = {
            "schema": "loom.agent.session.v1",
            "sessionId": session_id,
            "title": safe_title,
            "status": "active",
            "runtimeProfileId": safe_runtime_profile_id,
            "createdAt": now,
            "updatedAt": now,
        }
        if safe_model_id:
            session["modelId"] = safe_model_id
        with self._lock:
            index = self._load_index_unlocked()
            if session_id in index["sessions"]:
                raise ValueError("session already exists")
            session_dir = self._session_dir(session_id)
            os.makedirs(os.path.join(session_dir, "runs"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "approvals"), exist_ok=True)
            for ledger_name in ("messages.jsonl", "events.jsonl"):
                open(os.path.join(session_dir, ledger_name), "a", encoding="utf-8").close()
            _atomic_write_json(os.path.join(session_dir, "session.json"), session)
            index["sessions"][session_id] = session
            self._write_index_unlocked(index)
        return copy.deepcopy(session)

    def get_session(self, session_id: str) -> JsonObject:
        with self._lock:
            session = self._load_index_unlocked()["sessions"].get(session_id)
            if not isinstance(session, dict):
                raise KeyError(session_id)
            return copy.deepcopy(session)

    def update_session(self, session_id: str, changes: Optional[JsonObject] = None, **fields: Any) -> JsonObject:
        requested = dict(changes or {})
        requested.update(fields)
        allowed = {"title", "status", "runtimeProfileId", "modelId", "lastMessagePreview", "activeRunId"}
        unknown = set(requested) - allowed
        if unknown:
            raise ValueError("unsupported session fields: " + ", ".join(sorted(unknown)))
        if "status" in requested and requested["status"] not in ("active", "archived"):
            raise ValueError("invalid session status")
        if "title" in requested and not str(requested["title"]).strip():
            raise ValueError("session title is required")
        remove_model_id = False
        if "modelId" in requested:
            model_id = str(requested.get("modelId") or "").strip()
            if model_id:
                requested["modelId"] = sanitize_for_storage(model_id)
            else:
                requested.pop("modelId", None)
                remove_model_id = True
        for key in ("title", "runtimeProfileId", "lastMessagePreview"):
            if key in requested:
                requested[key] = sanitize_for_storage(requested[key])
        with self._lock:
            index = self._load_index_unlocked()
            current = index["sessions"].get(session_id)
            if not isinstance(current, dict):
                raise KeyError(session_id)
            updated = dict(current)
            if remove_model_id:
                updated.pop("modelId", None)
            updated.update(requested)
            updated["updatedAt"] = _utc_now()
            _atomic_write_json(os.path.join(self._session_dir(session_id), "session.json"), updated)
            index["sessions"][session_id] = updated
            self._write_index_unlocked(index)
            return copy.deepcopy(updated)

    def archive_session(self, session_id: str) -> JsonObject:
        return self.update_session(session_id, {"status": "archived"})

    def delete_session(self, session_id: str) -> JsonObject:
        return self.archive_session(session_id)

    def list_sessions(
        self,
        query: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
        status: Optional[str] = "active",
    ) -> JsonObject:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        offset = _decode_cursor(cursor)
        with self._lock:
            sessions = list(self._load_index_unlocked()["sessions"].values())
        if status is not None:
            sessions = [item for item in sessions if item.get("status") == status]
        if query:
            needle = query.casefold()
            sessions = [
                item
                for item in sessions
                if needle in str(item.get("title", "")).casefold()
                or needle in str(item.get("lastMessagePreview", "")).casefold()
            ]
        sessions.sort(key=lambda item: (str(item.get("updatedAt", "")), str(item.get("sessionId", ""))), reverse=True)
        page = sessions[offset : offset + limit]
        next_offset = offset + len(page)
        result: JsonObject = {"sessions": copy.deepcopy(page)}
        if next_offset < len(sessions):
            result["nextCursor"] = _encode_cursor(next_offset)
        return result

    def append_message(self, session_id: str, message: JsonObject) -> JsonObject:
        with self._lock:
            self._require_session_unlocked(session_id)
            sanitized = sanitize_for_storage(message)
            self._validate_owned_record(sanitized, "messageId", session_id)
            path = self._messages_path(session_id)
            message_id = sanitized["messageId"]
            if any(record.get("messageId") == message_id for record in _read_jsonl(path)):
                raise ValueError("message already exists")
            _append_jsonl(path, sanitized)
            self._update_session_from_message_unlocked(session_id, sanitized)
            return copy.deepcopy(sanitized)

    def page_messages(
        self,
        session_id: str,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> JsonObject:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        cursor_end = _decode_cursor(cursor) if cursor else None
        with self._lock:
            self._require_session_unlocked(session_id)
            messages = _read_jsonl(self._messages_path(session_id))
        end = len(messages) if cursor_end is None else min(cursor_end, len(messages))
        start = max(0, end - limit)
        page = messages[start:end]
        result: JsonObject = {"messages": copy.deepcopy(page)}
        if start > 0:
            result["nextCursor"] = _encode_cursor(start)
        return result

    def create_run(self, run: JsonObject) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            sanitized = sanitize_for_storage(run)
            return copy.deepcopy(self._create_run_unlocked(index, sanitized))

    def get_run(self, run_id: str, session_id: Optional[str] = None) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            owner = session_id or index["runs"].get(run_id)
            if not owner:
                raise KeyError(run_id)
            run = _read_json(self._run_path(owner, run_id))
            if not isinstance(run, dict):
                raise KeyError(run_id)
            return copy.deepcopy(run)

    def update_run(self, run_id: str, changes: JsonObject, session_id: Optional[str] = None) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            owner = session_id or index["runs"].get(run_id)
            if not owner:
                raise KeyError(run_id)
            path = self._run_path(owner, run_id)
            current = _read_json(path)
            if not isinstance(current, dict):
                raise KeyError(run_id)
            updated = dict(current)
            updated.update(sanitize_for_storage(changes))
            _atomic_write_json(path, updated)
            self._sync_active_run_unlocked(index, owner, updated)
            self._write_index_unlocked(index)
            return copy.deepcopy(updated)

    def list_runs(self, session_id: str) -> list[JsonObject]:
        with self._lock:
            self._require_session_unlocked(session_id)
            runs_dir = os.path.join(self._session_dir(session_id), "runs")
            runs = []
            try:
                filenames = os.listdir(runs_dir)
            except OSError:
                filenames = []
            for filename in filenames:
                if not filename.endswith(".json"):
                    continue
                run = _read_json(os.path.join(runs_dir, filename))
                if isinstance(run, dict):
                    runs.append(run)
            return copy.deepcopy(sorted(runs, key=lambda item: str(item.get("runId", ""))))

    def recover_unfinished_runs(self) -> list[JsonObject]:
        unfinished_statuses = {"queued", "running", "waiting_approval", "paused"}
        with self._lock:
            index = self._load_index_unlocked()
            recovered_with_times = []
            for run_id, session_id in index["runs"].items():
                path = self._run_path(session_id, run_id)
                run = _read_json(path)
                if isinstance(run, dict) and run.get("status") in unfinished_statuses:
                    try:
                        modified = os.path.getmtime(path)
                    except OSError:
                        modified = 0.0
                    recovered_with_times.append((modified, run_id, run))
            recovered_with_times.sort(key=lambda item: (item[0], item[1]))
            active_by_session: Dict[str, JsonObject] = {}
            for _modified, _run_id, run in recovered_with_times:
                active_by_session[run["sessionId"]] = run
            changed = False
            for session_id, run in active_by_session.items():
                session = index["sessions"].get(session_id)
                if isinstance(session, dict) and session.get("activeRunId") != run["runId"]:
                    updated = dict(session)
                    updated["activeRunId"] = run["runId"]
                    updated["updatedAt"] = _utc_now()
                    _atomic_write_json(os.path.join(self._session_dir(session_id), "session.json"), updated)
                    index["sessions"][session_id] = updated
                    changed = True
            if changed:
                self._write_index_unlocked(index)
            return [copy.deepcopy(item[2]) for item in recovered_with_times]

    def create_approval(self, approval: JsonObject) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            sanitized = sanitize_for_storage(approval)
            session_id = sanitized.get("sessionId")
            approval_id = sanitized.get("approvalId")
            if not isinstance(session_id, str) or not isinstance(approval_id, str):
                raise ValueError("approvalId and sessionId are required")
            self._require_session_unlocked(session_id)
            if approval_id in index["approvals"]:
                raise ValueError("approval already exists")
            _atomic_write_json(self._approval_path(session_id, approval_id), sanitized)
            index["approvals"][approval_id] = session_id
            self._write_index_unlocked(index)
            return copy.deepcopy(sanitized)

    def get_approval(self, approval_id: str, session_id: Optional[str] = None) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            owner = session_id or index["approvals"].get(approval_id)
            if not owner:
                raise KeyError(approval_id)
            approval = _read_json(self._approval_path(owner, approval_id))
            if not isinstance(approval, dict):
                raise KeyError(approval_id)
            return copy.deepcopy(approval)

    def update_approval(
        self,
        approval_id: str,
        changes: JsonObject,
        session_id: Optional[str] = None,
    ) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            owner = session_id or index["approvals"].get(approval_id)
            if not owner:
                raise KeyError(approval_id)
            path = self._approval_path(owner, approval_id)
            current = _read_json(path)
            if not isinstance(current, dict):
                raise KeyError(approval_id)
            updated = dict(current)
            updated.update(sanitize_for_storage(changes))
            _atomic_write_json(path, updated)
            return copy.deepcopy(updated)

    def compare_and_update_approval(
        self,
        approval_id: str,
        changes: JsonObject,
        *,
        expected_status: str,
        session_id: Optional[str] = None,
    ) -> JsonObject:
        with self._lock:
            index = self._load_index_unlocked()
            owner = session_id or index["approvals"].get(approval_id)
            if not owner:
                raise KeyError(approval_id)
            path = self._approval_path(owner, approval_id)
            current = _read_json(path)
            if not isinstance(current, dict):
                raise KeyError(approval_id)
            if current.get("status") != expected_status:
                raise RepositoryConflictError(
                    f"approval {approval_id} expected status {expected_status}, found {current.get('status')}"
                )
            updated = dict(current)
            updated.update(sanitize_for_storage(changes))
            _atomic_write_json(path, updated)
            return copy.deepcopy(updated)

    def list_approvals(self, session_id: str, run_id: Optional[str] = None) -> list[JsonObject]:
        with self._lock:
            self._require_session_unlocked(session_id)
            approvals_dir = os.path.join(self._session_dir(session_id), "approvals")
            approvals = []
            try:
                filenames = os.listdir(approvals_dir)
            except OSError:
                filenames = []
            for filename in filenames:
                if not filename.endswith(".json"):
                    continue
                approval = _read_json(os.path.join(approvals_dir, filename))
                if isinstance(approval, dict) and (run_id is None or approval.get("runId") == run_id):
                    approvals.append(approval)
            return copy.deepcopy(sorted(approvals, key=lambda item: str(item.get("approvalId", ""))))

    def create_message_run(
        self,
        session_id: str,
        client_message_id: str,
        message: JsonObject,
        run: JsonObject,
    ) -> JsonObject:
        if not client_message_id:
            raise ValueError("clientMessageId is required")
        with self._lock:
            index = self._load_index_unlocked()
            self._require_session_unlocked(session_id, index)
            session_keys = index["clientMessages"].setdefault(session_id, {})
            existing = session_keys.get(client_message_id)
            if isinstance(existing, dict):
                return {
                    "message": self._find_message_unlocked(session_id, existing["messageId"]),
                    "run": self.get_run(existing["runId"], session_id=session_id),
                    "created": False,
                }

            sanitized_message = sanitize_for_storage(message)
            sanitized_run = sanitize_for_storage(run)
            self._validate_owned_record(sanitized_message, "messageId", session_id)
            self._validate_owned_record(sanitized_run, "runId", session_id)
            transaction_path = self._message_transaction_path(session_id, client_message_id)
            pending = _read_json(transaction_path)
            if isinstance(pending, dict):
                recovered = self._commit_message_transaction_unlocked(index, pending)
                recovered["created"] = False
                return recovered
            transaction = {
                "schema": "loom.agent.message-transaction.v1",
                "sessionId": session_id,
                "clientMessageId": client_message_id,
                "message": sanitized_message,
                "run": sanitized_run,
            }
            _atomic_write_json(transaction_path, transaction)
            return self._commit_message_transaction_unlocked(index, transaction)

    def find_message_run(self, session_id: str, client_message_id: str) -> JsonObject | None:
        if not client_message_id:
            return None
        with self._lock:
            index = self._load_index_unlocked()
            self._require_session_unlocked(session_id, index)
            existing = index["clientMessages"].get(session_id, {}).get(client_message_id)
            if not isinstance(existing, dict):
                return None
            return {
                "message": self._find_message_unlocked(session_id, existing["messageId"]),
                "run": self.get_run(existing["runId"], session_id=session_id),
                "created": False,
            }

    def append_event(self, session_id: str, event: JsonObject) -> JsonObject:
        with self._lock:
            self._require_session_unlocked(session_id)
            sanitized = sanitize_for_storage(event)
            event_id = sanitized.get("eventId")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("eventId is required")
            path = self._events_path(session_id)
            last_seq, events_by_id, events = self._event_state_unlocked(path)
            existing = events_by_id.get(event_id)
            if existing is not None:
                return copy.deepcopy(existing)
            sanitized["seq"] = last_seq + 1
            _append_jsonl(path, sanitized)
            events_by_id[event_id] = copy.deepcopy(sanitized)
            events.append(copy.deepcopy(sanitized))
            self._event_states[path] = (
                _file_signature(path),
                sanitized["seq"],
                events_by_id,
                events,
            )
            return copy.deepcopy(sanitized)

    def _event_state_unlocked(
        self,
        path: str,
    ) -> tuple[int, dict[str, JsonObject], list[JsonObject]]:
        signature = _file_signature(path)
        cached = self._event_states.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1], cached[2], cached[3]

        events = _read_jsonl(path)
        events_by_id: dict[str, JsonObject] = {}
        last_seq = 0
        for item in events:
            event_id = item.get("eventId")
            if isinstance(event_id, str) and event_id:
                events_by_id.setdefault(event_id, item)
            seq = item.get("seq")
            if isinstance(seq, int):
                last_seq = max(last_seq, seq)
        self._event_states[path] = (signature, last_seq, events_by_id, events)
        return last_seq, events_by_id, events

    def replay_events(
        self,
        session_id: str,
        after_seq: int = 0,
        limit: Optional[int] = None,
    ) -> list[JsonObject]:
        if after_seq < 0:
            raise ValueError("after_seq must not be negative")
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            self._require_session_unlocked(session_id)
            _last_seq, _events_by_id, cached_events = self._event_state_unlocked(
                self._events_path(session_id)
            )
            events = [
                event
                for event in cached_events
                if isinstance(event.get("seq"), int) and event["seq"] > after_seq
            ]
        events.sort(key=lambda event: event["seq"])
        if limit is not None:
            events = events[:limit]
        return copy.deepcopy(events)

    def rebuild_index(self) -> JsonObject:
        with self._lock:
            return copy.deepcopy(self._rebuild_index_unlocked())

    def _session_dir(self, session_id: str) -> str:
        if not session_id or session_id in (".", "..") or os.path.basename(session_id) != session_id:
            raise ValueError("invalid session id")
        return os.path.join(self.sessions_root, session_id)

    def _messages_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), "messages.jsonl")

    def _events_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), "events.jsonl")

    def _run_path(self, session_id: str, run_id: str) -> str:
        self._validate_identifier(run_id, "run id")
        return os.path.join(self._session_dir(session_id), "runs", run_id + ".json")

    def _approval_path(self, session_id: str, approval_id: str) -> str:
        self._validate_identifier(approval_id, "approval id")
        return os.path.join(self._session_dir(session_id), "approvals", approval_id + ".json")

    def _message_transaction_path(self, session_id: str, client_message_id: str) -> str:
        digest = hashlib.sha256(str(client_message_id).encode("utf-8")).hexdigest()
        return os.path.join(self._session_dir(session_id), "transactions", digest + ".json")

    def _commit_message_transaction_unlocked(self, index: JsonObject, transaction: JsonObject) -> JsonObject:
        session_id = str(transaction.get("sessionId") or "")
        client_message_id = str(transaction.get("clientMessageId") or "")
        message = transaction.get("message")
        run = transaction.get("run")
        if not client_message_id or not isinstance(message, dict) or not isinstance(run, dict):
            raise ValueError("invalid message transaction")
        self._require_session_unlocked(session_id, index)
        self._validate_owned_record(message, "messageId", session_id)
        self._validate_owned_record(run, "runId", session_id)

        run_path = self._run_path(session_id, str(run["runId"]))
        existing_run = _read_json(run_path)
        if existing_run is None:
            created_run = self._create_run_unlocked(index, run, write_index=False)
        elif isinstance(existing_run, dict) and existing_run.get("sessionId") == session_id:
            created_run = existing_run
            index["runs"][created_run["runId"]] = session_id
            self._sync_active_run_unlocked(index, session_id, created_run)
        else:
            raise ValueError("message transaction run conflict")

        messages = _read_jsonl(self._messages_path(session_id))
        if not any(item.get("messageId") == message["messageId"] for item in messages):
            _append_jsonl(self._messages_path(session_id), message)

        events = _read_jsonl(self._events_path(session_id))
        has_idempotency_event = any(
            item.get("type") == "message.completed"
            and isinstance(item.get("data"), dict)
            and item["data"].get("clientMessageId") == client_message_id
            for item in events
        )
        if not has_idempotency_event:
            _append_jsonl(
                self._events_path(session_id),
                self._idempotency_event_unlocked(
                    session_id,
                    client_message_id,
                    message,
                    str(created_run["runId"]),
                ),
            )

        index["clientMessages"].setdefault(session_id, {})[client_message_id] = {
            "messageId": message["messageId"],
            "runId": created_run["runId"],
        }
        self._update_session_from_message_unlocked(session_id, message, index=index)
        self._write_index_unlocked(index)
        transaction_path = self._message_transaction_path(session_id, client_message_id)
        try:
            os.remove(transaction_path)
        except FileNotFoundError:
            pass
        return {
            "message": copy.deepcopy(message),
            "run": copy.deepcopy(created_run),
            "created": True,
        }

    def _recover_message_transactions_unlocked(self, index: JsonObject) -> None:
        try:
            session_ids = os.listdir(self.sessions_root)
        except OSError:
            return
        for session_id in session_ids:
            transactions_dir = os.path.join(self.sessions_root, session_id, "transactions")
            try:
                filenames = os.listdir(transactions_dir)
            except OSError:
                continue
            for filename in filenames:
                if not filename.endswith(".json"):
                    continue
                transaction = _read_json(os.path.join(transactions_dir, filename))
                if not isinstance(transaction, dict):
                    continue
                try:
                    self._commit_message_transaction_unlocked(index, transaction)
                except Exception:
                    continue

    @staticmethod
    def _validate_identifier(identifier: str, label: str) -> None:
        if not identifier or identifier in (".", "..") or os.path.basename(identifier) != identifier:
            raise ValueError("invalid " + label)

    def _require_session_unlocked(self, session_id: str, index: Optional[JsonObject] = None) -> JsonObject:
        current_index = index or self._load_index_unlocked()
        session = current_index["sessions"].get(session_id)
        if not isinstance(session, dict):
            raise KeyError(session_id)
        return session

    @staticmethod
    def _validate_owned_record(record: JsonObject, id_field: str, session_id: str) -> None:
        if not isinstance(record.get(id_field), str) or not record[id_field]:
            raise ValueError(id_field + " is required")
        if record.get("sessionId") != session_id:
            raise ValueError("record belongs to another session")

    def _create_run_unlocked(
        self,
        index: JsonObject,
        run: JsonObject,
        write_index: bool = True,
    ) -> JsonObject:
        session_id = run.get("sessionId")
        run_id = run.get("runId")
        if not isinstance(session_id, str) or not isinstance(run_id, str):
            raise ValueError("runId and sessionId are required")
        self._require_session_unlocked(session_id, index)
        if run_id in index["runs"] or os.path.exists(self._run_path(session_id, run_id)):
            raise ValueError("run already exists")
        _atomic_write_json(self._run_path(session_id, run_id), run)
        index["runs"][run_id] = session_id
        self._sync_active_run_unlocked(index, session_id, run)
        if write_index:
            self._write_index_unlocked(index)
        return run

    def _sync_active_run_unlocked(self, index: JsonObject, session_id: str, run: JsonObject) -> None:
        session = index["sessions"].get(session_id)
        if not isinstance(session, dict):
            return
        updated = dict(session)
        unfinished = run.get("status") in {"queued", "running", "waiting_approval", "paused"}
        if unfinished:
            updated["activeRunId"] = run["runId"]
        elif updated.get("activeRunId") == run.get("runId"):
            updated.pop("activeRunId", None)
        else:
            return
        updated["updatedAt"] = _utc_now()
        _atomic_write_json(os.path.join(self._session_dir(session_id), "session.json"), updated)
        index["sessions"][session_id] = updated

    def _update_session_from_message_unlocked(
        self,
        session_id: str,
        message: JsonObject,
        index: Optional[JsonObject] = None,
    ) -> None:
        current_index = index or self._load_index_unlocked()
        session = self._require_session_unlocked(session_id, current_index)
        updated = dict(session)
        preview = self._message_preview(message)
        if preview:
            updated["lastMessagePreview"] = preview[:240]
        updated["updatedAt"] = _utc_now()
        _atomic_write_json(os.path.join(self._session_dir(session_id), "session.json"), updated)
        current_index["sessions"][session_id] = updated
        if index is None:
            self._write_index_unlocked(current_index)

    @staticmethod
    def _message_preview(message: JsonObject) -> str:
        for block in message.get("blocks", []):
            if isinstance(block, dict) and block.get("type") == "text":
                data = block.get("data")
                if isinstance(data, dict) and isinstance(data.get("text"), str):
                    return data["text"].strip()
        return ""

    def _find_message_unlocked(self, session_id: str, message_id: str) -> JsonObject:
        for message in _read_jsonl(self._messages_path(session_id)):
            if message.get("messageId") == message_id:
                return copy.deepcopy(message)
        raise KeyError(message_id)

    def _idempotency_event_unlocked(
        self,
        session_id: str,
        client_message_id: str,
        message: JsonObject,
        run_id: str,
    ) -> JsonObject:
        message_id = str(message["messageId"])
        events = _read_jsonl(self._events_path(session_id))
        seq = max((event.get("seq", 0) for event in events if isinstance(event.get("seq"), int)), default=0) + 1
        return {
            "schema": "loom.realtime.event.v1",
            "eventId": "evt_" + uuid.uuid4().hex,
            "seq": seq,
            "timestamp": _utc_now(),
            "topic": "agent.message",
            "entityId": message_id,
            "type": "message.completed",
            "data": {
                "sessionId": session_id,
                "clientMessageId": client_message_id,
                "messageId": message_id,
                "runId": run_id,
                "message": copy.deepcopy(message),
            },
        }

    def _empty_index(self) -> JsonObject:
        return {
            "schema": self.INDEX_SCHEMA,
            "sessions": {},
            "runs": {},
            "approvals": {},
            "clientMessages": {},
        }

    def _load_index_unlocked(self) -> JsonObject:
        index = _read_json(self.index_path)
        if (
            isinstance(index, dict)
            and index.get("schema") == self.INDEX_SCHEMA
            and isinstance(index.get("sessions"), dict)
            and isinstance(index.get("runs"), dict)
            and isinstance(index.get("approvals"), dict)
            and isinstance(index.get("clientMessages"), dict)
        ):
            return index
        return self._rebuild_index_unlocked()

    def _rebuild_index_unlocked(self) -> JsonObject:
        index = self._empty_index()
        try:
            session_ids = os.listdir(self.sessions_root)
        except OSError:
            session_ids = []
        for session_id in session_ids:
            session_dir = os.path.join(self.sessions_root, session_id)
            if not os.path.isdir(session_dir):
                continue
            session = _read_json(os.path.join(session_dir, "session.json"))
            if isinstance(session, dict) and session.get("sessionId") == session_id:
                index["sessions"][session_id] = session
            runs_dir = os.path.join(session_dir, "runs")
            try:
                run_files = os.listdir(runs_dir)
            except OSError:
                run_files = []
            for filename in run_files:
                if not filename.endswith(".json"):
                    continue
                run = _read_json(os.path.join(runs_dir, filename))
                if isinstance(run, dict) and run.get("sessionId") == session_id and isinstance(run.get("runId"), str):
                    index["runs"][run["runId"]] = session_id
            approvals_dir = os.path.join(session_dir, "approvals")
            try:
                approval_files = os.listdir(approvals_dir)
            except OSError:
                approval_files = []
            for filename in approval_files:
                if not filename.endswith(".json"):
                    continue
                approval = _read_json(os.path.join(approvals_dir, filename))
                if (
                    isinstance(approval, dict)
                    and approval.get("sessionId") == session_id
                    and isinstance(approval.get("approvalId"), str)
                ):
                    index["approvals"][approval["approvalId"]] = session_id
            for event in _read_jsonl(os.path.join(session_dir, "events.jsonl")):
                data = event.get("data")
                if event.get("type") != "message.completed" or not isinstance(data, dict):
                    continue
                client_message_id = data.get("clientMessageId")
                message_id = data.get("messageId")
                run_id = data.get("runId")
                if all(isinstance(value, str) and value for value in (client_message_id, message_id, run_id)):
                    index["clientMessages"].setdefault(session_id, {})[client_message_id] = {
                        "messageId": message_id,
                        "runId": run_id,
                    }
        self._write_index_unlocked(index)
        return index

    def _write_index_unlocked(self, index: JsonObject) -> None:
        _atomic_write_json(self.index_path, index)
