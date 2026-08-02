from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

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
            assert expired.get_trace("run-paused")["trace"][0]["ownerAccountId"] == "account-a"
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
