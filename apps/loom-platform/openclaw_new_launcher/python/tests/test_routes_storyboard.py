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

from api.routes_storyboard import register_storyboard_routes
from core.paths import AppPaths


def _fake_model_client(text: str) -> SimpleNamespace:
    def complete(request, emit, cancel, *, timeout_sec=None):
        return {"text": text, "toolCalls": [], "usage": {}, "model": "test"}
    return SimpleNamespace(complete=complete)


def _app(base_path: str, *, model_text: str = "ok", protected: bool = False) -> FastAPI:
    app = FastAPI()
    paths = AppPaths(base_path)

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

    svc = SimpleNamespace(
        get_param_config=lambda: {"模块一": {"产品/服务类型": {"实物商品": "hint"}}},
        import_param_config=lambda payload: {"ok": True, "optionCount": 1, "warnings": {"missing": []}, "backfilled": {}},
        generate=lambda stage, project, mc: {"stage": stage, "result": model_text, "rawText": model_text},
    )

    ctx = SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        protected_error=lambda _path: fastapi_json({"error": "未授权"}, 403) if protected else None,
        get_storyboard_svc=lambda: svc,
        get_agent_service=lambda: SimpleNamespace(model_client=_fake_model_client(model_text)),
        paths=paths,
    )
    register_storyboard_routes(app, ctx)
    return app


class StoryboardRouteTests(unittest.TestCase):
    def test_get_param_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp))
            resp = client.get("/api/storyboard/param-config")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("模块一", data["config"])

    def test_import_param_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp))
            resp = client.post("/api/storyboard/import-param-config", json={"config": {"模块一": {}}})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["ok"])

    def test_generate_requires_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp, protected=True))
            resp = client.post("/api/storyboard/generate", json={"stage": "script", "project": {}})
            self.assertEqual(resp.status_code, 403)

    def test_generate_returns_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp, model_text="你好文案"))
            resp = client.post("/api/storyboard/generate", json={
                "stage": "script",
                "project": {"target": {"object": "咖啡"}},
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["result"], "你好文案")
            self.assertEqual(data["stage"], "script")


if __name__ == "__main__":
    unittest.main()
