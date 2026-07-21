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
        content = json.dumps(tool_input or {}, ensure_ascii=False, sort_keys=True, default=str).lower()
        searchable = f"{name} {content}"
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
        approval_for_dispatch = _matrix_dispatch_requires_approval(capability_name, tool_input or {})
        targets = _targets(tool_input or {})
        allowed = self._targets_allowed(targets)
        if not allowed:
            return PolicyDecision(classification, False, False, "Target is outside the authorized device scope.")
        requires_approval = (
            classification == "critical"
            if self.approval_mode == "weak"
            else classification in {"outbound", "critical"} or approval_for_dispatch
        )
        reasons = {
            "read": "Read-only capability may execute automatically.",
            "control_safe": "Bounded control may execute within the authorized target scope.",
            "outbound": (
                "Explicit user request may execute automatically within the authorized target scope."
                if self.approval_mode == "weak"
                else "External communication requires approval."
            ),
            "critical": "Critical account, payment, deletion, or security action requires approval.",
        }
        reason = (
            "Free-form or full-control Matrix dispatch requires user approval."
            if approval_for_dispatch and self.approval_mode == "strong"
            else "Explicit user request may execute automatically within the authorized target scope."
            if approval_for_dispatch
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
        targets = _targets(tool_input)
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
        capability_name = str(_capability_value(capability, "name", "") or "")
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
            and approval.get("targetsHash") == _input_hash(_targets(tool_input))
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


def _capability_value(capability: Any, name: str, default: Any) -> Any:
    if isinstance(capability, Mapping):
        return capability.get(name, default)
    return getattr(capability, name, default)


def _targets(tool_input: Mapping[str, Any]) -> Json:
    for key in ("targets", "target"):
        value = tool_input.get(key)
        if isinstance(value, Mapping) and value:
            return redact_sensitive(dict(value))
    if tool_input.get("deviceId"):
        return {"deviceIds": [str(tool_input["deviceId"])]}
    if tool_input.get("accountId"):
        return {"accountId": str(tool_input["accountId"])}
    return {}


def _input_hash(tool_input: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(tool_input), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _matrix_dispatch_requires_approval(capability_name: str, tool_input: Mapping[str, Any]) -> bool:
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
