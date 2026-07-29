from __future__ import annotations

import json
import secrets
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from _support import LICENSE_SERVER_ROOT  # noqa: F401
from test_license_flow import load_server


REDEEM_SERVICE_PATH = "/api/service/account-entitlements/redeem"
CURRENT_SERVICE_PATH = "/api/service/account-entitlements/current"
MIGRATE_SERVICE_PATH = "/api/service/account-entitlements/migrate-legacy"
SERVICE_TOKEN = "test-account-redeem-service-token"


class AccountEntitlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))
        self._http_base_url = ""

    def tearDown(self) -> None:
        self.doCleanups()
        self.temp.cleanup()

    def create_code(
        self,
        *,
        max_activations: int = 4,
        quotas: dict[str, object] | None = None,
    ) -> str:
        return self.server.create_code_records(
            count=1,
            licensee="Matrix Customer",
            edition="pro",
            features=["openclaw", "matrix.devices", "publishing.draft"],
            expires=(date.today() + timedelta(days=30)).isoformat(),
            max_activations=max_activations,
            member_mode=True,
            plan="matrix_pro",
            gateway_base_url="https://gateway.example/v1",
            gateway_token="gateway-secret-token",
            gateway_image_token="gateway-image-secret",
            gateway_video_token="gateway-video-secret",
            quotas=quotas or {"concurrentTasks": 3, "image": 100},
        )[0]

    def service_headers(self, token: str = SERVICE_TOKEN) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_redeem_is_idempotent_for_same_account_and_persists_safe_snapshot(self) -> None:
        code = self.create_code()
        request = {"code": code.lower(), "accountId": "account-1001"}

        first = self.server.redeem_account_entitlement(
            request, request_ip="127.0.0.1"
        )
        second = self.server.redeem_account_entitlement(
            request, request_ip="127.0.0.1"
        )

        expected = {
            "source": "authorization_code",
            "plan": "matrix_pro",
            "features": [
                "openclaw",
                "matrix.devices",
                "publishing.draft",
            ],
            "limits": {
                "devices": 1000,
                "concurrentTasks": 3,
                "unlimitedDevices": True,
            },
            "expiresAt": (date.today() + timedelta(days=30)).isoformat(),
            "codeLabel": code[-9:],
        }
        self.assertEqual(expected, first)
        self.assertEqual(first, second)
        self.assertNotIn(code, json.dumps(first, ensure_ascii=False))
        self.assertNotIn("gateway", json.dumps(first, ensure_ascii=False).lower())

        with self.server.connect() as connection:
            redemption_rows = connection.execute(
                "select * from account_entitlement_redemptions"
            ).fetchall()
            audit_rows = connection.execute(
                """
                select actor, action, target_type, target_id, before_json, after_json
                from audit_logs where action = 'account_entitlement.redeem'
                """
            ).fetchall()
        self.assertEqual(1, len(redemption_rows))
        self.assertEqual("account-1001", redemption_rows[0]["account_id"])
        self.assertEqual(self.server.code_hash(code), redemption_rows[0]["code_hash"])
        self.assertEqual(1, len(audit_rows))
        persisted = json.dumps(
            [dict(redemption_rows[0]), dict(audit_rows[0])],
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(code, persisted)
        self.assertNotIn("gateway-secret-token", persisted)
        self.assertNotIn("gateway-image-secret", persisted)
        self.assertNotIn("gateway-video-secret", persisted)

    def test_same_account_redeem_refreshes_current_code_entitlement(self) -> None:
        code = self.create_code(max_activations=6, quotas={"concurrentTasks": 5})
        request = {"code": code, "accountId": "account-refresh-on-redeem"}
        self.server.redeem_account_entitlement(request)
        downgraded_expiry = (date.today() + timedelta(days=7)).isoformat()
        with self.server.connect() as connection:
            connection.execute(
                """
                update codes
                set plan = ?, features_json = ?, max_activations = ?,
                    quotas_json = ?, expires = ?
                where code_hash = ?
                """,
                (
                    "matrix_basic",
                    json.dumps(["matrix.devices", "matrix.tasks"]),
                    2,
                    json.dumps({"concurrentTasks": 1}),
                    downgraded_expiry,
                    self.server.code_hash(code),
                ),
            )
            connection.commit()

        refreshed = self.server.redeem_account_entitlement(request)

        self.assertEqual("matrix_basic", refreshed["plan"])
        self.assertEqual(["matrix.devices", "matrix.tasks"], refreshed["features"])
        self.assertEqual(
            {
                "devices": 1000,
                "concurrentTasks": 1,
                "unlimitedDevices": True,
            },
            refreshed["limits"],
        )
        self.assertEqual(downgraded_expiry, refreshed["expiresAt"])
        with self.server.connect() as connection:
            snapshot = connection.execute(
                """
                select plan, devices, concurrent_tasks, expires_at
                from account_entitlement_redemptions
                where code_hash = ?
                """,
                (self.server.code_hash(code),),
            ).fetchone()
        self.assertEqual(
            ("matrix_basic", 1000, 1, downgraded_expiry),
            tuple(snapshot),
        )

    def test_redeem_rejects_cross_account_reuse_with_stable_error(self) -> None:
        code = self.create_code()
        self.server.redeem_account_entitlement(
            {"code": code, "accountId": "account-owner"}
        )

        with self.assertRaises(self.server.ActivationError) as raised:
            self.server.redeem_account_entitlement(
                {"code": code, "accountId": "account-other"}
            )

        self.assertEqual(409, raised.exception.status)
        self.assertEqual("ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED", raised.exception.code)
        with self.server.connect() as connection:
            rows = connection.execute(
                "select account_id from account_entitlement_redemptions"
            ).fetchall()
        self.assertEqual(["account-owner"], [row["account_id"] for row in rows])

    def test_signed_legacy_activation_can_migrate_without_plain_authorization_code(self) -> None:
        code = self.create_code()
        legacy_license = self.server.activate_code(
            {
                "code": code,
                "installId": "legacy-install",
                "deviceId": "legacy-device",
            }
        )

        migrated = self.server.migrate_legacy_account_entitlement(
            {
                "legacyLicense": legacy_license,
                "accountId": "account-legacy-owner",
            },
            request_ip="127.0.0.1",
        )

        self.assertEqual("matrix_pro", migrated["plan"])
        self.assertTrue(migrated["limits"]["unlimitedDevices"])
        self.assertNotIn(code, json.dumps(migrated, ensure_ascii=False))
        with self.server.connect() as connection:
            redemption = connection.execute(
                """
                select code_hash, account_id from account_entitlement_redemptions
                where account_id = ?
                """,
                ("account-legacy-owner",),
            ).fetchone()
            audit_row = connection.execute(
                """
                select action, after_json from audit_logs
                where action = 'account_entitlement.migrate_legacy'
                """
            ).fetchone()
        self.assertEqual(self.server.code_hash(code), redemption["code_hash"])
        self.assertEqual("account-legacy-owner", redemption["account_id"])
        self.assertIsNotNone(audit_row)
        self.assertNotIn(
            legacy_license["signature"],
            str(audit_row["after_json"]),
        )

    def test_legacy_migration_rejects_tampering_unmatched_proof_and_cross_account_reuse(self) -> None:
        code = self.create_code()
        legacy_license = self.server.activate_code(
            {
                "code": code,
                "installId": "legacy-install",
                "deviceId": "legacy-device",
            }
        )
        tampered = {**legacy_license, "deviceId": "tampered-device"}
        with self.assertRaises(self.server.ActivationError) as invalid_signature:
            self.server.migrate_legacy_account_entitlement(
                {
                    "legacyLicense": tampered,
                    "accountId": "account-attacker",
                }
            )
        self.assertEqual(
            "LEGACY_LICENSE_PROOF_INVALID",
            invalid_signature.exception.code,
        )

        unmatched_payload = dict(legacy_license)
        unmatched_payload.pop("signature")
        unmatched_payload["licenseId"] = "signed-but-not-activated"
        unmatched = self.server.sign_license(unmatched_payload)
        with self.assertRaises(self.server.ActivationError) as not_found:
            self.server.migrate_legacy_account_entitlement(
                {
                    "legacyLicense": unmatched,
                    "accountId": "account-attacker",
                }
            )
        self.assertEqual(
            "LEGACY_LICENSE_PROOF_NOT_FOUND",
            not_found.exception.code,
        )

        self.server.migrate_legacy_account_entitlement(
            {
                "legacyLicense": legacy_license,
                "accountId": "account-owner",
            }
        )
        with self.assertRaises(self.server.ActivationError) as conflict:
            self.server.migrate_legacy_account_entitlement(
                {
                    "legacyLicense": legacy_license,
                    "accountId": "account-other",
                }
            )
        self.assertEqual(
            "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED",
            conflict.exception.code,
        )

    def test_concurrent_cross_account_redeem_has_exactly_one_winner(self) -> None:
        code = self.create_code()
        contender_count = 12
        start = threading.Barrier(contender_count)

        def redeem(index: int) -> tuple[str, str]:
            start.wait(timeout=10)
            try:
                result = self.server.redeem_account_entitlement(
                    {"code": code, "accountId": f"account-{index}"}
                )
                return "ok", str(result["plan"])
            except self.server.ActivationError as error:
                return "error", error.code

        with ThreadPoolExecutor(max_workers=contender_count) as executor:
            results = list(executor.map(redeem, range(contender_count)))

        self.assertEqual(1, sum(status == "ok" for status, _ in results))
        self.assertEqual(
            contender_count - 1,
            sum(
                status == "error"
                and value == "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED"
                for status, value in results
            ),
        )
        with self.server.connect() as connection:
            redemption_count = connection.execute(
                "select count(*) from account_entitlement_redemptions"
            ).fetchone()[0]
            audit_count = connection.execute(
                """
                select count(*) from audit_logs
                where action = 'account_entitlement.redeem'
                """
            ).fetchone()[0]
        self.assertEqual(1, redemption_count)
        self.assertEqual(1, audit_count)

    def test_redeem_rejects_disabled_and_expired_codes(self) -> None:
        disabled_code = self.create_code()
        expired_code = self.create_code()
        with self.server.connect() as connection:
            connection.execute(
                "update codes set disabled = 1 where code_hash = ?",
                (self.server.code_hash(disabled_code),),
            )
            connection.execute(
                "update codes set expires = ? where code_hash = ?",
                (
                    (date.today() - timedelta(days=1)).isoformat(),
                    self.server.code_hash(expired_code),
                ),
            )
            connection.commit()

        for code, expected_code in (
            (disabled_code, "LICENSE_DISABLED"),
            (expired_code, "LICENSE_EXPIRED"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(self.server.ActivationError) as raised:
                    self.server.redeem_account_entitlement(
                        {"code": code, "accountId": "account-status-check"}
                    )
                self.assertEqual(403, raised.exception.status)
                self.assertEqual(expected_code, raised.exception.code)

        with self.server.connect() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "select count(*) from account_entitlement_redemptions"
                ).fetchone()[0],
            )

    def test_current_returns_safe_binding_and_reports_missing_account(self) -> None:
        code = self.create_code()
        redeemed = self.server.redeem_account_entitlement(
            {"code": code, "accountId": "account-current"}
        )

        current = self.server.current_account_entitlement("account-current")

        self.assertEqual(redeemed, current)
        self.assertNotIn(code, json.dumps(current, ensure_ascii=False))
        self.assertNotIn("gateway", json.dumps(current, ensure_ascii=False).lower())
        with self.assertRaises(self.server.ActivationError) as missing:
            self.server.current_account_entitlement("account-free")
        self.assertEqual(404, missing.exception.status)
        self.assertEqual("ACCOUNT_ENTITLEMENT_NOT_FOUND", missing.exception.code)

    def test_current_detects_entitlement_revocation_and_expiry(self) -> None:
        disabled_code = self.create_code()
        expired_code = self.create_code()
        self.server.redeem_account_entitlement(
            {"code": disabled_code, "accountId": "account-disabled"}
        )
        self.server.redeem_account_entitlement(
            {"code": expired_code, "accountId": "account-expired"}
        )
        with self.server.connect() as connection:
            connection.execute(
                "update codes set disabled = 1 where code_hash = ?",
                (self.server.code_hash(disabled_code),),
            )
            connection.execute(
                "update codes set expires = ? where code_hash = ?",
                (
                    (date.today() - timedelta(days=1)).isoformat(),
                    self.server.code_hash(expired_code),
                ),
            )
            connection.commit()

        for account_id, expected_code in (
            ("account-disabled", "LICENSE_DISABLED"),
            ("account-expired", "LICENSE_EXPIRED"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(self.server.ActivationError) as raised:
                    self.server.current_account_entitlement(account_id)
                self.assertEqual(403, raised.exception.status)
                self.assertEqual(expected_code, raised.exception.code)

    def test_current_falls_back_to_an_older_valid_authorization(self) -> None:
        valid_code = self.create_code(quotas={"concurrentTasks": 7})
        disabled_code = self.create_code(quotas={"concurrentTasks": 2})
        account_id = "account-multiple-authorizations"
        expected = self.server.redeem_account_entitlement(
            {"code": valid_code, "accountId": account_id}
        )
        self.server.redeem_account_entitlement(
            {"code": disabled_code, "accountId": account_id}
        )
        with self.server.connect() as connection:
            connection.execute(
                "update codes set disabled = 1 where code_hash = ?",
                (self.server.code_hash(disabled_code),),
            )
            connection.commit()

        current = self.server.current_account_entitlement(account_id)

        self.assertEqual(expected, current)
        self.assertEqual(7, current["limits"]["concurrentTasks"])

    def test_current_refreshes_safe_metadata_from_the_bound_code(self) -> None:
        code = self.create_code()
        self.server.redeem_account_entitlement(
            {"code": code, "accountId": "account-refresh"}
        )
        refreshed_expires = (date.today() + timedelta(days=90)).isoformat()
        with self.server.connect() as connection:
            connection.execute(
                """
                update codes
                set plan = ?, features_json = ?, max_activations = ?,
                    quotas_json = ?, expires = ?, gateway_token = ?
                where code_hash = ?
                """,
                (
                    "matrix_enterprise",
                    json.dumps(["openclaw", "matrix.devices", "matrix.enterprise"]),
                    8,
                    json.dumps({"concurrentTasks": 12}),
                    refreshed_expires,
                    "rotated-gateway-secret",
                    self.server.code_hash(code),
                ),
            )
            connection.commit()

        current = self.server.current_account_entitlement("account-refresh")

        self.assertEqual(
            {
                "source": "authorization_code",
                "plan": "matrix_enterprise",
                "features": [
                    "openclaw",
                    "matrix.devices",
                    "matrix.enterprise",
                ],
                "limits": {
                    "devices": 1000,
                    "concurrentTasks": 12,
                    "unlimitedDevices": True,
                },
                "expiresAt": refreshed_expires,
                "codeLabel": code[-9:],
            },
            current,
        )
        serialized = json.dumps(current, ensure_ascii=False)
        self.assertNotIn(code, serialized)
        self.assertNotIn("rotated-gateway-secret", serialized)

    def test_service_token_validation_uses_constant_time_comparison(self) -> None:
        self.assertTrue(
            hasattr(self.server, "account_redeem_service_token_valid"),
            "account redeem service auth is not implemented",
        )
        with patch(
            "luming_license.domains.account_entitlements.secrets.compare_digest",
            wraps=secrets.compare_digest,
        ) as compare_digest:
            accepted = self.server.account_redeem_service_token_valid(
                self.service_headers()
            )
            rejected = self.server.account_redeem_service_token_valid(
                self.service_headers("wrong-token")
            )

        self.assertTrue(accepted)
        self.assertFalse(rejected)
        self.assertEqual(
            [
                (SERVICE_TOKEN, SERVICE_TOKEN),
                ("wrong-token", SERVICE_TOKEN),
            ],
            [call.args for call in compare_digest.call_args_list],
        )

    def test_http_route_requires_service_bearer_and_returns_stable_errors(self) -> None:
        code = self.create_code(max_activations=2, quotas={"concurrentTasks": 5})

        missing_auth = self.request_json(
            {"code": code, "accountId": "http-account"},
            token=None,
            expected_status=401,
        )
        wrong_auth = self.request_json(
            {"code": code, "accountId": "http-account"},
            token="wrong-token",
            expected_status=401,
        )
        missing_account = self.request_json(
            {"code": code},
            expected_status=400,
        )
        success = self.request_json(
            {"code": code, "accountId": "http-account"},
        )
        retry = self.request_json(
            {"code": code, "accountId": "http-account"},
        )
        conflict = self.request_json(
            {"code": code, "accountId": "http-other"},
            expected_status=409,
        )
        current = self.request_json(
            {"accountId": "http-account"},
            path=CURRENT_SERVICE_PATH,
        )
        missing_current = self.request_json(
            {"accountId": "http-free"},
            path=CURRENT_SERVICE_PATH,
            expected_status=404,
        )
        unauthorized_current = self.request_json(
            {"accountId": "http-account"},
            path=CURRENT_SERVICE_PATH,
            token=None,
            expected_status=401,
        )

        self.assertEqual("SERVICE_AUTH_REQUIRED", missing_auth["code"])
        self.assertEqual("SERVICE_AUTH_REQUIRED", wrong_auth["code"])
        self.assertEqual("ACCOUNT_REDEEM_INVALID_REQUEST", missing_account["code"])
        self.assertEqual(
            {
                "ok": True,
                "entitlement": {
                    "source": "authorization_code",
                    "plan": "matrix_pro",
                    "features": [
                        "openclaw",
                        "matrix.devices",
                        "publishing.draft",
                    ],
                    "limits": {
                        "devices": 1000,
                        "concurrentTasks": 5,
                        "unlimitedDevices": True,
                    },
                    "expiresAt": (date.today() + timedelta(days=30)).isoformat(),
                    "codeLabel": code[-9:],
                },
            },
            success,
        )
        self.assertEqual(success, retry)
        self.assertEqual(success, current)
        self.assertEqual(
            "ACCOUNT_ENTITLEMENT_ALREADY_REDEEMED", conflict["code"]
        )
        self.assertEqual(
            "ACCOUNT_ENTITLEMENT_NOT_FOUND", missing_current["code"]
        )
        self.assertEqual("SERVICE_AUTH_REQUIRED", unauthorized_current["code"])
        serialized = json.dumps(
            [
                missing_auth,
                wrong_auth,
                missing_account,
                success,
                retry,
                conflict,
                current,
                missing_current,
                unauthorized_current,
            ],
            ensure_ascii=False,
        )
        self.assertNotIn(code, serialized)
        self.assertNotIn("gateway-secret-token", serialized)

    def test_legacy_migration_http_route_requires_service_auth(self) -> None:
        code = self.create_code()
        legacy_license = self.server.activate_code(
            {
                "code": code,
                "installId": "legacy-http-install",
                "deviceId": "legacy-http-device",
            }
        )
        request = {
            "legacyLicense": legacy_license,
            "accountId": "legacy-http-account",
        }

        unauthorized = self.request_json(
            request,
            path=MIGRATE_SERVICE_PATH,
            token=None,
            expected_status=401,
        )
        migrated = self.request_json(
            request,
            path=MIGRATE_SERVICE_PATH,
        )

        self.assertEqual("SERVICE_AUTH_REQUIRED", unauthorized["code"])
        self.assertEqual("matrix_pro", migrated["entitlement"]["plan"])
        self.assertNotIn(legacy_license["signature"], json.dumps(migrated))

    def test_http_route_fails_closed_when_service_token_is_not_configured(self) -> None:
        code = self.create_code()
        self.server.SETTINGS = replace(
            self.server.SETTINGS,
            account_redeem_service_token="",
        )

        response = self.request_json(
            {"code": code, "accountId": "http-account"},
            expected_status=503,
        )

        self.assertEqual("SERVICE_AUTH_NOT_CONFIGURED", response["code"])

    def request_json(
        self,
        payload: dict[str, object],
        *,
        path: str = REDEEM_SERVICE_PATH,
        token: str | None = SERVICE_TOKEN,
        expected_status: int = 200,
    ) -> dict[str, object]:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.start_http_server()}{path}",
            method="POST",
            headers=headers,
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            response = urlopen(request, timeout=5)
            status = response.status
            body = response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
        self.assertEqual(
            expected_status, status, body.decode("utf-8", errors="replace")
        )
        return json.loads(body.decode("utf-8"))

    def start_http_server(self) -> str:
        from http.server import ThreadingHTTPServer

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


if __name__ == "__main__":
    unittest.main()
