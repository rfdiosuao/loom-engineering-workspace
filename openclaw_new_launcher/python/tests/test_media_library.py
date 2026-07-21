from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from services.media_library import MediaLibrary, MediaLibraryError


class MediaLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.library = MediaLibrary(str(self.data_dir))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write(self, relative: str, payload: bytes = b"asset") -> Path:
        path = self.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_list_discovers_existing_image_and_video_files(self) -> None:
        first_image = self.write("generated-images/loom-image-a.png", b"png-a")
        second_image = self.write("generated-images/openclaw-image-b.webp", b"webp-b")
        video = self.write("videos/loom-video-c.mp4", b"video-c")
        os.utime(first_image, (100, 100))
        os.utime(second_image, (200, 200))
        os.utime(video, (300, 300))

        result = self.library.list_assets(kind=None, cursor="", limit=20)

        self.assertEqual([item["kind"] for item in result["items"]], ["video", "image", "image"])
        self.assertEqual([item["filename"] for item in result["items"]], [video.name, second_image.name, first_image.name])
        self.assertTrue(all(item["id"] for item in result["items"]))
        self.assertFalse(result["hasMore"])
        self.assertEqual(result["nextCursor"], "")

    def test_listing_is_stable_and_ignores_unknown_extensions(self) -> None:
        self.write("generated-images/keep.jpg", b"jpg")
        self.write("generated-images/ignore.txt", b"text")

        first = self.library.list_assets("image", "", 20)
        second = self.library.list_assets("image", "", 20)

        self.assertEqual(len(first["items"]), 1)
        self.assertEqual(first["items"][0]["id"], second["items"][0]["id"])

    def test_sidecar_metadata_is_optional_and_corruption_is_ignored(self) -> None:
        image = self.write("generated-images/loom-image-a.png", b"png")
        Path(f"{image}.json").write_text("{bad-json", encoding="utf-8")

        corrupt = self.library.list_assets("image", "", 20)["items"][0]
        self.assertEqual(corrupt["filename"], image.name)
        self.assertNotIn("prompt", corrupt)

        Path(f"{image}.json").write_text(
            json.dumps({"schema": "loom.media.asset.v1", "prompt": "保留中文", "ratio": "5:2", "source": "cli"}),
            encoding="utf-8",
        )
        enriched = self.library.list_assets("image", "", 20)["items"][0]
        self.assertEqual(enriched["prompt"], "保留中文")
        self.assertEqual(enriched["ratio"], "5:2")
        self.assertEqual(enriched["source"], "cli")

    def test_generation_size_metadata_cannot_replace_the_file_byte_size(self) -> None:
        image = self.write("generated-images/loom-image-sized.png", b"seven!!")
        Path(f"{image}.json").write_text(
            json.dumps({
                "schema": "loom.media.asset.v1",
                "size": "1024x1024",
                "ratio": "1:1",
            }),
            encoding="utf-8",
        )

        item = self.library.list_assets("image", "", 20)["items"][0]

        self.assertEqual(item["size"], 7)
        self.assertEqual(item["generationSize"], "1024x1024")

    def test_pagination_uses_opaque_cursor_without_duplicates(self) -> None:
        for index in range(3):
            path = self.write(f"generated-images/image-{index}.png", str(index).encode())
            os.utime(path, (100 + index, 100 + index))

        first = self.library.list_assets("image", "", 2)
        second = self.library.list_assets("image", first["nextCursor"], 2)

        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(second["items"]), 1)
        self.assertFalse(second["hasMore"])
        self.assertFalse({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})

    def test_record_and_delete_manage_sidecar_without_touching_other_files(self) -> None:
        image = self.write("generated-images/recorded.png", b"png")
        item = self.library.record(str(image), {"prompt": "test", "mode": "i2i", "ratio": "3:4"})
        other = self.write("generated-images/other.png", b"other")

        self.assertTrue(Path(f"{image}.json").is_file())
        self.assertEqual(item["mode"], "i2i")
        deleted = self.library.delete(item["id"])

        self.assertEqual(deleted, {"deleted": True, "id": item["id"]})
        self.assertFalse(image.exists())
        self.assertFalse(Path(f"{image}.json").exists())
        self.assertTrue(other.exists())

    def test_rejects_unknown_ids_directories_and_paths_outside_library(self) -> None:
        outside = self.data_dir / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        directory = self.data_dir / "generated-images" / "folder.png"
        directory.mkdir(parents=True)

        with self.assertRaises(MediaLibraryError):
            self.library.resolve("missing")
        with self.assertRaises(MediaLibraryError):
            self.library.record(str(outside), {})
        with self.assertRaises(MediaLibraryError):
            self.library.record(str(directory), {})

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlink_that_escapes_allowed_roots(self) -> None:
        outside = self.data_dir / "outside.png"
        outside.write_bytes(b"secret")
        link = self.data_dir / "generated-images" / "linked.png"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(outside, link)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        self.assertEqual(self.library.list_assets("image", "", 20)["items"], [])
        with self.assertRaises(MediaLibraryError):
            self.library.record(str(link), {})


if __name__ == "__main__":
    unittest.main()
