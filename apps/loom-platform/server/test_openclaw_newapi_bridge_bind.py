from __future__ import annotations

import importlib.util
import base64
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

import bcrypt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


MODULE_PATH = Path(__file__).with_name("openclaw_newapi_bridge.py")


def load_bridge():
    spec = importlib.util.spec_from_file_location("openclaw_newapi_bridge_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class BindTicketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = load_bridge()
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge.BIND_DB_PATH = str(Path(self.tmp.name) / "bind-tickets.db")
        self.bridge.DB_PATH = str(Path(self.tmp.name) / "one-api.db")
        self.original_launcher_token = self.bridge.handle_launcher_token
        self.original_send_code = self.bridge._send_login_email_code
        self.original_fetch_models = self.bridge.fetch_models
        self.original_request_json = self.bridge.request_json
        self.original_authenticate_user = self.bridge.authenticate_user
        self.original_auth_failure_limit = self.bridge.AUTH_FAILURE_RATE_LIMIT
        self.original_public_api_base = self.bridge.PUBLIC_API_BASE
        self.original_entitlement_private_key_b64 = getattr(self.bridge, "ENTITLEMENT_PRIVATE_KEY_B64", "")
        self.original_entitlement_key_id = getattr(self.bridge, "ENTITLEMENT_KEY_ID", "")
        self.original_trusted_entitlement_key_id = self.bridge.TRUSTED_ENTITLEMENT_KEY_ID
        self.original_trusted_entitlement_public_key_b64 = (
            self.bridge.TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64
        )
        self.original_lease_ttl = getattr(self.bridge, "ENTITLEMENT_LEASE_TTL_SEC", 0)
        self.original_offline_grace = getattr(self.bridge, "ENTITLEMENT_OFFLINE_GRACE_SEC", 0)
        self.original_authorization_refresh_ttl = getattr(
            self.bridge,
            "ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC",
            0,
        )
        self.original_license_service_base = self.bridge.LICENSE_ENTITLEMENT_SERVICE_BASE
        self.original_license_service_token = self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN
        self.original_current_entitlement = (
            self.bridge.current_authorization_entitlement_from_license_server
        )
        self.original_redeem_code = getattr(
            self.bridge,
            "redeem_authorization_code_with_license_server",
            None,
        )
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.signing_public_key = private_key.public_key()
        self.bridge.ENTITLEMENT_PRIVATE_KEY_B64 = base64.b64encode(private_bytes).decode("ascii")
        self.bridge.ENTITLEMENT_KEY_ID = "test-ed25519-v1"
        self.bridge.TRUSTED_ENTITLEMENT_KEY_ID = "test-ed25519-v1"
        self.bridge.TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64 = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        self.bridge.ENTITLEMENT_LEASE_TTL_SEC = 3600
        self.bridge.ENTITLEMENT_OFFLINE_GRACE_SEC = 72 * 3600
        if hasattr(self.bridge, "_ENTITLEMENT_AUTHORIZATION_REFRESHED_AT"):
            self.bridge._ENTITLEMENT_AUTHORIZATION_REFRESHED_AT.clear()
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = ""
        self._init_newapi_db()

    def tearDown(self) -> None:
        self.bridge.handle_launcher_token = self.original_launcher_token
        self.bridge._send_login_email_code = self.original_send_code
        self.bridge.fetch_models = self.original_fetch_models
        self.bridge.request_json = self.original_request_json
        self.bridge.authenticate_user = self.original_authenticate_user
        self.bridge.AUTH_FAILURE_RATE_LIMIT = self.original_auth_failure_limit
        self.bridge.PUBLIC_API_BASE = self.original_public_api_base
        self.bridge.ENTITLEMENT_PRIVATE_KEY_B64 = self.original_entitlement_private_key_b64
        self.bridge.ENTITLEMENT_KEY_ID = self.original_entitlement_key_id
        self.bridge.TRUSTED_ENTITLEMENT_KEY_ID = self.original_trusted_entitlement_key_id
        self.bridge.TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64 = (
            self.original_trusted_entitlement_public_key_b64
        )
        self.bridge.ENTITLEMENT_LEASE_TTL_SEC = self.original_lease_ttl
        self.bridge.ENTITLEMENT_OFFLINE_GRACE_SEC = self.original_offline_grace
        if hasattr(self.bridge, "ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC"):
            self.bridge.ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC = (
                self.original_authorization_refresh_ttl
            )
        if hasattr(self.bridge, "_ENTITLEMENT_AUTHORIZATION_REFRESHED_AT"):
            self.bridge._ENTITLEMENT_AUTHORIZATION_REFRESHED_AT.clear()
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_BASE = self.original_license_service_base
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = self.original_license_service_token
        self.bridge.current_authorization_entitlement_from_license_server = (
            self.original_current_entitlement
        )
        if self.original_redeem_code is not None:
            self.bridge.redeem_authorization_code_with_license_server = self.original_redeem_code
        self.tmp.cleanup()

    def verify_lease_signature(self, lease):
        signature = base64.b64decode(lease["signature"])
        signed = dict(lease)
        signed.pop("signature")
        self.signing_public_key.verify(
            signature,
            self.bridge.canonical_json(signed).encode("utf-8"),
        )

    def test_raw_entitlement_signing_key_preserves_whitespace_bytes(self):
        private_bytes = b" " + bytes(range(1, 31)) + b"\n"
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        self.bridge.ENTITLEMENT_PRIVATE_KEY_B64 = base64.b64encode(private_bytes).decode("ascii")
        self.bridge.TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64 = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

        payload = {"schema": "loom.entitlement_test.v1", "accountId": "42"}
        signature = base64.b64decode(self.bridge.sign_entitlement_payload(payload))

        private_key.public_key().verify(
            signature,
            self.bridge.canonical_json(payload).encode("utf-8"),
        )

    def test_base64_private_key_file_matches_license_server_format(self):
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        loaded = self.bridge._private_key_from_bytes(
            base64.b64encode(private_bytes) + b"\n"
        )

        self.assertEqual(
            loaded.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            private_bytes,
        )

    def test_signer_mismatch_fails_before_minting_any_lease(self):
        self.bridge.TRUSTED_ENTITLEMENT_PUBLIC_KEY_B64 = base64.b64encode(
            b"\0" * 32
        ).decode("ascii")

        with self.assertRaisesRegex(RuntimeError, "trust anchor"):
            self.bridge.sign_entitlement_payload(
                {"schema": "loom.entitlement_test.v1", "accountId": "42"}
            )

    def test_deployment_sample_matches_desktop_entitlement_trust_anchor(self):
        platform_root = MODULE_PATH.parents[1]
        env_text = MODULE_PATH.with_name(
            "openclaw-newapi-bridge.env.example"
        ).read_text(encoding="utf-8")
        rust_text = (
            platform_root
            / "openclaw_new_launcher"
            / "src-tauri"
            / "src"
            / "license.rs"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "OPENCLAW_ENTITLEMENT_KEY_ID=openclaw-ed25519-v1",
            env_text,
        )
        self.assertIn(
            "OPENCLAW_ENTITLEMENT_PRIVATE_KEY_FILE=/opt/openclaw-license/private_key.b64",
            env_text,
        )
        self.assertIn(
            'const ACCOUNT_ENTITLEMENT_KEY_ID: &str = "openclaw-ed25519-v1";',
            rust_text,
        )
        self.assertIn(
            self.original_trusted_entitlement_public_key_b64,
            rust_text,
        )

    def _init_newapi_db(self) -> None:
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.executescript(
                """
                create table users (
                    id integer primary key,
                    username text,
                    password text,
                    display_name text,
                    role integer,
                    status integer,
                    email text,
                    "group" text,
                    deleted_at datetime
                );
                create table tokens (
                    id integer primary key autoincrement,
                    user_id integer,
                    key varchar(128),
                    status integer default 1,
                    name text,
                    created_time integer,
                    accessed_time integer,
                    expired_time integer default -1,
                    remain_quota integer default 0,
                    unlimited_quota numeric,
                    model_limits_enabled numeric,
                    model_limits text,
                    allow_ips text default '',
                    used_quota integer default 0,
                    "group" text default '',
                    cross_group_retry numeric,
                    deleted_at datetime
                );
                create table options (
                    key text primary key,
                    value text
                );
                """
            )
            password_hash = bcrypt.hashpw(b"password-not-real", bcrypt.gensalt(rounds=4)).decode("utf-8")
            connection.execute(
                'insert into users(id, username, password, status, email, "group", deleted_at) values(42, ?, ?, 1, ?, ?, null)',
                ("user@example.com", password_hash, "user@example.com", "default"),
            )
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "default", null)',
                ("sk-test-secret-value", "LOOM test token"),
            )
            connection.commit()
        finally:
            connection.close()

    def stub_launcher_token(self, _body):
        return 200, {
            "success": True,
            "data": {
                "userId": "42",
                "account": "user@example.com",
                "key": "sk-test-secret-value",
                "tokenMasked": "sk-t***alue",
                "tokenId": 7,
                "tokenName": "OpenClaw Launcher",
                "source": "existing",
                "models": ["qwen3.7-plus", "agnes-2.0-flash"],
            },
        }

    def test_start_returns_ticket_without_raw_key(self):
        self.bridge.handle_launcher_token = self.stub_launcher_token

        status, payload = self.bridge.handle_bind_start({"username": "user@example.com", "password": "pw"})

        self.assertEqual(status, 200, payload)
        data = payload["data"]
        self.assertTrue(data["ticket"].startswith("ocb_"))
        self.assertEqual(data["account"], "user@example.com")
        self.assertEqual(data["tokenMasked"], "sk-t***alue")
        self.assertIn("models", data)
        self.assertNotIn("key", data)

    def test_bind_ticket_database_never_contains_plain_api_token(self):
        self.bridge.handle_launcher_token = self.stub_launcher_token

        status, payload = self.bridge.handle_bind_start(
            {"username": "user@example.com", "password": "pw"}
        )

        self.assertEqual(status, 200, payload)
        raw_database = Path(self.bridge.BIND_DB_PATH).read_bytes()
        self.assertNotIn(b"sk-test-secret-value", raw_database)

    def test_launcher_payload_does_not_reuse_limited_historical_token(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 1, "agnes-2.0-flash", "default", null)',
                ("sk-limited-old", "old user token"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda token: ["qwen3.7-plus"] if token != "sk-limited-old" else ["agnes-2.0-flash"]

        self.assertIsNone(self.bridge.select_token("42"))
        status, payload = self.bridge.build_launcher_payload(user_id="42", account="user@example.com", group="default")

        self.assertEqual(status, 200, payload)
        data = payload["data"]
        self.assertEqual(data["source"], "created")
        self.assertTrue(data["tokenName"].startswith("LOOM Launcher "))
        self.assertFalse(data["modelLimitsEnabled"])
        self.assertNotEqual(data["key"], "sk-limited-old")
        self.assertEqual(data["models"], ["qwen3.7-plus"])

    def test_launcher_payload_does_not_reuse_unrestricted_arbitrary_token(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "default", null)',
                ("sk-arbitrary-old", "Default API token"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        self.assertIsNone(self.bridge.select_token("42"))
        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
        )

        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertNotEqual(data["key"], "sk-arbitrary-old")
        self.assertTrue(data["tokenName"].startswith("LOOM Launcher "))
        self.assertEqual(data["tokenKind"], "launcher")

    def test_created_launcher_token_uses_newapi_default_policy(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="pro",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["permissionMode"], "default")
        connection = sqlite3.connect(self.bridge.DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            token = connection.execute(
                """
                select expired_time, remain_quota, unlimited_quota, model_limits_enabled,
                       model_limits, allow_ips, \"group\", cross_group_retry
                from tokens
                where name = ?
                """,
                (payload["data"]["tokenName"],),
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(token)
        self.assertEqual(token["expired_time"], -1)
        self.assertEqual(token["remain_quota"], 0)
        self.assertEqual(token["unlimited_quota"], 1)
        self.assertEqual(token["model_limits_enabled"], 0)
        self.assertEqual(token["model_limits"], "")
        self.assertEqual(token["allow_ips"], "")
        self.assertEqual(token["group"], "pro")
        self.assertEqual(token["cross_group_retry"], 0)
        self.assertEqual(payload["data"]["tokenGroup"], "pro")

    def test_unactivated_launcher_payload_blocks_matrix_without_signed_lease(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
            install_id="install-a",
            device_id="host-a",
        )

        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertNotIn("entitlementLease", data)
        self.assertNotIn("entitlementKey", data)
        self.assertEqual(data["entitlement"]["source"], "authorization_required")
        self.assertEqual(data["entitlement"]["features"], [])
        self.assertEqual(data["entitlement"]["limits"]["devices"], 0)
        self.assertEqual(data["entitlement"]["limits"]["concurrentTasks"], 0)

    def test_unactivated_account_can_login_on_multiple_hosts_without_phone_access(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        for index in range(3):
            status, payload = self.bridge.build_launcher_payload(
                user_id="42",
                account="user@example.com",
                group="default",
                install_id=f"install-{index}",
                device_id=f"host-{index}",
            )
            self.assertEqual(status, 200)
            self.assertNotIn("entitlementLease", payload["data"])
            self.assertEqual(
                payload["data"]["entitlement"]["source"],
                "authorization_required",
            )

    def _activated_lease(self, *, install_id="install-a", host_device_id="host-a"):
        self.bridge.persist_account_entitlement_grant(
            "42",
            {
                "source": "authorization_code",
                "plan": "activated",
                "features": [
                    "matrix.devices",
                    "matrix.tasks",
                    "matrix.parallel_tasks",
                    "matrix.diagnostics",
                ],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 8,
                    "unlimitedDevices": True,
                },
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "LM-ACTIVE-****-TEST",
            },
            action="test_seed",
        )
        status, payload = self.bridge.issue_entitlement_lease(
            account_id="42",
            group="default",
            install_id=install_id,
            device_id=host_device_id,
            session_token="sk-test-secret-value",
            source_verified=True,
        )
        self.assertEqual(status, 200, payload)
        return payload["entitlementLease"]

    def test_activated_account_can_claim_multiple_phones(self):
        lease = self._activated_lease()
        status, payload = self.bridge.authorize_entitlement_operation(
            lease,
            "matrix.device.claim",
            ["phone-a"],
        )
        self.assertEqual(status, 200)

        status, payload = self.bridge.authorize_entitlement_operation(
            lease,
            "matrix.device.claim",
            ["phone-b"],
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(
            payload["phoneSeatLease"]["phoneDeviceIds"],
            ["phone-a", "phone-b"],
        )
        self.assertEqual(
            self.bridge.entitlement_audit_events("42")[-1]["code"],
            "ok",
        )

    def test_activated_account_phone_claim_is_idempotent_and_release_allows_replacement(self):
        lease = self._activated_lease()

        for _ in range(3):
            status, payload = self.bridge.authorize_entitlement_operation(
                lease,
                "matrix.task.start",
                ["phone-a"],
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["claimedPhoneDeviceIds"], ["phone-a"])
            seat_lease = payload["phoneSeatLease"]
            self.assertEqual(seat_lease["schema"], "loom.phone_seat_lease.v1")
            self.assertEqual(seat_lease["accountId"], "42")
            self.assertEqual(seat_lease["hostDeviceId"], "host-a")
            self.assertEqual(seat_lease["phoneDeviceIds"], ["phone-a"])
            self.verify_lease_signature(seat_lease)

        status, payload = self.bridge.authorize_entitlement_operation(
            lease,
            "matrix.device.release",
            ["phone-a"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["releasedPhoneDeviceIds"], ["phone-a"])
        self.assertEqual(payload["phoneSeatLease"]["phoneDeviceIds"], [])
        self.verify_lease_signature(payload["phoneSeatLease"])

        status, payload = self.bridge.authorize_entitlement_operation(
            lease,
            "matrix.device.claim",
            ["phone-b"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["claimedPhoneDeviceIds"], ["phone-b"])

    def test_phone_identity_cannot_be_claimed_by_two_accounts_without_repair(self):
        first_lease = self._activated_lease()
        status, payload = self.bridge.authorize_entitlement_operation(
            first_lease,
            "matrix.device.claim",
            ["physical-phone-a"],
        )
        self.assertEqual(status, 200, payload)

        self.bridge.persist_account_entitlement_grant(
            "43",
            {
                "source": "authorization_code",
                "plan": "activated",
                "features": [
                    "matrix.devices",
                    "matrix.tasks",
                    "matrix.parallel_tasks",
                    "matrix.diagnostics",
                ],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 8,
                    "unlimitedDevices": True,
                },
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "LM-ACTIVE-****-OTHER",
            },
            action="test_seed",
        )
        status, second_payload = self.bridge.issue_entitlement_lease(
            account_id="43",
            group="default",
            install_id="install-b",
            device_id="host-b",
            session_token="sk-other-secret-value",
            source_verified=True,
        )
        self.assertEqual(status, 200, second_payload)
        second_lease = second_payload["entitlementLease"]

        denied_status, denied = self.bridge.authorize_entitlement_operation(
            second_lease,
            "matrix.device.claim",
            ["physical-phone-a"],
        )

        self.assertEqual(denied_status, 409)
        self.assertEqual(denied["code"], "phone_owned_by_another_account")
        self.assertEqual(denied["action"], "repair_phone")

    def test_verified_repair_transfers_phone_identity_to_current_account(self):
        first_lease = self._activated_lease()
        status, payload = self.bridge.authorize_entitlement_operation(
            first_lease,
            "matrix.device.claim",
            ["physical-phone-a"],
        )
        self.assertEqual(status, 200, payload)

        self.bridge.persist_account_entitlement_grant(
            "43",
            {
                "source": "authorization_code",
                "plan": "activated",
                "features": [
                    "matrix.devices",
                    "matrix.tasks",
                    "matrix.parallel_tasks",
                    "matrix.diagnostics",
                ],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 8,
                    "unlimitedDevices": True,
                },
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "LM-ACTIVE-****-OTHER",
            },
            action="test_seed",
        )
        status, second_payload = self.bridge.issue_entitlement_lease(
            account_id="43",
            group="default",
            install_id="install-b",
            device_id="host-b",
            session_token="sk-other-secret-value",
            source_verified=True,
        )
        self.assertEqual(status, 200, second_payload)
        second_lease = second_payload["entitlementLease"]

        transfer_status, transferred = self.bridge.authorize_entitlement_operation(
            second_lease,
            "matrix.device.reclaim",
            ["physical-phone-a"],
        )
        self.assertEqual(transfer_status, 200, transferred)
        self.assertEqual(
            transferred["claimedPhoneDeviceIds"],
            ["physical-phone-a"],
        )
        self.assertEqual(
            transferred["reclaimedPhoneDeviceIds"],
            ["physical-phone-a"],
        )

        old_status, old_payload = self.bridge.authorize_entitlement_operation(
            first_lease,
            "matrix.task.start",
            ["physical-phone-a"],
        )
        self.assertEqual(old_status, 409)
        self.assertEqual(old_payload["code"], "phone_owned_by_another_account")

    def test_entitlement_check_requires_token_owned_by_lease_account(self):
        lease = self._activated_lease()

        status, payload = self.bridge.handle_entitlement_check(
            {
                "entitlementLease": lease,
                "operation": "matrix.device.claim",
                "phoneDeviceIds": ["phone-a"],
            },
            "",
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], "account_token_required")

        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute(
                'insert into users(id, username, password, status, email, "group", deleted_at) values(43, ?, ?, 1, ?, ?, null)',
                ("other@example.com", "unused", "other@example.com", "default"),
            )
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(43, ?, 1, ?, 1, -1, 0, 1, 0, "", "default", null)',
                ("sk-other-secret-value", "LOOM other token"),
            )
            connection.commit()
        finally:
            connection.close()

        status, payload = self.bridge.handle_entitlement_check(
            {
                "entitlementLease": lease,
                "operation": "matrix.device.claim",
                "phoneDeviceIds": ["phone-a"],
            },
            "Bearer sk-other-secret-value",
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "account_mismatch")

        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            account_tokens = [
                str(row[0])
                for row in connection.execute(
                    "select key from tokens where user_id = 42"
                ).fetchall()
            ]
        finally:
            connection.close()
        bound_token = next(
            token
            for token in account_tokens
            if self.bridge.entitlement_session_binding(token) == lease["sessionBinding"]
        )
        status, payload = self.bridge.handle_entitlement_check(
            {
                "entitlementLease": lease,
                "operation": "matrix.device.claim",
                "phoneDeviceIds": ["phone-a"],
            },
            f"Bearer {bound_token}",
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])

    def test_entitlement_check_rejects_different_token_from_same_account(self):
        lease = self._activated_lease()
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 2, -1, 0, 1, 0, "", "default", null)',
                ("sk-second-session-token", "LOOM second session"),
            )
            connection.commit()
        finally:
            connection.close()

        status, payload = self.bridge.handle_entitlement_check(
            {
                "entitlementLease": lease,
                "operation": "matrix.device.claim",
                "phoneDeviceIds": ["phone-a"],
            },
            "Bearer sk-second-session-token",
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "account_session_mismatch")

    def test_model_service_group_does_not_silently_upgrade_matrix_entitlement(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="svip",
            install_id="install-a",
            device_id="phone-a",
        )

        self.assertEqual(status, 200)
        self.assertNotIn("entitlementLease", payload["data"])
        self.assertEqual(
            payload["data"]["entitlement"]["source"],
            "authorization_required",
        )
        self.assertEqual(payload["data"]["entitlement"]["limits"]["devices"], 0)

    def test_cached_paid_grant_cannot_mint_fresh_lease_without_license_service(self):
        self.bridge.persist_account_entitlement_grant(
            "42",
            {
                "source": "authorization_code",
                "plan": "matrix_pro",
                "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
                "limits": {"devices": 4, "concurrentTasks": 2},
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "OC-PRO-****-ZZ99",
            },
            action="test_seed",
        )
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = ""

        status, payload = self.bridge.issue_entitlement_lease(
            account_id="42",
            group="default",
            install_id="install-a",
            device_id="host-a",
            session_token="sk-test-secret-value",
        )

        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "authorization_service_unavailable")
        self.assertNotIn("entitlementLease", payload)

    def test_fresh_lease_syncs_permanent_revocation_and_blocks_phone_access(self):
        self.bridge.persist_account_entitlement_grant(
            "42",
            {
                "source": "authorization_code",
                "plan": "matrix_pro",
                "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
                "limits": {"devices": 4, "concurrentTasks": 2},
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "OC-PRO-****-ZZ99",
            },
            action="test_seed",
        )
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"

        def revoked(_account_id):
            raise self.bridge.BridgeUpstreamError(
                "Authorization code was revoked",
                status_code=410,
                code="ACCOUNT_ENTITLEMENT_REVOKED",
            )

        self.bridge.current_authorization_entitlement_from_license_server = revoked

        status, payload = self.bridge.issue_entitlement_lease(
            account_id="42",
            group="default",
            install_id="install-a",
            device_id="host-a",
            session_token="sk-test-secret-value",
        )

        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["code"], "authorization_required")
        self.assertEqual(payload["entitlement"]["source"], "authorization_required")
        self.assertEqual(payload["entitlement"]["limits"]["devices"], 0)

    def test_license_service_rejects_non_https_endpoint_before_network_call(self):
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_BASE = "http://license.example"
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
        original_urlopen = self.bridge.urllib.request.urlopen
        self.bridge.urllib.request.urlopen = lambda *_args, **_kwargs: self.fail(
            "insecure license request reached the network"
        )
        try:
            with self.assertRaises(self.bridge.BridgeUpstreamError) as raised:
                self.bridge.current_authorization_entitlement_from_license_server("42")
        finally:
            self.bridge.urllib.request.urlopen = original_urlopen

        self.assertEqual(raised.exception.code, "ENTITLEMENT_SERVICE_INSECURE")

    def test_paid_offline_grace_never_extends_past_authorization_expiry(self):
        now = int(time.time())
        grant_expires_at = now + 1800

        lease = self.bridge.signed_entitlement_lease(
            account_id="42",
            session_token="sk-test-secret-value",
            install_id="install-a",
            device_id="host-a",
            policy={
                "plan": "matrix_pro",
                "source": "authorization_code",
                "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
                "limits": {"devices": 4, "concurrentTasks": 2},
                "expiresAt": grant_expires_at,
            },
            entitlement_version=1,
            now=now,
        )

        self.assertEqual(lease["expiresAt"], grant_expires_at)
        self.assertEqual(lease["offlineGraceUntil"], grant_expires_at)

    def test_redeemed_authorization_code_upgrades_account_and_survives_refresh(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        seen = []
        entitlement = {
            "source": "authorization_code",
            "plan": "pro",
            "features": [
                "matrix.devices",
                "matrix.tasks",
                "matrix.parallel_tasks",
                "matrix.diagnostics",
            ],
            "limits": {"devices": 5, "concurrentTasks": 3},
            "expiresAt": int(time.time()) + 30 * 86400,
            "codeLabel": "OC-PRO-****-A1B2",
        }

        def redeem(code, *, account_id):
            seen.append((code, account_id))
            return dict(entitlement)

        self.bridge.redeem_authorization_code_with_license_server = redeem
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
        self.bridge.current_authorization_entitlement_from_license_server = (
            lambda _account_id: dict(entitlement)
        )
        status, payload = self.bridge.handle_entitlement_redeem(
            {
                "code": "OC-PRO-SECRET-A1B2",
                "installId": "install-a",
                "deviceId": "host-a",
            },
            "Bearer sk-test-secret-value",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(seen, [("OC-PRO-SECRET-A1B2", "42")])
        lease = payload["entitlementLease"]
        self.assertEqual(lease["accountId"], "42")
        self.assertEqual(
            lease["limits"],
            {
                "devices": 1000,
                "concurrentTasks": 3,
                "unlimitedDevices": True,
            },
        )
        self.assertEqual(payload["entitlement"]["source"], "authorization_code")
        self.verify_lease_signature(lease)

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
            install_id="install-a",
            device_id="host-a",
        )
        self.assertEqual(status, 200)
        lease_a = payload["data"]["entitlementLease"]
        self.assertEqual(
            lease_a["limits"],
            {
                "devices": 1000,
                "concurrentTasks": 3,
                "unlimitedDevices": True,
            },
        )
        self.assertEqual(payload["data"]["entitlement"]["source"], "authorization_code")

        status, payload = self.bridge.authorize_entitlement_operation(
            lease_a,
            "matrix.device.claim",
            ["phone-a", "phone-b"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            payload["phoneSeatLease"]["phoneDeviceIds"],
            ["phone-a", "phone-b"],
        )
        self.verify_lease_signature(payload["phoneSeatLease"])

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
            install_id="install-b",
            device_id="host-b",
        )
        self.assertEqual(status, 200)
        lease_b = payload["data"]["entitlementLease"]
        status, payload = self.bridge.authorize_entitlement_operation(
            lease_b,
            "matrix.device.claim",
            ["phone-c"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["phoneSeatLease"]["phoneDeviceIds"], ["phone-c"])
        self.verify_lease_signature(payload["phoneSeatLease"])

    def test_authorization_expiry_parsing_is_utc_and_accepts_z_suffix(self):
        self.assertEqual(
            self.bridge._entitlement_expiry_epoch("2030-01-01T00:00:00Z"),
            1_893_456_000,
        )
        self.assertEqual(
            self.bridge._entitlement_expiry_epoch("2030-01-01"),
            1_893_542_399,
        )

    def test_entitlement_redeem_requires_account_token_and_never_persists_plain_code(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        self.bridge.redeem_authorization_code_with_license_server = lambda *_args, **_kwargs: {
            "source": "authorization_code",
            "plan": "standard",
            "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
            "limits": {"devices": 3, "concurrentTasks": 2},
            "expiresAt": int(time.time()) + 86400,
            "codeLabel": "OC-STANDARD-****-ZZ99",
        }

        status, payload = self.bridge.handle_entitlement_redeem(
            {
                "code": "OC-STANDARD-TOP-SECRET-ZZ99",
                "installId": "install-a",
                "deviceId": "host-a",
            },
            "",
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], "account_token_required")

        status, payload = self.bridge.handle_entitlement_redeem(
            {
                "code": "OC-STANDARD-TOP-SECRET-ZZ99",
                "installId": "install-a",
                "deviceId": "host-a",
            },
            "Bearer sk-test-secret-value",
        )
        self.assertEqual(status, 200, payload)
        self.assertNotIn("OC-STANDARD-TOP-SECRET-ZZ99", repr(payload))
        raw_db = Path(self.bridge.BIND_DB_PATH).read_bytes()
        self.assertNotIn(b"OC-STANDARD-TOP-SECRET-ZZ99", raw_db)

    def test_entitlement_redeem_preserves_stable_license_service_error_codes(self):
        def reject(*_args, **_kwargs):
            raise self.bridge.BridgeUpstreamError(
                "Authorization code is expired",
                status_code=403,
                code="LICENSE_EXPIRED",
            )

        self.bridge.redeem_authorization_code_with_license_server = reject

        status, payload = self.bridge.handle_entitlement_redeem(
            {
                "code": "OC-STANDARD-EXPIRED-ZZ99",
                "installId": "install-a",
                "deviceId": "host-a",
            },
            "Bearer sk-test-secret-value",
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "authorization_code_expired")

    def test_signed_legacy_license_migration_binds_current_account_without_persisting_proof(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        proof = {
            "schema": "loom.license.v1",
            "licenseId": "legacy-license-id",
            "installId": "legacy-install",
            "deviceId": "legacy-device",
            "expires": "2030-01-01",
            "signature": "legacy-signature-do-not-persist",
        }
        entitlement = {
            "source": "authorization_code",
            "plan": "matrix_pro",
            "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
            "limits": {
                "devices": 1000,
                "concurrentTasks": 3,
                "unlimitedDevices": True,
            },
            "expiresAt": int(time.time()) + 86400,
            "codeLabel": "OC-PRO-****-A1B2",
        }
        seen = []

        def migrate(legacy_license, *, account_id):
            seen.append((legacy_license, account_id))
            return dict(entitlement)

        self.bridge.migrate_legacy_authorization_with_license_server = migrate

        status, payload = self.bridge.handle_entitlement_migrate_legacy(
            {
                "legacyLicense": proof,
                "installId": "current-install",
                "deviceId": "current-host",
            },
            "Bearer sk-test-secret-value",
        )

        self.assertEqual(200, status, payload)
        self.assertEqual([(proof, "42")], seen)
        self.assertEqual("42", payload["entitlementLease"]["accountId"])
        self.verify_lease_signature(payload["entitlementLease"])
        self.assertNotIn(
            proof["signature"].encode("utf-8"),
            Path(self.bridge.BIND_DB_PATH).read_bytes(),
        )

    def test_legacy_license_migration_requires_login_and_valid_proof_shape(self):
        status, payload = self.bridge.handle_entitlement_migrate_legacy(
            {"legacyLicense": {}},
            "",
        )
        self.assertEqual(401, status)
        self.assertEqual("account_token_required", payload["code"])

        status, payload = self.bridge.handle_entitlement_migrate_legacy(
            {
                "legacyLicense": {},
                "installId": "current-install",
                "deviceId": "current-host",
            },
            "Bearer sk-test-secret-value",
        )
        self.assertEqual(400, status)
        self.assertEqual("legacy_license_proof_invalid", payload["code"])

    def test_permanent_license_revocation_downgrades_account_and_revokes_old_lease(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        entitlement = {
            "source": "authorization_code",
            "plan": "matrix_pro",
            "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
            "limits": {"devices": 4, "concurrentTasks": 2},
            "expiresAt": int(time.time()) + 86400,
            "codeLabel": "OC-PRO-****-ZZ99",
        }
        self.bridge.persist_account_entitlement_grant(
            "42",
            entitlement,
            action="test_seed",
        )
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
        self.bridge.current_authorization_entitlement_from_license_server = (
            lambda _account_id: dict(entitlement)
        )
        _, before = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
            install_id="install-a",
            device_id="host-a",
        )
        old_lease = before["data"]["entitlementLease"]

        def revoked(_account_id):
            raise self.bridge.BridgeUpstreamError(
                "Authorization code was revoked",
                status_code=410,
                code="ACCOUNT_ENTITLEMENT_REVOKED",
            )

        original_current = self.bridge.current_authorization_entitlement_from_license_server
        original_service_token = self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN
        try:
            connection = sqlite3.connect(self.bridge.DB_PATH)
            connection.execute(
                "update tokens set name = ?, key = ? where key = ?",
                ("LOOM Launcher test", "testsecretvalue123", "sk-test-secret-value"),
            )
            connection.commit()
            connection.close()
            self.bridge.current_authorization_entitlement_from_license_server = revoked
            self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
            status, refreshed = self.bridge.handle_entitlement_refresh(
                {"installId": "install-a", "deviceId": "host-a"},
                "Bearer testsecretvalue123",
            )
        finally:
            self.bridge.current_authorization_entitlement_from_license_server = original_current
            self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = original_service_token

        self.assertEqual(status, 200, refreshed)
        self.assertEqual(
            refreshed["data"]["entitlement"]["source"],
            "authorization_required",
        )
        self.assertEqual(refreshed["data"]["entitlement"]["limits"]["devices"], 0)
        self.assertNotIn("entitlementLease", refreshed["data"])
        old_status, old_result = self.bridge.authorize_entitlement_operation(
            old_lease,
            "matrix.task.start",
        )
        self.assertEqual(old_status, 403)
        self.assertEqual(old_result["code"], "lease_revoked")

    def test_temporary_license_outage_does_not_mint_a_fresh_paid_lease(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        self.bridge.persist_account_entitlement_grant(
            "42",
            {
                "source": "authorization_code",
                "plan": "matrix_pro",
                "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
                "limits": {"devices": 4, "concurrentTasks": 2},
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "OC-PRO-****-ZZ99",
            },
            action="test_seed",
        )

        def unavailable(_account_id):
            raise self.bridge.BridgeUpstreamError(
                "License service is unavailable",
                status_code=503,
            )

        original_current = self.bridge.current_authorization_entitlement_from_license_server
        original_service_token = self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN
        try:
            connection = sqlite3.connect(self.bridge.DB_PATH)
            connection.execute(
                "update tokens set name = ?, key = ? where key = ?",
                ("LOOM Launcher test", "testsecretvalue123", "sk-test-secret-value"),
            )
            connection.commit()
            connection.close()
            self.bridge.current_authorization_entitlement_from_license_server = unavailable
            self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"

            status, payload = self.bridge.handle_entitlement_refresh(
                {"installId": "install-a", "deviceId": "host-a"},
                "Bearer testsecretvalue123",
            )
        finally:
            self.bridge.current_authorization_entitlement_from_license_server = original_current
            self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = original_service_token

        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "authorization_service_unavailable")
        self.assertNotIn("entitlementLease", repr(payload))
        self.assertEqual(
            self.bridge.effective_entitlement_policy("42")["source"],
            "authorization_code",
        )

    def test_refresh_without_license_service_credentials_does_not_mint_cached_paid_lease(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        self.bridge.persist_account_entitlement_grant(
            "42",
            {
                "source": "authorization_code",
                "plan": "matrix_pro",
                "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
                "limits": {"devices": 4, "concurrentTasks": 2},
                "expiresAt": int(time.time()) + 86400,
                "codeLabel": "OC-PRO-****-ZZ99",
            },
            action="test_seed",
        )
        connection = sqlite3.connect(self.bridge.DB_PATH)
        connection.execute(
            "update tokens set name = ?, key = ? where key = ?",
            ("LOOM Launcher test", "testsecretvalue123", "sk-test-secret-value"),
        )
        connection.commit()
        connection.close()
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = ""

        status, payload = self.bridge.handle_entitlement_refresh(
            {"installId": "install-a", "deviceId": "host-a"},
            "Bearer testsecretvalue123",
        )

        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "authorization_service_unavailable")
        self.assertNotIn("entitlementLease", repr(payload))

    def test_entitlement_version_revokes_previous_lease(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        old_lease = self._activated_lease(
            install_id="install-a",
            host_device_id="phone-a",
        )

        new_version = self.bridge.revoke_account_entitlements("42", reason="password-reset")

        self.assertEqual(
            new_version,
            int(old_lease["entitlementVersion"]) + 1,
        )
        status, check = self.bridge.authorize_entitlement_operation(old_lease, "matrix.task.start")
        self.assertEqual(status, 403)
        self.assertEqual(check["code"], "lease_revoked")

        status, check = self.bridge.authorize_entitlement_operation(
            old_lease,
            "matrix.emergency_stop",
        )
        self.assertEqual(status, 200, check)
        self.assertTrue(check["success"])

    def test_operation_refreshes_authorization_and_revokes_an_active_lease(self):
        lease = self._activated_lease()
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
        self.bridge.ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC = 30
        calls = []

        def revoked(account_id):
            calls.append(account_id)
            raise self.bridge.BridgeUpstreamError(
                "Authorization code was revoked",
                status_code=410,
                code="ACCOUNT_ENTITLEMENT_REVOKED",
            )

        self.bridge.current_authorization_entitlement_from_license_server = revoked

        status, payload = self.bridge.authorize_entitlement_operation(
            lease,
            "matrix.task.start",
            ["phone-a"],
        )

        self.assertEqual(403, status)
        self.assertEqual("lease_revoked", payload["code"])
        self.assertEqual(["42"], calls)

    def test_operation_authorization_refresh_is_bounded_by_a_short_cache(self):
        lease = self._activated_lease()
        self.bridge.LICENSE_ENTITLEMENT_SERVICE_TOKEN = "service-token"
        self.bridge.ENTITLEMENT_AUTHORIZATION_REFRESH_TTL_SEC = 30
        calls = []
        entitlement = {
            "source": "authorization_code",
            "plan": "activated",
            "features": [
                "matrix.devices",
                "matrix.tasks",
                "matrix.parallel_tasks",
                "matrix.diagnostics",
            ],
            "limits": {
                "devices": 1000,
                "concurrentTasks": 8,
                "unlimitedDevices": True,
            },
            "expiresAt": int(time.time()) + 86400,
            "codeLabel": "LM-ACTIVE-****-TEST",
        }

        def current(account_id):
            calls.append(account_id)
            return dict(entitlement)

        self.bridge.current_authorization_entitlement_from_license_server = current

        for phone_id in ("phone-a", "phone-b"):
            status, payload = self.bridge.authorize_entitlement_operation(
                lease,
                "matrix.task.start",
                [phone_id],
            )
            self.assertEqual(200, status, payload)

        self.assertEqual(["42"], calls)

    def test_valid_source_reactivation_clears_revocation_and_keeps_old_lease_invalid(self):
        entitlement = {
            "source": "authorization_code",
            "plan": "matrix_pro",
            "features": ["matrix.devices", "matrix.tasks", "matrix.diagnostics"],
            "limits": {"devices": 4, "concurrentTasks": 2},
            "expiresAt": int(time.time()) + 86400,
            "codeLabel": "OC-PRO-****-R1A2",
        }
        self.bridge.persist_account_entitlement_grant(
            "42",
            entitlement,
            action="test_seed",
        )
        old_status, old_payload = self.bridge.issue_entitlement_lease(
            account_id="42",
            group="default",
            install_id="install-a",
            device_id="host-a",
            session_token="session-a",
            source_verified=True,
        )
        self.assertEqual(old_status, 200, old_payload)
        old_lease = old_payload["entitlementLease"]

        revoked_version = self.bridge.revoke_account_entitlements(
            "42",
            reason="support-review",
        )
        restored_version = self.bridge.persist_account_entitlement_grant(
            "42",
            entitlement,
            action="source_reactivated",
        )
        new_status, new_payload = self.bridge.issue_entitlement_lease(
            account_id="42",
            group="default",
            install_id="install-a",
            device_id="host-a",
            session_token="session-b",
            source_verified=True,
        )

        self.assertEqual(new_status, 200, new_payload)
        self.assertGreater(restored_version, revoked_version)
        connection = sqlite3.connect(self.bridge.BIND_DB_PATH)
        try:
            revoked_at = connection.execute(
                "select revoked_at from entitlement_accounts where account_id = ?",
                ("42",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(revoked_at, 0)
        old_check, old_result = self.bridge.authorize_entitlement_operation(
            old_lease,
            "matrix.task.start",
        )
        self.assertEqual(old_check, 403)
        self.assertEqual(old_result["code"], "lease_revoked")
        new_check, new_result = self.bridge.authorize_entitlement_operation(
            new_payload["entitlementLease"],
            "matrix.task.start",
            ["phone-a"],
        )
        self.assertEqual(new_check, 200, new_result)

    def test_expired_lease_blocks_new_matrix_tasks_but_allows_safety_operations(self):
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]
        original_ttl = self.bridge.ENTITLEMENT_LEASE_TTL_SEC
        self.bridge.ENTITLEMENT_LEASE_TTL_SEC = -1
        try:
            lease = self._activated_lease(
                install_id="install-a",
                host_device_id="phone-a",
            )
        finally:
            self.bridge.ENTITLEMENT_LEASE_TTL_SEC = original_ttl

        status, check = self.bridge.authorize_entitlement_operation(lease, "matrix.task.start")
        self.assertEqual(status, 403)
        self.assertEqual(check["code"], "lease_expired")

        status, check = self.bridge.authorize_entitlement_operation(lease, "matrix.emergency_stop")
        self.assertEqual(status, 200)
        self.assertTrue(check["success"])

    def test_concurrent_activated_phone_claims_preserve_all_phones(self):
        lease = self._activated_lease()
        results = []
        lock = threading.Lock()

        def claim(index):
            result = self.bridge.authorize_entitlement_operation(
                lease,
                "matrix.device.claim",
                [f"phone-{index}"],
            )
            with lock:
                results.append(result)

        threads = [threading.Thread(target=claim, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(1 for status, _ in results if status == 200), 8)
        connection = sqlite3.connect(self.bridge.BIND_DB_PATH)
        try:
            claimed = [
                str(row[0])
                for row in connection.execute(
                    """
                    select phone_device_id
                    from entitlement_phone_seats
                    where account_id = ? and released_at = 0
                    order by phone_device_id
                    """,
                    ("42",),
                ).fetchall()
            ]
        finally:
            connection.close()
        self.assertEqual(claimed, [f"phone-{index}" for index in range(8)])

    def test_launcher_token_in_account_group_is_reused(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "", "pro", 0, null)',
                ("explicitgroupkey", "LOOM Launcher grouped"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="pro",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["key"], "explicitgroupkey")
        self.assertEqual(payload["data"]["permissionMode"], "default")
        self.assertEqual(payload["data"]["tokenGroup"], "pro")

    def test_account_group_launcher_token_is_preferred_over_newer_empty_group_fallback(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 2, -1, 0, 1, 0, "", "", "", 0, null)',
                ("neweremptygroupkey", "LOOM Launcher empty fallback"),
            )
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "", "pro", 0, null)',
                ("olderaccountgroupkey", "LOOM Launcher account group"),
            )
            connection.commit()
        finally:
            connection.close()

        token = self.bridge.select_token("42", account_group="pro")

        self.assertIsNotNone(token)
        self.assertEqual(token["key"], "olderaccountgroupkey")
        self.assertEqual(token["tokenGroup"], "pro")

    def test_empty_group_fallback_is_migrated_to_account_group_during_login(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 2, -1, 0, 1, 0, "", "", "", 0, null)',
                ("emptygroupfallbackkey", "LOOM Launcher empty fallback"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="pro",
        )

        self.assertEqual(status, 200)
        self.assertNotEqual(payload["data"]["key"], "emptygroupfallbackkey")
        self.assertEqual(payload["data"]["tokenGroup"], "pro")

    def test_zero_expiry_launcher_token_is_not_reused_as_never_expiring(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 1, 0, 0, 1, 0, "", "", "", 0, null)',
                ("zeroexpirykey", "LOOM Launcher zero expiry"),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertIsNone(self.bridge.select_token("42"))

    def test_preferred_name_cannot_select_a_non_launcher_token(self):
        self.assertIsNone(self.bridge.select_token("42", "LOOM test token"))

    def test_expired_launcher_token_is_replaced_before_login_returns(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, 1, 0, 1, 0, "", "default", null)',
                ("expiredlaunchertoken", "LOOM Launcher expired"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        self.assertIsNone(self.bridge.select_token("42"))
        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
        )

        self.assertEqual(status, 200)
        self.assertNotEqual(payload["data"]["key"], "expiredlaunchertoken")

    def test_password_login_preserves_significant_surrounding_spaces(self):
        password = " password with spaces "
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("update users set password = ? where id = 42", (password_hash,))
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.handle_launcher_token({
            "username": "user@example.com",
            "password": password,
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])

    def test_ensure_launcher_token_rejects_arbitrary_bearer_token_to_prevent_privilege_escalation(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "default", null)',
                ("arbitrary-bearer-token", "Default API token"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.handle_ensure_launcher_token(
            {},
            "Bearer sk-arbitrary-bearer-token",
        )

        self.assertEqual(status, 403)
        self.assertFalse(payload["success"])
        self.assertIn("re-login", payload["error"])

    def test_ensure_launcher_token_accepts_existing_default_policy_launcher_token(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "", "default", 0, null)',
                ("existinglaunchertoken", "LOOM Launcher existing"),
            )
            connection.commit()
        finally:
            connection.close()
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.handle_ensure_launcher_token(
            {},
            "Bearer sk-existinglaunchertoken",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["key"], "existinglaunchertoken")
        self.assertEqual(payload["data"]["permissionMode"], "default")
        self.assertEqual(payload["data"]["tokenGroup"], "default")

    def test_ensure_launcher_token_rejects_launcher_token_from_another_group(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, allow_ips, "group", cross_group_retry, deleted_at) values(42, ?, 1, ?, 1, -1, 0, 1, 0, "", "", "pro", 0, null)',
                ("wronggrouplaunchertoken", "LOOM Launcher wrong group"),
            )
            connection.commit()
        finally:
            connection.close()

        status, payload = self.bridge.handle_ensure_launcher_token(
            {},
            "Bearer sk-wronggrouplaunchertoken",
        )

        self.assertEqual(status, 403)
        self.assertFalse(payload["success"])

    def test_ensure_launcher_token_rejects_an_unknown_bearer_token(self):
        status, payload = self.bridge.handle_ensure_launcher_token({}, "Bearer sk-unknown-token")

        self.assertEqual(status, 401)
        self.assertFalse(payload["success"])

    def test_ensure_launcher_token_rejects_zero_expiry_bearer_token(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.execute("delete from tokens")
            connection.execute(
                'insert into tokens(user_id, key, status, name, created_time, expired_time, remain_quota, unlimited_quota, model_limits_enabled, model_limits, "group", deleted_at) values(42, ?, 1, ?, 1, 0, 0, 1, 0, "", "default", null)',
                ("zero-expiry-bearer", "Default API token"),
            )
            connection.commit()
        finally:
            connection.close()

        status, payload = self.bridge.handle_ensure_launcher_token(
            {},
            "Bearer sk-zero-expiry-bearer",
        )

        self.assertEqual(status, 401)
        self.assertFalse(payload["success"])

    def test_launcher_payload_carries_account_group_and_session_cookie_for_one_request_login(self):
        self.bridge.fetch_models = lambda _token: ["qwen3.7-plus", "glm-5.2-coding", "agnes-2.0-flash"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="pro",
            session_cookie="session=fake-session-not-real",
        )

        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertEqual(data["userId"], "42")
        self.assertEqual(data["account"], "user@example.com")
        self.assertEqual(data["group"], "pro")
        self.assertEqual(data["sessionCookie"], "session=fake-session-not-real")
        self.assertEqual(data["models"], ["qwen3.7-plus", "glm-5.2-coding", "agnes-2.0-flash"])
        self.assertEqual(data["defaults"]["textModel"], "glm-5.2-coding")

    def test_launcher_payload_uses_configured_public_api_base(self):
        self.bridge.PUBLIC_API_BASE = "https://relay.example.com/openai/v1"
        self.bridge.fetch_models = lambda _token: ["qwen3.7-plus"]

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["api"]["baseUrl"], "https://relay.example.com/openai/v1")

    def test_auth_capabilities_report_missing_smtp_without_exposing_options(self):
        capabilities = self.bridge.auth_capabilities_payload()

        self.assertTrue(capabilities["passwordLogin"])
        self.assertFalse(capabilities["inlineEmailCode"])
        self.assertFalse(capabilities["inlineRegistration"])
        self.assertFalse(capabilities["webRegistrationRequired"])
        self.assertFalse(capabilities["emailConfigured"])
        self.assertIn("SMTP", capabilities["emailReason"])
        self.assertNotIn("SMTPToken", repr(capabilities))

    def test_auth_capabilities_separate_email_login_from_web_registration(self):
        connection = sqlite3.connect(self.bridge.DB_PATH)
        try:
            connection.executemany(
                "insert into options(key, value) values(?, ?)",
                [
                    ("SMTPServer", "smtp.example.invalid"),
                    ("SMTPAccount", "mailer@example.invalid"),
                    ("SMTPToken", "not-a-real-secret"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        capabilities = self.bridge.auth_capabilities_payload()

        self.assertTrue(capabilities["inlineEmailCode"])
        self.assertFalse(capabilities["inlineRegistration"])
        self.assertTrue(capabilities["webRegistrationRequired"])

    def test_launcher_payload_fails_closed_when_model_catalog_is_empty(self):
        self.bridge.fetch_models = lambda _token: []

        status, payload = self.bridge.build_launcher_payload(
            user_id="42",
            account="user@example.com",
            group="default",
        )

        self.assertEqual(status, 503)
        self.assertFalse(payload["success"])
        self.assertNotIn("sk-test-secret-value", repr(payload))

    def test_launcher_login_rejection_returns_401_without_token_lookup(self):
        status, payload = self.bridge.handle_launcher_token({
            "username": "user@example.com",
            "password": "wrong-password",
        })

        self.assertEqual(status, 401)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "invalid username or password")

    def test_launcher_authenticates_against_local_database_without_web_turnstile(self):
        self.bridge.request_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher password authentication must not call the Turnstile-protected web login")
        )
        self.bridge.fetch_models = lambda _token: ["glm-5.2-coding"]

        status, payload = self.bridge.handle_launcher_token({
            "username": "user@example.com",
            "password": "password-not-real",
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["userId"], "42")
        self.assertNotIn("password", repr(payload).lower())

    def test_launcher_releases_failure_budget_when_auth_database_is_unavailable(self):
        self.bridge.authenticate_user = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        )

        status, payload = self.bridge.handle_launcher_token({
            "username": "user@example.com",
            "password": "password-not-real",
        })

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "authentication service is temporarily unavailable")
        self.assertFalse(self.bridge.auth_failure_limited("user@example.com", "password"))

    def test_launcher_login_rate_limits_repeated_failures_per_account(self):
        self.bridge.AUTH_FAILURE_RATE_LIMIT = 3
        body = {"username": "user@example.com", "password": "wrong-password"}

        statuses = [self.bridge.handle_launcher_token(body)[0] for _ in range(4)]

        self.assertEqual(statuses, [401, 401, 401, 429])

    def test_successful_launcher_login_clears_previous_failure_budget(self):
        self.bridge.AUTH_FAILURE_RATE_LIMIT = 3
        self.bridge.fetch_models = lambda _token: ["qwen3.7-plus"]
        wrong_body = {"username": "user@example.com", "password": "wrong-password"}
        correct_body = {"username": "user@example.com", "password": "password-not-real"}

        self.assertEqual(self.bridge.handle_launcher_token(wrong_body)[0], 401)
        self.assertEqual(self.bridge.handle_launcher_token(wrong_body)[0], 401)
        self.assertEqual(self.bridge.handle_launcher_token(correct_body)[0], 200)
        self.assertFalse(self.bridge.auth_failure_limited("user@example.com", "password"))

    def test_auth_attempt_budget_is_atomic_under_concurrency(self):
        self.bridge.AUTH_FAILURE_RATE_LIMIT = 3
        results = []
        lock = threading.Lock()

        def reserve():
            allowed = self.bridge.reserve_auth_attempt("user@example.com", "password")
            with lock:
                results.append(allowed)

        threads = [threading.Thread(target=reserve) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 20)
        self.assertEqual(sum(1 for allowed in results if allowed), 3)

    def test_claim_returns_key_once(self):
        self.bridge.handle_launcher_token = self.stub_launcher_token
        _, start_payload = self.bridge.handle_bind_start({"username": "user@example.com", "password": "pw"})
        ticket = start_payload["data"]["ticket"]

        status, payload = self.bridge.handle_bind_claim({"ticket": ticket})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["key"], "sk-test-secret-value")

        status, payload = self.bridge.handle_bind_claim({"ticket": ticket})
        self.assertEqual(status, 404)
        self.assertIn("not found", payload["error"])

    def test_claim_returns_inactive_entitlement_until_authorization_code_is_bound(self):
        self.bridge.handle_launcher_token = self.stub_launcher_token
        _, start_payload = self.bridge.handle_bind_start({"username": "user@example.com", "password": "pw"})
        ticket = start_payload["data"]["ticket"]

        status, payload = self.bridge.handle_bind_claim({
            "ticket": ticket,
            "installId": "install-claim",
            "deviceId": "host-claim",
        })

        self.assertEqual(status, 200)
        self.assertNotIn("entitlementLease", payload["data"])
        self.assertEqual(
            payload["data"]["entitlement"]["source"],
            "authorization_required",
        )
        self.assertEqual(payload["data"]["entitlement"]["limits"]["devices"], 0)

    def test_concurrent_claim_only_returns_key_once(self):
        self.bridge.handle_launcher_token = self.stub_launcher_token
        _, start_payload = self.bridge.handle_bind_start({"username": "user@example.com", "password": "pw"})
        ticket = start_payload["data"]["ticket"]
        results = []
        lock = threading.Lock()

        def claim():
            result = self.bridge.handle_bind_claim({"ticket": ticket})
            with lock:
                results.append(result)

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successes = [payload for status, payload in results if status == 200 and payload.get("data", {}).get("key")]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(results), 8)

    def test_expired_ticket_is_rejected(self):
        ticket = self.bridge.create_bind_ticket(
            {"success": True, "data": {"key": "sk-expired", "account": "expired@example.com"}},
            ttl_sec=-1,
        )["ticket"]

        status, payload = self.bridge.handle_bind_claim({"ticket": ticket})

        self.assertEqual(status, 410)
        self.assertIn("expired", payload["error"])

    def test_email_code_login_returns_launcher_payload_without_exposing_code(self):
        sent = {}

        def capture_code(email, code):
            sent["email"] = email
            sent["code"] = code

        self.bridge._send_login_email_code = capture_code
        self.bridge.fetch_models = lambda _token: ["qwen3.7-plus", "agnes-2.0-flash"]

        status, payload = self.bridge.handle_email_code_send({"email": "user@example.com", "purpose": "login"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["email"], "user@example.com")
        self.assertNotIn(sent["code"], repr(payload))

        status, payload = self.bridge.handle_email_code_login({"email": "user@example.com", "code": sent["code"]})
        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertEqual(data["account"], "user@example.com")
        self.assertEqual(data["api"]["baseUrl"], "https://api.heang.top/v1")
        self.assertEqual(data["models"], ["qwen3.7-plus", "agnes-2.0-flash"])

        status, payload = self.bridge.handle_email_code_login({"email": "user@example.com", "code": sent["code"]})
        self.assertEqual(status, 400)
        self.assertIn("重新发送", payload["error"])

    def test_email_code_register_returns_managed_session_in_one_request(self):
        upstream_paths = []

        def register_user(opener, path, *, method="GET", body=None, headers=None, timeout=20):
            upstream_paths.append(path)
            self.assertEqual(method, "POST")
            if path == "/api/user/register":
                connection = sqlite3.connect(self.bridge.DB_PATH)
                try:
                    connection.execute(
                        'insert into users(id, username, status, email, "group", deleted_at) values(99, ?, 1, ?, ?, null)',
                        (body["email"], body["email"], "standard"),
                    )
                    connection.commit()
                finally:
                    connection.close()
                return {"success": True, "message": "registered"}
            if path == "/api/user/login":
                processor = next(
                    handler
                    for handler in opener.handlers
                    if isinstance(handler, self.bridge.urllib.request.HTTPCookieProcessor)
                )
                processor.cookiejar.set_cookie(self.bridge.http.cookiejar.Cookie(
                    version=0,
                    name="session",
                    value="fake-register-session-not-real",
                    port=None,
                    port_specified=False,
                    domain="127.0.0.1",
                    domain_specified=False,
                    domain_initial_dot=False,
                    path="/",
                    path_specified=True,
                    secure=False,
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                ))
                return {
                    "success": True,
                    "data": {"id": "99", "username": body["username"], "group": "standard"},
                }
            raise AssertionError(f"unexpected upstream path: {path}")

        self.bridge.request_json = register_user
        self.bridge.fetch_models = lambda _token: ["qwen3.7-plus", "agnes-2.0-flash"]

        status, payload = self.bridge.handle_email_code_register({
            "email": "new@example.com",
            "username": "new@example.com",
            "password": "secret123",
            "code": "246810",
            "verification_code": "246810",
        })

        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertEqual(data["account"]["id"], "99")
        self.assertEqual(data["account"]["email"], "new@example.com")
        self.assertEqual(data["account"]["plan"], "standard")
        self.assertEqual(data["api"]["baseUrl"], "https://api.heang.top/v1")
        self.assertEqual(data["models"], ["qwen3.7-plus", "agnes-2.0-flash"])
        self.assertEqual(data["sessionCookie"], "session=fake-register-session-not-real")
        self.assertEqual(upstream_paths, ["/api/user/register", "/api/user/login"])


if __name__ == "__main__":
    unittest.main()
