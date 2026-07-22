from __future__ import annotations

import json
import os
import sys
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ReleaseSmokeTests(unittest.TestCase):
    def test_strict_smoke_runs_provider_matrix_and_phone_checks(self) -> None:
        from core.release_smoke import run_release_smoke

        commands: list[list[str]] = []

        def runner(command, _timeout):
            commands.append(list(command))
            if "phone" in command:
                data = {"results": [{"ok": True, "status": {"online": True}}, {"ok": True, "status": {"online": True}}]}
            else:
                data = {"ready": True}
            return 0, json.dumps({"ok": True, "command": command[2], "data": data}), ""

        report = run_release_smoke(
            "loom_cli.py",
            require_provider=True,
            require_matrix=True,
            require_phone_count=2,
            command_runner=runner,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["total"], 5)
        self.assertTrue(any("verify" in command for command in commands))

    def test_phone_requirement_fails_with_actionable_count(self) -> None:
        from core.release_smoke import run_release_smoke

        def runner(command, _timeout):
            data = {"results": [{"ok": True, "status": {"online": True}}]} if "phone" in command else {}
            return 0, json.dumps({"ok": True, "data": data}), ""

        report = run_release_smoke(
            "loom_cli.py",
            require_phone_count=2,
            command_runner=runner,
        )

        self.assertFalse(report["passed"])
        phone = next(item for item in report["checks"] if item["name"] == "phone_status")
        self.assertEqual(phone["observedDevices"], 1)
        self.assertIn("至少 2 台", phone["error"])

    def test_report_redacts_provider_credentials(self) -> None:
        from core.release_smoke import run_release_smoke

        def runner(_command, _timeout):
            return 0, json.dumps({"ok": True, "data": {"apiKey": "sk-secret", "token": "secret-token"}}), ""

        report = run_release_smoke("loom_cli.py", command_runner=runner)
        serialized = json.dumps(report, ensure_ascii=False)

        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_nested_wire_verification_failure_fails_release_gate(self) -> None:
        from core.release_smoke import run_release_smoke

        def runner(command, _timeout):
            result = {"ok": False, "targets": {"codex": {"ok": False}}} if "verify" in command else {}
            return 0, json.dumps({"ok": True, "data": {"result": result}}), ""

        report = run_release_smoke("loom_cli.py", require_provider=True, command_runner=runner)

        self.assertFalse(report["passed"])
        provider = next(item for item in report["checks"] if item["name"] == "provider_verify")
        self.assertFalse(provider["passed"])

    def test_direct_business_failure_preserves_actionable_error(self) -> None:
        from core.release_smoke import run_release_smoke

        def runner(_command, _timeout):
            return 0, json.dumps({"ok": True, "data": {"ok": False, "error": "模型账号已过期"}}), ""

        report = run_release_smoke("loom_cli.py", command_runner=runner)

        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][0]["error"], "模型账号已过期")


if __name__ == "__main__":
    unittest.main()
