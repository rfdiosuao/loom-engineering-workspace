from __future__ import annotations

import os
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
