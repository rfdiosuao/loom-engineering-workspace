import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient


PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_ROOT)

from api.routes_phone_stream import register_phone_stream_routes
from core.stream_tickets import StreamTicketIssuer


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Context:
    def __init__(self):
        self.paths = SimpleNamespace(launcher_dir="D:/loom/data")
        self.stream_ticket_issuer = StreamTicketIssuer(ttl_seconds=30)

    @staticmethod
    def auth_error(_request):
        return None

    @staticmethod
    async def body(request):
        return await request.json()

    @staticmethod
    def fastapi_json(payload, status=200):
        from fastapi.responses import JSONResponse

        return JSONResponse(payload, status_code=status)


def _runtime(_ctx, _allowed):
    return ({
        "selectedDeviceId": "phone-usb",
        "devices": [{
            "id": "phone-usb",
            "baseUrl": "http://127.0.0.1:19527",
            "phoneToken": "p" * 64,
            "launcherId": "launcher-a",
            "launcherSecret": "s" * 64,
        }],
    }, "member-token")


class PhoneStreamRouteTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _Context()
        self.app = FastAPI()
        self.upstream_requests = []

        def phone_open(request, timeout=0):
            self.upstream_requests.append((request, timeout))
            if request.full_url.endswith("/api/lumi/stream/session"):
                return _Response(json.dumps({
                    "success": True,
                    "data": {
                        "state": "active",
                        "sessionId": "phone-session-1",
                        "streamToken": "upstream-secret-token",
                        "tokenExpiresAtEpochMs": 4_102_444_800_000,
                        "codec": "avc1.42E01F",
                        "width": 720,
                        "height": 1280,
                        "fps": 15,
                    },
                }).encode("utf-8"))
            return _Response(b"LUMI-framed-h264")

        register_phone_stream_routes(
            self.app,
            self.ctx,
            phone_open=phone_open,
            runtime_resolver=_runtime,
            entitlement_authorizer=lambda *_args, **_kwargs: None,
            account_id_resolver=lambda _ctx: "account-a",
        )
        self.client = TestClient(self.app)

    def test_start_returns_only_local_short_ticket_and_never_phone_credentials(self):
        response = self.client.post(
            "/api/phone-stream/devices/phone-usb/session",
            json={"clientSessionId": "focus-1", "fps": 15},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["transport"], "usb-forward")
        self.assertTrue(payload["ticket"])
        serialized = json.dumps(payload)
        for secret in ("upstream-secret-token", "member-token", "p" * 64, "s" * 64):
            self.assertNotIn(secret, serialized)

    def test_binary_stream_requires_bound_one_time_ticket(self):
        missing = self.client.get("/api/phone-stream/devices/phone-usb/h264")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["code"], "stream_ticket_invalid")

        grant = self.client.post(
            "/api/phone-stream/devices/phone-usb/session",
            json={"clientSessionId": "focus-2"},
        ).json()
        first = self.client.get(
            grant["streamUrl"],
            headers={"Authorization": f"Bearer {grant['ticket']}"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.content, b"LUMI-framed-h264")
        self.assertEqual(first.headers["content-type"], "application/vnd.luming.h264")

        replay = self.client.get(
            grant["streamUrl"],
            headers={"Authorization": f"Bearer {grant['ticket']}"},
        )
        self.assertEqual(replay.status_code, 401)

    def test_permission_required_is_a_degraded_media_state_not_device_failure(self):
        def permission_open(_request, timeout=0):
            return _Response(json.dumps({
                "success": True,
                "data": {
                    "state": "permission_required",
                    "sessionId": "phone-session-pending",
                    "streamToken": "pending-secret",
                    "requiresUserConsent": True,
                },
            }).encode("utf-8"))

        app = FastAPI()
        register_phone_stream_routes(
            app,
            self.ctx,
            phone_open=permission_open,
            runtime_resolver=_runtime,
            entitlement_authorizer=lambda *_args, **_kwargs: None,
            account_id_resolver=lambda _ctx: "account-a",
        )
        response = TestClient(app).post(
            "/api/phone-stream/devices/phone-usb/session",
            json={"clientSessionId": "focus-permission"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"], "permission_required")
        self.assertEqual(payload["fallback"], "snapshot")
        self.assertNotIn("ticket", payload)
        self.assertNotIn("pending-secret", response.text)

    def test_stop_is_safety_cleanup_and_does_not_require_current_entitlement(self):
        operations = []
        app = FastAPI()

        def authorize(_ctx, _device_ids, operation):
            operations.append(operation)
            if operation == "phone.stream.stop":
                raise AssertionError("stop cleanup must not be entitlement-gated")

        register_phone_stream_routes(
            app,
            self.ctx,
            phone_open=lambda request, timeout=0: (
                _Response(json.dumps({
                    "success": True,
                    "data": {
                        "state": "active",
                        "sessionId": "phone-session-cleanup",
                        "streamToken": "cleanup-secret",
                        "tokenExpiresAtEpochMs": 4_102_444_800_000,
                    },
                }).encode("utf-8"))
                if request.full_url.endswith("/api/lumi/stream/session")
                else _Response(json.dumps({"success": True, "data": {"stopped": True}}).encode("utf-8"))
            ),
            runtime_resolver=_runtime,
            entitlement_authorizer=authorize,
            account_id_resolver=lambda _ctx: "account-cleanup",
        )
        client = TestClient(app)
        started = client.post(
            "/api/phone-stream/devices/phone-usb/session",
            json={"clientSessionId": "focus-cleanup"},
        )
        self.assertEqual(started.status_code, 200, started.text)

        stopped = client.delete("/api/phone-stream/devices/phone-usb/session")

        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertTrue(stopped.json()["stopped"])
        self.assertEqual(operations, ["phone.stream.start"])


if __name__ == "__main__":
    unittest.main()
