from __future__ import annotations

import json
from typing import Any

from .config import Settings

DEFAULT_FEATURES = ["openclaw", "image", "video", "storyboard"]


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_features(raw: str, *, default_features: list[str] | None = None) -> list[str]:
    features = [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    return features or list(default_features or DEFAULT_FEATURES)


def parse_models(raw: Any, *, default_gateway_models: list[str] | None = None) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return list(default_gateway_models if default_gateway_models is not None else Settings.from_env().gateway_models)
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]


def parse_json_object(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return dict(default or {})
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return dict(default or {})
    return data if isinstance(data, dict) else dict(default or {})


def parse_optional_models(
    raw: Any,
    fallback: list[str] | None = None,
    *,
    default_gateway_models: list[str] | None = None,
) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return list(fallback or [])
    return parse_models(text, default_gateway_models=default_gateway_models)


def load_json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def normalize_string(value: Any) -> str:
    return str(value or "").strip()


def clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(minimum, parsed))
