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


class AuditCredentialRedactionTests(unittest.TestCase):
    def test_cli_and_task_audits_redact_login_license_and_bind_credentials(self) -> None:
        from loom_cli import dispatch

        cases = [
            (
                [
                    "account",
                    "login-code",
                    "--email",
                    "person@example.com",
                    "--code",
                    "LOGIN-246810",
                ],
                "LOGIN-246810",
            ),
            (
                ["license", "activate", "--code", "LICENSE-ALPHA-987"],
                "LICENSE-ALPHA-987",
            ),
            (
                ["account", "bind-ticket", "--ticket", "ocb_BIND-TICKET-654"],
                "ocb_BIND-TICKET-654",
            ),
            (
                ["account", "login-code", "person@example.com", "LOGIN-POSITIONAL-112"],
                "LOGIN-POSITIONAL-112",
            ),
            (
                ["license", "activate", "LICENSE-POSITIONAL-223"],
                "LICENSE-POSITIONAL-223",
            ),
            (
                ["account", "bind-ticket", "--code=ocb_BIND-EQUALS-334"],
                "ocb_BIND-EQUALS-334",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                for argv, _secret in cases:
                    code, payload = dispatch(
                        [*argv, "--permission", "control", "--json", "--dry-run"],
                        base_path=temp_dir,
                    )
                    self.assertEqual(code, 0)
                    self.assertTrue(payload["ok"])

            for filename in ("loom-cli-audit.jsonl", "loom-task-ledger.jsonl"):
                with self.subTest(filename=filename):
                    with open(os.path.join(temp_dir, filename), "r", encoding="utf-8") as handle:
                        records = [json.loads(line) for line in handle if line.strip()]
                    serialized = json.dumps(records, ensure_ascii=False)
                    for _argv, secret in cases:
                        self.assertNotIn(secret, serialized)
                    self.assertEqual(len(records), len(cases))
                    self.assertTrue(
                        all(
                            any("***" in str(item) for item in record["paramSummary"])
                            for record in records
                        )
                    )

    def test_central_audit_redaction_handles_mcp_credentials_contextually(self) -> None:
        from loom_cli import append_audit_record

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                path = append_audit_record(
                    "mcp-audit.jsonl",
                    {
                        "tool": "loom_account_login_code",
                        "paramSummary": {"email": "person@example.com", "code": "LOGIN-135790"},
                        "error": "",
                    },
                )
            with open(path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())

        self.assertEqual(record["paramSummary"]["code"], "***")
        self.assertNotIn("LOGIN-135790", json.dumps(record, ensure_ascii=False))

    def test_central_audit_redaction_preserves_ordinary_diagnostic_codes(self) -> None:
        from loom_cli import append_audit_record

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                path = append_audit_record(
                    "diagnostic-audit.jsonl",
                    {
                        "tool": "cli:diagnostics run",
                        "paramSummary": {"code": "PYTHON_RUNTIME_MISSING", "scope": "runtime"},
                        "error": {"code": "diagnostic_failed"},
                    },
                )
            with open(path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())

        self.assertEqual(record["paramSummary"]["code"], "PYTHON_RUNTIME_MISSING")
        self.assertEqual(record["error"]["code"], "diagnostic_failed")


if __name__ == "__main__":
    unittest.main()
