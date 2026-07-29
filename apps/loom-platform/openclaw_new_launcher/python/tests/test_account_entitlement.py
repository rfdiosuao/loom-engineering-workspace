from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from core.account_entitlement import AccountEntitlementError, AccountEntitlementManager
from core.license_manager import LicenseManager
from core.paths import AppPaths
from core.storage import read_json, write_json


class AccountEntitlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = AppPaths(self.temp.name)
        self.legacy = LicenseManager(self.paths)
        self.private_key = Ed25519PrivateKey.generate()
        self.anchor_store: dict[str, dict] = {}
        public = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.manager = AccountEntitlementManager(
            self.paths,
            legacy_license_manager=self.legacy,
            public_keys={"test-key": base64.b64encode(public).decode("ascii")},
            anchor_reader=lambda: dict(self.anchor_store.get("value") or {}) or None,
            anchor_writer=lambda payload: self.anchor_store.__setitem__(
                "value",
                json.loads(json.dumps(payload)),
            ),
        )
        write_json(
            self.paths.member_session_file,
            {
                "source": "newapi_account",
                "memberId": "newapi:42",
                "memberToken": "sk-test-session-token",
                "newApi": {"userId": "42", "baseUrl": "https://api.heang.top"},
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _lease(self, **overrides):
        now = int(time.time())
        lease = {
            "schema": "loom.entitlement_lease.v1",
            "accountId": "42",
            "sessionBinding": hashlib.sha256(
                b"loom-entitlement-session-v1\0sk-test-session-token"
            ).hexdigest(),
            "installId": self.legacy.get_install_id(),
            "deviceId": self.legacy.device_id(),
            "hostDeviceId": self.legacy.device_id(),
            "features": ["matrix.devices", "matrix.tasks"],
            "plan": "activated",
            "source": "authorization_code",
            "limits": {
                "devices": 1000,
                "concurrentTasks": 1,
                "unlimitedDevices": True,
            },
            "issuedAt": now,
            "expiresAt": now + 3600,
            "offlineGraceUntil": now + 73 * 3600,
            "entitlementVersion": 1,
            "keyId": "test-key",
        }
        lease.update(overrides)
        signed = dict(lease)
        lease["signature"] = base64.b64encode(
            self.private_key.sign(
                json.dumps(
                    signed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        ).decode("ascii")
        return lease

    def _phone_seat_lease(self, phone_device_ids=None, **overrides):
        now = int(time.time())
        lease = {
            "schema": "loom.phone_seat_lease.v1",
            "accountId": "42",
            "installId": self.legacy.get_install_id(),
            "hostDeviceId": self.legacy.device_id(),
            "phoneDeviceIds": list(phone_device_ids or ["phone-a"]),
            "limit": 1000,
            "issuedAt": now,
            "expiresAt": now + 3600,
            "entitlementVersion": 1,
            "keyId": "test-key",
        }
        lease.update(overrides)
        signed = dict(lease)
        lease["signature"] = base64.b64encode(
            self.private_key.sign(
                json.dumps(
                    signed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        ).decode("ascii")
        return lease

    def test_accepts_signed_lease_bound_to_account_install_and_host(self):
        accepted = self.manager.accept_lease(self._lease())

        self.assertTrue(accepted["authorized"])
        self.assertEqual(accepted["plan"], "activated")
        self.assertEqual(accepted["limits"]["devices"], 1000)
        self.assertTrue(self.manager.is_authorized("matrix.devices"))

    def test_rejects_tampered_or_copied_lease(self):
        lease = self._lease()
        lease["limits"]["devices"] = 99
        with self.assertRaises(AccountEntitlementError) as tampered:
            self.manager.accept_lease(lease)
        self.assertEqual(tampered.exception.code, "lease_signature_invalid")

        copied = self._lease(installId="other-install")
        with self.assertRaises(AccountEntitlementError) as wrong_install:
            self.manager.accept_lease(copied)
        self.assertEqual(wrong_install.exception.code, "install_id_mismatch")

    def test_logged_in_account_cannot_fall_back_after_entitlement_was_seen(self):
        self.manager.accept_lease(self._lease())
        os.remove(self.paths.account_entitlement_file)

        self.assertFalse(self.manager.is_authorized("matrix.devices"))
        state = self.manager.current_state("matrix.devices")
        self.assertEqual(state["code"], "entitlement_required")

    def test_existing_lease_is_rejected_when_monotonic_state_was_deleted(self):
        self.manager.accept_lease(self._lease())
        os.remove(self.paths.account_entitlement_state_file)

        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["code"], "lease_state_missing")
        self.assertEqual(state["action"], "refresh_entitlement")

    def test_restoring_old_local_files_cannot_roll_back_external_anchor(self):
        lease_v1 = self._lease(entitlementVersion=1)
        self.manager.accept_lease(lease_v1)
        old_lease = json.loads(json.dumps(lease_v1))
        old_state = json.loads(
            json.dumps(self.manager._state())
        )
        self.manager.accept_lease(self._lease(entitlementVersion=2))

        write_json(self.paths.account_entitlement_file, old_lease)
        write_json(self.paths.account_entitlement_state_file, old_state)
        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["code"], "entitlement_anchor_mismatch")

    def test_persisted_lease_fails_closed_when_external_anchor_is_deleted(self):
        self.manager.accept_lease(self._lease())
        self.anchor_store.clear()

        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["code"], "entitlement_anchor_missing")

    def test_frozen_wall_clock_cannot_extend_offline_grace_on_the_same_boot(self):
        wall_time = int(time.time())
        clock = {"wall": wall_time, "uptimeMs": 120_000}
        manager = AccountEntitlementManager(
            self.paths,
            legacy_license_manager=self.legacy,
            public_keys=self.manager.public_keys,
            now=lambda: clock["wall"],
            uptime_ms=lambda: clock["uptimeMs"],
            anchor_reader=lambda: dict(self.anchor_store.get("value") or {}) or None,
            anchor_writer=lambda payload: self.anchor_store.__setitem__(
                "value",
                json.loads(json.dumps(payload)),
            ),
        )
        manager.accept_lease(
            self._lease(
                issuedAt=wall_time - 10,
                expiresAt=wall_time + 120,
                offlineGraceUntil=wall_time + 180,
            )
        )

        clock["uptimeMs"] += 240_000
        restarted = AccountEntitlementManager(
            self.paths,
            legacy_license_manager=self.legacy,
            public_keys=self.manager.public_keys,
            now=lambda: clock["wall"],
            uptime_ms=lambda: clock["uptimeMs"],
            anchor_reader=lambda: dict(self.anchor_store.get("value") or {}) or None,
            anchor_writer=lambda payload: self.anchor_store.__setitem__(
                "value",
                json.loads(json.dumps(payload)),
            ),
        )

        state = restarted.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual("lease_expired", state["code"])

    def test_reboot_with_non_advancing_wall_clock_requires_online_refresh(self):
        wall_time = int(time.time())
        clock = {"wall": wall_time, "uptimeMs": 600_000}
        manager = AccountEntitlementManager(
            self.paths,
            legacy_license_manager=self.legacy,
            public_keys=self.manager.public_keys,
            now=lambda: clock["wall"],
            uptime_ms=lambda: clock["uptimeMs"],
            anchor_reader=lambda: dict(self.anchor_store.get("value") or {}) or None,
            anchor_writer=lambda payload: self.anchor_store.__setitem__(
                "value",
                json.loads(json.dumps(payload)),
            ),
        )
        manager.accept_lease(self._lease())

        clock["uptimeMs"] = 10_000
        state = manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual("clock_integrity_online_required", state["code"])

    def test_logged_in_account_cannot_fall_back_to_legacy_before_first_lease(self):
        self.manager.legacy.is_authorized = lambda _feature=None: True

        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["source"], "account_entitlement")
        self.assertEqual(state["code"], "entitlement_required")

    def test_logged_in_unactivated_account_is_directed_to_bind_authorization_code(self):
        session = read_json(self.paths.member_session_file, {})
        session["accountEntitlement"] = {
            "source": "authorization_required",
            "plan": "inactive",
            "features": [],
            "limits": {
                "devices": 0,
                "concurrentTasks": 0,
                "unlimitedDevices": False,
            },
        }
        write_json(self.paths.member_session_file, session)

        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["code"], "authorization_required")
        self.assertEqual(state["action"], "bind_authorization_code")
        self.assertIn("授权码", state["message"])

    def test_legacy_machine_license_cannot_unlock_account_bound_matrix(self):
        os.remove(self.paths.member_session_file)
        self.manager.legacy.is_authorized = lambda _feature=None: True

        state = self.manager.current_state("matrix.devices")

        self.assertFalse(state["authorized"])
        self.assertEqual(state["source"], "legacy_license_migration_required")
        self.assertEqual(state["code"], "account_entitlement_required")
        with self.assertRaises(AccountEntitlementError) as denied:
            self.manager.authorize_phone_devices(
                ["phone-a"],
                "matrix.device.claim",
            )
        self.assertEqual(denied.exception.code, "account_entitlement_required")

    def test_legacy_machine_license_remains_available_outside_matrix_scope(self):
        os.remove(self.paths.member_session_file)
        self.manager.legacy.is_authorized = lambda _feature=None: True

        state = self.manager.current_state("publishing.draft")

        self.assertTrue(state["authorized"])
        self.assertEqual(state["source"], "legacy_license")

    def test_account_entitlement_signature_cannot_be_replayed_as_legacy_license(self):
        lease = self._lease()
        self.legacy.public_key = self.private_key.public_key()
        write_json(self.paths.license_file, lease)

        self.assertFalse(self.legacy.verify(lease))
        status = self.legacy.diagnose(include_gateway_profile=False)
        self.assertFalse(status["ok"])
        self.assertEqual(status["code"], "license_schema_invalid")

    def test_signed_lease_is_bound_to_the_current_account_token(self):
        accepted = self.manager.accept_lease(self._lease())
        self.assertTrue(accepted["authorized"])

        session = {
            "source": "newapi_account",
            "memberId": "newapi:42",
            "memberToken": "sk-other-session-token",
            "newApi": {"userId": "42", "baseUrl": "https://api.heang.top"},
        }
        with self.assertRaises(AccountEntitlementError) as mismatch:
            self.manager.verify_lease(self._lease(), session=session)
        self.assertEqual(mismatch.exception.code, "account_session_mismatch")

    def test_persisted_dpapi_session_token_is_unprotected_before_binding_check(self):
        protected = {
            "__loomSecret": "dpapi",
            "value": "opaque-test-ciphertext",
        }
        write_json(
            self.paths.member_session_file,
            {
                "source": "newapi_account",
                "memberId": "newapi:42",
                "memberToken": protected,
                "newApi": {"userId": "42", "baseUrl": "https://api.heang.top"},
            },
        )
        self.manager._unprotect = lambda value: (
            "sk-test-session-token" if value == protected else str(value or "")
        )

        accepted = self.manager.accept_lease(self._lease())
        state = self.manager.current_state("matrix.devices")

        self.assertTrue(accepted["authorized"])
        self.assertTrue(state["authorized"])

    def test_unreadable_persisted_session_secret_fails_closed(self):
        self.manager._unprotect = lambda _value: (_ for _ in ()).throw(
            RuntimeError("dpapi unavailable")
        )

        with self.assertRaises(AccountEntitlementError) as unreadable:
            self.manager.verify_lease(self._lease())

        self.assertEqual(
            unreadable.exception.code,
            "account_session_binding_unreadable",
        )

    def test_offline_phone_requires_signed_seat_lease_not_tamperable_local_state(self):
        self.manager.accept_lease(self._lease())
        with self.assertRaises(AccountEntitlementError) as new_phone:
            self.manager.authorize_phone_devices(["phone-a"], "matrix.device.claim")
        self.assertEqual(new_phone.exception.code, "entitlement_online_claim_required")

        write_json(
            self.paths.account_entitlement_state_file,
            {
                **self.manager._state(),
                "accountLeaseSeen": True,
                "claimedPhoneDeviceIds": ["phone-a"],
            },
        )
        with self.assertRaises(AccountEntitlementError) as tampered_state:
            self.manager.authorize_phone_devices(["phone-a"], "matrix.task.start")
        self.assertEqual(
            tampered_state.exception.code,
            "entitlement_online_claim_required",
        )

        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(["phone-a"]),
        )
        result = self.manager.authorize_phone_devices(["phone-a"], "matrix.task.start")
        self.assertTrue(result["authorized"])
        self.assertTrue(result["offline"])

    def test_activated_account_can_claim_multiple_phones(self):
        self.manager.accept_lease(self._lease())
        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(["phone-a"]),
        )
        self.manager._server_check = lambda **_kwargs: {
            "phoneSeatLease": self._phone_seat_lease(["phone-a", "phone-b"]),
        }

        result = self.manager.authorize_phone_devices(
            ["phone-a", "phone-b"],
            "matrix.task.start",
            session={"memberToken": "secret"},
        )

        self.assertTrue(result["authorized"])
        self.assertEqual(
            result["claimedPhoneDeviceIds"],
            ["phone-a", "phone-b"],
        )

    def test_pending_phone_release_is_persisted_and_retried_before_next_online_action(self):
        self.manager.accept_lease(self._lease())
        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(["phone-a", "phone-b"]),
        )
        self.manager.queue_phone_device_release(
            ["phone-a"],
            reason="delete_failed_offline",
        )
        calls: list[tuple[list[str], str]] = []

        def server_check(**kwargs):
            device_ids = list(kwargs["phone_device_ids"])
            operation = str(kwargs["operation"])
            calls.append((device_ids, operation))
            return {
                "phoneSeatLease": self._phone_seat_lease(["phone-b"]),
            }

        self.manager._server_check = server_check
        result = self.manager.authorize_phone_devices(
            ["phone-b"],
            "matrix.task.start",
            session={
                "memberToken": "secret",
                "newApi": {"baseUrl": "https://api.heang.top"},
            },
        )

        self.assertTrue(result["authorized"])
        self.assertEqual(
            calls,
            [
                (["phone-a"], "matrix.device.release"),
                (["phone-b"], "matrix.task.start"),
            ],
        )
        self.assertEqual(self.manager.pending_phone_device_releases(), [])

    def test_failed_pending_release_remains_queued_without_blocking_valid_offline_phone(self):
        self.manager.accept_lease(self._lease())
        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(["phone-a", "phone-b"]),
        )
        self.manager.queue_phone_device_release(["phone-a"], reason="delete")

        def unavailable(**_kwargs):
            raise AccountEntitlementError(
                "offline",
                code="entitlement_service_unreachable",
                action="retry",
                status_code=503,
            )

        self.manager._server_check = unavailable
        result = self.manager.authorize_phone_devices(
            ["phone-b"],
            "matrix.task.start",
            session={
                "memberToken": "secret",
                "newApi": {"baseUrl": "https://api.heang.top"},
            },
        )

        self.assertTrue(result["authorized"])
        self.assertTrue(result["offline"])
        self.assertEqual(
            self.manager.pending_phone_device_releases(),
            ["phone-a"],
        )

    def test_account_task_slot_limits_parallel_direct_and_matrix_operations(self):
        entitlement = {
            "accountId": "42",
            "limits": {"concurrentTasks": 1},
        }
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first():
            with self.manager.account_task_slot(entitlement, "matrix.task.execute"):
                first_entered.set()
                release_first.wait(timeout=2)

        def second():
            first_entered.wait(timeout=2)
            with self.manager.account_task_slot(entitlement, "phone.task"):
                second_entered.set()

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        self.assertTrue(first_entered.wait(timeout=1))
        self.assertFalse(second_entered.wait(timeout=0.15))
        release_first.set()
        self.assertTrue(second_entered.wait(timeout=1))
        first_thread.join(timeout=1)
        second_thread.join(timeout=1)

    def test_tampered_or_wrong_host_phone_seat_lease_is_not_trusted_offline(self):
        self.manager.accept_lease(self._lease())

        tampered = self._phone_seat_lease(["phone-a"])
        tampered["phoneDeviceIds"] = ["phone-b"]
        write_json(self.paths.account_phone_seat_lease_file, tampered)
        with self.assertRaises(AccountEntitlementError) as tampered_result:
            self.manager.authorize_phone_devices(["phone-b"], "matrix.task.start")
        self.assertEqual(
            tampered_result.exception.code,
            "entitlement_online_claim_required",
        )

        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(["phone-a"], hostDeviceId="copied-host"),
        )
        with self.assertRaises(AccountEntitlementError) as copied_result:
            self.manager.authorize_phone_devices(["phone-a"], "matrix.task.start")
        self.assertEqual(
            copied_result.exception.code,
            "entitlement_online_claim_required",
        )

    def test_phone_seat_lease_must_match_current_entitlement_version_and_limit(self):
        self.manager.accept_lease(
            self._lease(
                entitlementVersion=4,
                limits={"devices": 2, "concurrentTasks": 1},
            )
        )

        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(
                ["phone-a"],
                entitlementVersion=3,
                limit=2,
            ),
        )
        with self.assertRaises(AccountEntitlementError) as stale:
            self.manager.authorize_phone_devices(["phone-a"], "matrix.task.start")
        self.assertEqual(stale.exception.code, "entitlement_online_claim_required")

        write_json(
            self.paths.account_phone_seat_lease_file,
            self._phone_seat_lease(
                ["phone-a", "phone-b", "phone-c"],
                entitlementVersion=4,
                limit=3,
            ),
        )
        with self.assertRaises(AccountEntitlementError) as inflated:
            self.manager.authorize_phone_devices(["phone-a"], "matrix.task.start")
        self.assertEqual(inflated.exception.code, "entitlement_online_claim_required")

    def test_unactivated_account_cannot_enumerate_claimed_phones(self):
        with self.assertRaises(AccountEntitlementError) as denied:
            self.manager.claimed_phone_device_ids()

        self.assertIn(
            denied.exception.code,
            {"entitlement_required", "authorization_required"},
        )

    def test_signed_lease_rejects_boolean_or_string_numeric_fields(self):
        for field, value in (
            ("issuedAt", True),
            ("expiresAt", "1900000000"),
            ("offlineGraceUntil", False),
            ("entitlementVersion", "1"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(AccountEntitlementError) as malformed:
                    self.manager.verify_lease(self._lease(**{field: value}))
                self.assertEqual(malformed.exception.code, "lease_malformed")

        with self.assertRaises(AccountEntitlementError) as string_limit:
            self.manager.verify_lease(
                self._lease(limits={"devices": "1", "concurrentTasks": 1})
            )
        self.assertEqual(string_limit.exception.code, "lease_malformed")

        with self.assertRaises(AccountEntitlementError) as boolean_limit:
            self.manager.verify_lease(
                self._lease(limits={"devices": 1, "concurrentTasks": True})
            )
        self.assertEqual(boolean_limit.exception.code, "lease_malformed")

    def test_phone_seat_lease_rejects_boolean_or_string_numeric_fields(self):
        entitlement = self._lease()
        self.manager.accept_lease(entitlement)

        for field, value in (
            ("issuedAt", True),
            ("expiresAt", "1900000000"),
            ("entitlementVersion", False),
            ("limit", "1"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(AccountEntitlementError) as malformed:
                    self.manager.verify_phone_seat_lease(
                        self._phone_seat_lease(**{field: value}),
                        entitlement_lease=entitlement,
                    )
                self.assertEqual(
                    malformed.exception.code,
                    "phone_seat_lease_malformed",
                )


if __name__ == "__main__":
    unittest.main()
