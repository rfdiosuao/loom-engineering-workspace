from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_log import register_log_routes


class LogRouteTests(unittest.TestCase):
    def test_clear_then_same_length_append_resets_stale_generation_cursor(self) -> None:
        from core.log_files import append_rotating_text

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("first")

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            client = TestClient(app)
            first = client.get("/api/log/get").json()
            cleared = client.post("/api/log/clear").json()
            append_rotating_text(log_path, "fresh", max_bytes=4096)
            second = client.get(
                f"/api/log/get?offset={first['offset']}&generation={first['generation']}"
            ).json()

        self.assertEqual(first["offset"], second["offset"])
        self.assertNotEqual(first["generation"], cleared["generation"])
        self.assertEqual(second["generation"], cleared["generation"])
        self.assertTrue(second["reset"])
        self.assertEqual(second["log"], "fresh")

    def test_same_size_rotation_resets_stale_generation_cursor(self) -> None:
        from core.log_files import append_rotating_text

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            original = "a" * 200
            replacement = "b" * 200
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            client = TestClient(app)
            first = client.get("/api/log/get").json()
            append_rotating_text(log_path, replacement, max_bytes=256)
            second = client.get(
                f"/api/log/get?offset={first['offset']}&generation={first['generation']}"
            ).json()

        self.assertEqual(first["offset"], second["offset"])
        self.assertNotEqual(first["generation"], second["generation"])
        self.assertTrue(second["reset"])
        self.assertEqual(second["log"], replacement)

    def test_same_size_external_replacement_resets_stale_generation_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            replacement_path = os.path.join(log_dir, "replacement.log")
            original = "old-generation"
            replacement = "new-generation"
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            client = TestClient(app)
            first = client.get("/api/log/get").json()
            with open(replacement_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(replacement)
            os.replace(replacement_path, log_path)
            second = client.get(
                f"/api/log/get?offset={first['offset']}&generation={first['generation']}"
            ).json()

        self.assertEqual(len(original), len(replacement))
        self.assertEqual(first["offset"], second["offset"])
        self.assertNotEqual(first["generation"], second["generation"])
        self.assertTrue(second["reset"])
        self.assertEqual(second["log"], replacement)

    def test_log_snapshot_is_atomic_with_append_and_next_delta_does_not_duplicate(self) -> None:
        from core import log_files

        class InstrumentedLock:
            def __init__(self) -> None:
                self._lock = threading.RLock()
                self.owner_ident: int | None = None
                self.writer_attempted = threading.Event()

            def __enter__(self):
                if threading.current_thread().name == "log-writer":
                    self.writer_attempted.set()
                self._lock.acquire()
                self.owner_ident = threading.get_ident()
                return self

            def __exit__(self, _exc_type, _exc, _traceback) -> None:
                self.owner_ident = None
                self._lock.release()

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            initial = "before\n"
            appended = "after"
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(initial)

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            client = TestClient(app)
            lock = InstrumentedLock()
            stat_captured = threading.Event()
            release_reader = threading.Event()
            writer_done = threading.Event()
            reader_ident: list[int] = []
            first_response: list[dict] = []
            errors: list[BaseException] = []
            real_getsize = os.path.getsize

            def paused_getsize(path: str) -> int:
                size = real_getsize(path)
                if path == log_path and threading.current_thread().name != "log-writer" and not stat_captured.is_set():
                    reader_ident.append(threading.get_ident())
                    stat_captured.set()
                    if not release_reader.wait(5):
                        raise AssertionError("reader barrier was not released")
                return size

            def read_first() -> None:
                try:
                    first_response.append(client.get("/api/log/get").json())
                except BaseException as exc:
                    errors.append(exc)

            def append_once() -> None:
                try:
                    log_files.append_rotating_text(log_path, appended, max_bytes=4096)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    writer_done.set()

            with (
                patch.object(log_files, "_LOG_FILE_LOCK", lock),
                patch.object(log_files.os.path, "getsize", side_effect=paused_getsize),
            ):
                reader = threading.Thread(target=read_first, name="log-reader")
                reader.start()
                self.assertTrue(stat_captured.wait(5))
                reader_holds_lock = lock.owner_ident == reader_ident[0]
                writer = threading.Thread(target=append_once, name="log-writer")
                writer.start()
                self.assertTrue(lock.writer_attempted.wait(5))
                if not reader_holds_lock:
                    self.assertTrue(writer_done.wait(5))
                release_reader.set()
                reader.join(5)
                writer.join(5)
                self.assertFalse(reader.is_alive())
                self.assertFalse(writer.is_alive())
                second_response = client.get(f"/api/log/get?offset={first_response[0]['offset']}").json()

        self.assertEqual(errors, [])
        first = first_response[0]
        self.assertEqual(first["log"], initial)
        self.assertEqual(first["offset"], len(initial.encode("utf-8")))
        self.assertEqual(first["windowBytes"] + first["omittedBytes"], first["totalBytes"])
        self.assertEqual(second_response["log"], appended)
        self.assertEqual(second_response["offset"], len((initial + appended).encode("utf-8")))

    def test_log_clear_delegates_to_shared_lock_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=["before clear\n"],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            with patch(
                "api.routes_log.clear_text_log",
                return_value={"cleared": True, "generation": "generation-after-clear"},
            ) as clear:
                response = TestClient(app).post("/api/log/clear")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["generation"], "generation-after-clear")
        clear.assert_called_once_with(os.path.join(temp_dir, "logs", "bridge-service.log"))
        self.assertEqual(ctx.log_buffer, [])

    def test_persisted_oversized_jsonl_record_reports_full_file_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            record = '{"message":"' + ("x" * (700 * 1024)) + '"}\n'
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write(record)
            total_bytes = os.path.getsize(log_path)

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            response = TestClient(app).get("/api/log/get")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["totalBytes"], total_bytes)
        self.assertEqual(payload["windowBytes"], len(payload["log"].encode("utf-8")))
        self.assertEqual(payload["omittedBytes"], total_bytes - payload["windowBytes"])
        self.assertTrue(payload["truncated"])
        self.assertGreater(payload["omittedBytes"], 0)

    def test_persisted_tail_offset_survives_window_slide_after_same_size_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = os.path.join(temp_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "bridge-service.log")
            old_record = ("x" * 1023) + "\n"
            new_prefix = "new-entry-"
            new_record = new_prefix + ("y" * (1023 - len(new_prefix))) + "\n"
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(old_record * 700)

            app = FastAPI()
            ctx = SimpleNamespace(
                auth_error=lambda _request: None,
                fastapi_json=lambda data, status_code=200: JSONResponse(status_code=status_code, content=data),
                log_buffer=[],
                log_lock=threading.RLock(),
                paths=SimpleNamespace(data_dir=temp_dir),
            )
            register_log_routes(app, ctx)
            client = TestClient(app)
            first = client.get("/api/log/get").json()
            first_total = os.path.getsize(log_path)

            with open(log_path, "a", encoding="utf-8", newline="") as handle:
                handle.write(new_record)
            second = client.get(f"/api/log/get?offset={first['offset']}").json()
            second_total = os.path.getsize(log_path)

        self.assertEqual(first["offset"], first_total)
        self.assertEqual(second["log"], new_record)
        self.assertEqual(second["offset"], second_total)
        self.assertFalse(second["reset"])
        self.assertEqual(second["totalBytes"], second_total)
        self.assertEqual(second["windowStartBytes"], second["omittedBytes"])
        self.assertEqual(second["windowBytes"] + second["omittedBytes"], second["totalBytes"])


if __name__ == "__main__":
    unittest.main()
