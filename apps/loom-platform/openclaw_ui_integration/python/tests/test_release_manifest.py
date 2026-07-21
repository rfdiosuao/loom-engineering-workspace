from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.release_manifest import ManifestValidationError, parse_release_manifest


VALID_SHA256 = "a" * 64


def valid_manifest() -> dict:
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
                "id": "desktop-rpa",
                "name": "Desktop RPA",
                "version": "1.0.0",
                "platform": "windows",
                "arch": "x64",
                "type": "zip",
                "size": 50000000,
                "sha256": VALID_SHA256,
                "urls": [
                    "https://cdn.heang.top/openclaw/v2.2.0/desktop-rpa.zip",
                    "https://github.com/openclaw/openclaw/releases/download/v2.2.0/desktop-rpa.zip",
                ],
                "installPath": "OpenClawFiles/desktop-rpa",
                "entry": "Luminode.exe",
                "healthCheck": {
                    "kind": "http",
                    "url": "http://127.0.0.1:18080/health",
                    "timeoutMs": 3000,
                },
                "rollback": {
                    "keepPrevious": True,
                    "backupName": "desktop-rpa.previous",
                },
            }
        ],
    }


class ReleaseManifestTests(unittest.TestCase):
    def test_valid_manifest_parses_components(self) -> None:
        manifest = parse_release_manifest(valid_manifest())

        self.assertEqual(manifest.product, "OpenClaw")
        self.assertEqual(manifest.version, "2.2.0")
        self.assertEqual(len(manifest.components), 1)
        self.assertEqual(manifest.components[0].component_id, "desktop-rpa")
        self.assertEqual(manifest.components[0].urls[0], "https://cdn.heang.top/openclaw/v2.2.0/desktop-rpa.zip")

    def test_missing_required_top_level_field_is_rejected(self) -> None:
        data = valid_manifest()
        del data["product"]

        with self.assertRaisesRegex(ManifestValidationError, "product"):
            parse_release_manifest(data)

    def test_component_requires_real_sha256(self) -> None:
        data = valid_manifest()
        data["components"][0]["sha256"] = "<64-hex>"

        with self.assertRaisesRegex(ManifestValidationError, "sha256"):
            parse_release_manifest(data)

    def test_component_download_urls_must_not_point_to_localhost(self) -> None:
        data = valid_manifest()
        data["components"][0]["urls"] = ["http://127.0.0.1:9000/desktop-rpa.zip"]

        with self.assertRaisesRegex(ManifestValidationError, "localhost|127.0.0.1"):
            parse_release_manifest(data)

    def test_component_install_path_must_stay_relative(self) -> None:
        data = valid_manifest()
        data["components"][0]["installPath"] = "../OpenClawFiles/desktop-rpa"

        with self.assertRaisesRegex(ManifestValidationError, "installPath"):
            parse_release_manifest(data)


if __name__ == "__main__":
    unittest.main()
