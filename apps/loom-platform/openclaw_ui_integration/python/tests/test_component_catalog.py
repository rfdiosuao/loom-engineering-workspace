from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.component_catalog import ComponentCatalog
from core.component_state import ComponentStateStore


VALID_SHA256 = "1" * 64


def write_manifest(path: str) -> None:
    data = {
        "schemaVersion": 1,
        "product": "OpenClaw",
        "channel": "stable",
        "version": "2.2.0",
        "publishedAt": "2026-06-28T00:00:00+08:00",
        "minLauncherVersion": "2.1.15",
        "signature": {
            "algorithm": "ed25519",
            "value": "base64-signature",
        },
        "components": [
            {
                "id": "codex-desktop",
                "name": "Codex",
                "version": "26.602.71036",
                "platform": "windows",
                "arch": "x64",
                "type": "installer",
                "size": 100,
                "sha256": VALID_SHA256,
                "urls": ["https://download.heang.top/openclaw/codex.exe"],
                "installPath": "OpenClawFiles/agents/codex",
                "entry": "Codex-Installer.exe",
                "category": "agent",
                "officialUrl": "https://get.microsoft.com/installer/download/9PLM9XGG6VKS",
            }
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class ComponentCatalogTests(unittest.TestCase):
    def test_status_merges_manifest_component_with_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = os.path.join(temp_dir, "release-manifest.json")
            write_manifest(manifest_path)
            state_store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            state_store.mark("codex-desktop", "ready", version="26.602.71036")

            catalog = ComponentCatalog(manifest_path=manifest_path, state_store=state_store)
            payload = catalog.status()

            self.assertEqual(payload["manifest"]["version"], "2.2.0")
            self.assertEqual(payload["components"][0]["id"], "codex-desktop")
            self.assertEqual(payload["components"][0]["name"], "Codex")
            self.assertEqual(payload["components"][0]["status"], "ready")
            self.assertEqual(payload["components"][0]["category"], "agent")
            self.assertEqual(payload["components"][0]["officialUrl"], "https://get.microsoft.com/installer/download/9PLM9XGG6VKS")

    def test_missing_manifest_returns_clear_error_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ComponentCatalog(
                manifest_path=os.path.join(temp_dir, "missing.json"),
                state_store=ComponentStateStore(os.path.join(temp_dir, "state.json")),
            )

            payload = catalog.status()

            self.assertEqual(payload["components"], [])
            self.assertIn("manifest", payload["error"])


if __name__ == "__main__":
    unittest.main()
