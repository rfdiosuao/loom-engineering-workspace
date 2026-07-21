from __future__ import annotations

import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class LoomSchedulerContractTests(unittest.TestCase):
    def test_scheduler_add_list_and_cancel_are_structured(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            add_code, add_payload = dispatch(
                [
                    "schedule",
                    "add",
                    "--name",
                    "daily status",
                    "--command",
                    "status",
                    "--at",
                    "2026-07-01T09:00:00+08:00",
                    "--permission",
                    "automation",
                    "--json",
                ],
                base_path=temp_dir,
            )
            self.assertEqual(add_code, 0)
            task_id = add_payload["data"]["task"]["id"]

            list_code, list_payload = dispatch(["schedule", "list", "--json"], base_path=temp_dir)
            self.assertEqual(list_code, 0)
            self.assertEqual(list_payload["data"]["tasks"][0]["id"], task_id)

            cancel_code, cancel_payload = dispatch(
                ["schedule", "cancel", "--id", task_id, "--permission", "automation", "--json"],
                base_path=temp_dir,
            )
            self.assertEqual(cancel_code, 0)
            self.assertFalse(cancel_payload["data"]["task"]["enabled"])

    def test_scheduler_rejects_unknown_commands(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            code, payload = dispatch(
                [
                    "schedule",
                    "add",
                    "--name",
                    "bad",
                    "--command",
                    "desktop rpa delete everything",
                    "--permission",
                    "automation",
                    "--json",
                ],
                base_path=temp_dir,
            )

        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "invalid_schedule_command")

    def test_scheduler_allows_safe_phone_read_screen_alias(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            code, payload = dispatch(
                [
                    "schedule",
                    "add",
                    "--name",
                    "phone read",
                    "--command",
                    "phone read-screen",
                    "--every",
                    "PT10M",
                    "--permission",
                    "automation",
                    "--json",
                    "--dry-run",
                ],
                base_path=temp_dir,
            )

        self.assertEqual(code, 0)
        self.assertTrue(payload["data"]["dryRun"])
        self.assertEqual(payload["data"]["task"]["command"], "phone read-screen")


if __name__ == "__main__":
    unittest.main()
