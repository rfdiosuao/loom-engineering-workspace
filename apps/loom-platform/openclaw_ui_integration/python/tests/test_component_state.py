from __future__ import annotations

import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.component_state import ComponentStateError, ComponentStateStore
from core.release_manifest import parse_release_manifest


VALID_SHA256 = "d" * 64


def manifest_data() -> dict:
    return {
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
                "id": "openclaw-engine",
                "name": "OpenClaw Engine",
                "version": "2026.6.1",
                "platform": "windows",
                "arch": "x64",
                "type": "zip",
                "size": 100,
                "sha256": VALID_SHA256,
                "urls": ["https://download.heang.top/openclaw/openclaw-engine.zip"],
                "installPath": "OpenClawFiles/engine",
            },
            {
                "id": "desktop-rpa",
                "name": "Desktop RPA",
                "version": "1.0.0",
                "platform": "windows",
                "arch": "x64",
                "type": "zip",
                "size": 100,
                "sha256": VALID_SHA256,
                "urls": ["https://download.heang.top/openclaw/desktop-rpa.zip"],
                "installPath": "OpenClawFiles/desktop-rpa",
            },
        ],
    }


class ComponentStateStoreTests(unittest.TestCase):
    def test_mark_ready_persists_component_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "components-state.json"))

            state = store.mark(
                "openclaw-engine",
                "ready",
                version="2026.6.1",
                previous_version="2026.5.28",
                job_id="job-1",
            )
            loaded = store.load()

            self.assertEqual(state.status, "ready")
            self.assertEqual(loaded["openclaw-engine"].version, "2026.6.1")
            self.assertEqual(loaded["openclaw-engine"].previous_version, "2026.5.28")
            self.assertEqual(loaded["openclaw-engine"].job_id, "job-1")

    def test_invalid_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "components-state.json"))

            with self.assertRaisesRegex(ComponentStateError, "status"):
                store.mark("openclaw-engine", "maybe")

    def test_snapshot_fills_manifest_components_as_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "components-state.json"))
            manifest = parse_release_manifest(manifest_data())

            store.mark("openclaw-engine", "ready", version="2026.6.1")
            snapshot = store.snapshot_for_manifest(manifest)

            self.assertEqual(snapshot[0].component_id, "openclaw-engine")
            self.assertEqual(snapshot[0].status, "ready")
            self.assertEqual(snapshot[1].component_id, "desktop-rpa")
            self.assertEqual(snapshot[1].status, "not_installed")
            self.assertEqual(snapshot[1].version, "1.0.0")

    def test_corrupt_state_file_returns_empty_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "components-state.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken json")

            store = ComponentStateStore(path)
            self.assertEqual(store.load(), {})


if __name__ == "__main__":
    unittest.main()
