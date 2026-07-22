"""Deterministic two-stage capability routing for the central agent."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


Json = dict[str, Any]


_BROAD_INTENT_PATTERNS = (
    "全部能力",
    "所有能力",
    "完整能力",
    "能力目录",
    "能力列表",
    "已开放能力",
    "已连接能力",
    "连接的能力",
    "可以掌握什么",
    "你会什么",
    "你能做什么",
    "what can you do",
    "what capabilities",
    "connected capabilities",
    "all capabilities",
    "capability catalog",
)

_CAPABILITY_CATALOG_NAME = "loom.capabilities.list"
_LEGACY_CAPABILITY_CATALOG_SUFFIX = ".loom_cli_commands"

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "media": (
        "生图", "图片", "海报", "封面", "素材", "相册", "生视频", "视频", "image", "video", "media",
    ),
    "phone": (
        "手机", "设备", "截图", "读屏", "亮屏", "解锁", "点击", "输入", "返回键", "主页键", "发布",
        "抖音", "小红书", "快手", "微博", "微信", "qq", "闲鱼", "咸鱼", "淘宝", "京东", "拼多多",
        "美团", "知乎", "boss直聘", "飞书", "钉钉", "浏览器", "相机", "相册",
        "phone", "device", "screenshot", "publish",
    ),
    "matrix": (
        "矩阵", "多台", "批量", "设备组", "群控", "急停", "下发任务", "matrix", "fleet", "campaign",
    ),
    "acquisition": (
        "获客", "线索", "招聘", "简历", "boss直聘", "飞书", "客户", "lead", "acquisition", "feishu", "recruit",
    ),
    "schedule": ("定时", "计划任务", "日程", "调度", "schedule", "cron"),
    "models": ("模型", "供应商", "api key", "apikey", "provider", "model"),
    "account": ("账号", "登录", "订阅", "额度", "账户", "account", "login", "quota"),
    "license": ("授权", "授权码", "许可证", "激活码", "商业授权", "license", "activation"),
    "agent": ("智能体", "agent", "runtime", "运行时", "技能", "skill", "mcp", "cli"),
    "settings": ("设置", "主题", "深色", "浅色", "更新", "版本", "settings", "theme", "update", "version"),
    "diagnostics": (
        "诊断", "日志", "报错", "错误", "失败", "状态", "健康", "修复", "更新", "diagnostic", "log", "error", "status",
    ),
}

_CORE_NAME_PATTERNS = (
    ".capabilities.",
    ".capability.",
    ".jobs.get",
    ".jobs.list",
    ".logs.tail",
    "loom.status",
    "loom_status",
)


def route_capabilities(
    request: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
    checkpoint: Mapping[str, Any] | None = None,
) -> tuple[list[Json], Json]:
    """Return a focused catalog, with an automatic full-catalog safety fallback."""

    available = [dict(item) for item in capabilities if isinstance(item, Mapping)]
    checkpoint = checkpoint or {}
    text = _request_text(request)
    folded = text.casefold()
    explicit_mode = str(request.get("capabilityRoutingMode") or "").strip().lower()
    hinted = _available_capability_hints(request, available)

    catalog_capability = _capability_catalog(available)
    if (
        explicit_mode != "full"
        and any(pattern in folded for pattern in _BROAD_INTENT_PATTERNS)
        and catalog_capability is not None
    ):
        catalog_name = str(catalog_capability.get("name") or "").strip()
        if _has_capability_result(checkpoint, catalog_name):
            return [catalog_capability], _routing_metadata(
                "response_only",
                set(),
                len(available),
                1,
                "capability_catalog_available",
                hinted,
                toolChoice="none",
            )
        return [catalog_capability], _routing_metadata(
            "forced",
            set(),
            len(available),
            1,
            "capability_catalog_required",
            hinted,
            forcedCapability=catalog_name,
        )

    fallback_reason = ""
    if explicit_mode == "full":
        fallback_reason = "requested_full_catalog"
    elif int(checkpoint.get("toolSelectionRepairAttempts", 0) or 0) > 0:
        fallback_reason = "selection_repair"
    elif any(pattern in folded for pattern in _BROAD_INTENT_PATTERNS):
        fallback_reason = "broad_capability_intent"

    domains = _intent_domains(folded, request)
    if not fallback_reason and not domains and not hinted:
        fallback_reason = "ambiguous_intent"

    if fallback_reason:
        return available, _routing_metadata(
            "full", domains, len(available), len(available), fallback_reason, hinted
        )

    selected: list[Json] = []
    for capability in available:
        capability_domains = _capability_domains(capability)
        if (
            str(capability.get("name") or "") in hinted
            or capability_domains.intersection(domains)
            or _is_core_capability(capability)
        ):
            selected.append(capability)

    if not selected:
        return available, _routing_metadata(
            "full", domains, len(available), len(available), "empty_route", hinted
        )
    if len(selected) >= len(available):
        return available, _routing_metadata(
            "full", domains, len(available), len(available), "all_domains_selected", hinted
        )
    reason = "intent_match" if domains else "explicit_hint"
    return selected, _routing_metadata(
        "focused", domains, len(available), len(selected), reason, hinted
    )


def _available_capability_hints(
    request: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
) -> list[str]:
    raw_hints = request.get("capabilityHints")
    if not isinstance(raw_hints, list):
        return []
    available_names = {
        str(capability.get("name") or "").strip()
        for capability in capabilities
        if str(capability.get("name") or "").strip()
    }
    return sorted(
        {
            hint.strip()
            for hint in raw_hints
            if isinstance(hint, str) and hint.strip() in available_names
        }
    )


def _capability_catalog(capabilities: Sequence[Mapping[str, Any]]) -> Json | None:
    preferred: Json | None = None
    for capability in capabilities:
        name = str(capability.get("name") or "").strip()
        display_name = str(capability.get("displayName") or "").strip()
        if name == _CAPABILITY_CATALOG_NAME:
            return dict(capability)
        if display_name == "查看能力目录" or name.endswith(_LEGACY_CAPABILITY_CATALOG_SUFFIX):
            preferred = dict(capability)
    return preferred


def _has_capability_result(checkpoint: Mapping[str, Any], capability_name: str) -> bool:
    tool_results = checkpoint.get("toolResults")
    if not isinstance(tool_results, list):
        return False
    return any(
        isinstance(item, Mapping)
        and str(item.get("capability") or "").strip() == capability_name
        for item in tool_results
    )


def _request_text(request: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("prompt", "input", "text", "task", "message", "userMessage"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    messages = request.get("messages")
    if isinstance(messages, list):
        for item in messages[-4:]:
            if not isinstance(item, Mapping) or str(item.get("role") or "user") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                        chunks.append(str(block["text"]))
    return "\n".join(chunks)[:12000]


def _intent_domains(text: str, request: Mapping[str, Any]) -> set[str]:
    domains = {
        domain
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    }
    scope = request.get("requestScope")
    if isinstance(scope, Mapping):
        _add_target_domains(domains, scope)
        for key in ("target", "targets"):
            target = scope.get(key)
            if isinstance(target, Mapping):
                _add_target_domains(domains, target)
    for key in ("target", "targets"):
        target = request.get(key)
        if isinstance(target, Mapping):
            _add_target_domains(domains, target)
    return domains


def _add_target_domains(domains: set[str], target: Mapping[str, Any]) -> None:
    raw_device_ids = target.get("deviceIds") or target.get("devices")
    device_ids = raw_device_ids if isinstance(raw_device_ids, list) else []
    has_single_device = bool(target.get("deviceId")) or len(device_ids) == 1
    has_multiple_devices = len(device_ids) > 1
    has_matrix_target = bool(
        target.get("groupIds")
        or target.get("groups")
        or target.get("groupId")
        or target.get("group")
        or target.get("allOnline") is True
    )
    if has_single_device and not has_matrix_target:
        domains.add("phone")
    if has_multiple_devices or has_matrix_target:
        domains.add("matrix")


def _capability_domains(capability: Mapping[str, Any]) -> set[str]:
    haystack = " ".join(
        str(capability.get(key) or "")
        for key in ("name", "domain", "displayName", "description", "source")
    ).casefold()
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", haystack)))
    domains: set[str] = set()
    aliases = {
        "image": "media",
        "video": "media",
        "media": "media",
        "asset": "media",
        "phone": "phone",
        "device": "phone",
        "publish": "phone",
        "matrix": "matrix",
        "fleet": "matrix",
        "campaign": "matrix",
        "acquisition": "acquisition",
        "lead": "acquisition",
        "feishu": "acquisition",
        "schedule": "schedule",
        "cron": "schedule",
        "model": "models",
        "models": "models",
        "provider": "models",
        "account": "account",
        "auth": "account",
        "agent": "agent",
        "runtime": "agent",
        "skill": "agent",
        "diagnostics": "diagnostics",
        "diagnostic": "diagnostics",
        "logs": "diagnostics",
        "status": "diagnostics",
    }
    for token in tokens:
        mapped = aliases.get(token)
        if mapped:
            domains.add(mapped)
    metadata_domain = str(capability.get("domain") or "").strip().casefold()
    if metadata_domain:
        domains.add(aliases.get(metadata_domain, metadata_domain))
    return domains


def _is_core_capability(capability: Mapping[str, Any]) -> bool:
    name = str(capability.get("name") or "").casefold()
    normalized = f".{name}."
    return any(pattern in normalized for pattern in _CORE_NAME_PATTERNS)


def _routing_metadata(
    mode: str,
    domains: set[str],
    total: int,
    selected: int,
    reason: str,
    hinted: Sequence[str] = (),
    **extras: Any,
) -> Json:
    return {
        "schema": "loom.agent.capability-routing.v1",
        "mode": mode,
        "domains": sorted(domains),
        "total": total,
        "selected": selected,
        "reason": reason,
        "hinted": list(hinted),
        **extras,
    }


__all__ = ["route_capabilities"]
