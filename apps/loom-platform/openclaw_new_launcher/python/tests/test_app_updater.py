from __future__ import annotations

import hashlib
import io
import json
import errno
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from core.paths import AppPaths
from services.app_updater import LoomAppUpdater, LoomRelease, _default_update_cache_dir


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        url: str = "https://example.invalid/value",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._stream = io.BytesIO(payload)
        self.url = url
        self.status = status
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class _InterruptedResponse(_Response):
    def __init__(self, payload: bytes, *, fail_after: int, **kwargs) -> None:
        super().__init__(payload, **kwargs)
        self._fail_after = fail_after
        self._delivered = False

    def read(self, size: int = -1) -> bytes:
        del size
        if not self._delivered:
            self._delivered = True
            return self._stream.read(self._fail_after)
        raise ConnectionResetError("connection reset during update download")


class LoomAppUpdaterTests(unittest.TestCase):
    def test_latest_release_exposes_release_notes_and_publication_metadata(self) -> None:
        installer = b"release-with-notes"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "tag_name": "v2.3.0",
            "body": "## 更新内容\n\n- 全新更新中心\n- 支持安全回滚",
            "published_at": "2026-07-22T08:30:00Z",
            "html_url": "https://example.invalid/releases/v2.3.0",
            "assets": [{
                "name": "LOOM-2.3.0-setup.exe",
                "size": len(installer),
                "digest": f"sha256:{digest}",
                "browser_download_url": "https://downloads.example/LOOM-2.3.0-setup.exe",
            }],
        }

        def opener(request, timeout=0):
            del timeout
            return _Response(json.dumps(release).encode("utf-8"), url=request.full_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.2.0",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
            )
            latest, error = updater.latest_release()

        self.assertIsNone(error)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.version, "2.3.0")
        self.assertIn("全新更新中心", latest.notes)
        self.assertEqual(latest.published_at, "2026-07-22T08:30:00Z")
        self.assertEqual(latest.release_url, "https://example.invalid/releases/v2.3.0")

    def test_cancelled_download_keeps_partial_file_for_a_later_resume(self) -> None:
        installer = b"x" * (2 * 1024 * 1024 + 64)
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "body": "取消后应保留进度",
            "assets": [{
                "name": "LOOM-2.3.0-setup.exe",
                "size": len(installer),
                "digest": f"sha256:{digest}",
                "browser_download_url": "https://downloads.example/LOOM-2.3.0-setup.exe",
            }],
        }
        updater_ref: list[LoomAppUpdater] = []

        class CancellingResponse(_Response):
            def read(self, size: int = -1) -> bytes:
                chunk = super().read(min(size, 512 * 1024))
                if chunk and self._stream.tell() >= 512 * 1024:
                    updater_ref[0].cancel_update()
                return chunk

        def opener(request, timeout=0):
            del timeout
            if request.full_url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=request.full_url)
            return CancellingResponse(installer, url=request.full_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = os.path.join(temp_dir, "LOOM-Update-Recovery", "updates")
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.2.0",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )
            updater_ref.append(updater)

            success, version, _output = updater.install_latest()
            partial_path = os.path.join(cache_root, "LOOM-2.3.0-setup.exe.part")

            self.assertFalse(success)
            self.assertEqual(version, "2.2.0")
            self.assertEqual(updater.status()["phase"], "cancelled")
            self.assertEqual(updater.status()["errorCode"], "update_cancelled")
            self.assertTrue(os.path.isfile(partial_path))
            self.assertGreater(os.path.getsize(partial_path), 0)

    def test_update_result_receipt_is_returned_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recovery_root = os.path.join(temp_dir, "LOOM-Update-Recovery")
            update_cache = os.path.join(recovery_root, "updates")
            result_dir = os.path.join(recovery_root, "upgrade-backups", "2.3.0-test")
            os.makedirs(result_dir, exist_ok=True)
            with open(os.path.join(result_dir, "update-success.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "version": "2.3.0",
                    "state": "healthy",
                    "confirmedAt": "2026-07-22T08:45:00+08:00",
                }, handle)
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.3.0",
                release_api_urls=(),
                update_cache_dir=update_cache,
            )

            self.assertTrue(updater.has_pending_update_result())
            first = updater.consume_update_result()
            self.assertFalse(updater.has_pending_update_result())
            second = updater.consume_update_result()

        self.assertEqual(first["status"], "success")
        self.assertEqual(first["version"], "2.3.0")
        self.assertIsNone(second)

    def test_update_result_is_not_pending_without_a_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.3.0",
                release_api_urls=(),
                update_cache_dir=os.path.join(temp_dir, "LOOM-Update-Recovery", "updates"),
            )

            self.assertFalse(updater.has_pending_update_result())

    def test_update_failure_receipt_is_read_from_recovery_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recovery_root = os.path.join(temp_dir, "LOOM-Update-Recovery")
            update_cache = os.path.join(recovery_root, "updates")
            os.makedirs(recovery_root, exist_ok=True)
            with open(os.path.join(recovery_root, "update-failed.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "version": "2.3.0",
                    "state": "failed",
                    "error": "new version health check failed",
                    "rollbackState": "restored",
                    "recoveryActions": ["Restart the previous LOOM version."],
                }, handle)
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.2.0",
                release_api_urls=(),
                update_cache_dir=update_cache,
            )

            result = updater.consume_update_result()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rollbackState"], "restored")
        self.assertIn("health check failed", result["message"])
        self.assertEqual(result["remediation"], ["Restart the previous LOOM version."])

    def test_default_update_cache_uses_external_recovery_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {"LOCALAPPDATA": temp_dir},
                clear=False,
            ), patch.dict(os.environ, {"LOOM_UPDATE_CACHE_DIR": ""}):
                cache_dir = _default_update_cache_dir()

        self.assertEqual(
            os.path.normcase(cache_dir),
            os.path.normcase(os.path.join(temp_dir, "LOOM-Update-Recovery", "updates")),
        )

    def test_latest_release_chooses_highest_valid_version_across_sources(self) -> None:
        def release(version: str) -> dict:
            payload = f"installer-{version}".encode("ascii")
            digest = hashlib.sha256(payload).hexdigest()
            return {
                "assets": [
                    {
                        "name": f"LOOM-{version}-setup.exe",
                        "size": len(payload),
                        "digest": f"sha256:{digest}",
                        "browser_download_url": f"https://downloads.example/LOOM-{version}-setup.exe",
                    }
                ]
            }

        releases = {
            "https://gitee.example/releases/latest": release("2.1.45"),
            "https://github.example/releases/latest": release("2.1.58"),
        }

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            return _Response(json.dumps(releases[url]).encode("utf-8"), url=url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.1.57",
                release_api_urls=tuple(releases),
                opener=opener,
            )
            latest, error = updater.latest_version()

        self.assertIsNone(error)
        self.assertEqual(latest, "2.1.58")
        self.assertEqual(updater.cached_release.version, "2.1.58")
        self.assertEqual(updater.cached_release.source, "github.example")

    def test_latest_release_prefers_complete_setup_with_verified_digest(self) -> None:
        installer = b"complete-installer"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "tag_name": "v2.1.58",
            "assets": [
                {
                    "name": "LOOM-2.1.58-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.58-setup.exe",
                },
                {
                    "name": "LOOM-2.1.58-online-setup.exe",
                    "size": 3,
                    "digest": "sha256:" + ("0" * 64),
                    "browser_download_url": "https://downloads.example/online.exe",
                },
            ],
        }

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url.endswith("/releases/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.1.57",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
            )

            latest, error = updater.latest_version()

        self.assertIsNone(error)
        self.assertEqual(latest, "2.1.58")
        self.assertEqual(updater.cached_release.sha256, digest)
        self.assertTrue(updater.cached_release.url.endswith("LOOM-2.1.58-setup.exe"))

    def test_gitee_release_can_use_sidecar_sha_when_size_and_digest_are_omitted(self) -> None:
        digest = hashlib.sha256(b"gitee-installer").hexdigest()
        release = {
            "tag_name": "v2.1.58",
            "assets": [
                {
                    "name": "LOOM-2.1.58-setup.exe",
                    "browser_download_url": "https://gitee.example/LOOM-2.1.58-setup.exe",
                },
                {
                    "name": "LOOM-2.1.58-setup.exe.sha256.txt",
                    "browser_download_url": "https://gitee.example/LOOM-2.1.58-setup.exe.sha256.txt",
                },
            ],
        }

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url.endswith("/releases/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            if url.endswith(".sha256.txt"):
                return _Response(f"{digest} *LOOM-2.1.58-setup.exe".encode("ascii"), url=url)
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.1.57",
                release_api_urls=("https://gitee.example/releases/latest",),
                opener=opener,
            )
            latest, error = updater.latest_version()

        self.assertIsNone(error)
        self.assertEqual(latest, "2.1.58")
        self.assertEqual(updater.cached_release.size, 0)
        self.assertEqual(updater.cached_release.sha256, digest)

    def test_install_latest_verifies_sha256_before_launching(self) -> None:
        installer = b"verified-installer-bytes"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "tag_name": "v2.1.58",
            "assets": [
                {
                    "name": "LOOM-2.1.58-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.58-setup.exe",
                }
            ],
        }
        launched: list[str] = []

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url.endswith("/releases/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            if url.endswith("LOOM-2.1.58-setup.exe"):
                return _Response(installer, url=url)
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.1.57",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda path: launched.append(path),
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
            )

            success, version, output = updater.install_latest()

            self.assertTrue(success)
            self.assertEqual(version, "2.1.58")
            self.assertEqual(len(launched), 1)
            with open(launched[0], "rb") as handle:
                self.assertEqual(handle.read(), installer)
            self.assertTrue(any("SHA256" in line for line in output))

    def test_verified_cached_installer_skips_a_second_download(self) -> None:
        installer = b"already-downloaded-and-verified"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [{
                "name": "LOOM-2.3.0-setup.exe",
                "size": len(installer),
                "digest": f"sha256:{digest}",
                "browser_download_url": "https://downloads.example/LOOM-2.3.0-setup.exe",
            }],
        }
        download_requests: list[str] = []

        def opener(request, timeout=0):
            del timeout
            if request.full_url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=request.full_url)
            download_requests.append(request.full_url)
            raise AssertionError("verified cached installer should not be downloaded again")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = os.path.join(temp_dir, "cache")
            os.makedirs(cache_root, exist_ok=True)
            installer_path = os.path.join(cache_root, "LOOM-2.3.0-setup.exe")
            with open(installer_path, "wb") as handle:
                handle.write(installer)
            launched: list[str] = []
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.2.0",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=launched.append,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )

            success, version, _output = updater.install_latest()

        self.assertTrue(success)
        self.assertEqual(version, "2.3.0")
        self.assertFalse(download_requests)
        self.assertEqual(launched, [installer_path])

    def test_install_uses_its_request_local_release_snapshot(self) -> None:
        installer = b"request-local-release"
        digest = hashlib.sha256(installer).hexdigest()
        selected = LoomRelease(
            version="2.1.90",
            filename="LOOM-2.1.90-setup.exe",
            url="https://downloads.example/LOOM-2.1.90-setup.exe",
            size=len(installer),
            sha256=digest,
            source="selected.example",
        )
        unrelated = LoomRelease(
            version="9.9.9",
            filename="LOOM-9.9.9-setup.exe",
            url="https://downloads.example/LOOM-9.9.9-setup.exe",
            size=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
            source="concurrent-check.example",
        )
        launched: list[str] = []

        def opener(request, timeout=0):
            del timeout
            self.assertEqual(request.full_url, selected.url)
            return _Response(installer, url=selected.url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=(),
                opener=opener,
                launcher=launched.append,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            updater.cached_release = unrelated
            with patch.object(updater, "_resolve_latest_release", return_value=(selected, None)):
                success, version, _output = updater.install_latest()

        self.assertTrue(success)
        self.assertEqual(version, selected.version)
        self.assertEqual(os.path.basename(launched[0]), selected.filename)

    def test_install_latest_refuses_a_digest_mismatch(self) -> None:
        installer = b"tampered"
        release = {
            "tag_name": "v2.1.58",
            "assets": [
                {
                    "name": "LOOM-2.1.58-setup.exe",
                    "size": len(installer),
                    "digest": "sha256:" + ("a" * 64),
                    "browser_download_url": "https://downloads.example/LOOM-2.1.58-setup.exe",
                }
            ],
        }
        launched: list[str] = []

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            payload = json.dumps(release).encode("utf-8") if url.endswith("/releases/latest") else installer
            return _Response(payload, url=url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(temp_dir),
                current_version="2.1.57",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda path: launched.append(path),
            )
            success, _version, output = updater.install_latest()

        self.assertFalse(success)
        self.assertFalse(launched)
        self.assertTrue(any("SHA256" in line for line in output))

    def test_update_cache_is_outside_the_install_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = os.path.join(temp_dir, "installed-app")
            cache_root = os.path.join(temp_dir, "external-cache")
            updater = LoomAppUpdater(
                AppPaths(install_root),
                current_version="2.1.61",
                release_api_urls=(),
                update_cache_dir=cache_root,
            )

            self.assertEqual(os.path.realpath(updater.update_cache_dir), os.path.realpath(cache_root))
            self.assertFalse(
                os.path.commonpath(
                    [os.path.realpath(updater.update_cache_dir), os.path.realpath(updater.paths.data_dir)]
                )
                == os.path.realpath(updater.paths.data_dir)
            )

    def test_install_latest_resumes_partial_download_and_reports_progress(self) -> None:
        installer = b"verified-installer-with-resume"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.62-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.62-setup.exe",
                }
            ]
        }
        seen_ranges: list[str] = []
        progress: list[dict[str, object]] = []
        launched: list[str] = []

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url.endswith("/releases/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            range_header = request.headers.get("Range") or request.headers.get("range")
            if range_header:
                seen_ranges.append(range_header)
            start = int(str(range_header).split("=")[1].split("-")[0])
            return _Response(
                installer[start:],
                url=url,
                status=206,
                headers={"Content-Range": f"bytes {start}-{len(installer) - 1}/{len(installer)}"},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = os.path.join(temp_dir, "cache")
            os.makedirs(cache_root, exist_ok=True)
            partial_path = os.path.join(cache_root, "LOOM-2.1.62-setup.exe.part")
            with open(partial_path, "wb") as handle:
                handle.write(installer[:9])
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.61",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda path: launched.append(path),
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )

            success, version, _output = updater.install_latest(progress_callback=progress.append)

        self.assertTrue(success)
        self.assertEqual(version, "2.1.62")
        self.assertEqual(seen_ranges, ["bytes=9-"])
        self.assertEqual(len(launched), 1)
        self.assertTrue(any(item.get("phase") == "downloading" for item in progress))
        self.assertEqual(progress[-1].get("phase"), "ready")
        self.assertEqual(progress[-1].get("downloaded"), len(installer))

    def test_invalid_content_range_discards_partial_before_full_retry(self) -> None:
        installer = b"verified-installer-after-invalid-range"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }
        download_requests = 0

        def opener(request, timeout=0):
            nonlocal download_requests
            del timeout
            url = request.full_url
            if url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            download_requests += 1
            range_header = request.headers.get("Range") or request.headers.get("range")
            if download_requests == 1:
                self.assertEqual(range_header, "bytes=9-")
                return _Response(
                    installer,
                    url=url,
                    status=206,
                    headers={"Content-Range": f"bytes 0-{len(installer) - 1}/{len(installer)}"},
                )
            self.assertIsNone(range_header)
            return _Response(installer, url=url)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = os.path.join(temp_dir, "cache")
            os.makedirs(cache_root, exist_ok=True)
            partial_path = os.path.join(cache_root, "LOOM-2.1.90-setup.exe.part")
            with open(partial_path, "wb") as handle:
                handle.write(installer[:9])
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda _path: None,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )

            first_success, _version, first_output = updater.install_latest()
            self.assertFalse(first_success)
            self.assertFalse(os.path.exists(partial_path))
            self.assertTrue(any("断点续传" in line for line in first_output))
            self.assertEqual(updater.status()["errorCode"], "network_interrupted")

            second_success, version, _output = updater.install_latest()

        self.assertTrue(second_success)
        self.assertEqual(version, "2.1.90")

    def test_http_416_discards_partial_and_recovers_with_full_download(self) -> None:
        installer = b"verified-installer-after-http-416"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }
        download_requests = 0

        def opener(request, timeout=0):
            nonlocal download_requests
            del timeout
            url = request.full_url
            if url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            download_requests += 1
            range_header = request.headers.get("Range") or request.headers.get("range")
            if download_requests == 1:
                self.assertEqual(range_header, "bytes=7-")
                raise urllib.error.HTTPError(url, 416, "Range Not Satisfiable", {}, None)
            self.assertIsNone(range_header)
            return _Response(installer, url=url)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = os.path.join(temp_dir, "cache")
            os.makedirs(cache_root, exist_ok=True)
            partial_path = os.path.join(cache_root, "LOOM-2.1.90-setup.exe.part")
            with open(partial_path, "wb") as handle:
                handle.write(installer[:7])
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda _path: None,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )

            first_success, _version, _output = updater.install_latest()
            self.assertFalse(first_success)
            self.assertFalse(os.path.exists(partial_path))
            self.assertEqual(updater.status()["errorCode"], "network_interrupted")
            self.assertTrue(updater.status()["retryable"])

            second_success, version, _output = updater.install_latest()

        self.assertTrue(second_success)
        self.assertEqual(version, "2.1.90")

    def test_http_403_is_not_reported_as_retryable_network_interruption(self) -> None:
        installer = b"verified-installer"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }

        def opener(request, timeout=0):
            del timeout
            url = request.full_url
            if url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )

            success, _version, _output = updater.install_latest()

        self.assertFalse(success)
        self.assertEqual(updater.status()["errorCode"], "release_http_error")
        self.assertFalse(updater.status()["retryable"])

    def test_install_latest_refuses_invalid_windows_signature_after_sha256(self) -> None:
        installer = b"sha-valid-but-unsigned"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.62-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.62-setup.exe",
                }
            ]
        }
        launched: list[str] = []

        def opener(request, timeout=0):
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            payload = json.dumps(release).encode("utf-8") if url.endswith("/releases/latest") else installer
            return _Response(payload, url=url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.61",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda path: launched.append(path),
                signature_verifier=lambda _path: (False, "NotSigned"),
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            success, _version, output = updater.install_latest()

        self.assertFalse(success)
        self.assertFalse(launched)
        self.assertTrue(any("签名" in line or "signature" in line.lower() for line in output))

    def test_status_exposes_download_state_without_install_path_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.61",
                release_api_urls=(),
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            status = updater.status()

        self.assertEqual(status["phase"], "idle")
        self.assertEqual(status["downloaded"], 0)
        self.assertEqual(status["total"], 0)
        self.assertNotIn("installer_path", status)

    def test_cache_permission_failure_returns_actionable_failed_status(self) -> None:
        installer = b"verified-installer"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }

        def opener(request, timeout=0):
            del timeout
            return _Response(json.dumps(release).encode("utf-8"), url=request.full_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            with patch("services.app_updater.os.makedirs", side_effect=PermissionError("access denied")):
                success, _version, output = updater.install_latest()

        self.assertFalse(success)
        self.assertTrue(any("权限" in line for line in output))
        status = updater.status()
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["errorCode"], "permission_denied")
        self.assertFalse(status["retryable"])
        self.assertTrue(status["remediation"])

    def test_cache_disk_full_returns_actionable_failed_status(self) -> None:
        installer = b"verified-installer"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }

        def opener(request, timeout=0):
            del timeout
            return _Response(json.dumps(release).encode("utf-8"), url=request.full_url)

        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            with patch(
                "services.app_updater.os.makedirs",
                side_effect=OSError(errno.ENOSPC, "no space left on device"),
            ):
                success, _version, output = updater.install_latest()

        self.assertFalse(success)
        self.assertTrue(any("磁盘空间" in line for line in output))
        status = updater.status()
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["errorCode"], "disk_full")
        self.assertFalse(status["retryable"])

    def test_locked_installer_returns_retryable_actionable_status(self) -> None:
        installer = b"verified-installer"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }

        def opener(request, timeout=0):
            del timeout
            url = request.full_url
            payload = json.dumps(release).encode("utf-8") if url.endswith("/latest") else installer
            return _Response(payload, url=url)

        lock_error = PermissionError("file is being used by another process")
        lock_error.winerror = 32
        with tempfile.TemporaryDirectory() as temp_dir:
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "app")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=os.path.join(temp_dir, "cache"),
            )
            with patch("services.app_updater.os.replace", side_effect=lock_error):
                success, _version, output = updater.install_latest()

        self.assertFalse(success)
        self.assertTrue(any("占用" in line for line in output))
        status = updater.status()
        self.assertEqual(status["errorCode"], "file_locked")
        self.assertTrue(status["retryable"])

    def test_interrupted_download_is_resumable_and_reports_network_error(self) -> None:
        installer = b"verified-installer-with-network-resume"
        digest = hashlib.sha256(installer).hexdigest()
        release = {
            "assets": [
                {
                    "name": "LOOM-2.1.90-setup.exe",
                    "size": len(installer),
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://downloads.example/LOOM-2.1.90-setup.exe",
                }
            ]
        }
        interrupted = False
        ranges: list[str] = []

        def opener(request, timeout=0):
            nonlocal interrupted
            del timeout
            url = request.full_url
            if url.endswith("/latest"):
                return _Response(json.dumps(release).encode("utf-8"), url=url)
            range_header = request.headers.get("Range") or request.headers.get("range")
            if not interrupted:
                interrupted = True
                return _InterruptedResponse(installer, fail_after=11, url=url)
            self.assertEqual(range_header, "bytes=11-")
            ranges.append(str(range_header))
            return _Response(
                installer[11:],
                url=url,
                status=206,
                headers={"Content-Range": f"bytes 11-{len(installer) - 1}/{len(installer)}"},
            )

        with tempfile.TemporaryDirectory(prefix="麓鸣-更新-") as temp_dir:
            cache_root = os.path.join(temp_dir, "中文 更新缓存")
            updater = LoomAppUpdater(
                AppPaths(os.path.join(temp_dir, "应用")),
                current_version="2.1.89",
                release_api_urls=("https://api.example/releases/latest",),
                opener=opener,
                launcher=lambda _path: None,
                signature_verifier=lambda _path: (True, "CN=LOOM Release"),
                update_cache_dir=cache_root,
            )

            first_success, _version, first_output = updater.install_latest()
            first_status = updater.status()
            partial_path = os.path.join(cache_root, "LOOM-2.1.90-setup.exe.part")
            self.assertFalse(first_success)
            self.assertTrue(os.path.isfile(partial_path))
            self.assertTrue(any("网络" in line for line in first_output))
            self.assertEqual(first_status["errorCode"], "network_interrupted")
            self.assertTrue(first_status["retryable"])

            second_success, version, _output = updater.install_latest()

        self.assertTrue(second_success)
        self.assertEqual(version, "2.1.90")
        self.assertEqual(ranges, ["bytes=11-"])


if __name__ == "__main__":
    unittest.main()
