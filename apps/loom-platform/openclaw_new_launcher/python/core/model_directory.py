"""Side-effect-free helpers for live Provider compatibility probes."""

from __future__ import annotations

import json
from typing import Any, Iterable


_NON_TEXT_MODEL_MARKERS = (
    "embedding",
    "rerank",
    "moderation",
    "whisper",
    "tts",
    "audio",
    "image",
    "dall-e",
    "flux",
    "imagen",
    "seedream",
    "video",
    "sora",
    "veo",
    "seedance",
    "kling",
)


def choose_live_text_model(
    model_ids: Iterable[Any],
    preferred_model: str = "",
) -> tuple[str, bool]:
    """Choose from the live catalog; never trust a stale preferred model."""

    models: list[str] = []
    for raw in model_ids or []:
        model = str(raw or "").strip()
        if model and model.casefold() not in {item.casefold() for item in models}:
            models.append(model)
    text_models = [model for model in models if _looks_like_text_model(model)]
    if not text_models:
        raise ValueError("provider_text_models_empty")
    preferred = str(preferred_model or "").strip()
    if preferred:
        selected = next(
            (model for model in text_models if model.casefold() == preferred.casefold()),
            "",
        )
        if selected:
            return selected, False
    return text_models[0], bool(preferred)


def protocol_text_verified(protocol: str, payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    if protocol == "responses":
        if str(payload.get("output_text") or "").strip():
            return True
        output = payload.get("output")
        return isinstance(output, list) and bool(output)
    if protocol == "chat_completions":
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return False
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        return isinstance(message, dict) and bool(str(message.get("content") or "").strip())
    return False


def protocol_tool_call_verified(protocol: str, payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    if protocol == "responses":
        output = payload.get("output")
        if not isinstance(output, list):
            return False
        candidates = [item for item in output if isinstance(item, dict)]
        for item in candidates:
            if item.get("type") != "function_call":
                continue
            if str(item.get("name") or "").strip() != "loom_capability_probe":
                continue
            if _probe_arguments_match(item.get("arguments")):
                return True
        return False
    if protocol == "chat_completions":
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return False
        for choice in choices:
            message = choice.get("message") if isinstance(choice, dict) else None
            tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                if not isinstance(function, dict):
                    continue
                if str(function.get("name") or "").strip() != "loom_capability_probe":
                    continue
                if _probe_arguments_match(function.get("arguments")):
                    return True
        return False
    return False


def _probe_arguments_match(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    return isinstance(value, dict) and value.get("probe") == "provider-tools"


def _looks_like_text_model(model_id: str) -> bool:
    lowered = str(model_id or "").strip().lower()
    return bool(lowered) and not any(marker in lowered for marker in _NON_TEXT_MODEL_MARKERS)
