from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_wire import register_wire_routes
from core.paths import AppPaths
from core.wire_config import WireService


def session_snapshot(model: str = "qwen3.7-plus") -> dict:
    return {
        "source": "newapi_account",
        "memberId": "newapi:test-user",
        "memberName": "test@example.invalid",
        "gatewayBaseUrl": "https://api.heang.top/v1",
        "gatewayDefaultModel": model,
        "gatewayImageModel": "gpt-image-1",
        "gatewayModels": [model, "gpt-image-1"],
        "memberToken": "sk-test-token-not-real",
        "gateway": {
            "classifiedModels": {
                "text": [model],
                "image": ["gpt-image-1"],
                "video": [],
            },
        },
        "phoneAgent": {
            "apiKey": "sk-test-token-not-real",
            "model": "agnes-2.0-flash",
        },
    }


class WireRouteTests(unittest.TestCase):
    def test_wire_current_is_safe_before_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(_app(temp_dir, session=None))

            response = client.get("/api/wire/current")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["wire"]["ok"])
            self.assertNotIn("apiKey", repr(payload))

    def test_wire_sync_verify_and_rollback_use_bridge_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = _app(temp_dir, session_snapshot("qwen3.7-plus"))
            client = TestClient(app)

            synced = client.post("/api/wire/sync").json()

            self.assertEqual(synced["wire"]["managedBy"], "heang_account")
            self.assertEqual(synced["wire"]["models"]["text"], "qwen3.7-plus")
            self.assertNotIn("sk-test-token-not-real", repr(synced))

            verified = client.post("/api/wire/verify").json()
            self.assertFalse(verified["ok"])
            self.assertFalse(verified["targets"]["codex"]["ok"])

            app.state.session = session_snapshot("gpt-4o")
            client.post("/api/wire/sync")
            rolled_back = client.post("/api/wire/rollback").json()

            self.assertEqual(rolled_back["wire"]["models"]["text"], "qwen3.7-plus")

    def test_wire_custom_provider_route_is_bridge_owned_and_redacts_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(_app(temp_dir, session=None))
            secret = "s" + "k-route-secret"

            response = client.post(
                "/api/wire/custom",
                json={
                    "provider": "OpenAI 兼容",
                    "baseUrl": "https://third.example/v1",
                    "apiKey": secret,
                    "textModel": "gpt-4o",
                    "imageModel": "gpt-image-1",
                    "phoneModel": "gpt-4o-mini",
                    "videoModel": "sora-draft",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["wire"]["managedBy"], "custom_provider")
            self.assertEqual(payload["wire"]["models"]["text"], "gpt-4o")
            self.assertNotIn(secret, repr(payload))
            self.assertNotIn("apiKey", repr(payload["wire"]))

    def test_wire_custom_provider_can_save_without_writing_any_runtime_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(_app(temp_dir, session=None))

            response = client.post(
                "/api/wire/custom",
                json={
                    "provider": "OpenAI compatible",
                    "baseUrl": "https://third.example/v1",
                    "apiKey": "sk-" + "route-save-only-not-real",
                    "textModel": "gpt-4o",
                    "targets": [],
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["syncResults"], [])
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "data", ".codex", "config.toml")))


def _app(base_path: str, session: dict | None) -> FastAPI:
    app = FastAPI()
    paths = AppPaths(base_path)
    app.state.session = session

    async def body(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def fastapi_json(data: dict, status_code: int = 200):
        payload = dict(data)
        payload["_meta"] = {"ok": 200 <= status_code < 400 and "error" not in payload, "status": status_code}
        return JSONResponse(status_code=status_code, content=payload)

    manager = SimpleNamespace(current=lambda: app.state.session)
    ctx = SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_newapi_account_mgr=lambda: manager,
        get_wire_svc=lambda: WireService(paths),
    )
    register_wire_routes(app, ctx)
    return app


if __name__ == "__main__":
    unittest.main()
