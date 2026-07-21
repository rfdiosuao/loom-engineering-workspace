from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from python.tools.virtual_phone_fleet import VirtualPhoneFleet


def _request(device, method: str, path: str, body: dict | None = None, *, token: str | None = None):
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{device.base_url}{path}",
        data=encoded,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "X-AGENT-PHONE-TOKEN": device.token if token is None else token,
        },
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class VirtualPhoneFleetContractTests(unittest.TestCase):
    def test_context_manager_serves_authenticated_apkclaw_status_and_pairing(self) -> None:
        with VirtualPhoneFleet(device_count=2, seed=17) as fleet:
            first, second = fleet.devices
            self.assertEqual(first.device_id, "virtual-phone-001")
            self.assertEqual(second.device_id, "virtual-phone-002")
            self.assertTrue(first.base_url.startswith("http://127.0.0.1:"))
            self.assertTrue(first.token.startswith("vf-test-only-"))
            self.assertNotEqual(first.base_url, second.base_url)

            status, payload = _request(first, "GET", "/api/device/status")
            self.assertEqual(status, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["data"]["deviceId"], first.device_id)
            self.assertTrue(payload["data"]["screenshotSupported"])

            status, payload = _request(first, "GET", "/api/device/status", token="wrong")
            self.assertEqual(status, 401)
            self.assertEqual(payload["errorCode"], "unauthorized")

            status, payload = _request(
                first,
                "POST",
                "/api/lumi/security/pair",
                {"launcherId": "loom-test-launcher", "launcherName": "test"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["data"]["launcherId"], "loom-test-launcher")
            self.assertTrue(payload["data"]["launcherSecret"].startswith("vf-pair-test-only-"))

            public_manifest = json.dumps(fleet.public_manifest())
            self.assertNotIn(first.token, public_manifest)
            self.assertNotIn("launcherSecret", public_manifest)

    def test_screenshot_hash_read_and_control_responses_are_deterministic(self) -> None:
        with VirtualPhoneFleet(device_count=1, seed=23) as fleet:
            device = fleet.devices[0]
            status, first = _request(device, "GET", "/api/tool/screenshot")
            self.assertEqual(status, 200)
            frame = first["data"]
            self.assertEqual(frame["mime"], "image/png")
            self.assertGreater(len(frame["base64"]), 40)
            self.assertEqual(len(frame["screenHash"]), 64)

            query = urlencode({"knownHash": frame["screenHash"]})
            status, unchanged = _request(device, "GET", f"/api/tool/screenshot?{query}")
            self.assertEqual(status, 200)
            self.assertTrue(unchanged["data"]["notModified"])
            self.assertNotIn("base64", unchanged["data"])

            status, read = _request(device, "GET", "/api/tool/get_screen_info")
            self.assertEqual(status, 200)
            self.assertEqual(read["data"]["packageName"], "com.loom.virtualphone")

            status, control = _request(device, "POST", "/api/tool/tap", {"x": 120, "y": 240})
            self.assertEqual(status, 200)
            self.assertEqual(control["data"]["action"], "tap")
            self.assertTrue(control["data"]["changed"])
            self.assertNotEqual(control["data"]["beforeHash"], control["data"]["afterHash"])

            _, after = _request(device, "GET", "/api/tool/screenshot")
            self.assertEqual(after["data"]["screenHash"], control["data"]["afterHash"])

    def test_tasks_emit_ordered_events_progress_completion_and_cancellation(self) -> None:
        with VirtualPhoneFleet(device_count=1, seed=31) as fleet:
            device = fleet.devices[0]
            status, submitted = _request(
                device,
                "POST",
                "/api/lumi/agent/tasks",
                {"prompt": "Open settings", "tool_policy": "safe_action"},
            )
            self.assertEqual(status, 202)
            task_id = submitted["data"]["taskId"]

            snapshots = []
            for _ in range(4):
                _, payload = _request(device, "GET", f"/api/lumi/agent/tasks/{task_id}")
                snapshots.append(payload["data"])
            self.assertEqual([item["progress"] for item in snapshots], [20, 55, 85, 100])
            self.assertEqual(snapshots[-1]["status"], "success")

            _, event_payload = _request(device, "GET", f"/api/lumi/agent/tasks/{task_id}/events?afterSeq=1")
            events = event_payload["data"]["events"]
            self.assertTrue(events)
            self.assertTrue(all(event["seq"] > 1 for event in events))
            self.assertEqual([event["seq"] for event in events], sorted(event["seq"] for event in events))
            self.assertEqual(events[-1]["type"], "task_completed")

            fleet.set_scenario(device.device_id, "reconnect", failures_before_reconnect=1)
            disconnected = _request(device, "GET", f"/api/lumi/agent/tasks/{task_id}/events?afterSeq=1")
            replayed = _request(device, "GET", f"/api/lumi/agent/tasks/{task_id}/events?afterSeq=1")
            self.assertEqual(disconnected[0], 503)
            self.assertEqual(replayed[0], 200)
            self.assertEqual(replayed[1]["data"]["events"], events)

            fleet.set_scenario(device.device_id, "normal")

            _, next_task = _request(device, "POST", "/api/lumi/agent/tasks", {"prompt": "Wait"})
            next_id = next_task["data"]["taskId"]
            status, cancelled = _request(device, "POST", f"/api/lumi/agent/tasks/{next_id}/cancel", {})
            self.assertEqual(status, 200)
            self.assertEqual(cancelled["data"]["status"], "cancelled")

    def test_latency_offline_failure_no_progress_and_reconnect_scenarios(self) -> None:
        with VirtualPhoneFleet(device_count=5, seed=41) as fleet:
            latency, offline, failure, no_progress, reconnect = fleet.devices
            fleet.set_scenario(latency.device_id, "latency", latency_ms=35)
            started = time.monotonic()
            status, _ = _request(latency, "GET", "/api/device/status")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(time.monotonic() - started, 0.025)

            fleet.set_scenario(offline.device_id, "offline")
            status, payload = _request(offline, "GET", "/api/device/status")
            self.assertEqual(status, 503)
            self.assertEqual(payload["errorCode"], "device_offline")

            fleet.set_scenario(failure.device_id, "failure")
            _, created = _request(failure, "POST", "/api/lumi/agent/tasks", {"prompt": "Fail deterministically"})
            failure_id = created["data"]["taskId"]
            failure_snapshots = [
                _request(failure, "GET", f"/api/lumi/agent/tasks/{failure_id}")[1]["data"]
                for _ in range(3)
            ]
            self.assertEqual(failure_snapshots[-1]["status"], "error")
            self.assertEqual(failure_snapshots[-1]["errorCode"], "simulated_task_failure")

            fleet.set_scenario(no_progress.device_id, "no_progress")
            _, created = _request(no_progress, "POST", "/api/lumi/agent/tasks", {"prompt": "Stay running"})
            stalled_id = created["data"]["taskId"]
            stalled = [
                _request(no_progress, "GET", f"/api/lumi/agent/tasks/{stalled_id}")[1]["data"]
                for _ in range(4)
            ]
            self.assertEqual({item["progress"] for item in stalled}, {20})
            self.assertEqual({item["status"] for item in stalled}, {"running"})

            fleet.set_scenario(reconnect.device_id, "reconnect", failures_before_reconnect=2)
            first = _request(reconnect, "GET", "/api/device/status")
            second = _request(reconnect, "GET", "/api/device/status")
            third = _request(reconnect, "GET", "/api/device/status")
            self.assertEqual([first[0], second[0], third[0]], [503, 503, 200])
            self.assertEqual(third[1]["data"]["connectionState"], "reconnected")

    def test_legacy_execute_task_returns_a_running_snapshot_when_progress_is_stalled(self) -> None:
        with VirtualPhoneFleet(device_count=1, seed=43) as fleet:
            device = fleet.devices[0]
            fleet.set_scenario(device.device_id, "no_progress")

            status, payload = _request(
                device,
                "POST",
                "/api/lumi/agent/execute_task",
                {"prompt": "Remain stalled for recovery testing"},
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["data"]["status"], "running")
            self.assertEqual(payload["data"]["progress"], 20)


class VirtualPhoneFleetScaleTests(unittest.TestCase):
    def test_100_devices_start_with_stable_identities_bounded_resources_and_clean_shutdown(self) -> None:
        baseline_threads = {thread.ident for thread in threading.enumerate()}
        expected_identities = VirtualPhoneFleet(device_count=100, seed=101).identities()
        fleet = VirtualPhoneFleet(device_count=100, seed=101, max_concurrency=12)

        with fleet:
            self.assertEqual(fleet.identities(), expected_identities)
            self.assertEqual(len({device.device_id for device in fleet.devices}), 100)
            self.assertEqual(len({device.base_url for device in fleet.devices}), 100)

            with ThreadPoolExecutor(max_workers=32) as executor:
                statuses = list(executor.map(lambda item: _request(item, "GET", "/api/device/status"), fleet.devices))
            self.assertTrue(all(status == 200 for status, _ in statuses))

            before_hashes = {payload["data"]["deviceId"]: payload["data"]["screenHash"] for _, payload in statuses}
            with ThreadPoolExecutor(max_workers=32) as executor:
                controls = list(
                    executor.map(
                        lambda item: _request(item, "POST", "/api/tool/system_key", {"key": "HOME"}),
                        fleet.devices,
                    )
                )
            self.assertTrue(all(status == 200 for status, _ in controls))
            self.assertTrue(
                all(payload["data"]["afterHash"] != before_hashes[device.device_id] for device, (_, payload) in zip(fleet.devices, controls))
            )

            resources = fleet.resource_snapshot()
            self.assertEqual(resources["deviceCount"], 100)
            self.assertEqual(resources["serviceThreads"], 1)
            self.assertLessEqual(resources["peakConcurrentRequests"], 12)
            self.assertLessEqual(resources["cachedScreenshotBytes"], 100 * 1024)
            self.assertLessEqual(resources["eventsPerDeviceLimit"], 128)
            self.assertLessEqual(resources["tasksPerDeviceLimit"], 32)

            urls = [device.base_url for device in fleet.devices]

        self.assertFalse(fleet.running)
        self.assertFalse(fleet.service_thread_alive)
        remaining_new_threads = [
            thread for thread in threading.enumerate() if thread.ident not in baseline_threads and thread.is_alive()
        ]
        self.assertEqual(remaining_new_threads, [])
        with self.assertRaises(URLError):
            urlopen(f"{urls[0]}/api/device/status", timeout=0.2)


if __name__ == "__main__":
    unittest.main()
