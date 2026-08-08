from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api.routes_agent import _invoke, register_agent_routes
from api.routes_realtime import register_realtime_routes


class FakeAgentService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.session = {
            "schema": "loom.agent.session.v1",
            "sessionId": "session_1",
            "title": "招聘任务",
            "status": "active",
            "runtimeProfileId": "default",
            "createdAt": "2026-07-16T00:00:00Z",
            "updatedAt": "2026-07-16T00:00:00Z",
        }
        self.archived_session = {
            **self.session,
            "sessionId": "session_archived",
            "title": "Archived conversation",
            "status": "archived",
        }
        self.run = {
            "schema": "loom.agent.run.v1",
            "runId": "run_1",
            "sessionId": "session_1",
            "status": "running",
            "campaignIds": [],
        }

    def bootstrap(self):
        return {"runtime": {"available": True}, "capabilities": [], "permissions": {}}

    def list_sessions(self, **params):
        self.calls.append(("list_sessions", params))
        return {"sessions": [self.session, self.archived_session], "nextCursor": "cursor_2"}

    def create_session(self, body):
        self.calls.append(("create_session", body))
        return self.session

    def update_session(self, session_id, body):
        self.calls.append(("update_session", (session_id, body)))
        return {**self.session, **body}

    def session_detail(self, session_id, **params):
        self.calls.append(("session_detail", (session_id, params)))
        return {"session": self.session, "messages": []}

    def send_message(self, session_id, body):
        self.calls.append(("send_message", (session_id, body)))
        return {"message": {"messageId": "message_1"}, "run": self.run}

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return self.run

    def get_trace(self, run_id):
        self.calls.append(("get_trace", run_id))
        return {"runId": run_id, "nodes": []}

    def pause_run(self, run_id):
        return {**self.run, "status": "paused"}

    def resume_run(self, run_id):
        return {**self.run, "status": "running"}

    def cancel_run(self, run_id):
        return {**self.run, "status": "cancelled"}

    def resolve_approval(self, approval_id, body):
        return {"approval": {"approvalId": approval_id, "status": body["decision"]}, "run": self.run}

    def queue_approval_resolution(self, approval_id, body):
        self.calls.append(("queue_approval_resolution", (approval_id, body)))
        return {"approval": {"approvalId": approval_id, "status": body["decision"]}, "run": self.run}

    def events_after(self, *, session_id, after_seq):
        self.calls.append(("events_after", (session_id, after_seq)))
        return [{
            "schema": "loom.realtime.event.v1",
            "eventId": "evt_2",
            "seq": 2,
            "timestamp": "2026-07-16T00:00:00Z",
            "topic": "agent.run",
            "entityId": "run_1",
            "type": "run.completed",
            "data": {},
        }]

    def shutdown(self):
        self.calls.append(("shutdown", None))
        return {"stopped": True, "drained": True}


def _ctx(service: FakeAgentService, *, authorized: bool = True):
    async def body(request):
        return await request.json()

    def auth_error(_request):
        if authorized:
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return SimpleNamespace(
        auth_error=auth_error,
        body=body,
        fastapi_json=lambda payload, status=200: JSONResponse(payload, status_code=status),
        get_agent_service=lambda: service,
        shutdown_agent_service=service.shutdown,
    )


def _client(service: FakeAgentService | None = None):
    service = service or FakeAgentService()
    app = FastAPI()
    ctx = _ctx(service)
    register_realtime_routes(app, ctx)
    register_agent_routes(app, ctx)
    return TestClient(app), service


def test_agent_routes_require_bridge_authentication() -> None:
    app = FastAPI()
    register_agent_routes(app, _ctx(FakeAgentService(), authorized=False))

    response = TestClient(app).get("/api/agent/bootstrap")

    assert response.status_code == 401


def test_agent_shutdown_uses_the_existing_service_without_lazy_creation() -> None:
    client, service = _client()

    response = client.post("/api/agent/shutdown")

    assert response.status_code == 200
    assert response.json() == {"stopped": True, "drained": True}
    assert service.calls == [("shutdown", None)]


