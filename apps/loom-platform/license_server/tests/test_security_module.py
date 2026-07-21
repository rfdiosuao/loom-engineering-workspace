from __future__ import annotations

import unittest
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory

from _support import LICENSE_SERVER_ROOT
from luming_license.errors import ActivationError
from luming_license.security import (
    admin_session_cookie,
    password_hash,
    request_admin_token,
    require_confirmation,
    verify_password,
)
from test_license_flow import load_server


class SecurityModuleTests(unittest.TestCase):
    def test_password_round_trip_and_wrong_password(self) -> None:
        encoded = password_hash("correct-password-123")
        self.assertTrue(verify_password("correct-password-123", encoded))
        self.assertFalse(verify_password("wrong-password-123", encoded))

    def test_pre_refactor_password_fixture_is_still_accepted(self) -> None:
        encoded = "pbkdf2_sha256$210000$bGVnYWN5LXNhbHQtMTIzNA==$3CCUtJV5MQV3HkHUClnbSw1j5H3oeVBH1tKfKgRk7dM="
        self.assertTrue(verify_password("legacy-password-123", encoded))
        self.assertFalse(verify_password("wrong-password-123", encoded))

    def test_cookie_token_is_used_when_headers_are_absent(self) -> None:
        headers = Message()
        headers["Cookie"] = "__Host-luming_admin_session=session-value"
        self.assertEqual("session-value", request_admin_token(headers))

    def test_request_admin_token_uses_compatible_precedence(self) -> None:
        headers = Message()
        headers["Authorization"] = "Bearer bearer-token"
        headers["X-Admin-Session"] = "header-session"
        headers["X-Admin-Token"] = "legacy-token"
        headers["Cookie"] = "__Host-luming_admin_session=cookie-token"
        self.assertEqual("bearer-token", request_admin_token(headers))

        del headers["Authorization"]
        self.assertEqual("header-session", request_admin_token(headers))
        del headers["X-Admin-Session"]
        self.assertEqual("legacy-token", request_admin_token(headers))
        del headers["X-Admin-Token"]
        self.assertEqual("cookie-token", request_admin_token(headers))

    def test_dangerous_confirmation_fails_closed(self) -> None:
        with self.assertRaises(ActivationError):
            require_confirmation({}, "DELETE")

    def test_session_cookie_has_required_attributes(self) -> None:
        cookie = admin_session_cookie("session-value", max_age=60)
        for marker in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=60"):
            self.assertIn(marker, cookie)

    def test_clear_session_cookie_keeps_required_attributes(self) -> None:
        cookie = admin_session_cookie("", max_age=0)
        for marker in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=0"):
            self.assertIn(marker, cookie)

    def test_server_invite_creation_keeps_generator_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            server.generate_invite_code = lambda: "INV-TEST-TEST-TEST-TEST"
            _, invite_code = server.create_invite_record()
        self.assertEqual("INV-TEST-TEST-TEST-TEST", invite_code)

    def test_server_account_creation_keeps_public_row_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            original = server.account_row_public
            calls: list[int] = []

            def tracked(row):
                calls.append(int(row["id"]))
                return original(row)

            server.account_row_public = tracked
            server.create_account_record(username="public-row", password="password-123")
        self.assertEqual(1, len(calls))

    def test_server_registration_keeps_account_creator_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            _, invite_code = server.create_invite_record()
            original = server._create_account_record_on_connection
            calls: list[str] = []

            def tracked(connection, **kwargs):
                calls.append(str(kwargs["username"]))
                return original(connection, **kwargs)

            server._create_account_record_on_connection = tracked
            server.register_account_with_invite(
                invite_code=invite_code,
                username="registered-user",
                password="password-123",
            )
        self.assertEqual(["registered-user"], calls)

    def test_server_session_load_keeps_context_builder_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            account, _ = server.create_account_record(username="session-user", password="password-123")
            token, _ = server.create_admin_session(account["accountId"])
            expected = {"authType": "patched"}
            server.admin_context_from_row = lambda row, *, auth_type, token="": expected
            actual = server.load_admin_context_from_session(token)
        self.assertIs(expected, actual)

    def test_server_rate_limit_storage_key_monkeypatch_is_used_by_nested_consume(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            calls: list[tuple[str, str]] = []

            def storage_key(scope: str, key: str) -> str:
                calls.append((scope, key))
                return f"patched:{scope}:{key}"

            server.rate_limit_storage_key = storage_key
            server.rate_limit_consume("nested", "key", limit=2, window_seconds=60, lockout_seconds=60)
            self.assertIn("patched:nested:key", server.RATE_LIMITS)
        self.assertGreaterEqual(len(calls), 2)

    def test_separately_loaded_servers_keep_rate_limit_state_isolated(self) -> None:
        with TemporaryDirectory() as first_directory, TemporaryDirectory() as second_directory:
            first = load_server(Path(first_directory))
            second = load_server(Path(second_directory))
            first.rate_limit_record_failure("login", "same-key", limit=1, window_seconds=60, lockout_seconds=60)
            with self.assertRaises(ActivationError):
                first.rate_limit_check("login", "same-key")
            second.rate_limit_check("login", "same-key")

    def test_server_account_lookup_keeps_username_normalizer_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            account, _ = server.create_account_record(username="normalized-user", password="password-123")
            calls: list[str] = []

            def normalize(value):
                calls.append(str(value))
                return "normalized-user"

            server.normalize_username = normalize
            actual = server.get_account_by_username("lookup-value")
        self.assertEqual(["lookup-value"], calls)
        self.assertEqual(account["accountId"], actual["id"])

    def test_server_account_creation_keeps_all_normalizers_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            calls: list[str] = []

            def username(value):
                calls.append("username")
                return "normalized-account"

            def role(value):
                calls.append("role")
                return server.ACCOUNT_ROLE_SUPER_ADMIN

            def status(value):
                calls.append("status")
                return server.ACCOUNT_STATUS_DISABLED

            server.normalize_username = username
            server.normalize_account_role = role
            server.normalize_account_status = status
            account, _ = server.create_account_record(
                username="raw-account",
                password="password-123",
                role="raw-role",
                status="raw-status",
            )
        self.assertEqual(["username", "role", "status"], calls)
        self.assertEqual("normalized-account", account["username"])
        self.assertEqual("super_admin", account["role"])
        self.assertEqual("disabled", account["status"])

    def test_server_registration_keeps_invite_and_username_normalizers_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            _, invite_code = server.create_invite_record()
            calls: list[str] = []

            def normalize_invite(value):
                calls.append("invite")
                return invite_code

            def normalize_username(value):
                calls.append("username")
                return "normalized-registration"

            server.normalize_invite_code = normalize_invite
            server.normalize_username = normalize_username
            account, _, _ = server.register_account_with_invite(
                invite_code="raw-invite",
                username="raw-registration",
                password="password-123",
            )
        self.assertEqual(["invite", "username", "username"], calls)
        self.assertEqual("normalized-registration", account["username"])

    def test_server_account_update_keeps_role_and_status_normalizers_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            account, _ = server.create_account_record(username="update-user", password="password-123")
            calls: list[str] = []

            def role(value):
                calls.append("role")
                return server.ACCOUNT_ROLE_SUPER_ADMIN

            def status(value):
                calls.append("status")
                return server.ACCOUNT_STATUS_DISABLED

            server.normalize_account_role = role
            server.normalize_account_status = status
            actual = server.update_account_record(account_id=account["accountId"], role="raw-role", status="raw-status")
        self.assertEqual(["role", "status"], calls)
        self.assertEqual("super_admin", actual["role"])
        self.assertEqual("disabled", actual["status"])

    def test_server_role_rank_keeps_normalizer_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            calls: list[str] = []

            def normalize(value):
                calls.append(str(value))
                return server.ACCOUNT_ROLE_SUPER_ADMIN

            server.normalize_account_role = normalize
            rank = server.role_rank("raw-role")
        self.assertEqual(["raw-role"], calls)
        self.assertEqual(2, rank)

    def test_server_invite_rows_keep_public_row_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            invite, _ = server.create_invite_record()
            original = server.invite_row_public
            calls: list[int] = []

            def tracked(row):
                calls.append(int(row["id"]))
                return original(row)

            server.invite_row_public = tracked
            rows = server.list_invite_rows()
        self.assertEqual([invite["inviteId"]], calls)
        self.assertEqual(invite["inviteId"], rows[0]["inviteId"])

    def test_server_invite_create_and_toggle_keep_public_row_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            original = server.invite_row_public
            calls: list[int] = []

            def tracked(row):
                calls.append(int(row["id"]))
                return original(row)

            server.invite_row_public = tracked
            invite, _ = server.create_invite_record()
            server.toggle_invite_record(invite["inviteId"])
        self.assertEqual([invite["inviteId"], invite["inviteId"]], calls)

    def test_server_invite_lookup_keeps_normalizer_monkeypatch_visible(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            _, invite_code = server.create_invite_record()
            calls: list[str] = []

            def normalize(value):
                calls.append(str(value))
                return invite_code

            server.normalize_invite_code = normalize
            invite = server.get_invite_by_code("raw-invite")
        self.assertEqual(["raw-invite"], calls)
        self.assertEqual(invite_code, invite["invite_code"])

    def test_server_account_list_keeps_accepted_row_call_count_and_order(self) -> None:
        with TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            server.create_account_record(username="first-user", password="password-123")
            server.create_account_record(username="second-user", password="password-123")
            original = server.account_row_public
            calls: list[int] = []

            def tracked(row):
                calls.append(int(row["id"]))
                return original(row)

            server.account_row_public = tracked
            rows = server.list_account_rows()
        expected = [account_id for row in rows for account_id in (row["accountId"], row["accountId"])]
        self.assertEqual(expected, calls)
