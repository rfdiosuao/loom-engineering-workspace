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
