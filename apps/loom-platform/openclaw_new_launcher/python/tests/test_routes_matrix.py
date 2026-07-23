from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
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

from api.routes_jobs import register_job_routes
from api.routes_matrix import _last_json_object, _matrix_stream_fingerprint, register_matrix_routes
from core.stream_tickets import StreamTicketIssuer
from services.jobs import JobManager


class MatrixRouteContractTests(unittest.TestCase):
    def test_matrix_manual_back_and_home_use_supported_direct_phone_actions(self) -> None:
        from api.routes_matrix import _execute_matrix_manual_action

        for action in ("back", "home"):
            with self.subTest(action=action), patch(
                "api.routes_matrix._build_phone_task_plan", return_value={}
            ) as build_plan, patch(
                "api.routes_matrix._submit_phone_job", return_value={"success": True}
            ):
                result = _execute_matrix_manual_action(
                    SimpleNamespace(),
                    "phone-a",
                    {"action": action, "clientCommandId": f"command-{action}"},
                )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(build_plan.call_args.args[1]["actionBody"], {"action": action})

    def test_matrix_manual_recent_returns_actionable_unsupported_failure(self) -> None:
        from api.routes_matrix import _execute_matrix_manual_action

        with patch("api.routes_matrix._submit_phone_job") as submit_phone:
            result = _execute_matrix_manual_action(
                SimpleNamespace(),
                "phone-a",
                {"action": "recent", "clientCommandId": "command-recent"},
            )

        submit_phone.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "matrix_control_unsupported")
        self.assertIn("最近任务", result["error"])
        self.assertIn("暂不支持", result["error"])

    def test_matrix_screen_parser_accepts_pretty_printed_json(self) -> None:
        stdout = json.dumps(
            {
                "ok": True,
                "filePath": "data/phone-frames/frame.jpg",
                "frame": {
                    "width": 1080,
                    "height": 2400,
                    "image": {"mime": "image/jpeg", "base64": "c2NyZWVu"},
                },
            },
            ensure_ascii=False,
            indent=2,
        )

        payload = _last_json_object(stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["frame"]["width"], 1080)

    def test_matrix_stream_fingerprint_ignores_volatile_timestamps(self) -> None:
        first = {
            "schema": "loom.matrix.stream.v1",
            "updatedAt": "2026-07-14T10:00:00+0800",
            "status": {"updatedAt": "2026-07-14T10:00:00+0800", "devices": [], "summary": {}},
            "events": [],
        }
        second = {
            **first,
            "updatedAt": "2026-07-14T10:00:01+0800",
            "status": {**first["status"], "updatedAt": "2026-07-14T10:00:01+0800"},
        }

        self.assertEqual(_matrix_stream_fingerprint(first), _matrix_stream_fingerprint(second))

    def test_matrix_event_stream_returns_sse_status_and_events_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "group": "demo", "online": True})
            from core.phone_matrix import MatrixControlPlane

            MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path="")).append_runtime_event(
                "phone.online",
                "phone-a",
                "Phone registered",
            )
            preflight = client.options(
                "/api/matrix/events/stream",
                headers={
                    "Origin": "http://tauri.localhost",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            ticket = app.state.stream_ticket_issuer.issue(
                topic="matrix",
                resource="all",
                subject="local-ui:testclient",
            )

            response = client.get(
                "/api/matrix/events/stream?once=1",
                headers={"Authorization": f"Bearer {ticket}"},
            )

            self.assertEqual(preflight.status_code, 204)
            self.assertIn("Authorization", preflight.headers["access-control-allow-headers"])
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            self.assertIn("event: matrix", response.text)
            self.assertIn('"schema": "loom.realtime.event.v1"', response.text)
            self.assertIn('"deviceId": "phone-a"', response.text)

    def test_matrix_dispatch_executes_direct_path_and_records_result_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)

            registered = client.post(
                "/api/matrix/device/register",
                json={"deviceId": "phone-a", "group": "demo", "online": True},
            )
            self.assertEqual(registered.status_code, 200)

            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={
                        "prompt": "读取当前屏幕",
                        "mode": "observe",
                        "profile": "fast",
                        "target": {"deviceIds": ["phone-a"]},
                    },
                )

                self.assertEqual(submitted.status_code, 202)
                payload = submitted.json()
                campaign_id = payload["task"]["campaignId"]
                job = _wait_for_job(client, payload["jobId"])

                ledger_path = os.path.join(temp_dir, "loom-task-ledger.jsonl")
                trace_path = os.path.join(temp_dir, "loom-action-trace.jsonl")
                with open(ledger_path, "r", encoding="utf-8") as handle:
                    ledger = json.loads(handle.readline())
                with open(trace_path, "r", encoding="utf-8") as handle:
                    trace = json.loads(handle.readline())

            self.assertEqual(job["status"], "succeeded")
            result = job["result"]
            self.assertTrue(result["success"])
            self.assertEqual(result["results"][0]["executionLayer"], "direct")
            self.assertIn("--device-id", result["results"][0]["stdoutPreview"])
            self.assertIn("phone-a", result["results"][0]["stdoutPreview"])

            watched = client.get(f"/api/matrix/watch?campaignId={campaign_id}")
            event_types = [event["type"] for event in watched.json()["events"]]
            self.assertIn("result", event_types)

            status = client.get("/api/matrix/status").json()
            self.assertFalse(status["devices"][0]["busy"])
            self.assertEqual(status["campaigns"][-1]["status"], "succeeded")
            self.assertEqual(ledger["source"], "bridge")
            self.assertEqual(ledger["tool"], "bridge:matrix.dispatch")
            self.assertEqual(ledger["actionTraceId"], trace["traceId"])

    def test_canonical_dispatch_executes_only_assigned_device_with_assignment_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            submitted_plans: list[dict] = []

            def submit_phone(_ctx, **plan):
                submitted_plans.append(plan)
                return {"success": True, "stdout": "ok", "stderr": ""}

            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            client.post("/api/matrix/device/register", json={"deviceId": "phone-b", "online": True})
            with patch("api.routes_matrix._submit_phone_job", side_effect=submit_phone):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={
                        "schema": "loom.matrix.dispatch.v2",
                        "campaignId": "campaign_route_v2",
                        "concurrency": 1,
                        "mode": "safe",
                        "profile": "standard",
                        "deviceAssignments": [
                            {
                                "assignmentId": "assignment_route_b",
                                "deviceId": "phone-b",
                                "prompt": "  Execute the assignment prompt on phone B.  ",
                                "templateId": "screen_read_v1",
                                "input": {"candidateId": "candidate_route"},
                                "timeoutSec": 180,
                                "retryBudget": 1,
                            }
                        ],
                    },
                )
                self.assertEqual(submitted.status_code, 202)
                job = _wait_for_job(client, submitted.json()["jobId"])

            payload = submitted.json()
            device_task = payload["task"]["missions"][0]["deviceTasks"][0]

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(payload["task"]["campaignId"], "campaign_route_v2")
        self.assertEqual(device_task["assignmentId"], "assignment_route_b")
        self.assertEqual(device_task["deviceId"], "phone-b")
        self.assertEqual(len(submitted_plans), 1)
        plan = submitted_plans[0]
        args = plan["args"]
        self.assertEqual(plan["device_id"], "phone-b")
        self.assertEqual(plan["script_name"], "openclaw-phone-agent.mjs")
        self.assertEqual(plan["timeout_sec"], 180)
        self.assertTrue(plan["exact_timeout"])
        self.assertEqual(args[args.index("--prompt") + 1], "  Execute the assignment prompt on phone B.  ")
        self.assertEqual(args[args.index("--campaign-id") + 1], "campaign_route_v2")
        self.assertEqual(args[args.index("--assignment-id") + 1], "assignment_route_b")
        self.assertEqual(args[args.index("--assignment-template-id") + 1], "screen_read_v1")
        self.assertEqual(json.loads(args[args.index("--input-json") + 1]), {"candidateId": "candidate_route"})
        self.assertEqual(args[args.index("--timeout-sec") + 1], "180")
        self.assertEqual(args[args.index("--retry-budget") + 1], "1")
        self.assertEqual(
            plan["evidence_body"]["input"],
            {"candidateId": "candidate_route"},
        )
        self.assertEqual(plan["evidence_body"]["assignmentId"], "assignment_route_b")
        self.assertEqual(job["result"]["results"][0]["assignmentId"], "assignment_route_b")

    def test_canonical_dispatch_does_not_retry_structured_remote_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            attempts: list[dict] = []

            def submit_phone(_ctx, **plan):
                attempts.append(plan)
                return {
                    "success": False,
                    "errorCode": "timeout",
                    "error": "remote task may still be running",
                    "taskId": "remote-task-42",
                    "stdout": "",
                    "stderr": "",
                }

            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            with patch("api.routes_matrix._submit_phone_job", side_effect=submit_phone):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={
                        "schema": "loom.matrix.dispatch.v2",
                        "campaignId": "campaign_uncertain",
                        "concurrency": 1,
                        "mode": "safe",
                        "profile": "standard",
                        "deviceAssignments": [
                            {
                                "assignmentId": "assignment_uncertain",
                                "deviceId": "phone-a",
                                "prompt": "read the current screen",
                                "templateId": "screen_read_v1",
                                "input": {},
                                "timeoutSec": 180,
                                "retryBudget": 3,
                            }
                        ],
                    },
                )
                job = _wait_for_job(client, submitted.json()["jobId"])

            self.assertEqual(job["status"], "failed")
            self.assertEqual(len(attempts), 1)
            result = job["result"]["results"][0]
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(result["taskId"], "remote-task-42")
            self.assertTrue(result["outcomeIndeterminate"])
            status = client.get(
                "/api/matrix/status",
                params={"campaignId": "campaign_uncertain"},
            ).json()
            stored_task = status["campaigns"][0]["missions"][0]["deviceTasks"][0]
            self.assertEqual(stored_task.get("taskId"), "remote-task-42")
            self.assertTrue(stored_task.get("outcomeIndeterminate"))

    def test_matrix_status_can_query_campaign_older_than_default_window(self) -> None:
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            campaign_ids = [
                matrix.dispatch(
                    {
                        "prompt": f"read screen {index}",
                        "mode": "observe",
                        "target": {"deviceIds": ["phone-a"]},
                    }
                )["campaignId"]
                for index in range(25)
            ]

            default_status = client.get("/api/matrix/status").json()
            selected_status = client.get(
                "/api/matrix/status",
                params={"campaignId": campaign_ids[0]},
            ).json()

            self.assertNotIn(campaign_ids[0], [item["campaignId"] for item in default_status["campaigns"]])
            self.assertEqual(
                [item["campaignId"] for item in selected_status["campaigns"]],
                [campaign_ids[0]],
            )

    def test_matrix_observe_reuses_phone_control_fast_read_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "读取当前屏幕",
                    "mode": "observe",
                    "profile": "fast",
                    "target": {"deviceIds": ["phone-a"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"])

        self.assertEqual(job["status"], "succeeded")
        result = job["result"]["results"][0]
        argv = json.loads(result["stdoutPreview"])["argv"]
        self.assertEqual(argv[0], "read")
        self.assertIn("--fast-path", argv)
        self.assertEqual(argv[argv.index("--fast-path") + 1], "observe_fast")
        self.assertEqual(argv[argv.index("--device-id") + 1], "phone-a")

    def test_matrix_open_settings_reuses_phone_control_action_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _write_script(
                temp_dir,
                "openclaw-phone-agent.mjs",
                body="raise SystemExit('open-settings should use deterministic action first')\n",
            )
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "打开系统设置",
                    "mode": "safe",
                    "profile": "fast",
                    "template": "open-settings",
                    "target": {"deviceIds": ["phone-a"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"])

        self.assertEqual(job["status"], "succeeded")
        result = job["result"]["results"][0]
        self.assertEqual(result["executionLayer"], "template")
        argv = json.loads(result["stdoutPreview"])["argv"]
        self.assertEqual(argv[0], "action")
        self.assertEqual(argv[argv.index("--fast-path") + 1], "action_fast")
        self.assertEqual(argv[argv.index("--device-id") + 1], "phone-a")
        action_body = json.loads(argv[argv.index("--action-body") + 1])
        self.assertEqual(action_body["action"], "open_app")
        self.assertEqual(action_body["packageName"], "com.android.settings")

    def test_matrix_template_failure_falls_back_on_same_device_without_nested_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-vision.mjs",
                body=(
                    "import json\n"
                    "print(json.dumps({'success': False, 'data': {"
                    "'errorCode': 'action_failed', 'error': 'foreground verification failed'"
                    "}}, ensure_ascii=False))\n"
                ),
            )
            _write_script(temp_dir, "openclaw-phone-agent.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "打开系统设置",
                    "mode": "safe",
                    "profile": "fast",
                    "template": "open-settings",
                    "target": {"deviceIds": ["phone-a"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"])
            jobs = client.get("/api/jobs/list?limit=10").json()["jobs"]

        self.assertEqual(job["status"], "succeeded")
        result = job["result"]["results"][0]
        self.assertEqual(result["executionLayer"], "agent")
        self.assertEqual(result["fallback"]["errorCode"], "action_failed")
        argv = json.loads(result["stdoutPreview"])["argv"]
        self.assertEqual(argv[argv.index("--daemon") + 1], "auto")
        self.assertEqual(argv[argv.index("--device-id") + 1], "phone-a")
        self.assertEqual([item["kind"] for item in jobs], ["matrix.dispatch"])

    def test_matrix_agent_reuses_phone_control_daemon_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-agent.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "执行一个需要 Agent 的多步骤任务",
                    "mode": "safe",
                    "profile": "fast",
                    "target": {"deviceIds": ["phone-a"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"])

        self.assertEqual(job["status"], "succeeded")
        result = job["result"]["results"][0]
        argv = json.loads(result["stdoutPreview"])["argv"]
        self.assertEqual(argv[0], "run")
        self.assertEqual(argv[argv.index("--daemon") + 1], "auto")
        self.assertEqual(argv[argv.index("--device-id") + 1], "phone-a")

    def test_matrix_dispatch_streams_device_script_output_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-agent.mjs",
                body=(
                    "import json, time\n"
                    "print('agent round 1: matrix live log', flush=True)\n"
                    "time.sleep(0.7)\n"
                    "print(json.dumps({'ok': True}, ensure_ascii=False), flush=True)\n"
                    "time.sleep(0.1)\n"
                ),
            )
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "group": "demo", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "执行一个需要 Agent 的真实手机任务",
                    "mode": "safe",
                    "profile": "fast",
                    "target": {"deviceIds": ["phone-a"]},
                },
            )

            self.assertEqual(submitted.status_code, 202)
            job_id = submitted.json()["jobId"]
            try:
                event = _wait_for_matrix_event(temp_dir, "matrix live log", timeout=3.0)
                in_flight = client.get(f"/api/jobs/{job_id}").json()["job"]
                self.assertEqual(in_flight["status"], "running")
            finally:
                _wait_for_job(client, job_id, timeout=5.0)
            self.assertEqual(event["type"], "phone.events.phone.task.stdout")
            self.assertEqual(event["deviceId"], "phone-a")

    def test_matrix_full_output_survives_job_store_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-agent.mjs",
                body=(
                    "import json\n"
                    "print('x' * 22000)\n"
                    "print(json.dumps({'ok': True}))\n"
                ),
            )
            state_path = os.path.join(temp_dir, "jobs-state.json")
            _app, client = _client(temp_dir, state_path=state_path)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            submitted = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "complex agent task", "mode": "safe", "target": {"deviceIds": ["phone-a"]}},
            )
            job = _wait_for_job(client, submitted.json()["jobId"])
            restarted = JobManager(lambda _message: None, state_path=state_path)
            restored = restarted.get(job["id"])

        self.assertGreater(len(job["result"]["results"][0]["stdout"]), 20_000)
        self.assertEqual(
            restored["result"]["results"][0]["stdout"],
            job["result"]["results"][0]["stdout"],
        )

    def test_matrix_dispatch_failed_device_marks_background_job_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs", return_code=1)
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "读取当前屏幕", "mode": "observe", "target": {"deviceIds": ["phone-a"]}},
            )
            job = _wait_for_job(client, submitted.json()["jobId"])

        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["result"]["success"])
        self.assertTrue(job["error"])

    def test_matrix_dispatch_continues_to_next_phone_after_one_device_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-vision.mjs",
                body=(
                    "import json, sys\n"
                    "argv = sys.argv[1:]\n"
                    "device = argv[argv.index('--device-id') + 1]\n"
                    "print(json.dumps({'argv': argv, 'ok': device != 'phone-a'}, ensure_ascii=False))\n"
                    "raise SystemExit(1 if device == 'phone-a' else 0)\n"
                ),
            )
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            client.post("/api/matrix/device/register", json={"deviceId": "phone-b", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "读取当前屏幕",
                    "mode": "observe",
                    "target": {"deviceIds": ["phone-a", "phone-b"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"])
            status = client.get("/api/matrix/status").json()

        self.assertEqual(job["status"], "failed")
        results = job["result"]["results"]
        self.assertEqual([item["deviceId"] for item in results], ["phone-a", "phone-b"])
        self.assertFalse(results[0]["success"])
        self.assertTrue(results[1]["success"])
        second_argv = json.loads(results[1]["stdoutPreview"])["argv"]
        self.assertEqual(second_argv[second_argv.index("--device-id") + 1], "phone-b")
        self.assertEqual({item["deviceId"] for item in status["devices"]}, {"phone-a", "phone-b"})

    def test_matrix_dispatch_starts_multiple_phones_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-vision.mjs",
                body=(
                    "import json, os, sys, time\n"
                    "argv = sys.argv[1:]\n"
                    "device = argv[argv.index('--device-id') + 1]\n"
                    "other = 'phone-b' if device == 'phone-a' else 'phone-a'\n"
                    "base = os.path.dirname(os.path.abspath(__file__))\n"
                    "open(os.path.join(base, f'started-{device}'), 'w').close()\n"
                    "deadline = time.time() + 3.0\n"
                    "other_path = os.path.join(base, f'started-{other}')\n"
                    "while time.time() < deadline and not os.path.exists(other_path):\n"
                    "    time.sleep(0.01)\n"
                    "overlapped = os.path.exists(other_path)\n"
                    "print(json.dumps({'argv': argv, 'ok': overlapped}, ensure_ascii=False))\n"
                    "raise SystemExit(0 if overlapped else 9)\n"
                ),
            )
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            client.post("/api/matrix/device/register", json={"deviceId": "phone-b", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "并发读取两台手机屏幕",
                    "mode": "observe",
                    "target": {"deviceIds": ["phone-a", "phone-b"]},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"], timeout=8.0)
            status = client.get("/api/matrix/status").json()

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"]["concurrency"], 2)
        self.assertEqual(
            [item["deviceId"] for item in job["result"]["results"]],
            ["phone-a", "phone-b"],
        )
        self.assertTrue(all(item["success"] for item in job["result"]["results"]))
        self.assertEqual(status["campaigns"][-1]["status"], "succeeded")

    def test_matrix_dispatch_serializes_two_campaigns_targeting_the_same_phone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            active = 0
            max_active = 0
            active_lock = threading.Lock()

            def submit_phone(_ctx, **_plan):
                nonlocal active, max_active
                with active_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.12)
                with active_lock:
                    active -= 1
                return {"success": True}

            with patch("api.routes_matrix._submit_phone_job", side_effect=submit_phone):
                first = client.post(
                    "/api/matrix/dispatch",
                    json={"prompt": "first", "target": {"deviceIds": ["phone-a"]}},
                )
                second = client.post(
                    "/api/matrix/dispatch",
                    json={"prompt": "second", "target": {"deviceIds": ["phone-a"]}},
                )
                first_job = _wait_for_job(client, first.json()["jobId"], timeout=3)
                second_job = _wait_for_job(client, second.json()["jobId"], timeout=3)

            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 202)
            self.assertEqual(first_job["status"], "succeeded")
            self.assertEqual(second_job["status"], "succeeded")
            self.assertEqual(max_active, 1)
            self.assertIsNone(client.get("/api/matrix/devices/phone-a/lease").json()["lease"])

    def test_matrix_pause_stops_active_phone_process_and_preserves_paused_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            started = threading.Event()
            stopped = threading.Event()

            def submit_phone(_ctx, **plan):
                started.set()
                deadline = time.time() + 2
                while time.time() < deadline and not plan["should_cancel"]():
                    time.sleep(0.01)
                stopped.set()
                return {"success": False, "cancelled": True, "errorCode": "cancelled"}

            with patch("api.routes_matrix._submit_phone_job", side_effect=submit_phone):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={"prompt": "hold", "target": {"deviceIds": ["phone-a"]}},
                )
                self.assertTrue(started.wait(5))
                device_task_id = submitted.json()["task"]["missions"][0]["deviceTasks"][0]["deviceTaskId"]
                paused = client.post(f"/api/matrix/tasks/{device_task_id}/pause")
                _wait_for_job(client, submitted.json()["jobId"], timeout=3)

            self.assertEqual(paused.status_code, 200)
            self.assertEqual(paused.json()["deviceTask"]["status"], "paused")
            self.assertTrue(stopped.is_set())
            status = client.get("/api/matrix/status").json()
            persisted = status["campaigns"][-1]["missions"][0]["deviceTasks"][0]
            self.assertEqual(persisted["status"], "paused")
            self.assertEqual(status["devices"][0]["currentTaskId"], "")

    def test_matrix_dispatch_clamps_requested_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)
            device_ids = [f"phone-{index}" for index in range(1, 10)]
            for device_id in device_ids:
                client.post(
                    "/api/matrix/device/register",
                    json={"deviceId": device_id, "online": True},
                )

            submitted = client.post(
                "/api/matrix/dispatch",
                json={
                    "prompt": "读取矩阵设备状态",
                    "mode": "observe",
                    "concurrency": 99,
                    "target": {"deviceIds": device_ids},
                },
            )
            job = _wait_for_job(client, submitted.json()["jobId"], timeout=5.0)

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"]["concurrency"], 8)
        self.assertEqual(len(job["result"]["results"]), 9)

    def test_matrix_dispatch_treats_ok_false_payload_as_failure_even_with_zero_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(
                temp_dir,
                "openclaw-phone-vision.mjs",
                body=(
                    "import json\n"
                    "print(json.dumps({'ok': False, 'errorCode': 'device_offline', "
                    "'error': 'device_offline: invalid token'}, ensure_ascii=False))\n"
                ),
            )
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "读取当前屏幕", "mode": "observe", "target": {"deviceIds": ["phone-a"]}},
            )
            job = _wait_for_job(client, submitted.json()["jobId"])
            persisted = client.get("/api/matrix/status").json()["campaigns"][-1]["missions"][0]["deviceTasks"][0]

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["result"]["results"][0]["error"], "device_offline: invalid token")
        self.assertEqual(job["result"]["errorCode"], "device_offline")
        self.assertEqual(job["result"]["failedDevices"], [{
            "deviceId": "phone-a",
            "deviceTaskId": job["result"]["results"][0]["deviceTaskId"],
            "errorCode": "device_offline",
            "error": "device_offline: invalid token",
        }])
        self.assertEqual(persisted["failureCode"], "device_offline")
        self.assertEqual(persisted["failureReason"], "device_offline: invalid token")

    def test_matrix_cancel_all_route_cancels_every_active_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            from core.phone_matrix import MatrixControlPlane

            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            first = matrix.dispatch(
                {"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-a"]}}
            )
            second = matrix.dispatch(
                {"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-a"]}}
            )

            response = client.post("/api/matrix/cancel", json={"all": True})
            states = {
                item["campaignId"]: item["status"]
                for item in client.get("/api/matrix/status").json()["campaigns"]
            }

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cancelledCount"], 2)
        self.assertEqual(states[first["campaignId"]], "cancelled")
        self.assertEqual(states[second["campaignId"]], "cancelled")

    def test_matrix_cancel_all_never_starts_a_device_waiting_for_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first_started = threading.Event()
            release_first = threading.Event()
            campaign_finished = threading.Event()
            started_devices: list[str] = []

            def submit_phone(_ctx, **plan):
                device_id = str(plan.get("device_id") or "")
                started_devices.append(device_id)
                if device_id == "phone-a":
                    first_started.set()
                    if not release_first.wait(timeout=3):
                        raise AssertionError("first device was not released")
                return {
                    "success": False,
                    "cancelled": True,
                    "errorCode": "cancelled",
                    "error": "cancelled",
                }

            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            client.post("/api/matrix/device/register", json={"deviceId": "phone-b", "online": True})
            with patch("api.routes_matrix._submit_phone_job", side_effect=submit_phone), patch(
                "api.routes_matrix._record_matrix_task_evidence",
                side_effect=lambda *_args, **_kwargs: campaign_finished.set(),
            ):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={
                        "prompt": "read screen",
                        "mode": "observe",
                        "concurrency": 1,
                        "target": {"deviceIds": ["phone-a", "phone-b"]},
                    },
                )
                self.assertTrue(first_started.wait(timeout=3))
                cancelled = client.post("/api/matrix/cancel", json={"all": True})
                release_first.set()
                self.assertTrue(campaign_finished.wait(timeout=3))
                job = client.get(f"/api/jobs/{submitted.json()['jobId']}").json()["job"]
                campaign = client.get("/api/matrix/status").json()["campaigns"][0]

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(started_devices, ["phone-a"])
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(campaign["status"], "cancelled")

    def test_matrix_emergency_stop_rejects_empty_and_mixed_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)

            empty = client.post("/api/matrix/emergency-stop", json={})
            mixed = client.post(
                "/api/matrix/emergency-stop",
                json={"all": True, "deviceIds": ["phone-a"]},
            )
            false_all = client.post("/api/matrix/emergency-stop", json={"all": False})
            non_string_ids = client.post("/api/matrix/emergency-stop", json={"deviceIds": [1, None]})

        self.assertEqual(empty.status_code, 400)
        self.assertEqual(mixed.status_code, 400)
        self.assertEqual(false_all.status_code, 400)
        self.assertEqual(non_string_ids.status_code, 400)

    def test_matrix_emergency_stop_authenticates_before_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from core.phone_matrix import MatrixControlPlane

            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read selected", "target": {"deviceIds": ["phone-a"]}}
            )
            before = matrix.status()["campaigns"]

            def deny(_request):
                return JSONResponse(status_code=401, content={"error": "unauthorized"})

            _app, client = _client(temp_dir, auth_error=deny)
            denied = client.post(
                "/api/matrix/emergency-stop",
                json={"campaignId": task["campaignId"]},
            )
            after = matrix.status()["campaigns"]

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(after, before)

    def test_matrix_emergency_stop_selected_scope_is_idempotent_and_preserves_unrelated_campaigns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            from core.phone_matrix import MatrixControlPlane

            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            selected = matrix.dispatch(
                {"prompt": "read selected", "target": {"deviceIds": ["phone-a"]}}
            )
            unrelated = matrix.dispatch(
                {"prompt": "read unrelated", "target": {"deviceIds": ["phone-b"]}}
            )
            unrelated_status = next(
                item["status"]
                for item in matrix.status()["campaigns"]
                if item["campaignId"] == unrelated["campaignId"]
            )

            first = client.post(
                "/api/matrix/emergency-stop",
                json={"deviceIds": ["phone-a"]},
            )
            second = client.post(
                "/api/matrix/emergency-stop",
                json={"deviceIds": ["phone-a"]},
            )
            states = {
                item["campaignId"]: item["status"]
                for item in client.get("/api/matrix/status").json()["campaigns"]
            }

        payload = first.json()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(payload["schema"], "loom.matrix.emergency_stop.v1")
        self.assertEqual(payload["scope"], "devices")
        self.assertEqual(payload["matchedCampaignIds"], [selected["campaignId"]])
        self.assertEqual(payload["campaignIds"], [selected["campaignId"]])
        self.assertEqual(payload["affectedTaskCount"], 1)
        self.assertEqual(payload["affected"][0]["deviceId"], "phone-a")
        self.assertEqual(states[selected["campaignId"]], "cancelled")
        self.assertEqual(states[unrelated["campaignId"]], unrelated_status)
        self.assertFalse(second.json()["cancelled"])
        self.assertEqual(second.json()["matchedCampaignIds"], [selected["campaignId"]])
        self.assertEqual(second.json()["affected"], [])

    def test_matrix_emergency_stop_cancels_the_matching_running_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executor_started = threading.Event()
            executor_finished = threading.Event()

            def blocked_submit(ctx, **plan):
                try:
                    job_id = str(plan.get("inline_job_id") or "")
                    executor_started.set()
                    deadline = time.time() + 2
                    while time.time() < deadline:
                        if ctx.get_job_mgr().is_cancelled(job_id):
                            return {"success": False, "cancelled": True, "error": "cancelled"}
                        time.sleep(0.01)
                    raise AssertionError("emergency stop did not reach the running phone job")
                finally:
                    executor_finished.set()

            app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})
            with patch("api.routes_matrix._submit_phone_job", side_effect=blocked_submit):
                submitted = client.post(
                    "/api/matrix/dispatch",
                    json={"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}},
                )
                payload = submitted.json()
                self.assertTrue(executor_started.wait(5), "phone job did not enter the running state")

                with patch.object(
                    app.state.job_mgr,
                    "cancel_matching",
                    wraps=app.state.job_mgr.cancel_matching,
                ) as cancel_matching:
                    stopped = client.post(
                        "/api/matrix/emergency-stop",
                        json={"campaignId": payload["task"]["campaignId"]},
                    )
                    self.assertFalse(cancel_matching.call_args.kwargs["wait_for_workers"])
                job = _wait_for_job(client, payload["jobId"])
                self.assertTrue(executor_finished.wait(5), "cancelled phone executor did not exit")

                stale_started = threading.Event()

                def stale_target(stale_job_id: str) -> dict:
                    stale_started.set()
                    deadline = time.time() + 2
                    while time.time() < deadline:
                        if app.state.job_mgr.is_cancelled(stale_job_id):
                            return {"cancelled": True}
                        time.sleep(0.01)
                    raise AssertionError("repeat emergency stop did not cancel the stale job")

                stale_job = app.state.job_mgr.submit_progress(
                    "matrix.retry",
                    "stale matrix retry",
                    stale_target,
                    initial_progress={"campaignId": payload["task"]["campaignId"]},
                )
                self.assertTrue(stale_started.wait(5), "stale job did not enter the running state")
                repeated = client.post(
                    "/api/matrix/emergency-stop",
                    json={"campaignId": payload["task"]["campaignId"]},
                )
                stale_snapshot = _wait_for_job(client, stale_job["id"])

        stop_payload = stopped.json()
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stop_payload["cancelledJobIds"], [payload["jobId"]])
        self.assertEqual(stop_payload["affectedTaskCount"], 1)
        self.assertEqual(job["status"], "cancelled")
        self.assertFalse(repeated.json()["cancelled"])
        self.assertEqual(repeated.json()["campaignIds"], [])
        self.assertEqual(repeated.json()["matchedCampaignIds"], [payload["task"]["campaignId"]])
        self.assertEqual(repeated.json()["cancelledJobIds"], [stale_job["id"]])
        self.assertEqual(stale_snapshot["status"], "cancelled")

    def test_matrix_emergency_stop_device_scope_cancels_only_jobs_fully_inside_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, client = _client(temp_dir)
            from core.phone_matrix import MatrixControlPlane

            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )
            children = {
                child["deviceId"]: child
                for child in task["missions"][0]["deviceTasks"]
            }
            started_a = threading.Event()
            started_b = threading.Event()
            release_b = threading.Event()

            def wait_for_cancel(started: threading.Event, release: threading.Event):
                def target(job_id: str) -> dict:
                    started.set()
                    while not release.wait(0.01):
                        if app.state.job_mgr.is_cancelled(job_id):
                            return {"cancelled": True}
                    return {"success": True}

                return target

            job_a = app.state.job_mgr.submit_progress(
                "matrix.resume",
                "resume phone-a",
                wait_for_cancel(started_a, threading.Event()),
                initial_progress={
                    "campaignId": task["campaignId"],
                    "deviceTaskId": children["phone-a"]["deviceTaskId"],
                    "deviceId": "phone-a",
                    "matrixDeviceTaskIds": [children["phone-a"]["deviceTaskId"]],
                    "matrixDeviceIds": ["phone-a"],
                },
            )
            job_b = app.state.job_mgr.submit_progress(
                "matrix.resume",
                "resume phone-b",
                wait_for_cancel(started_b, release_b),
                initial_progress={
                    "campaignId": task["campaignId"],
                    "deviceTaskId": children["phone-b"]["deviceTaskId"],
                    "deviceId": "phone-b",
                    "matrixDeviceTaskIds": [children["phone-b"]["deviceTaskId"]],
                    "matrixDeviceIds": ["phone-b"],
                },
            )
            self.assertTrue(started_a.wait(5))
            self.assertTrue(started_b.wait(5))

            stopped = client.post(
                "/api/matrix/emergency-stop",
                json={"deviceIds": ["phone-a"]},
            )
            snapshot_a = _wait_for_job(client, job_a["id"])
            snapshot_b = app.state.job_mgr.get(job_b["id"])
            stale_started = threading.Event()
            stale_job = app.state.job_mgr.submit_progress(
                "matrix.resume",
                "stale resume phone-a",
                wait_for_cancel(stale_started, threading.Event()),
                initial_progress={
                    "campaignId": task["campaignId"],
                    "deviceTaskId": children["phone-a"]["deviceTaskId"],
                    "deviceId": "phone-a",
                    "matrixDeviceTaskIds": [children["phone-a"]["deviceTaskId"]],
                    "matrixDeviceIds": ["phone-a"],
                },
            )
            self.assertTrue(stale_started.wait(5))
            repeated = client.post(
                "/api/matrix/emergency-stop",
                json={"deviceTaskIds": [children["phone-a"]["deviceTaskId"]]},
            )
            stale_snapshot = _wait_for_job(client, stale_job["id"])
            sibling_after_repeat = app.state.job_mgr.get(job_b["id"])
            campaign = matrix.status()["campaigns"][0]
            release_b.set()
            _wait_for_job(client, job_b["id"])

        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["cancelledJobIds"], [job_a["id"]])
        self.assertEqual(snapshot_a["status"], "cancelled")
        self.assertEqual(snapshot_b["status"], "running")
        self.assertFalse(repeated.json()["cancelled"])
        self.assertEqual(repeated.json()["cancelledJobIds"], [stale_job["id"]])
        self.assertEqual(stale_snapshot["status"], "cancelled")
        self.assertEqual(sibling_after_repeat["status"], "running")
        self.assertEqual(states, {"phone-a": "cancelled", "phone-b": "queued"})

    def test_matrix_emergency_stop_device_scope_can_explicitly_request_campaign_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            from core.phone_matrix import MatrixControlPlane

            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )

            stopped = client.post(
                "/api/matrix/emergency-stop",
                json={"deviceIds": ["phone-a"], "campaignAtomic": True},
            )
            campaign = matrix.status()["campaigns"][0]

        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(stopped.status_code, 200)
        self.assertTrue(stopped.json()["campaignAtomic"])
        self.assertEqual(stopped.json()["matchedCampaignIds"], [task["campaignId"]])
        self.assertEqual(states, {"phone-a": "cancelled", "phone-b": "cancelled"})

    def test_matrix_template_run_executes_and_returns_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "online": True})

            submitted = client.post(
                "/api/matrix/template/run",
                json={"template": "screen-summary", "target": {"deviceIds": ["phone-a"]}},
            )
            job = _wait_for_job(client, submitted.json()["jobId"])

        self.assertEqual(submitted.status_code, 202)
        self.assertEqual(job["status"], "succeeded")
        self.assertTrue(job["result"]["success"])

    def test_matrix_dispatch_safety_gate_returns_product_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs")
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "group": "demo", "online": True})

            response = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "批量私信所有客户", "target": {"groups": ["demo"]}},
            )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "safety_confirmation_required")
            self.assertIn("确认", response.json()["error"])

    def test_matrix_dispatch_rejects_offline_target_before_queueing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-offline", "online": False})

            response = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-offline"]}},
            )
            if response.status_code == 202:
                _wait_for_job(client, response.json()["jobId"])

            jobs = client.get("/api/jobs/list?limit=10").json()["jobs"]

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "matrix_no_online_devices")
        self.assertEqual(jobs, [])

    def test_matrix_leads_route_records_redacted_local_lead(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)

            recorded = client.post(
                "/api/matrix/leads",
                json={
                    "summary": "用户询问套餐 13800000000 Bearer secret-token",
                    "deviceId": "phone-a",
                    "campaignId": "campaign_123",
                    "tags": ["演示"],
                    "token": "secret-token",
                },
            )
            listed = client.get("/api/matrix/leads?limit=5")

        self.assertEqual(recorded.status_code, 200)
        payload = recorded.json()
        serialized = json.dumps({"recorded": payload, "listed": listed.json()}, ensure_ascii=False)
        self.assertTrue(payload["lead"]["leadId"].startswith("lead_"))
        self.assertEqual(listed.json()["leads"][0]["deviceId"], "phone-a")
        self.assertNotIn("13800000000", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_matrix_retry_route_dispatches_failed_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _write_script(temp_dir, "openclaw-phone-vision.mjs", return_code=1)
            _app, client = _client(temp_dir)
            client.post("/api/matrix/device/register", json={"deviceId": "phone-a", "group": "demo", "online": True})
            submitted = client.post(
                "/api/matrix/dispatch",
                json={"prompt": "读取当前屏幕", "mode": "observe", "target": {"deviceIds": ["phone-a"]}},
            )
            campaign_id = submitted.json()["task"]["campaignId"]
            _wait_for_job(client, submitted.json()["jobId"])

            _write_script(temp_dir, "openclaw-phone-vision.mjs", return_code=0)
            retried = client.post("/api/matrix/retry", json={"campaignId": campaign_id})
            retry_job = _wait_for_job(client, retried.json()["jobId"])

        self.assertEqual(retried.status_code, 202)
        self.assertEqual(retry_job["status"], "succeeded")
        retry_payload = retried.json()
        self.assertTrue(retry_payload["retry"]["retried"])
        self.assertEqual(retry_payload["retry"]["retryOf"], campaign_id)
        self.assertTrue(retry_payload["retry"]["task"]["campaignId"].startswith("campaign_"))


def _write_script(base_path: str, name: str, *, return_code: int = 0, body: str = "") -> None:
    scripts_dir = os.path.join(base_path, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(os.path.join(scripts_dir, name), "w", encoding="utf-8") as handle:
        handle.write(body or (
            "import json, sys\n"
            "print(json.dumps({'argv': sys.argv[1:], 'ok': True}, ensure_ascii=False))\n"
            f"raise SystemExit({return_code})\n"
        ))


def _client(
    base_path: str,
    state_path: str | None = None,
    *,
    auth_error=None,
) -> tuple[FastAPI, TestClient]:
    logs: list[str] = []
    job_mgr = JobManager(logs.append, state_path=state_path)
    app = FastAPI()
    ctx = _context(base_path, job_mgr, logs)
    issuer = StreamTicketIssuer()
    ctx.stream_ticket_issuer = issuer
    app.state.job_mgr = job_mgr
    app.state.stream_ticket_issuer = issuer
    if auth_error is not None:
        ctx.auth_error = auth_error
    register_matrix_routes(app, ctx)
    register_job_routes(app, ctx)
    return app, TestClient(app)


def _context(base_path: str, job_mgr: JobManager, logs: list[str]) -> SimpleNamespace:
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
        append_log=logs.append,
        auth_error=lambda _request: None,
        body=body,
        fastapi_json=fastapi_json,
        get_job_mgr=lambda: job_mgr,
        paths=SimpleNamespace(base_path=base_path, launcher_dir=base_path, node_exe=sys.executable),
        sanitize_text=lambda text: text,
    )


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        if response.status_code == 200:
            job = response.json()["job"]
            if job.get("status") in {"succeeded", "failed", "cancelled"}:
                return job
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {job_id}")


def _wait_for_matrix_event(base_path: str, needle: str, timeout: float = 1.0) -> dict:
    path = os.path.join(base_path, "matrix-events.jsonl")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if needle in str(event.get("message") or ""):
                        return event
        time.sleep(0.02)
    raise AssertionError(f"matrix event containing {needle!r} was not written")


if __name__ == "__main__":
    unittest.main()
