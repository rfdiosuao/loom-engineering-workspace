"""JSON storage helpers with conservative merge behavior."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any


def read_json(path: str, default: Any | None = None) -> Any:
    if not os.path.exists(path):
        return {} if default is None else default
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def write_json(path: str, data: Any, *, ensure_ascii: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=ensure_ascii)


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

