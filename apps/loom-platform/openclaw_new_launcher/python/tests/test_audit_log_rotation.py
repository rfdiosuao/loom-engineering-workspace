from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class AuditLogRotationTests(unittest.TestCase):
    def test_rotation_is_bounded_and_tail_spans_archives(self) -> None:
        from core.audit_log import append_jsonl, archive_paths, tail_lines

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "audit.jsonl")
            for index in range(20):
                append_jsonl(path, json.dumps({"index": index, "padding": "x" * 48}), max_bytes=256, archive_count=3)

            paths = archive_paths(path, 3, oldest_first=True)
            lines = tail_lines(path, 5, archive_count=3)

        self.assertLessEqual(len(paths), 4)
        self.assertEqual([json.loads(line)["index"] for line in lines], [15, 16, 17, 18, 19])

    def test_cli_ledger_reads_records_from_rotated_archives(self) -> None:
        from loom_cli import append_audit_record, dispatch

        with tempfile.TemporaryDirectory() as root:
            environment = {
                "LOOM_AUDIT_DIR": root,
                "LOOM_AUDIT_MAX_BYTES": "256",
                "LOOM_AUDIT_ARCHIVE_COUNT": "4",
            }
            with patch.dict(os.environ, environment):
                for index in range(12):
                    append_audit_record("loom-task-ledger.jsonl", {"index": index, "padding": "y" * 64})
                code, payload = dispatch(["logs", "ledger", "--limit", "4", "--json"])

        self.assertEqual(code, 0)
        indexes = [json.loads(line)["index"] for line in payload["data"]["lines"]]
        self.assertEqual(indexes, [8, 9, 10, 11])

    def test_rotation_preserves_central_redaction(self) -> None:
        from loom_cli import append_audit_record

        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": root, "LOOM_AUDIT_MAX_BYTES": "256"}):
                path = append_audit_record("mcp-audit.jsonl", {"apiKey": "sk-secret-value", "token": "secret-token"})
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()

        self.assertNotIn("sk-secret-value", text)
        self.assertNotIn("secret-token", text)


if __name__ == "__main__":
    unittest.main()
