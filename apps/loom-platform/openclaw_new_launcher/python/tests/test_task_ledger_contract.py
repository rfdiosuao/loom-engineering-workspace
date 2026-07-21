from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class TaskLedgerContractTests(unittest.TestCase):
    def test_cli_writes_task_ledger_and_action_trace_to_user_data(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                code, payload = dispatch(
                    [
                        "phone",
                        "read",
                        "--prompt",
                        "读取当前屏幕 sk-test-token",
                        "--json",
                        "--dry-run",
                    ],
                    base_path=temp_dir,
                )

                ledger_path = os.path.join(temp_dir, "loom-task-ledger.jsonl")
                trace_path = os.path.join(temp_dir, "loom-action-trace.jsonl")
                with open(ledger_path, "r", encoding="utf-8") as handle:
                    ledger = json.loads(handle.readline())
                with open(trace_path, "r", encoding="utf-8") as handle:
                    trace = json.loads(handle.readline())

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(ledger["taskId"].startswith("task_"))
        self.assertEqual(ledger["source"], "cli")
        self.assertEqual(ledger["tool"], "cli:phone read")
        self.assertEqual(ledger["actionTraceId"], trace["traceId"])
        self.assertEqual(trace["taskId"], ledger["taskId"])
        self.assertIn("steps", trace)
        serialized = json.dumps({"ledger": ledger, "trace": trace}, ensure_ascii=False)
        self.assertNotIn("sk-test-token", serialized)

    def test_mcp_call_is_recorded_as_mcp_source_in_task_ledger(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                result = loom_mcp.call_tool(
                    "loom_status",
                    {"dryRun": True},
                    permission="read",
                    base_path=temp_dir,
                )
                ledger_path = os.path.join(temp_dir, "loom-task-ledger.jsonl")
                with open(ledger_path, "r", encoding="utf-8") as handle:
                    ledger = json.loads(handle.readline())

        self.assertFalse(result.get("isError", False))
        self.assertEqual(ledger["source"], "mcp")
        self.assertEqual(ledger["tool"], "mcp:status")
        self.assertTrue(ledger["ok"])

    def test_repeated_phone_template_calls_update_template_optimizer(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                for _ in range(2):
                    code, payload = dispatch(
                        [
                            "phone",
                            "template-task",
                            "--template",
                            "screen-summary",
                            "--json",
                            "--dry-run",
                        ],
                        base_path=temp_dir,
                    )
                    self.assertEqual(code, 0)
                    self.assertTrue(payload["ok"])

                optimizer_path = os.path.join(temp_dir, "loom-template-optimizer.json")
                with open(optimizer_path, "r", encoding="utf-8") as handle:
                    optimizer = json.load(handle)

        self.assertEqual(optimizer["schema"], "loom.template_optimizer.v1")
        self.assertGreaterEqual(len(optimizer["candidates"]), 1)
        candidate = optimizer["candidates"][0]
        self.assertEqual(candidate["successCount"], 2)
        self.assertIn("suggestedTemplate", candidate)
        self.assertEqual(candidate["suggestedTemplate"]["command"], "phone template-task")
        self.assertTrue(candidate["suggestedTemplate"]["requiresConfirmation"])

    def test_logs_ledger_reads_task_ledger(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                dispatch(["status", "--json"], base_path=temp_dir)
                code, payload = dispatch(["logs", "ledger", "--limit", "5", "--json"], base_path=temp_dir)

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["path"].endswith("loom-task-ledger.jsonl"))
        self.assertGreaterEqual(len(payload["data"]["lines"]), 1)


if __name__ == "__main__":
    unittest.main()
