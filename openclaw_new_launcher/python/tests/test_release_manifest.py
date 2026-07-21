from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.release_manifest import ManifestValidationError, canonical_manifest_payload, parse_release_manifest
from core.release_manifest_client import (
    DEFAULT_RELEASE_MANIFEST_SOURCES,
    ManifestFetchError,
    ReleaseManifestClient,
    default_release_manifest_sources,
)


def valid_manifest() -> dict:
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


def signed_manifest() -> tuple[dict, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    manifest = valid_manifest()
    signature = private_key.sign(canonical_manifest_payload(manifest))
    manifest["signature"]["value"] = base64.b64encode(signature).decode("ascii")
    public_key_b64 = base64.b64encode(
        public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    ).decode("ascii")
    return manifest, public_key_b64


class ReleaseManifestValidationTests(unittest.TestCase):
    def test_rejects_unknown_component_archive_type(self) -> None:
        manifest = copy.deepcopy(valid_manifest())
        manifest["components"][0]["type"] = "rar"

        with self.assertRaisesRegex(ManifestValidationError, "type"):
            parse_release_manifest(manifest)

    def test_rejects_placeholder_component_sha256_values(self) -> None:
        placeholders = [
            "1" * 64,
            "0123456789abcdef" * 4,
            "123456789abcdef0" * 4,
            "deadbeef" * 8,
        ]
        for placeholder in placeholders:
            with self.subTest(placeholder=placeholder):
                manifest = copy.deepcopy(valid_manifest())
                manifest["components"][0]["sha256"] = placeholder

                with self.assertRaisesRegex(ManifestValidationError, "placeholder"):
                    parse_release_manifest(manifest)

    def test_verifies_ed25519_signature_with_public_key(self) -> None:
        manifest, public_key = signed_manifest()

        parsed = parse_release_manifest(manifest, public_key=public_key, require_signature_verification=True)

        self.assertEqual(parsed.product, "LOOM")

    def test_component_can_declare_external_detection_paths(self) -> None:
        manifest = copy.deepcopy(valid_manifest())
        manifest["components"][0]["externalPaths"] = [
            "%LOCALAPPDATA%/hermes/hermes-agent/venv/Scripts/hermes.EXE",
            "%USERPROFILE%/.hermes/config.yaml",
        ]

        parsed = parse_release_manifest(manifest)

        self.assertEqual(
            getattr(parsed.components[0], "external_paths", ()),
            (
                "%LOCALAPPDATA%/hermes/hermes-agent/venv/Scripts/hermes.EXE",
                "%USERPROFILE%/.hermes/config.yaml",
            ),
        )

    def test_component_can_declare_silent_installer_args(self) -> None:
        manifest = copy.deepcopy(valid_manifest())
        manifest["components"][0]["type"] = "installer"
        manifest["components"][0]["entry"] = "Hermes-Setup.exe"
        manifest["components"][0]["installerArgs"] = ["/S"]
        manifest["components"][0]["installerTimeoutMs"] = 123000

        parsed = parse_release_manifest(manifest)

        self.assertEqual(getattr(parsed.components[0], "installer_args", ()), ("/S",))
        self.assertEqual(getattr(parsed.components[0], "installer_timeout_ms", 0), 123000)

    def test_component_can_declare_install_and_uninstall_commands(self) -> None:
        manifest = copy.deepcopy(valid_manifest())
        manifest["components"][0]["installCommand"] = ["npm", "install", "-g", "opencode-ai@1.17.11"]
        manifest["components"][0]["uninstallCommand"] = ["npm", "uninstall", "-g", "opencode-ai"]
        manifest["components"][0]["commandTimeoutMs"] = 456000

        parsed = parse_release_manifest(manifest)

        self.assertEqual(getattr(parsed.components[0], "install_command", ()), ("npm", "install", "-g", "opencode-ai@1.17.11"))
        self.assertEqual(getattr(parsed.components[0], "uninstall_command", ()), ("npm", "uninstall", "-g", "opencode-ai"))
        self.assertEqual(getattr(parsed.components[0], "command_timeout_ms", 0), 456000)

    def test_rejects_unpinned_or_latest_npm_install_commands(self) -> None:
        for package_name in ("opencode-ai", "@openai/codex@latest"):
            with self.subTest(package_name=package_name):
                manifest = copy.deepcopy(valid_manifest())
                manifest["components"][0]["installCommand"] = ["npm", "install", "-g", package_name]

                with self.assertRaisesRegex(ManifestValidationError, "installCommand"):
                    parse_release_manifest(manifest)

    def test_rejects_pipe_to_shell_install_commands(self) -> None:
        manifest = copy.deepcopy(valid_manifest())
        manifest["components"][0]["installCommand"] = [
            "powershell",
            "-NoProfile",
            "-Command",
            "irm https://example.invalid/install.ps1 | iex",
        ]

        with self.assertRaisesRegex(ManifestValidationError, "installCommand"):
            parse_release_manifest(manifest)

    def test_rejects_tampered_manifest_when_signature_verification_required(self) -> None:
        manifest, public_key = signed_manifest()
        manifest["components"][0]["version"] = "9.9.9"

        with self.assertRaisesRegex(ManifestValidationError, "signature"):
            parse_release_manifest(manifest, public_key=public_key, require_signature_verification=True)

    def test_requires_public_key_when_signature_verification_required(self) -> None:
        manifest, _public_key = signed_manifest()

        with self.assertRaisesRegex(ManifestValidationError, "public key"):
            parse_release_manifest(manifest, require_signature_verification=True)

    def test_manifest_client_requires_signature_verification_for_remote_sources(self) -> None:
        manifest, _public_key = signed_manifest()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "release-manifest-cache.json")
            client = ReleaseManifestClient(
                cache_path=cache_path,
                fetcher=lambda _url, _timeout: json.dumps(manifest).encode("utf-8"),
            )

            with self.assertRaisesRegex(ManifestFetchError, "no cached manifest"):
                client.fetch(["https://download.example.invalid/release-manifest.json"])
            self.assertFalse(os.path.exists(cache_path))

    def test_manifest_client_accepts_signed_remote_and_signed_cache_with_public_key(self) -> None:
        manifest, public_key = signed_manifest()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "release-manifest-cache.json")
            client = ReleaseManifestClient(
                cache_path=cache_path,
                public_key=public_key,
                fetcher=lambda _url, _timeout: json.dumps(manifest).encode("utf-8"),
            )

            fetched = client.fetch(["https://download.example.invalid/release-manifest.json"])
            self.assertFalse(fetched.from_cache)
            self.assertEqual(fetched.manifest.product, "LOOM")

            cached = ReleaseManifestClient(cache_path=cache_path, public_key=public_key).fetch([])
            self.assertTrue(cached.from_cache)
            self.assertEqual(cached.manifest.product, "LOOM")

    def test_default_release_manifest_sources_point_to_loom_release_channel(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(default_release_manifest_sources(), list(DEFAULT_RELEASE_MANIFEST_SOURCES))
            self.assertTrue(all("rfdiosuao/loom-release-channel" in source for source in default_release_manifest_sources()))

    def test_default_release_manifest_sources_can_be_overridden_and_disabled(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"LOOM_RELEASE_MANIFEST_URLS": "https://a.test/one.json;https://b.test/two.json"}):
            self.assertEqual(default_release_manifest_sources(), ["https://a.test/one.json", "https://b.test/two.json"])
        with unittest.mock.patch.dict(os.environ, {"LOOM_RELEASE_MANIFEST_DISABLE_DEFAULTS": "1"}, clear=True):
            self.assertEqual(default_release_manifest_sources(), [])

    def test_schema_allows_optional_distribution_manifest_for_online_package(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(PYTHON_DIR)),
            "schemas",
            "openclaw-release-manifest.schema.json",
        )
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)

        distribution = schema["properties"]["distribution"]
        self.assertEqual(distribution["type"], "object")
        self.assertIn("mirrors", distribution["required"])
        self.assertIn("layers", distribution["required"])
        self.assertEqual(distribution["properties"]["layers"]["items"]["$ref"], "#/$defs/distributionLayer")


if __name__ == "__main__":
    unittest.main()
