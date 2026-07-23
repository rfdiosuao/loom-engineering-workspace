from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


def _register_matrix_devices_from_process(base_path: str, prefix: str, count: int) -> list[str]:
    from core.paths import AppPaths
    from core.phone_matrix import MatrixControlPlane

    matrix = MatrixControlPlane(AppPaths(base_path=base_path))
    device_ids = []
    for index in range(count):
        device_id = f"{prefix}-{index}"
        matrix.register_device({"deviceId": device_id, "online": True})
        device_ids.append(device_id)
    return device_ids


class MatrixControlPlaneTests(unittest.TestCase):
    def test_matrix_workbench_contains_phone_app_download_entry(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        page_path = os.path.join(repo_root, "src", "components", "matrix", "MatrixTaskDrawer.tsx")
        with open(page_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("PHONE_AGENT_APK_URL", source)
        self.assertIn("PHONE_AGENT_QR_SRC", source)
        self.assertIn("data-matrix-phone-app-download", source)
        self.assertIn("phone-agent-apk-qr.svg", source)
        self.assertIn("手机端 App", source)

    def test_matrix_workbench_uses_authenticated_realtime_stream_for_live_updates(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        stream_path = os.path.join(repo_root, "src", "components", "matrix", "useMatrixStream.ts")
        api_path = os.path.join(repo_root, "src", "services", "api.ts")
        with open(stream_path, "r", encoding="utf-8") as handle:
            stream = handle.read()
        with open(api_path, "r", encoding="utf-8") as handle:
            api = handle.read()

        self.assertIn("openRealtimeStream", stream)
        self.assertIn("topic: 'matrix'", stream)
        self.assertNotIn("new EventSource", stream)
        self.assertIn("issueTicket", api)
        self.assertIn("/api/matrix/events/stream", api)

    def test_matrix_workbench_hides_agent_prompt_and_uses_cn_task_labels(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        page_path = os.path.join(repo_root, "src", "components", "matrix", "MatrixWorkbenchPage.tsx")
        drawer_path = os.path.join(repo_root, "src", "components", "matrix", "MatrixTaskDrawer.tsx")
        with open(page_path, "r", encoding="utf-8") as handle:
            page = handle.read()
        with open(drawer_path, "r", encoding="utf-8") as handle:
            drawer = handle.read()
        source = page + drawer

        self.assertNotIn("CONTROL_PROMPT", source)
        self.assertNotIn("复制提示词", source)
        self.assertNotIn("CODEX CONTROL", source)
        self.assertIn("data-matrix-task-drawer", drawer)
        for label in ["只读观察", "安全控制", "完整控制", "快速", "标准", "深度"]:
            self.assertIn(label, source)
        self.assertIn("grid-cols-[132px_minmax(320px,1fr)_300px]", page)

    def test_matrix_workbench_has_bounded_realtime_events_and_screens(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        stream_path = os.path.join(repo_root, "src", "components", "matrix", "useMatrixStream.ts")
        scheduler_path = os.path.join(repo_root, "src", "components", "matrix", "screenScheduler.ts")
        screens_path = os.path.join(repo_root, "src", "components", "matrix", "useVisibleScreens.ts")
        with open(stream_path, "r", encoding="utf-8") as handle:
            stream = handle.read()
        with open(scheduler_path, "r", encoding="utf-8") as handle:
            scheduler = handle.read()
        with open(screens_path, "r", encoding="utf-8") as handle:
            screens = handle.read()

        self.assertIn("openRealtimeStream", stream)
        self.assertIn("mergeMatrixEvents", stream)
        self.assertIn("MAX_SCREEN_REQUESTS = 12", scheduler)
        self.assertIn("document.visibilityState === 'visible'", screens)

    def test_matrix_workbench_bounds_device_timeline(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        view_model_path = os.path.join(repo_root, "src", "components", "matrix", "matrixViewModel.ts")
        timeline_path = os.path.join(repo_root, "src", "components", "matrix", "DeviceTimeline.tsx")
        with open(view_model_path, "r", encoding="utf-8") as handle:
            view_model = handle.read()
        with open(timeline_path, "r", encoding="utf-8") as handle:
            timeline = handle.read()

        self.assertIn("limit = 200", view_model)
        self.assertIn(".slice(-limit)", view_model)
        self.assertIn("data-matrix-device-timeline", timeline)
        self.assertIn("max-h-[164px]", timeline)

    def test_matrix_workbench_waits_for_real_job_result_and_only_targets_online_devices(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        page_path = os.path.join(repo_root, "src", "components", "matrix", "MatrixWorkbenchPage.tsx")
        with open(page_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("await matrixApi.dispatch", source)
        self.assertIn("selectedOnlineIds", source)
        self.assertIn("await refresh()", source)
        self.assertNotIn("任务已发布到真实设备队列。", source)

    def test_matrix_workbench_prioritizes_offline_over_stale_task_state(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        view_model_path = os.path.join(repo_root, "src", "components", "matrix", "matrixViewModel.ts")
        view_model_test_path = os.path.join(repo_root, "src", "components", "matrix", "matrixViewModel.test.ts")
        with open(view_model_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(view_model_test_path, "r", encoding="utf-8") as handle:
            test_source = handle.read()

        offline_guard = "if (!device.online) return 'offline';"
        failure_guard = "if ((device.failureCount || 0) > 0"
        self.assertLess(source.index(offline_guard), source.index(failure_guard))
        self.assertIn("deriveDeviceStatus gives offline state precedence over stale task data", test_source)

    def test_phone_runtime_events_are_written_to_matrix_ledger(self) -> None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        routes_path = os.path.join(repo_root, "python", "api", "routes_phone.py")
        with open(routes_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("append_runtime_event", source)
        self.assertIn("phone.events.", source)

    def test_runtime_event_ledger_entry_is_redacted_and_watchable(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            event = matrix.append_runtime_event(
                "phone.snapshot",
                "phone-a",
                "observed https://example.com/path/to/raw/job?id=123 with Bearer secret-token",
                source="phone.events.snapshot",
                details={"token": "secret-token", "durationMs": 42},
            )
            events = matrix.watch()["events"]

        serialized = json.dumps({"event": event, "events": events}, ensure_ascii=False)
        self.assertEqual(events[-1]["type"], "phone.snapshot")
        self.assertEqual(events[-1]["deviceId"], "phone-a")
        self.assertEqual(events[-1]["source"], "phone.events.snapshot")
        self.assertEqual(events[-1]["details"]["durationMs"], 42)
        self.assertNotIn("secret-token", serialized)

    def test_identical_runtime_events_are_not_appended_twice(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            first = matrix.append_runtime_event(
                "phone.events.snapshot",
                "phone-a",
                "任务执行完成",
                source="phone.events.snapshot",
                details={"busy": False, "runningTaskCount": 0},
            )
            second = matrix.append_runtime_event(
                "phone.events.snapshot",
                "phone-a",
                "任务执行完成",
                source="phone.events.snapshot",
                details={"busy": False, "runningTaskCount": 0},
            )
            events = matrix.watch()["events"]

        self.assertEqual(len(events), 1)
        self.assertEqual(second["eventId"], first["eventId"])
        self.assertTrue(second["deduplicated"])

    def test_identical_state_stream_event_stays_deduplicated_after_time_window(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            first = matrix.append_runtime_event(
                "phone.events.snapshot",
                "phone-a",
                "idle",
                source="phone.events.snapshot",
                details={"busy": False, "runningTaskCount": 0},
            )
            with open(matrix.events_path, "r", encoding="utf-8") as handle:
                saved = json.loads(handle.readline())
            saved["timestamp"] = "2020-01-01T00:00:00+00:00"
            with open(matrix.events_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(saved, ensure_ascii=False) + "\n")

            second = matrix.append_runtime_event(
                "phone.events.snapshot",
                "phone-a",
                "idle",
                source="phone.events.snapshot",
                details={"busy": False, "runningTaskCount": 0},
            )

        self.assertEqual(second["eventId"], first["eventId"])
        self.assertTrue(second["deduplicated"])

    def test_event_ledger_rotates_and_keeps_three_archives(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            with patch("core.phone_matrix.MATRIX_EVENT_FILE_MAX_BYTES", 700):
                for index in range(80):
                    matrix.append_runtime_event(
                        "phone.task.output",
                        "phone-a",
                        f"event-{index}-" + ("x" * 120),
                        source="test",
                    )
            archives = [
                name
                for name in os.listdir(os.path.dirname(matrix.events_path))
                if name.startswith("matrix-events.jsonl.")
            ]
            visible_events = matrix.watch(limit=500)["events"]

        self.assertGreaterEqual(len(archives), 1)
        self.assertLessEqual(len(archives), 3)
        self.assertGreater(len(visible_events), 1)
        self.assertEqual(visible_events[-1]["message"].split("-")[1], "79")

    def test_event_ledger_tail_reports_when_earlier_jsonl_bytes_were_omitted(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            os.makedirs(os.path.dirname(matrix.events_path), exist_ok=True)
            with open(matrix.events_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "large", "message": "x" * 1000}) + "\n")
                handle.write(json.dumps({"type": "latest", "message": "kept"}) + "\n")

            with patch("core.phone_matrix.MATRIX_EVENT_TAIL_BYTES", 256):
                snapshot = matrix.watch(limit=500)

        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["events"][-1]["type"], "latest")
        self.assertGreater(snapshot["truncation"]["omittedBytes"], 0)
        self.assertEqual(snapshot["truncation"]["reason"], "jsonl_tail_limit")

    def test_event_ledger_tail_reports_actual_discarded_line_bytes(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            os.makedirs(os.path.dirname(matrix.events_path), exist_ok=True)
            first = json.dumps({"type": "first", "message": "x" * 240}) + "\n"
            second = json.dumps({"type": "latest", "message": "kept"}) + "\n"
            with open(matrix.events_path, "w", encoding="utf-8") as handle:
                handle.write(first)
                handle.write(second)
            file_size = os.path.getsize(matrix.events_path)

            with patch("core.phone_matrix.MATRIX_EVENT_TAIL_BYTES", 180):
                snapshot = matrix.watch(limit=500)

        self.assertEqual(snapshot["events"][-1]["type"], "latest")
        self.assertGreater(snapshot["truncation"]["omittedBytes"], file_size - 180)
        self.assertIn("jsonl_tail_limit", snapshot["truncation"]["reasons"])

    def test_watch_limit_reports_request_level_truncation(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            for index in range(3):
                matrix.append_runtime_event("task.step", "phone-a", f"step-{index}")

            snapshot = matrix.watch(limit=1)

        self.assertTrue(snapshot["truncated"])
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertGreaterEqual(snapshot["truncation"]["omittedEvents"], 2)
        self.assertIn("request_limit", snapshot["truncation"]["reasons"])

    def test_invalid_utf8_device_registry_is_quarantined_instead_of_crashing(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            os.makedirs(os.path.dirname(matrix.devices_path), exist_ok=True)
            with open(matrix.devices_path, "wb") as handle:
                handle.write(b'{"schema":"loom.matrix.devices.v1","devices":[' + bytes([0x80]))

            status = matrix.status()
            quarantined = [
                name
                for name in os.listdir(os.path.dirname(matrix.devices_path))
                if name.startswith("matrix-devices.json.corrupt-")
            ]

        self.assertEqual(status["summary"]["total"], 0)
        self.assertEqual(len(quarantined), 1)

    def test_invalid_external_phone_config_is_not_moved_by_matrix_reader(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            os.makedirs(os.path.dirname(matrix.phone_devices_path), exist_ok=True)
            with open(matrix.phone_devices_path, "wb") as handle:
                handle.write(b'{"devices":' + bytes([0x80]))

            matrix.status()
            quarantined = [
                name for name in os.listdir(os.path.dirname(matrix.phone_devices_path))
                if name.startswith("phone-agents.json.corrupt-")
            ]
            original_exists = os.path.exists(matrix.phone_devices_path)

        self.assertTrue(original_exists)
        self.assertEqual(quarantined, [])

    def test_device_registry_preserves_updates_from_multiple_processes(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            with ProcessPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(_register_matrix_devices_from_process, temp_dir, f"worker-{index}", 12)
                    for index in range(4)
                ]
                expected = {
                    device_id
                    for future in futures
                    for device_id in future.result(timeout=30)
                }
            status = MatrixControlPlane(AppPaths(base_path=temp_dir)).status()
            actual = {item["deviceId"] for item in status["devices"]}

        self.assertEqual(actual, expected)

    def test_unregister_device_removes_live_card_but_keeps_event_ledger(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "name": "Phone A", "online": True})
            matrix.append_runtime_event("phone.task.complete", "phone-a", "done")

            result = matrix.unregister_device("phone-a")

            self.assertTrue(result["removed"])
            self.assertEqual(matrix.status()["devices"], [])
            self.assertEqual(matrix.watch()["events"][-1]["message"], "done")

    def test_device_registry_redacts_tokens_and_tracks_runtime_fields(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            device = matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "group": "demo",
                    "online": True,
                    "heartbeatAt": datetime.now(timezone.utc).isoformat(),
                    "currentScreenSummary": "微信首页",
                    "failureCount": 2,
                    "model": "agnes-2.0-flash",
                    "token": "secret-token",
                    "lumiLauncherSecret": "secret",
                }
            )
            status = matrix.status()

        serialized = json.dumps({"device": device, "status": status}, ensure_ascii=False)
        self.assertEqual(status["schema"], "loom.matrix.v1")
        self.assertEqual(status["devices"][0]["deviceId"], "phone-a")
        self.assertEqual(status["devices"][0]["group"], "demo")
        self.assertTrue(status["devices"][0]["online"])
        self.assertEqual(status["devices"][0]["currentScreenSummary"], "微信首页")
        self.assertEqual(status["devices"][0]["failureCount"], 2)
        self.assertEqual(status["devices"][0]["model"], "agnes-2.0-flash")
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("lumiLauncherSecret", serialized)

    def test_device_registry_keeps_safe_live_task_progress_fields(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-progress",
                    "online": True,
                    "currentStep": "read_screen",
                    "headline": "正在读取当前页面",
                    "needsCodex": True,
                    "progressLog": [
                        {
                            "round": 2,
                            "type": "tool",
                            "toolId": "get_screen_info",
                            "text": "第 2 阶段：读取当前页面",
                            "time": 500,
                            "parameters": {"token": "secret-token"},
                        }
                    ],
                }
            )
            device = matrix.status()["devices"][0]

        serialized = json.dumps(device, ensure_ascii=False)
        self.assertEqual(device["currentStep"], "read_screen")
        self.assertEqual(device["headline"], "正在读取当前页面")
        self.assertTrue(device["needsCodex"])
        self.assertEqual(device["progressLog"][0]["text"], "第 2 阶段：读取当前页面")
        self.assertNotIn("parameters", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_device_registry_marks_stale_heartbeat_offline_with_stream_fields(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        stale = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-stale",
                    "online": True,
                    "heartbeatAt": stale,
                    "lastEventAt": stale,
                    "streamStatus": "connected",
                    "streamLatencyMs": 120,
                    "currentPackage": "com.demo",
                    "accessibilityRunning": True,
                    "screenOn": True,
                    "deviceLocked": False,
                    "runningTaskCount": 1,
                }
            )
            status = matrix.status()

        device = status["devices"][0]
        self.assertFalse(device["online"])
        self.assertEqual(device["streamStatus"], "offline")
        self.assertGreaterEqual(device["streamLatencyMs"], 30000)
        self.assertEqual(device["currentPackage"], "com.demo")
        self.assertTrue(device["accessibilityRunning"])
        self.assertTrue(device["screenOn"])
        self.assertFalse(device["deviceLocked"])
        self.assertEqual(device["runningTaskCount"], 0)

    def test_device_registry_uses_heartbeat_when_last_event_is_missing(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        stale = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-heartbeat-only",
                    "online": True,
                    "heartbeatAt": stale,
                    "streamStatus": "connected",
                }
            )
            device = matrix.status()["devices"][0]

        self.assertFalse(device["online"])
        self.assertEqual(device["streamStatus"], "offline")

    def test_device_registry_accepts_explicit_idle_clear(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": True,
                    "busy": True,
                    "currentTaskId": "task-1",
                    "runningTaskCount": 1,
                }
            )
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": True,
                    "busy": False,
                    "currentTaskId": "",
                    "runningTaskCount": 0,
                    "currentStep": "",
                    "headline": "",
                }
            )
            device = matrix.status()["devices"][0]

        self.assertTrue(device["online"])
        self.assertFalse(device["busy"])
        self.assertEqual(device["currentTaskId"], "")
        self.assertEqual(device["runningTaskCount"], 0)

    def test_older_presence_update_cannot_revive_offline_device(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": False,
                    "busy": False,
                    "currentTaskId": "",
                    "presenceObservedAt": "2026-07-16T12:00:10+00:00",
                }
            )
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": True,
                    "busy": True,
                    "currentTaskId": "old-task",
                    "presenceObservedAt": "2026-07-16T12:00:05+00:00",
                }
            )
            device = matrix.status()["devices"][0]

        self.assertFalse(device["online"])
        self.assertFalse(device["busy"])
        self.assertEqual(device["currentTaskId"], "")
        self.assertEqual(device["runningTaskCount"], 0)

    def test_offline_device_is_not_reported_busy_from_stale_task_id(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device(
                {
                    "deviceId": "phone-a",
                    "online": False,
                    "busy": True,
                    "currentTaskId": "stale-task",
                }
            )
            device = matrix.status()["devices"][0]

        self.assertFalse(device["online"])
        self.assertFalse(device["busy"])
        self.assertEqual(device["currentTaskId"], "")
        self.assertEqual(device["runningTaskCount"], 0)

    def test_status_includes_saved_phone_config_devices_without_token_leak(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(base_path=temp_dir)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "selectedDeviceId": "android-main",
                        "devices": [
                            {
                                "id": "android-main",
                                "name": "Android Phone",
                                "baseUrl": "http://192.168.1.13:9527",
                                "token": "phone-secret-token",
                                "album": "LOOM",
                                "lastSeenAt": "2026-07-01T12:00:00+08:00",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            status = MatrixControlPlane(paths).status()

        self.assertEqual(status["summary"]["total"], 1)
        device = status["devices"][0]
        self.assertEqual(device["deviceId"], "android-main")
        self.assertEqual(device["name"], "Android Phone")
        self.assertEqual(device["source"], "phone-config")
        self.assertTrue(device["selected"])
        self.assertFalse(device["online"])
        self.assertFalse(device["busy"])
        self.assertEqual(device["model"], "qwen3.7-plus")
        serialized = json.dumps(status, ensure_ascii=False)
        self.assertNotIn("phone-secret-token", serialized)
        self.assertNotIn("192.168.1.13", serialized)

    def test_phone_config_names_remain_distinct_when_runtime_registry_uses_stale_names(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(base_path=temp_dir)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "selectedDeviceId": "phone-a",
                        "devices": [
                            {"id": "phone-a", "name": "招聘一号机"},
                            {"id": "phone-b", "name": "招聘二号机"},
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            matrix = MatrixControlPlane(paths)
            matrix.register_device({"deviceId": "phone-a", "name": "共享旧名称", "online": True})
            matrix.register_device({"deviceId": "phone-b", "name": "共享旧名称", "online": True})
            devices = matrix.status()["devices"]

        self.assertEqual(
            [(device["deviceId"], device["name"]) for device in devices],
            [("phone-a", "招聘一号机"), ("phone-b", "招聘二号机")],
        )
        self.assertTrue(all(device["online"] for device in devices))

    def test_phone_config_refresh_drops_deleted_inventory_but_keeps_active_task_evidence(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(base_path=temp_dir)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            config_path = os.path.join(paths.launcher_dir, "phone-agents.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "selectedDeviceId": "phone-active",
                        "devices": [
                            {"id": "phone-active", "name": "Active Phone"},
                            {"id": "phone-deleted", "name": "Deleted Phone"},
                        ],
                    },
                    handle,
                )

            matrix = MatrixControlPlane(paths)
            matrix.register_device(
                {
                    "deviceId": "phone-active",
                    "online": True,
                    "busy": True,
                    "currentTaskId": "task-1",
                    "runningTaskCount": 1,
                }
            )
            matrix.register_device({"deviceId": "phone-deleted", "online": True})
            campaign = matrix.dispatch(
                {
                    "prompt": "read screen",
                    "deviceIds": ["phone-deleted"],
                }
            )

            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "selectedDeviceId": "phone-active",
                        "devices": [{"id": "phone-active", "name": "Active Phone"}],
                    },
                    handle,
                )

            status = matrix.status()

        self.assertEqual([device["deviceId"] for device in status["devices"]], ["phone-active"])
        self.assertTrue(status["devices"][0]["busy"])
        self.assertEqual(status["devices"][0]["currentTaskId"], "task-1")
        self.assertEqual(status["devices"][0]["runningTaskCount"], 1)
        self.assertEqual(status["campaigns"][0]["campaignId"], campaign["campaignId"])
        task = status["campaigns"][0]["missions"][0]["deviceTasks"][0]
        self.assertEqual(task["deviceId"], "phone-deleted")
        self.assertEqual(task["status"], "queued")

    def test_dispatch_creates_campaign_mission_device_tasks_steps_and_events(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "demo", "online": True})
            task = matrix.dispatch(
                {
                    "title": "读屏",
                    "prompt": "读取当前屏幕",
                    "target": {"groups": ["demo"]},
                    "profile": "fast",
                    "mode": "observe",
                }
            )
            status = matrix.status()
            events = matrix.watch(task["campaignId"])

        self.assertTrue(task["campaignId"].startswith("campaign_"))
        self.assertTrue(task["missions"][0]["missionId"].startswith("mission_"))
        device_task = task["missions"][0]["deviceTasks"][0]
        self.assertEqual(device_task["deviceId"], "phone-a")
        self.assertEqual(device_task["executionLayer"], "direct")
        self.assertEqual([step["kind"] for step in device_task["steps"]], ["direct", "result"])
        self.assertEqual(status["devices"][0]["currentTaskId"], "")
        self.assertEqual([event["type"] for event in events["events"][:2]], ["queued", "assigned"])

    def test_dispatch_stays_queued_until_a_worker_actually_starts(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            status = matrix.status()

        persisted = status["campaigns"][0]
        device_task = persisted["missions"][0]["deviceTasks"][0]
        self.assertEqual(task["status"], "queued")
        self.assertEqual(persisted["status"], "queued")
        self.assertEqual(persisted["missions"][0]["status"], "queued")
        self.assertEqual(device_task["status"], "queued")
        self.assertEqual(status["devices"][0]["currentTaskId"], "")

    def test_canonical_dispatch_targets_only_assigned_device_and_preserves_fields(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})

            with patch.object(matrix, "_target_devices", side_effect=AssertionError("legacy target parser used")):
                task = matrix.dispatch(
                    {
                        "schema": "loom.matrix.dispatch.v2",
                        "campaignId": "campaign_from_caller",
                        "concurrency": 1,
                        "mode": "safe",
                        "profile": "standard",
                        "deviceAssignments": [
                            {
                                "assignmentId": "assignment_phone_b",
                                "deviceId": "phone-b",
                                "prompt": "Inspect only phone B.",
                                "templateId": "screen_read_v1",
                                "input": {"candidateId": "candidate_42"},
                                "timeoutSec": 180,
                                "retryBudget": 1,
                            }
                        ],
                    }
                )
            status = matrix.status()

        self.assertEqual(task["campaignId"], "campaign_from_caller")
        self.assertEqual(task["concurrency"], 1)
        device_tasks = task["missions"][0]["deviceTasks"]
        self.assertEqual(len(device_tasks), 1)
        self.assertEqual(
            {
                key: device_tasks[0][key]
                for key in (
                    "assignmentId",
                    "deviceId",
                    "prompt",
                    "templateId",
                    "input",
                    "timeoutSec",
                    "retryBudget",
                )
            },
            {
                "assignmentId": "assignment_phone_b",
                "deviceId": "phone-b",
                "prompt": "Inspect only phone B.",
                "templateId": "screen_read_v1",
                "input": {"candidateId": "candidate_42"},
                "timeoutSec": 180,
                "retryBudget": 1,
            },
        )
        devices = {item["deviceId"]: item for item in status["devices"]}
        self.assertEqual(devices["phone-a"]["currentTaskId"], "")
        self.assertEqual(devices["phone-b"]["currentTaskId"], "")

    def test_canonical_dispatch_rejects_unsupported_template_before_mutation(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch(
                    {
                        "schema": "loom.matrix.dispatch.v2",
                        "campaignId": "campaign_invalid",
                        "concurrency": 1,
                        "deviceAssignments": [
                            {
                                "assignmentId": "assignment_invalid",
                                "deviceId": "phone-a",
                                "templateId": "unsupported_template",
                                "input": {},
                                "timeoutSec": 180,
                                "retryBudget": 0,
                            }
                        ],
                    }
                )
            status = matrix.status()
            events = matrix.watch("campaign_invalid")

        self.assertEqual(raised.exception.code, "matrix_unsupported_assignment")
        self.assertEqual(status["campaigns"], [])
        self.assertEqual(status["devices"][0]["currentTaskId"], "")
        self.assertEqual(events["events"], [])

    def test_canonical_dispatch_rejects_timeout_that_executor_would_clamp(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch(
                    {
                        "schema": "loom.matrix.dispatch.v2",
                        "campaignId": "campaign_short_timeout",
                        "concurrency": 1,
                        "deviceAssignments": [
                            {
                                "assignmentId": "assignment_short_timeout",
                                "deviceId": "phone-a",
                                "prompt": "Read phone A.",
                                "input": {},
                                "timeoutSec": 29,
                                "retryBudget": 0,
                            }
                        ],
                    }
                )

            status = matrix.status()

        self.assertEqual(raised.exception.code, "matrix_invalid_dispatch")
        self.assertEqual(status["campaigns"], [])
        self.assertEqual(status["devices"][0]["currentTaskId"], "")

    def test_dispatch_rejects_offline_target_without_creating_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-offline", "online": False})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch({"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-offline"]}})

            status = matrix.status()

        self.assertEqual(raised.exception.code, "matrix_no_online_devices")
        self.assertEqual(status["campaigns"], [])
        self.assertFalse(status["devices"][0]["online"])
        self.assertEqual(status["devices"][0]["currentTaskId"], "")

    def test_dispatch_rejects_unknown_target_instead_of_returning_empty_queue(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch({"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-missing"]}})

        self.assertEqual(raised.exception.code, "matrix_target_not_found")

    def test_dispatch_rejects_mixed_device_and_group_targets(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "lab", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch({
                    "prompt": "read screen",
                    "target": {"deviceIds": ["phone-a"], "groups": ["lab"]},
                })

        self.assertEqual(raised.exception.code, "matrix_invalid_target")

    def test_dispatch_rejects_top_level_and_nested_target_before_mutation(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "lab", "online": True})
            matrix.register_device({"deviceId": "phone-b", "group": "sales", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch(
                    {
                        "prompt": "read screen",
                        "deviceIds": ["phone-a"],
                        "target": {"deviceIds": ["phone-b"]},
                    }
                )
            status = matrix.status()

        self.assertEqual(raised.exception.code, "matrix_invalid_target")
        self.assertEqual(status["campaigns"], [])
        self.assertTrue(all(not device["currentTaskId"] for device in status["devices"]))

    def test_dispatch_requires_explicit_target_to_prevent_accidental_broadcast(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.dispatch({"prompt": "读取当前屏幕"})

            all_online = matrix.dispatch(
                {"prompt": "读取当前屏幕", "target": {"allOnline": True}}
            )

        self.assertEqual(raised.exception.code, "matrix_no_target")
        self.assertEqual(
            all_online["missions"][0]["deviceTasks"][0]["deviceId"],
            "phone-a",
        )

    def test_explicit_all_online_targets_every_online_device(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            for index in range(6):
                matrix.register_device({"deviceId": f"phone-{index + 1}", "online": True})

            task = matrix.dispatch({"prompt": "read screen", "target": {"allOnline": True}})
            device_ids = {
                item["deviceId"]
                for item in task["missions"][0]["deviceTasks"]
            }

        self.assertEqual(device_ids, {f"phone-{index + 1}" for index in range(6)})

    def test_cancel_all_only_cancels_active_campaigns(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            first = matrix.dispatch(
                {"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-a"]}}
            )
            second = matrix.dispatch(
                {"prompt": "读取当前屏幕", "target": {"deviceIds": ["phone-a"]}}
            )
            matrix.record_result(
                first["missions"][0]["deviceTasks"][0]["deviceTaskId"],
                ok=True,
                duration_ms=10,
            )

            result = matrix.cancel_all()
            status = matrix.status()

        self.assertEqual(result["cancelledCount"], 1)
        states = {item["campaignId"]: item["status"] for item in status["campaigns"]}
        self.assertEqual(states[first["campaignId"]], "succeeded")
        self.assertEqual(states[second["campaignId"]], "cancelled")

    def test_cancel_does_not_rewrite_a_terminal_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            matrix.record_result(
                task["missions"][0]["deviceTasks"][0]["deviceTaskId"],
                ok=True,
                duration_ms=10,
            )

            result = matrix.cancel(task["campaignId"])
            campaign = matrix.status()["campaigns"][0]

        self.assertFalse(result["cancelled"])
        self.assertTrue(result["alreadyTerminal"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(campaign["status"], "succeeded")

    def test_cancel_missing_campaign_fails_instead_of_returning_false_success(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.cancel("campaign-missing")

        self.assertEqual(raised.exception.code, "matrix_campaign_not_found")

    def test_cancel_preserves_succeeded_child_in_mixed_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )
            children = {
                child["deviceId"]: child
                for child in task["missions"][0]["deviceTasks"]
            }
            matrix.record_result(children["phone-a"]["deviceTaskId"], ok=True, duration_ms=17)

            result = matrix.cancel(task["campaignId"])
            campaign = matrix.status()["campaigns"][0]
            events = matrix.watch(task["campaignId"], limit=500)["events"]

        states = {
            child["deviceId"]: child
            for child in campaign["missions"][0]["deviceTasks"]
        }
        cancelled_task_ids = {
            event["deviceTaskId"]
            for event in events
            if event["type"] == "cancelled"
        }
        self.assertTrue(result["cancelled"])
        self.assertEqual(states["phone-a"]["status"], "succeeded")
        self.assertEqual(states["phone-a"]["durationMs"], 17)
        self.assertEqual(states["phone-b"]["status"], "cancelled")
        self.assertEqual(cancelled_task_ids, {states["phone-b"]["deviceTaskId"]})

    def test_cancel_all_preserves_succeeded_child_in_mixed_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )
            children = {
                child["deviceId"]: child
                for child in task["missions"][0]["deviceTasks"]
            }
            matrix.record_result(children["phone-a"]["deviceTaskId"], ok=True, duration_ms=19)

            result = matrix.cancel_all()
            campaign = matrix.status()["campaigns"][0]

        states = {
            child["deviceId"]: child
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(result["cancelledCount"], 1)
        self.assertEqual(states["phone-a"]["status"], "succeeded")
        self.assertEqual(states["phone-a"]["durationMs"], 19)
        self.assertEqual(states["phone-b"]["status"], "cancelled")

    def test_emergency_stop_device_scope_preserves_unrelated_devices_in_the_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )

            result = matrix.emergency_stop(device_ids={"phone-b"})
            campaign = matrix.status()["campaigns"][0]

        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(result["affectedTaskCount"], 1)
        self.assertEqual(result["affected"][0]["deviceId"], "phone-b")
        self.assertEqual(result["matchedCampaignIds"], [task["campaignId"]])
        self.assertEqual(states, {"phone-a": "queued", "phone-b": "cancelled"})

    def test_emergency_stop_device_task_scope_preserves_sibling_tasks(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )
            children = {
                child["deviceId"]: child
                for child in task["missions"][0]["deviceTasks"]
            }

            result = matrix.emergency_stop(
                device_task_ids={children["phone-a"]["deviceTaskId"]}
            )
            campaign = matrix.status()["campaigns"][0]

        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(result["affectedTaskCount"], 1)
        self.assertEqual(result["affected"][0]["deviceTaskId"], children["phone-a"]["deviceTaskId"])
        self.assertEqual(states, {"phone-a": "cancelled", "phone-b": "queued"})

    def test_emergency_stop_explicit_campaign_atomic_scope_is_idempotent(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )

            first = matrix.emergency_stop(device_ids={"phone-b"}, campaign_atomic=True)
            second = matrix.emergency_stop(device_ids={"phone-b"}, campaign_atomic=True)
            campaign = matrix.status()["campaigns"][0]

        affected_ids = [item["deviceId"] for item in first["affected"]]
        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertTrue(first["cancelled"])
        self.assertEqual(first["campaignIds"], [task["campaignId"]])
        self.assertEqual(first["affectedTaskCount"], 2)
        self.assertEqual(first["affectedDeviceCount"], 2)
        self.assertEqual(affected_ids, ["phone-a", "phone-b"])
        self.assertEqual(states, {"phone-a": "cancelled", "phone-b": "cancelled"})
        self.assertFalse(second["cancelled"])
        self.assertEqual(second["affected"], [])

    def test_emergency_stop_cancels_paused_tasks_in_the_matched_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
            )
            children = {
                child["deviceId"]: child
                for child in task["missions"][0]["deviceTasks"]
            }
            matrix.pause_task(children["phone-b"]["deviceTaskId"])

            result = matrix.emergency_stop(device_ids={"phone-b"}, campaign_atomic=True)
            campaign = matrix.status()["campaigns"][0]

        states = {
            child["deviceId"]: child["status"]
            for child in campaign["missions"][0]["deviceTasks"]
        }
        self.assertEqual(result["affectedTaskCount"], 2)
        self.assertEqual(states, {"phone-a": "cancelled", "phone-b": "cancelled"})

    def test_emergency_stop_terminal_selection_expands_to_active_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        for scope in ("device", "deviceTask"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as temp_dir:
                matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
                matrix.register_device({"deviceId": "phone-a", "online": True})
                matrix.register_device({"deviceId": "phone-b", "online": True})
                task = matrix.dispatch(
                    {"prompt": "read screen", "target": {"deviceIds": ["phone-a", "phone-b"]}}
                )
                children = {
                    child["deviceId"]: child
                    for child in task["missions"][0]["deviceTasks"]
                }
                matrix.record_result(children["phone-a"]["deviceTaskId"], ok=True, duration_ms=31)

                result = matrix.emergency_stop(
                    device_ids={"phone-a"} if scope == "device" else None,
                    device_task_ids={children["phone-a"]["deviceTaskId"]} if scope == "deviceTask" else None,
                    campaign_atomic=True,
                )
                campaign = matrix.status()["campaigns"][0]

                states = {
                    child["deviceId"]: child["status"]
                    for child in campaign["missions"][0]["deviceTasks"]
                }
                self.assertEqual(states, {"phone-a": "succeeded", "phone-b": "cancelled"})
                self.assertEqual(result["matchedCampaignIds"], [task["campaignId"]])
                self.assertEqual(result["affectedTaskCount"], 1)
                self.assertEqual(result["affected"][0]["deviceId"], "phone-b")

    def test_terminal_task_rejects_late_step_and_task_event_mutation(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            matrix.record_result(device_task_id, ok=True, duration_ms=23)
            before_task = matrix.status()["campaigns"][0]["missions"][0]["deviceTasks"][0]
            before_events = matrix.watch(task["campaignId"], limit=500)["events"]

            late_step = matrix.mark_step(
                device_task_id,
                "step_late",
                status="running",
                message="late step",
            )
            late_event = matrix.append_task_event("step", device_task_id, "late event")
            late_result = matrix.record_result(
                device_task_id,
                ok=False,
                duration_ms=999,
                failure_reason="late failure",
            )
            after_task = matrix.status()["campaigns"][0]["missions"][0]["deviceTasks"][0]
            after_events = matrix.watch(task["campaignId"], limit=500)["events"]

        self.assertFalse(late_step["ok"])
        self.assertTrue(late_step["terminal"])
        self.assertFalse(late_event["ok"])
        self.assertTrue(late_event["terminal"])
        self.assertFalse(late_result["ok"])
        self.assertTrue(late_result["terminal"])
        self.assertEqual(after_task, before_task)
        self.assertEqual(after_events, before_events)

    def test_late_result_cannot_overwrite_cancelled_campaign(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]

            matrix.cancel(task["campaignId"])
            late_result = matrix.record_result(device_task_id, ok=True, duration_ms=10)
            status = matrix.status()

        self.assertTrue(late_result["cancelled"])
        self.assertEqual(status["campaigns"][0]["status"], "cancelled")

    def test_late_result_cannot_overwrite_paused_assignment(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]

            matrix.pause_task(device_task_id)
            late_result = matrix.record_result(device_task_id, ok=True, duration_ms=10)
            persisted = matrix.status()["campaigns"][0]["missions"][0]["deviceTasks"][0]

        self.assertFalse(late_result["ok"])
        self.assertTrue(late_result["paused"])
        self.assertEqual(persisted["status"], "paused")

    def test_template_and_agent_layers_are_selected_before_model_inference(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "demo", "online": True})
            template_task = matrix.dispatch({"prompt": "打开系统设置", "target": {"deviceIds": ["phone-a"]}})
            agent_task = matrix.dispatch({"prompt": "完成一个复杂多步骤任务", "target": {"deviceIds": ["phone-a"]}, "mode": "full"})

        self.assertEqual(template_task["missions"][0]["deviceTasks"][0]["executionLayer"], "template")
        self.assertEqual(agent_task["missions"][0]["deviceTasks"][0]["executionLayer"], "agent")

    def test_safety_gate_requires_confirmation_for_bulk_outreach(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixSafetyError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "demo", "online": True})
            with self.assertRaises(MatrixSafetyError) as raised:
                matrix.dispatch({"prompt": "批量私信所有客户并自动回复", "target": {"groups": ["demo"]}})

        self.assertEqual(raised.exception.code, "safety_confirmation_required")
        self.assertIn("确认", raised.exception.message)

    def test_experience_report_records_success_rate_without_sensitive_values(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "demo", "online": True})
            task = matrix.dispatch(
                {
                    "prompt": "读取当前屏幕 sk-test-token",
                    "target": {"deviceIds": ["phone-a"]},
                }
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            matrix.record_result(device_task_id, ok=True, duration_ms=321, failure_reason="")
            report = matrix.experience_report()

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertEqual(report["schema"], "loom.matrix.experience.v1")
        self.assertGreaterEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["successRate"], 1.0)
        self.assertIn("templateSuggestions", report)
        self.assertNotIn("sk-test-token", serialized)

    def test_lead_records_are_local_structured_and_redacted(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            lead = matrix.record_lead(
                {
                    "source": "task",
                    "deviceId": "phone-a",
                    "campaignId": "campaign_123",
                    "deviceTaskId": "deviceTask_123",
                    "title": "客户线索",
                    "summary": "用户询问套餐，Bearer secret-token",
                    "status": "new",
                    "tags": ["demo", "需要跟进"],
                    "token": "secret-token",
                    "phone": "13800000000",
                }
            )
            listed = matrix.list_leads(limit=10)

        serialized = json.dumps({"lead": lead, "listed": listed}, ensure_ascii=False)
        self.assertEqual(lead["schema"], "loom.matrix.lead.v1")
        self.assertTrue(lead["leadId"].startswith("lead_"))
        self.assertEqual(listed["leads"][0]["deviceId"], "phone-a")
        self.assertEqual(listed["leads"][0]["tags"], ["demo", "需要跟进"])
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("13800000000", serialized)

    def test_retry_failed_campaign_creates_new_campaign_without_bypassing_safety(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "group": "demo", "online": True})
            task = matrix.dispatch(
                {
                    "prompt": "读取当前屏幕",
                    "target": {"deviceIds": ["phone-a"]},
                    "mode": "observe",
                    "profile": "fast",
                }
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]
            matrix.record_result(device_task_id, ok=False, duration_ms=123, failure_reason="设备离线")
            retried = matrix.retry_failed(task["campaignId"], {})
            events = matrix.watch(task["campaignId"])

        self.assertTrue(retried["retried"])
        self.assertEqual(retried["retryOf"], task["campaignId"])
        self.assertEqual(retried["task"]["retryOf"], task["campaignId"])
        retry_device_task = retried["task"]["missions"][0]["deviceTasks"][0]
        self.assertEqual(retry_device_task["deviceId"], "phone-a")
        self.assertEqual(retry_device_task["executionLayer"], "direct")
        self.assertEqual(
            retried["failureReasons"],
            [{
                "deviceTaskId": device_task_id,
                "deviceId": "phone-a",
                "code": "",
                "reason": "设备离线",
            }],
        )
        self.assertIn("retry", [event["type"] for event in events["events"]])

    def test_retry_missing_campaign_fails_instead_of_returning_false_success(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane, MatrixTargetError

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))

            with self.assertRaises(MatrixTargetError) as raised:
                matrix.retry_failed("campaign-missing", {})

        self.assertEqual(raised.exception.code, "matrix_campaign_not_found")

    def test_indeterminate_result_requires_human_and_blocks_immediate_retry(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            task = matrix.dispatch(
                {"prompt": "read screen", "target": {"deviceIds": ["phone-a"]}}
            )
            device_task_id = task["missions"][0]["deviceTasks"][0]["deviceTaskId"]

            matrix.record_result(
                device_task_id,
                ok=False,
                duration_ms=1000,
                failure_code="timeout",
                failure_reason="remote task may still be running",
                task_id="remote-task-42",
                outcome_indeterminate=True,
                execution_may_continue=True,
            )
            campaign = matrix.status(task["campaignId"])["campaigns"][0]
            retry = matrix.retry_failed(task["campaignId"], {})

        stored_task = campaign["missions"][0]["deviceTasks"][0]
        self.assertEqual(stored_task["status"], "needs_human")
        self.assertFalse(retry["retried"])
        self.assertFalse(retry["retryable"])
        self.assertTrue(retry["outcomeIndeterminate"])
        self.assertTrue(retry["executionMayContinue"])
        self.assertIn("check", retry["reason"].lower())

    def test_canonical_retry_preserves_each_failed_assignment_contract(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            matrix.register_device({"deviceId": "phone-a", "online": True})
            matrix.register_device({"deviceId": "phone-b", "online": True})
            task = matrix.dispatch(
                {
                    "schema": "loom.matrix.dispatch.v2",
                    "campaignId": "canonical_retry_source",
                    "concurrency": 2,
                    "mode": "safe",
                    "profile": "deep",
                    "deviceAssignments": [
                        {
                            "assignmentId": "assignment_a",
                            "deviceId": "phone-a",
                            "prompt": "Inspect A exactly.",
                            "templateId": "screen_read_v1",
                            "input": {"candidateId": "candidate-a", "rank": 1},
                            "timeoutSec": 321,
                            "retryBudget": 3,
                        },
                        {
                            "assignmentId": "assignment_b",
                            "deviceId": "phone-b",
                            "prompt": "Inspect B exactly.",
                            "input": {"candidateId": "candidate-b", "rank": 2},
                            "timeoutSec": 654,
                            "retryBudget": 5,
                        },
                    ],
                }
            )
            for device_task in task["missions"][0]["deviceTasks"]:
                matrix.record_result(
                    device_task["deviceTaskId"],
                    ok=False,
                    duration_ms=50,
                    failure_reason="retry me",
                )

            retried = matrix.retry_failed(task["campaignId"], {})

        retry_task = retried["task"]
        retry_assignments = retry_task["missions"][0]["deviceTasks"]
        self.assertEqual(retry_task["requestSchema"], "loom.matrix.dispatch.v2")
        self.assertEqual(retry_task["concurrency"], 2)
        self.assertEqual(
            [
                {
                    key: assignment[key]
                    for key in (
                        "assignmentId",
                        "deviceId",
                        "prompt",
                        "templateId",
                        "input",
                        "timeoutSec",
                        "retryBudget",
                    )
                }
                for assignment in retry_assignments
            ],
            [
                {
                    "assignmentId": "assignment_a",
                    "deviceId": "phone-a",
                    "prompt": "Inspect A exactly.",
                    "templateId": "screen_read_v1",
                    "input": {"candidateId": "candidate-a", "rank": 1},
                    "timeoutSec": 321,
                    "retryBudget": 3,
                },
                {
                    "assignmentId": "assignment_b",
                    "deviceId": "phone-b",
                    "prompt": "Inspect B exactly.",
                    "templateId": "",
                    "input": {"candidateId": "candidate-b", "rank": 2},
                    "timeoutSec": 654,
                    "retryBudget": 5,
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