def test_agent_shutdown_preserves_incomplete_drain_flags() -> None:
    service = FakeAgentService()

    def incomplete_shutdown():
        return {
            "stopped": False,
            "drained": False,
            "unfinishedRuns": 1,
            "unfinishedWorkers": 1,
            "outcomeIndeterminate": True,
            "executionMayContinue": True,
            "code": "agent_shutdown_incomplete",
            "message": "仍有执行可能继续",
            "retryable": False,
        }

    service.shutdown = incomplete_shutdown
    client, _service = _client(service)

    response = client.post("/api/agent/shutdown")

    assert response.status_code == 200
    assert response.json()["drained"] is False
    assert response.json()["unfinishedRuns"] == 1
    assert response.json()["unfinishedWorkers"] == 1
    assert response.json()["executionMayContinue"] is True
    assert response.json()["code"] == "agent_shutdown_incomplete"


def test_agent_account_scope_change_is_not_reported_as_a_missing_resource() -> None:
    class StaleAccountService(FakeAgentService):
        def bootstrap(self):
            raise KeyError("agent account scope")

    client, _service = _client(StaleAccountService())

    response = client.get("/api/agent/bootstrap")

    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_ACCOUNT_CONTEXT_CHANGED"
    assert response.json()["error"] == "模型账号已切换，智能体需要重新连接，请刷新后重试。"
    assert "agent resource not found" not in response.text


def test_agent_entitlement_denial_is_actionable_and_never_leaks_internal_protocol_text() -> None:
    class InactiveEntitlementService(FakeAgentService):
        def create_session(self, body):
            raise PermissionError(
                "AGENT_ENTITLEMENT_REQUIRED: account entitlement is inactive"
            )

    client, _service = _client(InactiveEntitlementService())

    response = client.post("/api/agent/sessions", json={"title": "不应创建"})

    assert response.status_code == 403
    assert response.json() == {
        "error": "商业矩阵授权尚未激活。请先在“模型账号”绑定授权码，再返回这里继续。",
        "code": "AGENT_ENTITLEMENT_REQUIRED",
    }
    assert "account entitlement" not in response.text
    assert "is inactive" not in response.text


def test_sync_agent_service_calls_do_not_block_the_event_loop() -> None:
    async def scenario() -> float:
        started = time.monotonic()
        pending = asyncio.create_task(_invoke(lambda: time.sleep(0.15)))
        await asyncio.sleep(0.02)
        elapsed = time.monotonic() - started
        await pending
        return elapsed

    assert asyncio.run(scenario()) < 0.08


def test_agent_session_list_hides_archived_sessions_from_the_ordinary_route() -> None:
    client, _service = _client()

    response = client.get("/api/agent/sessions")

    assert response.status_code == 200
    assert [session["sessionId"] for session in response.json()["sessions"]] == ["session_1"]
    assert response.json()["nextCursor"] == "cursor_2"


def test_agent_session_message_run_and_approval_routes() -> None:
    client, service = _client()

    assert client.get("/api/agent/bootstrap").status_code == 200
    assert client.get("/api/agent/sessions?query=招聘&limit=20").json()["sessions"][0]["sessionId"] == "session_1"
    assert client.post("/api/agent/sessions", json={"title": "招聘任务"}).status_code == 200
    assert client.patch("/api/agent/sessions/session_1", json={"title": "新标题"}).json()["session"]["title"] == "新标题"
    assert client.get("/api/agent/sessions/session_1?limit=50").status_code == 200
    sent = client.post("/api/agent/sessions/session_1/messages", json={
        "clientMessageId": "client_1",
        "text": "筛选今天的简历",
        "attachments": [],
        "targets": {"deviceIds": [], "groups": ["招聘一组"]},
        "capabilityHints": [],
        "runtimeProfileId": "default",
    })
    assert sent.json()["run"]["runId"] == "run_1"
    assert client.get("/api/agent/runs/run_1").json()["run"]["status"] == "running"
    assert client.get("/api/agent/runs/run_1/trace").json()["nodes"] == []
    assert client.post("/api/agent/runs/run_1/pause").json()["run"]["status"] == "paused"
    assert client.post("/api/agent/runs/run_1/resume").json()["run"]["status"] == "running"
    assert client.post("/api/agent/runs/run_1/cancel").json()["run"]["status"] == "cancelled"
    resolved = client.post("/api/agent/approvals/approval_1", json={"decision": "approved"})
    assert resolved.json()["approval"]["status"] == "approved"
    resolved_from_ui = client.post("/api/agent/approvals/approval_2", json={"decision": "approve"})
    assert resolved_from_ui.json()["approval"]["status"] == "approved"
    rejected_from_ui = client.post("/api/agent/approvals/approval_3", json={"decision": "reject"})
    assert rejected_from_ui.json()["approval"]["status"] == "rejected"
    assert any(call[0] == "queue_approval_resolution" for call in service.calls)
    assert any(call[0] == "send_message" for call in service.calls)


