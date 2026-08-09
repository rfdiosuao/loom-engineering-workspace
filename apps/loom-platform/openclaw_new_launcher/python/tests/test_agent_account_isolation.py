from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from core.agent_capabilities import CapabilityRegistry
from core.agent_sessions import AgentSessionRepository
from core.newapi_account_manager import NewApiAccountManager
from core.paths import AppPaths
from services.agent_service import AgentService


class _Runtime:
    def __init__(self) -> None:
        self.calls = 0

    def status(self, _profile_id=None):
        return {"available": True}

    def start(self, _request, _emit, _cancel, *, timeout_sec=None):
        self.calls += 1
        return {"final": {"text": "done"}}


class _Entitlement:
    def __init__(self, account_id: str, *, authorized: bool) -> None:
        self.account_id = account_id
        self.authorized = authorized

    def current_state(self, _feature=None):
        return {
            "authorized": self.authorized,
            "accountId": self.account_id,
            "lease": {"accountId": self.account_id},
            "code": "ok" if self.authorized else "entitlement_expired",
        }


class _Account:
    def __init__(self, account_id: str, *, authorized: bool = True) -> None:
        self.account_id = account_id
        self.account_entitlement = _Entitlement(account_id, authorized=authorized)

    def public_session(self):
        return {
            "loggedIn": True,
            "memberId": f"newapi:{self.account_id}",
            "accountEntitlement": {
                "accountId": self.account_id,
                "authorized": self.account_entitlement.authorized,
            },
            "models": {"text": []},
            "selectedModels": {"text": ""},
        }


class _GuestAccount:
    def __init__(self) -> None:
        self.account_entitlement = _Entitlement("", authorized=False)
        self.available = True

    def public_session(self):
        if not self.available:
            raise RuntimeError("account session unavailable")
        return {
            "loggedIn": False,
            "accountEntitlement": {
                "accountId": "",
                "authorized": False,
            },
            "models": {"text": []},
            "selectedModels": {"text": ""},
        }


class _BrokenProductionAccount(NewApiAccountManager):
    def __init__(self) -> None:
        self.account_entitlement = _Entitlement("account-a", authorized=True)

    def public_session(self):
        raise RuntimeError("account session unavailable")


def _registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        internal_operations={},
        skill_provider=lambda: [],
        mcp_provider=lambda: [],
        cli_catalog_provider=lambda: {"domains": []},
    )


def _service(root: str, account_id: str, *, authorized: bool = True, runtime=None):
    return AgentService(
        AppPaths(root),
        runtime=runtime or _Runtime(),
        account_manager=_Account(account_id, authorized=authorized),
        capabilities=_registry(),
    )


def _canonical_contract_errors(payload: dict) -> list[str]:
    schema_files = {
        "loom.agent.approval.v1": "agent-approval.v1.schema.json",
        "loom.agent.session.v1": "agent-session.v1.schema.json",
        "loom.agent.message.v1": "agent-message.v1.schema.json",
        "loom.agent.run.v1": "agent-run.v1.schema.json",
        "loom.agent.run.v2": "agent-run.v2.schema.json",
    }
    schema_id = str(payload.get("schema") or "")
    schema_name = schema_files.get(schema_id)
    if schema_name is None:
        return [f"unsupported public schema: {schema_id or '<missing>'}"]
    contract_root = Path(PYTHON_DIR).parents[3] / "packages" / "contracts"
    schema = json.loads(
        (contract_root / "schemas" / schema_name).read_text(encoding="utf-8")
    )
    return [
        f"{schema_id} at /{'/'.join(str(part) for part in error.path)}: {error.message}"
        for error in Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    ]


def _public_contract_violations(label: str, payload: dict) -> list[str]:
    violations = []
    for private_key in ("ownerAccountId", "request"):
        if private_key in payload:
            violations.append(f"{label}: leaked private field {private_key}")
    if payload.get("checkpoint") == "":
        violations.append(f"{label}: leaked empty checkpoint")
    violations.extend(
        f"{label}: {error}" for error in _canonical_contract_errors(payload)
    )
    return violations


