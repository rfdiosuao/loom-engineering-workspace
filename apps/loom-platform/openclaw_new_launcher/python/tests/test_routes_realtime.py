from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api.routes_realtime import consume_stream_ticket, register_realtime_routes, stream_cors_headers


def _ctx(*, authorized: bool = True):
    from fastapi.responses import JSONResponse

    def auth_error(_request):
        if authorized:
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return SimpleNamespace(
        auth_error=auth_error,
        body=lambda request: request.json(),
        fastapi_json=lambda payload, status=200: JSONResponse(payload, status_code=status),
    )


def test_realtime_ticket_requires_bridge_authentication() -> None:
    app = FastAPI()
    register_realtime_routes(app, _ctx(authorized=False))

    response = TestClient(app).post("/api/realtime/tickets", json={"topic": "agent"})

    assert response.status_code == 401


def test_realtime_ticket_rejects_unknown_topic() -> None:
    app = FastAPI()
    register_realtime_routes(app, _ctx())

    response = TestClient(app).post("/api/realtime/tickets", json={"topic": "other"})

    assert response.status_code == 400


def test_realtime_ticket_requires_a_topic_specific_resource() -> None:
    app = FastAPI()
    register_realtime_routes(app, _ctx())

    client = TestClient(app)
    assert client.post("/api/realtime/tickets", json={"topic": "agent"}).status_code == 400
    assert client.post(
        "/api/realtime/tickets",
        json={"topic": "agent", "resource": "invalid session id"},
    ).status_code == 400
    assert client.post(
        "/api/realtime/tickets",
        json={"topic": "matrix", "resource": "campaign-1"},
    ).status_code == 400


def test_realtime_ticket_is_bound_to_topic_resource_subject_and_single_use() -> None:
    app = FastAPI()
    ctx = _ctx()
    register_realtime_routes(app, ctx)

    response = TestClient(app).post(
        "/api/realtime/tickets",
        json={"topic": "matrix", "resource": "all"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticket"]
    assert payload["expiresAt"].endswith("Z")
    assert payload["streamUrl"] == "/api/matrix/events/stream"
    assert consume_stream_ticket(
        ctx,
        payload["ticket"],
        topic="agent",
        resource="all",
        subject="local-ui:testclient",
    ) is None
    assert consume_stream_ticket(
        ctx,
        payload["ticket"],
        topic="matrix",
        resource="campaign-1",
        subject="local-ui:testclient",
    ) is None
    grant = consume_stream_ticket(
        ctx,
        payload["ticket"],
        topic="matrix",
        resource="all",
        subject="local-ui:testclient",
    )
    assert grant is not None
    assert grant["topic"] == "matrix"
    assert grant["resource"] == "all"
    assert grant["subject"] == "local-ui:testclient"
    assert consume_stream_ticket(
        ctx,
        payload["ticket"],
        topic="matrix",
        resource="all",
        subject="local-ui:testclient",
    ) is None


def test_stream_cors_allows_only_exact_local_origins() -> None:
    app = FastAPI()

    @app.get("/cors")
    async def cors(request: Request):
        return stream_cors_headers(request)

    client = TestClient(app)
    for origin in (
        "http://tauri.localhost",
        "tauri://localhost",
        "http://localhost:1420",
        "http://127.0.0.1:5173",
        "http://[::1]:3000",
    ):
        response = client.get("/cors", headers={"Origin": origin})
        assert response.json()["Access-Control-Allow-Origin"] == origin
        assert response.json()["Vary"] == "Origin"

    for origin in (
        "https://example.com",
        "http://localhost.example.com",
        "http://localhost:99999",
        "http://user@localhost:5173",
        "http://localhost:5173/path",
    ):
        assert client.get("/cors", headers={"Origin": origin}).json() == {}
