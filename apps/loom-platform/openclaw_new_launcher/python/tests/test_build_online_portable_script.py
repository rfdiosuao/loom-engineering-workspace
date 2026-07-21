from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest


WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT_PATH = os.path.join(WORKSPACE_ROOT, "scripts", "build-online-portable.ps1")


def _write(path: str, content: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _make_source_portable(root: str) -> str:
    source = os.path.join(root, "source")
    payload = os.path.join(source, "LOOMFiles")
    os.makedirs(payload, exist_ok=True)
    _write(os.path.join(source, "LOOM.exe"), "launcher")
    _write(os.path.join(payload, "package.json"), json.dumps({"version": "9.9.9"}))
    _write(os.path.join(payload, "_up_", "python", "bridge.py"), "# bridge")
    _write(os.path.join(payload, "scripts", "openclaw-context.mjs"), "// context")
    _write(os.path.join(payload, "data", ".openclaw", "workspace", "runtime-context.json"), "{}")
    _write(os.path.join(payload, "release-manifest.json"), "{}")
    _write(os.path.join(payload, "release-public-key.txt"), "pub")
    _write(os.path.join(payload, "node", "node.exe"), "node")
    _write(os.path.join(payload, "node_modules", "pkg", "index.js"), "// deps")
    _write(os.path.join(payload, "_up_", "python-runtime", "python.exe"), "python")
    return source


def _nested_distribution_manifest(path: str) -> None:
    layer_hash = "a" * 64
    manifest = {
        "schemaVersion": 1,
        "product": "LOOM",
        "channel": "rc",
        "version": "9.9.9",
        "publishedAt": "2026-06-28T00:00:00Z",
        "minLauncherVersion": "2.1.19",
        "signature": {"algorithm": "ed25519", "value": base64.b64encode(b"x" * 64).decode("ascii")},
        "components": [
            {
                "id": "codex-desktop",
                "name": "Codex",
                "version": "1.0.0",
                "platform": "windows",
                "arch": "x64",
                "type": "zip",
                "size": 1,
                "sha256": layer_hash,
                "urls": ["https://download.example.invalid/codex.zip"],
                "installPath": "LOOMFiles/agents/codex",
            }
        ],
        "distribution": {
            "mirrors": ["https://download.example.invalid/loom/"],
            "layers": [
                {"id": "node", "title": "Node.js", "file": "node.tgz", "sha256": layer_hash, "installPath": "LOOMFiles/node", "required": True},
                {
                    "id": "openclaw-deps",
                    "title": "Runtime deps",
                    "file": "openclaw-deps.tgz",
                    "sha256": layer_hash,
                    "installPath": "LOOMFiles/node_modules",
                    "required": True,
                },
                {
                    "id": "python-runtime",
                    "title": "Python runtime",
                    "file": "python-runtime.tgz",
                    "sha256": layer_hash,
                    "installPath": "LOOMFiles/_up_/python-runtime",
                    "required": True,
                },
            ],
        },
    }
    _write(path, json.dumps(manifest, ensure_ascii=False))


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell is required")
class BuildOnlinePortableScriptTests(unittest.TestCase):
    def test_accepts_distribution_section_inside_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = _make_source_portable(temp_dir)
            manifest_path = os.path.join(temp_dir, "release-manifest.json")
            output_root = os.path.join(temp_dir, "out")
            _nested_distribution_manifest(manifest_path)

            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    SCRIPT_PATH,
                    "-SourcePortableDir",
                    source,
                    "-DistributionManifestPath",
                    manifest_path,
                    "-OutputRoot",
                    output_root,
                    "-PackageName",
                    "LOOM-Online-vtest",
                    "-NoZip",
                ],
                cwd=WORKSPACE_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            package_dir = os.path.join(output_root, "LOOM-Online-vtest")
            self.assertTrue(os.path.isfile(os.path.join(package_dir, "LOOM.exe")))
            self.assertFalse(os.path.exists(os.path.join(package_dir, "LOOMFiles", "node")))
            self.assertFalse(os.path.exists(os.path.join(package_dir, "LOOMFiles", "node_modules")))
            self.assertTrue(os.path.isfile(os.path.join(package_dir, "LOOMFiles", "_up_", "python-runtime", "python.exe")))

            cached_manifest = os.path.join(package_dir, "LOOMFiles", "data", ".openclaw", "dist-cache", "manifest.json")
            with open(cached_manifest, "rb") as handle:
                self.assertNotEqual(handle.read(3), b"\xef\xbb\xbf")
            with open(cached_manifest, "r", encoding="utf-8-sig") as handle:
                cached = json.load(handle)
            with open(manifest_path, "r", encoding="utf-8-sig") as handle:
                source_manifest = json.load(handle)
            self.assertEqual(cached, source_manifest)
            self.assertEqual(cached["schemaVersion"], 1)
            self.assertEqual(cached["product"], "LOOM")
            self.assertEqual(cached["signature"]["algorithm"], "ed25519")
            self.assertIn("components", cached)
            self.assertIn("distribution", cached)


if __name__ == "__main__":
    unittest.main()
