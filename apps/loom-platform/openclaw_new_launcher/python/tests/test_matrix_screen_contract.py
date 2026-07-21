from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_matrix import _capture_matrix_screen, register_matrix_routes
from core.phone_matrix import MatrixControlPlane
from core.stream_tickets import StreamTicketIssuer
from services.jobs import JobManager


class MatrixScreenContractTests(unittest.TestCase):
    def test_ticketless_once_stream_does_not_expose_matrix_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            with patch("api.routes_matrix._matrix_event_sync_best_effort") as sync:
                response = client.get("/api/matrix/events/stream?once=1")

        self.assertEqual(response.status_code, 401)
        sync.assert_not_called()
        self.assertNotIn('"status"', response.text)
        self.assertNotIn('"events"', response.text)

    def test_screen_capture_does_not_block_the_async_route_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, _client_instance = _client(temp_dir)
            endpoint = next(
                route.endpoint
                for route in app.routes
                if getattr(route, "path", "") == "/api/matrix/devices/{device_id}/screen"
            )
            request = SimpleNamespace(query_params={})

            def slow_capture(_ctx, device_id: str, **_options) -> dict:
                time.sleep(0.15)
                return {
                    "schema": "loom.matrix.screen.v1",
                    "deviceId": device_id,
                    "screenHash": "sha256:async",
                    "image": "QUJD",
                }

            async def exercise() -> float:
                started = time.monotonic()
                response_task = asyncio.create_task(endpoint("phone-a", request))
                await asyncio.sleep(0.02)
                loop_delay = time.monotonic() - started
                await response_task
                return loop_delay

            with patch("api.routes_matrix._capture_matrix_screen", side_effect=slow_capture):
                loop_delay = asyncio.run(exercise())

        self.assertLess(loop_delay, 0.08)

    def test_screen_known_hash_omits_unchanged_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            capture = {
                "schema": "loom.matrix.screen.v1",
                "deviceId": "phone-a",
                "capturedAt": "2026-07-16T10:00:00Z",
                "screenHash": "sha256:abc123",
                "mime": "image/jpeg",
                "width": 1080,
                "height": 2400,
                "image": "QUJD",
                "notModified": False,
            }
            with patch("api.routes_matrix._capture_matrix_screen", return_value=capture, create=True) as mocked:
                response = client.get(
                    "/api/matrix/devices/phone-a/screen?knownHash=sha256%3Aabc123"
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["notModified"])
        self.assertNotIn("image", response.json())
        mocked.assert_called_once()

    def test_screen_batch_returns_multiple_devices_with_adaptive_capture_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)

            def capture(_ctx, device_id: str, **_options) -> dict:
                return {
                    "schema": "loom.matrix.screen.v1",
                    "deviceId": device_id,
                    "capturedAt": "2026-07-20T10:00:00Z",
                    "screenHash": f"sha256:{device_id}",
                    "mime": "image/jpeg",
                    "width": 432,
                    "height": 960,
                    "image": "QUJD",
                    "notModified": False,
                }

            with patch("api.routes_matrix._capture_matrix_screen", side_effect=capture) as mocked:
                response = client.post(
                    "/api/matrix/screens",
                    json={
                        "requests": [
                            {"deviceId": "phone-a", "focused": True},
                            {"deviceId": "phone-b"},
                        ]
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schema"], "loom.matrix.screens.v1")
        self.assertEqual([item["deviceId"] for item in response.json()["screens"]], ["phone-a", "phone-b"])
        self.assertEqual(response.json()["errors"], [])
        self.assertEqual(mocked.call_args_list[0].kwargs["quality"], 62)
        self.assertEqual(mocked.call_args_list[0].kwargs["max_long_side"], 960)
        self.assertEqual(mocked.call_args_list[1].kwargs["quality"], 48)
        self.assertEqual(mocked.call_args_list[1].kwargs["max_long_side"], 640)

    def test_screen_capture_refreshes_matrix_foreground_app_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = SimpleNamespace(
                base_path=temp_dir,
                launcher_dir=temp_dir,
                node_exe=sys.executable,
            )
            matrix = MatrixControlPlane(paths)
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": True,
                    "currentPackage": "com.google.android.apps.photos",
                    "foregroundApp": "Photos",
                }
            )
            payload = {
                "ok": True,
                "frame": {
                    "capturedAt": "2026-07-18T19:27:44Z",
                    "width": 432,
                    "height": 960,
                    "currentScreen": {
                        "packageName": "com.google.android.apps.nexuslauncher",
                        "screen": {
                            "currentPackage": "com.google.android.apps.nexuslauncher",
                            "currentApp": "Pixel Launcher",
                        },
                    },
                    "image": {"mime": "image/jpeg", "base64": "QUJD"},
                },
            }
            ctx = SimpleNamespace(paths=paths)
            with patch("api.routes_matrix._script_path", return_value=__file__), patch(
                "api.routes_matrix._run_phone_process_with_matrix_stream",
                return_value={
                    "returncode": 0,
                    "stdout": json.dumps(payload),
                    "stderr": "",
                },
            ):
                _capture_matrix_screen(ctx, "phone-a")

            device = matrix.status()["devices"][0]

        self.assertEqual(device["currentPackage"], "com.google.android.apps.nexuslauncher")
        self.assertEqual(device["foregroundApp"], "Pixel Launcher")

    def test_screen_capture_uses_the_shared_slow_device_observe_budget(self) -> None:
        paths = SimpleNamespace(
            base_path=os.path.dirname(__file__),
            launcher_dir=os.path.dirname(__file__),
            node_exe=sys.executable,
        )
        payload = {
            "ok": True,
            "frame": {
                "width": 432,
                "height": 960,
                "image": {"mime": "image/jpeg", "base64": "QUJD"},
            },
        }
        ctx = SimpleNamespace(paths=paths)
        with patch("api.routes_matrix._script_path", return_value=__file__), patch(
            "api.routes_matrix._run_phone_process_with_matrix_stream",
            return_value={"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
        ) as run_process:
            _capture_matrix_screen(ctx, "phone-a")

        self.assertGreaterEqual(run_process.call_args.kwargs["timeout_sec"], 45)

    def test_screen_capture_passes_the_slow_device_budget_into_the_vision_cli(self) -> None:
        paths = SimpleNamespace(
            base_path=os.path.dirname(__file__),
            launcher_dir=os.path.dirname(__file__),
            node_exe=sys.executable,
        )
        payload = {
            "ok": True,
            "frame": {
                "width": 432,
                "height": 960,
                "image": {"mime": "image/jpeg", "base64": "QUJD"},
            },
        }
        ctx = SimpleNamespace(paths=paths)
        with patch("api.routes_matrix._script_path", return_value=__file__), patch(
            "api.routes_matrix._run_phone_process_with_matrix_stream",
            return_value={"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
        ) as run_process:
            _capture_matrix_screen(ctx, "phone-a")

        command = run_process.call_args.args[1]
        self.assertIn("--frame-timeout-ms", command)
        self.assertGreaterEqual(int(command[command.index("--frame-timeout-ms") + 1]), 40_000)

    def test_screen_capture_uses_requested_lightweight_frame_settings_and_cache(self) -> None:
        paths = SimpleNamespace(
            base_path=os.path.dirname(__file__),
            launcher_dir=os.path.dirname(__file__),
            node_exe=sys.executable,
        )
        payload = {
            "ok": True,
            "frame": {
                "width": 360,
                "height": 800,
                "image": {"mime": "image/jpeg", "base64": "QUJD"},
            },
        }
        ctx = SimpleNamespace(paths=paths)
        with patch("api.routes_matrix._script_path", return_value=__file__), patch(
            "api.routes_matrix._run_phone_process_with_matrix_stream",
            return_value={"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
        ) as run_process:
            _capture_matrix_screen(
                ctx,
                "phone-a",
                quality=48,
                max_long_side=640,
                cache_ttl_ms=1200,
            )

        command = run_process.call_args.args[1]
        self.assertEqual(command[command.index("--quality") + 1], "48")
        self.assertEqual(command[command.index("--max-long-side") + 1], "640")
        self.assertEqual(command[command.index("--cache-ttl-ms") + 1], "1200")

    def test_screen_capture_clears_stale_app_name_when_new_frame_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = SimpleNamespace(
                base_path=temp_dir,
                launcher_dir=temp_dir,
                node_exe=sys.executable,
            )
            matrix = MatrixControlPlane(paths)
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": True,
                    "currentPackage": "com.google.android.apps.photos",
                    "foregroundApp": "Photos",
                }
            )
            payload = {
                "ok": True,
                "frame": {
                    "width": 432,
                    "height": 960,
                    "currentScreen": {"packageName": "com.android.systemui"},
                    "image": {"mime": "image/jpeg", "base64": "QUJD"},
                },
            }
            ctx = SimpleNamespace(paths=paths)
            with patch("api.routes_matrix._script_path", return_value=__file__), patch(
                "api.routes_matrix._run_phone_process_with_matrix_stream",
                return_value={
                    "returncode": 0,
                    "stdout": json.dumps(payload),
                    "stderr": "",
                },
            ):
                _capture_matrix_screen(ctx, "phone-a")

            device = matrix.status()["devices"][0]

        self.assertEqual(device["currentPackage"], "com.android.systemui")
        self.assertEqual(device["foregroundApp"], "")

    def test_timeline_returns_only_recent_events_for_requested_device(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.append_runtime_event("phone.step", "phone-a", "first")
            matrix.append_runtime_event("phone.step", "phone-b", "other")
            matrix.append_runtime_event("phone.step", "phone-a", "latest")

            response = client.get("/api/matrix/devices/phone-a/timeline?limit=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([event["message"] for event in response.json()["events"]], ["latest"])
        self.assertTrue(all(event["deviceId"] == "phone-a" for event in response.json()["events"]))

    def test_normal_matrix_stream_requires_one_time_topic_ticket_and_replays_after_seq(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.append_runtime_event("phone.step", "phone-a", "first")
            matrix.append_runtime_event("phone.step", "phone-a", "second")

            denied = client.get("/api/matrix/events/stream?afterSeq=0&once=1&unified=1")
            ticket = app.state.stream_ticket_issuer.issue(
                topic="matrix",
                resource="all",
                subject="local-ui:testclient",
            )
            streamed = client.get(
                "/api/matrix/events/stream?afterSeq=1&once=1&unified=1",
                headers={"Authorization": f"Bearer {ticket}"},
            )
            replay = client.get(
                "/api/matrix/events/stream?afterSeq=0&once=1&unified=1",
                headers={"Authorization": f"Bearer {ticket}"},
            )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(streamed.status_code, 200)
        self.assertIn('"schema": "loom.realtime.event.v1"', streamed.text)
        self.assertIn('"message": "second"', streamed.text)
        self.assertNotIn('"message": "first"', streamed.text)
        self.assertEqual(replay.status_code, 401)


def _client(base_path: str) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    job_mgr = JobManager(lambda _message: None)

    async def body(request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def fastapi_json(data: dict, status_code: int = 200):
        return JSONResponse(status_code=status_code, content=data)

    ctx = SimpleNamespace(
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_job_mgr=lambda: job_mgr,
        paths=SimpleNamespace(base_path=base_path, launcher_dir=base_path, node_exe=sys.executable),
        stream_ticket_issuer=StreamTicketIssuer(ttl_seconds=30),
    )
    app.state.stream_ticket_issuer = ctx.stream_ticket_issuer
    register_matrix_routes(app, ctx)
    return app, TestClient(app)


if __name__ == "__main__":
    unittest.main()
