from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from test_license_flow import load_server


MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_db_preservation.py"
SPEC = importlib.util.spec_from_file_location("verify_db_preservation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

REQUIRED_TABLES = (
    "codes",
    "activations",
    "accounts",
    "admin_sessions",
    "invite_codes",
    "audit_logs",
    "settings",
    "beta_claims",
    "prompt_templates",
    "account_gateway_settings",
    "publish_relay_packets",
    "plans",
)


def create_real_database(root: Path) -> Path:
    root.mkdir()
    server = load_server(root)
    with server.connect():
        pass
    return Path(server.SETTINGS.db_path)


def create_matching_pair(root: Path) -> tuple[Path, Path]:
    before = create_real_database(root / "server")
    after = root / "after.db"
    shutil.copy2(before, after)
    return before, after


def insert_code_record(path: Path, code_hash: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            insert into codes (
                code_hash, code_label, licensee, edition, features_json,
                expires, created_at
            ) values (?, 'test-label', 'test-licensee', 'TEST', '[]',
                      '2099-01-01', '2026-01-01T00:00:00+00:00')
            """,
            (code_hash,),
        )
        connection.commit()


class VerifyDatabasePreservationTests(unittest.TestCase):
    def test_nonexistent_input_fails_without_creating_a_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "missing-before.db"
            after = root / "missing-after.db"

            with self.assertRaises(ValueError):
                MODULE.verify_databases(str(before), str(after))

            self.assertFalse(before.exists())
            self.assertFalse(after.exists())

    def test_empty_regular_files_fail_without_being_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.db"
            after = root / "after.db"
            before.touch()
            after.touch()

            with self.assertRaises(ValueError):
                MODULE.verify_databases(str(before), str(after))

            self.assertEqual(0, before.stat().st_size)
            self.assertEqual(0, after.stat().st_size)

    def test_rejects_same_path_for_before_and_after(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = create_real_database(Path(directory) / "server")

            with self.assertRaisesRegex(ValueError, "same file"):
                MODULE.verify_databases(str(database), str(database))

    def test_rejects_hardlinked_before_and_after(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = create_real_database(root / "server")
            after = root / "hardlink.db"
            try:
                os.link(before, after)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable: {error.__class__.__name__}")

            with self.assertRaisesRegex(ValueError, "same file"):
                MODULE.verify_databases(str(before), str(after))

    def test_all_required_table_names_with_bogus_columns_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.db"
            after = root / "after.db"
            for path in (before, after):
                with closing(sqlite3.connect(path)) as connection:
                    for table in REQUIRED_TABLES:
                        connection.execute(f'create table "{table}" (bogus text)')
                    connection.commit()

            with self.assertRaisesRegex(ValueError, "required columns"):
                MODULE.verify_databases(str(before), str(after))

    def test_rejects_authorization_table_in_expected_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before, after = create_matching_pair(Path(directory))

            with self.assertRaisesRegex(ValueError, "unsupported expected-change"):
                MODULE.verify_databases(
                    str(before),
                    str(after),
                    expected_changes=("codes",),
                )

    def test_missing_canonical_required_columns_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before, after = create_matching_pair(Path(directory))
            with closing(sqlite3.connect(after)) as connection:
                connection.execute("drop table settings")
                connection.execute("create table settings (key text primary key)")
                connection.commit()

            with self.assertRaisesRegex(ValueError, "required columns"):
                MODULE.verify_databases(str(before), str(after))

    def test_read_only_setup_failure_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "database.db"
            path.touch()
            connection = Mock()
            connection.execute.side_effect = sqlite3.OperationalError("setup failed")

            with patch.object(MODULE.sqlite3, "connect", return_value=connection):
                with self.assertRaises(MODULE.DatabaseVerificationError):
                    MODULE._open_read_only(path, "test")

            connection.close.assert_called_once_with()

    def test_real_matching_database_copy_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before, after = create_matching_pair(Path(directory))

            comparisons, failures = MODULE.verify_databases(str(before), str(after))

            self.assertEqual([], failures)
            self.assertEqual(
                set(REQUIRED_TABLES),
                {item.table for item in comparisons},
            )
            self.assertTrue(all(item.equal for item in comparisons))

    def test_allows_plan_change_when_authorization_data_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before, after = create_matching_pair(Path(directory))
            with closing(sqlite3.connect(after)) as connection:
                connection.execute(
                    "update plans set features_json = ? where plan_key = 'monthly'",
                    ('["openclaw","matrix.devices"]',),
                )
                connection.commit()

            comparisons, failures = MODULE.verify_databases(str(before), str(after))

            self.assertEqual([], failures)
            plan = next(item for item in comparisons if item.table == "plans")
            self.assertTrue(plan.expected_change)
            self.assertFalse(plan.equal)

    def test_rejects_changed_authorization_data_without_printing_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before, after = create_matching_pair(Path(directory))
            insert_code_record(before, "hash-a")
            insert_code_record(after, "hash-b")

            _comparisons, failures = MODULE.verify_databases(str(before), str(after))

            self.assertEqual(["codes"], failures)


if __name__ == "__main__":
    unittest.main()
