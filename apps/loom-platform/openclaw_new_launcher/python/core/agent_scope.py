from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any

from core.agent_language import has_positive_term, is_negated_occurrence


_ALL_ONLINE_PHRASES = (
    "全部在线设备",
    "所有在线设备",
    "全部在线手机",
    "所有在线手机",
    "全体在线设备",
    "全部手机",
    "所有手机",
    "全部设备",
    "所有设备",
    "all online devices",
    "all online phones",
)
_PHONE_ACTION_TERMS = (
    "控制",
    "操作",
    "执行",
    "继续",
    "打开",
    "点击",
    "返回",
    "启动",
    "关闭",
    "安装",
    "卸载",
    "登录",
    "发布",
    "发送",
    "传到",
    "传入",
    "传给",
    "传输",
    "上传",
    "导入",
    "保存到",
    "查看",
    "检查",
    "检测",
    "看看",
    "读取",
    "读屏",
    "截图",
    "屏幕",
    "分发",
    "重试",
    "取消",
)
_PHONE_CONTEXT_TERMS = ("手机", "设备", "矩阵", "那几台", "这几台", "那些", "这些", "那台", "这台")
_AMBIGUOUS_PLURAL_SCOPE_TERMS = ("那几台", "这几台", "那些", "这些", "多台", "几台")
_MOBILE_PLATFORM_TERMS = (
    "\u5c0f\u7ea2\u4e66",
    "\u6296\u97f3",
    "\u5feb\u624b",
    "\u5fae\u535a",
    "\u5fae\u4fe1",
    "qq",
    "\u95f2\u9c7c",
    "\u54b8\u9c7c",
    "\u6dd8\u5b9d",
    "\u4eac\u4e1c",
    "\u62fc\u591a\u591a",
    "\u7f8e\u56e2",
    "\u77e5\u4e4e",
    "boss\u76f4\u8058",
    "\u98de\u4e66",
    "\u9489\u9489",
    "\u6d4f\u89c8\u5668",
    "\u76f8\u673a",
    "\u76f8\u518c",
    "douyin",
    "xiaohongshu",
    "rednote",
)
_DEVICE_LIKE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])(?:P|PHONE|ANDROID)[-_]?\d[A-Za-z0-9_-]*(?![A-Za-z0-9_-])", re.IGNORECASE)


@dataclass
class ScopeResolution:
    status: str
    mode: str
    device_ids: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    all_online: bool = False
    summary: str = ""
    clarification: str = ""

    def targets(self) -> dict[str, Any]:
        if self.status != "resolved":
            return {}
        if self.device_ids:
            return {"deviceIds": list(self.device_ids)}
        if self.groups:
            return {"groups": list(self.groups)}
        if self.all_online:
            return {"allOnline": True}
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "targets": self.targets(),
            "summary": self.summary,
            **({"clarification": self.clarification} if self.clarification else {}),
        }


def resolve_request_scope(text: str, explicit_scope: Mapping[str, Any] | None, matrix_status: Mapping[str, Any] | None) -> ScopeResolution:
    scope = dict(explicit_scope) if isinstance(explicit_scope, Mapping) else {}
    mode = "manual" if str(scope.get("mode") or "auto").strip().lower() == "manual" else "auto"
    devices, groups, online_device_ids, device_aliases = _matrix_facts(matrix_status)
    online_count = len(online_device_ids)
    if mode == "manual":
        return _resolve_manual_scope(scope, devices, groups, online_count)

    content = str(text or "").strip()
    direct_device_ids = [device_id for device_id in devices if _contains_identifier(content, device_id)]
    alias_device_ids, ambiguous_alias = _resolve_device_aliases(content, device_aliases)
    if ambiguous_alias:
        return _ambiguous(mode, "设备名称对应多台手机，请改用设备 ID")
    selected_device_ids = set([*direct_device_ids, *alias_device_ids])
    device_ids = [device_id for device_id in devices if device_id in selected_device_ids]
    matched_groups = [group for group in groups if _contains_label(content, group)]
    folded = content.casefold()
    all_online = has_positive_term(folded, tuple(phrase.casefold() for phrase in _ALL_ONLINE_PHRASES))
    selector_count = sum(bool(value) for value in (device_ids, matched_groups, all_online))
    if selector_count > 1:
        return _ambiguous(mode, "请求同时包含不同类型的设备范围")
    if device_ids:
        return ScopeResolution(
            status="resolved",
            mode=mode,
            device_ids=device_ids,
            summary=f"已锁定 {len(device_ids)} 台设备",
        )
    if matched_groups:
        return ScopeResolution(
            status="resolved",
            mode=mode,
            groups=matched_groups,
            summary=f"已锁定 {len(matched_groups)} 个设备组",
        )
    if all_online:
        if online_count <= 0:
            return _ambiguous(mode, "当前没有在线设备")
        return ScopeResolution(
            status="resolved",
            mode=mode,
            all_online=True,
            summary=f"已锁定全部 {online_count} 台在线设备",
        )
    if _requires_phone_target(content):
        if any(term.casefold() in content.casefold() for term in _AMBIGUOUS_PLURAL_SCOPE_TERMS):
            return _ambiguous(mode, "请求包含多台设备，但没有明确设备范围")
        if len(online_device_ids) == 1:
            return ScopeResolution(
                status="resolved",
                mode=mode,
                device_ids=online_device_ids,
                summary="已自动选择唯一在线手机",
            )
        if len(devices) == 1:
            return ScopeResolution(
                status="resolved",
                mode=mode,
                device_ids=devices,
                summary="已自动选择唯一已配置手机",
            )
        return _ambiguous(mode, "请求涉及手机操作，但没有唯一可验证的设备范围")
    return ScopeResolution(
        status="not_required",
        mode=mode,
        summary="当前请求不需要手机范围",
    )


