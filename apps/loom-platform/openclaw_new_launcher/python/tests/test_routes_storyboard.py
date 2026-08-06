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
from core.loom_model_client import ModelGatewayError
from core.paths import AppPaths


def _fake_model_client(text: str) -> SimpleNamespace:
    def complete(request, emit, cancel, *, timeout_sec=None):
        return {"text": text, "toolCalls": [], "usage": {}, "model": "test"}
    return SimpleNamespace(complete=complete)


def _app(
    base_path: str,
    *,
    model_text: str = "ok",
    protected: bool = False,
    authenticated: bool = True,
    model_error: ModelGatewayError | None = None,
) -> FastAPI:
    app = FastAPI()
    paths = AppPaths(base_path)
    logs: list[str] = []

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

    def generate(stage, project, model_client):
        if model_error is not None:
            raise model_error
        return {"stage": stage, "result": model_text, "rawText": model_text}

    svc = SimpleNamespace(
        get_param_config=lambda: {"模块一": {"产品/服务类型": {"实物商品": "hint"}}},
        import_param_config=lambda payload: {"ok": True, "optionCount": 1, "warnings": {"missing": []}, "backfilled": {}},
        generate=generate,
    )

    ctx = SimpleNamespace(
        auth_error=lambda _request: None if authenticated else fastapi_json({"error": "Unauthorized"}, 401),
        body=body,
        fastapi_json=fastapi_json,
        protected_error=lambda _path: fastapi_json({"error": "未授权"}, 403) if protected else None,
        append_log=logs.append,
        get_storyboard_svc=lambda: svc,
        get_agent_service=lambda: SimpleNamespace(model_client=_fake_model_client(model_text)),
        paths=paths,
    )
    register_storyboard_routes(app, ctx)
    app.state.test_logs = logs
    return app


class StoryboardRouteTests(unittest.TestCase):
    def test_generate_requires_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(_app(tmp, authenticated=False))
            resp = client.post("/api/storyboard/generate", json={"stage": "script", "project": {}})
            self.assertEqual(resp.status_code, 401)

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

    def test_generate_returns_actionable_login_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp,
                model_error=ModelGatewayError(
                    "AGENT_ACCOUNT_LOGIN_REQUIRED",
                    "Managed model login is required.",
                ),
            )
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                "/api/storyboard/generate",
                json={"stage": "script", "project": {"target": {"object": "咖啡"}}},
            )

            self.assertEqual(resp.status_code, 401)
            data = resp.json()
            self.assertEqual(data["errorCode"], "AGENT_ACCOUNT_LOGIN_REQUIRED")
            self.assertEqual(data["error"], "请先登录模型账号，再使用全案九步生成内容。")
            self.assertFalse(data["retryable"])
            self.assertIn("打开“模型账号”完成登录", data["remediation"])
            self.assertEqual(data["stage"], "script")
            self.assertEqual(len(app.state.test_logs), 1)
            self.assertIn("code=AGENT_ACCOUNT_LOGIN_REQUIRED", app.state.test_logs[0])
            self.assertNotIn("Traceback", app.state.test_logs[0])


if __name__ == "__main__":
    unittest.main()
