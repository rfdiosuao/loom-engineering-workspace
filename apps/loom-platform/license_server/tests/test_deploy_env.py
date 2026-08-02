from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT  # noqa: F401

from luming_license.deploy_env import upsert_env_value, validate_zpay_env_file


class DeployEnvironmentTests(unittest.TestCase):
    def test_upsert_preserves_unrelated_secrets_and_replaces_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "openclaw-license.env"
            env_file.write_text(
                "# production\n"
                "LICENSE_ACCOUNT_REDEEM_SERVICE_TOKEN=keep-entitlement-secret\n"
                "OPENCLAW_PUBLISH_RELAY_TOKEN=old-relay-secret\n"
                "ANOTHER_SETTING=keep-me\n",
                encoding="utf-8",
            )

            upsert_env_value(
                env_file,
                "OPENCLAW_PUBLISH_RELAY_TOKEN",
                "new relay value",
            )

            content = env_file.read_text(encoding="utf-8")
            self.assertIn(
                "LICENSE_ACCOUNT_REDEEM_SERVICE_TOKEN=keep-entitlement-secret",
                content,
            )
            self.assertIn("ANOTHER_SETTING=keep-me", content)
            self.assertNotIn("old-relay-secret", content)
            self.assertIn('OPENCLAW_PUBLISH_RELAY_TOKEN="new relay value"', content)
            if os.name != "nt":
                self.assertEqual(0o600, env_file.stat().st_mode & 0o777)

    def test_upsert_rejects_invalid_environment_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                upsert_env_value(Path(temp) / "service.env", "BAD-NAME", "value")

    def test_zpay_validation_accepts_complete_https_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "openclaw-license.env"
            env_file.write_text(
                "LICENSE_ZPAY_ENABLED=1\n"
                "LICENSE_ZPAY_BASE_URL=https://zpayz.cn\n"
                "LICENSE_ZPAY_PID=merchant-id\n"
                'LICENSE_ZPAY_KEY="secret with spaces"\n'
                "LICENSE_ZPAY_CREATE_PATH=/mapi.php\n"
                "LICENSE_ZPAY_QUERY_ENABLED=true\n"
                "LICENSE_ZPAY_QUERY_PATH=/api.php\n"
                "LICENSE_ZPAY_NOTIFY_URL=https://license.example.com/api/payments/zpay/notify\n"
                "LICENSE_ZPAY_RETURN_URL=https://license.example.com/api/payments/zpay/return\n",
                encoding="utf-8",
            )

            validate_zpay_env_file(env_file)

    def test_zpay_validation_rejects_missing_secret_without_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "openclaw-license.env"
            env_file.write_text(
                "LICENSE_ZPAY_ENABLED=1\n"
                "LICENSE_ZPAY_BASE_URL=https://zpayz.cn\n"
                "LICENSE_ZPAY_PID=merchant-id\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "LICENSE_ZPAY_KEY") as caught:
                validate_zpay_env_file(env_file)
            self.assertNotIn("merchant-id", str(caught.exception))

    def test_zpay_validation_rejects_disabled_or_insecure_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "openclaw-license.env"
            common = (
                "LICENSE_ZPAY_PID=merchant-id\n"
                "LICENSE_ZPAY_KEY=secret\n"
                "LICENSE_ZPAY_CREATE_PATH=/mapi.php\n"
                "LICENSE_ZPAY_QUERY_ENABLED=1\n"
                "LICENSE_ZPAY_QUERY_PATH=/api.php\n"
                "LICENSE_ZPAY_NOTIFY_URL=https://license.example.com/api/payments/zpay/notify\n"
                "LICENSE_ZPAY_RETURN_URL=https://license.example.com/api/payments/zpay/return\n"
            )
            env_file.write_text(
                "LICENSE_ZPAY_ENABLED=0\n"
                "LICENSE_ZPAY_BASE_URL=https://zpayz.cn\n" + common,
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "LICENSE_ZPAY_ENABLED"):
                validate_zpay_env_file(env_file)

            env_file.write_text(
                "LICENSE_ZPAY_ENABLED=1\n"
                "LICENSE_ZPAY_BASE_URL=http://zpayz.cn\n" + common,
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "LICENSE_ZPAY_BASE_URL"):
                validate_zpay_env_file(env_file)
