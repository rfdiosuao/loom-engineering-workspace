"""Risk classification and single-tool-call approval policy."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Mapping
from typing import Any

from core.agent_runtime import redact_sensitive


Json = dict[str, Any]
ACTION_LEVELS = {"read", "control_safe", "outbound", "critical"}
APPROVAL_MODES = {"strong", "weak"}


class PolicyViolationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PolicyDecision:
    classification: str
    requires_approval: bool
    allowed: bool
    reason: str

    def to_dict(self) -> Json:
        return {
            "classification": self.classification,
            "requiresApproval": self.requires_approval,
            "allowed": self.allowed,
            "reason": self.reason,
        }


class AgentPolicyEngine:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        approval_ttl_sec: int = 300,
        authorized_device_ids: set[str] | None = None,
        approval_mode: str = "strong",
    ):
        normalized_mode = str(approval_mode or "strong").strip().lower()
        if normalized_mode not in APPROVAL_MODES:
            raise ValueError(f"Unsupported approval mode: {approval_mode}")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.approval_ttl_sec = max(1, int(approval_ttl_sec))
        self.authorized_device_ids = set(authorized_device_ids) if authorized_device_ids is not None else None
        self.approval_mode = normalized_mode

    def classify(self, capability: Any, tool_input: Mapping[str, Any] | None = None) -> str:
        risk = str(_capability_value(capability, "risk", "") or "").lower()
        permission = str(_capability_value(capability, "permission", "read") or "read").lower()
        name = str(_capability_value(capability, "name", "") or "").lower()
        action_content = _action_content(capability, tool_input or {})
        searchable = f"{name} {action_content}"
        if _is_real_acquisition_run(name, tool_input or {}):
            return "critical"
        if _is_committed_external_publish(name, tool_input or {}):
            return "critical"
        if _is_media_generation_capability(name) and _media_transfer_targets(tool_input or {}):
            return "outbound"
        if any(marker in searchable for marker in _CRITICAL_MARKERS):
            return "critical"
        if any(marker in searchable for marker in _OUTBOUND_MARKERS):
            return "outbound"
        if risk in ACTION_LEVELS:
            return risk
        return "read" if permission == "read" else "control_safe"

    def evaluate(self, capability: Any, tool_input: Mapping[str, Any] | None = None) -> PolicyDecision:
        classification = self.classify(capability, tool_input)
        capability_name = str(_capability_value(capability, "name", "") or "").lower()
        approval_for_matrix_operation = _matrix_operation_requires_approval(
            capability_name,
            tool_input or {},
        )
        targets = _targets(tool_input or {}, capability_name)
        allowed = self._targets_allowed(targets)
        if not allowed:
            return PolicyDecision(classification, False, False, "Target is outside the authorized device scope.")
        requires_approval = (
            classification == "critical"
            if self.approval_mode == "weak"
            else classification in {"outbound", "critical"} or approval_for_matrix_operation
        )
        reasons = {
            "read": "Read-only capability may execute automatically.",
            "control_safe": "Bounded control may execute within the authorized target scope.",
            "outbound": (
                "Explicit user request may execute automatically within the authorized target scope."
                if self.approval_mode == "weak"
                else "External communication requires approval."
            ),
            "critical": "Critical account, payment, deletion, security, or committed external action requires approval.",
        }
        reason = (
            "Matrix dispatch or retry requires user approval."
            if approval_for_matrix_operation and self.approval_mode == "strong"
            else "Explicit user request may execute automatically within the authorized target scope."
            if approval_for_matrix_operation
            else reasons[classification]
        )
        return PolicyDecision(classification, requires_approval, True, reason)

    def create_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        capability: Any,
        tool_input: Mapping[str, Any],
    ) -> Json:
        decision = self.evaluate(capability, tool_input)
        if not decision.allowed:
            raise PolicyViolationError("target_not_authorized", decision.reason)
        if not decision.requires_approval:
            raise PolicyViolationError("approval_not_required", "This capability does not require approval.")
        capability_name = str(_capability_value(capability, "name", "") or "")
        targets = _targets(tool_input, capability_name)
        target_scope = str(
            _capability_value(
                capability,
                "target_scope",
                _capability_value(capability, "targetScope", "required"),
            )
            or "required"
        ).strip().lower()
        if decision.classification == "critical" and target_scope != "none" and not targets:
            raise PolicyViolationError("critical_target_required", "Critical actions require an explicit target.")
        now = _aware_utc(self._clock())
        capability_display_name = str(
            _capability_value(capability, "display_name", "")
            or _capability_value(capability, "displayName", "")
            or "受控操作"
        )
        safe_summary = _summarize(tool_input)
        return {
            "schema": "loom.agent.approval.v1",
            "approvalId": f"approval_{uuid.uuid4().hex}",
            "sessionId": session_id,
            "runId": run_id,
            "toolCallId": tool_call_id,
            "capability": capability_name,
            "inputHash": _input_hash(tool_input),
            "targetsHash": _input_hash(targets),
            "actionSummary": _action_summary(capability_display_name, tool_input),
            "targets": targets or {"scope": "explicit-user-action"},
            "inputSummary": safe_summary,
            "risk": decision.classification,
            "riskReason": decision.reason,
            "status": "pending",
            "requestedAt": _iso(now),
            "expiresAt": _iso(now + timedelta(seconds=self.approval_ttl_sec)),
        }

    def resolve_approval(self, approval: Mapping[str, Any], *, decision: str, decided_by: str) -> Json:
        if decision not in {"approved", "rejected"}:
            raise PolicyViolationError("invalid_approval_decision", "Approval decision must be approved or rejected.")
        if approval.get("status") != "pending":
            raise PolicyViolationError("approval_already_resolved", "Approval is no longer pending.")
        now = _aware_utc(self._clock())
        if _parse_time(approval.get("expiresAt")) <= now:
            return {**dict(approval), "status": "expired"}
        return {
            **dict(approval),
            "status": decision,
            "decision": decision,
            "decidedBy": str(decided_by),
            "decidedAt": _iso(now),
        }

    def is_authorized(
        self,
        approval: Mapping[str, Any] | None,
        tool_call_id: str,
        capability_name: str,
        tool_input: Mapping[str, Any],
    ) -> bool:
        if not isinstance(approval, Mapping) or approval.get("status") != "approved":
            return False
        if _parse_time(approval.get("expiresAt")) <= _aware_utc(self._clock()):
            return False
        return (
            approval.get("toolCallId") == tool_call_id
            and approval.get("capability") == capability_name
            and approval.get("inputHash") == _input_hash(tool_input)
            and approval.get("targetsHash") == _input_hash(_targets(tool_input, capability_name))
        )

    def consume_approval(
        self,
        approval: Mapping[str, Any],
        tool_call_id: str,
        capability_name: str,
        tool_input: Mapping[str, Any],
    ) -> Json:
        if not self.is_authorized(approval, tool_call_id, capability_name, tool_input):
            raise PolicyViolationError("approval_not_authorized", "Approval does not authorize this tool call.")
        return {**dict(approval), "status": "consumed", "consumedAt": _iso(_aware_utc(self._clock()))}

    def _targets_allowed(self, targets: Mapping[str, Any]) -> bool:
        if self.authorized_device_ids is None:
            return True
        if "groups" in targets or "allOnline" in targets:
            return False
        raw_devices = targets.get("deviceIds", [])
        if not isinstance(raw_devices, list):
            return False
        return all(str(device_id) in self.authorized_device_ids for device_id in raw_devices)


_OUTBOUND_MARKERS = (
    "send_dm",
    "send-message",
    "private_message",
    "post_comment",
    "comment.publish",
    "add_friend",
    "add_wechat",
    "publish",
    "outbound",
    "私信",
    "评论",
    "加好友",
    "发布",
)

_CRITICAL_MARKERS = (
    "payment",
    "purchase",
    "transfer_money",
    "delete_account",
    "account.delete",
    "grant_access",
    "security_setting",
    "reset_password",
    "支付",
    "转账",
    "删除账号",
    "账号授权",
    "安全设置",
)

_ACTION_TEXT_KEYS = ("action", "operation", "command", "task", "prompt")
_FREE_FORM_ACTION_SCOPES = {"single-device-write", "matrix-write"}


def _capability_value(capability: Any, name: str, default: Any) -> Any:
    if isinstance(capability, Mapping):
        return capability.get(name, default)
    return getattr(capability, name, default)


def _action_content(capability: Any, tool_input: Mapping[str, Any]) -> str:
    """Return only text that represents an executable action, not descriptive content."""

    permission = str(_capability_value(capability, "permission", "read") or "read").strip().lower()
    if permission == "read":
        return ""
    name = str(_capability_value(capability, "name", "") or "").strip().lower()
    target_scope = str(
        _capability_value(
            capability,
            "target_scope",
            _capability_value(capability, "targetScope", "none"),
        )
        or "none"
    ).strip().lower()
    if target_scope not in _FREE_FORM_ACTION_SCOPES and name not in {
        "loom.matrix.dispatch",
        "loom.phone.control",
    }:
        return ""

    values = [tool_input.get(key) for key in _ACTION_TEXT_KEYS if tool_input.get(key) is not None]
    assignments = tool_input.get("deviceAssignments")
    if isinstance(assignments, list):
        for assignment in assignments:
            if not isinstance(assignment, Mapping):
                continue
            values.extend(
                assignment.get(key)
                for key in _ACTION_TEXT_KEYS
                if assignment.get(key) is not None
            )
    return json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).lower()


def _targets(tool_input: Mapping[str, Any], capability_name: str = "") -> Json:
    for key in ("targets", "target"):
        value = tool_input.get(key)
        if isinstance(value, Mapping) and value:
            return redact_sensitive(dict(value))
    if _is_media_generation_capability(capability_name):
        media_targets = _media_transfer_targets(tool_input)
        if media_targets:
            return redact_sensitive(media_targets)
    if tool_input.get("deviceId"):
        return {"deviceIds": [str(tool_input["deviceId"])]}
    if tool_input.get("accountId"):
        return {"accountId": str(tool_input["accountId"])}
    return {}


def _is_media_generation_capability(capability_name: str) -> bool:
    return str(capability_name or "").strip().lower() in {
        "loom.media.image.generate",
        "loom.media.video.generate",
    }


def _media_transfer_targets(tool_input: Mapping[str, Any]) -> Json:
    device_ids = _target_string_list(tool_input.get("deviceIds"))
    groups = _target_string_list(tool_input.get("groups"))
    if device_ids:
        return {"deviceIds": device_ids}
    if groups:
        return {"groups": groups}
    if tool_input.get("allOnline") is True:
        return {"allOnline": True}
    return {}


def _target_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        item = str(raw or "").strip()[:80]
        if item and item not in result:
            result.append(item)
    return result


def _input_hash(tool_input: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(tool_input), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _matrix_operation_requires_approval(capability_name: str, tool_input: Mapping[str, Any]) -> bool:
    if capability_name == "loom.matrix.retry":
        return True
    if capability_name != "loom.matrix.dispatch":
        return False
    if str(tool_input.get("mode") or "").strip().lower() == "full":
        return True
    if str(tool_input.get("prompt") or "").strip():
        return True
    assignments = tool_input.get("deviceAssignments")
    if not isinstance(assignments, list):
        return False
    return any(
        isinstance(assignment, Mapping)
        and bool(str(assignment.get("prompt") or "").strip())
        for assignment in assignments
    )


def _is_real_acquisition_run(capability_name: str, tool_input: Mapping[str, Any]) -> bool:
    if not capability_name.endswith("loom_acquisition_agent_run"):
        return False
    value = tool_input.get("realRun")
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_committed_external_publish(capability_name: str, tool_input: Mapping[str, Any]) -> bool:
    return capability_name == "loom.phone.publish" and tool_input.get("draftOnly") is False


def _summarize(value: Any, *, depth: int = 0) -> Any:
    safe = redact_sensitive(value)
    if depth >= 3:
        return "[nested content omitted]"
    if isinstance(safe, Mapping):
        return {str(key)[:80]: _summarize(item, depth=depth + 1) for key, item in list(safe.items())[:20]}
    if isinstance(safe, list):
        return [_summarize(item, depth=depth + 1) for item in safe[:20]]
    if isinstance(safe, str):
        return safe[:240]
    return safe


def _action_summary(capability_display_name: str, tool_input: Mapping[str, Any]) -> str:
    raw_action = str(tool_input.get("action") or tool_input.get("operation") or "execute").strip().lower()
    action_labels = {
        "execute": "执行操作",
        "publish": "发布内容",
        "send": "发送内容",
        "delete_account": "删除账号",
        "scroll": "滚动屏幕",
        "tap": "点击屏幕",
        "input_text": "输入文字",
        "back": "返回",
        "home": "回到主页",
    }
    if raw_action in action_labels:
        action = action_labels[raw_action]
    elif raw_action and any("\u4e00" <= character <= "\u9fff" for character in raw_action):
        action = raw_action[:80]
    else:
        action = "执行操作"
    return f"{capability_display_name or '受控操作'}：{action}"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return _aware_utc(datetime.fromisoformat(text))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
