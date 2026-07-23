from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api.routes_account import _account_response, _friendly_account_error, _redact_secret_text
from api.routes_account import register_account_routes
from core.newapi_account_manager import NewApiAccountError
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


class AccountRouteResponseTests(unittest.TestCase):
    def test_password_login_returns_before_background_runtime_sync(self) -> None:
        app = FastAPI()
        sync_started = threading.Event()
        sync_release = threading.Event()
        calls = []

        class Manager:
            def login(self, username, password, *, base_url="", api_token="", sync_runtime=True):
                calls.append((username, password, base_url, api_token, sync_runtime))
                return {"source": "newapi_account", "memberName": username}

            def public_session(self):
                return {"loggedIn": True, "account": "user@example.invalid"}

            def sync_targets(self, _session):
                sync_started.set()
                sync_release.wait(2)
                return [{"target": "codex", "ok": True}]

        register_account_routes(app, _ctx(Manager()))
        client = TestClient(app)
        started = time.perf_counter()
        response = client.post(
            "/api/account/login",
            json={"email": "user@example.invalid", "password": "not-real", "baseUrl": "https://api-cn.heang.top"},
        )
        elapsed = time.perf_counter() - started
        try:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["syncPending"])
            self.assertLess(elapsed, 1.0)
            self.assertEqual(calls[0][-1], False)
            self.assertTrue(sync_started.wait(1))
        finally:
            sync_release.set()

    def test_account_capabilities_route_returns_safe_email_mode(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            auth_capabilities=lambda **_kwargs: {
                "passwordLogin": True,
                "inlineEmailCode": False,
                "webRegistrationRequired": True,
                "emailReason": "请在网页完成邮箱注册",
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.get("/api/account/capabilities")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["capabilities"]["inlineEmailCode"])
        self.assertNotIn("token", repr(response.json()).lower())

    def test_account_response_does_not_expose_session_secrets(self) -> None:
        response = _account_response(
            account={
                "loggedIn": True,
                "account": "user@example.com",
                "tokenMasked": "sk-***1234",
            },
            session={
                "memberToken": "sk-secret",
                "newApi": {"sessionCookie": "sid=secret"},
                "lastSyncResults": [
                    {"target": "image", "ok": True, "apiKey": "sk-secret"},
                    {"target": "openclaw", "ok": False, "error": "contains sk-secret"},
                ],
            },
            extra_sync_results=[{"target": "openclaw", "ok": True, "apiKey": "sk-secret"}],
        )

        dumped = repr(response)
        self.assertNotIn("member", response)
        self.assertNotIn("sk-secret", dumped)
        self.assertNotIn("sessionCookie", dumped)
        self.assertEqual(response["account"]["account"], "user@example.com")

    def test_error_text_redacts_secret_markers(self) -> None:
        secret = "s" + "k-" + "demo-secret"
        redacted = _redact_secret_text(f"failed with apiKey={secret}")

        self.assertNotIn(secret, redacted)
        self.assertIn("apiKey=[redacted]", redacted)

    def test_friendly_account_error_keeps_email_whitelist_reason(self) -> None:
        message = _friendly_account_error("The administrator has enabled the email domain name whitelist")

        self.assertIn("邮箱域名", message)
        self.assertNotIn("接口暂不可用", message)

    def test_friendly_account_error_translates_bridge_password_rejection(self) -> None:
        message = _friendly_account_error("invalid username or password", "password_login")

        self.assertIn("密码错误", message)
        self.assertNotIn("invalid username", message.lower())

    def test_login_email_code_occupied_error_is_not_shown_as_registration_failure(self) -> None:
        app = FastAPI()

        def send_email_code(email: str, *, base_url: str = "", purpose: str = "") -> dict:
            raise NewApiAccountError("邮箱地址已被占用")

        manager = SimpleNamespace(send_email_code=send_email_code)
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/email-code/send",
            json={"email": "used@example.invalid", "baseUrl": "https://api.heang.top", "purpose": "login"},
        )

        self.assertEqual(response.status_code, 400)
        message = response.json()["error"]
        self.assertIn("验证码登录", message)
        self.assertIn("密码登录", message)
        self.assertNotIn("邮箱地址已被占用", message)

    def test_account_sync_uses_manager_wire_results_without_legacy_openclaw_bypass(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            refresh_current=lambda: {
                "lastSyncResults": [
                    {"target": "openclaw", "ok": True},
                    {"target": "phone", "ok": True},
                ],
            },
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
            },
        )

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

        def legacy_bypass():
            raise AssertionError("legacy OpenClaw direct sync should not be called")

        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=body,
            fastapi_json=fastapi_json,
            get_newapi_account_mgr=lambda: manager,
            append_log=lambda _text: None,
            sync_openclaw_models_from_api_profiles=legacy_bypass,
        )
        register_account_routes(app, ctx)
        client = TestClient(app)

        response = client.post("/api/account/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["target"] for item in response.json()["syncResults"]],
            ["openclaw", "phone"],
        )

    def test_email_code_send_route_uses_bridge_manager_and_hides_sensitive_fields(self) -> None:
        app = FastAPI()
        calls = []

        def send_email_code(email: str, *, base_url: str = "", purpose: str = "") -> dict:
            calls.append((email, base_url, purpose))
            return {
                "sent": True,
                "email": email,
                "retryAfter": 60,
                "code": "123456",
                "token": "sk-route-secret",
            }

        manager = SimpleNamespace(send_email_code=send_email_code)
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/email-code/send",
            json={"email": "user@example.invalid", "baseUrl": "https://api.heang.top", "purpose": "login"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(calls, [("user@example.invalid", "https://api.heang.top", "login")])
        self.assertTrue(payload["sent"])
        self.assertNotIn("123456", repr(payload))
        self.assertNotIn("sk-route-secret", repr(payload))

    def test_email_code_send_route_rejects_sent_false(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            send_email_code=lambda *_args, **_kwargs: {
                "sent": False,
                "message": "upstream mail delivery failed",
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/email-code/send",
            json={"email": "user@example.invalid", "purpose": "login"},
        )

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["sent"])
        self.assertEqual(payload["error"]["code"], "email_code_not_sent")

    def test_select_models_route_preserves_phone_model(self) -> None:
        app = FastAPI()
        calls = []

        def select_models(**models):
            calls.append(models)
            return {"selectedModels": {"phone": models["phone_model"]}}

        manager = SimpleNamespace(select_models=select_models)
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/models/select",
            json={
                "textModel": "qwen-test",
                "phoneModel": "agnes-2.0-flash",
                "imageModel": "image-test",
                "videoModel": "video-test",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [{
                "text_model": "qwen-test",
                "phone_model": "agnes-2.0-flash",
                "image_model": "image-test",
                "video_model": "video-test",
            }],
        )
        self.assertEqual(
            response.json()["account"]["selectedModels"]["phone"],
            "agnes-2.0-flash",
        )

    def test_email_code_login_route_returns_public_account_and_redacted_sync_results(self) -> None:
        app = FastAPI()
        calls = []

        def login_with_email_code(email: str, code: str, *, base_url: str = "") -> dict:
            calls.append((email, code, base_url))
            return {
                "lastSyncResults": [
                    {"target": "openclaw", "ok": True, "apiKey": "sk-route-secret"},
                    {"target": "phone", "ok": False, "error": "token=sk-route-secret"},
                ],
            }

        manager = SimpleNamespace(
            login_with_email_code=login_with_email_code,
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
                "tokenMasked": "sk-****cret",
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/email-code/login",
            json={"email": "user@example.invalid", "code": "654321", "baseUrl": "https://api.heang.top"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(calls, [("user@example.invalid", "654321", "https://api.heang.top")])
        self.assertEqual(payload["account"]["account"], "user@example.invalid")
        self.assertNotIn("sk-route-secret", repr(payload))
        self.assertNotIn("apiKey", repr(payload["syncResults"]))
        self.assertIn("token=[redacted]", repr(payload))

    def test_register_route_uses_email_code_and_never_returns_password_or_token(self) -> None:
        app = FastAPI()
        calls = []

        def register_with_email_code(email: str, password: str, code: str, *, base_url: str = "") -> dict:
            calls.append((email, password, code, base_url))
            return {
                "memberToken": "sk-route-secret",
                "lastSyncResults": [
                    {"target": "openclaw", "ok": True, "apiKey": "sk-route-secret"},
                ],
            }

        manager = SimpleNamespace(
            register_with_email_code=register_with_email_code,
            public_session=lambda: {
                "loggedIn": True,
                "account": "new-user@example.invalid",
                "tokenMasked": "sk-****cret",
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/register",
            json={
                "email": "new-user@example.invalid",
                "password": "not-written-to-response",
                "code": "246810",
                "baseUrl": "https://api.heang.top",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(calls, [("new-user@example.invalid", "not-written-to-response", "246810", "https://api.heang.top")])
        self.assertEqual(payload["account"]["account"], "new-user@example.invalid")
        self.assertNotIn("not-written-to-response", repr(payload))
        self.assertNotIn("sk-route-secret", repr(payload))

    def test_subscription_route_returns_native_snapshot_and_purchase_url(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            subscription_snapshot=lambda: {
                "mode": "native",
                "balance": 1200,
                "plan": "pro",
                "expiresAt": "2026-12-31T00:00:00Z",
                "usage": {"usedQuota": 12},
                "purchaseUrl": "https://api.heang.top",
            }
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.get("/api/account/subscription")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subscription"]["mode"], "native")
        self.assertEqual(payload["subscription"]["plan"], "pro")
        self.assertIn("purchaseUrl", payload["subscription"])

    def test_current_route_can_show_cached_snapshot_while_offline(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            public_session=lambda: {
                "loggedIn": True,
                "account": "cached@example.invalid",
                "offline": True,
                "stale": True,
                "models": {"text": ["qwen3.7-plus"], "image": [], "video": []},
                "selectedModels": {"text": "qwen3.7-plus", "image": "", "videoDraft": ""},
                "usage": {"quota": 800},
            }
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.get("/api/account/current")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["account"]
        self.assertTrue(payload["loggedIn"])
        self.assertTrue(payload["offline"])
        self.assertEqual(payload["account"], "cached@example.invalid")

    def test_logout_route_clears_public_account_state(self) -> None:
        app = FastAPI()
        manager = SimpleNamespace(
            logout=lambda: True,
            public_session=lambda: {
                "loggedIn": False,
                "models": {"text": [], "image": [], "video": []},
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post("/api/account/logout")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["loggedOut"])
        self.assertFalse(payload["account"]["loggedIn"])


def _ctx(manager):
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

    return SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_newapi_account_mgr=lambda: manager,
        append_log=lambda _text: None,
    )


if __name__ == "__main__":
    unittest.main()
