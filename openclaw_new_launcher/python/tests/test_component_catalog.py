from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api.routes_components import SIMULATION_COMPONENTS
from core.component_catalog import ComponentCatalog, default_manifest_path
from core.component_state import ComponentState, ComponentStateStore


def unsigned_manifest() -> dict:
    payload = b"component package"
    return {
        "schemaVersion": 1,
        "product": "LOOM",
        "channel": "stable",
        "version": "1.0.0",
        "publishedAt": "2026-06-28T00:00:00Z",
        "minLauncherVersion": "1.0.0",
        "signature": {
            "algorithm": "ed25519",
            "value": base64.b64encode(b"x" * 64).decode("ascii"),
        },
        "components": [
            {
                "id": "codex-desktop",
                "name": "Codex",
                "version": "1.0.0",
                "platform": "windows",
                "arch": "x64",
                "type": "zip",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "urls": ["https://download.example.invalid/codex.zip"],
                "installPath": "agents/codex-desktop",
                "entry": "bin/codex.exe",
            }
        ],
    }


class ComponentCatalogFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {"LOOM_RELEASE_MANIFEST_DISABLE_DEFAULTS": "1"})
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_default_manifest_path_finds_parent_release_manifest_in_dev_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launcher_dir = os.path.join(temp_dir, "openclaw_new_launcher")
            os.makedirs(launcher_dir)
            parent_manifest = os.path.join(temp_dir, "release-manifest.json")
            with open(parent_manifest, "w", encoding="utf-8") as file:
                file.write("{}")

            self.assertEqual(default_manifest_path(launcher_dir), parent_manifest)

    def test_default_manifest_path_finds_double_up_tauri_resource_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = os.path.join(temp_dir, "Luming")
            nested_resource_dir = os.path.join(install_dir, "_up_", "_up_")
            os.makedirs(nested_resource_dir)
            manifest = os.path.join(nested_resource_dir, "release-manifest.json")
            with open(manifest, "w", encoding="utf-8") as file:
                file.write("{}")

            self.assertEqual(default_manifest_path(install_dir), manifest)

    def test_default_manifest_path_finds_repo_manifest_from_tauri_debug_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_dir = os.path.join(
                temp_dir,
                "openclaw_new_launcher",
                "src-tauri",
                "target",
                "debug",
            )
            os.makedirs(debug_dir)
            parent_manifest = os.path.join(temp_dir, "release-manifest.json")
            with open(parent_manifest, "w", encoding="utf-8") as file:
                file.write("{}")

            self.assertEqual(default_manifest_path(debug_dir), parent_manifest)

    def test_missing_manifest_exposes_five_simulation_targets_without_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "components-state.json")
            catalog = ComponentCatalog(
                manifest_path=os.path.join(temp_dir, "missing-release-manifest.json"),
                state_store=ComponentStateStore(state_path),
                fallback_components=SIMULATION_COMPONENTS.values(),
            )

            status = catalog.status()

            self.assertEqual(status["manifest"], None)
            self.assertEqual(status["manifestErrorCode"], "manifest_unavailable")
            self.assertTrue(status["installLocked"])
            self.assertIn("正式组件清单未就绪", status["warning"])
            self.assertNotIn("模拟安装", status["warning"])
            self.assertNotIn("All manifest sources", status["warning"])
            self.assertEqual(
                [component["id"] for component in status["components"]],
                ["codex-desktop", "claude-code", "opencode", "openclaw-companion", "hermes"],
            )
            codex = next(component for component in status["components"] if component["id"] == "codex-desktop")
            self.assertEqual(codex["name"], "ChatGPT Codex 原版")
            self.assertEqual(codex["type"], "msstore")
            self.assertEqual(codex["installCommand"], [])
            self.assertEqual(codex["urls"], ["https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi"])
            self.assertTrue(all(component["status"] == "not_installed" for component in status["components"]))
            self.assertFalse(os.path.exists(state_path))

    def test_status_can_overlay_simulation_result_without_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "components-state.json")
            catalog = ComponentCatalog(
                manifest_path=os.path.join(temp_dir, "missing-release-manifest.json"),
                state_store=ComponentStateStore(state_path),
                fallback_components=SIMULATION_COMPONENTS.values(),
            )

            status = catalog.status(
                state_overrides=[
                    ComponentState("codex-desktop", "simulation_ready", version="simulate", job_id="job_sim"),
                ]
            )

            codex = next(component for component in status["components"] if component["id"] == "codex-desktop")
            self.assertEqual(codex["status"], "simulation_ready")
            self.assertEqual(codex["installedVersion"], None)
            self.assertEqual(codex["jobId"], "job_sim")
            self.assertFalse(os.path.exists(state_path))

    def test_started_component_still_reports_installed_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "components-state.json")
            catalog = ComponentCatalog(
                manifest_path=os.path.join(temp_dir, "missing-release-manifest.json"),
                state_store=ComponentStateStore(state_path),
                fallback_components=SIMULATION_COMPONENTS.values(),
            )

            status = catalog.status(
                state_overrides=[
                    ComponentState("codex-desktop", "started", version="simulate", job_id="job_start"),
                ]
            )

            codex = next(component for component in status["components"] if component["id"] == "codex-desktop")
            self.assertEqual(codex["status"], "started")
            self.assertEqual(codex["installedVersion"], "simulate")
            self.assertEqual(codex["jobId"], "job_start")

    def test_legacy_codex_cli_state_is_not_reported_as_official_store_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = ComponentCatalog(
                manifest_path=os.path.join(temp_dir, "missing-release-manifest.json"),
                state_store=ComponentStateStore(os.path.join(temp_dir, "components-state.json")),
                fallback_components=SIMULATION_COMPONENTS.values(),
            )

            status = catalog.status(state_overrides=[
                ComponentState("codex-desktop", "started", version="0.142.3-win32-x64", job_id="legacy-cli"),
            ])

            codex = next(component for component in status["components"] if component["id"] == "codex-desktop")
            self.assertEqual(codex["status"], "not_installed")
            self.assertIsNone(codex["installedVersion"])
            self.assertEqual(codex["errorCode"], "legacy_codex_cli_state")

    def test_manifest_without_public_key_is_not_treated_as_installable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = os.path.join(temp_dir, "release-manifest.json")
            state_path = os.path.join(temp_dir, "components-state.json")
            with open(manifest_path, "w", encoding="utf-8") as file:
                json.dump(unsigned_manifest(), file)
            catalog = ComponentCatalog(
                manifest_path=manifest_path,
                state_store=ComponentStateStore(state_path),
                fallback_components=SIMULATION_COMPONENTS.values(),
            )

            status = catalog.status()

            self.assertEqual(status["manifest"], None)
            self.assertEqual(status["manifestErrorCode"], "manifest_unavailable")
            self.assertTrue(status["installLocked"])
            self.assertIn("清单", status["warning"])


if __name__ == "__main__":
    unittest.main()