def _private_contract_paths(value, path: tuple[str, ...] = ()) -> list[str]:
    paths = []
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = (*path, str(key))
            if key in {"ownerAccountId", "request"}:
                paths.append("/" + "/".join(next_path))
            paths.extend(_private_contract_paths(nested, next_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_private_contract_paths(nested, (*path, str(index))))
    return paths


def test_agent_service_public_round_trip_projects_v1_and_keeps_private_persistence() -> None:
    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-contract")
        try:
            session = service.create_session({"title": "Public contract round trip"})
            sent = service.send_message(
                session["sessionId"],
                {
                    "clientMessageId": "public-contract-v1",
                    "text": "Inspect public contract boundaries",
                },
            )
            idempotent = service.send_message(
                session["sessionId"],
                {
                    "clientMessageId": "public-contract-v1",
                    "text": "Inspect public contract boundaries",
                },
            )
            fetched = service.get_run(sent["run"]["runId"])
            trace_outcome = service.get_trace(sent["run"]["runId"])
            persisted_session = service.repository.get_session(session["sessionId"])
            persisted_run = service.repository.get_run(sent["run"]["runId"])
        finally:
            service.shutdown()

    assert persisted_session["ownerAccountId"] == "account-contract"
    assert persisted_run["ownerAccountId"] == "account-contract"
    assert persisted_run["request"]["prompt"] == "Inspect public contract boundaries"
    assert trace_outcome["trace"]
    assert trace_outcome["nodes"]
    assert _private_contract_paths(trace_outcome["trace"]) == []
    assert _private_contract_paths(trace_outcome["nodes"]) == []
    assert _private_contract_paths(trace_outcome) == []
    violations = []
    for label, payload in (
        ("create_session", session),
        ("send_message.message", sent["message"]),
        ("send_message.run", sent["run"]),
        ("send_message.idempotent.message", idempotent["message"]),
        ("send_message.idempotent.run", idempotent["run"]),
        ("get_run", fetched),
    ):
        violations.extend(_public_contract_violations(label, payload))
    assert violations == []


def test_agent_service_public_reader_accepts_private_v2_persistence_without_leaking_it() -> None:
    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-contract-v2")
        try:
            session = service.create_session({"title": "Persisted v2 reader"})
            persisted = service.repository.create_run(
                {
                    "schema": "loom.agent.run.v2",
                    "runId": "run-persisted-v2",
                    "sessionId": session["sessionId"],
                    "status": "completed",
                    "executionState": {
                        "phase": "terminal",
                        "retryable": False,
                        "degraded": False,
                    },
                    "checkpoint": "",
                    "campaignIds": [],
                    "request": {"prompt": "private persisted v2 request"},
                }
            )
            public = service.get_run("run-persisted-v2")
        finally:
            service.shutdown()

    assert persisted["ownerAccountId"] == "account-contract-v2"
    assert persisted["request"]["prompt"] == "private persisted v2 request"
    assert public["schema"] == "loom.agent.run.v2"
    assert _public_contract_violations("get_run.v2", public) == []


def test_agent_service_trace_run_controls_and_approval_project_public_contracts() -> None:
    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-public-controls")
        try:
            session = service.create_session({"title": "Public control contracts"})
            session_id = session["sessionId"]

            def private_run(run_id: str, status: str) -> dict:
                return service.repository.create_run(
                    {
                        "schema": "loom.agent.run.v1",
                        "runId": run_id,
                        "sessionId": session_id,
                        "status": status,
                        "executionState": {
                            "phase": "terminal" if status == "completed" else "planning",
                            "retryable": False,
                            "degraded": False,
                        },
                        "checkpoint": "",
                        "campaignIds": [],
                        "request": {"prompt": f"private request for {run_id}"},
                        "controlState": "private-control-state",
                    }
                )

            trace_run = private_run("run-public-trace", "waiting_approval")
            approval = service.repository.create_approval(
                {
                    "schema": "loom.agent.approval.v1",
                    "approvalId": "approval-public-trace",
                    "sessionId": session_id,
                    "runId": trace_run["runId"],
                    "toolCallId": "tool-public-trace",
                    "capability": "loom.test.public-contract",
                    "inputHash": "sha256:" + ("a" * 64),
                    "actionSummary": "Exercise public approval projection",
                    "targets": {
                        "kind": "contract-test",
                        "nested": {
                            "ownerAccountId": "must-not-leak",
                            "request": {"prompt": "must-not-leak"},
                        },
                    },
                    "inputSummary": {
                        "args": [
                            {"ownerAccountId": "must-not-leak"},
                            {"request": {"prompt": "must-not-leak"}},
                            {"safe": True},
                        ]
                    },
                    "risk": "outbound",
                    "riskReason": "Contract boundary test",
                    "status": "pending",
                    "requestedAt": "2026-08-08T10:00:00Z",
                    "expiresAt": "2026-08-08T11:00:00Z",
                }
            )
            for index, event_type in enumerate(
                ("tool.requested", "tool.started", "tool.completed"),
                start=1,
            ):
                service.repository.append_event(
                    session_id,
                    {
                        "schema": "loom.realtime.event.v1",
                        "eventId": f"event-public-trace-{index}",
                        "timestamp": f"2026-08-08T10:00:0{index}Z",
                        "topic": "agent.run",
                        "entityId": trace_run["runId"],
                        "type": event_type,
                        "data": {
                            "runId": trace_run["runId"],
                            "toolCallId": "tool-public-trace",
                            "message": {
                                "ownerAccountId": "must-not-leak",
                                "request": {"prompt": "must-not-leak"},
                            },
                        },
                    },
                )
            trace = service.get_trace(trace_run["runId"])

            pause_run = private_run("run-public-pause", "running")
            paused = service.pause_run(pause_run["runId"])
            resume_run = private_run("run-public-resume", "completed")
            resumed = service.resume_run(resume_run["runId"])
            cancel_run = private_run("run-public-cancel", "running")
            cancelled = service.cancel_run(cancel_run["runId"])
            resolved = service.resolve_approval(
                approval["approvalId"],
                {"decision": "rejected", "operator": "contract-test"},
            )

            persisted_trace_run = service.repository.get_run(trace_run["runId"])
            persisted_approval = service.repository.get_approval(approval["approvalId"])
        finally:
            service.shutdown()

    assert persisted_trace_run["ownerAccountId"] == "account-public-controls"
    assert persisted_trace_run["request"]["prompt"] == "private request for run-public-trace"
    assert persisted_approval["ownerAccountId"] == "account-public-controls"
    assert trace["trace"]
    assert trace["nodes"]
    assert trace["approvals"]
    assert trace["trace"] == trace["nodes"]
    aggregated = next(node for node in trace["trace"] if node["kind"] == "tool")
    assert aggregated["eventCount"] == 3
    assert _private_contract_paths(trace) == []
    violations = []
    for label, payload in (
        ("get_trace.run", trace["run"]),
        ("get_trace.approval", trace["approvals"][0]),
        ("pause_run", paused),
        ("resume_run", resumed),
        ("cancel_run", cancelled),
        ("resolve_approval.run", resolved["run"]),
        ("resolve_approval.approval", resolved["approval"]),
    ):
        violations.extend(_public_contract_violations(label, payload))
    assert violations == []


def test_repository_persists_owner_on_session_history_run_trace_and_approval() -> None:
    with tempfile.TemporaryDirectory() as root:
        repository = AgentSessionRepository(root, owner_account_id="account-a")
        session = repository.create_session("Owned", session_id="session-owned")
        message = repository.append_message(
            session["sessionId"],
            {
                "messageId": "message-owned",
                "sessionId": session["sessionId"],
                "role": "user",
                "blocks": [],
            },
        )
        run = repository.create_run(
            {
                "runId": "run-owned",
                "sessionId": session["sessionId"],
                "status": "queued",
            }
        )
        approval = repository.create_approval(
            {
                "approvalId": "approval-owned",
                "runId": run["runId"],
                "sessionId": session["sessionId"],
                "status": "pending",
            }
        )
        event = repository.append_event(
            session["sessionId"],
            {
                "eventId": "event-owned",
                "sessionId": session["sessionId"],
                "type": "run.queued",
                "data": {"runId": run["runId"]},
            },
        )

        for record in (session, message, run, approval, event):
            assert record["ownerAccountId"] == "account-a"


def test_account_b_cannot_list_read_or_resume_account_a_repository_data() -> None:
    with tempfile.TemporaryDirectory() as root:
        owner_a = AgentSessionRepository(root, owner_account_id="account-a")
        owner_a.create_session("A", session_id="session-a")
        owner_a.create_run(
            {"runId": "run-a", "sessionId": "session-a", "status": "paused"}
        )
        owner_a.create_approval(
            {
                "approvalId": "approval-a",
                "runId": "run-a",
                "sessionId": "session-a",
                "status": "pending",
            }
        )
        owner_b = AgentSessionRepository(root, owner_account_id="account-b")

        assert owner_b.list_sessions()["sessions"] == []
        for reader, identifier in (
            (owner_b.get_session, "session-a"),
            (owner_b.get_run, "run-a"),
            (owner_b.get_approval, "approval-a"),
        ):
            with pytest.raises(KeyError):
                reader(identifier)
        assert owner_b.recover_unfinished_runs() == []


def test_account_b_cannot_update_archive_or_delete_account_a_session() -> None:
    with tempfile.TemporaryDirectory() as root:
        owner_a = AgentSessionRepository(root, owner_account_id="account-a")
        owner_a.create_session("A", session_id="session-a")
        owner_b = AgentSessionRepository(root, owner_account_id="account-b")

        for mutation in (
            lambda: owner_b.update_session("session-a", {"title": "Hijacked"}),
            lambda: owner_b.archive_session("session-a"),
            lambda: owner_b.delete_session("session-a"),
        ):
            with pytest.raises(KeyError):
                mutation()

        assert owner_a.get_session("session-a")["title"] == "A"
        assert owner_a.get_session("session-a")["status"] == "active"


def test_legacy_unowned_data_is_quarantined_from_scoped_accounts_by_default() -> None:
    with tempfile.TemporaryDirectory() as root:
        legacy = AgentSessionRepository(root)
        legacy.create_session("Legacy", session_id="session-legacy")

        scoped = AgentSessionRepository(root, owner_account_id="account-a")

        assert scoped.list_sessions()["sessions"] == []
        with pytest.raises(KeyError):
            scoped.get_session("session-legacy")


def test_inactive_entitlement_bootstrap_exposes_a_read_only_execution_gate() -> None:
    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-a", authorized=False)
        try:
            bootstrap = service.bootstrap()
        finally:
            service.shutdown()

    assert bootstrap["executionAccess"] == {
        "authorized": False,
        "code": "AGENT_ENTITLEMENT_REQUIRED",
        "message": "商业矩阵授权尚未激活。请先在“模型账号”绑定授权码，再返回这里继续。",
        "action": "open_account_entitlement",
    }
    assert bootstrap["permissions"] == {
        "read": True,
        "control": False,
        "outbound": False,
        "critical": False,
    }


def test_logged_out_guest_bootstrap_is_read_only_not_an_account_switch() -> None:
    with tempfile.TemporaryDirectory() as root:
        service = AgentService(
            AppPaths(root),
            runtime=_Runtime(),
            account_manager=_GuestAccount(),
            capabilities=_registry(),
        )
        try:
            bootstrap = service.bootstrap()
            assert service.list_sessions()["sessions"] == []
            with pytest.raises(PermissionError, match="AGENT_ENTITLEMENT_REQUIRED"):
                service.create_session({"title": "Blocked guest session"})
        finally:
            service.shutdown()

    assert bootstrap["executionAccess"]["authorized"] is False
    assert bootstrap["executionAccess"]["code"] == "AGENT_ENTITLEMENT_REQUIRED"
    assert bootstrap["permissions"] == {
        "read": True,
        "control": False,
        "outbound": False,
        "critical": False,
    }


def test_logged_out_guest_still_fails_closed_if_account_session_becomes_unavailable() -> None:
    with tempfile.TemporaryDirectory() as root:
        account = _GuestAccount()
        service = AgentService(
            AppPaths(root),
            runtime=_Runtime(),
            account_manager=account,
            capabilities=_registry(),
        )
        try:
            account.available = False
            with pytest.raises(KeyError, match="agent account scope"):
                service.bootstrap()
        finally:
            service.shutdown()


def test_expired_account_can_read_own_history_but_cannot_execute_or_resume() -> None:
    with tempfile.TemporaryDirectory() as root:
        active = _service(root, "account-a")
        session = active.create_session({"title": "History"})
        active.repository.create_run(
            {
                "runId": "run-paused",
                "sessionId": session["sessionId"],
                "status": "paused",
            }
        )
        active.repository.append_event(
            session["sessionId"],
            {
                "eventId": "event-paused",
                "sessionId": session["sessionId"],
                "type": "run.paused",
                "data": {"runId": "run-paused"},
            },
        )
        active.shutdown()

        expired = _service(root, "account-a", authorized=False)
        try:
            assert expired.list_sessions()["sessions"][0]["sessionId"] == session["sessionId"]
            assert expired.session_detail(session["sessionId"])["session"]["title"] == "History"
            assert expired.get_run("run-paused")["status"] == "paused"
            public_trace = expired.get_trace("run-paused")
            assert _private_contract_paths(public_trace) == []
            assert expired.repository.replay_events(session["sessionId"])[0]["ownerAccountId"] == "account-a"
            with pytest.raises(PermissionError, match="AGENT_ENTITLEMENT_REQUIRED"):
                expired.send_message(
                    session["sessionId"],
                    {"clientMessageId": "blocked", "text": "continue"},
                )
            with pytest.raises(PermissionError, match="AGENT_ENTITLEMENT_REQUIRED"):
                expired.resume_run("run-paused")
        finally:
            expired.shutdown()


def test_service_recovery_only_replays_current_account_runs() -> None:
    with tempfile.TemporaryDirectory() as root:
        owner_a = AgentSessionRepository(root, owner_account_id="account-a")
        owner_a.create_session("A", session_id="session-a")
        owner_a.create_run(
            {"runId": "run-a", "sessionId": "session-a", "status": "queued"}
        )
        runtime_b = _Runtime()

        service_b = _service(root, "account-b", runtime=runtime_b)
        try:
            assert service_b.list_sessions()["sessions"] == []
            assert runtime_b.calls == 0
        finally:
            service_b.shutdown()


def test_production_account_lookup_failure_never_falls_back_to_unscoped_data() -> None:
    with tempfile.TemporaryDirectory() as root:
        legacy = AgentSessionRepository(root)
        legacy.create_session("Legacy", session_id="session-legacy")

        service = AgentService(
            AppPaths(root),
            runtime=_Runtime(),
            account_manager=_BrokenProductionAccount(),
            capabilities=_registry(),
        )
        try:
            with pytest.raises(KeyError):
                service.list_sessions()
        finally:
            service.shutdown()