def test_real_agent_session_detail_route_returns_only_canonical_public_dtos() -> None:
    from tests.test_agent_account_isolation import (
        _public_contract_violations,
        _service,
    )

    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-route-contract")
        try:
            client, _ = _client(service)
            created_response = client.post(
                "/api/agent/sessions",
                json={"title": "Route public contract"},
            )
            assert created_response.status_code == 200
            session = created_response.json()["session"]
            sent_response = client.post(
                f"/api/agent/sessions/{session['sessionId']}/messages",
                json={
                    "clientMessageId": "route-public-contract",
                    "text": "Exercise the real agent route",
                },
            )
            assert sent_response.status_code == 200
            sent = sent_response.json()
            detail_response = client.get(
                f"/api/agent/sessions/{session['sessionId']}?limit=50"
            )
            assert detail_response.status_code == 200
            detail = detail_response.json()
            persisted_run = service.repository.get_run(sent["run"]["runId"])
        finally:
            service.shutdown()

    assert persisted_run["ownerAccountId"] == "account-route-contract"
    assert persisted_run["request"]["prompt"] == "Exercise the real agent route"
    public_records = [
        ("route.create_session", session),
        ("route.send_message.message", sent["message"]),
        ("route.send_message.run", sent["run"]),
        ("route.session_detail.session", detail["session"]),
        *(
            (f"route.session_detail.messages[{index}]", message)
            for index, message in enumerate(detail["messages"])
        ),
        *(
            (f"route.session_detail.runs[{index}]", run)
            for index, run in enumerate(detail["runs"])
        ),
    ]
    violations = [
        violation
        for label, payload in public_records
        for violation in _public_contract_violations(label, payload)
    ]
    assert violations == []


def test_real_agent_approval_route_projects_queued_outcome() -> None:
    from tests.test_agent_account_isolation import (
        _public_contract_violations,
        _service,
    )

    with tempfile.TemporaryDirectory() as root:
        service = _service(root, "account-route-approval")
        try:
            session = service.create_session({"title": "Route approval projection"})
            run = service.repository.create_run(
                {
                    "schema": "loom.agent.run.v1",
                    "runId": "run-route-approval",
                    "sessionId": session["sessionId"],
                    "status": "waiting_approval",
                    "executionState": {
                        "phase": "planning",
                        "retryable": False,
                        "degraded": False,
                    },
                    "checkpoint": "",
                    "campaignIds": [],
                    "request": {"prompt": "private approval route request"},
                    "controlState": "private-control-state",
                }
            )
            approval = service.repository.create_approval(
                {
                    "schema": "loom.agent.approval.v1",
                    "approvalId": "approval-route-public",
                    "sessionId": session["sessionId"],
                    "runId": run["runId"],
                    "toolCallId": "tool-route-public",
                    "capability": "loom.test.route-public",
                    "inputHash": "sha256:" + ("b" * 64),
                    "actionSummary": "Exercise queued route projection",
                    "targets": {"kind": "contract-test"},
                    "inputSummary": {"safe": True},
                    "risk": "outbound",
                    "riskReason": "Contract boundary test",
                    "status": "pending",
                    "requestedAt": "2026-08-08T10:00:00Z",
                    "expiresAt": "2026-08-08T11:00:00Z",
                }
            )
            client, _ = _client(service)

            response = client.post(
                f"/api/agent/approvals/{approval['approvalId']}",
                json={"decision": "rejected", "operator": "route-contract-test"},
            )
            persisted_run = service.repository.get_run(run["runId"])
            persisted_approval = service.repository.get_approval(approval["approvalId"])
        finally:
            service.shutdown()

    assert response.status_code == 200
    outcome = response.json()
    assert persisted_run["ownerAccountId"] == "account-route-approval"
    assert persisted_run["request"]["prompt"] == "private approval route request"
    assert persisted_approval["ownerAccountId"] == "account-route-approval"
    violations = [
        violation
        for label, payload in (
            ("route.approval", outcome["approval"]),
            ("route.approval.run", outcome["run"]),
        )
        for violation in _public_contract_violations(label, payload)
    ]
    assert violations == []


