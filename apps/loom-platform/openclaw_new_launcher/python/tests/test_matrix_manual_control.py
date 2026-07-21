from __future__ import annotations

import asyncio
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

from api.routes_matrix import register_matrix_routes
from core.phone_matrix import MatrixControlPlane, MatrixTargetError
from services.jobs import JobManager


class MatrixManualControlTests(unittest.TestCase):
    def test_manual_control_does_not_block_the_async_route_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, _client_instance = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            endpoint = next(
                route.endpoint
                for route in app.routes
                if getattr(route, "path", "") == "/api/matrix/devices/{device_id}/control"
            )

            class Request:
                async def json(self):
                    return {
                        "leaseId": lease["leaseId"],
                        "action": "home",
                        "clientCommandId": "cmd-async",
                    }

            def slow_action(_ctx, _device_id: str, command: dict) -> dict:
                time.sleep(0.15)
                return {"status": "applied", "commandId": command["clientCommandId"]}

            async def exercise() -> float:
                started = time.monotonic()
                response_task = asyncio.create_task(endpoint("phone-a", Request()))
                await asyncio.sleep(0.02)
                loop_delay = time.monotonic() - started
                await response_task
                return loop_delay

            with patch("api.routes_matrix._execute_matrix_manual_action", side_effect=slow_action):
                loop_delay = asyncio.run(exercise())

        self.assertLess(loop_delay, 0.08)

    def test_manual_control_requires_valid_lease_and_normalized_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            missing = client.post(
                "/api/matrix/devices/phone-a/control",
                json={"leaseId": "lease-missing", "action": "tap", "x": 0.5, "y": 0.5, "clientCommandId": "cmd-1"},
            )
            lease = client.post(
                "/api/matrix/devices/phone-a/lease",
                json={"holderType": "human", "holderId": "operator-1"},
            ).json()["lease"]
            invalid = client.post(
                "/api/matrix/devices/phone-a/control",
                json={"leaseId": lease["leaseId"], "action": "tap", "x": 1.01, "y": 0.5, "clientCommandId": "cmd-2"},
            )

        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.json()["code"], "device_lease_conflict")
        self.assertEqual(invalid.status_code, 400)

    def test_manual_control_rejects_an_agent_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": "run-1"}
            )

            with patch(
                "api.routes_matrix._execute_matrix_manual_action",
                return_value={"status": "applied", "commandId": "cmd-agent"},
            ) as execute:
                response = client.post(
                    "/api/matrix/devices/phone-a/control",
                    json={
                        "leaseId": lease["leaseId"],
                        "action": "home",
                        "clientCommandId": "cmd-agent",
                    },
                )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "device_lease_conflict")
        execute.assert_not_called()

    def test_manual_control_revalidates_lease_after_waiting_for_device_lock(self) -> None:
        from api.routes_matrix import _matrix_device_execution_lock

        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            execution_lock = _matrix_device_execution_lock("phone-a")
            response: dict = {}

            def send_control() -> None:
                response["value"] = client.post(
                    "/api/matrix/devices/phone-a/control",
                    json={
                        "leaseId": lease["leaseId"],
                        "action": "home",
                        "clientCommandId": "cmd-queued",
                    },
                )

            execution_lock.acquire()
            thread = threading.Thread(target=send_control)
            try:
                with patch(
                    "api.routes_matrix._execute_matrix_manual_action",
                    return_value={"status": "applied", "commandId": "cmd-queued"},
                ) as execute:
                    thread.start()
                    time.sleep(0.05)
                    with open(matrix.leases_path, "r", encoding="utf-8") as handle:
                        state = json.load(handle)
                    state["leases"][0]["expiresAt"] = "2000-01-01T00:00:00Z"
                    with open(matrix.leases_path, "w", encoding="utf-8") as handle:
                        json.dump(state, handle)
                    execution_lock.release()
                    thread.join(timeout=2)
            finally:
                if execution_lock._is_owned():
                    execution_lock.release()
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(response["value"].status_code, 409)
        self.assertEqual(response["value"].json()["code"], "device_lease_conflict")
        execute.assert_not_called()

    def test_manual_control_revalidates_lease_immediately_before_side_effect(self) -> None:
        original_begin = MatrixControlPlane.begin_control_command

        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )

            def expire_after_claim(instance, *args, **kwargs):
                claim = original_begin(instance, *args, **kwargs)
                with open(instance.leases_path, "r", encoding="utf-8") as handle:
                    state = json.load(handle)
                state["leases"][0]["expiresAt"] = "2000-01-01T00:00:00Z"
                with open(instance.leases_path, "w", encoding="utf-8") as handle:
                    json.dump(state, handle)
                return claim

            with patch.object(
                MatrixControlPlane,
                "begin_control_command",
                autospec=True,
                side_effect=expire_after_claim,
            ), patch(
                "api.routes_matrix._execute_matrix_manual_action",
                return_value={"status": "applied", "commandId": "cmd-expired-after-claim"},
            ) as execute:
                response = client.post(
                    "/api/matrix/devices/phone-a/control",
                    json={
                        "leaseId": lease["leaseId"],
                        "action": "home",
                        "clientCommandId": "cmd-expired-after-claim",
                    },
                )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "device_lease_conflict")
        execute.assert_not_called()

    def test_idempotent_manual_command_is_bound_to_the_original_human_holder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            command = {
                "leaseId": lease["leaseId"],
                "action": "home",
                "clientCommandId": "cmd-holder-bound",
            }
            with patch(
                "api.routes_matrix._execute_matrix_manual_action",
                return_value={"status": "applied", "commandId": "cmd-holder-bound"},
            ) as execute:
                first = client.post("/api/matrix/devices/phone-a/control", json=command)
                with open(matrix.leases_path, "r", encoding="utf-8") as handle:
                    state = json.load(handle)
                state["leases"][0]["holderId"] = "operator-2"
                with open(matrix.leases_path, "w", encoding="utf-8") as handle:
                    json.dump(state, handle)
                replay = client.post("/api/matrix/devices/phone-a/control", json=command)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["code"], "device_lease_conflict")
        execute.assert_called_once()

    def test_manual_control_fails_closed_when_lease_ledger_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            with open(matrix.leases_path, "w", encoding="utf-8") as handle:
                handle.write("{corrupt")

            with patch(
                "api.routes_matrix._execute_matrix_manual_action",
                return_value={"status": "applied", "commandId": "cmd-corrupt-ledger"},
            ) as execute:
                response = client.post(
                    "/api/matrix/devices/phone-a/control",
                    json={
                        "leaseId": lease["leaseId"],
                        "action": "home",
                        "clientCommandId": "cmd-corrupt-ledger",
                    },
                )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "matrix_lease_ledger_unavailable")
        execute.assert_not_called()

    def test_client_command_id_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            lease = matrix.acquire_lease(
                "phone-a", {"holderType": "human", "holderId": "operator-1"}
            )
            command = {
                "leaseId": lease["leaseId"],
                "action": "swipe",
                "x": 0.5,
                "y": 0.8,
                "endX": 0.5,
                "endY": 0.2,
                "durationMs": 300,
                "clientCommandId": "cmd-same",
            }
            applied = {"status": "applied", "commandId": "cmd-same", "result": {"success": True}}
            with patch(
                "api.routes_matrix._execute_matrix_manual_action",
                return_value=applied,
                create=True,
            ) as execute:
                first = client.post("/api/matrix/devices/phone-a/control", json=command)
                second = client.post("/api/matrix/devices/phone-a/control", json=command)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        execute.assert_called_once()

    def test_normalized_swipe_is_translated_to_phone_normalized_points(self) -> None:
        from api.routes_matrix import _execute_matrix_manual_action

        captured: dict = {}

        def build_plan(_ctx, body, *, device_id):
            captured["body"] = body
            captured["deviceId"] = device_id
            return {"kind": "phone.task"}

        ctx = SimpleNamespace()
        command = {
            "leaseId": "lease-1",
            "clientCommandId": "cmd-1",
            "action": "swipe",
            "x": 0.5,
            "y": 0.8,
            "endX": 0.5,
            "endY": 0.2,
            "durationMs": 300,
        }
        with patch("api.routes_matrix._build_phone_task_plan", side_effect=build_plan), patch(
            "api.routes_matrix._submit_phone_job",
            return_value={"success": True},
        ):
            result = _execute_matrix_manual_action(ctx, "phone-a", command)

        action_body = captured["body"]["actionBody"]
        self.assertEqual(captured["deviceId"], "phone-a")
        self.assertEqual(action_body["start"], {"nx": 0.5, "ny": 0.8})
        self.assertEqual(action_body["end"], {"nx": 0.5, "ny": 0.2})
        self.assertNotIn("x", action_body)
        self.assertEqual(result["status"], "applied")

    def test_pause_resume_preserve_identifiers_and_reject_terminal_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch({"prompt": "read", "target": {"deviceIds": ["phone-a"]}})
            campaign_id = task["campaignId"]
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]

            paused = client.post(f"/api/matrix/tasks/{device_task_id}/pause")
            with patch("api.routes_matrix._submit_phone_job", return_value={"success": True}):
                resumed = client.post(f"/api/matrix/tasks/{device_task_id}/resume")
                deadline = time.time() + 1
                while time.time() < deadline and matrix.task_status(device_task_id) != "succeeded":
                    time.sleep(0.01)
            matrix.record_result(device_task_id, ok=True, duration_ms=10)
            terminal = client.post(f"/api/matrix/tasks/{device_task_id}/pause")

        self.assertEqual(paused.status_code, 200)
        self.assertEqual(paused.json()["deviceTask"]["deviceTaskId"], device_task_id)
        self.assertEqual(paused.json()["campaign"]["campaignId"], campaign_id)
        self.assertEqual(paused.json()["deviceTask"]["status"], "paused")
        self.assertEqual(resumed.json()["deviceTask"]["status"], "queued")
        self.assertEqual(terminal.status_code, 409)
        self.assertEqual(terminal.json()["code"], "matrix_invalid_task_transition")

    def test_takeover_atomically_pauses_the_bound_agent_task_and_swaps_its_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch({"prompt": "read", "target": {"deviceIds": ["phone-a"]}})
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            agent_lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": device_task_id}
            )
            matrix.start_task(device_task_id)

            takeover = client.post(
                "/api/matrix/devices/phone-a/lease",
                json={
                    "holderType": "human",
                    "holderId": "operator-1",
                    "leaseId": agent_lease["leaseId"],
                    "deviceTaskId": device_task_id,
                },
            )

        self.assertEqual(takeover.status_code, 200)
        self.assertEqual(takeover.json()["lease"]["holderType"], "human")
        self.assertEqual(takeover.json()["lease"]["pausedDeviceTaskId"], device_task_id)
        self.assertEqual(takeover.json()["deviceTask"]["status"], "paused")

    def test_takeover_rejects_a_stale_task_lease_pair_without_pausing_either_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            first = matrix.dispatch({"prompt": "first", "target": {"deviceIds": ["phone-a"]}})
            second = matrix.dispatch({"prompt": "second", "target": {"deviceIds": ["phone-a"]}})
            first_task_id = first["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            second_task_id = second["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            active_lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": second_task_id}
            )
            matrix.start_task(second_task_id)

            takeover = client.post(
                "/api/matrix/devices/phone-a/lease",
                json={
                    "holderType": "human",
                    "holderId": "operator-1",
                    "leaseId": active_lease["leaseId"],
                    "deviceTaskId": first_task_id,
                },
            )
            first_status = matrix.task_status(first_task_id)
            second_status = matrix.task_status(second_task_id)
            retained_lease = matrix.get_lease("phone-a")["lease"]

        self.assertEqual(takeover.status_code, 409)
        self.assertEqual(takeover.json()["code"], "device_lease_conflict")
        self.assertEqual(first_status, "queued")
        self.assertEqual(second_status, "running")
        self.assertEqual(retained_lease["leaseId"], active_lease["leaseId"])

    def test_failed_takeover_lease_write_does_not_leave_the_agent_task_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch({"prompt": "read", "target": {"deviceIds": ["phone-a"]}})
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            agent_lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": device_task_id}
            )
            matrix.start_task(device_task_id)

            original_write_leases = MatrixControlPlane._write_leases

            def reject_human_lease(instance, state):
                if any(item.get("holderType") == "human" for item in state.get("leases", [])):
                    raise MatrixTargetError("device_lease_conflict", "simulated lease acquisition failure")
                return original_write_leases(instance, state)

            with patch.object(MatrixControlPlane, "_write_leases", autospec=True, side_effect=reject_human_lease):
                takeover = client.post(
                    "/api/matrix/devices/phone-a/lease",
                    json={
                        "holderType": "human",
                        "holderId": "operator-1",
                        "leaseId": agent_lease["leaseId"],
                        "deviceTaskId": device_task_id,
                    },
                )
            task_status = matrix.task_status(device_task_id)
            retained_lease = matrix.get_lease("phone-a")["lease"]

        self.assertEqual(takeover.status_code, 409)
        self.assertEqual(task_status, "running")
        self.assertEqual(retained_lease["leaseId"], agent_lease["leaseId"])

    def test_pause_with_a_stale_lease_does_not_pause_the_task_or_release_the_active_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            first = matrix.dispatch({"prompt": "first", "target": {"deviceIds": ["phone-a"]}})
            second = matrix.dispatch({"prompt": "second", "target": {"deviceIds": ["phone-a"]}})
            first_task_id = first["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            second_task_id = second["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            active_lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": second_task_id}
            )

            paused = client.post(
                f"/api/matrix/tasks/{first_task_id}/pause",
                json={"leaseId": active_lease["leaseId"]},
            )
            first_status = matrix.task_status(first_task_id)
            retained_lease = matrix.get_lease("phone-a")["lease"]

        self.assertEqual(paused.status_code, 409)
        self.assertEqual(paused.json()["code"], "device_lease_conflict")
        self.assertEqual(first_status, "queued")
        self.assertEqual(retained_lease["holderId"], second_task_id)

    def test_releasing_human_takeover_resumes_only_the_task_bound_to_that_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _app, client = _client(temp_dir)
            matrix = MatrixControlPlane(SimpleNamespace(launcher_dir=temp_dir, wire_path=""))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            first = matrix.dispatch({"prompt": "first", "target": {"deviceIds": ["phone-a"]}})
            first_task_id = first["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            agent_lease = matrix.acquire_lease(
                "phone-a", {"holderType": "agent", "holderId": first_task_id}
            )
            matrix.start_task(first_task_id)
            takeover = client.post(
                "/api/matrix/devices/phone-a/lease",
                json={
                    "holderType": "human",
                    "holderId": "operator-1",
                    "leaseId": agent_lease["leaseId"],
                    "deviceTaskId": first_task_id,
                },
            )
            self.assertEqual(takeover.status_code, 200, takeover.json())
            human_lease = takeover.json()["lease"]
            second = matrix.dispatch({"prompt": "second", "target": {"deviceIds": ["phone-a"]}})
            second_task_id = second["missions"][0]["deviceTasks"][0]["deviceTaskId"]

            with patch("api.routes_matrix._submit_phone_job", return_value={"success": True}):
                released = client.request(
                    "DELETE",
                    "/api/matrix/devices/phone-a/lease",
                    json={"leaseId": human_lease["leaseId"]},
                )
                deadline = time.time() + 1
                while time.time() < deadline and matrix.task_status(first_task_id) != "succeeded":
                    time.sleep(0.01)
            first_status = matrix.task_status(first_task_id)
            second_status = matrix.task_status(second_task_id)

        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["resumedDeviceTaskId"], first_task_id)
        self.assertTrue(released.json()["jobId"])
        self.assertEqual(first_status, "succeeded")
        self.assertEqual(second_status, "queued")


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
    )
    register_matrix_routes(app, ctx)
    return app, TestClient(app)


if __name__ == "__main__":
    unittest.main()
