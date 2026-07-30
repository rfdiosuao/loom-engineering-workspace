from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from api.routes_cli import _phone_target_ids, _run_phone_cli_process, register_cli_routes
from core.account_entitlement import AccountEntitlementError
from services.jobs import JobManager


class _ImmediatePopen:
    def __init__(self, stdout: str = "{}", stderr: str = "", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.terminated = False

    def communicate(self, timeout=None):
        del timeout
        return self._stdout, self._stderr

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


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
    def test_phone_fleet_target_options_map_to_authorized_device_scope(self) -> None:
        self.assertEqual(
            _phone_target_ids([
                "run",
                "--target",
                "phone-b,phone-a",
                "--prompt",
                "inspect",
            ]),
            ["phone-a", "phone-b"],
        )
        self.assertEqual(
            _phone_target_ids(["status", "--devices=phone-c,phone-a"]),
            ["phone-a", "phone-c"],
        )
        self.assertEqual(_phone_target_ids(["status", "--target", "all"]), [])

    def test_phone_cli_holds_device_slot_and_writes_cooperative_cancel_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cancel_file = os.path.join(temp_dir, "phone-cli.cancel")
            slot_calls: list[dict] = []

            class Entitlement:
                def current_state(self, _feature=None):
                    return {
                        "authorized": True,
                        "accountId": "account-a",
                    }

                def authorize_phone_devices(
                    self,
                    device_ids,
                    operation,
                    *,
                    session=None,
                ):
                    del session
                    return {
                        "authorized": True,
                        "accountId": "account-a",
                        "phoneDeviceIds": list(device_ids),
                        "operation": operation,
                    }

                @contextmanager
                def account_task_slot(
                    self,
                    entitlement,
                    operation,
                    *,
                    cancelled=None,
                    device_ids=None,
                ):
                    slot_calls.append({
                        "entitlement": dict(entitlement),
                        "operation": operation,
                        "deviceIds": list(device_ids or []),
                    })
                    yield

            class HangingPopen(_ImmediatePopen):
                def __init__(self):
                    super().__init__(returncode=None)

                def communicate(self, timeout=None):
                    if self.terminated:
                        return "", ""
                    raise __import__("subprocess").TimeoutExpired("node", timeout)

            process = HangingPopen()
            ctx = SimpleNamespace(
                paths=SimpleNamespace(base_path=temp_dir),
                sanitize_text=lambda text: text,
                get_entitlement_mgr=lambda: Entitlement(),
            )
            cancellation_checks = 0

            def should_cancel():
                nonlocal cancellation_checks
                cancellation_checks += 1
                return cancellation_checks >= 2

            with patch(
                "api.routes_cli._authorize_phone_entitlement",
                return_value={"authorized": True, "accountId": "account-a"},
            ), patch(
                "api.routes_cli.phone_process_env",
                return_value={},
            ), patch(
                "api.routes_cli.subprocess.Popen",
                return_value=process,
            ):
                result = _run_phone_cli_process(
                    ctx,
                    argv=["node", "openclaw-phone-agent.mjs", "run", "--json"],
                    allowed_device_ids=["phone-a"],
                    operation="cli.phone:agent",
                    timeout_sec=5,
                    safety_cleanup=False,
                    should_cancel=should_cancel,
                    cancel_file=cancel_file,
                    cooperative_cancel=True,
                )

            self.assertFalse(result["success"])
            self.assertEqual(result["code"], "cancelled")
            self.assertTrue(process.terminated)
            self.assertTrue(os.path.isfile(cancel_file))
            self.assertEqual(slot_calls[0]["operation"], "cli.phone:agent")
            self.assertEqual(slot_calls[0]["deviceIds"], ["phone-a"])

    def test_phone_cli_rejects_direct_phone_credentials_before_dispatch(self) -> None:
        app = _FakeApp()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=lambda _request: None,
            fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
            protected_error=lambda _path: None,
        )
        register_cli_routes(app, ctx)
        handler = app.handlers[(("POST",), "/api/cli/run")]

        async def body(_request):
            return {
                "command": "phone:agent",
                "args": [
                    "run",
                    "--device-id",
                    "phone-a",
                    "--phone-url",
                    "http://phone-b:9527",
                    "--phone-token",
                    "phone-b-token",
                    "--prompt",
                    "打开微信",
                    "--json",
                ],
                "confirmed": True,
            }

        ctx.body = body
        response = __import__("asyncio").run(handler(SimpleNamespace()))

        self.assertEqual(response["status"], 400)
        self.assertEqual(response["code"], "phone_direct_credentials_forbidden")

    def test_phone_publish_rejects_direct_relay_overrides_before_dispatch(self) -> None:
        app = _FakeApp()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            body=lambda _request: None,
            fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
            protected_error=lambda _path: None,
        )
        register_cli_routes(app, ctx)
        handler = app.handlers[(("POST",), "/api/cli/run")]

        for args in (
            ["--relay-url", "https://relay.example.invalid"],
            ["--relay-token=untrusted-token"],
            ["--channel-id", "other-account"],
            ["--transport", "reverse"],
        ):
            async def body(_request, args=args):
                return {
                    "command": "phone:publish",
                    "args": [*args, "--platform", "xiaohongshu", "--json"],
                    "confirmed": True,
                }

            ctx.body = body
            response = __import__("asyncio").run(handler(SimpleNamespace()))

            self.assertEqual(response["status"], 400, args)
            self.assertEqual(response["code"], "phone_direct_relay_forbidden", args)

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
            storage = {
                os.path.join(temp_dir, "phone-agents.json"): {
                    "selectedDeviceId": "phone-a",
                    "devices": [{
                        "id": "phone-a",
                        "baseUrl": "http://127.0.0.1:19527",
                        "token": "token-a",
                        "launcherId": "launcher-a",
                        "launcherSecret": "secret-a",
                        "deviceInstanceId": "stable-a",
                    }],
                }
            }
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
                read_json=lambda path, default: storage.get(path, default),
                write_json=lambda path, data: storage.__setitem__(path, data),
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
                "api.routes_cli.subprocess.Popen",
                return_value=_ImmediatePopen(),
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
                        "deviceInstanceId": {"__loomSecret": "dpapi", "value": "encrypted-device-instance"},
                        "ownerAccountId": {"__loomSecret": "dpapi", "value": "encrypted-owner-account"},
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
            ctx.get_entitlement_mgr = lambda: SimpleNamespace(
                current_state=lambda _feature=None: {
                    "authorized": True,
                    "source": "account_entitlement",
                    "accountId": "42",
                    "lease": {"accountId": "42"},
                    "limits": {"devices": 1000, "concurrentTasks": 100},
                },
                claimed_phone_device_ids=lambda: ["lumi-phone-secure"],
                authorize_phone_devices=lambda _ids, _operation, session=None: {
                    "authorized": True,
                    "accountId": "42",
                },
                phone_runtime_authorization=lambda _ids, session=None: {
                    "entitlementLease": {
                        "schema": "loom.entitlement_lease.v1",
                        "accountId": "42",
                    },
                    "phoneSeatLease": {
                        "schema": "loom.phone_seat_lease.v1",
                        "accountId": "42",
                    },
                },
            )
            ctx.get_newapi_account_mgr = lambda: SimpleNamespace(
                current=lambda: {"memberToken": "test", "newApi": {}}
            )
            register_cli_routes(app, ctx)
            handler = app.handlers[(("POST",), "/api/cli/run")]
            request = SimpleNamespace()

            async def body(_request):
                return {"command": "phone:fleet", "args": ["list", "--json"], "confirmed": False}

            ctx.body = body
            captured = {}

            def fake_popen(_argv, **kwargs):
                captured["env"] = kwargs["env"]
                return _ImmediatePopen()

            def unprotect(value):
                return {
                    "encrypted-token": "plain-token",
                    "encrypted-launcher-secret": "plain-launcher-secret",
                    "encrypted-device-instance": "lumi-phone-secure",
                    "encrypted-owner-account": "42",
                }[value["value"]]

            with patch("api.routes_phone.unprotect_secret", side_effect=unprotect), patch(
                "api.routes_cli.subprocess.Popen", side_effect=fake_popen
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

    def test_phone_cli_only_exposes_claimed_devices_and_rejects_unclaimed_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, "openclaw-phone-fleet.mjs")
            open(script_path, "w", encoding="utf-8").close()
            storage = {
                os.path.join(temp_dir, "phone-agents.json"): {
                    "selectedDeviceId": "phone-a",
                    "devices": [
                        {
                            "id": "phone-a",
                            "baseUrl": "http://127.0.0.1:19527",
                            "token": "token-a",
                            "launcherId": "launcher-a",
                            "launcherSecret": "secret-a",
                            "deviceInstanceId": "stable-a",
                            "ownerAccountId": "account-a",
                        },
                        {
                            "id": "phone-b",
                            "baseUrl": "http://127.0.0.1:29527",
                            "token": "token-b",
                            "launcherId": "launcher-b",
                            "launcherSecret": "secret-b",
                            "deviceInstanceId": "stable-b",
                            "ownerAccountId": "account-a",
                        },
                    ],
                }
            }
            authorization_calls: list[tuple[list[str], str]] = []

            class Entitlement:
                def current_state(self, _feature=None):
                    return {
                        "authorized": True,
                        "source": "account_entitlement",
                        "accountId": "account-a",
                        "lease": {"accountId": "account-a"},
                        "limits": {"devices": 1000, "concurrentTasks": 100},
                    }

                def claimed_phone_device_ids(self):
                    return ["stable-a"]

                def authorize_phone_devices(self, ids, operation, *, session=None):
                    del session
                    authorization_calls.append((list(ids), operation))
                    return {"authorized": True, "accountId": "account-a"}

                def phone_runtime_authorization(self, ids, *, session=None):
                    del session
                    return {
                        "entitlementLease": {
                            "schema": "loom.entitlement_lease.v1",
                            "accountId": "account-a",
                        },
                        "phoneSeatLease": {
                            "schema": "loom.phone_seat_lease.v1",
                            "accountId": "account-a",
                            "phoneDeviceIds": list(ids),
                        },
                    }

            app = _FakeApp()
            jobs = JobManager(lambda _message: None)
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                body=lambda _request: None,
                fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
                get_job_mgr=lambda: jobs,
                get_entitlement_mgr=lambda: Entitlement(),
                get_newapi_account_mgr=lambda: SimpleNamespace(
                    current=lambda: {"memberToken": "test", "newApi": {}}
                ),
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
            captured = {}

            async def list_body(_request):
                return {
                    "command": "phone:fleet",
                    "args": ["list", "--json"],
                    "confirmed": False,
                }

            ctx.body = list_body

            def fake_popen(_argv, **kwargs):
                captured["env"] = kwargs["env"]
                return _ImmediatePopen()

            with patch("api.routes_cli.subprocess.Popen", side_effect=fake_popen):
                response = __import__("asyncio").run(handler(SimpleNamespace()))
                job_id = response["jobId"]
                for _ in range(100):
                    job = jobs.get(job_id)
                    if job and job.get("status") in {"succeeded", "failed"}:
                        break
                    time.sleep(0.01)

            runtime = json.loads(captured["env"]["LOOM_PHONE_RUNTIME_CONFIG_JSON"])
            self.assertEqual([item["id"] for item in runtime["devices"]], ["phone-a"])
            self.assertNotIn("token-b", json.dumps(runtime))
            self.assertGreaterEqual(len(authorization_calls), 2)

            async def unclaimed_body(_request):
                return {
                    "command": "phone:fleet",
                    "args": ["status", "--device-id", "phone-b", "--json"],
                    "confirmed": False,
                }

            ctx.body = unclaimed_body
            denied = __import__("asyncio").run(handler(SimpleNamespace()))
            self.assertEqual(denied["status"], 409)
            self.assertEqual(denied["code"], "phone_seat_not_claimed")

    def test_running_phone_cli_is_terminated_after_entitlement_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            open(
                os.path.join(temp_dir, "openclaw-phone-fleet.mjs"),
                "w",
                encoding="utf-8",
            ).close()
            calls = 0

            class Entitlement:
                def current_state(self, _feature=None):
                    return {
                        "authorized": True,
                        "source": "account_entitlement",
                        "accountId": "account-a",
                        "lease": {"accountId": "account-a"},
                        "limits": {"devices": 1000, "concurrentTasks": 100},
                    }

                def claimed_phone_device_ids(self):
                    return ["stable-a"]

                def authorize_phone_devices(self, ids, operation, *, session=None):
                    nonlocal calls
                    del ids, operation, session
                    calls += 1
                    if calls >= 3:
                        raise AccountEntitlementError(
                            "权益已撤销",
                            code="account_entitlement_revoked",
                            action="bind_authorization_code",
                        )
                    return {"authorized": True, "accountId": "account-a"}

            class HangingPopen(_ImmediatePopen):
                def __init__(self):
                    super().__init__(returncode=None)

                def communicate(self, timeout=None):
                    if self.terminated:
                        return "", ""
                    raise __import__("subprocess").TimeoutExpired("node", timeout)

            process = HangingPopen()
            storage = {
                os.path.join(temp_dir, "phone-agents.json"): {
                    "selectedDeviceId": "phone-a",
                    "devices": [{
                        "id": "phone-a",
                        "baseUrl": "http://127.0.0.1:19527",
                        "token": "token-a",
                        "launcherId": "launcher-a",
                        "launcherSecret": "secret-a",
                        "deviceInstanceId": "stable-a",
                        "ownerAccountId": "account-a",
                    }],
                }
            }
            app = _FakeApp()
            jobs = JobManager(lambda _message: None)
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                body=lambda _request: None,
                fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
                get_job_mgr=lambda: jobs,
                get_entitlement_mgr=lambda: Entitlement(),
                get_newapi_account_mgr=lambda: SimpleNamespace(
                    current=lambda: {"memberToken": "test", "newApi": {}}
                ),
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

            async def body(_request):
                return {
                    "command": "phone:fleet",
                    "args": ["status", "--device-id", "phone-a", "--json"],
                    "confirmed": False,
                    "timeoutSec": 30,
                }

            ctx.body = body
            with patch("api.routes_cli.subprocess.Popen", return_value=process), patch(
                "api.routes_cli._PHONE_CLI_ENTITLEMENT_HEARTBEAT_SEC",
                0.01,
                create=True,
            ):
                response = __import__("asyncio").run(handler(SimpleNamespace()))
                job_id = response["jobId"]
                for _ in range(200):
                    job = jobs.get(job_id)
                    if job and job.get("status") in {"succeeded", "failed"}:
                        break
                    time.sleep(0.01)

            result = jobs.get(job_id)["result"]
            self.assertTrue(process.terminated)
            self.assertFalse(result["success"])
            self.assertEqual(result["code"], "account_entitlement_revoked")

    def test_phone_cli_route_wires_job_cancellation_into_process_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            open(
                os.path.join(temp_dir, "openclaw-phone-fleet.mjs"),
                "w",
                encoding="utf-8",
            ).close()

            class ImmediateCancelledJobs:
                def progress(self, *_args, **_kwargs):
                    return None

                def is_cancelled(self, job_id):
                    return job_id == "job-cancelled"

                def submit_progress(self, _kind, _label, target, initial_progress=None):
                    self.initial_progress = dict(initial_progress or {})
                    return {
                        "id": "job-cancelled",
                        "status": "cancelled",
                        "result": target("job-cancelled"),
                    }

            jobs = ImmediateCancelledJobs()
            app = _FakeApp()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                body=lambda _request: None,
                fastapi_json=lambda data, status_code=200: {"status": status_code, **data},
                get_job_mgr=lambda: jobs,
                protected_error=lambda _path: None,
                sanitize_text=lambda text: text,
                paths=SimpleNamespace(
                    base_path=temp_dir,
                    scripts_dir=temp_dir,
                    script_roots=(),
                    node_exe=sys.executable,
                    launcher_dir=temp_dir,
                ),
            )
            register_cli_routes(app, ctx)
            handler = app.handlers[(("POST",), "/api/cli/run")]

            async def body(_request):
                return {
                    "command": "phone:fleet",
                    "args": ["status", "--device-id", "phone-a", "--json"],
                    "confirmed": False,
                }

            ctx.body = body
            captured = {}

            def authorize(_ctx, _ids, _operation):
                return {"authorized": True}

            with patch(
                "api.routes_cli._claimed_phone_local_device_ids",
                return_value=["phone-a"],
            ), patch(
                "api.routes_cli._authorize_phone_entitlement",
                side_effect=authorize,
            ), patch(
                "api.routes_cli._run_phone_cli_process",
            ) as run_process:
                run_process.side_effect = lambda *_args, **kwargs: (
                    captured.update(kwargs)
                    or {"success": False, "code": "cancelled", "cancelled": True}
                )
                response = __import__("asyncio").run(handler(SimpleNamespace()))

            self.assertEqual(response["jobId"], "job-cancelled")
            self.assertTrue(callable(captured["should_cancel"]))
            self.assertTrue(captured["should_cancel"]())
            self.assertTrue(jobs.initial_progress["requiresPhoneEntitlement"])
            self.assertEqual(jobs.initial_progress["phoneDeviceIds"], ["phone-a"])

    def test_unexpected_entitlement_error_terminates_phone_cli_process(self) -> None:
        class HangingPopen(_ImmediatePopen):
            def __init__(self):
                super().__init__(returncode=None)

            def communicate(self, timeout=None):
                if self.terminated:
                    return "", ""
                raise __import__("subprocess").TimeoutExpired("node", timeout)

        process = HangingPopen()
        ctx = SimpleNamespace(
            paths=SimpleNamespace(base_path="D:/loom-test"),
            sanitize_text=lambda text: text,
        )
        checks = 0

        def authorize(_ctx, _ids, _operation):
            nonlocal checks
            checks += 1
            if checks >= 2:
                raise OSError("entitlement state unreadable")
            return {"authorized": True}

        with patch("api.routes_cli._authorize_phone_entitlement", side_effect=authorize), patch(
            "api.routes_cli.phone_process_env",
            return_value={},
        ), patch(
            "api.routes_cli.subprocess.Popen",
            return_value=process,
        ), patch(
            "api.routes_cli._PHONE_CLI_ENTITLEMENT_HEARTBEAT_SEC",
            0.01,
        ):
            result = _run_phone_cli_process(
                ctx,
                argv=["node", "phone-cli.mjs"],
                allowed_device_ids=["phone-a"],
                operation="cli.phone:fleet",
                timeout_sec=5,
                safety_cleanup=False,
                should_cancel=lambda: False,
            )

        self.assertTrue(process.terminated)
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "phone_entitlement_check_failed")


if __name__ == "__main__":
    unittest.main()
