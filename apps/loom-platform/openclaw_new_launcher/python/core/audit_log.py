"""Bounded, cross-process JSONL audit log storage."""

from __future__ import annotations

import os
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_ARCHIVE_COUNT = 5


def append_jsonl(path: str, line: str, *, max_bytes: int | None = None, archive_count: int | None = None) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (line.rstrip("\r\n") + "\n").encode("utf-8")
    size_limit = _configured_int("LOOM_AUDIT_MAX_BYTES", max_bytes, DEFAULT_MAX_BYTES, 256, 1024 * 1024 * 1024)
    archives = _configured_int("LOOM_AUDIT_ARCHIVE_COUNT", archive_count, DEFAULT_ARCHIVE_COUNT, 0, 50)

    with _exclusive_lock(str(target) + ".lock"):
        current_size = target.stat().st_size if target.exists() else 0
        if current_size > 0 and current_size + len(encoded) > size_limit:
            _rotate(target, archives)
        with target.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
    return str(target)


def tail_lines(path: str, limit: int, *, archive_count: int | None = None) -> list[str]:
    count = max(1, int(limit))
    archives = _configured_int("LOOM_AUDIT_ARCHIVE_COUNT", archive_count, DEFAULT_ARCHIVE_COUNT, 0, 50)
    rows: deque[str] = deque(maxlen=count)
    for candidate in archive_paths(path, archives, oldest_first=True):
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    rows.append(line.rstrip("\r\n"))
        except OSError:
            continue
    return list(rows)


def archive_paths(path: str, archive_count: int | None = None, *, oldest_first: bool = False) -> list[str]:
    archives = _configured_int("LOOM_AUDIT_ARCHIVE_COUNT", archive_count, DEFAULT_ARCHIVE_COUNT, 0, 50)
    indexes = range(archives, 0, -1) if oldest_first else range(1, archives + 1)
    candidates = [f"{path}.{index}" for index in indexes]
    candidates.append(path)
    return [candidate for candidate in candidates if os.path.exists(candidate)]


def _rotate(target: Path, archive_count: int) -> None:
    if archive_count <= 0:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    oldest = Path(f"{target}.{archive_count}")
    try:
        oldest.unlink()
    except FileNotFoundError:
        pass
    for index in range(archive_count - 1, 0, -1):
        source = Path(f"{target}.{index}")
        if source.exists():
            os.replace(source, Path(f"{target}.{index + 1}"))
    if target.exists():
        os.replace(target, Path(f"{target}.1"))


def _configured_int(name: str, explicit: int | None, default: int, minimum: int, maximum: int) -> int:
    raw = explicit if explicit is not None else os.environ.get(name, "")
    try:
        value = int(raw) if str(raw).strip() else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@contextmanager
def _exclusive_lock(path: str) -> Iterator[None]:
    handle = open(path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


__all__ = ["append_jsonl", "archive_paths", "tail_lines"]
