from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.release_manifest_client import ManifestFetchError, ReleaseManifestClient


VALID_SHA256 = "e" * 64


def manifest_data(version: str = "2.2.0") -> dict:
    return {
        "schemaVersion": 1,
        "product": "OpenClaw",
        "channel": "stable",
        "version": version,
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
            }
        ],
    }


class ReleaseManifestClientTests(unittest.TestCase):
    def test_fetch_tries_next_source_and_writes_cache(self) -> None:
        calls: list[str] = []

        def fetcher(url: str, timeout: float) -> bytes:
            calls.append(url)
            if "primary" in url:
                raise OSError("primary down")
            return json.dumps(manifest_data("2.2.1")).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "release-manifest.json")
            client = ReleaseManifestClient(cache_path=cache_path, fetcher=fetcher)

            result = client.fetch(["https://primary.example/manifest.json", "https://backup.example/manifest.json"])

            self.assertFalse(result.from_cache)
            self.assertEqual(result.source_url, "https://backup.example/manifest.json")
            self.assertEqual(result.manifest.version, "2.2.1")
            self.assertEqual(calls, ["https://primary.example/manifest.json", "https://backup.example/manifest.json"])
            self.assertTrue(os.path.exists(cache_path))

    def test_fetch_uses_last_good_cache_when_all_sources_fail(self) -> None:
        def fetcher(url: str, timeout: float) -> bytes:
            raise OSError("network down")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "release-manifest.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(manifest_data("2.1.9"), handle)

            client = ReleaseManifestClient(cache_path=cache_path, fetcher=fetcher)
            result = client.fetch(["https://primary.example/manifest.json"])

            self.assertTrue(result.from_cache)
            self.assertEqual(result.manifest.version, "2.1.9")

    def test_invalid_remote_manifest_does_not_overwrite_cache(self) -> None:
        def fetcher(url: str, timeout: float) -> bytes:
            return json.dumps({"schemaVersion": 1}).encode("utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "release-manifest.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(manifest_data("2.1.9"), handle)

            client = ReleaseManifestClient(cache_path=cache_path, fetcher=fetcher)
            result = client.fetch(["https://primary.example/manifest.json"])

            self.assertTrue(result.from_cache)
            self.assertEqual(result.manifest.version, "2.1.9")
            with open(cache_path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            self.assertEqual(cached["version"], "2.1.9")

    def test_missing_sources_and_cache_raise_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = ReleaseManifestClient(cache_path=os.path.join(temp_dir, "release-manifest.json"))

            with self.assertRaisesRegex(ManifestFetchError, "No manifest source"):
                client.fetch([])


if __name__ == "__main__":
    unittest.main()
