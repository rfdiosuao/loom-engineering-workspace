from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
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
    def test_payment_routes_create_query_and_refresh_entitlement_after_paid(self) -> None:
        app = FastAPI()
        calls: list[object] = []

        class Manager:
            def payment_plans(self):
                calls.append("plans")
                return {
                    "plans": [{"planKey": "monthly", "amountMinor": 9900}],
                    "payment": {"configured": True, "channels": ["alipay"]},
                }

            def create_payment_order(self, plan_key, payment_type, request_id):
                calls.append(("create", plan_key, payment_type, request_id))
                return {"order": {"orderId": "order-1", "status": "pending"}}

            def payment_order_status(self, order_id, reconcile=False):
                calls.append(("status", order_id, reconcile))
                return {"order": {"orderId": order_id, "status": "paid"}}

            def refresh_current(self):
                calls.append("refresh")
                return {"accountEntitlement": {"plan": "monthly"}}

            def public_session(self):
                return {
                    "loggedIn": True,
                    "accountEntitlement": {"plan": "monthly"},
                }

        register_account_routes(app, _ctx(Manager()))
        client = TestClient(app)

        plans = client.get("/api/account/payments/plans")
        created = client.post(
            "/api/account/payments/order",
            json={
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "click-1",
                "accountId": "attacker",
            },
        )
        paid = client.post(
            "/api/account/payments/order/status",
            json={
                "orderId": "order-1",
                "accountId": "attacker",
                "reconcile": True,
            },
        )

        self.assertEqual(200, plans.status_code, plans.text)
        self.assertEqual(200, created.status_code, created.text)
        self.assertEqual(200, paid.status_code, paid.text)
        self.assertEqual("monthly", paid.json()["account"]["accountEntitlement"]["plan"])
        self.assertEqual(
            [
                "plans",
                ("create", "monthly", "alipay", "click-1"),
                ("status", "order-1", True),
                "refresh",
            ],
            calls,
        )

    def test_entitlement_redeem_runs_inside_account_transition_gate(self) -> None:
        app = FastAPI()
        events: list[str] = []
        transition = {"active": False, "token": 0}

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": True,
                    "accountEntitlement": {"accountId": "account-current"},
                }

            def redeem_entitlement_code(self, _code):
                if not transition["active"]:
                    raise AssertionError("redeem escaped account transition")
                events.append("redeem")
                return {"source": "newapi_account"}

        def begin_transition() -> int:
            transition["token"] += 1
            transition["active"] = True
            events.append("begin")
            return transition["token"]

        def end_transition(token: object) -> bool:
            events.append("end")
            if token != transition["token"]:
                return False
            transition["active"] = False
            return True

        ctx = _ctx(Manager())
        ctx.begin_account_transition = begin_transition
        ctx.end_account_transition = end_transition
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/entitlement/redeem",
            json={"code": "LM-PRO-CURRENT"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, ["begin", "redeem", "end"])
        self.assertFalse(transition["active"])

    def test_account_transition_gate_covers_login_and_releases_after_failure(
        self,
    ) -> None:
        app = FastAPI()
        events: list[str] = []
        transition = {"active": False, "token": 0}

        class Manager:
            def public_session(self):
                return {"loggedIn": False}

            def login(self, *_args, **_kwargs):
                if not transition["active"]:
                    raise AssertionError("account transition gate is not active")
                events.append("login")
                raise NewApiAccountError("upstream unavailable")

        def begin_transition() -> int:
            transition["token"] += 1
            transition["active"] = True
            events.append("begin")
            return transition["token"]

        def end_transition(token: object) -> bool:
            events.append("end")
            if token != transition["token"]:
                return False
            transition["active"] = False
            return True

        ctx = _ctx(Manager())
        ctx.begin_account_transition = begin_transition
        ctx.end_account_transition = end_transition
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(events, ["begin", "login", "end"])
        self.assertFalse(transition["active"])

    def test_login_from_logged_out_state_discards_the_unscoped_agent_runtime(
        self,
    ) -> None:
        app = FastAPI()
        calls: list[str] = []
        state = {"loggedIn": False}

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": state["loggedIn"],
                    **(
                        {
                            "account": "new@example.invalid",
                            "accountEntitlement": {"accountId": "account-new"},
                        }
                        if state["loggedIn"]
                        else {}
                    ),
                }

            def login(self, *_args, **_kwargs):
                calls.append("login")
                state["loggedIn"] = True
                return {"source": "newapi_account"}

            def sync_targets(self, _session):
                return []

        ctx = _ctx(Manager())

        def shutdown_agent_service() -> dict:
            calls.append("shutdown_agent")
            return {
                "stopped": True,
                "drained": True,
                "executionMayContinue": False,
            }

        ctx.shutdown_agent_service = shutdown_agent_service
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[:2], ["shutdown_agent", "login"])

    def test_login_from_logged_out_state_stays_fail_closed_when_agent_shutdown_is_indeterminate(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()

        class Manager:
            def public_session(self):
                return {"loggedIn": False}

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        ctx = _ctx(Manager())
        ctx.shutdown_agent_service = lambda: {
            "stopped": False,
            "drained": False,
            "outcomeIndeterminate": True,
            "executionMayContinue": True,
        }
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertTrue(response.json()["cleanup"]["executionMayContinue"])

    def test_login_from_logged_out_state_stays_fail_closed_when_agent_shutdown_raises(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()
        logs: list[str] = []

        class Manager:
            def public_session(self):
                return {"loggedIn": False}

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        def shutdown_agent_service() -> dict:
            raise RuntimeError("shutdown failed apiKey=do-not-leak")

        ctx = _ctx(Manager())
        ctx.append_log = logs.append
        ctx.shutdown_agent_service = shutdown_agent_service
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertNotIn("do-not-leak", repr(response.json()))
        self.assertNotIn("do-not-leak", "".join(logs))

    def test_login_from_logged_out_state_rejects_a_malformed_agent_shutdown_result(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()

        class Manager:
            def public_session(self):
                return {"loggedIn": False}

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        ctx = _ctx(Manager())
        ctx.shutdown_agent_service = lambda: None
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertTrue(response.json()["cleanup"]["executionMayContinue"])

    def test_account_transition_fails_closed_when_current_identity_cannot_be_read(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()
        logs: list[str] = []

        class Manager:
            def public_session(self):
                raise RuntimeError("identity store unreadable apiKey=do-not-leak")

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        ctx = _ctx(Manager())
        ctx.append_log = logs.append
        register_account_routes(app, ctx)

        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertEqual(
            response.json()["cleanup"]["code"],
            "account_runtime_identity_unavailable",
        )
        self.assertTrue(response.json()["cleanup"]["executionMayContinue"])
        self.assertNotIn("do-not-leak", repr(response.json()))
        self.assertNotIn("do-not-leak", "".join(logs))

    def test_account_login_captures_immutable_previous_runtime_identity(self) -> None:
        app = FastAPI()
        captured = []

        class Manager:
            def __init__(self) -> None:
                self.account_id = "account-old"

            def public_session(self):
                return {
                    "loggedIn": True,
                    "account": "old@example.invalid",
                    "accountEntitlement": {"accountId": self.account_id},
                }

            def login(self, *_args, **_kwargs):
                self.account_id = "account-new"
                return {"source": "newapi_account"}

            def sync_targets(self, _session):
                return []

        manager = Manager()

        def cleanup(identity) -> dict:
            captured.append(identity)
            return {
                "ok": True,
                "executionMayContinue": False,
            }

        register_account_routes(
            app,
            _ctx(manager, account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].account_id, "account-old")
        self.assertRegex(captured[0].owner_binding, r"^[0-9a-f]{64}$")
        self.assertTrue(captured[0].resolved)
        with self.assertRaises(FrozenInstanceError):
            captured[0].account_id = "account-tampered"

    def test_account_transition_blocks_when_identity_is_unresolved_and_execution_may_continue(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()
        captured = []

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": True,
                    "account": "old@example.invalid",
                }

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        def cleanup(identity) -> dict:
            captured.append(identity)
            return {
                "ok": False,
                "code": "account_runtime_identity_unresolved",
                "executionMayContinue": True,
            }

        register_account_routes(
            app,
            _ctx(Manager(), account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0].resolved)
        self.assertFalse(login_called.is_set())

    def test_account_transition_confirms_terminal_state_before_replacing_credentials(
        self,
    ) -> None:
        app = FastAPI()
        login_called = threading.Event()

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": True,
                    "accountEntitlement": {"accountId": "account-old"},
                }

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        def cleanup(_identity) -> dict:
            return {
                "ok": True,
                "executionMayContinue": False,
                "unfinishedJobIds": ["job-old"],
            }

        register_account_routes(
            app,
            _ctx(Manager(), account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertTrue(response.json()["cleanup"]["executionMayContinue"])

    def test_concurrent_account_transitions_are_serialized_and_capture_each_previous_identity(
        self,
    ) -> None:
        app = FastAPI()
        state_lock = threading.Lock()
        first_cleanup_started = threading.Event()
        release_first_cleanup = threading.Event()
        cleanup_identities = []
        login_order: list[str] = []
        active_cleanups = 0
        maximum_active_cleanups = 0

        class Manager:
            def __init__(self) -> None:
                self.account_id = "account-old"

            def public_session(self):
                with state_lock:
                    account_id = self.account_id
                return {
                    "loggedIn": True,
                    "account": f"{account_id}@example.invalid",
                    "accountEntitlement": {"accountId": account_id},
                }

            def login_with_email_code(self, email, _code, *, base_url=""):
                del base_url
                account_id = "account-a" if email.startswith("a@") else "account-b"
                with state_lock:
                    self.account_id = account_id
                    login_order.append(account_id)
                return {"source": "newapi_account"}

        manager = Manager()

        def cleanup(identity) -> dict:
            nonlocal active_cleanups, maximum_active_cleanups
            with state_lock:
                active_cleanups += 1
                maximum_active_cleanups = max(
                    maximum_active_cleanups,
                    active_cleanups,
                )
                cleanup_identities.append(identity)
                cleanup_number = len(cleanup_identities)
            try:
                if cleanup_number == 1:
                    first_cleanup_started.set()
                    release_first_cleanup.wait(2)
                return {
                    "ok": True,
                    "executionMayContinue": False,
                }
            finally:
                with state_lock:
                    active_cleanups -= 1

        register_account_routes(
            app,
            _ctx(manager, account_logout_cleanup=cleanup),
        )
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                client.post,
                "/api/account/email-code/login",
                json={"email": "a@example.invalid", "code": "111111"},
            )
            self.assertTrue(first_cleanup_started.wait(1))
            second = pool.submit(
                client.post,
                "/api/account/email-code/login",
                json={"email": "b@example.invalid", "code": "222222"},
            )
            time.sleep(0.1)
            with state_lock:
                self.assertEqual(login_order, [])
                self.assertEqual(len(cleanup_identities), 1)
            release_first_cleanup.set()
            first_response = first.result(timeout=3)
            second_response = second.result(timeout=3)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(login_order, ["account-a", "account-b"])
        self.assertEqual(
            [identity.account_id for identity in cleanup_identities],
            ["account-old", "account-a"],
        )
        self.assertEqual(maximum_active_cleanups, 1)

    def test_account_login_drains_existing_runtime_before_replacing_session(self) -> None:
        app = FastAPI()
        calls: list[str] = []

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": True,
                    "account": "old@example.invalid",
                }

            def login(self, *_args, **_kwargs):
                calls.append("login")
                return {"source": "newapi_account"}

            def sync_targets(self, _session):
                return []

        def cleanup(_identity) -> dict:
            calls.append("cleanup")
            return {
                "ok": True,
                "executionMayContinue": False,
            }

        register_account_routes(
            app,
            _ctx(Manager(), account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[:2], ["cleanup", "login"])

    def test_account_login_does_not_replace_session_while_old_runtime_continues(self) -> None:
        app = FastAPI()
        login_called = threading.Event()

        class Manager:
            def public_session(self):
                return {
                    "loggedIn": True,
                    "account": "old@example.invalid",
                }

            def login(self, *_args, **_kwargs):
                login_called.set()
                return {"source": "newapi_account"}

        def cleanup(_identity) -> dict:
            return {
                "ok": False,
                "executionMayContinue": True,
                "unfinishedJobIds": ["job-old"],
            }

        register_account_routes(
            app,
            _ctx(Manager(), account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post(
            "/api/account/login",
            json={"email": "new@example.invalid", "password": "secret"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(login_called.is_set())
        self.assertTrue(response.json()["cleanup"]["executionMayContinue"])
        self.assertIn("旧账号", response.json()["error"])

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

    def test_subscription_not_found_does_not_instruct_a_logged_in_user_to_login(self) -> None:
        message = _friendly_account_error("HTTP_404: resource not found", "subscription")

        self.assertEqual(message, "模型账户服务暂不可用，请稍后重试；当前已显示上次安全快照。")
        self.assertNotIn("密码登录", message)

    def test_sync_not_found_does_not_offer_an_unrelated_password_login_recovery(self) -> None:
        message = _friendly_account_error("HTTP_404: resource not found", "sync")

        self.assertEqual(message, "模型账号接口暂不可用，请稍后重试")
        self.assertNotIn("密码登录", message)

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

    def test_account_sync_stops_runtime_when_entitlement_is_inactive(self) -> None:
        app = FastAPI()
        cleanup_calls: list[str] = []
        manager = SimpleNamespace(
            refresh_current=lambda: {"lastSyncResults": []},
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
                "accountEntitlement": {
                    "source": "authorization_required",
                    "plan": "inactive",
                    "limits": {"devices": 0, "concurrentTasks": 0},
                },
            },
        )

        def cleanup(_identity) -> dict:
            cleanup_calls.append("cleanup")
            return {
                "ok": True,
                "performed": True,
                "executionMayContinue": False,
                "cancelledJobIds": ["job-publish"],
            }

        register_account_routes(
            app,
            _ctx(manager, account_logout_cleanup=cleanup),
        )
        response = TestClient(app).post("/api/account/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(cleanup_calls, ["cleanup"])
        self.assertEqual(
            response.json()["cleanup"]["cancelledJobIds"],
            ["job-publish"],
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

    def test_entitlement_redeem_binds_code_to_logged_in_account_and_returns_safe_snapshot(self) -> None:
        app = FastAPI()
        calls = []

        def redeem_entitlement_code(code: str) -> dict:
            calls.append(code)
            return {
                "source": "newapi_account",
                "lastSyncResults": [],
            }

        manager = SimpleNamespace(
            redeem_entitlement_code=redeem_entitlement_code,
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
                "accountEntitlement": {
                    "source": "signed_lease",
                    "plan": "pro",
                    "limits": {"devices": 5, "concurrentTasks": 3},
                },
            },
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        response = client.post(
            "/api/account/entitlement/redeem",
            json={"code": "LM-PRO-UNUSED"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["LM-PRO-UNUSED"])
        self.assertEqual(
            response.json()["account"]["accountEntitlement"]["limits"]["devices"],
            5,
        )
        self.assertNotIn("LM-PRO-UNUSED", repr(response.json()))

    def test_entitlement_redeem_translates_code_errors_and_rejects_empty_code(self) -> None:
        app = FastAPI()

        def redeem_entitlement_code(_code: str) -> dict:
            raise NewApiAccountError("authorization_code_expired")

        manager = SimpleNamespace(
            redeem_entitlement_code=redeem_entitlement_code,
            public_session=lambda: {"loggedIn": True},
        )
        register_account_routes(app, _ctx(manager))
        client = TestClient(app)

        blank = client.post("/api/account/entitlement/redeem", json={"code": ""})
        expired = client.post(
            "/api/account/entitlement/redeem",
            json={"code": "LM-EXPIRED"},
        )

        self.assertEqual(blank.status_code, 400)
        self.assertIn("授权码", blank.json()["error"])
        self.assertEqual(expired.status_code, 400)
        self.assertIn("过期", expired.json()["error"])
        self.assertNotIn("authorization_code_expired", expired.json()["error"])

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
        calls: list[str] = []
        state = {"loggedIn": True}

        def cleanup(_identity) -> dict:
            calls.append("cleanup")
            return {
                "ok": True,
                "executionMayContinue": False,
                "cancelledJobIds": ["job-phone"],
            }

        def logout() -> bool:
            calls.append("logout")
            state["loggedIn"] = False
            return True

        manager = SimpleNamespace(
            logout=logout,
            public_session=lambda: {
                "loggedIn": state["loggedIn"],
                "accountEntitlement": {"accountId": "account-old"},
                "models": {"text": [], "image": [], "video": []},
            },
        )
        register_account_routes(app, _ctx(manager, account_logout_cleanup=cleanup))
        client = TestClient(app)

        response = client.post("/api/account/logout")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(calls, ["cleanup", "logout"])
        self.assertTrue(payload["loggedOut"])
        self.assertFalse(payload["account"]["loggedIn"])
        self.assertTrue(payload["cleanup"]["ok"])
        self.assertFalse(payload["cleanup"]["executionMayContinue"])

    def test_logout_route_keeps_credentials_when_cleanup_is_incomplete(self) -> None:
        app = FastAPI()
        logs: list[str] = []
        logout_calls: list[str] = []
        manager = SimpleNamespace(
            logout=lambda: logout_calls.append("logout") or True,
            public_session=lambda: {
                "loggedIn": True,
                "models": {"text": [], "image": [], "video": []},
            },
        )

        def cleanup(_identity) -> dict:
            raise RuntimeError("daemon stop failed apiKey=do-not-leak")

        ctx = _ctx(manager, account_logout_cleanup=cleanup)
        ctx.append_log = logs.append
        register_account_routes(app, ctx)
        client = TestClient(app)

        response = client.post("/api/account/logout")

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["loggedOut"])
        self.assertTrue(payload["account"]["loggedIn"])
        self.assertEqual(logout_calls, [])
        self.assertFalse(payload["cleanup"]["ok"])
        self.assertTrue(payload["cleanup"]["executionMayContinue"])
        self.assertNotIn("do-not-leak", repr(payload))
        self.assertNotIn("do-not-leak", "".join(logs))


def _ctx(manager, *, account_logout_cleanup=None):
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
        account_logout_cleanup=account_logout_cleanup,
        paths=SimpleNamespace(base_path="test-install"),
    )


if __name__ == "__main__":
    unittest.main()
