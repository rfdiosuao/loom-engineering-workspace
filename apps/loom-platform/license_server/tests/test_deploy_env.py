from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT  # noqa: F401

from luming_license.deploy_env import upsert_env_value


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

