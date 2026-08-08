from __future__ import annotations

import hashlib
import importlib.util
import os
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


class MatrixSoakTests(unittest.TestCase):
    def test_two_phone_soak_passes_and_reports_latency(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(method, path, body, _timeout):
            if path == "/api/matrix/status":
                return {"devices": [{"deviceId": "phone-1", "online": True}, {"deviceId": "phone-2", "online": True}]}
            self.assertEqual(method, "POST")
            return {"screens": [{"deviceId": item["deviceId"]} for item in body["requests"]], "errors": []}

        report = run_matrix_soak(call, min_devices=2, max_iterations=3, monotonic=_Clock())

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["rounds"], 3)
        self.assertEqual(report["summary"]["minimumObservedDevices"], 2)
        self.assertGreater(report["summary"]["p95Ms"], 0)

    def test_missing_device_or_screen_failure_fails_gate(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, path, _body, _timeout):
            if path == "/api/matrix/status":
                return {"devices": [{"deviceId": "phone-1", "online": True}]}
            return {"screens": [], "errors": [{"deviceId": "phone-1", "error": "timeout"}]}

        report = run_matrix_soak(
            call,
            min_devices=2,
            max_failure_rate=0,
            max_iterations=1,
            monotonic=_Clock(),
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["minimumObservedDevices"], 1)
        self.assertGreater(report["summary"]["failureRate"], 0)

    def test_read_only_profile_stays_backward_compatible_and_auditable(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, path, _body, _timeout):
            self.assertEqual(path, "/api/matrix/status")
            return {"devices": [{"deviceId": "phone-1", "online": True}]}

        report = run_matrix_soak(
            call,
            capture_screens=False,
            max_iterations=1,
            monotonic=_Clock(),
            commit="abc123",
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["profile"], "read-only")
        self.assertEqual(report["commit"], "abc123")
        self.assertEqual(report["protocolVersion"], "6.0")
        self.assertIn("artifactHashes", report)
        self.assertNotIn("lifecycle", report)

    def test_read_only_device_inventory_includes_offline_devices(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, _path, _body, _timeout):
            return {"devices": [
                {"deviceId": "phone-1", "online": True},
                {"deviceId": "phone-2", "online": False},
            ]}

        report = run_matrix_soak(
            call,
            capture_screens=False,
            max_iterations=1,
            monotonic=_Clock(),
        )

        inventory = {item["deviceId"]: item for item in report["devices"]}
        self.assertEqual(sorted(inventory), ["phone-1", "phone-2"])
        self.assertEqual(inventory["phone-1"]["online"], True)
        self.assertEqual(inventory["phone-2"]["online"], False)

    def test_read_only_inventory_fails_closed_without_hardware_attestation(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, _path, _body, _timeout):
            return {"devices": [
                {"deviceId": "phone-1", "online": True, "virtual": False},
                {"deviceId": "phone-2", "online": True, "virtual": False},
            ]}

        report = run_matrix_soak(
            call,
            capture_screens=False,
            min_devices=2,
            max_iterations=1,
            monotonic=_Clock(),
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["provenanceSummary"], {
            "unknown": 2,
            "virtual": 0,
            "physicalAttested": 0,
        })
        for device in report["devices"]:
            self.assertEqual(device["provenance"], "unknown")
            self.assertIsNone(device["virtual"])
            self.assertEqual(device["realDeviceEligible"], False)
        self.assertEqual(report["realDeviceEligibility"]["eligibleCount"], 0)
        self.assertEqual(report["realDeviceEligibility"]["gateProven"], False)

    def test_read_only_duplicate_online_id_cannot_satisfy_two_device_gate(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, _path, _body, _timeout):
            return {"devices": [
                {"deviceId": "phone-1", "online": True},
                {"deviceId": "phone-1", "online": True},
            ]}

        report = run_matrix_soak(call, capture_screens=False, min_devices=2, max_iterations=1, monotonic=_Clock())

        self.assertFalse(report["passed"])
        self.assertEqual(report["rounds"][0]["onlineDevices"], 1)
        self.assertEqual(len(report["devices"]), 1)
        self.assertEqual(report["identityAnomalies"][0]["duplicateDeviceIds"], ["phone-1"])

    def test_read_only_string_false_is_not_online(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, _path, _body, _timeout):
            return {"devices": [{"deviceId": "phone-1", "online": "false"}]}

        report = run_matrix_soak(call, capture_screens=False, min_devices=1, max_iterations=1, monotonic=_Clock())

        self.assertFalse(report["passed"])
        self.assertEqual(report["rounds"][0]["onlineDevices"], 0)
        self.assertEqual(report["devices"][0]["online"], False)

    def test_read_only_conflicting_duplicate_id_is_auditable_failure(self) -> None:
        from core.matrix_soak import run_matrix_soak

        def call(_method, _path, _body, _timeout):
            return {"devices": [
                {"deviceId": "phone-1", "online": True},
                {"deviceId": "phone-1", "online": False},
            ]}

        report = run_matrix_soak(call, capture_screens=False, min_devices=1, max_iterations=1, monotonic=_Clock())

        self.assertFalse(report["passed"])
        self.assertEqual(report["identityAnomalies"][0]["conflictingDeviceIds"], ["phone-1"])
        self.assertEqual(report["rounds"][0]["status"], "failed")


