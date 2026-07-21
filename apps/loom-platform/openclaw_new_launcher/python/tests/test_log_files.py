from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class LogFileTests(unittest.TestCase):
    def test_rotation_and_clear_advance_opaque_generation(self) -> None:
        from core.log_files import append_rotating_text, clear_text_log, read_text_tail

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            first_generation = append_rotating_text(path, "a" * 200, max_bytes=256)
            first = read_text_tail(path, max_bytes=256)

            rotated_generation = append_rotating_text(path, "b" * 200, max_bytes=256)
            rotated = read_text_tail(path, max_bytes=256)

            cleared = clear_text_log(path)
            after_clear = read_text_tail(path, max_bytes=256)

        self.assertEqual(first["generation"], first_generation)
        self.assertEqual(rotated["generation"], rotated_generation)
        self.assertNotEqual(rotated_generation, first_generation)
        self.assertTrue(cleared["cleared"])
        self.assertEqual(after_clear["generation"], cleared["generation"])
        self.assertNotEqual(cleared["generation"], rotated_generation)
        self.assertNotIn(temp_dir, first_generation)

    def test_rotating_log_is_bounded_and_keeps_three_archives(self) -> None:
        from core.log_files import append_rotating_text

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            for index in range(80):
                append_rotating_text(
                    path,
                    f"line-{index}-" + ("x" * 80) + "\n",
                    max_bytes=700,
                    archive_count=3,
                )

            archives = [
                name
                for name in os.listdir(temp_dir)
                if name.startswith("bridge-service.log.")
            ]
            total_bytes = sum(
                os.path.getsize(os.path.join(temp_dir, name))
                for name in ["bridge-service.log", *archives]
            )

        self.assertEqual(len(archives), 3)
        self.assertLessEqual(total_bytes, 4 * 800)

    def test_tail_reader_does_not_load_unbounded_history(self) -> None:
        from core.log_files import read_text_tail

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            with open(path, "w", encoding="utf-8") as handle:
                for index in range(10_000):
                    handle.write(f"line-{index:05d}-" + ("x" * 40) + "\n")

            tail = read_text_tail(path, max_bytes=2048)
            total_bytes = os.path.getsize(path)

        self.assertLessEqual(len(tail["text"].encode("utf-8")), 2048)
        self.assertNotIn("line-00000", tail["text"])
        self.assertIn("line-09999", tail["text"])
        self.assertTrue(tail["truncated"])
        self.assertEqual(tail["totalBytes"], total_bytes)
        self.assertEqual(tail["windowBytes"], len(tail["text"].encode("utf-8")))
        self.assertEqual(tail["omittedBytes"], tail["totalBytes"] - tail["windowBytes"])

    def test_single_oversized_record_and_long_line_stay_bounded(self) -> None:
        from core.log_files import append_rotating_text, read_text_tail

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            append_rotating_text(path, "x" * 1000, max_bytes=300, archive_count=3)
            tail = read_text_tail(path, max_bytes=256)
            size = os.path.getsize(path)

        self.assertLessEqual(size, 300)
        self.assertEqual(len(tail["text"].encode("utf-8")), 256)
        self.assertEqual(tail["totalBytes"], size)
        self.assertEqual(tail["windowBytes"], 256)
        self.assertEqual(tail["omittedBytes"], size - 256)
        self.assertTrue(tail["truncated"])

    def test_tail_reader_aligns_to_utf8_boundary_for_long_multibyte_line(self) -> None:
        from core.log_files import read_text_tail

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("汉" * 100)

            tail = read_text_tail(path, max_bytes=256)

        self.assertLessEqual(len(tail["text"].encode("utf-8")), 256)
        self.assertEqual(tail["omittedBytes"], tail["totalBytes"] - tail["windowBytes"])
        self.assertNotIn(chr(0xFFFD), tail["text"])
        self.assertTrue(tail["text"])

    def test_clear_text_log_uses_shared_file_lock(self) -> None:
        from core import log_files

        class AuditLock:
            def __init__(self) -> None:
                self.entered = 0

            def __enter__(self):
                self.entered += 1
                return self

            def __exit__(self, _exc_type, _exc, _traceback) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bridge-service.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("before clear\n")
            lock = AuditLock()
            with patch.object(log_files, "_LOG_FILE_LOCK", lock):
                cleared = log_files.clear_text_log(path)
            with open(path, "r", encoding="utf-8") as handle:
                contents = handle.read()

        self.assertTrue(cleared["cleared"])
        self.assertTrue(cleared["generation"])
        self.assertEqual(lock.entered, 1)
        self.assertEqual(contents, "")


if __name__ == "__main__":
    unittest.main()