def test_agent_stream_requires_single_use_ticket_and_replays_after_sequence() -> None:
    client, service = _client()
    ticket = client.post(
        "/api/realtime/tickets",
        json={"topic": "agent", "resource": "session_1"},
    ).json()["ticket"]

    response = client.get(
        "/api/agent/events/stream",
        params={"sessionId": "session_1", "afterSeq": 1, "once": 1},
        headers={"Authorization": f"Bearer {ticket}"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: agent" in response.text
    assert '"eventId":"evt_2"' in response.text
    assert ("events_after", ("session_1", 1)) in service.calls
    assert client.get(
        "/api/agent/events/stream",
        params={"sessionId": "session_1", "once": 1},
        headers={"Authorization": f"Bearer {ticket}"},
    ).status_code == 401


def test_agent_stream_emits_sanitized_terminal_error_when_event_ledger_read_fails() -> None:
    class FailingEventLedgerService(FakeAgentService):
        def events_after(self, *, session_id, after_seq):
            self.calls.append(("events_after", (session_id, after_seq)))
            raise OSError("D:/private/events.jsonl unavailable; token=ledger-secret")

    service = FailingEventLedgerService()
    app = FastAPI()
    ctx = _ctx(service)
    register_realtime_routes(app, ctx)
    register_agent_routes(app, ctx)
    client = TestClient(app)
    ticket = client.post(
        "/api/realtime/tickets",
        json={"topic": "agent", "resource": "session_1"},
    ).json()["ticket"]
    stream_endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/agent/events/stream"
        and "GET" in getattr(route, "methods", set())
    )

    async def scenario() -> str:
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request({
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/agent/events/stream",
            "raw_path": b"/api/agent/events/stream",
            "query_string": b"sessionId=session_1&afterSeq=0",
            "headers": [(b"authorization", f"Bearer {ticket}".encode("ascii"))],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }, receive)
        response = await stream_endpoint(request)
        frame = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
        try:
            await asyncio.wait_for(anext(response.body_iterator), timeout=1)
        except StopAsyncIteration:
            return frame
        raise AssertionError("agent stream continued after its terminal error frame")

    frame = asyncio.run(scenario())
    payload = json.loads(frame.split("data: ", 1)[1])

    assert frame.startswith("event: agent_stream_error\n")
    assert payload == {
        "type": "agent_stream_error",
        "code": "AGENT_STREAM_LEDGER_UNAVAILABLE",
        "phase": "event_replay",
        "retryable": True,
    }
    assert "events.jsonl" not in frame
    assert "ledger-secret" not in frame
    assert service.calls == [("events_after", ("session_1", 0))]


def test_agent_stream_rejects_query_tickets_and_does_not_spend_a_ticket_on_the_wrong_session() -> None:
    client, _service = _client()
    ticket = client.post(
        "/api/realtime/tickets",
        json={"topic": "agent", "resource": "session_1"},
    ).json()["ticket"]

    assert client.get(
        "/api/agent/events/stream",
        params={"ticket": ticket, "sessionId": "session_1", "once": 1},
    ).status_code == 401
    assert client.get(
        "/api/agent/events/stream",
        params={"sessionId": "session_2", "once": 1},
        headers={"Authorization": f"Bearer {ticket}"},
    ).status_code == 401
    assert client.get(
        "/api/agent/events/stream",
        params={"sessionId": "session_1", "once": 1},
        headers={"Authorization": f"Bearer {ticket}"},
    ).status_code == 200


def test_agent_stream_allows_authorization_header_preflight() -> None:
    client, _service = _client()

    response = client.options(
        "/api/agent/events/stream",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 204
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "Authorization" in response.headers["access-control-allow-headers"]
