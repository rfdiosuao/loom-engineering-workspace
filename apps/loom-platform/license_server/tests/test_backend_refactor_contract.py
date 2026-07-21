from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_license_flow import load_server


COMPAT_EXPORTS = {
    "Handler", "ActivationError", "connect", "init_db", "make_db_backup",
    "create_account_record", "create_admin_session", "create_code_records",
    "get_code_rows", "get_code_secret_rows", "get_activation_rows",
    "get_plan_rows", "client_public_config", "update_public_settings",
    "activate_code", "find_member_license", "publish_relay_enqueue",
    "publish_relay_claim", "publish_relay_complete", "publish_relay_status",
    "main", "serve",
}

EXPECTED_TABLE_COLUMNS = {
    "codes": {"code_hash", "full_code", "licensee", "expires", "max_activations", "owner_account_id"},
    "activations": {"id", "code_hash", "install_id", "device_id", "license_json", "activated_at"},
    "accounts": {"id", "username", "password_hash", "role", "status"},
    "admin_sessions": {"session_hash", "account_id", "expires_at", "revoked_at"},
    "plans": {"plan_key", "features_json", "duration_days", "disabled"},
    "settings": {"key", "value_json", "updated_at"},
    "audit_logs": {"id", "action", "before_json", "after_json", "created_at"},
    "publish_relay_packets": {"packet_id", "status", "packet_json", "lease_id", "attempts"},
}
REPORT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "validation"
    / "LOOM_LICENSE_BACKEND_MODULAR_20260714.md"
)


class BackendRefactorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_server_facade_exports_stable_names(self) -> None:
        self.assertEqual(set(), COMPAT_EXPORTS - set(dir(self.server)))

    def test_schema_keeps_required_columns(self) -> None:
        with self.server.connect() as connection:
            for table, required in EXPECTED_TABLE_COLUMNS.items():
                actual = {row[1] for row in connection.execute(f"pragma table_info({table})")}
                self.assertEqual(set(), required - actual, table)


class ValidationReportContractTests(unittest.TestCase):
    def test_rollback_disarms_guard_before_best_effort_fallback_cleanup(self) -> None:
        report = REPORT_PATH.read_text(encoding="utf-8")
        rollback = report.split("## Preflight-First Program Rollback", 1)[1]
        health = rollback.index("curl -fsS http://localhost:18791/health")
        disarm = rollback.index("switched=0", health)
        disable_trap = rollback.index("trap - EXIT", disarm)
        server_cleanup = rollback.index(
            'rm -f -- "$base/.server.py.pre-rollback"', health
        )
        package_cleanup = rollback.index(
            'rm -rf -- "$base/.luming_license.pre-rollback"', health
        )

        self.assertLess(health, disarm)
        self.assertLess(disarm, disable_trap)
        self.assertLess(disable_trap, server_cleanup)
        self.assertLess(disable_trap, package_cleanup)
        self.assertIn("|| true", rollback[server_cleanup:package_cleanup])
