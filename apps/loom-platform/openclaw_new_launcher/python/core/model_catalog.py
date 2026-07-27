"""Shared, side-effect-free model catalog facts.

Catalog visibility is inventory evidence only. A model becomes selectable only
after at least one supported protocol has been verified by a caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


ALLOWED_CAPABILITIES = {
    "chat",
    "tools",
    "vision",
    "image_generation",
    "video_generation",
    "coding",
}
SUPPORTED_PROTOCOLS = {
    "chat_completions",
    "responses",
    "images",
    "videos",
}

_IMAGE_MARKERS = ("image", "dall-e", "flux", "imagen", "seedream", "stable-diffusion")
_VIDEO_MARKERS = ("video", "sora", "veo", "seedance", "kling", "hailuo", "runway")
_CODING_MARKERS = ("code", "coding", "coder", "codex")


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    display_name: str
    provider_id: str
    capabilities: tuple[str, ...]
    protocols: tuple[str, ...]
    available: bool
    unavailable_reason: str


def build_model_descriptors(
    entries: Iterable[Any],
    *,
    provider_id: str,
    aliases: Mapping[str, Iterable[str]] | None = None,
    protocol_evidence: Mapping[str, Iterable[str]] | None = None,
) -> list[ModelDescriptor]:
    """Normalize model inventory into deterministic immutable descriptors."""
    materialized = list(entries or [])
    alias_groups = _alias_groups(materialized, aliases or {})
    alias_to_canonical = {
        alias.casefold(): canonical
        for canonical, values in alias_groups.items()
        for alias in (canonical, *values)
    }
    external_protocols = _protocol_evidence(protocol_evidence or {}, alias_to_canonical)
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in materialized:
        item = entry if isinstance(entry, dict) else {}
        raw_id = _text(
            item.get("modelId"),
            item.get("id"),
            item.get("model"),
            item.get("name"),
            entry if not isinstance(entry, dict) else "",
        )
        if not raw_id:
            continue
        canonical = alias_to_canonical.get(raw_id.casefold(), raw_id)
        key = canonical.casefold()
        if key not in grouped:
            grouped[key] = {
                "model_id": canonical,
                "display_name": _text(item.get("displayName"), item.get("display_name"), canonical),
                "capabilities": [],
                "protocols": [],
                "explicit_unavailable": False,
                "unavailable_reason": "",
            }
            order.append(key)
        target = grouped[key]
        target["capabilities"] = _merge_unique(
            target["capabilities"],
            _capabilities(item.get("capabilities"), canonical),
        )
        target["protocols"] = _merge_unique(
            target["protocols"],
            _protocols(item.get("protocols")),
        )
        if item.get("available") is False:
            target["explicit_unavailable"] = True
        reason = _text(item.get("unavailableReason"), item.get("unavailable_reason"))
        if reason:
            target["unavailable_reason"] = reason

    result: list[ModelDescriptor] = []
    for key in order:
        item = grouped[key]
        protocols = tuple(_merge_unique(
            item["protocols"],
            external_protocols.get(key, []),
        ))
        available = bool(protocols) and not item["explicit_unavailable"]
        reason = item["unavailable_reason"]
        if available:
            reason = ""
        elif not reason:
            reason = "protocol_not_verified"
        result.append(ModelDescriptor(
            model_id=item["model_id"],
            display_name=item["display_name"],
            provider_id=_text(provider_id),
            capabilities=tuple(item["capabilities"] or _infer_capabilities(item["model_id"])),
            protocols=protocols,
            available=available,
            unavailable_reason=reason,
        ))
    return result


def model_descriptor_to_dict(descriptor: ModelDescriptor) -> dict[str, Any]:
    return {
        "modelId": descriptor.model_id,
        "displayName": descriptor.display_name,
        "providerId": descriptor.provider_id,
        "capabilities": list(descriptor.capabilities),
        "protocols": list(descriptor.protocols),
        "available": descriptor.available,
        "unavailableReason": descriptor.unavailable_reason,
    }


def selectable_model_ids(descriptors: Iterable[ModelDescriptor]) -> list[str]:
    return [
        descriptor.model_id
        for descriptor in descriptors or []
        if descriptor.available
    ]


def resolve_model_descriptor(
    descriptors: Iterable[ModelDescriptor],
    model_id_or_alias: str,
    *,
    aliases: Mapping[str, Iterable[str]] | None = None,
) -> ModelDescriptor | None:
    needle = _text(model_id_or_alias).casefold()
    if not needle:
        return None
    alias_groups = _normalize_alias_mapping(aliases or {})
    for descriptor in descriptors or []:
        candidates = [descriptor.model_id, *alias_groups.get(descriptor.model_id, [])]
        if any(candidate.casefold() == needle for candidate in candidates):
            return descriptor
    return None


def classify_model_catalog_error(error: Any, *, status_code: int | None = None) -> dict[str, Any]:
    raw = _text(error).lower()
    status = status_code or _status_code_from_text(raw)
    if "selected_model_not_listed" in raw:
        return _error(
            "selected_model_not_listed",
            "所选模型不在当前账号可见的模型目录中，请刷新目录后重新选择。",
            retryable=False,
        )
    if "provider_models_empty" in raw or "model_catalog_empty" in raw:
        return _error(
            "model_catalog_empty",
            "当前账号没有返回可用的模型目录，请检查账号分组或上游配置。",
            retryable=False,
        )
    if status == 404:
        return _error(
            "protocol_endpoint_not_found",
            "上游未提供所需的模型协议接口，请检查接口地址或模型协议。",
            retryable=False,
            status_code=404,
        )
    if status == 503:
        return _error(
            "upstream_temporarily_unavailable",
            "上游模型服务暂时不可用，请稍后重试。",
            retryable=True,
            status_code=503,
        )
    if status == 524:
        return _error(
            "upstream_response_timeout",
            "上游模型服务响应超时，请稍后重试或切换服务节点。",
            retryable=True,
            status_code=524,
        )
    if status is not None and 500 <= status <= 599:
        return _error(
            "upstream_service_error",
            "上游模型服务异常，请稍后重试。",
            retryable=True,
            status_code=status,
        )
    if "network_error" in raw or "timeout" in raw:
        return _error(
            "model_catalog_network_error",
            "模型目录连接失败，请检查网络后重试。",
            retryable=True,
        )
    return _error(
        "model_catalog_error",
        "模型目录暂时无法使用，请刷新后重试。",
        retryable=False,
        status_code=status,
    )


def _alias_groups(
    entries: Iterable[Any],
    configured: Mapping[str, Iterable[str]],
) -> dict[str, list[str]]:
    result = _normalize_alias_mapping(configured)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical = _text(
            entry.get("modelId"),
            entry.get("id"),
            entry.get("model"),
            entry.get("name"),
        )
        values = entry.get("aliases")
        if not canonical or not isinstance(values, (list, tuple, set)):
            continue
        existing = next((key for key in result if key.casefold() == canonical.casefold()), canonical)
        result[existing] = _merge_unique(result.get(existing, []), [_text(value) for value in values])
    return result


def _normalize_alias_mapping(aliases: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    canonical_by_folded: dict[str, str] = {}
    for raw_canonical, raw_values in aliases.items():
        canonical = _text(raw_canonical)
        if not canonical:
            continue
        canonical = canonical_by_folded.setdefault(canonical.casefold(), canonical)
        values = raw_values if not isinstance(raw_values, str) else [raw_values]
        result[canonical] = _merge_unique(result.get(canonical, []), [_text(value) for value in values])
    return result


def _protocol_evidence(
    evidence: Mapping[str, Iterable[str]],
    alias_to_canonical: Mapping[str, str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for raw_model, raw_protocols in evidence.items():
        model = _text(raw_model)
        if not model:
            continue
        canonical = alias_to_canonical.get(model.casefold(), model)
        result[canonical.casefold()] = _merge_unique(
            result.get(canonical.casefold(), []),
            _protocols(raw_protocols),
        )
    return result


def _protocols(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value] if value else []
    return sorted({
        _text(item).lower()
        for item in values
        if _text(item).lower() in SUPPORTED_PROTOCOLS
    })


def _capabilities(value: Any, model_id: str) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value] if value else []
    explicit = [
        _text(item).lower()
        for item in values
        if _text(item).lower() in ALLOWED_CAPABILITIES
    ]
    return _merge_unique(explicit, _infer_capabilities(model_id))


def _infer_capabilities(model_id: str) -> list[str]:
    lowered = model_id.lower()
    if any(marker in lowered for marker in _VIDEO_MARKERS):
        return ["video_generation"]
    if any(marker in lowered for marker in _IMAGE_MARKERS):
        return ["image_generation"]
    if any(marker in lowered for marker in _CODING_MARKERS):
        return ["chat", "coding"]
    return ["chat"]


def _error(
    code: str,
    message_zh: str,
    *,
    retryable: bool,
    status_code: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "messageZh": message_zh,
        "retryable": retryable,
        "statusCode": status_code,
    }


def _status_code_from_text(value: str) -> int | None:
    match = re.search(r"(?:http[_\s:-]*|status[_\s:-]*)(\d{3})", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _merge_unique(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            text = _text(value)
            folded = text.casefold()
            if not text or folded in seen:
                continue
            seen.add(folded)
            result.append(text)
    return result


def _text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "none":
            return text
    return ""
