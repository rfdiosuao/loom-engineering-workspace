from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_catalog import AgentCatalog
from core.agent_definition import AgentDefinitionError, parse_agent_definition


class AgentCatalogTests(unittest.TestCase):
    def test_bundled_catalog_exposes_four_distinct_agents(self) -> None:
        definitions = AgentCatalog().definitions()

        self.assertEqual(
            [item.component_id for item in definitions],
            ["gemini-cli", "goose", "grok-build", "pi"],
        )
        pi = next(item for item in definitions if item.component_id == "pi")
        self.assertEqual(pi.install_mode, "managed_npm")
        self.assertEqual(
            pi.install_command,
            ("npm", "install", "-g", "--ignore-scripts", "@earendil-works/pi-coding-agent"),
        )
        self.assertFalse(pi.sandbox)
        grok = next(item for item in definitions if item.component_id == "grok-build")
        self.assertTrue(grok.install_locked)
        self.assertEqual(grok.install_command, ())

    def test_duplicate_agent_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = {
                "schemaVersion": 1,
                "id": "pi",
                "name": "Pi",
                "description": "test",
                "officialUrl": "https://pi.dev/docs/latest",
                "sourceUrl": "https://github.com/earendil-works/pi",
                "installMode": "detect_only",
                "providerConfigMode": "unsupported",
                "installCommand": [],
                "uninstallCommand": [],
                "commandNames": ["pi"],
                "compatibility": "test",
                "sandbox": False,
                "priority": "P2",
            }
            for filename in ("a.json", "b.json"):
                with open(os.path.join(temp_dir, filename), "w", encoding="utf-8") as handle:
                    json.dump(source, handle)

            with self.assertRaisesRegex(AgentDefinitionError, "duplicate agent id"):
                AgentCatalog(temp_dir).definitions()

    def test_arbitrary_shell_and_secret_bearing_install_commands_are_rejected(self) -> None:
        base = {
            "schemaVersion": 1,
            "id": "unsafe-agent",
            "name": "Unsafe",
            "description": "test",
            "officialUrl": "https://pi.dev/docs/latest",
            "sourceUrl": "https://github.com/earendil-works/pi",
            "installMode": "managed_npm",
            "providerConfigMode": "unsupported",
            "uninstallCommand": ["npm", "uninstall", "-g", "@earendil-works/pi-coding-agent"],
            "commandNames": ["pi"],
            "compatibility": "test",
            "sandbox": False,
            "priority": "P2",
        }
        for command in (
            ["powershell", "-Command", "irm", "https://x.ai/install.ps1", "|", "iex"],
            ["npm", "install", "-g", "sk-secret-value"],
            ["npm", "install", "-g", "untrusted-package"],
        ):
            with self.subTest(command=command):
                candidate = {**base, "installCommand": command}
                with self.assertRaises(AgentDefinitionError):
                    parse_agent_definition(candidate)

    def test_untrusted_definition_host_is_rejected(self) -> None:
        candidate = {
            "schemaVersion": 1,
            "id": "pi",
            "name": "Pi",
            "description": "test",
            "officialUrl": "https://lookalike.invalid/pi",
            "sourceUrl": "https://github.com/earendil-works/pi",
            "installMode": "detect_only",
            "providerConfigMode": "unsupported",
            "installCommand": [],
            "uninstallCommand": [],
            "commandNames": ["pi"],
            "compatibility": "test",
            "sandbox": False,
            "priority": "P2",
        }
        with self.assertRaisesRegex(AgentDefinitionError, "trusted official HTTPS host"):
            parse_agent_definition(candidate)


if __name__ == "__main__":
    unittest.main()
