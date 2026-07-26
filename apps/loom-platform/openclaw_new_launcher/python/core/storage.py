"""JSON storage helpers with conservative merge behavior."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from typing import Any


def read_json(path: str, default: Any | None = None) -> Any:
    if not os.path.exists(path):
        return {} if default is None else default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def write_json(path: str, data: Any, *, ensure_ascii: bool = False) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=ensure_ascii)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def update_json(path: str, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    updated = updater(data)
    if updated is not None:
        data = updated
    write_json(path, data)
    return data


def add_unique(values: list[str], value: str) -> list[str]:
    if value not in values:
        values.append(value)
    return values
