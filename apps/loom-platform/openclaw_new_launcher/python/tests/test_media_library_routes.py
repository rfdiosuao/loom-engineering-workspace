from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from api.routes_media import _reveal_in_file_manager, register_media_routes


class MediaLibraryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        image_dir = self.data_dir / "generated-images"
        video_dir = self.data_dir / "videos"
        image_dir.mkdir(parents=True)
        video_dir.mkdir(parents=True)
        (image_dir / "test.png").write_bytes(b"image")
        (video_dir / "test.mp4").write_bytes(b"0123456789")

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=SimpleNamespace(data_dir=str(self.data_dir)),
            auth_error=lambda _request: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_media_routes(app, ctx)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_filters_assets_and_returns_persistent_paths(self) -> None:
        response = self.client.get("/api/media/assets?kind=image&limit=20")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["filename"], "test.png")
        self.assertTrue(os.path.isabs(payload["items"][0]["path"]))

    def test_content_supports_full_and_range_responses(self) -> None:
        asset_id = self.client.get("/api/media/assets?kind=video").json()["items"][0]["id"]

        full = self.client.get(f"/api/media/assets/{asset_id}/content")
        partial = self.client.get(
            f"/api/media/assets/{asset_id}/content",
            headers={"Range": "bytes=2-5"},
        )

        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.content, b"0123456789")
        self.assertEqual(full.headers["accept-ranges"], "bytes")
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b"2345")
        self.assertEqual(partial.headers["content-range"], "bytes 2-5/10")

    def test_invalid_range_returns_416(self) -> None:
        asset_id = self.client.get("/api/media/assets?kind=video").json()["items"][0]["id"]

        response = self.client.get(
            f"/api/media/assets/{asset_id}/content",
            headers={"Range": "bytes=50-60"},
        )

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers["content-range"], "bytes */10")

    @mock.patch("api.routes_media._reveal_in_file_manager")
    def test_reveal_and_delete_use_resolved_asset(self, reveal: mock.Mock) -> None:
        asset = self.client.get("/api/media/assets?kind=image").json()["items"][0]

        opened = self.client.post(f"/api/media/assets/{asset['id']}/reveal")
        deleted = self.client.delete(f"/api/media/assets/{asset['id']}")

        self.assertEqual(opened.status_code, 200)
        reveal.assert_called_once_with(asset["path"])
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertFalse(Path(asset["path"]).exists())

    @mock.patch("api.routes_media.subprocess.Popen")
    def test_windows_reveal_selects_exact_file_with_separate_explorer_arguments(
        self,
        popen: mock.Mock,
    ) -> None:
        path = r"D:\LOOM\Luming AI Matrix Acquisition Workbench\data\generated-images\test.png"

        with mock.patch("api.routes_media.os.name", "nt"):
            _reveal_in_file_manager(path)

        popen.assert_called_once_with(
            ["explorer.exe", "/select,", os.path.normpath(path)]
        )

    def test_unknown_asset_returns_404_without_exposing_paths(self) -> None:
        response = self.client.get("/api/media/assets/does-not-exist/content")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(str(self.data_dir), response.text)


if __name__ == "__main__":
    unittest.main()
