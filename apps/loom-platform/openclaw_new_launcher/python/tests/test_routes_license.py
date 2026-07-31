from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_license import register_license_routes


class LicenseRoutePublicSafetyTests(unittest.TestCase):
    def test_current_route_masks_gateway_and_member_secrets(self) -> None:
        app = FastAPI()
        register_license_routes(app, _context())
        client = TestClient(app)

        response = client.get("/api/license/current")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        dumped = repr(payload)
        self.assertNotIn("sk-live-test-secret", dumped)
        self.assertNotIn("member-secret-token", dumped)
        self.assertNotIn("'apiKey':", dumped)
        self.assertNotIn('"apiKey":', dumped)
        self.assertEqual(payload["gatewayProfile"]["apiKeyMasked"], "sk-l****cret")
        self.assertEqual(payload["member"]["memberTokenMasked"], "memb****oken")

    def test_current_route_exposes_commercial_status_and_local_machine_ids(self) -> None:
        app = FastAPI()
        register_license_routes(app, _context())
        client = TestClient(app)

        payload = client.get("/api/license/current").json()

        self.assertEqual(payload["status"], "authorized")
        self.assertEqual(payload["code"], "AUTHORIZED")
        self.assertEqual(payload["installId"], "install-route-test")
        self.assertEqual(payload["deviceId"], "device-route-test")
        self.assertEqual(payload["license"]["plan"], "team_monthly")

    def test_authorized_route_uses_account_entitlement_after_migration(self) -> None:
        requested: list[str | None] = []
        context = _context()
        context.get_entitlement_mgr = lambda: SimpleNamespace(
            is_authorized=lambda feature=None: requested.append(feature) or feature == "matrix.devices"
        )
        context.get_license_mgr = lambda: SimpleNamespace(
            is_authorized=lambda _feature=None: (_ for _ in ()).throw(
                AssertionError("legacy license must not authorize migrated accounts")
            )
        )
        app = FastAPI()
        register_license_routes(app, context)
        client = TestClient(app)

        response = client.post("/api/license/authorized", json={"feature": "matrix.devices"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authorized"], True)
        self.assertEqual(requested, ["matrix.devices"])

    def test_current_route_uses_signed_account_entitlement_as_commercial_truth(self) -> None:
        context = _context()
        legacy_license = context.get_license_mgr()
        legacy_license.current_license = lambda: (_ for _ in ()).throw(
            AssertionError("legacy license must not override signed account entitlement")
        )
        context.get_entitlement_mgr = lambda: SimpleNamespace(
            current_state=lambda _feature=None: {
                "authorized": True,
                "source": "account_entitlement",
                "accountLeaseSeen": True,
                "plan": "activated",
                "features": ["matrix.devices", "matrix.tasks"],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 1,
                    "unlimitedDevices": True,
                },
                "expiresAt": 1_900_000_000,
                "offlineGraceUntil": 1_900_259_200,
                "entitlementVersion": 4,
                "offline": False,
                "lease": {
                    "accountId": "42",
                    "installId": "install-route-test",
                    "deviceId": "device-route-test",
                    "hostDeviceId": "device-route-test",
                    "signature": "signed-account-lease",
                    "codeLabel": "",
                },
            },
            is_authorized=lambda _feature=None: True,
        )
        app = FastAPI()
        register_license_routes(app, context)
        client = TestClient(app)

        payload = client.get("/api/license/current").json()

        self.assertEqual(payload["status"], "authorized")
        self.assertEqual(payload["license"]["plan"], "activated")
        self.assertIsNone(payload["license"]["deviceLimit"])
        self.assertTrue(payload["license"]["unlimitedDevices"])
        self.assertEqual(payload["license"]["signature"], "signed-account-lease")
        self.assertEqual(payload["source"], "account_entitlement")

    def test_activate_route_redeems_against_logged_in_account_not_legacy_machine(self) -> None:
        calls: list[str] = []
        transition_events: list[str] = []
        transition = {"active": False, "token": 0}
        context = _context()
        context.get_license_mgr().activate = lambda _code: (_ for _ in ()).throw(
            AssertionError("legacy machine activation must not run for logged-in account")
        )
        account_manager = SimpleNamespace(
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
                "accountEntitlement": {
                    "plan": "pro",
                    "limits": {"devices": 5, "concurrentTasks": 3},
                },
            },
            redeem_entitlement_code=lambda code: (
                (_ for _ in ()).throw(AssertionError("license redeem escaped account transition"))
                if not transition["active"]
                else calls.append(code) or {}
            ),
        )
        def begin_transition() -> int:
            transition["token"] += 1
            transition["active"] = True
            transition_events.append("begin")
            return transition["token"]

        def end_transition(token: object) -> bool:
            transition_events.append("end")
            if token != transition["token"]:
                return False
            transition["active"] = False
            return True

        context.begin_account_transition = begin_transition
        context.end_account_transition = end_transition
        context.get_newapi_account_mgr = lambda: account_manager
        context.get_entitlement_mgr = lambda: SimpleNamespace(
            current_state=lambda _feature=None: {
                "authorized": True,
                "source": "account_entitlement",
                "accountLeaseSeen": True,
                "plan": "pro",
                "features": ["matrix.devices", "matrix.tasks"],
                "limits": {"devices": 5, "concurrentTasks": 3},
                "expiresAt": 1_900_000_000,
                "offlineGraceUntil": 1_900_259_200,
                "entitlementVersion": 8,
                "offline": False,
                "lease": {
                    "accountId": "42",
                    "installId": "install-route-test",
                    "deviceId": "device-route-test",
                    "signature": "signed-pro-lease",
                },
            },
            is_authorized=lambda _feature=None: True,
        )
        app = FastAPI()
        register_license_routes(app, context)
        client = TestClient(app)

        response = client.post("/api/license/activate", json={"code": "LM-PRO-UNUSED"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["LM-PRO-UNUSED"])
        self.assertEqual(transition_events, ["begin", "end"])
        self.assertEqual(response.json()["license"]["deviceLimit"], 5)
        self.assertNotIn("LM-PRO-UNUSED", repr(response.json()))

    def test_activate_route_rejects_redeem_during_another_account_transition(self) -> None:
        context = _context()
        context.get_license_mgr().activate = lambda _code: (_ for _ in ()).throw(
            AssertionError("legacy machine activation must not run during account transition")
        )
        account_manager = SimpleNamespace(
            public_session=lambda: {
                "loggedIn": True,
                "account": "user@example.invalid",
            },
            redeem_entitlement_code=lambda _code: (_ for _ in ()).throw(
                AssertionError("authorization code must not be redeemed during account transition")
            ),
        )
        context.begin_account_transition = lambda: (_ for _ in ()).throw(
            ValueError("account transition already in progress")
        )
        context.end_account_transition = lambda _token: (_ for _ in ()).throw(
            AssertionError("unstarted transition must not be ended")
        )
        context.get_newapi_account_mgr = lambda: account_manager
        app = FastAPI()
        register_license_routes(app, context)
        client = TestClient(app)

        response = client.post("/api/license/activate", json={"code": "LM-RACE"})

        self.assertEqual(response.status_code, 409)
        self.assertIn("账号正在切换", response.json()["error"])


def _context() -> SimpleNamespace:
    license_mgr = SimpleNamespace(
        current_license=lambda: {
            "licensee": "LOOM Tester",
            "signature": "signed-test-value",
            "plan": "team_monthly",
            "gateway": {"apiKey": "sk-live-test-secret"},
            "memberToken": "member-secret-token",
        },
        diagnose=lambda include_gateway_profile=True: {
            "ok": True,
            "code": "ok",
            "message": "authorized",
        },
        get_install_id=lambda: "install-route-test",
        device_id=lambda: "device-route-test",
        current_gateway_profile=lambda: {
            "baseUrl": "https://api.heang.top/v1",
            "apiKey": "sk-live-test-secret",
            "imageApiKey": "sk-live-test-secret",
            "models": ["qwen3.7-plus"],
        },
    )
    member_mgr = SimpleNamespace(
        current=lambda: {
            "memberId": "test-user",
            "memberToken": "member-secret-token",
        },
    )
    return SimpleNamespace(
        auth_error=lambda _request: None,
        body=lambda request: request.json(),
        fastapi_json=_fastapi_json,
        get_license_mgr=lambda: license_mgr,
        get_member_mgr=lambda: member_mgr,
    )


def _fastapi_json(data: dict, status_code: int = 200):
    payload = dict(data)
    payload["_meta"] = {"ok": 200 <= status_code < 400 and "error" not in payload, "status": status_code}
    return JSONResponse(status_code=status_code, content=payload)


if __name__ == "__main__":
    unittest.main()