def _resolve_manual_scope(
    scope: Mapping[str, Any],
    devices: list[str],
    groups: list[str],
    online_count: int,
) -> ScopeResolution:
    device_ids = _string_list(scope.get("deviceIds"))
    selected_groups = _string_list(scope.get("groups"))
    all_online = scope.get("allOnline") is True
    selector_count = sum(bool(value) for value in (device_ids, selected_groups, all_online))
    if selector_count != 1:
        return _ambiguous("manual", "手动范围必须只选择设备、设备组或全部在线中的一种")
    if device_ids:
        if any(device_id not in devices for device_id in device_ids):
            return _ambiguous("manual", "手动选择包含当前矩阵中不存在的设备")
        return ScopeResolution("resolved", "manual", device_ids=device_ids, summary=f"已手动选择 {len(device_ids)} 台设备")
    if selected_groups:
        if any(group not in groups for group in selected_groups):
            return _ambiguous("manual", "手动选择包含当前矩阵中不存在的设备组")
        return ScopeResolution("resolved", "manual", groups=selected_groups, summary=f"已手动选择 {len(selected_groups)} 个设备组")
    if online_count <= 0:
        return _ambiguous("manual", "当前没有在线设备")
    return ScopeResolution("resolved", "manual", all_online=True, summary=f"已手动选择全部 {online_count} 台在线设备")


def _matrix_facts(
    matrix_status: Mapping[str, Any] | None,
) -> tuple[list[str], list[str], list[str], dict[str, list[str]]]:
    raw_devices = matrix_status.get("devices", []) if isinstance(matrix_status, Mapping) else []
    devices: list[str] = []
    groups: list[str] = []
    online_device_ids: list[str] = []
    device_aliases: dict[str, list[str]] = {}
    for item in raw_devices if isinstance(raw_devices, Sequence) and not isinstance(raw_devices, (str, bytes)) else []:
        if not isinstance(item, Mapping):
            continue
        device_id = str(item.get("deviceId") or "").strip()
        if device_id and device_id not in devices:
            devices.append(device_id)
        if device_id and item.get("online") is True and device_id not in online_device_ids:
            online_device_ids.append(device_id)
        for raw_alias in (item.get("name"), item.get("displayName"), item.get("alias")):
            alias = str(raw_alias or "").strip()
            if not device_id or not alias or alias.casefold() == device_id.casefold():
                continue
            alias_ids = device_aliases.setdefault(alias, [])
            if device_id not in alias_ids:
                alias_ids.append(device_id)
        raw_groups = item.get("groups") if isinstance(item.get("groups"), list) else []
        group_values = [item.get("group"), *raw_groups]
        for raw_group in group_values:
            group = str(raw_group or "").strip()
            if group and group not in groups:
                groups.append(group)
    return devices, groups, online_device_ids, device_aliases


def _resolve_device_aliases(text: str, aliases: Mapping[str, Sequence[str]]) -> tuple[list[str], bool]:
    matched_labels = [
        (label, _label_spans(text, label))
        for label in aliases
        if _contains_label(text, label)
    ]
    matched_labels.sort(key=lambda item: len(item[0]), reverse=True)
    specific_labels: list[str] = []
    covered_spans: list[tuple[int, int]] = []
    for label, spans in matched_labels:
        if not any(
            not any(start >= covered_start and end <= covered_end for covered_start, covered_end in covered_spans)
            for start, end in spans
        ):
            continue
        specific_labels.append(label)
        covered_spans.extend(spans)

    device_ids: list[str] = []
    for label in specific_labels:
        alias_ids = [str(item).strip() for item in aliases.get(label, []) if str(item).strip()]
        if len(alias_ids) != 1:
            return [], True
        if alias_ids[0] not in device_ids:
            device_ids.append(alias_ids[0])
    return device_ids, False


def _contains_identifier(text: str, identifier: str) -> bool:
    matches = re.finditer(
        rf"(?<![A-Za-z0-9_-]){re.escape(identifier)}(?![A-Za-z0-9_-])",
        text,
        re.IGNORECASE,
    )
    return any(not is_negated_occurrence(text, match.start()) for match in matches)


def _contains_label(text: str, label: str) -> bool:
    return bool(_label_spans(text, label))


def _label_spans(text: str, label: str) -> list[tuple[int, int]]:
    if not label:
        return []
    pattern = re.escape(label)
    if not re.search(r"[\u3400-\u9fff]", label):
        pattern = rf"(?<![A-Za-z0-9_-]){pattern}(?![A-Za-z0-9_-])"
    return [
        match.span()
        for match in re.finditer(pattern, text, re.IGNORECASE)
        if not is_negated_occurrence(text, match.start())
    ]


def _requires_phone_target(text: str) -> bool:
    folded = text.casefold()
    has_action = has_positive_term(folded, tuple(term.casefold() for term in _PHONE_ACTION_TERMS))
    has_context = has_positive_term(
        folded,
        tuple(term.casefold() for term in (*_PHONE_CONTEXT_TERMS, *_MOBILE_PLATFORM_TERMS)),
    )
    return has_action and (has_context or _DEVICE_LIKE_PATTERN.search(text) is not None)


def _ambiguous(mode: str, summary: str) -> ScopeResolution:
    return ScopeResolution(
        status="ambiguous",
        mode=mode,
        summary=summary,
        clarification="请告诉我要操作哪台手机、哪个设备组，或明确选择全部在线设备。",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if isinstance(item, str) and item.strip()))
