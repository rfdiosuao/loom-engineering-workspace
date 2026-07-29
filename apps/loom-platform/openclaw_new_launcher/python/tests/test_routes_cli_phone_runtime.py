from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from api.routes_cli import register_cli_routes
from services.jobs import JobManager


class _FakeApp:
    def __init__(self) -> None:
        self.handlers = {}

    def api_route(self, path, methods):
        def decorator(handler):
            self.handlers[(tuple(methods), path)] = handler
            return handler
        return decorator

    def post(self, path):
        return self.api_route(path, ["POST"])


class CliPhoneRuntimeConfigTests(unittest.TestCase):
    def test_every_phone_cli_command_uses_phone_matrix_license_gate(self) -> None:
        app = _FakeApp()
        checked_paths = []
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=lambda _request: None,
            fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
            protected_error=lambda path: checked_paths.append(path) or {
                "status": 403,
                "code": "LICENSE_FEATURE_REQUIRED",
            },
        )
        register_cli_routes(app, ctx)
        handler = app.handlers[(("POST",), "/api/cli/run")]

        for command, args, confirmed in (
            ("phone:publish", [], True),
            ("phone:fleet", ["status", "--json"], False),
            ("phone:agent", ["run", "--prompt", "读取屏幕", "--mode", "observe", "--json"], False),
        ):
            async def body(_request, command=command, args=args, confirmed=confirmed):
                return {"command": command, "args": args, "confirmed": confirmed}

            ctx.body = body
            response = __import__("asyncio").run(handler(SimpleNamespace()))
            self.assertEqual(response["status"], 403)
            self.assertEqual(response["code"], "LICENSE_FEATURE_REQUIRED")

        self.assertEqual(checked_paths, ["/api/phone"] * 3)

    def test_phone_video_stop_requires_local_auth_and_an_explicit_device_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, "openclaw-phone-video.mjs")
            open(script_path, "w", encoding="utf-8").close()
            app = _FakeApp()
            jobs = JobManager(lambda _message: None)
            auth_calls = []
            protected_calls = []
            ctx = SimpleNamespace(
                auth_error=lambda request: auth_calls.append(request) or None,
                body=lambda _request: None,
                fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
                get_job_mgr=lambda: jobs,
                protected_error=lambda path: protected_calls.append(path) or {
                    "status": 403,
                    "code": "LICENSE_FEATURE_REQUIRED",
                },
                sanitize_text=lambda text: text,
                paths=SimpleNamespace(
                    base_path=temp_dir,
                    scripts_dir=temp_dir,
                    script_roots=(),
                    node_exe=sys.executable,
                    launcher_dir=temp_dir,
                ),
                read_json=lambda _path, default: default,
                write_json=lambda _path, _data: None,
            )
            register_cli_routes(app, ctx)
            handler = app.handlers[(("POST",), "/api/cli/run")]
            request = SimpleNamespace()

            async def explicit_stop(_request):
                return {
                    "command": "phone:video",
                    "args": ["stop", "--device-id", "phone-a", "--json"],
                    "confirmed": True,
                }

            ctx.body = explicit_stop
            with patch(
                "api.routes_cli.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
            ):
                response = __import__("asyncio").run(handler(request))
                job_id = response["jobId"]
                for _ in range(100):
                    job = jobs.get(job_id)
                    if job and job.get("status") in {"succeeded", "failed"}:
                        break
                    __import__("time").sleep(0.01)

            self.assertEqual(len(auth_calls), 1)
            self.assertEqual(protected_calls, [])
            self.assertEqual(jobs.get(job_id)["status"], "succeeded")

            async def unscoped_stop(_request):
                return {
                    "command": "phone:video",
                    "args": ["stop", "--json"],
                    "confirmed": True,
                }

            ctx.body = unscoped_stop
            response = __import__("asyncio").run(handler(request))
            self.assertEqual(response["status"], 403)
            self.assertEqual(response["code"], "LICENSE_FEATURE_REQUIRED")
            self.assertEqual(protected_calls, ["/api/phone"])

            ctx.auth_error = lambda _request: {
                "status": 401,
                "code": "LOCAL_API_AUTH_REQUIRED",
            }
            ctx.body = explicit_stop
            response = __import__("asyncio").run(handler(request))
            self.assertEqual(response["status"], 401)
            self.assertEqual(response["code"], "LOCAL_API_AUTH_REQUIRED")

    def test_phone_cli_route_passes_decrypted_runtime_config_to_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, "openclaw-phone-fleet.mjs")
            open(script_path, "w", encoding="utf-8").close()
            app = _FakeApp()
            jobs = JobManager(lambda _message: None)
            storage = {
                os.path.join(temp_dir, "phone-agents.json"): {
                    "selectedDeviceId": "phone-secure",
                    "devices": [{
                        "id": "phone-secure",
                        "baseUrl": "http://127.0.0.1:9527",
                        "token": {"__loomSecret": "dpapi", "value": "encrypted-token"},
                        "launcherId": "loom-desktop-secure",
                        "launcherSecret": {"__loomSecret": "dpapi", "value": "encrypted-launcher-secret"},
                        "deviceInstanceId": "lumi-phone-secure",
                    }],
                }
            }
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                body=lambda _request: None,
                fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
                get_job_mgr=lambda: jobs,
                get_license_mgr=lambda: SimpleNamespace(is_authorized=lambda: True),
                protected_error=lambda _path: None,
                sanitize_text=lambda text: text,
                paths=SimpleNamespace(
                    base_path=temp_dir,
                    scripts_dir=temp_dir,
                    script_roots=(),
                    node_exe=sys.executable,
                    launcher_dir=temp_dir,
                ),
                read_json=lambda path, default: storage.get(path, default),
                write_json=lambda path, data: storage.__setitem__(path, data),
            )
            register_cli_routes(app, ctx)
            handler = app.handlers[(("POST",), "/api/cli/run")]
            request = SimpleNamespace()

            async def body(_request):
                return {"command": "phone:fleet", "args": ["list", "--json"], "confirmed": False}

            ctx.body = body
            captured = {}

            def fake_run(_argv, **kwargs):
                captured["env"] = kwargs["env"]
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")

            def unprotect(value):
                return {
                    "encrypted-token": "plain-token",
                    "encrypted-launcher-secret": "plain-launcher-secret",
                }[value["value"]]

            with patch("api.routes_phone.unprotect_secret", side_effect=unprotect), patch(
                "api.routes_cli.subprocess.run", side_effect=fake_run
            ):
                response = __import__("asyncio").run(handler(request))
                job_id = response["jobId"]
                for _ in range(100):
                    job = jobs.get(job_id)
                    if job and job.get("status") in {"succeeded", "failed"}:
                        break
                    __import__("time").sleep(0.01)

            runtime = json.loads(captured["env"]["LOOM_PHONE_RUNTIME_CONFIG_JSON"])
            self.assertEqual(runtime["devices"][0]["token"], "plain-token")
            self.assertEqual(runtime["devices"][0]["launcherSecret"], "plain-launcher-secret")
            self.assertNotIn("plain-token", json.dumps(jobs.get(job_id), ensure_ascii=False))
            self.assertNotIn("plain-launcher-secret", json.dumps(jobs.get(job_id), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
