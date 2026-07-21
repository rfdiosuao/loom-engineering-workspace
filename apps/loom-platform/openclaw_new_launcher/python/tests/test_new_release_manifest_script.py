from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PYTHON_DIR = os.path.join(WORKSPACE_ROOT, "openclaw_new_launcher", "python")
SCRIPT_PATH = os.path.join(WORKSPACE_ROOT, "scripts", "new-release-manifest.ps1")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.release_manifest import ManifestValidationError, parse_release_manifest


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell is required")
class NewReleaseManifestScriptTests(unittest.TestCase):
    def test_signed_manifest_preserves_and_covers_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_path = os.path.join(temp_dir, "component.zip")
            with open(artifact_path, "wb") as handle:
                handle.write(b"release component payload")

            distribution = {
                "mirrors": ["https://downloads.loom.test/runtime/"],
                "layers": [
                    {
                        "id": "node",
                        "title": "Node.js",
                        "file": "node.tgz",
                        "sha256": "1234567890abcdef" * 4,
                        "installPath": "LOOMFiles/node",
                        "required": True,
                    }
                ],
            }
            spec = {
                "schemaVersion": 1,
                "product": "LOOM",
                "channel": "test",
                "version": "9.9.9",
                "publishedAt": "2026-07-18T00:00:00Z",
                "minLauncherVersion": "2.1.92",
                "components": [
                    {
                        "id": "test-component",
                        "name": "Test component",
                        "version": "1.0.0",
                        "platform": "windows",
                        "arch": "x64",
                        "type": "zip",
                        "artifactPath": artifact_path,
                        "urls": ["https://downloads.loom.test/test-component.zip"],
                        "installPath": "agents/test-component",
                    }
                ],
                "distribution": distribution,
            }
            spec_path = os.path.join(temp_dir, "spec.json")
            manifest_path = os.path.join(temp_dir, "release-manifest.json")
            public_key_path = os.path.join(temp_dir, "release-public-key.txt")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(spec, handle)

            private_key = base64.b64encode(bytes(range(32))).decode("ascii")
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    SCRIPT_PATH,
                    "-SpecPath",
                    spec_path,
                    "-OutputPath",
                    manifest_path,
                    "-PublicKeyPath",
                    public_key_path,
                    "-PrivateKey",
                    private_key,
                ],
                cwd=WORKSPACE_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            with open(public_key_path, "r", encoding="utf-8-sig") as handle:
                public_key = handle.read().strip()

            self.assertEqual(manifest["distribution"], distribution)
            parse_release_manifest(manifest, public_key=public_key, require_signature_verification=True)

            tampered = copy.deepcopy(manifest)
            tampered["distribution"]["mirrors"][0] = "https://tampered.loom.test/runtime/"
            with self.assertRaisesRegex(ManifestValidationError, "signature"):
                parse_release_manifest(tampered, public_key=public_key, require_signature_verification=True)


if __name__ == "__main__":
    unittest.main()
