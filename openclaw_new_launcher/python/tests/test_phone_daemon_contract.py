from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api import routes_phone
from api.routes_phone import register_phone_routes


class PhoneDaemonContractTest(unittest.TestCase):
    def test_phone_agent_command_uses_daemon_auto_flag(self) -> None:
        cmd = routes_phone.build_phone_agent_command(
            {
                "prompt": "打开系统设置",
                "mode": "safe",
                "json": True,
            }
        )

        self.assertIn("--daemon", cmd)
        self.assertIn("auto", cmd)

    @patch("api.routes_phone.subprocess.Popen")
    def test_daemon_start_route_spawns_node_daemon(self, popen) -> None:
        popen.return_value.pid = 123

        with patch("api.routes_phone.phone_daemon_status", return_value={"ok": True, "running": False, "state": "stopped"}):
            result = routes_phone.start_phone_daemon()

        self.assertTrue(result["ok"])
        args = popen.call_args.args[0]
        self.assertIn("openclaw-phone-daemon.mjs", " ".join(args))

    @patch("api.routes_phone.subprocess.Popen")
    def test_daemon_start_is_idempotent_when_already_running(self, popen) -> None:
        with patch("api.routes_phone.phone_daemon_status") as status:
            status.return_value = {
                "ok": True,
                "running": True,
                "state": "running",
                "pid": 4321,
                "port": 9527,
                "sessions": 2,
            }

            result = routes_phone.start_phone_daemon(base_root="D:/Axiangmu/AUSTART")

        self.assertTrue(result["ok"])
        self.assertTrue(result["running"])
        self.assertEqual(result["state"], "running")
        self.assertTrue(result["alreadyRunning"])
        self.assertEqual(result["pid"], 4321)
        self.assertEqual(result["port"], 9527)
        popen.assert_not_called()

    def test_daemon_status_missing_runtime_is_structured(self) -> None:
        with patch("api.routes_phone.read_phone_daemon_runtime", side_effect=FileNotFoundError()):
            result = routes_phone.phone_daemon_status()

        self.assertFalse(result["running"])
        self.assertEqual(result["state"], "stopped")

    def test_daemon_health_sends_runtime_token(self) -> None:
        captured: dict[str, str | None] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"ok": true, "pid": 123}'

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["timeout"] = str(timeout)
            captured["token"] = request.get_header("X-loom-phone-daemon-token") or request.get_header("X-LOOM-PHONE-DAEMON-TOKEN")
            return FakeResponse()

        with patch("api.routes_phone.urlopen", side_effect=fake_urlopen):
            result = routes_phone._phone_daemon_health({"port": 9321, "token": "runtime-test-token"})

        self.assertEqual(result, {"ok": True, "pid": 123})
        self.assertEqual(captured["url"], "http://127.0.0.1:9321/health")
        self.assertEqual(captured["timeout"], "3")
        self.assertEqual(captured["token"], "runtime-test-token")

    def test_daemon_stop_missing_runtime_is_structured(self) -> None:
        with patch("api.routes_phone.read_phone_daemon_runtime", side_effect=FileNotFoundError()):
            result = routes_phone.stop_phone_daemon()

        self.assertTrue(result["ok"])
        self.assertFalse(result["running"])
        self.assertEqual(result["state"], "stopped")
        self.assertFalse(result["stopped"])
        self.assertEqual(result["reason"], "not_running")

    def test_phone_process_env_supports_lightweight_matrix_context(self) -> None:
        ctx = SimpleNamespace(paths=SimpleNamespace(base_path="D:/loom-test"))

        env = routes_phone.phone_process_env(ctx)

        self.assertNotIn("LOOM_PHONE_RUNTIME_CONFIG", env)

    def test_phone_daemon_routes_wire_status_start_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = FastAPI()
            logs: list[str] = []
            ctx = SimpleNamespace(
                append_log=logs.append,
                auth_error=lambda _request: None,
                body=lambda _request: {},
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                read_json=lambda _path, default: default,
                paths=SimpleNamespace(base_path=temp_dir, launcher_dir=temp_dir, node_exe="node-test.exe"),
            )
            register_phone_routes(app, ctx)
            client = TestClient(app)

            with (
                patch("api.routes_phone.phone_daemon_status", return_value={"ok": True, "running": True, "state": "running", "pid": 12, "port": 9527}),
                patch("api.routes_phone.start_phone_daemon", return_value={"ok": True, "running": True, "state": "running", "alreadyRunning": True, "pid": 12, "port": 9527}),
                patch("api.routes_phone.stop_phone_daemon", return_value={"ok": True, "running": False, "state": "stopped", "stopped": True}),
            ):
                status_response = client.get("/api/phone/daemon/status")
                start_response = client.post("/api/phone/daemon/start")
                stop_response = client.post("/api/phone/daemon/stop")

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["state"], "running")
        self.assertEqual(start_response.status_code, 200)
        self.assertTrue(start_response.json()["alreadyRunning"])
        self.assertEqual(stop_response.status_code, 200)
        self.assertTrue(stop_response.json()["stopped"])


if __name__ == "__main__":
    unittest.main()
