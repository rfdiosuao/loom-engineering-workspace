"""Restart-aware lifecycle and tool-loop orchestration for central agent runs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from core.agent_capabilities import (
    CapabilityError,
    CapabilityExecutionError,
    CapabilityInputError,
    CapabilityRegistry,
)
from core.agent_capability_router import route_capabilities
from core.agent_policy import AgentPolicyEngine, PolicyViolationError
from core.agent_runtime import AgentRuntimeAdapter, RuntimeExecutionError, redact_sensitive
from core.agent_sessions import RepositoryConflictError


Json = dict[str, Any]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
MAX_TOOL_INPUT_REPAIR_ATTEMPTS = 1
MAX_TOOL_SELECTION_REPAIR_ATTEMPTS = 1
MAX_TOOL_EXECUTION_REPAIR_ATTEMPTS = 1
MAX_CONSECUTIVE_DEDUPLICATED_CALLS = 1
MAX_TOOL_CALLS_PER_ROUND = 32
TOOL_CALL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
CAPABILITY_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,159}\Z")
RUNTIME_PROGRESS_EVENT_TYPES = frozenset({
    "message.delta",
    "plan.updated",
    "model.usage",
    "model.tool_call.delta",
    "model.completed",
    "model.failed",
})


class AgentRepositoryProtocol(Protocol):
    def create_run(self, run: Json) -> Json: ...
    def get_run(self, run_id: str, session_id: str | None = None) -> Json: ...
    def update_run(
        self,
        run_id: str,
        changes: Json,
        session_id: str | None = None,
        *,
        remove_fields: tuple[str, ...] = (),
    ) -> Json: ...
    def recover_unfinished_runs(self) -> list[Json]: ...
    def create_approval(self, approval: Json) -> Json: ...
    def get_approval(self, approval_id: str, session_id: str | None = None) -> Json: ...
    def update_approval(self, approval_id: str, changes: Json, session_id: str | None = None) -> Json: ...
    def compare_and_update_approval(
        self,
        approval_id: str,
        changes: Json,
        *,
        expected_status: str,
        session_id: str | None = None,
    ) -> Json: ...
    def append_message(self, session_id: str, message: Json) -> Json: ...


class AgentEventProtocol(Protocol):
    def publish(
        self,
        session_id: str,
        event_type: str,
        *,
        topic: str,
        entity_id: str,
        data: Json | None = None,
    ) -> Json: ...


@dataclass
class _RunControl:
    cancel: threading.Event = field(default_factory=threading.Event)
    action: str | None = None


class AgentOrchestrator:
    def __init__(
        self,
        repository: AgentRepositoryProtocol,
        event_bus: AgentEventProtocol,
        runtime: AgentRuntimeAdapter,
        capabilities: CapabilityRegistry,
        policy: AgentPolicyEngine,
        *,
        request_builder: Callable[[str, Json], Mapping[str, Any]] | None = None,
        matrix_attachment_listener: Callable[[str, str, str, Json], None] | None = None,
        max_tool_rounds: int = 20,
    ):
        self.repository = repository
        self.event_bus = event_bus
        self.runtime = runtime
        self.capabilities = capabilities
        self.policy = policy
        self.request_builder = request_builder
        self.matrix_attachment_listener = matrix_attachment_listener
        self.max_tool_rounds = max(1, int(max_tool_rounds))
        self._controls: dict[str, _RunControl] = {}
        self._pending_inputs: dict[tuple[str, str], Json] = {}
        self._lock = threading.RLock()

    def queue_run(self, session_id: str, *, run_id: str | None = None) -> Json:
        run = {
            "schema": "loom.agent.run.v1",
            "runId": run_id or f"run_{uuid.uuid4().hex}",
            "sessionId": session_id,
            "status": "queued",
            "campaignIds": [],
            "checkpoint": _dump_checkpoint(_empty_checkpoint()),
        }
        created = self.repository.create_run(run)
        self._emit(session_id, created["runId"], "run.queued", {"status": "queued"})
        return created

    def execute_run(
        self,
        session_id: str,
        run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> Json:
        run = self.repository.get_run(run_id, session_id=session_id)
        if run.get("status") in TERMINAL_STATUSES:
            return run
        control = self._control(run_id, reset=run.get("status") == "paused")
        if control.action == "cancel" or control.cancel.is_set() and control.action == "cancel":
            return self.cancel_run(run_id, session_id=session_id)

        checkpoint = _load_checkpoint(run.get("checkpoint"))
        _capture_request_scope(checkpoint, run, request)
        if checkpoint.get("inFlightToolCall") and run.get("status") == "paused":
            return run
        if run.get("status") == "waiting_approval":
            resumed = self._resume_approved_tool(session_id, run, checkpoint)
            if resumed is None:
                return self.repository.get_run(run_id, session_id=session_id)
            run, checkpoint = resumed
            if run.get("status") != "running":
                return run

        runtime_request = self._build_request(session_id, run, request, checkpoint)
        previous_status = str(run.get("status") or "")
        started_at = run.get("startedAt") or _utc_now()
        with self._lock:
            if control.cancel.is_set():
                return self._finish_control_request(session_id, run_id, control)
            run = self.repository.update_run(
                run_id,
                {"status": "running", "startedAt": started_at, "checkpoint": _dump_checkpoint(checkpoint)},
                session_id=session_id,
            )
        if previous_status != "running":
            self._emit(session_id, run_id, "run.started", {"status": "running", "startedAt": started_at})

        scope = runtime_request.get("requestScope")
        if isinstance(scope, Mapping) and scope.get("status") == "ambiguous":
            clarification = str(
                runtime_request.get("scopeClarification")
                or scope.get("clarification")
                or "请明确要操作的手机或设备组。"
            ).strip()
            return self._complete_run(
                session_id,
                run_id,
                {"final": {"text": clarification[:500]}},
                checkpoint,
            )

        for round_index in range(self.max_tool_rounds):
            if control.cancel.is_set():
                return self._finish_control_request(session_id, run_id, control)
            checkpoint["round"] = int(checkpoint.get("round", 0)) + 1
            routed, routing = route_capabilities(
                runtime_request,
                self.capabilities.list_capabilities(available_only=True),
                checkpoint,
            )
            runtime_request["capabilities"] = routed
            runtime_request["capabilityRouting"] = routing
            runtime_request["toolResults"] = list(checkpoint.get("toolResults", []))
            runtime_request["round"] = checkpoint["round"]
            try:
                result = self.runtime.start(
                    runtime_request,
                    lambda event: self._runtime_event(session_id, run_id, event),
                    control.cancel,
                )
            except RuntimeExecutionError as exc:
                if control.action in {"pause", "cancel"}:
                    return self._finish_control_request(session_id, run_id, control)
                return self._fail_run(session_id, run_id, exc.code, str(exc), exc.recoverable, checkpoint)
            except Exception as exc:
                if control.action in {"pause", "cancel"}:
                    return self._finish_control_request(session_id, run_id, control)
                return self._fail_run(session_id, run_id, "agent_runtime_failed", str(exc), True, checkpoint)

            if control.cancel.is_set():
                return self._finish_control_request(session_id, run_id, control)

            tool_calls = result.get("toolCalls", []) if isinstance(result, Mapping) else []
            if not isinstance(tool_calls, list):
                return self._fail_run(
                    session_id,
                    run_id,
                    "agent_runtime_invalid_tool_calls",
                    "Runtime toolCalls must be an array.",
                    True,
                    checkpoint,
                )
            if not tool_calls:
                return self._complete_run(session_id, run_id, result, checkpoint)

            try:
                normalized_tool_calls = _normalize_tool_call_batch(tool_calls, request)
            except ValueError as exc:
                return self._fail_run(
                    session_id,
                    run_id,
                    "agent_runtime_invalid_tool_calls",
                    str(exc),
                    True,
                    checkpoint,
                )

            for call in normalized_tool_calls:
                call_id = call["toolCallId"]
                if call_id in checkpoint["completedToolCallIds"]:
                    continue
                self._emit(
                    session_id,
                    run_id,
                    "tool.queued",
                    {"toolCallId": call_id, "capability": call["name"], "status": "queued"},
                )
                if control.cancel.is_set():
                    return self._finish_control_request(session_id, run_id, control)
                capability = None
                try:
                    capability = self.capabilities.get(call["name"])
                    call = self._bind_execution_scope(session_id, run_id, call, capability, checkpoint)
                    fingerprint = _tool_fingerprint(capability.name, call["input"])
                    previous_result = _previous_completed_tool_result(checkpoint, fingerprint)
                    can_refresh = (
                        capability.permission == "read"
                        and previous_result is not None
                        and _tool_result_requires_refresh(previous_result.get("result"))
                    )
                    if previous_result is not None and not can_refresh:
                        duplicate_count = int(checkpoint.get("consecutiveDeduplicatedToolCalls", 0) or 0) + 1
                        checkpoint["consecutiveDeduplicatedToolCalls"] = duplicate_count
                        if duplicate_count > MAX_CONSECUTIVE_DEDUPLICATED_CALLS:
                            error = {
                                "code": "agent_repeated_tool_call",
                                "message": "智能体连续请求了相同工具且没有新证据，已停止重复执行。",
                                "recoverable": True,
                            }
                            _close_failed_tool_checkpoint(checkpoint, call, error)
                            self._emit(
                                session_id,
                                run_id,
                                "tool.failed",
                                {"toolCallId": call_id, "capability": call["name"], "error": error},
                            )
                            return self._fail_run(
                                session_id,
                                run_id,
                                error["code"],
                                error["message"],
                                True,
                                checkpoint,
                            )
                        self._reuse_completed_tool_result(
                            session_id,
                            run_id,
                            call,
                            checkpoint,
                            previous_result,
                            fingerprint,
                        )
                        continue
                    checkpoint["consecutiveDeduplicatedToolCalls"] = 0
                    self.capabilities.validate_input(call["name"], call["input"])
                    decision = self.policy.evaluate(capability, call["input"])
                    if not decision.allowed:
                        raise PolicyViolationError("policy_denied", decision.reason)
                    if decision.requires_approval:
                        return self._wait_for_approval(session_id, run_id, call, capability, checkpoint)
                    self._execute_tool(session_id, run_id, call, capability, checkpoint)
                    if control.cancel.is_set():
                        return self._finish_control_request(session_id, run_id, control)
                except CapabilityInputError as exc:
                    if control.action in {"pause", "cancel"}:
                        return self._finish_control_request(session_id, run_id, control)
                    error = {
                        "code": exc.code,
                        "message": str(exc),
                        "recoverable": True,
                    }
                    _close_failed_tool_checkpoint(checkpoint, call, error)
                    repair_attempts = checkpoint.get("toolInputRepairAttempts")
                    if not isinstance(repair_attempts, dict):
                        repair_attempts = {}
                        checkpoint["toolInputRepairAttempts"] = repair_attempts
                    repair_count = int(repair_attempts.get(call["name"], 0) or 0) + 1
                    repair_attempts[call["name"]] = repair_count
                    self.repository.update_run(
                        run_id,
                        {"checkpoint": _dump_checkpoint(checkpoint)},
                        session_id=session_id,
                    )
                    self._emit(
                        session_id,
                        run_id,
                        "tool.input_rejected",
                        {
                            "toolCallId": call_id,
                            "capability": call["name"],
                            "status": "repairing",
                            "attempt": repair_count,
                            "error": error,
                        },
                    )
                    if repair_count <= MAX_TOOL_INPUT_REPAIR_ATTEMPTS:
                        break
                    self._emit(
                        session_id,
                        run_id,
                        "tool.failed",
                        {
                            "toolCallId": call_id,
                            "capability": call["name"],
                            "status": "failed",
                            "error": error,
                        },
                    )
                    return self._fail_run(
                        session_id,
                        run_id,
                        exc.code,
                        str(exc),
                        False,
                        checkpoint,
                    )
                except CapabilityError as exc:
                    if control.action in {"pause", "cancel"}:
                        return self._finish_control_request(session_id, run_id, control)
                    code = getattr(exc, "code", "tool_failed")
                    recoverable = getattr(exc, "recoverable", False)
                    error_flags = _capability_error_flags(exc)
                    error = {
                        "code": code,
                        "message": str(exc),
                        "recoverable": bool(recoverable),
                        **error_flags,
                    }
                    if code == "capability_not_found":
                        _close_failed_tool_checkpoint(checkpoint, call, {**error, "recoverable": True})
                        repair_count = int(checkpoint.get("toolSelectionRepairAttempts", 0) or 0) + 1
                        checkpoint["toolSelectionRepairAttempts"] = repair_count
                        self.repository.update_run(
                            run_id,
                            {"checkpoint": _dump_checkpoint(checkpoint)},
                            session_id=session_id,
                        )
                        if repair_count <= MAX_TOOL_SELECTION_REPAIR_ATTEMPTS:
                            self._emit(
                                session_id,
                                run_id,
                                "tool.input_rejected",
                                {
                                    "toolCallId": call_id,
                                    "capability": call["name"],
                                    "status": "repairing",
                                    "reason": "selection",
                                    "attempt": repair_count,
                                    "error": {**error, "recoverable": True},
                                },
                            )
                            break
                    elif recoverable and not (
                        error_flags.get("outcomeIndeterminate")
                        or error_flags.get("executionMayContinue")
                    ):
                        _close_failed_tool_checkpoint(checkpoint, call, error)
                        repair_attempts = checkpoint.get("toolExecutionRepairAttempts")
                        if not isinstance(repair_attempts, dict):
                            repair_attempts = {}
                            checkpoint["toolExecutionRepairAttempts"] = repair_attempts
                        repair_key = f"{call['name']}:{code}"
                        repair_count = int(repair_attempts.get(repair_key, 0) or 0) + 1
                        repair_attempts[repair_key] = repair_count
                        self.repository.update_run(
                            run_id,
                            {"checkpoint": _dump_checkpoint(checkpoint)},
                            session_id=session_id,
                        )
                        if repair_count <= MAX_TOOL_EXECUTION_REPAIR_ATTEMPTS:
                            self._emit(
                                session_id,
                                run_id,
                                "tool.input_rejected",
                                {
                                    "toolCallId": call_id,
                                    "capability": call["name"],
                                    "status": "repairing",
                                    "reason": "execution",
                                    "attempt": repair_count,
                                    "error": error,
                                },
                            )
                            break
                    _close_failed_tool_checkpoint(checkpoint, call, error)
                    self._emit(
                        session_id,
                        run_id,
                        "tool.failed",
                        {"toolCallId": call_id, "capability": call["name"], "error": error},
                    )
                    return self._fail_run(
                        session_id,
                        run_id,
                        code,
                        str(exc),
                        recoverable,
                        checkpoint,
                        error_flags=error_flags,
                    )
                except PolicyViolationError as exc:
                    if control.action in {"pause", "cancel"}:
                        return self._finish_control_request(session_id, run_id, control)
                    code = getattr(exc, "code", "policy_denied")
                    recoverable = getattr(exc, "recoverable", False)
                    error_flags = _capability_error_flags(exc)
                    error = {
                        "code": code,
                        "message": str(exc),
                        "recoverable": bool(recoverable),
                        **error_flags,
                    }
                    _close_failed_tool_checkpoint(checkpoint, call, error)
                    self._emit(
                        session_id,
                        run_id,
                        "tool.failed",
                        {"toolCallId": call_id, "capability": call["name"], "error": error},
                    )
                    return self._fail_run(
                        session_id,
                        run_id,
                        code,
                        str(exc),
                        recoverable,
                        checkpoint,
                        error_flags=error_flags,
                    )
                except Exception as exc:
                    if control.action in {"pause", "cancel"}:
                        return self._finish_control_request(session_id, run_id, control)
                    self._emit(
                        session_id,
                        run_id,
                        "tool.failed",
                        {"toolCallId": call_id, "capability": call["name"], "error": {"code": "tool_failed", "message": str(exc)}},
                    )
                    return self._fail_run(session_id, run_id, "tool_failed", str(exc), True, checkpoint)
            self.repository.update_run(run_id, {"checkpoint": _dump_checkpoint(checkpoint)}, session_id=session_id)

        return self._fail_run(
            session_id,
            run_id,
            "agent_tool_loop_limit",
            "Agent exceeded the maximum number of tool rounds.",
            True,
            checkpoint,
        )

    def pause_run(self, run_id: str, *, session_id: str | None = None) -> Json:
        with self._lock:
            run = self.repository.get_run(run_id, session_id=session_id)
            if run.get("status") in TERMINAL_STATUSES:
                return run
            session_id = str(run["sessionId"])
            control = self._control(run_id)
            control.action = "pause"
            control.cancel.set()
            updated = self.repository.update_run(run_id, {"status": "paused"}, session_id=session_id)
        self._emit(session_id, run_id, "run.paused", {"checkpoint": updated.get("checkpoint")})
        return updated

    def resume_run(
        self,
        run_id: str,
        *,
        session_id: str | None = None,
        request: Mapping[str, Any] | None = None,
    ) -> Json:
        run = self.repository.get_run(run_id, session_id=session_id)
        if run.get("status") != "paused":
            return run
        session_id = str(run["sessionId"])
        with self._lock:
            self._controls[run_id] = _RunControl()
        self.repository.update_run(
            run_id,
            {"status": "queued"},
            session_id=session_id,
            remove_fields=("error", "completedAt"),
        )
        return self.execute_run(session_id, run_id, request)

    def cancel_run(self, run_id: str, *, session_id: str | None = None) -> Json:
        with self._lock:
            run = self.repository.get_run(run_id, session_id=session_id)
            if run.get("status") in TERMINAL_STATUSES:
                return run
            session_id = str(run["sessionId"])
            control = self._control(run_id)
            control.action = "cancel"
            control.cancel.set()
            updated = self.repository.update_run(
                run_id,
                {"status": "cancelled", "completedAt": _utc_now()},
                session_id=session_id,
            )
        self._emit(session_id, run_id, "run.cancelled", {})
        return updated

    def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        request: Mapping[str, Any] | None = None,
        defer_execution: bool = False,
    ) -> Json:
        approval = self.repository.get_approval(approval_id, session_id=session_id)
        try:
            resolved = self.policy.resolve_approval(approval, decision=decision, decided_by=decided_by)
            resolved = self.repository.compare_and_update_approval(
                approval_id,
                resolved,
                expected_status="pending",
                session_id=session_id,
            )
        except RepositoryConflictError as exc:
            raise PolicyViolationError("approval_conflict", "Approval was resolved by another request.") from exc
        except PolicyViolationError as exc:
            if exc.code == "approval_already_resolved":
                raise PolicyViolationError("approval_conflict", "Approval was resolved by another request.") from exc
            raise
        run_id = str(resolved["runId"])
        self._emit(
            session_id,
            run_id,
            "approval.resolved",
            {
                "approvalId": approval_id,
                "toolCallId": resolved["toolCallId"],
                "capability": resolved.get("capability"),
                "decision": decision,
                "status": resolved.get("status"),
                "decidedBy": resolved.get("decidedBy"),
                "decidedAt": resolved.get("decidedAt"),
            },
        )
        if resolved.get("status") != "approved":
            error_code = "approval_rejected" if resolved.get("status") == "rejected" else "approval_expired"
            error = {
                "code": error_code,
                "message": "Approval did not authorize the pending tool call.",
                "recoverable": True,
            }
            self._emit(
                session_id,
                run_id,
                "tool.failed",
                {
                    "toolCallId": resolved["toolCallId"],
                    "capability": resolved.get("capability"),
                    "status": "failed",
                    "error": error,
                },
            )
            run = self.repository.update_run(
                run_id,
                {
                    "status": "paused",
                    "error": error,
                },
                session_id=session_id,
            )
            self._emit(session_id, run_id, "run.paused", {"reason": run["error"]["code"]})
            return {"approval": resolved, "run": run}
        if defer_execution:
            return {
                "approval": resolved,
                "run": self.repository.get_run(run_id, session_id=session_id),
            }
        run = self.execute_run(session_id, run_id, request)
        return {"approval": self.repository.get_approval(approval_id, session_id=session_id), "run": run}

    def recover_unfinished_runs(self) -> list[Json]:
        recovered: list[Json] = []
        for run in self.repository.recover_unfinished_runs():
            if run.get("status") != "running":
                recovered.append(run)
                continue
            checkpoint = _load_checkpoint(run.get("checkpoint"))
            in_flight = bool(checkpoint.get("inFlightToolCall"))
            code = "agent_restart_inflight_unknown" if in_flight else "agent_restart_recovery"
            error = (
                {
                    "code": code,
                    "message": "应用停止时有工具正在执行；操作可能仍在目标端继续，麓鸣不会自动重放。",
                    "recoverable": False,
                    "outcomeIndeterminate": True,
                    "executionMayContinue": True,
                }
                if in_flight
                else {
                    "code": code,
                    "message": "The run was paused after application restart and can be resumed.",
                    "recoverable": True,
                }
            )
            tool_call = checkpoint.get("inFlightToolCall")
            if in_flight:
                _close_failed_tool_checkpoint(checkpoint, tool_call, error)
            status = "failed" if in_flight else "paused"
            changes = {
                "status": status,
                "error": error,
                "checkpoint": _dump_checkpoint(checkpoint),
            }
            if in_flight:
                changes["completedAt"] = _utc_now()
            updated = self.repository.update_run(
                run["runId"],
                changes,
                session_id=run["sessionId"],
            )
            if in_flight and isinstance(tool_call, Mapping):
                self._emit(
                    run["sessionId"],
                    run["runId"],
                    "tool.failed",
                    {
                        "toolCallId": str(tool_call.get("toolCallId") or tool_call.get("id") or ""),
                        "capability": str(tool_call.get("name") or tool_call.get("capability") or ""),
                        "status": "failed",
                        "error": error,
                    },
                )
            if in_flight:
                self._emit(run["sessionId"], run["runId"], "run.failed", {"error": error})
            else:
                self._emit(run["sessionId"], run["runId"], "run.paused", {"reason": code})
            recovered.append(updated)
        return recovered

    def record_unexpected_service_failure(
        self,
        session_id: str,
        run_id: str,
        message: str,
    ) -> Json:
        run = self.repository.get_run(run_id, session_id=session_id)
        if run.get("status") in TERMINAL_STATUSES:
            return run
        checkpoint = _load_checkpoint(run.get("checkpoint"))
        tool_call = checkpoint.get("inFlightToolCall")
        in_flight = isinstance(tool_call, Mapping) and bool(tool_call)
        if in_flight:
            error = {
                "code": "agent_service_inflight_unknown",
                "message": "智能体服务在工具执行期间异常退出；操作可能仍在目标端执行，请先检查实际状态，不要直接重试。",
                "recoverable": False,
                "outcomeIndeterminate": True,
                "executionMayContinue": True,
            }
            _close_failed_tool_checkpoint(checkpoint, tool_call, error)
        else:
            error = {
                "code": "agent_service_failed",
                "message": str(redact_sensitive(message or "Agent service failed unexpectedly."))[:500],
                "recoverable": True,
            }
        with self._lock:
            current = self.repository.get_run(run_id, session_id=session_id)
            if current.get("status") in TERMINAL_STATUSES:
                return current
            updated = self.repository.update_run(
                run_id,
                {
                    "status": "failed",
                    "completedAt": _utc_now(),
                    "checkpoint": _dump_checkpoint(checkpoint),
                    "error": error,
                },
                session_id=session_id,
            )
        if in_flight:
            call = dict(tool_call)
            try:
                self._emit(
                    session_id,
                    run_id,
                    "tool.failed",
                    {
                        "toolCallId": str(call.get("toolCallId") or call.get("id") or ""),
                        "capability": str(call.get("name") or call.get("capability") or ""),
                        "status": "failed",
                        "error": error,
                    },
                )
            except Exception:
                pass
        try:
            self._emit(session_id, run_id, "run.failed", {"error": error})
        except Exception:
            pass
        return updated

    def _wait_for_approval(self, session_id: str, run_id: str, call: Json, capability: Any, checkpoint: Json) -> Json:
        approval = self.policy.create_approval(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=call["toolCallId"],
            capability=capability,
            tool_input=call["input"],
        )
        self.repository.create_approval(approval)
        self._pending_inputs[(run_id, call["toolCallId"])] = dict(call["input"])
        checkpoint["pendingApproval"] = {
            "approvalId": approval["approvalId"],
            "toolCall": redact_sensitive(call),
        }
        updated = self.repository.update_run(
            run_id,
            {"status": "waiting_approval", "checkpoint": _dump_checkpoint(checkpoint)},
            session_id=session_id,
        )
        self._emit(
            session_id,
            run_id,
            "run.waiting_approval",
            {
                "status": "waiting_approval",
                "approvalId": approval["approvalId"],
                "toolCallId": call["toolCallId"],
                "capability": call["name"],
            },
        )
        self._emit(
            session_id,
            run_id,
            "approval.required",
            {
                "approvalId": approval["approvalId"],
                "toolCallId": call["toolCallId"],
                "capability": call["name"],
                "risk": approval["risk"],
                "actionSummary": approval["actionSummary"],
                "targets": approval["targets"],
            },
        )
        return updated

    def _resume_approved_tool(self, session_id: str, run: Json, checkpoint: Json) -> tuple[Json, Json] | None:
        pending = checkpoint.get("pendingApproval")
        if not isinstance(pending, Mapping):
            return None
        approval_id = str(pending.get("approvalId") or "")
        call = pending.get("toolCall")
        if not approval_id or not isinstance(call, Mapping):
            return None
        approval = self.repository.get_approval(approval_id, session_id=session_id)
        if approval.get("status") != "approved":
            return None
        normalized = _normalize_tool_call(call)
        raw_input = self._pending_inputs.get((run["runId"], normalized["toolCallId"]), normalized["input"])
        normalized["input"] = raw_input
        capability = self.capabilities.get(normalized["name"])
        if not self.policy.is_authorized(approval, normalized["toolCallId"], normalized["name"], raw_input):
            error = {
                "code": "approval_scope_mismatch",
                "message": "Approval no longer matches the pending tool call.",
                "recoverable": True,
            }
            _close_failed_tool_checkpoint(checkpoint, normalized, error)
            self._pending_inputs.pop((run["runId"], normalized["toolCallId"]), None)
            failed = self.repository.update_run(
                run["runId"],
                {
                    "status": "paused",
                    "error": error,
                    "checkpoint": _dump_checkpoint(checkpoint),
                },
                session_id=session_id,
            )
            self._emit(
                session_id,
                run["runId"],
                "tool.failed",
                {
                    "toolCallId": normalized["toolCallId"],
                    "capability": normalized["name"],
                    "status": "failed",
                    "error": error,
                },
            )
            self._emit(session_id, run["runId"], "run.paused", {"reason": "approval_scope_mismatch"})
            return failed, checkpoint
        control = self._control(str(run["runId"]))
        with self._lock:
            if control.cancel.is_set():
                return self._finish_control_request(session_id, str(run["runId"]), control), checkpoint
            run = self.repository.update_run(
                run["runId"],
                {"status": "running", "checkpoint": _dump_checkpoint(checkpoint)},
                session_id=session_id,
            )
        try:
            self._execute_tool(session_id, run["runId"], normalized, capability, checkpoint, approval=approval)
        except CapabilityError as exc:
            code = getattr(exc, "code", "tool_failed")
            recoverable = getattr(exc, "recoverable", False)
            error_flags = _capability_error_flags(exc)
            error = {
                "code": code,
                "message": str(exc),
                "recoverable": bool(recoverable),
                **error_flags,
            }
            _close_failed_tool_checkpoint(checkpoint, normalized, error)
            self._pending_inputs.pop((run["runId"], normalized["toolCallId"]), None)
            if recoverable and not (
                error_flags.get("outcomeIndeterminate")
                or error_flags.get("executionMayContinue")
            ):
                repair_attempts = checkpoint.get("toolExecutionRepairAttempts")
                if not isinstance(repair_attempts, dict):
                    repair_attempts = {}
                    checkpoint["toolExecutionRepairAttempts"] = repair_attempts
                repair_key = f"{normalized['name']}:{code}"
                repair_count = int(repair_attempts.get(repair_key, 0) or 0) + 1
                repair_attempts[repair_key] = repair_count
                if repair_count <= MAX_TOOL_EXECUTION_REPAIR_ATTEMPTS:
                    run = self.repository.update_run(
                        run["runId"],
                        {"status": "running", "checkpoint": _dump_checkpoint(checkpoint)},
                        session_id=session_id,
                    )
                    self._emit(
                        session_id,
                        run["runId"],
                        "tool.input_rejected",
                        {
                            "toolCallId": normalized["toolCallId"],
                            "capability": normalized["name"],
                            "status": "repairing",
                            "reason": "execution",
                            "attempt": repair_count,
                            "error": error,
                        },
                    )
                    return run, checkpoint
            self._emit(
                session_id,
                run["runId"],
                "tool.failed",
                {"toolCallId": normalized["toolCallId"], "capability": normalized["name"], "error": error},
            )
            return self._fail_run(
                session_id,
                run["runId"],
                code,
                str(exc),
                recoverable,
                checkpoint,
                error_flags=error_flags,
            ), checkpoint
        except PolicyViolationError as exc:
            code = getattr(exc, "code", "policy_denied")
            recoverable = getattr(exc, "recoverable", False)
            error_flags = _capability_error_flags(exc)
            error = {
                "code": code,
                "message": str(exc),
                "recoverable": bool(recoverable),
                **error_flags,
            }
            _close_failed_tool_checkpoint(checkpoint, normalized, error)
            self._pending_inputs.pop((run["runId"], normalized["toolCallId"]), None)
            self._emit(
                session_id,
                run["runId"],
                "tool.failed",
                {"toolCallId": normalized["toolCallId"], "capability": normalized["name"], "error": error},
            )
            return self._fail_run(
                session_id,
                run["runId"],
                code,
                str(exc),
                recoverable,
                checkpoint,
                error_flags=error_flags,
            ), checkpoint
        except Exception as exc:
            self._emit(
                session_id,
                run["runId"],
                "tool.failed",
                {
                    "toolCallId": normalized["toolCallId"],
                    "capability": normalized["name"],
                    "error": {"code": "tool_failed", "message": str(exc)},
                },
            )
            return self._fail_run(
                session_id,
                run["runId"],
                "tool_failed",
                str(exc),
                True,
                checkpoint,
            ), checkpoint
        checkpoint.pop("pendingApproval", None)
        with self._lock:
            if control.cancel.is_set():
                return self._finish_control_request(session_id, str(run["runId"]), control), checkpoint
            run = self.repository.update_run(
                run["runId"],
                {"status": "running", "checkpoint": _dump_checkpoint(checkpoint)},
                session_id=session_id,
            )
        return run, checkpoint

    def _bind_execution_scope(
        self,
        session_id: str,
        run_id: str,
        call: Json,
        capability: Any,
        checkpoint: Json,
    ) -> Json:
        target_scope = str(getattr(capability, "target_scope", "none") or "none")
        if target_scope == "none":
            return call

        tool_input = dict(call["input"])
        scope = checkpoint.get("requestScope")
        scope = scope if isinstance(scope, Mapping) else {}
        targets = scope.get("targets")
        targets = dict(targets) if isinstance(targets, Mapping) else {}

        if target_scope in {"single-device-read", "single-device-write"}:
            device_ids = _string_list(targets.get("deviceIds"))
            groups = _string_list(targets.get("groups"))
            supplied = _declared_scope_value(
                tool_input,
                direct_keys=("deviceId", "device", "target"),
                cli_options=("--device-id", "--device", "--target"),
            )
            if supplied and supplied not in device_ids:
                raise PolicyViolationError(
                    "phone_target_scope_required",
                    "phone_target_scope_required: Phone target must be selected in this run's request scope.",
                )
            if target_scope == "single-device-write" and (len(device_ids) != 1 or groups):
                code = "phone_target_scope_required" if not device_ids and not groups else "phone_single_target_required"
                raise PolicyViolationError(
                    code,
                    f"{code}: Single-phone control requires exactly one resolved device; use Matrix dispatch for multiple targets.",
                )
            if not supplied:
                if len(device_ids) == 1 and not groups:
                    supplied = device_ids[0]
                elif device_ids or groups:
                    raise PolicyViolationError(
                        "phone_single_target_required",
                        "phone_single_target_required: A single-phone tool requires one device; use Matrix dispatch for multiple targets.",
                    )
                else:
                    raise PolicyViolationError(
                        "phone_target_scope_required",
                        "phone_target_scope_required: Phone tools require a device selected in this run's request scope.",
                    )
            tool_input = _bind_single_device_input(tool_input, capability, supplied)

        elif target_scope == "matrix-write":
            if not targets:
                raise PolicyViolationError(
                    "matrix_target_scope_required",
                    "Matrix dispatch requires an explicit target selected for this run.",
                )
            tool_input = _bind_matrix_target_input(tool_input, capability, targets)

        elif target_scope == "optional-device-write":
            device_ids = _string_list(targets.get("deviceIds"))
            groups = _string_list(targets.get("groups"))
            all_online = targets.get("allOnline") is True
            for key in ("deviceIds", "groups", "allOnline"):
                tool_input.pop(key, None)
            if device_ids:
                tool_input["deviceIds"] = device_ids
            elif groups:
                tool_input["groups"] = groups
            elif all_online:
                tool_input["allOnline"] = True

        elif target_scope == "campaign-write":
            run = self.repository.get_run(run_id, session_id=session_id)
            campaign_ids = _string_list(scope.get("campaignIds"))
            campaign_ids = list(dict.fromkeys([*campaign_ids, *_string_list(run.get("campaignIds"))]))
            if not campaign_ids:
                raise PolicyViolationError(
                    "matrix_campaign_scope_required",
                    "Matrix cancel and retry require a campaign bound to this run.",
                )
            supplied = _declared_scope_value(
                tool_input,
                direct_keys=("campaignId", "id"),
                cli_options=("--campaign", "--campaign-id"),
            )
            if len(campaign_ids) == 1:
                campaign_id = campaign_ids[0]
            elif supplied in campaign_ids:
                campaign_id = supplied
            else:
                raise PolicyViolationError(
                    "matrix_campaign_scope_violation",
                    "Matrix campaign is outside this run's requested campaign scope.",
                )
            tool_input = _bind_campaign_input(tool_input, capability, campaign_id)

        return {**call, "input": tool_input}

    def _bind_matrix_scope(self, session_id: str, run_id: str, call: Json, checkpoint: Json) -> Json:
        capability = self.capabilities.get(str(call.get("name") or ""))
        return self._bind_execution_scope(session_id, run_id, call, capability, checkpoint)

    def _execute_tool(
        self,
        session_id: str,
        run_id: str,
        call: Json,
        capability: Any,
        checkpoint: Json,
        *,
        approval: Mapping[str, Any] | None = None,
    ) -> Any:
        call_id = call["toolCallId"]
        checkpoint["inFlightToolCall"] = redact_sensitive(call)
        self.repository.update_run(run_id, {"checkpoint": _dump_checkpoint(checkpoint)}, session_id=session_id)
        if approval is not None:
            consumed = self.policy.consume_approval(approval, call_id, call["name"], call["input"])
            try:
                self.repository.compare_and_update_approval(
                    str(approval["approvalId"]),
                    consumed,
                    expected_status="approved",
                    session_id=session_id,
                )
            except RepositoryConflictError as exc:
                raise PolicyViolationError("approval_conflict", "Approval was consumed by another request.") from exc
        self._emit(
            session_id,
            run_id,
            "tool.started",
            {"toolCallId": call_id, "capability": call["name"], "inputSummary": _summary(call["input"])},
        )
        result = self.capabilities.execute(call["name"], call["input"])
        completed_checkpoint = copy.deepcopy(checkpoint)
        try:
            safe_result = redact_sensitive(result)
            self._attach_matrix_result(session_id, run_id, call, safe_result)
            completed_checkpoint["completedToolCallIds"].append(call_id)
            completed_checkpoint["toolResults"].append(
                {
                    "toolCallId": call_id,
                    "capability": call["name"],
                    "status": "completed",
                    "input": _summary(call["input"]),
                    "result": _summary(safe_result),
                    "fingerprint": _tool_fingerprint(capability.name, call["input"]),
                }
            )
            completed_checkpoint["inFlightToolCall"] = None
            completed_checkpoint.pop("pendingApproval", None)
            self.repository.update_run(
                run_id,
                {"checkpoint": _dump_checkpoint(completed_checkpoint)},
                session_id=session_id,
            )
        except Exception as exc:
            raise CapabilityExecutionError(
                "agent_tool_result_persistence_failed",
                "工具已经执行，但麓鸣未能可靠保存执行结果；请先检查目标状态，不要直接重复执行。",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=False,
            ) from exc
        checkpoint.clear()
        checkpoint.update(completed_checkpoint)
        completed_data = {
            "toolCallId": call_id,
            "capability": call["name"],
            "outputSummary": _summary(safe_result),
        }
        if isinstance(safe_result, Mapping):
            if isinstance(safe_result.get("attachments"), list):
                completed_data["attachments"] = safe_result["attachments"]
            if isinstance(safe_result.get("phoneTransfer"), Mapping):
                completed_data["phoneTransfer"] = safe_result["phoneTransfer"]
        self._emit(
            session_id,
            run_id,
            "tool.completed",
            completed_data,
        )
        self._pending_inputs.pop((run_id, call_id), None)
        return safe_result

    def _reuse_completed_tool_result(
        self,
        session_id: str,
        run_id: str,
        call: Json,
        checkpoint: Json,
        previous_result: Mapping[str, Any],
        fingerprint: str,
    ) -> None:
        call_id = call["toolCallId"]
        if call_id not in checkpoint["completedToolCallIds"]:
            checkpoint["completedToolCallIds"].append(call_id)
        output_summary = _summary(previous_result.get("result"))
        checkpoint["toolResults"].append({
            "toolCallId": call_id,
            "capability": call["name"],
            "status": "completed",
            "input": _summary(call["input"]),
            "result": output_summary,
            "fingerprint": fingerprint,
            "deduplicated": True,
        })
        checkpoint["inFlightToolCall"] = None
        self.repository.update_run(
            run_id,
            {"checkpoint": _dump_checkpoint(checkpoint)},
            session_id=session_id,
        )
        self._emit(
            session_id,
            run_id,
            "tool.completed",
            {
                "toolCallId": call_id,
                "capability": call["name"],
                "outputSummary": output_summary,
                "deduplicated": True,
            },
        )

    def _attach_matrix_result(self, session_id: str, run_id: str, call: Json, result: Any) -> None:
        if not isinstance(result, Mapping):
            return
        campaign_id = str(result.get("campaignId") or "")
        if not campaign_id:
            return
        run = self.repository.get_run(run_id, session_id=session_id)
        campaign_ids = list(dict.fromkeys([*run.get("campaignIds", []), campaign_id]))
        self.repository.update_run(run_id, {"campaignIds": campaign_ids}, session_id=session_id)
        tasks = result.get("deviceTasks", [])
        failed_ids = [
            str(task.get("deviceId"))
            for task in tasks if isinstance(task, Mapping) and task.get("status") in {"failed", "cancelled", "needs_human"} and task.get("deviceId")
        ] if isinstance(tasks, list) else []
        counts = result.get("counts", {}) if isinstance(result.get("counts"), Mapping) else {}
        device_ids = [
            str(task.get("deviceId"))
            for task in tasks if isinstance(task, Mapping) and task.get("deviceId")
        ] if isinstance(tasks, list) else []
        self._emit(
            session_id,
            run_id,
            "matrix.attached",
            {
                "messageId": f"matrix:{campaign_id}",
                "campaignId": campaign_id,
                "runId": run_id,
                "toolCallId": call["toolCallId"],
                "status": str(result.get("status") or "queued"),
                "counts": _summary(counts),
                "total": int(counts.get("total", len(device_ids)) or 0),
                "completed": int(counts.get("completed", 0) or 0),
                "failed": int(counts.get("failed", 0) or 0),
                "deviceIds": device_ids,
                "failedDeviceIds": failed_ids,
                "partialFailure": bool(failed_ids) and int(counts.get("completed", 0) or 0) > 0,
            },
            topic="matrix.campaign",
            entity_id=campaign_id,
        )
        if self.matrix_attachment_listener is not None:
            try:
                self.matrix_attachment_listener(session_id, run_id, campaign_id, dict(result))
            except Exception:
                pass

    def _complete_run(self, session_id: str, run_id: str, result: Mapping[str, Any], checkpoint: Json) -> Json:
        final = result.get("final") or result.get("message") or {"text": "Completed"}
        safe_final = redact_sensitive(final)
        message_id = str(result.get("messageId") or "").strip() or None
        with self._lock:
            control = self._control(run_id)
            if control.cancel.is_set():
                return self._finish_control_request(session_id, run_id, control)
            message = self._append_assistant_message(session_id, safe_final, message_id=message_id)
            event_data = {"message": message} if message is not None else {"text": _final_text(safe_final)}
            self._emit(session_id, run_id, "message.completed", event_data)
            run = self.repository.update_run(
                run_id,
                {"status": "completed", "completedAt": _utc_now(), "checkpoint": _dump_checkpoint(checkpoint)},
                session_id=session_id,
            )
        self._emit(session_id, run_id, "run.completed", {"campaignIds": run.get("campaignIds", [])})
        return run

    def _append_assistant_message(self, session_id: str, final: Any, *, message_id: str | None = None) -> Json | None:
        if not hasattr(self.repository, "append_message"):
            return None
        blocks = final.get("blocks") if isinstance(final, Mapping) else None
        if not isinstance(blocks, list):
            text = final.get("text") if isinstance(final, Mapping) else str(final)
            blocks = [{"type": "text", "data": {"text": str(text or "")[:4000]}}]
        now = _utc_now()
        message = {
            "schema": "loom.agent.message.v1",
            "messageId": message_id or f"message_{uuid.uuid4().hex}",
            "sessionId": session_id,
            "role": "assistant",
            "status": "completed",
            "blocks": redact_sensitive(blocks),
            "createdAt": now,
            "completedAt": now,
        }
        return self.repository.append_message(session_id, message)

    def _runtime_event(self, session_id: str, run_id: str, event: Any) -> None:
        if not isinstance(event, Mapping):
            return
        event_type = str(event.get("type") or "").strip()
        if event_type not in RUNTIME_PROGRESS_EVENT_TYPES:
            return
        raw_data = event.get("data", {})
        data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
        data.pop("sessionId", None)
        data.pop("runId", None)
        if event_type == "message.delta":
            delta = str(data.get("delta", data.get("text", "")) or "")[:16000]
            if not delta:
                return
            expected_prefix = f"message_{run_id}"
            message_id = str(data.get("messageId") or "").strip()
            if message_id != expected_prefix and not message_id.startswith(f"{expected_prefix}_round_"):
                message_id = expected_prefix
            data = {
                "messageId": message_id,
                "role": "assistant",
                "delta": delta,
            }
        elif event_type == "plan.updated":
            raw_steps = data.get("steps")
            if not isinstance(raw_steps, list):
                return
            steps = [str(step).strip()[:500] for step in raw_steps if isinstance(step, str) and step.strip()][:32]
            if not steps:
                return
            data = {"steps": steps}
        self._emit(session_id, run_id, event_type, data)

    def _build_request(self, session_id: str, run: Json, request: Mapping[str, Any] | None, checkpoint: Json) -> Json:
        if request is not None:
            built = dict(request)
        elif self.request_builder is not None:
            built = dict(self.request_builder(session_id, run))
        else:
            built = {}
        built.setdefault("sessionId", session_id)
        built.setdefault("runId", run["runId"])
        built.setdefault("runtimeProfileId", built.get("runtimeProfileId") or "default")
        routed, routing = route_capabilities(
            built,
            self.capabilities.list_capabilities(available_only=True),
            checkpoint,
        )
        built["capabilities"] = routed
        built["capabilityRouting"] = routing
        built["toolResults"] = list(checkpoint.get("toolResults", []))
        return built

    def _fail_run(
        self,
        session_id: str,
        run_id: str,
        code: str,
        message: str,
        recoverable: bool,
        checkpoint: Json,
        *,
        error_flags: Mapping[str, bool] | None = None,
    ) -> Json:
        error = {"code": str(code), "message": str(redact_sensitive(message))[:500], "recoverable": bool(recoverable)}
        error.update(dict(error_flags or {}))
        with self._lock:
            control = self._control(run_id)
            if control.cancel.is_set():
                return self._finish_control_request(session_id, run_id, control)
            run = self.repository.update_run(
                run_id,
                {"status": "failed", "completedAt": _utc_now(), "checkpoint": _dump_checkpoint(checkpoint), "error": error},
                session_id=session_id,
            )
        self._emit(session_id, run_id, "run.failed", {"error": error})
        return run

    def _finish_control_request(self, session_id: str, run_id: str, control: _RunControl) -> Json:
        if control.action == "pause":
            return self.repository.get_run(run_id, session_id=session_id)
        return self.cancel_run(run_id, session_id=session_id)

    def _emit(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        data: Mapping[str, Any],
        *,
        topic: str = "agent.run",
        entity_id: str | None = None,
    ) -> Json:
        event_data = dict(data)
        event_data.setdefault("sessionId", session_id)
        event_data.setdefault("runId", run_id)
        return self.event_bus.publish(
            session_id,
            event_type,
            topic=topic,
            entity_id=entity_id or run_id,
            data=redact_sensitive(event_data),
        )

    def _control(self, run_id: str, *, reset: bool = False) -> _RunControl:
        with self._lock:
            if reset or run_id not in self._controls:
                self._controls[run_id] = _RunControl()
            return self._controls[run_id]


def _empty_checkpoint() -> Json:
    return {
        "version": 1,
        "round": 0,
        "completedToolCallIds": [],
        "toolResults": [],
        "inFlightToolCall": None,
        "consecutiveDeduplicatedToolCalls": 0,
    }


def _tool_fingerprint(capability_name: str, tool_input: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"capability": capability_name, "input": dict(tool_input)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _previous_completed_tool_result(checkpoint: Mapping[str, Any], fingerprint: str) -> Json | None:
    tool_results = checkpoint.get("toolResults")
    if not isinstance(tool_results, list):
        return None
    for item in reversed(tool_results):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("status") or "") != "completed":
            return None
        return dict(item) if str(item.get("fingerprint") or "") == fingerprint else None
    return None


def _tool_result_requires_refresh(value: Any, *, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if isinstance(value, Mapping):
        for key in ("status", "state", "phase"):
            status = str(value.get(key) or "").strip().lower().replace("-", "_")
            if status in {
                "queued",
                "pending",
                "running",
                "in_progress",
                "processing",
                "submitted",
                "waiting",
            }:
                return True
        return any(_tool_result_requires_refresh(item, depth=depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_tool_result_requires_refresh(item, depth=depth + 1) for item in value)
    return False


def _close_failed_tool_checkpoint(
    checkpoint: Json,
    tool_call: Any,
    error: Mapping[str, Any],
) -> None:
    call = dict(tool_call) if isinstance(tool_call, Mapping) else {}
    call_id = str(call.get("toolCallId") or call.get("id") or "").strip()
    capability = str(call.get("name") or call.get("capability") or "").strip()
    completed = checkpoint.get("completedToolCallIds")
    if not isinstance(completed, list):
        completed = []
        checkpoint["completedToolCallIds"] = completed
    if call_id and call_id not in completed:
        completed.append(call_id)
    tool_results = checkpoint.get("toolResults")
    if not isinstance(tool_results, list):
        tool_results = []
        checkpoint["toolResults"] = tool_results
    already_closed = any(
        isinstance(item, Mapping)
        and str(item.get("toolCallId") or "") == call_id
        and str(item.get("status") or "") == "failed"
        for item in tool_results
    )
    if call_id and not already_closed:
        tool_results.append(
            {
                "toolCallId": call_id,
                "capability": capability,
                "status": "failed",
                "input": _summary(call.get("input", {})),
                "error": _summary(dict(error)),
            }
        )
    checkpoint["inFlightToolCall"] = None
    checkpoint.pop("pendingApproval", None)


def _capability_error_flags(exc: BaseException) -> Json:
    if not hasattr(exc, "outcome_indeterminate") and not hasattr(exc, "execution_may_continue"):
        return {}
    return {
        "outcomeIndeterminate": bool(getattr(exc, "outcome_indeterminate", False)),
        "executionMayContinue": bool(getattr(exc, "execution_may_continue", False)),
    }


def _capture_request_scope(
    checkpoint: Json,
    run: Mapping[str, Any],
    request: Mapping[str, Any] | None,
) -> None:
    if isinstance(checkpoint.get("requestScope"), Mapping):
        return
    persisted_request = run.get("request")
    source = persisted_request if isinstance(persisted_request, Mapping) else request
    if not isinstance(source, Mapping):
        return
    request_scope = source.get("requestScope")
    if isinstance(request_scope, Mapping):
        checkpoint["requestScope"] = dict(request_scope)
        return
    scope: Json = {}
    targets = source.get("targets", source.get("target"))
    if isinstance(targets, Mapping) and targets:
        scope["targets"] = dict(targets)
    campaign_ids = _string_list(source.get("campaignIds"))
    if campaign_ids:
        scope["campaignIds"] = campaign_ids
    if scope:
        checkpoint["requestScope"] = scope


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if isinstance(item, str) and item.strip()))


def _declared_scope_value(
    tool_input: Mapping[str, Any],
    *,
    direct_keys: tuple[str, ...],
    cli_options: tuple[str, ...],
) -> str:
    for key in direct_keys:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    args = tool_input.get("args")
    if not isinstance(args, list):
        return ""
    for index, item in enumerate(args):
        if not isinstance(item, str):
            continue
        for option in cli_options:
            if item == option and index + 1 < len(args) and isinstance(args[index + 1], str):
                return args[index + 1].strip()
            if item.startswith(f"{option}="):
                return item.split("=", 1)[1].strip()
    return ""


def _bind_single_device_input(tool_input: Json, capability: Any, device_id: str) -> Json:
    if getattr(capability, "source", "") == "cli":
        args = _strip_cli_options(
            tool_input.get("args"),
            value_options=("--device-id", "--device", "--target", "--group"),
        )
        return {**tool_input, "args": [*args, "--device-id", device_id]}
    bound = dict(tool_input)
    for key in ("device", "deviceId", "deviceIds", "group", "groups", "target", "targets", "allOnline"):
        bound.pop(key, None)
    bound["deviceId"] = device_id
    return bound


def _bind_matrix_target_input(tool_input: Json, capability: Any, targets: Mapping[str, Any]) -> Json:
    device_ids = _string_list(targets.get("deviceIds"))
    groups = _string_list(targets.get("groups"))
    all_online = targets.get("allOnline") is True
    if sum(bool(value) for value in (device_ids, groups, all_online)) != 1:
        raise PolicyViolationError(
            "matrix_target_scope_required",
            "Matrix target scope must resolve to devices, groups, or an explicit all-online selection.",
        )
    bound_targets: Json = {}
    if device_ids:
        bound_targets["deviceIds"] = device_ids
    elif groups:
        bound_targets["groups"] = groups
    else:
        bound_targets["allOnline"] = True

    if getattr(capability, "source", "") == "cli":
        args = _strip_cli_options(
            tool_input.get("args"),
            value_options=("--device-id", "--device", "--target", "--group"),
        )
        if device_ids:
            args.extend(["--device", ",".join(device_ids)])
        elif groups:
            args.extend(["--group", ",".join(groups)])
        else:
            args.extend(["--target", "all"])
        return {**tool_input, "args": args}

    bound = dict(tool_input)
    for key in ("device", "deviceId", "deviceIds", "group", "groups", "target", "targets", "allOnline"):
        bound.pop(key, None)
    bound["targets"] = bound_targets
    return bound


def _bind_campaign_input(tool_input: Json, capability: Any, campaign_id: str) -> Json:
    if getattr(capability, "source", "") == "cli":
        args = _strip_cli_options(
            tool_input.get("args"),
            value_options=("--campaign", "--campaign-id"),
            flag_options=("--all",),
        )
        return {**tool_input, "args": [*args, "--campaign", campaign_id]}
    bound = dict(tool_input)
    bound.pop("id", None)
    bound["campaignId"] = campaign_id
    return bound


def _strip_cli_options(
    raw_args: Any,
    *,
    value_options: tuple[str, ...],
    flag_options: tuple[str, ...] = (),
) -> list[str]:
    args = [item for item in raw_args if isinstance(item, str)] if isinstance(raw_args, list) else []
    stripped: list[str] = []
    index = 0
    while index < len(args):
        item = args[index]
        if item in flag_options or any(item.startswith(f"{option}=") for option in flag_options):
            index += 1
            continue
        if item in value_options:
            index += 2
            continue
        if any(item.startswith(f"{option}=") for option in value_options):
            index += 1
            continue
        stripped.append(item)
        index += 1
    return stripped


def _final_text(final: Any) -> str:
    if isinstance(final, Mapping):
        return str(final.get("text") or "")[:4000]
    return str(final or "")[:4000]


def _load_checkpoint(raw: Any) -> Json:
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
    elif isinstance(raw, Mapping):
        parsed = dict(raw)
    else:
        parsed = {}
    checkpoint = _empty_checkpoint()
    if isinstance(parsed, Mapping):
        checkpoint.update(parsed)
    if not isinstance(checkpoint.get("completedToolCallIds"), list):
        checkpoint["completedToolCallIds"] = []
    if not isinstance(checkpoint.get("toolResults"), list):
        checkpoint["toolResults"] = []
    return checkpoint


def _dump_checkpoint(checkpoint: Mapping[str, Any]) -> str:
    return json.dumps(redact_sensitive(dict(checkpoint)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_tool_call(value: Any) -> Json:
    if not isinstance(value, Mapping):
        raise ValueError("Tool call must be an object.")
    call_id = str(value.get("toolCallId") or value.get("id") or "").strip()
    name = str(value.get("name") or value.get("capability") or "").strip()
    raw_input = value.get("input", value.get("arguments", {}))
    if (
        not TOOL_CALL_ID_PATTERN.fullmatch(call_id)
        or not CAPABILITY_NAME_PATTERN.fullmatch(name)
        or not isinstance(raw_input, Mapping)
    ):
        raise ValueError("Tool call requires toolCallId, name, and object input.")
    return {"toolCallId": call_id, "name": name, "input": dict(raw_input)}


def _normalize_tool_call_batch(values: list[Any], request: Mapping[str, Any]) -> list[Json]:
    if len(values) > MAX_TOOL_CALLS_PER_ROUND:
        raise ValueError(f"Runtime returned more than {MAX_TOOL_CALLS_PER_ROUND} tool calls in one round.")

    normalized: list[Json] = []
    seen_call_ids: set[str] = set()
    for value in values:
        call = _restore_explicit_publish_title(_normalize_tool_call(value), request)
        call_id = call["toolCallId"]
        if call_id in seen_call_ids:
            raise ValueError("Runtime returned duplicate toolCallId values in one round.")
        seen_call_ids.add(call_id)
        normalized.append(call)
    return normalized


_EXPLICIT_PUBLISH_TITLE_PATTERN = re.compile(
    r"(?:^|[\n\r。；;])\s*(?:标题|title)\s*[:：]\s*[\"“]?([^\"”\n\r。；;]+)",
    re.IGNORECASE,
)


def _restore_explicit_publish_title(call: Json, request: Mapping[str, Any]) -> Json:
    if call.get("name") != "loom.phone.publish":
        return call
    raw_input = call.get("input")
    if not isinstance(raw_input, Mapping):
        return call
    if str(raw_input.get("title") or "").strip():
        return call

    candidates = (request.get("prompt"), raw_input.get("notes"))
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        matched = _EXPLICIT_PUBLISH_TITLE_PATTERN.search(candidate)
        if not matched:
            continue
        title = matched.group(1).strip().strip('"“”')
        if not title:
            continue
        restored_input = dict(raw_input)
        restored_input["title"] = title
        return {**call, "input": restored_input}

    body = raw_input.get("body")
    if isinstance(body, str):
        first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
        title = re.sub(r"^[#>*\-\s]+", "", first_line).strip().strip('"')[:80]
        if title:
            restored_input = dict(raw_input)
            restored_input["title"] = title
            return {**call, "input": restored_input}
    return call


_SUMMARY_PRIORITY_KEYS = {
    name: index
    for index, name in enumerate((
        "ok",
        "success",
        "status",
        "code",
        "message",
        "summary",
        "currentPackage",
        "jobId",
        "id",
        "mode",
        "error",
        "failure",
        "result",
        "job",
    ))
}


def _summary(value: Any, *, depth: int = 0) -> Any:
    budget = {"chars": 12000, "nodes": 240}
    return _summary_value(redact_sensitive(value), depth=depth, budget=budget)


def _summary_value(value: Any, *, depth: int, budget: dict[str, int]) -> Any:
    if depth >= 5 or budget["chars"] <= 0 or budget["nodes"] <= 0:
        return "[nested content omitted]"
    budget["nodes"] -= 1
    if isinstance(value, Mapping):
        indexed = list(enumerate(value.items()))
        indexed.sort(key=lambda entry: (_SUMMARY_PRIORITY_KEYS.get(str(entry[1][0]), 999), entry[0]))
        summarized: Json = {}
        for _index, (key, item) in indexed[:30]:
            if budget["chars"] <= 0 or budget["nodes"] <= 0:
                break
            safe_key = str(key)[:80]
            budget["chars"] -= min(len(safe_key), budget["chars"])
            summarized[safe_key] = _summary_value(item, depth=depth + 1, budget=budget)
        return summarized
    if isinstance(value, list):
        summarized_list = []
        for item in value[:30]:
            if budget["chars"] <= 0 or budget["nodes"] <= 0:
                break
            summarized_list.append(_summary_value(item, depth=depth + 1, budget=budget))
        return summarized_list
    if isinstance(value, str):
        limit = min(500, max(0, budget["chars"]))
        clipped = value[:limit]
        budget["chars"] -= len(clipped)
        return clipped
    rendered = str(value)
    budget["chars"] -= min(len(rendered), max(0, budget["chars"]))
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
