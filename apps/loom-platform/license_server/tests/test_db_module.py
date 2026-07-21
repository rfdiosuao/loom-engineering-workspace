from __future__ import annotations

import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from test_license_flow import load_server


class DatabaseModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_connect_initializes_schema_idempotently(self) -> None:
        with self.server.connect() as first:
            first.execute("insert into settings (key, value_json, updated_at) values ('proof', '{}', 'now')")
            first.commit()
        with self.server.connect() as second:
            self.assertEqual(1, second.execute("select count(*) from settings where key='proof'").fetchone()[0])

    def test_online_backup_preserves_authorization_rows(self) -> None:
        code = self.server.create_code_records(
            count=1, licensee="Backup", edition="pro", features=["openclaw"],
            expires="2099-01-01", max_activations=1,
        )[0]
        backup = Path(self.server.make_db_backup("module-test"))
        self.assertTrue(backup.is_file())
        with closing(sqlite3.connect(backup)) as copied:
            self.assertEqual(1, copied.execute("select count(*) from codes where full_code=?", (code,)).fetchone()[0])

    def test_server_facades_keep_database_and_signing_isolated_per_load(self) -> None:
        first_public_key = self.server.public_key_b64()
        with tempfile.TemporaryDirectory() as second_directory:
            second_server = load_server(Path(second_directory))
            second_public_key = second_server.public_key_b64()

            self.assertNotEqual(first_public_key, second_public_key)
            self.assertEqual(first_public_key, self.server.public_key_b64())
            payload = {"licensee": "First", "edition": "pro"}
            signed = self.server.sign_license(payload)
            Ed25519PublicKey.from_public_bytes(base64.b64decode(first_public_key)).verify(
                base64.b64decode(signed["signature"]),
                self.server.canonical(payload),
            )

            self.server.create_code_records(
                count=1, licensee="First", edition="pro", features=["openclaw"],
                expires="2099-01-01", max_activations=1,
            )
            with self.server.connect() as first:
                self.assertEqual(1, first.execute("select count(*) from codes").fetchone()[0])
            with second_server.connect() as second:
                self.assertEqual(0, second.execute("select count(*) from codes").fetchone()[0])

    def test_connect_closes_connection_when_initialization_fails(self) -> None:
        from luming_license import db

        connection = MagicMock()
        with patch.object(db.sqlite3, "connect", return_value=connection), patch.object(
            db, "init_db", side_effect=RuntimeError("initialization failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                self.server.connect()
        connection.close.assert_called_once_with()

    def test_backup_closes_source_and_target_when_backup_fails(self) -> None:
        from luming_license import db

        class Source:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.close()
                return False

            def backup(self, target):
                raise RuntimeError("backup failed")

            def close(self):
                self.closed = True

        class Target:
            closed = False

            def close(self):
                self.closed = True

        source = Source()
        target = Target()
        with patch.object(db.os.path, "exists", return_value=True), patch.object(
            db, "connect", return_value=source
        ), patch.object(db.sqlite3, "connect", return_value=target):
            with self.assertRaisesRegex(RuntimeError, "backup failed"):
                db.make_db_backup("cleanup", settings=self.server.SETTINGS, defaults=self.server.DB_DEFAULTS)
        self.assertTrue(source.closed)
        self.assertTrue(target.closed)
