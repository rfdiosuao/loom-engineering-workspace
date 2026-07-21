from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _support import LICENSE_SERVER_ROOT
from luming_license import db

SERVER_PATH = LICENSE_SERVER_ROOT / "server.py"


def load_server(temp_dir: Path):
    private_key = Ed25519PrivateKey.generate()
    raw_key = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = temp_dir / "private_key.b64"
    key_file.write_text(base64.b64encode(raw_key).decode("ascii"), encoding="utf-8")

    os.environ["LICENSE_DB"] = str(temp_dir / "license.db")
    os.environ["LICENSE_BACKUP_DIR"] = str(temp_dir / "backups")
    os.environ["LICENSE_PRIVATE_KEY_FILE"] = str(key_file)
    os.environ["LICENSE_ADMIN_TOKEN"] = "test-admin-token"
    os.environ["MEMBER_GATEWAY_BASE_URL"] = ""
    os.environ["MEMBER_GATEWAY_IMAGE_BASE_URL"] = ""
    os.environ["MEMBER_GATEWAY_VIDEO_BASE_URL"] = ""
    os.environ["MEMBER_GATEWAY_TOKEN"] = ""
    os.environ["MEMBER_GATEWAY_IMAGE_TOKEN"] = ""
    os.environ["MEMBER_GATEWAY_VIDEO_TOKEN"] = ""
    os.environ["OPENCLAW_PUBLISH_RELAY_TOKEN"] = "test-relay-token"
    os.environ["LICENSE_PUBLIC_URL"] = "https://license.heang.top/"
    os.environ["LICENSE_SUPPORT_URL"] = "https://license.heang.top/"

    module_name = f"openclaw_license_server_test_{next(tempfile._get_candidate_names())}"
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LicenseServerFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.server = load_server(self.temp_path)
        self._http_base_url = ""

    def tearDown(self) -> None:
        self.doCleanups()
        self.temp.cleanup()

    def expires(self) -> str:
        return (date.today() + timedelta(days=365)).isoformat()

    def test_code_inventory_is_masked_and_secret_rows_are_scoped(self) -> None:
        merchant, _ = self.server.create_account_record(
            username="merchant-secret",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="merchant-other",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        code = self.server.create_code_records(
            count=1,
            licensee="Secret Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        merchant_context = {"accountId": merchant["accountId"], "role": "merchant"}
        other_context = {"accountId": other["accountId"], "role": "merchant"}

        inventory = self.server.get_code_rows(merchant_context)
        self.assertEqual(len(inventory), 1)
        self.assertNotIn("fullCode", inventory[0])
        self.assertNotIn(code, json.dumps(inventory, ensure_ascii=False))

        secrets = self.server.get_code_secret_rows([code_hash_value], merchant_context)
        self.assertEqual(secrets[0]["code"], code)
        with self.assertRaises(self.server.ActivationError) as denied:
            self.server.get_code_secret_rows([code_hash_value], other_context)
        self.assertEqual(denied.exception.status, 404)

    def test_code_secret_rows_reject_empty_selection(self) -> None:
        with self.assertRaises(self.server.ActivationError) as empty:
            self.server.get_code_secret_rows([])
        self.assertEqual(empty.exception.status, 400)

    def test_code_secret_rows_export_limit_is_500(self) -> None:
        valid_hashes = [f"{index:064x}" for index in range(501)]

        with self.assertRaises(self.server.ActivationError) as within_limit:
            self.server.get_code_secret_rows(valid_hashes[:500])
        self.assertEqual(within_limit.exception.status, 404)

        with self.assertRaises(self.server.ActivationError) as over_limit:
            self.server.get_code_secret_rows(valid_hashes)
        self.assertEqual(over_limit.exception.status, 400)

    def test_reveal_and_export_require_confirmation_and_write_redacted_audit(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-secret",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Export Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=admin["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        headers = {"X-Admin-Session": session}

        self.request_json(
            "POST",
            "/admin/api/codes/reveal",
            payload={"codeHash": code_hash_value, "confirmation": ""},
            headers=headers,
            expected_status=400,
        )
        revealed = self.request_json(
            "POST",
            "/admin/api/codes/reveal",
            payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
            headers=headers,
        )
        self.assertEqual(revealed["code"], code)

        self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": [code_hash_value], "confirmation": ""},
            headers=headers,
            expected_status=400,
        )
        exported = self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": [code_hash_value], "confirmation": "EXPORT"},
            headers=headers,
        )
        self.assertEqual(exported["codes"][0]["code"], code)

        logs = self.server.get_audit_rows(20)
        actions = {row["action"] for row in logs}
        self.assertTrue({"codes.reveal", "codes.export"}.issubset(actions))
        self.assertNotIn(code, json.dumps(logs, ensure_ascii=False))

    def test_reveal_and_export_routes_keep_base_secret_facade_call_shape(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-base-secret-facade",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Base Facade Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=admin["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        original_get_secrets = self.server.get_code_secret_rows
        calls: list[tuple[list[object], dict[str, object] | None]] = []

        def base_get_secrets(
            code_hashes: list[object],
            current_account: dict[str, object] | None = None,
        ) -> list[dict[str, object]]:
            calls.append((code_hashes, current_account))
            return original_get_secrets(code_hashes, current_account)

        self.server.get_code_secret_rows = base_get_secrets
        self.addCleanup(setattr, self.server, "get_code_secret_rows", original_get_secrets)
        headers = {"X-Admin-Session": session}

        revealed = self.request_json(
            "POST",
            "/admin/api/codes/reveal",
            payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
            headers=headers,
        )
        exported = self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": [code_hash_value], "confirmation": "EXPORT"},
            headers=headers,
        )

        self.assertEqual(code, revealed["code"])
        self.assertEqual(code, exported["codes"][0]["code"])
        self.assertEqual(2, len(calls))
        logs = self.server.get_audit_rows(20)
        self.assertEqual(1, sum(row["action"] == "codes.reveal" for row in logs))
        self.assertEqual(1, sum(row["action"] == "codes.export" for row in logs))
        self.assertNotIn(code, json.dumps(logs, ensure_ascii=False))

    def test_merchant_cannot_reveal_or_export_another_merchant_code(self) -> None:
        merchant_a, _ = self.server.create_account_record(
            username="merchant-a",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        merchant_b, _ = self.server.create_account_record(
            username="merchant-b",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        session_a, _ = self.server.create_admin_session(merchant_a["accountId"])
        session_b, _ = self.server.create_admin_session(merchant_b["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Merchant A Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant_a["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)

        for path, payload in (
            ("/admin/api/codes/reveal", {"codeHash": code_hash_value, "confirmation": "REVEAL"}),
            ("/admin/api/codes/export", {"codeHashes": [code_hash_value], "confirmation": "EXPORT"}),
        ):
            self.request_json(
                "POST",
                path,
                payload=payload,
                headers={"X-Admin-Session": session_b},
                expected_status=404,
            )

        revealed = self.request_json(
            "POST",
            "/admin/api/codes/reveal",
            payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
            headers={"X-Admin-Session": session_a},
        )
        self.assertEqual(revealed["code"], code)

    def test_merchant_mixed_code_export_is_rejected_without_partial_secrets(self) -> None:
        merchant, _ = self.server.create_account_record(
            username="merchant-mixed-export",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="merchant-mixed-export-other",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        session, _ = self.server.create_admin_session(merchant["accountId"])
        owned_code = self.server.create_code_records(
            count=1,
            licensee="Owned Export Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        other_code = self.server.create_code_records(
            count=1,
            licensee="Other Export Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=other["accountId"],
        )[0]

        response = self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={
                "codeHashes": [self.server.code_hash(owned_code), self.server.code_hash(other_code)],
                "confirmation": "EXPORT",
            },
            headers={"X-Admin-Session": session},
            expected_status=404,
        )

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertNotIn("codes", response)
        self.assertNotIn(owned_code, serialized)
        self.assertNotIn(other_code, serialized)

    def test_legacy_admin_token_can_reveal_and_export_any_merchant_code(self) -> None:
        merchant, _ = self.server.create_account_record(
            username="merchant-legacy-admin-access",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        code = self.server.create_code_records(
            count=1,
            licensee="Legacy Admin Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        headers = {"X-Admin-Token": "test-admin-token"}

        revealed = self.request_json(
            "POST",
            "/admin/api/codes/reveal",
            payload={"codeHash": code_hash_value, "confirmation": "REVEAL"},
            headers=headers,
        )
        exported = self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": [code_hash_value], "confirmation": "EXPORT"},
            headers=headers,
        )

        self.assertEqual(revealed["code"], code)
        self.assertEqual(exported["codes"][0]["code"], code)

    def test_code_export_http_limit_is_500(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-export-limit",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        headers = {"X-Admin-Session": session}
        valid_hashes = [f"{index:064x}" for index in range(501)]

        self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": valid_hashes[:500], "confirmation": "EXPORT"},
            headers=headers,
            expected_status=404,
        )
        self.request_json(
            "POST",
            "/admin/api/codes/export",
            payload={"codeHashes": valid_hashes, "confirmation": "EXPORT"},
            headers=headers,
            expected_status=400,
        )

    def test_reveal_and_export_do_not_return_secrets_when_audit_write_fails(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-audit-failure",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Audit Failure Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=admin["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        headers = {"X-Admin-Session": session}
        original_add_audit_log = self.server.add_audit_log

        def fail_audit_write(**_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

        self.server.add_audit_log = fail_audit_write
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        for path, payload, expected_error in (
            (
                "/admin/api/codes/reveal",
                {"codeHash": code_hash_value, "confirmation": "REVEAL"},
                "查看授权码失败",
            ),
            (
                "/admin/api/codes/export",
                {"codeHashes": [code_hash_value], "confirmation": "EXPORT"},
                "导出授权码失败",
            ),
        ):
            response = self.request_json(
                "POST",
                path,
                payload=payload,
                headers=headers,
                expected_status=500,
            )
            self.assertEqual(response["error"], expected_error)
            self.assertNotIn(code, json.dumps(response, ensure_ascii=False))

    def test_historical_audit_rows_redact_signed_license_and_member_response_tokens(self) -> None:
        code = "OC-PRO-HISTORICAL-SECRET-12345678"
        secrets_by_key = {
            "gatewayAccessToken": "historical-gateway-access-secret",
            "gatewayToken": "historical-gateway-secret",
            "gatewayImageAccessToken": "historical-gateway-image-access-secret",
            "gatewayVideoAccessToken": "historical-gateway-video-access-secret",
            "gatewayImageToken": "historical-gateway-image-secret",
            "gatewayVideoToken": "historical-gateway-video-secret",
            "accessToken": "historical-access-secret",
            "token": "historical-token-secret",
            "imageAccessToken": "historical-image-access-secret",
            "videoAccessToken": "historical-video-access-secret",
            "imageToken": "historical-image-secret",
            "videoToken": "historical-video-secret",
            "apiKey": "historical-api-key-secret",
            "sessionToken": "historical-session-token-secret",
        }
        signed_license = {
            key: secrets_by_key[key]
            for key in (
                "gatewayAccessToken",
                "gatewayToken",
                "gatewayImageAccessToken",
                "gatewayVideoAccessToken",
                "gatewayImageToken",
                "gatewayVideoToken",
            )
        }
        response = self.server.member_response(signed_license)
        response["gateway"].update(
            {
                key: secrets_by_key[key]
                for key in (
                    "accessToken",
                    "token",
                    "imageAccessToken",
                    "videoAccessToken",
                    "imageToken",
                    "videoToken",
                )
            }
        )
        response["member"]["apiKey"] = secrets_by_key["apiKey"]
        public_marker = "historical-public-token-count-marker"
        self.server.add_audit_log(
            action="legacy.secret",
            before={
                "fullCode": code,
                "signedLicense": signed_license,
            },
            after={
                "codes": [code],
                "memberResponse": response,
                "adminResponse": {"sessionToken": secrets_by_key["sessionToken"]},
                "metadata": {"tokenCount": public_marker},
            },
        )

        logs = self.server.get_audit_rows(20)
        serialized = json.dumps(logs, ensure_ascii=False)
        self.assertNotIn(code, serialized)
        for key, secret in secrets_by_key.items():
            self.assertNotIn(secret, serialized, key)
        self.assertIn("••••-12345678", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertIn(public_marker, serialized)

    def test_audit_facade_preserves_persisted_fields_and_descending_order(self) -> None:
        original_utc_now = self.server.utc_now
        timestamps = iter(("2030-01-02T03:04:05+00:00", "2030-01-02T03:04:06+00:00"))
        self.server.utc_now = lambda: next(timestamps)
        self.addCleanup(setattr, self.server, "utc_now", original_utc_now)

        self.server.add_audit_log(
            action="first.action",
            target_type="code",
            target_id="first-target",
            before={"z": 1, "gatewayToken": "first-secret"},
            after={"fullCode": "OC-PRO-AUDIT-12345678"},
            actor="admin#1",
            request_ip="203.0.113.8",
            backup_path="C:/backups/first.db",
        )
        self.server.add_audit_log(
            action="second.action",
            target_type="plan",
            target_id="second-target",
            before={"a": 2},
            after={"b": 3},
            actor="admin#2",
            request_ip="203.0.113.9",
            backup_path="C:/backups/second.db",
        )

        with self.server.connect() as conn:
            first = conn.execute("select * from audit_logs where action = 'first.action'").fetchone()

        self.assertEqual('{"gatewayToken": "[REDACTED]", "z": 1}', first["before_json"])
        self.assertEqual('{"fullCode": "\u2022\u2022\u2022\u2022-12345678"}', first["after_json"])
        self.assertEqual("admin#1", first["actor"])
        self.assertEqual("203.0.113.8", first["request_ip"])
        self.assertEqual("C:/backups/first.db", first["backup_path"])
        self.assertEqual("2030-01-02T03:04:05+00:00", first["created_at"])

        rows = self.server.get_audit_rows(2)
        self.assertEqual(["second.action", "first.action"], [row["action"] for row in rows])
        self.assertEqual("second.db", rows[0]["backupFile"])
        self.assertEqual("admin#1", rows[1]["actor"])
        self.assertEqual("203.0.113.8", rows[1]["requestIp"])
        self.assertEqual("C:/backups/first.db", rows[1]["backupPath"])
        self.assertEqual("2030-01-02T03:04:05+00:00", rows[1]["createdAt"])

    def test_persisted_audit_json_redacts_invite_credentials(self) -> None:
        invite = "INV-ABCD-EFGH-JKLM-NPQR"
        self.server.add_audit_log(
            action="invite.redaction.direct",
            before={"inviteCode": invite, "note": f"before invite:{invite} context"},
            after={"rawInviteCode": invite, "metadata": f"credential={invite}"},
        )

        with self.server.connect() as conn:
            row = conn.execute(
                "select before_json, after_json from audit_logs where action = ?",
                ("invite.redaction.direct",),
            ).fetchone()

        persisted = f"{row['before_json']} {row['after_json']}"
        self.assertNotIn(invite, persisted)
        self.assertIn("before", persisted)
        self.assertIn("context", persisted)

    def test_audit_facade_dispatches_public_value_and_json_collaborators(self) -> None:
        original_public_value = self.server.audit_public_value
        original_audit_json = self.server.audit_json
        public_calls: list[object] = []
        json_calls: list[object] = []

        def track_public_value(value: object, *, key: str = "") -> object:
            public_calls.append(value)
            return original_public_value(value, key=key)

        def track_audit_json(value: object) -> str:
            json_calls.append(value)
            return original_audit_json(value)

        self.server.audit_public_value = track_public_value
        self.server.audit_json = track_audit_json
        self.addCleanup(setattr, self.server, "audit_public_value", original_public_value)
        self.addCleanup(setattr, self.server, "audit_json", original_audit_json)

        before = {"gatewayToken": "facade-secret"}
        after = {"fullCode": "OC-PRO-FACADE-12345678"}
        self.server.add_audit_log(action="facade.dispatch", before=before, after=after)

        self.assertEqual([before, after], public_calls)
        self.assertEqual([{"gatewayToken": "[REDACTED]"}, {"fullCode": "\u2022\u2022\u2022\u2022-12345678"}], json_calls)

        public_calls.clear()
        self.server.get_audit_rows(1)
        self.assertEqual(2, len(public_calls))

    def test_account_code_and_plan_mutations_roll_back_when_audit_fails(self) -> None:
        admin, _ = self.server.create_account_record(
            username="atomic-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        headers = {"X-Admin-Session": session}
        original_add_audit_log = self.server.add_audit_log

        def fail_audit_write(**_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

        baseline_plan = next(plan for plan in self.server.get_plan_rows() if plan["planKey"] == "monthly")
        self.server.add_audit_log = fail_audit_write
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        self.request_json(
            "POST",
            "/admin/api/accounts",
            payload={"username": "atomic-account", "password": "account-password-123"},
            headers=headers,
            expected_status=400,
        )
        self.assertIsNone(self.server.get_account_by_username("atomic-account"))

        self.request_json(
            "POST",
            "/admin/api/codes",
            payload={
                "count": 1,
                "licensee": "Atomic Code Customer",
                "edition": "pro",
                "features": "openclaw",
                "expires": self.expires(),
                "maxActivations": 1,
            },
            headers=headers,
            expected_status=400,
        )
        with self.server.connect() as conn:
            self.assertEqual(0, conn.execute("select count(*) from codes where licensee = 'Atomic Code Customer'").fetchone()[0])

        self.request_json(
            "POST",
            "/admin/api/plans/update",
            payload={"planKey": "monthly", "displayName": "Atomic Plan", "durationDays": 99, "features": "openclaw"},
            headers=headers,
            expected_status=400,
        )
        current_plan = next(plan for plan in self.server.get_plan_rows() if plan["planKey"] == "monthly")
        self.assertEqual(baseline_plan, current_plan)

    def test_registration_and_direct_code_delete_roll_back_when_audit_fails(self) -> None:
        admin, _ = self.server.create_account_record(
            username="atomic-delete-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        invite, raw_invite_code = self.server.create_invite_record(note="atomic registration")
        code = self.server.create_code_records(
            count=1,
            licensee="Atomic Delete Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
        )[0]
        session, _ = self.server.create_admin_session(admin["accountId"])
        original_add_audit_log = self.server.add_audit_log

        def fail_audit_write(**_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

        self.server.add_audit_log = fail_audit_write
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        self.request_json(
            "POST",
            "/admin/api/auth/register",
            payload={"inviteCode": raw_invite_code, "username": "atomic-register", "password": "register-password-123"},
            expected_status=400,
        )
        self.assertIsNone(self.server.get_account_by_username("atomic-register"))
        with self.server.connect() as conn:
            invite_row = conn.execute("select used_count from invite_codes where id = ?", (invite["inviteId"],)).fetchone()
        self.assertEqual(0, invite_row["used_count"])

        self.request_json(
            "POST",
            "/admin/api/codes/delete",
            payload={"codeHash": self.server.code_hash(code), "confirmation": "DELETE"},
            headers={"X-Admin-Session": session},
            expected_status=400,
        )
        self.assertEqual(code, self.server.get_code_secret_rows([self.server.code_hash(code)])[0]["code"])

    def test_audited_transaction_finalization_is_idempotent(self) -> None:
        class CommitCounter:
            def __init__(self, connection: object) -> None:
                self.connection = connection
                self.commits = 0

            def commit(self) -> None:
                self.commits += 1
                self.connection.commit()

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        self.server._begin_audit_transaction()
        transaction = self.server._active_audit_transaction()
        self.assertIsNotNone(transaction)
        counter = CommitCounter(transaction.connection)
        transaction.connection = counter
        transaction.proxy.connection = counter
        try:
            with self.server.connect() as conn:
                conn.execute(
                    "insert into settings (key, value_json, updated_at) values (?, ?, ?)",
                    ("transaction-proof", "{}", "now"),
                )
                conn.commit()
            self.server.add_audit_log(action="transaction.proof")
            self.assertEqual(0, counter.commits)

            with self.server.db.connect(settings=self.server.SETTINGS, defaults=self.server.DB_DEFAULTS) as observer:
                self.assertIsNone(observer.execute("select 1 from settings where key = 'transaction-proof'").fetchone())
                self.assertIsNone(observer.execute("select 1 from audit_logs where action = 'transaction.proof'").fetchone())
        finally:
            transaction.response_sent = True
            self.server._finish_audit_transaction()

        self.server._finish_audit_transaction()

        self.assertEqual(1, counter.commits)

        with self.server.connect() as conn:
            self.assertIsNotNone(conn.execute("select 1 from settings where key = 'transaction-proof'").fetchone())
            self.assertIsNotNone(conn.execute("select 1 from audit_logs where action = 'transaction.proof'").fetchone())

    def test_http_commit_failure_returns_5xx_and_rolls_back_mutation_and_audit(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-commit-failure",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        baseline = self.server.get_beta_config()
        original_begin = self.server._begin_audit_transaction
        wrappers: list[object] = []

        class CommitFailure:
            def __init__(self, connection: object) -> None:
                self.connection = connection
                self.rollbacks = 0

            def commit(self) -> None:
                raise RuntimeError("injected commit failure with private path")

            def rollback(self) -> None:
                self.rollbacks += 1
                self.connection.rollback()

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        def begin_with_commit_failure() -> None:
            original_begin()
            transaction = self.server._active_audit_transaction()
            self.assertIsNotNone(transaction)
            wrapper = CommitFailure(transaction.connection)
            wrappers.append(wrapper)
            transaction.connection = wrapper
            transaction.proxy.connection = wrapper

        self.server._begin_audit_transaction = begin_with_commit_failure
        self.addCleanup(setattr, self.server, "_begin_audit_transaction", original_begin)

        response = self.request_json(
            "POST",
            "/admin/api/beta/config",
            payload={"dailyQuota": int(baseline["dailyQuota"]) + 1},
            headers={"X-Admin-Session": session},
            expected_status=500,
        )

        self.assertEqual({"ok": False, "error": "Internal server error"}, response)
        self.assertNotIn("commit", json.dumps(response).lower())
        self.assertEqual(baseline, self.server.get_beta_config())
        with self.server.connect() as conn:
            self.assertEqual(
                0,
                conn.execute(
                    "select count(*) from audit_logs where action = ?",
                    ("beta.config.update",),
                ).fetchone()[0],
            )
        self.assertEqual(1, len(wrappers))
        self.assertEqual(1, wrappers[0].rollbacks)

    def test_beta_claim_lock_contention_returns_sanitized_503(self) -> None:
        self.server.set_beta_config({"dailyQuota": 1, "validDays": 2})
        original_connect = self.server.connect

        def short_connect(*, timeout: float = 5.0):
            return original_connect(timeout=0.05)

        self.server.connect = short_connect
        self.addCleanup(setattr, self.server, "connect", original_connect)
        writer = original_connect()
        writer.execute("BEGIN IMMEDIATE")
        try:
            response = self.request_json(
                "POST",
                "/api/beta/claim",
                expected_status=503,
            )
        finally:
            writer.rollback()
            writer.close()

        self.assertEqual(
            {"ok": False, "error": "Service temporarily unavailable"}, response
        )
        serialized = json.dumps(response).lower()
        self.assertNotIn("locked", serialized)
        self.assertNotIn(str(self.temp_path).lower(), serialized)
        with original_connect() as conn:
            self.assertEqual(0, conn.execute("select count(*) from codes").fetchone()[0])
            self.assertEqual(0, conn.execute("select count(*) from beta_claims").fetchone()[0])

    def test_registration_audit_runs_after_session_and_last_login(self) -> None:
        invite, raw_invite_code = self.server.create_invite_record(note="registration audit order")
        call_order: list[str] = []
        original_create_session = self.server.create_admin_session
        original_update_last_login = self.server.update_account_last_login
        original_add_audit_log = self.server.add_audit_log

        def create_session(*args: object, **kwargs: object) -> tuple[str, str]:
            call_order.append("session")
            return original_create_session(*args, **kwargs)

        def update_last_login(*args: object, **kwargs: object) -> None:
            call_order.append("last-login")
            original_update_last_login(*args, **kwargs)

        def add_audit(**kwargs: object) -> None:
            call_order.append("audit")
            original_add_audit_log(**kwargs)

        self.server.create_admin_session = create_session
        self.server.update_account_last_login = update_last_login
        self.server.add_audit_log = add_audit
        self.addCleanup(setattr, self.server, "create_admin_session", original_create_session)
        self.addCleanup(setattr, self.server, "update_account_last_login", original_update_last_login)
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        self.request_json(
            "POST",
            "/admin/api/auth/register",
            payload={"inviteCode": raw_invite_code, "username": "ordered-register", "password": "register-password-123"},
        )

        self.assertEqual(["session", "last-login", "audit"], call_order)
        self.assertEqual(1, sum(row["action"] == "accounts.register" for row in self.server.get_audit_rows()))

    def test_registration_route_keeps_base_facade_call_shape_and_atomic_audit(self) -> None:
        invite, raw_invite_code = self.server.create_invite_record(note="base registration facade")
        original_register = self.server.register_account_with_invite
        calls: list[str] = []

        def base_register(
            *,
            invite_code: str,
            username: str,
            display_name: str = "",
            password: str = "",
            request_ip: str = "",
            user_agent: str = "",
        ) -> tuple[dict[str, object], str, str]:
            calls.append(username)
            return original_register(
                invite_code=invite_code,
                username=username,
                display_name=display_name,
                password=password,
                request_ip=request_ip,
                user_agent=user_agent,
            )

        self.server.register_account_with_invite = base_register
        self.addCleanup(setattr, self.server, "register_account_with_invite", original_register)

        response = self.request_json(
            "POST",
            "/admin/api/auth/register",
            payload={
                "inviteCode": raw_invite_code,
                "username": "base-register",
                "password": "register-password-123",
            },
        )

        self.assertTrue(response["ok"])
        self.assertEqual(["base-register"], calls)
        self.assertIsNotNone(self.server.get_account_by_username("base-register"))
        with self.server.connect() as conn:
            invite_row = conn.execute(
                "select used_count from invite_codes where id = ?", (invite["inviteId"],)
            ).fetchone()
            audit_row = conn.execute(
                "select actor, after_json from audit_logs where action = ? and target_id = ?",
                ("accounts.register", "base-register"),
            ).fetchone()
        self.assertEqual(1, invite_row["used_count"])
        self.assertIsNotNone(audit_row)
        self.assertNotIn(raw_invite_code, audit_row["after_json"])
        self.assertNotIn(raw_invite_code[-8:], audit_row["actor"])

    def test_http_invite_creation_never_persists_raw_invite_in_audit_json(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-invite-redaction",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        embedded_invite = "INV-ABCD-EFGH-JKLM-NPQR"

        response = self.request_json(
            "POST",
            "/admin/api/invites",
            payload={"note": f"campaign invite:{embedded_invite} retained", "maxUses": 1},
            headers={"X-Admin-Session": session},
        )
        raw_invite = response["inviteCode"]

        with self.server.connect() as conn:
            audit_row = conn.execute(
                "select before_json, after_json from audit_logs where action = ? order by id desc limit 1",
                ("invites.create",),
            ).fetchone()
        persisted = f"{audit_row['before_json']} {audit_row['after_json']}"
        self.assertNotIn(raw_invite, persisted)
        self.assertNotIn(embedded_invite, persisted)
        self.assertIn("campaign", persisted)
        self.assertIn("retained", persisted)

    def test_registration_rolls_back_when_session_or_last_login_update_fails(self) -> None:
        for failure_name in ("create_admin_session", "update_account_last_login", "auth_status_snapshot"):
            with self.subTest(failure=failure_name):
                invite, raw_invite_code = self.server.create_invite_record(note=f"registration {failure_name}")
                original = getattr(self.server, failure_name)

                def fail_after_registration(*_args: object, **_kwargs: object) -> object:
                    raise RuntimeError(f"{failure_name} unavailable")

                setattr(self.server, failure_name, fail_after_registration)
                try:
                    self.request_json(
                        "POST",
                        "/admin/api/auth/register",
                        payload={
                            "inviteCode": raw_invite_code,
                            "username": f"atomic-{failure_name}",
                            "password": "register-password-123",
                        },
                        expected_status=400,
                    )
                finally:
                    setattr(self.server, failure_name, original)

                self.assertIsNone(self.server.get_account_by_username(f"atomic-{failure_name}"))
                with self.server.connect() as conn:
                    invite_row = conn.execute("select used_count from invite_codes where id = ?", (invite["inviteId"],)).fetchone()
                    self.assertEqual(0, invite_row["used_count"])
                    self.assertEqual(0, conn.execute("select count(*) from admin_sessions").fetchone()[0])
                    self.assertEqual(
                        0,
                        conn.execute(
                            "select count(*) from audit_logs where action = ? and target_id = ?",
                            ("accounts.register", f"atomic-{failure_name}"),
                        ).fetchone()[0],
                    )

    def test_non_2xx_registration_rolls_back_stored_invite_status_normalization(self) -> None:
        for state, expected_status in (("expired", self.server.INVITE_CODE_STATUS_EXPIRED), ("used", self.server.INVITE_CODE_STATUS_USED)):
            with self.subTest(state=state):
                invite, raw_invite_code = self.server.create_invite_record(note=f"{state} registration")
                with self.server.connect() as conn:
                    if state == "expired":
                        conn.execute("update invite_codes set expires_at = ? where id = ?", ("2000-01-01T00:00:00+00:00", invite["inviteId"]))
                    else:
                        conn.execute("update invite_codes set used_count = max_uses where id = ?", (invite["inviteId"],))
                    conn.commit()

                self.request_json(
                    "POST",
                    "/admin/api/auth/register",
                    payload={"inviteCode": raw_invite_code, "username": f"{state}-register", "password": "register-password-123"},
                    expected_status=403,
                )

                self.assertIsNone(self.server.get_account_by_username(f"{state}-register"))
                with self.server.connect() as conn:
                    row = conn.execute("select status, used_count from invite_codes where id = ?", (invite["inviteId"],)).fetchone()
                self.assertEqual(self.server.INVITE_CODE_STATUS_ACTIVE, row["status"])
                self.assertEqual(
                    expected_status,
                    self.server.invite_row_public(
                        self.server.get_invite_by_code(raw_invite_code)
                    )["status"],
                )

    def test_bootstrap_rolls_back_when_audit_fails(self) -> None:
        original_add_audit_log = self.server.add_audit_log

        def fail_audit_write(**_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

        self.server.add_audit_log = fail_audit_write
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        self.request_json(
            "POST",
            "/admin/api/auth/bootstrap",
            payload={"username": "bootstrap-atomic", "password": "bootstrap-password-123"},
            headers={"X-Admin-Token": "test-admin-token"},
            expected_status=400,
        )
        self.assertEqual(0, self.server.count_accounts())
        with self.server.connect() as conn:
            self.assertEqual(0, conn.execute("select count(*) from admin_sessions").fetchone()[0])

    def test_beta_config_and_template_mutations_roll_back_when_audit_fails(self) -> None:
        admin, _ = self.server.create_account_record(
            username="management-atomic-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        headers = {"X-Admin-Session": session}
        baseline_beta = self.server.get_beta_config()
        existing_template = self.server.save_template(
            {"kind": "image", "title": "Atomic Existing", "prompt": "Existing template prompt"}
        )
        original_add_audit_log = self.server.add_audit_log

        def fail_audit_write(**_kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

        self.server.add_audit_log = fail_audit_write
        self.addCleanup(setattr, self.server, "add_audit_log", original_add_audit_log)

        self.request_json(
            "POST",
            "/admin/api/beta/config",
            payload={"enabled": False, "dailyQuota": 1},
            headers=headers,
            expected_status=400,
        )
        self.assertEqual(baseline_beta, self.server.get_beta_config())

        self.request_json(
            "POST",
            "/admin/api/templates",
            payload={"kind": "image", "title": "Atomic New", "prompt": "New template prompt"},
            headers=headers,
            expected_status=400,
        )
        self.assertNotIn("Atomic New", [template["title"] for template in self.server.list_templates()])

        self.request_json(
            "POST",
            "/admin/api/templates/delete",
            payload={"id": existing_template["id"], "confirmation": "DELETE"},
            headers=headers,
            expected_status=400,
        )
        self.assertIn(existing_template["id"], [template["id"] for template in self.server.list_templates()])

    def test_code_creation_audit_does_not_store_full_codes(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin-code-create-audit",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])

        response = self.request_json(
            "POST",
            "/admin/api/codes",
            payload={
                "count": 1,
                "licensee": "Audit Customer",
                "edition": "pro",
                "features": "openclaw",
                "expires": self.expires(),
                "maxActivations": 1,
            },
            headers={"X-Admin-Session": session},
        )
        code = response["codes"][0]
        with self.server.connect() as conn:
            row = conn.execute(
                "select after_json from audit_logs where action = 'codes.create' order by id desc limit 1"
            ).fetchone()

        self.assertIsNotNone(row)
        after = json.loads(row["after_json"])
        self.assertNotIn("codes", after)
        self.assertIn("codeLabels", after)
        self.assertNotIn(code, row["after_json"])

    def test_activation_inventory_is_scoped_and_redacted(self) -> None:
        admin, _ = self.server.create_account_record(
            username="activation-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        merchant, _ = self.server.create_account_record(
            username="activation-merchant",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="activation-other",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        owned_code = self.server.create_code_records(
            count=1,
            licensee="Owned Device",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        other_code = self.server.create_code_records(
            count=1,
            licensee="Other Device",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=other["accountId"],
        )[0]
        self.server.activate_code({"code": owned_code, "installId": "owned-install", "deviceId": "owned-device"})
        self.server.activate_code({"code": other_code, "installId": "other-install", "deviceId": "other-device"})

        admin_rows = self.server.get_all_activation_rows(
            {"accountId": admin["accountId"], "role": self.server.ACCOUNT_ROLE_SUPER_ADMIN}
        )
        merchant_rows = self.server.get_all_activation_rows(
            {"accountId": merchant["accountId"], "role": self.server.ACCOUNT_ROLE_MERCHANT}
        )
        self.assertEqual(len(admin_rows), 2)
        self.assertEqual(len(merchant_rows), 1)
        serialized = json.dumps(merchant_rows, ensure_ascii=False)
        self.assertIn("owned-device", serialized)
        self.assertNotIn(owned_code, serialized)
        self.assertNotIn("licenseJson", serialized)

        session, _ = self.server.create_admin_session(merchant["accountId"])
        response = self.request_json(
            "GET",
            "/admin/api/activations",
            headers={"X-Admin-Session": session},
        )
        self.assertEqual(response["activations"], merchant_rows)

    def test_activation_detail_returns_same_404_for_missing_and_cross_tenant_code(self) -> None:
        admin, _ = self.server.create_account_record(
            username="activation-detail-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        merchant, _ = self.server.create_account_record(
            username="activation-detail-owner",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="activation-detail-other",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        admin_session, _ = self.server.create_admin_session(admin["accountId"])
        owner_session, _ = self.server.create_admin_session(merchant["accountId"])
        other_session, _ = self.server.create_admin_session(other["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Activation Detail Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        self.server.activate_code(
            {"code": code, "installId": "activation-detail-install", "deviceId": "activation-detail-device"}
        )

        denied = self.request_json(
            "GET",
            f"/admin/api/codes/activations?codeHash={code_hash_value}",
            headers={"X-Admin-Session": other_session},
            expected_status=404,
        )
        missing = self.request_json(
            "GET",
            f"/admin/api/codes/activations?codeHash={'f' * 64}",
            headers={"X-Admin-Session": other_session},
            expected_status=404,
        )
        owned = self.request_json(
            "GET",
            f"/admin/api/codes/activations?codeHash={code_hash_value}",
            headers={"X-Admin-Session": owner_session},
        )
        admin_view = self.request_json(
            "GET",
            f"/admin/api/codes/activations?codeHash={code_hash_value}",
            headers={"X-Admin-Session": admin_session},
        )

        self.assertEqual(denied, missing)
        self.assertEqual(owned["activations"][0]["deviceId"], "activation-detail-device")
        self.assertEqual(admin_view, owned)

    def test_activation_delete_returns_same_404_for_missing_and_cross_tenant_record(self) -> None:
        admin, _ = self.server.create_account_record(
            username="activation-delete-admin",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        merchant, _ = self.server.create_account_record(
            username="activation-delete-owner",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="activation-delete-other",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        admin_session, _ = self.server.create_admin_session(admin["accountId"])
        other_session, _ = self.server.create_admin_session(other["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Activation Delete Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        self.server.activate_code(
            {"code": code, "installId": "activation-delete-install", "deviceId": "activation-delete-device"}
        )
        activation_id = self.server.get_activation_rows(code_hash_value)[0]["id"]

        denied = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": other_session},
            expected_status=404,
        )
        missing = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id + 10000, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": other_session},
            expected_status=404,
        )

        self.assertEqual(denied, missing)
        self.assertIsNotNone(self.server.get_activation_snapshot(activation_id))
        deleted = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": admin_session},
        )
        self.assertTrue(deleted["ok"])
        self.assertIsNone(self.server.get_activation_snapshot(activation_id))

    def test_merchant_can_delete_own_activation_via_http(self) -> None:
        merchant, _ = self.server.create_account_record(
            username="activation-delete-own",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        session, _ = self.server.create_admin_session(merchant["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Activation Delete Own Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        self.server.activate_code(
            {"code": code, "installId": "activation-delete-own-install", "deviceId": "activation-delete-own-device"}
        )
        activation_id = self.server.get_activation_rows(code_hash_value)[0]["id"]

        response = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": session},
        )

        self.assertTrue(response["ok"])
        self.assertIsNone(self.server.get_activation_snapshot(activation_id))

    def test_merchant_delete_rechecks_owner_after_snapshot_before_sql_delete(self) -> None:
        merchant, _ = self.server.create_account_record(
            username="activation-delete-race-owner",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        new_owner, _ = self.server.create_account_record(
            username="activation-delete-race-new-owner",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        session, _ = self.server.create_admin_session(merchant["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Activation Delete Race Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        code_hash_value = self.server.code_hash(code)
        self.server.activate_code(
            {"code": code, "installId": "activation-delete-race-install", "deviceId": "activation-delete-race-device"}
        )
        activation_id = self.server.get_activation_rows(code_hash_value)[0]["id"]
        original_make_db_backup = db.make_db_backup

        def change_owner_after_snapshot(label: str, **kwargs) -> str:
            backup_path = original_make_db_backup(label, **kwargs)
            with self.server.connect() as conn:
                conn.execute(
                    "update codes set owner_account_id = ? where code_hash = ?",
                    (new_owner["accountId"], code_hash_value),
                )
                conn.commit()
            return backup_path

        db.make_db_backup = change_owner_after_snapshot
        self.addCleanup(setattr, db, "make_db_backup", original_make_db_backup)

        denied = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": session},
            expected_status=404,
        )
        missing = self.request_json(
            "POST",
            "/admin/api/activations/delete",
            payload={"id": activation_id + 10000, "confirmation": "UNBIND"},
            headers={"X-Admin-Session": session},
            expected_status=404,
        )

        self.assertEqual(denied, missing)
        self.assertIsNotNone(self.server.get_activation_snapshot(activation_id))
        with self.server.connect() as conn:
            owner_id = conn.execute(
                "select owner_account_id from codes where code_hash = ?",
                (code_hash_value,),
            ).fetchone()["owner_account_id"]
        self.assertEqual(owner_id, new_owner["accountId"])

    def test_new_code_expiry_must_be_after_today(self) -> None:
        with self.assertRaises(self.server.ActivationError):
            self.server.normalize_code_expires(date.today().isoformat())
        with self.assertRaises(self.server.ActivationError):
            self.server.normalize_code_expires((date.today() - timedelta(days=1)).isoformat())
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(self.server.normalize_code_expires(tomorrow), tomorrow)

    def start_http_server(self) -> str:
        from http.server import ThreadingHTTPServer
        import threading

        if self._http_base_url:
            return self._http_base_url
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def cleanup() -> None:
            httpd.shutdown()
            thread.join(timeout=5)
            httpd.server_close()

        self.addCleanup(cleanup)
        self._http_base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
        return self._http_base_url

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        expected_status: int = 200,
    ):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import json

        base_url = self.start_http_server()
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(f"{base_url}{path}", method=method, headers=request_headers, data=data)
        try:
            response = urlopen(request, timeout=5)
            status = response.status
            body = response.read()
            response_headers = response.headers
        except HTTPError as error:
            status = error.code
            body = error.read()
            response_headers = error.headers
        self.assertEqual(status, expected_status, body.decode("utf-8", errors="replace"))
        return body, response_headers

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        expected_status: int = 200,
    ) -> dict[str, object]:
        import json

        body, _ = self.request_raw(
            method,
            path,
            payload=payload,
            headers=headers,
            expected_status=expected_status,
        )
        return json.loads(body.decode("utf-8") or "{}")

    def test_public_card_site_config_is_validated_and_exposed_to_clients(self) -> None:
        initial = self.server.client_public_config()
        self.assertEqual(initial["cardSite"]["enabled"], False)
        self.assertEqual(initial["cardSite"]["url"], "")

        with self.assertRaises(self.server.ActivationError):
            self.server.update_public_settings({"cardSiteUrl": "ftp://invalid.example"})

        updated = self.server.update_public_settings(
            {
                "cardSiteEnabled": True,
                "cardSiteLabel": "Buy license",
                "cardSiteUrl": "https://shop.example.com/cdk",
            }
        )
        self.assertEqual(updated["cardSiteLabel"], "Buy license")

        client_config = self.server.client_public_config()
        self.assertEqual(
            client_config,
            {
                "purchaseUrl": "https://shop.example.com/cdk",
                "supportUrl": "https://license.heang.top/",
                "cardSite": {
                    "enabled": True,
                    "label": "Buy license",
                    "url": "https://shop.example.com/cdk",
                }
            },
        )

    def test_commercial_features_are_available_to_new_default_plans(self) -> None:
        commercial = {
            "acquisition.workbench",
            "acquisition.feishu",
            "matrix.devices",
            "templates.cloud",
            "publishing.draft",
            "diagnostics.export",
        }

        self.assertTrue(commercial.issubset(set(self.server.DEFAULT_FEATURES)))
        plans = {item["planKey"]: item for item in self.server.get_plan_rows()}
        for plan_key in ("monthly", "quarterly", "yearly", "vip_monthly"):
            self.assertTrue(commercial.issubset(set(plans[plan_key]["features"])), plan_key)

    def test_default_plan_migration_does_not_widen_already_issued_codes(self) -> None:
        code = self.server.create_code_records(
            count=1,
            licensee="Legacy Customer",
            edition="legacy",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            plan="monthly",
        )[0]
        with self.server.connect() as conn:
            conn.execute(
                "update plans set features_json = ? where plan_key = ?",
                ('["openclaw","image","video","storyboard"]', "monthly"),
            )
            conn.commit()
        with self.server.connect() as conn:
            self.server.seed_default_plans(conn)
            conn.commit()

        plans = {item["planKey"]: item for item in self.server.get_plan_rows()}
        self.assertTrue(
            set(self.server.COMMERCIAL_FEATURES).issubset(set(plans["monthly"]["features"]))
        )
        rows = self.server.get_code_rows()
        issued = next(item for item in rows if item["codeHash"] == self.server.code_hash(code))
        self.assertEqual(issued["features"], ["openclaw"])

    def test_signed_commercial_license_contains_display_and_device_limit_fields(self) -> None:
        code = self.server.create_code_records(
            count=1,
            licensee="Commercial Customer",
            edition="team",
            features=list(self.server.DEFAULT_FEATURES),
            expires=self.expires(),
            max_activations=3,
            member_mode=False,
            plan="team_monthly",
        )[0]

        license_data = self.server.activate_code(
            {"code": code, "installId": "install-commercial", "deviceId": "device-commercial"}
        )

        self.assertEqual(license_data["licensee"], "Commercial Customer")
        self.assertEqual(license_data["edition"], "team")
        self.assertEqual(license_data["plan"], "team_monthly")
        self.assertEqual(license_data["expiresAt"], license_data["expires"])
        self.assertEqual(license_data["deviceLimit"], 3)
        self.assertEqual(license_data["installId"], "install-commercial")
        self.assertEqual(license_data["deviceId"], "device-commercial")
        self.assertTrue(set(self.server.DEFAULT_FEATURES).issubset(set(license_data["features"])))

    def test_activation_http_errors_expose_stable_public_codes(self) -> None:
        invalid = self.request_json(
            "POST",
            "/activate",
            payload={"code": "OC-NOT-FOUND", "installId": "install-invalid", "deviceId": "device-invalid"},
            expected_status=404,
        )
        self.assertEqual(invalid["code"], "LICENSE_INVALID")

        disabled_code = self.server.create_code_records(
            count=1,
            licensee="Disabled Customer",
            edition="team",
            features=list(self.server.DEFAULT_FEATURES),
            expires=self.expires(),
            max_activations=1,
        )[0]
        with self.server.connect() as conn:
            conn.execute(
                "update codes set disabled = 1 where code_hash = ?",
                (self.server.code_hash(disabled_code),),
            )
            conn.commit()
        disabled = self.request_json(
            "POST",
            "/api/member/activate",
            payload={"code": disabled_code, "installId": "install-disabled", "deviceId": "device-disabled"},
            expected_status=403,
        )
        self.assertEqual(disabled["code"], "LICENSE_DISABLED")

        expired_code = self.server.create_code_records(
            count=1,
            licensee="Expired Customer",
            edition="team",
            features=list(self.server.DEFAULT_FEATURES),
            expires=self.expires(),
            max_activations=1,
        )[0]
        with self.server.connect() as conn:
            conn.execute(
                "update codes set expires = ? where code_hash = ?",
                ((date.today() - timedelta(days=1)).isoformat(), self.server.code_hash(expired_code)),
            )
            conn.commit()
        expired = self.request_json(
            "POST",
            "/activate",
            payload={"code": expired_code, "installId": "install-expired", "deviceId": "device-expired"},
            expected_status=403,
        )
        self.assertEqual(expired["code"], "LICENSE_EXPIRED")

        bound_code = self.server.create_code_records(
            count=1,
            licensee="Bound Customer",
            edition="team",
            features=list(self.server.DEFAULT_FEATURES),
            expires=self.expires(),
            max_activations=1,
        )[0]
        self.server.activate_code(
            {"code": bound_code, "installId": "install-first", "deviceId": "device-first"}
        )
        mismatch = self.request_json(
            "POST",
            "/activate",
            payload={"code": bound_code, "installId": "install-second", "deviceId": "device-second"},
            expected_status=403,
        )
        self.assertEqual(mismatch["code"], "DEVICE_MISMATCH")

    def test_merchant_cannot_update_public_settings(self) -> None:
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import json
        import threading

        merchant, _ = self.server.create_account_record(
            username="merchant-settings",
            display_name="Merchant Settings",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        merchant_session, _ = self.server.create_admin_session(merchant["accountId"])

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/admin/api/public-settings"
            request = Request(
                url,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Session": merchant_session,
                },
                data=json.dumps(
                    {
                        "cardSiteEnabled": False,
                        "cardSiteLabel": "Blocked",
                        "cardSiteUrl": "",
                    }
                ).encode("utf-8"),
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_bootstrap_requires_password_and_does_not_return_temporary_password(self) -> None:
        missing_password = self.request_json(
            "POST",
            "/admin/api/auth/bootstrap",
            payload={"username": "admin"},
            headers={"X-Admin-Token": "test-admin-token"},
            expected_status=400,
        )
        self.assertIn("error", missing_password)
        self.assertEqual(self.server.count_accounts(), 0)

        created = self.request_json(
            "POST",
            "/admin/api/auth/bootstrap",
            payload={"username": "admin", "password": "admin-password-123"},
            headers={"X-Admin-Token": "test-admin-token"},
            expected_status=200,
        )
        self.assertTrue(created["ok"])
        self.assertNotIn("temporaryPassword", created)
        self.assertTrue(self.server.verify_password("admin-password-123", self.server.get_account_by_username("admin")["password_hash"]))

    def test_admin_http_account_creation_requires_password_and_hides_temporary_password(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin",
            display_name="Root",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session_token, _ = self.server.create_admin_session(admin["accountId"])
        headers = {"X-Admin-Session": session_token}

        blank = self.request_json(
            "POST",
            "/admin/api/accounts",
            payload={"username": "merchant-blank", "password": ""},
            headers=headers,
            expected_status=400,
        )
        self.assertIn("error", blank)

        created = self.request_json(
            "POST",
            "/admin/api/accounts",
            payload={
                "username": "merchant-created",
                "displayName": "Merchant Created",
                "password": "merchant-password-123",
                "role": self.server.ACCOUNT_ROLE_MERCHANT,
            },
            headers=headers,
            expected_status=200,
        )
        self.assertTrue(created["ok"])
        self.assertNotIn("temporaryPassword", created)
        self.assertEqual(created["account"]["username"], "merchant-created")

    def test_admin_cors_restricts_admin_origins_but_keeps_public_api_open(self) -> None:
        _, blocked_headers = self.request_raw(
            "OPTIONS",
            "/admin/api/auth/login",
            headers={"Origin": "https://evil.example"},
            expected_status=204,
        )
        self.assertIsNone(blocked_headers.get("Access-Control-Allow-Origin"))

        _, allowed_headers = self.request_raw(
            "OPTIONS",
            "/admin/api/auth/login",
            headers={"Origin": "http://127.0.0.1:3000"},
            expected_status=204,
        )
        self.assertEqual(allowed_headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:3000")

        _, public_headers = self.request_raw(
            "OPTIONS",
            "/api/client/config",
            headers={"Origin": "https://anywhere.example"},
            expected_status=204,
        )
        self.assertEqual(public_headers.get("Access-Control-Allow-Origin"), "*")

    def test_login_and_register_rate_limits_block_repeated_attempts(self) -> None:
        self.server.create_account_record(
            username="rate-user",
            password="correct-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        for _ in range(self.server.LOGIN_RATE_LIMIT_ATTEMPTS):
            self.request_json(
                "POST",
                "/admin/api/auth/login",
                payload={"username": "rate-user", "password": "wrong-password"},
                expected_status=401,
            )
        self.request_json(
            "POST",
            "/admin/api/auth/login",
            payload={"username": "rate-user", "password": "wrong-password"},
            expected_status=429,
        )

        for idx in range(self.server.REGISTER_RATE_LIMIT_ATTEMPTS):
            self.request_json(
                "POST",
                "/admin/api/auth/register",
                payload={
                    "inviteCode": "INV-DOES-NOT-EXIST",
                    "username": f"blocked-register-{idx}",
                    "password": "merchant-password-123",
                },
                expected_status=404,
            )
        self.request_json(
            "POST",
            "/admin/api/auth/register",
            payload={
                "inviteCode": "INV-DOES-NOT-EXIST",
                "username": "blocked-register-next",
                "password": "merchant-password-123",
            },
            expected_status=429,
        )

    def test_merchant_gateway_defaults_are_used_when_creating_codes(self) -> None:
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        import json
        import threading

        merchant, _ = self.server.create_account_record(
            username="merchant-gateway",
            display_name="Merchant Gateway",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        merchant_session, _ = self.server.create_admin_session(merchant["accountId"])

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}/admin"

            save_request = Request(
                f"{base_url}/api/account-gateway",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Session": merchant_session,
                },
                data=json.dumps(
                    {
                        "gatewayBaseUrl": "https://llm.merchant.example/v1",
                        "gatewayImageBaseUrl": "https://image.merchant.example/v1",
                        "gatewayVideoBaseUrl": "https://video.merchant.example/v1",
                        "gatewayToken": "merchant-llm-token",
                        "gatewayImageToken": "merchant-image-token",
                        "gatewayVideoToken": "merchant-video-token",
                        "gatewayDefaultModel": "merchant-chat",
                        "gatewayImageModel": "merchant-image",
                        "gatewayVideoModel": "merchant-video",
                        "gatewayModels": "merchant-chat,merchant-pro",
                    }
                ).encode("utf-8"),
            )
            save_response = json.loads(urlopen(save_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(save_response["settings"]["gatewayConfigured"])
            self.assertNotIn("merchant-llm-token", json.dumps(save_response, ensure_ascii=False))

            create_request = Request(
                f"{base_url}/api/codes",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Session": merchant_session,
                },
                data=json.dumps(
                    {
                        "licensee": "Gateway Customer",
                        "edition": "pro",
                        "count": 1,
                        "expires": self.expires(),
                        "maxActivations": 1,
                        "features": "openclaw,image,video",
                        "memberMode": True,
                        "plan": "merchant_custom",
                    }
                ).encode("utf-8"),
            )
            create_response = json.loads(urlopen(create_request, timeout=5).read().decode("utf-8"))
            code = create_response["codes"][0]
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        merchant_context = {
            "accountId": merchant["accountId"],
            "role": self.server.ACCOUNT_ROLE_MERCHANT,
        }
        rows = self.server.get_code_rows(merchant_context)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["gatewayConfigured"])
        self.assertTrue(rows[0]["gatewayImageConfigured"])
        self.assertTrue(rows[0]["gatewayVideoConfigured"])
        self.assertEqual(rows[0]["gatewayDefaultModel"], "merchant-chat")
        self.assertEqual(rows[0]["gatewayImageModel"], "merchant-image")
        self.assertEqual(rows[0]["gatewayVideoModel"], "merchant-video")
        self.assertNotEqual(rows[0]["gatewayToken"], "merchant-llm-token")

        license_data = self.server.activate_code(
            {"code": code, "installId": "merchant-install", "deviceId": "merchant-device"}
        )
        self.assertEqual(license_data["gatewayBaseUrl"], "https://llm.merchant.example/v1")
        self.assertEqual(license_data["gatewayAccessToken"], "merchant-llm-token")
        self.assertEqual(license_data["gatewayImageAccessToken"], "merchant-image-token")
        self.assertEqual(license_data["gatewayVideoAccessToken"], "merchant-video-token")

    def test_member_activation_preserves_separate_llm_image_and_video_gateway_config(self) -> None:
        code = self.server.create_code_records(
            count=1,
            licensee="Flow Customer",
            edition="pro",
            features=["openclaw", "image", "video", "storyboard"],
            expires=self.expires(),
            max_activations=1,
            member_mode=True,
            plan="monthly",
            gateway_base_url="https://llm.example.com/v1",
            gateway_image_base_url="https://image.example.com/v1",
            gateway_video_base_url="https://video.example.com/v1",
            gateway_token="llm-token",
            gateway_image_token="image-token",
            gateway_video_token="video-token",
            gateway_default_model="gpt-4.1-mini",
            gateway_image_model="gpt-image-2",
            gateway_video_model="happyhorse-1.0-t2v",
            gateway_models=["gpt-4.1-mini", "gpt-4.1"],
            quotas={},
        )[0]

        license_data = self.server.activate_code(
            {"code": code, "installId": "install-a", "deviceId": "device-a"}
        )

        expected_last8 = "".join(ch for ch in code if ch.isalnum())[-8:]
        self.assertTrue(license_data["memberMode"])
        self.assertEqual(license_data["activationCodeLast8"], expected_last8)
        self.assertEqual(license_data["gatewayBaseUrl"], "https://llm.example.com/v1")
        self.assertEqual(license_data["gatewayImageBaseUrl"], "https://image.example.com/v1")
        self.assertEqual(license_data["gatewayVideoBaseUrl"], "https://video.example.com/v1")
        self.assertEqual(license_data["gatewayAccessToken"], "llm-token")
        self.assertEqual(license_data["gatewayImageAccessToken"], "image-token")
        self.assertEqual(license_data["gatewayVideoAccessToken"], "video-token")
        self.assertEqual(license_data["gatewayDefaultModel"], "gpt-4.1-mini")
        self.assertEqual(license_data["gatewayImageModel"], "gpt-image-2")
        self.assertEqual(license_data["gatewayVideoModel"], "happyhorse-1.0-t2v")

        response = self.server.member_response(license_data)
        self.assertEqual(response["gateway"]["baseUrl"], "https://llm.example.com/v1")
        self.assertEqual(response["gateway"]["imageBaseUrl"], "https://image.example.com/v1")
        self.assertEqual(response["gateway"]["videoBaseUrl"], "https://video.example.com/v1")
        self.assertEqual(response["member"]["gatewayImageToken"], "image-token")
        self.assertEqual(response["member"]["gatewayVideoToken"], "video-token")

        refreshed = self.server.find_member_license(
            {"installId": "install-a", "gatewayImageAccessToken": "image-token"}
        )
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["gatewayImageModel"], "gpt-image-2")

        rows = self.server.get_code_rows()
        self.assertEqual(len(rows), 1)
        secrets = self.server.get_code_secret_rows([rows[0]["codeHash"]])
        self.assertEqual(secrets[0]["code"], code)
        self.assertEqual(rows[0]["activations"], 1)

    def test_member_current_rejects_empty_or_token_only_lookup(self) -> None:
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import json
        import threading

        code = self.server.create_code_records(
            count=1,
            licensee="Secure Member",
            edition="pro",
            features=["openclaw", "image", "video"],
            expires=self.expires(),
            max_activations=1,
            member_mode=True,
            plan="monthly",
            gateway_base_url="https://llm.example.com/v1",
            gateway_token="llm-token",
        )[0]
        license_data = self.server.activate_code(
            {"code": code, "installId": "install-secure", "deviceId": "device-secure"}
        )

        self.assertIsNone(self.server.find_member_license({}))
        self.assertIsNone(self.server.find_member_license({"gatewayAccessToken": "llm-token"}))
        self.assertIsNone(self.server.find_member_license({"memberId": license_data["memberId"]}))
        self.assertIsNone(
            self.server.find_member_license(
                {"memberId": license_data["memberId"], "gatewayAccessToken": "llm-token"}
            )
        )
        self.assertIsNone(
            self.server.find_member_license(
                {
                    "installId": "install-secure",
                    "deviceId": "wrong-device",
                    "memberId": license_data["memberId"],
                    "gatewayAccessToken": "llm-token",
                }
            )
        )
        self.assertIsNotNone(
            self.server.find_member_license(
                {
                    "installId": "install-secure",
                    "deviceId": "device-secure",
                    "memberId": license_data["memberId"],
                    "gatewayAccessToken": "llm-token",
                }
            )
        )

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/member/current",
                method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({}).encode("utf-8"),
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_merchant_cannot_apply_global_plan_template_gateway_secret(self) -> None:
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        import json
        import threading

        self.server.DEFAULT_GATEWAY_BASE_URL = "https://platform-default.example/v1"
        self.server.DEFAULT_GATEWAY_TOKEN = "platform-default-token"
        self.server.upsert_plan_record(
            {
                "planKey": "platform_secret",
                "displayName": "Platform Secret",
                "durationDays": 31,
                "features": "openclaw,image,video",
                "gatewayBaseUrl": "https://platform.example/v1",
                "gatewayToken": "platform-secret-token",
                "gatewayDefaultModel": "platform-model",
                "quotas": '{"image":100,"video":20}',
            }
        )
        merchant, _ = self.server.create_account_record(
            username="merchant-no-template",
            display_name="Merchant No Template",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        merchant_session, _ = self.server.create_admin_session(merchant["accountId"])

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/admin/api/codes",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Session": merchant_session,
                },
                data=json.dumps(
                    {
                        "licensee": "Merchant Customer",
                        "edition": "pro",
                        "count": 1,
                        "planTemplate": "platform_secret",
                        "memberMode": True,
                        "maxActivations": 1,
                        "features": "openclaw,image,video",
                        "expires": self.expires(),
                    }
                ).encode("utf-8"),
            )
            response = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
            code = response["codes"][0]
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        merchant_context = {
            "accountId": merchant["accountId"],
            "role": self.server.ACCOUNT_ROLE_MERCHANT,
        }
        rows = self.server.get_code_rows(merchant_context)
        self.assertEqual(len(rows), 1)
        secrets = self.server.get_code_secret_rows([rows[0]["codeHash"]], merchant_context)
        self.assertEqual(secrets[0]["code"], code)
        self.assertFalse(rows[0]["gatewayConfigured"])
        self.assertNotEqual(rows[0]["gatewayBaseUrl"], "https://platform.example/v1")
        with self.assertRaises(self.server.ActivationError):
            self.server.activate_code({"code": code, "installId": "install-a", "deviceId": "device-a"})

    def test_activation_limit_blocks_second_install(self) -> None:
        code = self.server.create_code_records(
            count=1,
            licensee="Single Device",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
        )[0]

        first = self.server.activate_code(
            {"code": code, "installId": "install-a", "deviceId": "device-a"}
        )
        self.assertEqual(first["installId"], "install-a")

        with self.assertRaises(self.server.ActivationError) as raised:
            self.server.activate_code(
                {"code": code, "installId": "install-b", "deviceId": "device-b"}
            )
        self.assertEqual(raised.exception.status, 403)

    def test_bulk_update_validates_code_hash_count_and_format(self) -> None:
        with self.assertRaises(self.server.ActivationError) as bad_hash:
            self.server.bulk_update_code_records({"codeHashes": ["not-a-sha256"]})
        self.assertEqual(bad_hash.exception.status, 400)

        with self.assertRaises(self.server.ActivationError) as too_many:
            self.server.bulk_update_code_records(
                {"codeHashes": ["a" * 64 for _ in range(self.server.MAX_BULK_CODE_HASHES + 1)]}
            )
        self.assertEqual(too_many.exception.status, 400)

    def test_admin_sessions_and_merchant_code_scope(self) -> None:
        admin, admin_temporary_password = self.server.create_account_record(
            username="admin",
            display_name="Root",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        merchant, merchant_temporary_password = self.server.create_account_record(
            username="merchant-one",
            display_name="Merchant One",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        other, _ = self.server.create_account_record(
            username="merchant-two",
            display_name="Merchant Two",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        self.assertEqual(admin_temporary_password, "")
        self.assertEqual(merchant_temporary_password, "")
        self.assertTrue(self.server.verify_password("merchant-password-123", self.server.get_account_by_id(merchant["accountId"])["password_hash"]))

        session_token, _ = self.server.create_admin_session(merchant["accountId"])
        merchant_context = self.server.load_admin_context_from_session(session_token)
        self.assertIsNotNone(merchant_context)
        assert merchant_context is not None
        self.assertEqual(merchant_context["role"], self.server.ACCOUNT_ROLE_MERCHANT)

        code = self.server.create_code_records(
            count=1,
            licensee="Owned Customer",
            edition="pro",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
            owner_account_id=merchant["accountId"],
        )[0]
        other_context = {"accountId": other["accountId"], "role": self.server.ACCOUNT_ROLE_MERCHANT}
        admin_context = {"accountId": admin["accountId"], "role": self.server.ACCOUNT_ROLE_SUPER_ADMIN}

        self.assertEqual(
            [row["codeHash"] for row in self.server.get_code_rows(merchant_context)],
            [self.server.code_hash(code)],
        )
        self.assertEqual(self.server.get_code_rows(other_context), [])
        self.assertEqual(len(self.server.get_code_rows(admin_context)), 1)

        with self.assertRaises(self.server.ActivationError) as raised:
            self.server.update_code_record(
                {
                    "codeHash": self.server.code_hash(code),
                    "licensee": "Forbidden Edit",
                    "edition": "pro",
                    "features": "openclaw",
                    "expires": self.expires(),
                    "maxActivations": 1,
                },
                current_account=other_context,
            )
        self.assertEqual(raised.exception.status, 403)
        self.assertTrue(self.server.revoke_admin_session(session_token))
        self.assertIsNone(self.server.load_admin_context_from_session(session_token))

    def test_account_generated_password_and_minimum_length(self) -> None:
        account, temporary_password = self.server.create_account_record(username="new-merchant")
        self.assertTrue(temporary_password)
        self.assertTrue(
            self.server.verify_password(
                temporary_password,
                self.server.get_account_by_id(account["accountId"])["password_hash"],
            )
        )
        with self.assertRaises(self.server.ActivationError):
            self.server.create_account_record(username="short-pass", password="short")

    def test_invite_registration_creates_merchant_and_consumes_code(self) -> None:
        admin, _ = self.server.create_account_record(
            username="admin",
            display_name="Root",
            password="admin-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        invite, raw_code = self.server.create_invite_record(
            note="seller invite",
            max_uses=1,
            expires_at=(date.today() + timedelta(days=30)).isoformat(),
            created_by=admin["accountId"],
        )

        self.assertEqual(invite["status"], "active")
        self.assertEqual(self.server.count_invites(active_only=True), 1)

        account, used_code, _ = self.server.register_account_with_invite(
            invite_code=raw_code.lower(),
            username="merchant-invite",
            display_name="Invite Merchant",
            password="merchant-password-123",
            request_ip="127.0.0.1",
        )

        self.assertEqual(used_code, raw_code)
        self.assertEqual(account["role"], self.server.ACCOUNT_ROLE_MERCHANT)
        self.assertEqual(account["displayName"], "Invite Merchant")
        self.assertEqual(self.server.count_invites(active_only=True), 0)

        rows = self.server.list_invite_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "used")
        self.assertEqual(rows[0]["usedCount"], 1)
        self.assertEqual(rows[0]["lastUsedUsername"], "merchant-invite")

        session_token, _ = self.server.create_admin_session(account["accountId"])
        context = self.server.load_admin_context_from_session(session_token)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["role"], self.server.ACCOUNT_ROLE_MERCHANT)

        with self.assertRaises(self.server.ActivationError) as raised:
            self.server.register_account_with_invite(
                invite_code=raw_code,
                username="merchant-second",
                password="merchant-password-456",
            )
        self.assertEqual(raised.exception.status, 403)

    def test_publish_relay_queue_claim_complete_and_auth(self) -> None:
        self.assertTrue(
            self.server.publish_relay_token_valid(
                {"Authorization": "Bearer test-relay-token"}
            )
        )
        self.assertFalse(
            self.server.publish_relay_token_valid(
                {"Authorization": "Bearer wrong-token"}
            )
        )

        packet = {
            "schema": "openclaw.publish.packet.v1",
            "channelId": "test-channel",
            "platformId": "custom",
            "title": "relay test",
            "body": "relay test",
            "media": [],
        }
        queued = self.server.publish_relay_enqueue(packet)
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(queued["channelId"], "test-channel")

        stats = self.server.publish_relay_stats("test-channel")
        self.assertEqual(stats["pending"], 1)

        claimed = self.server.publish_relay_claim("test-channel", "test-client", 30_000)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["packet"]["schema"], "openclaw.publish.packet.v1")
        self.assertEqual(claimed["attempts"], 1)
        self.assertEqual(claimed["leasedBy"], "test-client")

        already_leased = self.server.publish_relay_claim("test-channel", "other-client", 30_000)
        self.assertIsNone(already_leased)

        completed = self.server.publish_relay_complete(
            {
                "packetId": claimed["id"],
                "leaseId": claimed["leaseId"],
                "clientId": "test-client",
                "success": True,
                "result": {"ok": True},
            }
        )
        self.assertEqual(completed["status"], "done")
        final = self.server.publish_relay_status(claimed["id"])
        self.assertEqual(final["status"], "done")
        self.assertEqual(final["packet"]["title"], "relay test")

    def test_public_root_and_head_requests_are_release_ready(self) -> None:
        self.server.update_public_settings(
            {
                "cardSiteEnabled": True,
                "cardSiteLabel": "购买授权码",
                "cardSiteUrl": "https://shop.example.com/luming",
            }
        )

        body, headers = self.request_raw("GET", "/")
        html = body.decode("utf-8")
        self.assertIn("麓鸣商业授权中心", html)
        self.assertIn("https://shop.example.com/luming", html)
        self.assertEqual(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

        head_body, head_headers = self.request_raw("HEAD", "/health")
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers.get_content_type(), "application/json")

        admin_head, admin_headers = self.request_raw("HEAD", "/admin")
        self.assertEqual(admin_head, b"")
        self.assertEqual(admin_headers.get_content_type(), "text/html")

    def test_admin_pages_and_api_send_hardened_security_headers(self) -> None:
        _, page_headers = self.request_raw("GET", "/admin")
        self.assertIn("default-src 'self'", page_headers.get("Content-Security-Policy", ""))
        self.assertEqual(page_headers.get("Strict-Transport-Security"), "max-age=31536000; includeSubDomains")
        self.assertEqual(page_headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(page_headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(page_headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(page_headers.get("Cache-Control"), "no-store")

        _, api_headers = self.request_raw(
            "GET",
            "/admin/api/codes",
            expected_status=401,
        )
        self.assertEqual(api_headers.get("Cache-Control"), "no-store")

    def test_login_sets_http_only_cookie_and_cookie_auth_is_backward_compatible(self) -> None:
        self.server.create_account_record(
            username="cookie-admin",
            password="cookie-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        login, login_headers = self.request_raw(
            "POST",
            "/admin/api/auth/login",
            payload={"username": "cookie-admin", "password": "cookie-password-123"},
        )
        login_payload = json.loads(login.decode("utf-8"))
        cookie = login_headers.get("Set-Cookie", "")
        self.assertIn("__Host-luming_admin_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/", cookie)

        cookie_pair = cookie.split(";", 1)[0]
        current = self.request_json(
            "GET",
            "/admin/api/me",
            headers={"Cookie": cookie_pair},
        )
        self.assertEqual(current["account"]["username"], "cookie-admin")
        self.assertTrue(login_payload["sessionToken"])

        _, logout_headers = self.request_raw(
            "POST",
            "/admin/api/auth/logout",
            payload={},
            headers={"Cookie": cookie_pair},
        )
        self.assertIn("Max-Age=0", logout_headers.get("Set-Cookie", ""))

    def test_destructive_code_delete_requires_explicit_confirmation(self) -> None:
        admin, _ = self.server.create_account_record(
            username="danger-admin",
            password="danger-password-123",
            role=self.server.ACCOUNT_ROLE_SUPER_ADMIN,
        )
        session, _ = self.server.create_admin_session(admin["accountId"])
        code = self.server.create_code_records(
            count=1,
            licensee="Danger Customer",
            edition="team",
            features=["openclaw"],
            expires=self.expires(),
            max_activations=1,
        )[0]
        code_hash_value = self.server.code_hash(code)

        self.request_json(
            "POST",
            "/admin/api/codes/delete",
            payload={"codeHash": code_hash_value},
            headers={"X-Admin-Session": session},
            expected_status=400,
        )
        deleted = self.request_json(
            "POST",
            "/admin/api/codes/delete",
            payload={"codeHash": code_hash_value, "confirmation": "DELETE"},
            headers={"X-Admin-Session": session},
        )
        self.assertTrue(deleted["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
