"""Bounded text log storage helpers."""

from __future__ import annotations

import os
import secrets
import threading
from typing import Any


_LOG_FILE_LOCK = threading.RLock()
_LOG_FILE_GENERATIONS: dict[str, dict[str, Any]] = {}


def _file_identity(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return int(stat.st_dev), int(stat.st_ino)


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _new_generation() -> str:
    return secrets.token_hex(16)


def _current_generation_locked(path: str) -> str:
    key = _path_key(path)
    identity = _file_identity(path)
    state = _LOG_FILE_GENERATIONS.get(key)
    if state is None or state.get("identity") != identity:
        state = {"generation": _new_generation(), "identity": identity}
        _LOG_FILE_GENERATIONS[key] = state
    return str(state["generation"])


def _adopt_current_identity_locked(path: str) -> str:
    key = _path_key(path)
    state = _LOG_FILE_GENERATIONS.get(key)
    if state is None:
        state = {"generation": _new_generation(), "identity": None}
        _LOG_FILE_GENERATIONS[key] = state
    state["identity"] = _file_identity(path)
    return str(state["generation"])


def _advance_generation_locked(path: str) -> str:
    generation = _new_generation()
    _LOG_FILE_GENERATIONS[_path_key(path)] = {
        "generation": generation,
        "identity": _file_identity(path),
    }
    return generation


def append_rotating_text(
    path: str,
    text: str,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    archive_count: int = 3,
) -> str:
    payload = str(text or "")
    if not payload:
        with _LOG_FILE_LOCK:
            return _current_generation_locked(path)
    encoded_bytes = len(payload.encode("utf-8"))
    max_bytes = max(256, int(max_bytes or 0))
    archive_count = max(1, min(int(archive_count or 0), 10))
    if encoded_bytes > max_bytes:
        payload = payload.encode("utf-8")[-max_bytes:].decode("utf-8", errors="ignore")
        encoded_bytes = len(payload.encode("utf-8"))
    with _LOG_FILE_LOCK:
        _current_generation_locked(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            current_bytes = os.path.getsize(path)
        except OSError:
            current_bytes = 0
        rotated = current_bytes > 0 and current_bytes + encoded_bytes > max_bytes
        if rotated:
            _rotate(path, archive_count)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(payload)
        if rotated:
            return _advance_generation_locked(path)
        return _adopt_current_identity_locked(path)


def read_text_tail(path: str, *, max_bytes: int = 512 * 1024) -> dict:
    max_bytes = max(256, int(max_bytes or 0))
    with _LOG_FILE_LOCK:
        if not os.path.exists(path):
            generation = _current_generation_locked(path)
            return _tail_snapshot(b"", total_bytes=0, generation=generation, exists=False)
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as handle:
                if size > max_bytes:
                    handle.seek(-max_bytes, os.SEEK_END)
                payload = handle.read(max_bytes)
        except OSError:
            generation = _current_generation_locked(path)
            return _tail_snapshot(b"", total_bytes=0, generation=generation, exists=False)
        generation = _current_generation_locked(path)
        if size > max_bytes and b"\n" in payload:
            _partial_line, remainder = payload.split(b"\n", 1)
            if remainder:
                payload = remainder
        elif size > max_bytes:
            while payload and payload[0] & 0xC0 == 0x80:
                payload = payload[1:]
        return _tail_snapshot(payload, total_bytes=size, generation=generation, exists=True)


def clear_text_log(path: str) -> dict:
    with _LOG_FILE_LOCK:
        generation = _current_generation_locked(path)
        try:
            if os.path.exists(path):
                with open(path, "w", encoding="utf-8"):
                    pass
            generation = _advance_generation_locked(path)
            return {"cleared": True, "generation": generation}
        except OSError:
            return {"cleared": False, "generation": generation}


def _tail_snapshot(
    payload: bytes,
    *,
    total_bytes: int,
    generation: str,
    exists: bool,
) -> dict:
    window_bytes = len(payload)
    omitted_bytes = max(0, int(total_bytes) - window_bytes)
    return {
        "text": payload.decode("utf-8", errors="ignore"),
        "generation": generation,
        "exists": exists,
        "totalBytes": int(total_bytes),
        "windowStartBytes": omitted_bytes,
        "windowBytes": window_bytes,
        "omittedBytes": omitted_bytes,
        "truncated": omitted_bytes > 0,
    }


def _rotate(path: str, archive_count: int) -> None:
    oldest = f"{path}.{archive_count}"
    if os.path.exists(oldest):
        os.remove(oldest)
    for index in range(archive_count - 1, 0, -1):
        source = f"{path}.{index}"
        if os.path.exists(source):
            os.replace(source, f"{path}.{index + 1}")
    if os.path.exists(path):
        os.replace(path, f"{path}.1")