class MatrixLifecycleSoakTests(unittest.TestCase):
    def _fixture(self, events, *, devices=None):
        return {
            "schema": "loom.matrix.lifecycle-fixture.v1",
            "virtual": True,
            "safe": True,
            "sideEffectFree": True,
            "name": "unit-virtual-fleet",
            "devices": devices or [{"deviceId": "virtual-1"}],
            "events": events,
        }

    def _run(self, events, *, devices=None, **kwargs):
        from core.matrix_soak import run_lifecycle_soak

        return run_lifecycle_soak(self._fixture(events, devices=devices), **kwargs)

    def _assert_invalid_epoch_across_lifecycle(self, invalid_epoch) -> None:
        base_events = [
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 1, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 1},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 15, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e2", "pid": 11, "taskIds": ["task-1"]},
            {"atMs": 21, "type": "resource", "deviceId": "virtual-1", "epoch": "e2", "pid": 11, "rssMb": 90, "handles": 18, "threads": 4, "heartbeat": 1},
            {"atMs": 25, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 3, "epoch": "e2"},
            {"atMs": 30, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e2"},
            {"atMs": 35, "type": "submit", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e2"},
            {"atMs": 40, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e2", "accepted": True},
            {"atMs": 45, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-2", "status": "cancelled", "epoch": "e2"},
        ]
        cases = (
            (0, "epoch"),
            (1, "epoch"),
            (2, "epoch"),
            (3, "epoch"),
            (4, "epoch"),
            (5, "previousEpoch"),
            (5, "epoch"),
            (6, "epoch"),
            (7, "epoch"),
            (8, "epoch"),
            (9, "epoch"),
            (10, "epoch"),
            (11, "epoch"),
        )
        for index, field in cases:
            with self.subTest(index=index, field=field, invalid_epoch=invalid_epoch):
                events = json.loads(json.dumps(base_events))
                events[index][field] = invalid_epoch
                report = self._run(events)
                self.assertFalse(report["passed"])
                self.assertIn("epoch-invalid", report["failureKinds"])

    def test_empty_epoch_is_rejected_across_lifecycle(self) -> None:
        self._assert_invalid_epoch_across_lifecycle("")

    def test_numeric_epoch_is_rejected_across_lifecycle(self) -> None:
        self._assert_invalid_epoch_across_lifecycle(123)

    def test_lifecycle_rejects_missing_or_not_explicitly_safe_virtual_fixture(self) -> None:
        from core.matrix_soak import run_lifecycle_soak

        for fixture in (
            None,
            {},
            {"schema": "loom.matrix.lifecycle-fixture.v1", "virtual": False, "safe": True},
            {"schema": "loom.matrix.lifecycle-fixture.v1", "virtual": True, "safe": False},
        ):
            with self.subTest(fixture=fixture):
                with self.assertRaisesRegex(ValueError, "virtual.*safe"):
                    run_lifecycle_soak(fixture)

        fixture_without_side_effect_declaration = {
            "schema": "loom.matrix.lifecycle-fixture.v1",
            "virtual": True,
            "safe": True,
            "devices": [{"deviceId": "virtual-1"}],
            "events": [],
        }
        with self.assertRaisesRegex(ValueError, "side-effect-free"):
            run_lifecycle_soak(fixture_without_side_effect_declaration)

    def test_empty_fixture_cannot_pass_lifecycle_gate(self) -> None:
        report = self._run([])

        self.assertFalse(report["passed"])
        self.assertIn("lifecycle-flow-missing", report["failureKinds"])

    def test_invalid_event_time_is_rejected_instead_of_becoming_zero(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": "not-a-time", "type": "metadata", "deviceId": "virtual-1", "queueDepth": 1, "queueTaskIds": ["task-1"]},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("event-time-invalid", report["failureKinds"])
        self.assertEqual(report["stages"]["metadataSamples"], 0)

    def test_successful_terminal_requires_valid_progress(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("progress-missing", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_malformed_progress_or_heartbeat_never_counts_as_valid_progress(self) -> None:
        invalid_fields = (
            {},
            {"progress": float("nan"), "heartbeat": 1},
            {"progress": -1, "heartbeat": 1},
            {"progress": 101, "heartbeat": 1},
            {"progress": 50},
            {"progress": 50, "heartbeat": -1},
        )
        for fields in invalid_fields:
            with self.subTest(fields=fields):
                report = self._run([
                    {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
                    {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
                    {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1", **fields},
                    {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
                ])

                self.assertFalse(report["passed"])
                self.assertIn("progress-field-invalid", report["failureKinds"])
                self.assertEqual(report["stages"]["progress"], 0)
                self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_progress_regression_is_an_auditable_failure(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 40, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 20, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("progress-regression", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_submit_epoch_must_match_current_online_device_epoch(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e0"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e0"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e0"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("submit-epoch-mismatch", report["failureKinds"])
        self.assertEqual(report["stages"]["submit"], 0)
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_device_epoch_change_requires_reconcile_before_task_continues(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e2", "pid": 10},
            {"atMs": 20, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 25, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("epoch-change-requires-reconcile", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_offline_before_submit_detected_without_counting_submit(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": False, "epoch": "e1", "pid": 10},
            {"atMs": 10, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["stages"]["submit"], 0)
        self.assertIn("offline-before-submit", report["failureKinds"])
        self.assertEqual(report["devices"][0]["kind"], "virtual")

    def test_offline_mid_task_is_detected(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 20, "type": "device", "deviceId": "virtual-1", "online": False, "epoch": "e1", "pid": 10},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("offline-mid-task", report["failureKinds"])
        self.assertEqual(report["recovery"]["attempted"], 1)

    def test_heartbeat_without_progress_triggers_no_progress(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 80, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 2, "epoch": "e1"},
        ], no_progress_timeout_ms=50)

        self.assertFalse(report["passed"])
        self.assertIn("no-progress", report["failureKinds"])
        self.assertEqual(report["stages"]["progress"], 2)

    def test_reconnect_same_task_and_epoch_recovers_without_false_timeout(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 20, "type": "device", "deviceId": "virtual-1", "online": False, "epoch": "e1", "pid": 10},
            {"atMs": 35, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 40, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 45, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertTrue(report["passed"])
        self.assertEqual(report["recovery"]["succeeded"], 1)
        self.assertEqual(report["recovery"]["durationsMs"], [20])
        self.assertEqual(report["falseTimeout"]["count"], 0)
        self.assertEqual(report["stages"]["terminal"], 1)

    def test_reconnect_without_monotonic_progress_is_not_recovery(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 20, "type": "device", "deviceId": "virtual-1", "online": False, "epoch": "e1", "pid": 10},
            {"atMs": 35, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 40, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 45, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["recovery"]["succeeded"], 0)
        self.assertIn("reconnect-no-progress", report["failureKinds"])

    def test_reconnect_requires_progress_from_every_active_task(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 6, "type": "submit", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 11, "type": "progress", "deviceId": "virtual-1", "taskId": "task-2", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 20, "type": "device", "deviceId": "virtual-1", "online": False, "epoch": "e1", "pid": 10},
            {"atMs": 30, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 35, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 40, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
            {"atMs": 41, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-2", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["recovery"]["succeeded"], 0)
        self.assertIn("reconnect-no-progress", report["failureKinds"])

    def test_restart_reconcile_missing_task_is_lost_state_failure(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 20, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 35, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e1", "pid": 11, "taskIds": []},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-lost-state", report["failureKinds"])
        self.assertEqual(report["restartReconcile"]["lostTaskIds"], ["task-1"])
        self.assertEqual(report["restartReconcile"]["pidChanged"], True)

    def test_restart_checkpoint_cannot_omit_an_active_task(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 25, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": []},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e2", "pid": 11, "taskIds": []},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-checkpoint-incomplete", report["failureKinds"])
        self.assertEqual(report["restartReconcile"]["lostTaskIds"], ["task-1"])
        self.assertEqual(report["restartReconcile"]["succeeded"], 0)

    def test_incomplete_checkpoint_cannot_recover_omitted_task_during_reconcile(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 3, "type": "submit", "deviceId": "virtual-1", "taskId": "task-2", "epoch": "e1"},
            {"atMs": 5, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 25, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 6, "type": "progress", "deviceId": "virtual-1", "taskId": "task-2", "progress": 25, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 10, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e2", "pid": 11, "taskIds": ["task-1", "task-2"]},
            {"atMs": 25, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e2"},
            {"atMs": 26, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-2", "status": "succeeded", "epoch": "e2"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-checkpoint-incomplete", report["failureKinds"])
        self.assertIn("restart-lost-state", report["failureKinds"])
        self.assertEqual(report["restartReconcile"]["succeeded"], 0)
        self.assertEqual(report["restartReconcile"]["recoveredTaskIds"], ["task-1"])
        self.assertEqual(report["restartReconcile"]["lostTaskIds"], ["task-2"])

    def test_restart_reconcile_preserves_live_task_then_progresses_to_terminal(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 20, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 35, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e1", "pid": 11, "taskIds": ["task-1"]},
            {"atMs": 37, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 11, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 2},
            {"atMs": 40, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 45, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertTrue(report["passed"])
        self.assertEqual(report["restartReconcile"]["recoveredTaskIds"], ["task-1"])
        self.assertEqual(report["restartReconcile"]["succeeded"], 1)
        self.assertEqual(report["restartReconcile"]["durationsMs"], [15])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 1)
        self.assertEqual(report["stages"]["progress"], 2)
        self.assertEqual(report["restartReconcile"]["byDevice"][0]["epoch"], "e1")
        self.assertEqual(report["devices"][0]["pid"], 11)

    def test_restart_checkpoints_are_isolated_per_device(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 0, "type": "device", "deviceId": "virtual-2", "online": True, "epoch": "e2", "pid": 20},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 6, "type": "submit", "deviceId": "virtual-2", "taskId": "task-2", "epoch": "e2"},
            {"atMs": 7, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 8, "type": "progress", "deviceId": "virtual-2", "taskId": "task-2", "progress": 20, "heartbeat": 1, "epoch": "e2"},
            {"atMs": 10, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 12, "type": "restart-checkpoint", "deviceId": "virtual-2", "epoch": "e2", "pid": 20, "taskIds": ["task-2"]},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e1", "pid": 11, "taskIds": ["task-1"]},
            {"atMs": 24, "type": "restart-reconcile", "deviceId": "virtual-2", "previousEpoch": "e2", "epoch": "e2", "pid": 21, "taskIds": ["task-2"]},
            {"atMs": 30, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
            {"atMs": 31, "type": "terminal", "deviceId": "virtual-2", "taskId": "task-2", "status": "succeeded", "epoch": "e2"},
        ], devices=[{"deviceId": "virtual-1"}, {"deviceId": "virtual-2"}])

        self.assertTrue(report["passed"])
        self.assertEqual(report["restartReconcile"]["recoveredTaskIds"], ["task-1", "task-2"])
        by_device = {item["deviceId"]: item for item in report["restartReconcile"]["byDevice"]}
        self.assertEqual(by_device["virtual-1"]["recoveredTaskIds"], ["task-1"])
        self.assertEqual(by_device["virtual-2"]["recoveredTaskIds"], ["task-2"])

    def test_cross_device_and_epoch_events_cannot_complete_task(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 0, "type": "device", "deviceId": "virtual-2", "online": True, "epoch": "e2", "pid": 20},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-2", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e2"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-2", "taskId": "task-1", "status": "succeeded", "epoch": "e2"},
        ], devices=[{"deviceId": "virtual-1"}, {"deviceId": "virtual-2"}])

        self.assertFalse(report["passed"])
        self.assertIn("task-device-mismatch", report["failureKinds"])
        self.assertIn("task-epoch-mismatch", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)
        self.assertIn("terminal-missing", report["failureKinds"])

    def test_restart_checkpoint_rejects_other_devices_active_task(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 0, "type": "device", "deviceId": "virtual-2", "online": True, "epoch": "e2", "pid": 20},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "restart-checkpoint", "deviceId": "virtual-2", "epoch": "e2", "pid": 20, "taskIds": ["task-1"]},
            {"atMs": 15, "type": "restart-reconcile", "deviceId": "virtual-2", "previousEpoch": "e2", "epoch": "e2", "pid": 21, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ], devices=[{"deviceId": "virtual-1"}, {"deviceId": "virtual-2"}])

        self.assertFalse(report["passed"])
        self.assertIn("restart-checkpoint-task-mismatch", report["failureKinds"])

    def test_restart_checkpoint_pid_and_epoch_must_match_current_device(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e0", "pid": 99, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-checkpoint-pid-mismatch", report["failureKinds"])
        self.assertIn("restart-epoch-mismatch", report["failureKinds"])

    def test_restart_checkpoint_rejects_task_from_stale_epoch(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e2", "pid": 10},
            {"atMs": 20, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e2", "pid": 10, "taskIds": ["task-1"]},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-checkpoint-task-mismatch", report["failureKinds"])

    def test_restart_reconcile_requires_fresh_epoch_and_pid_boundary(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e0", "epoch": "e0", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 25, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("restart-epoch-mismatch", report["failureKinds"])
        self.assertIn("restart-pid-boundary-missing", report["failureKinds"])

    def test_restart_reconcile_can_migrate_live_task_to_new_epoch(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 20, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": ["task-1"]},
            {"atMs": 20, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e2", "pid": 11, "taskIds": ["task-1"]},
            {"atMs": 25, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 80, "heartbeat": 2, "epoch": "e2"},
            {"atMs": 30, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e2"},
        ])

        self.assertTrue(report["passed"])
        self.assertEqual(report["devices"][0]["epoch"], "e2")
        self.assertEqual(report["restartReconcile"]["byDevice"][0]["checkpointEpoch"], "e1")
        self.assertEqual(report["restartReconcile"]["byDevice"][0]["reconcileEpoch"], "e2")

    def test_terminal_after_no_progress_deadline_is_not_ordinary_success(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 80, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ], no_progress_timeout_ms=50, task_timeout_ms=1000)

        self.assertFalse(report["passed"])
        self.assertIn("no-progress", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_fixture_end_detects_no_progress_for_unterminated_task(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 10, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 100, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 2},
        ], no_progress_timeout_ms=50)

        self.assertFalse(report["passed"])
        self.assertIn("no-progress", report["failureKinds"])
        self.assertIn("terminal-missing", report["failureKinds"])

    def test_cancel_accepted_without_confirmed_terminal_fails(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1", "accepted": True},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["cancelConfirmation"]["requested"], 1)
        self.assertEqual(report["cancelConfirmation"]["confirmed"], 0)
        self.assertEqual(report["cancelConfirmation"]["unconfirmedTaskIds"], ["task-1"])
        self.assertIn("cancel-unconfirmed", report["failureKinds"])

    def test_cancel_requires_cancelled_terminal_and_then_passes(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1", "accepted": True},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "cancelled", "epoch": "e1"},
        ])

        self.assertTrue(report["passed"])
        self.assertEqual(report["cancelConfirmation"]["confirmed"], 1)
        self.assertEqual(report["stages"]["cancelConfirmed"], 1)

    def test_stale_cancel_epoch_cannot_confirm_newer_terminal(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e0", "accepted": True},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "cancelled", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("cancel-epoch-mismatch", report["failureKinds"])
        self.assertEqual(report["cancelConfirmation"]["confirmed"], 0)

    def test_cancel_request_without_epoch_is_rejected(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "cancel-request", "deviceId": "virtual-1", "taskId": "task-1", "accepted": True},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "cancelled", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("cancel-epoch-mismatch", report["failureKinds"])
        self.assertEqual(report["cancelConfirmation"]["confirmed"], 0)

    def test_failed_terminal_fails_lifecycle_gate(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "failed", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["taskOutcomes"]["failed"], 1)
        self.assertIn("failed-terminal", report["failureKinds"])

    def test_cancelled_terminal_without_accepted_request_fails(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "cancelled", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["cancelConfirmation"]["confirmed"], 0)
        self.assertIn("unexpected-cancel", report["failureKinds"])

    def test_duplicate_terminal_does_not_double_count_outcome(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
            {"atMs": 20, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("duplicate-terminal", report["failureKinds"])
        self.assertEqual(report["taskOutcomes"]["succeeded"], 1)

    def test_resource_growth_is_partitioned_by_pid_and_restart_cannot_hide_leak(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 1},
            {"atMs": 10, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 180, "handles": 30, "threads": 6, "heartbeat": 2},
            {"atMs": 20, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": []},
            {"atMs": 25, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e1", "pid": 11, "taskIds": []},
            {"atMs": 30, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 11, "rssMb": 90, "handles": 12, "threads": 3, "heartbeat": 1},
            {"atMs": 35, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 11, "rssMb": 95, "handles": 13, "threads": 3, "heartbeat": 2},
        ], max_resource_growth_mb=50)

        self.assertFalse(report["passed"])
        by_pid = {item["pid"]: item for item in report["resourceGrowth"]["byPid"]}
        self.assertEqual(by_pid[10]["growthMb"], 80)
        self.assertEqual(by_pid[11]["growthMb"], 5)
        self.assertEqual(by_pid[10]["trends"]["rssMb"], {"start": 100, "end": 180, "delta": 80})
        self.assertEqual(by_pid[10]["trends"]["handles"], {"start": 20, "end": 30, "delta": 10})
        self.assertEqual(by_pid[10]["trends"]["threads"], {"start": 4, "end": 6, "delta": 2})
        self.assertEqual(by_pid[10]["trends"]["heartbeat"], {"start": 1, "end": 2, "delta": 1})
        self.assertEqual(report["resourceGrowth"]["leakSignalPids"], [10])
        self.assertIn("resource-growth", report["failureKinds"])

    def test_handle_growth_has_independent_threshold_and_failure(self) -> None:
        from core.matrix_soak import run_lifecycle_soak

        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 1},
            {"atMs": 3, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 1000, "threads": 4, "heartbeat": 2},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 3, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertIn("max_handle_growth", inspect.signature(run_lifecycle_soak).parameters)
        self.assertFalse(report["passed"])
        self.assertIn("handle-growth", report["failureKinds"])
        self.assertEqual(report["resourceGrowth"]["thresholds"]["handles"], 128)

    def test_thread_growth_has_independent_threshold_and_failure(self) -> None:
        from core.matrix_soak import run_lifecycle_soak

        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 1},
            {"atMs": 3, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 100, "heartbeat": 2},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 3, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertIn("max_thread_growth", inspect.signature(run_lifecycle_soak).parameters)
        self.assertFalse(report["passed"])
        self.assertIn("thread-growth", report["failureKinds"])
        self.assertEqual(report["resourceGrowth"]["thresholds"]["threads"], 8)

    def test_resource_sample_requires_complete_finite_nonnegative_metrics(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": "nan", "threads": -1, "heartbeat": float("inf")},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("resource-field-invalid", report["failureKinds"])
        self.assertEqual(report["stages"]["resourceSamples"], 0)

    def test_resource_sample_must_match_current_pid_and_epoch(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e0", "pid": 99, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 1},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 2, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("resource-pid-mismatch", report["failureKinds"])
        self.assertIn("resource-epoch-mismatch", report["failureKinds"])
        self.assertEqual(report["stages"]["resourceSamples"], 0)

    def test_metadata_sample_must_match_current_pid_and_epoch(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "metadata", "deviceId": "virtual-1", "epoch": "e0", "pid": 10, "queueDepth": 0, "queueTaskIds": []},
            {"atMs": 3, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 99, "queueDepth": 0, "queueTaskIds": []},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("metadata-epoch-mismatch", report["failureKinds"])
        self.assertIn("metadata-pid-mismatch", report["failureKinds"])
        self.assertEqual(report["stages"]["metadataSamples"], 0)
        self.assertEqual(report["samples"]["metadata"], [])

    def test_device_pid_must_be_a_finite_nonnegative_integer(self) -> None:
        invalid_pids = (True, "10", float("nan"), float("inf"), None)
        for invalid_pid in invalid_pids:
            with self.subTest(pid=invalid_pid):
                report = self._run([
                    {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": invalid_pid},
                    {"atMs": 2, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 0, "queueTaskIds": []},
                    {"atMs": 3, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 1},
                ])

                self.assertFalse(report["passed"])
                self.assertIn("device-pid-invalid", report["failureKinds"])
                self.assertIsNone(report["devices"][0]["pid"])
                self.assertEqual(report["stages"]["metadataSamples"], 0)
                self.assertEqual(report["stages"]["resourceSamples"], 0)

    def test_queue_ids_and_depth_must_be_conserved(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 0, "queueTaskIds": []},
            {"atMs": 10, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 15, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 2, "queueTaskIds": ["wrong-task"]},
        ])

        self.assertFalse(report["passed"])
        self.assertEqual(report["queueConsistency"]["consistent"], False)
        self.assertGreaterEqual(len(report["queueConsistency"]["violations"]), 1)
        self.assertIn("queue-inconsistent", report["failureKinds"])
        self.assertEqual(report["stages"]["metadataSamples"], 2)

    def test_queue_duplicate_ids_are_not_hidden_by_set_deduplication(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 12, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 1, "queueTaskIds": ["task-1", "task-1"]},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("duplicate-task-ids", report["queueConsistency"]["violations"][0]["reasons"])
        self.assertEqual(report["samples"]["metadata"][0]["queueTaskIds"], ["task-1", "task-1"])

    def test_malformed_metadata_sample_is_rejected_without_defaulting_to_empty(self) -> None:
        invalid_samples = (
            {"queueDepth": -1, "queueTaskIds": []},
            {"queueDepth": 0.5, "queueTaskIds": []},
            {"queueDepth": "bad", "queueTaskIds": []},
            {"queueDepth": 0, "queueTaskIds": None},
            {"queueDepth": 1, "queueTaskIds": [""]},
            {"queueDepth": 1, "queueTaskIds": [123]},
        )
        for sample in invalid_samples:
            with self.subTest(sample=sample):
                report = self._run([
                    {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
                    {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
                    {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
                    {"atMs": 12, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, **sample},
                    {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
                ])

                self.assertFalse(report["passed"])
                self.assertIn("metadata-field-invalid", report["failureKinds"])
                self.assertEqual(report["stages"]["metadataSamples"], 0)

    def test_resource_heartbeat_must_not_regress_within_pid(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 2, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 2},
            {"atMs": 3, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 10, "threads": 4, "heartbeat": 1},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 3, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])

        self.assertFalse(report["passed"])
        self.assertIn("heartbeat-regression", report["failureKinds"])

    def test_late_terminal_is_false_timeout_and_not_ordinary_success(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 60, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ], task_timeout_ms=50)

        self.assertFalse(report["passed"])
        self.assertEqual(report["falseTimeout"]["count"], 1)
        self.assertEqual(report["falseTimeout"]["taskIds"], ["task-1"])
        self.assertEqual(report["taskOutcomes"]["lateTerminal"], 1)
        self.assertEqual(report["taskOutcomes"]["succeeded"], 0)

    def test_complete_lifecycle_reports_direct_audit_fields_and_samples(self) -> None:
        report = self._run([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 0, "queueTaskIds": []},
            {"atMs": 10, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 100, "handles": 20, "threads": 4, "heartbeat": 1},
            {"atMs": 15, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 20, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 25, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
            {"atMs": 30, "type": "metadata", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "queueDepth": 0, "queueTaskIds": []},
            {"atMs": 35, "type": "resource", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "rssMb": 101, "handles": 20, "threads": 4, "heartbeat": 2},
            {"atMs": 40, "type": "restart-checkpoint", "deviceId": "virtual-1", "epoch": "e1", "pid": 10, "taskIds": []},
            {"atMs": 45, "type": "restart-reconcile", "deviceId": "virtual-1", "previousEpoch": "e1", "epoch": "e1", "pid": 11, "taskIds": []},
        ], commit="abc123", artifact_hashes={"launcher": "sha256:123"})

        self.assertTrue(report["passed"])
        self.assertEqual(report["profile"], "lifecycle")
        self.assertEqual(report["evidenceMode"], "virtual")
        self.assertEqual(report["fixture"]["virtual"], True)
        self.assertEqual(report["fixture"]["safe"], True)
        self.assertEqual(report["fixture"]["sideEffectFree"], True)
        self.assertEqual(report["provenanceSummary"], {
            "unknown": 0,
            "virtual": 1,
            "physicalAttested": 0,
        })
        self.assertEqual(report["realDeviceEligibility"]["gateProven"], False)
        self.assertEqual(report["devices"][0]["provenance"], "virtual")
        self.assertEqual(report["devices"][0]["realDeviceEligible"], False)
        self.assertEqual(report["commit"], "abc123")
        self.assertEqual(report["artifactHashes"]["launcher"], "sha256:123")
        self.assertEqual(report["stages"]["submit"], 1)
        self.assertEqual(report["stages"]["progress"], 1)
        self.assertEqual(report["stages"]["terminal"], 1)
        self.assertEqual(report["stages"]["restartCheckpoint"], 1)
        self.assertEqual(report["stages"]["restartReconcile"], 1)
        self.assertEqual(report["stages"]["metadataSamples"], 2)
        self.assertEqual(report["stages"]["resourceSamples"], 2)
        self.assertEqual(len(report["samples"]["metadata"]), 2)
        self.assertEqual(report["samples"]["metadata"][0]["queueDepth"], 0)
        self.assertEqual(len(report["samples"]["resources"]), 2)
        self.assertEqual(report["samples"]["resources"][0]["pid"], 10)
        self.assertEqual(report["samples"]["resources"][0]["handles"], 20)
        self.assertIn("failureRate", report["summary"])
        self.assertIn("p50Ms", report["summary"])
        self.assertIn("p95Ms", report["summary"])
        self.assertIn("successRate", report["recovery"])

    def test_cli_lifecycle_requires_fixture_and_virtual_fixture_writes_honest_report(self) -> None:
        launcher_root = Path(__file__).resolve().parents[2]
        script = launcher_root / "scripts" / "loom-matrix-soak.py"
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

        missing = subprocess.run(
            [sys.executable, str(script), "--profile", "lifecycle"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("fixture", missing.stderr + missing.stdout)

        fixture = self._fixture([
            {"atMs": 0, "type": "device", "deviceId": "virtual-1", "online": True, "epoch": "e1", "pid": 10},
            {"atMs": 5, "type": "submit", "deviceId": "virtual-1", "taskId": "task-1", "epoch": "e1"},
            {"atMs": 10, "type": "progress", "deviceId": "virtual-1", "taskId": "task-1", "progress": 50, "heartbeat": 1, "epoch": "e1"},
            {"atMs": 15, "type": "terminal", "deviceId": "virtual-1", "taskId": "task-1", "status": "succeeded", "epoch": "e1"},
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "fixture.json"
            report_path = Path(temp_dir) / "report.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--profile", "lifecycle",
                    "--fixture", str(fixture_path),
                    "--max-resource-growth-mb", "50",
                    "--max-handle-growth", "100",
                    "--max-thread-growth", "6",
                    "--report", str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["profile"], "lifecycle")
        expected_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=launcher_root, text=True, encoding="utf-8"
        ).strip()
        source_paths = (
            launcher_root / "python" / "core" / "matrix_soak.py",
            launcher_root / "scripts" / "loom-matrix-soak.py",
            launcher_root / "python" / "tests" / "test_matrix_soak.py",
            launcher_root / "docs" / "runbooks" / "agent-reliability-release-gates.md",
        )
        relative_source_paths = [path.relative_to(launcher_root).as_posix() for path in source_paths]
        source_status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *relative_source_paths],
            cwd=launcher_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        expected_dirty = bool(source_status.stdout.strip())
        expected_report_commit = f"{expected_commit}+dirty" if expected_dirty else expected_commit
        self.assertEqual(report["commit"], expected_report_commit)
        self.assertEqual(report["sourceIdentity"]["headCommit"], expected_commit)
        self.assertEqual(report["sourceIdentity"]["dirty"], expected_dirty)
        digest = hashlib.sha256()
        for path in source_paths:
            digest.update(path.relative_to(launcher_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        self.assertEqual(report["sourceIdentity"]["fingerprint"], "sha256:" + digest.hexdigest())
        self.assertEqual(report["fixture"]["virtual"], True)
        self.assertEqual(report["fixture"]["safe"], True)
        self.assertEqual(report["fixture"]["sideEffectFree"], True)
        self.assertEqual(report["resourceGrowth"]["thresholds"], {
            "rssMb": 50.0,
            "handles": 100.0,
            "threads": 6.0,
        })
        self.assertEqual(report["provenanceSummary"]["virtual"], 1)
        self.assertEqual(report["realDeviceEligibility"]["gateProven"], False)
        self.assertEqual(report["realDeviceGate"]["executed"], False)
        self.assertIn("2-device/20-round", report["realDeviceGate"]["notExecuted"])
        self.assertIn("10-device/7200-second", report["realDeviceGate"]["notExecuted"])

    def test_source_identity_detects_clean_and_dirty_real_git_worktree(self) -> None:
        launcher_root = Path(__file__).resolve().parents[2]
        script = launcher_root / "scripts" / "loom-matrix-soak.py"
        spec = importlib.util.spec_from_file_location("loom_matrix_soak_identity_test", script)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        cli_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli_module)

        relative_paths = (
            Path("python/core/matrix_soak.py"),
            Path("scripts/loom-matrix-soak.py"),
            Path("python/tests/test_matrix_soak.py"),
            Path("docs/runbooks/agent-reliability-release-gates.md"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            source_paths = tuple(repository / relative for relative in relative_paths)
            for index, path in enumerate(source_paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"source-{index}\n", encoding="utf-8")

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                )
                return completed.stdout.strip()

            def expected_fingerprint() -> str:
                digest = hashlib.sha256()
                for path, relative in zip(source_paths, relative_paths):
                    digest.update(relative.as_posix().encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(path.read_bytes())
                    digest.update(b"\0")
                return "sha256:" + digest.hexdigest()

            git("init", "--quiet")
            git("config", "user.email", "wr06-test@example.invalid")
            git("config", "user.name", "WR06 Test")
            git("add", ".")
            git("commit", "--quiet", "-m", "baseline")
            head_commit = git("rev-parse", "HEAD")

            cli_module.ROOT = repository
            cli_module.SOURCE_PATHS = source_paths
            clean_identity = cli_module._current_source_identity()
            self.assertEqual(clean_identity["commit"], head_commit)
            self.assertEqual(clean_identity["headCommit"], head_commit)
            self.assertIs(clean_identity["dirty"], False)
            self.assertEqual(clean_identity["fingerprint"], expected_fingerprint())

            source_paths[0].write_text("source-dirty\n", encoding="utf-8")
            dirty_identity = cli_module._current_source_identity()
            self.assertEqual(dirty_identity["commit"], head_commit + "+dirty")
            self.assertEqual(dirty_identity["headCommit"], head_commit)
            self.assertIs(dirty_identity["dirty"], True)
            self.assertEqual(dirty_identity["fingerprint"], expected_fingerprint())


if __name__ == "__main__":
    unittest.main()
