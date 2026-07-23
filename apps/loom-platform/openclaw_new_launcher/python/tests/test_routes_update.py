from __future__ import annotations

import asyncio
import threading
import time
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.routes_update import register_update_routes


class _FailedUpdater:
    last_installer_path = ""

    def current_version(self) -> str:
        return "2.1.89"

    def latest_version(self):
        return "2.1.90", None

    def latest_release(self):
        return SimpleNamespace(
            version="2.1.90",
            notes="",
            published_at="",
            release_url="",
            size=0,
        ), None

    def is_newer_version(self, _version: str) -> bool:
        return True

    def install_latest(self, progress_callback=None):
        if progress_callback:
            progress_callback(self.status())
        return False, "2.1.89", ["网络连接中断", "网络恢复后重试"]

    def status(self) -> dict:
        return {
            "phase": "failed",
            "downloaded": 11,
            "total": 100,
            "percent": 11,
            "version": "2.1.90",
            "message": "网络连接中断，已保留下载进度。",
            "errorCode": "network_interrupted",
            "retryable": True,
            "remediation": ["网络恢复后点击重试，LOOM 会从已下载的位置继续。"],
        }


class UpdateRouteTests(unittest.TestCase):
    def test_check_response_includes_release_notes_and_publication_metadata(self) -> None:
        app = FastAPI()

        class MetadataUpdater(_FailedUpdater):
            def latest_release(self):
                return SimpleNamespace(
                    version="2.3.0",
                    notes="## 更新内容\n\n- 全新更新中心",
                    published_at="2026-07-22T08:30:00Z",
                    release_url="https://example.invalid/releases/v2.3.0",
                    size=1024,
                ), None

        updater = MetadataUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).get("/api/update/check")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latest"], "2.3.0")
        self.assertIn("全新更新中心", response.json()["notes"])
        self.assertEqual(response.json()["publishedAt"], "2026-07-22T08:30:00Z")
        self.assertEqual(response.json()["size"], 1024)

    def test_check_never_offers_an_older_release_as_an_update(self) -> None:
        app = FastAPI()

        class NewerCurrentUpdater(_FailedUpdater):
            def current_version(self) -> str:
                return "2.3.1"

            def latest_release(self):
                release, error = super().latest_release()
                release.version = "2.3.0"
                return release, error

            def is_newer_version(self, _version: str) -> bool:
                return False

        updater = NewerCurrentUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).get("/api/update/check")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["hasUpdate"])

    def test_cancel_route_requests_download_cancellation(self) -> None:
        app = FastAPI()

        class CancelUpdater(_FailedUpdater):
            def __init__(self) -> None:
                self.called = False

            def cancel_update(self) -> bool:
                self.called = True
                return True

        updater = CancelUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).post("/api/update/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelRequested"])
        self.assertTrue(updater.called)

    def test_result_route_consumes_post_restart_receipt(self) -> None:
        app = FastAPI()

        class ResultUpdater(_FailedUpdater):
            def has_pending_update_result(self) -> bool:
                return True

            def consume_update_result(self):
                return {"status": "success", "version": "2.3.0", "confirmedAt": "now"}

        updater = ResultUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).get("/api/update/result")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["pending"])
        self.assertEqual(response.json()["result"]["version"], "2.3.0")

    def test_result_route_reports_when_no_receipt_is_pending(self) -> None:
        app = FastAPI()

        class EmptyResultUpdater(_FailedUpdater):
            def has_pending_update_result(self) -> bool:
                return False

            def consume_update_result(self):
                raise AssertionError("an absent receipt must not be consumed")

        updater = EmptyResultUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).get("/api/update/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"pending": False, "result": None})

    def test_cancelled_update_is_a_normal_outcome_without_an_error_payload(self) -> None:
        app = FastAPI()

        class CancelledUpdater(_FailedUpdater):
            def install_latest(self, progress_callback=None):
                if progress_callback:
                    progress_callback(self.status())
                return False, "2.2.0", ["update cancelled"]

            def status(self) -> dict:
                return {
                    **super().status(),
                    "phase": "cancelled",
                    "message": "update cancelled",
                    "errorCode": "update_cancelled",
                    "retryable": True,
                }

        updater = CancelledUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).post("/api/update/do")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "cancelled")
        self.assertNotIn("error", response.json())

    def test_failed_update_response_exposes_recovery_metadata(self) -> None:
        app = FastAPI()
        updater = _FailedUpdater()
        logs: list[str] = []
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=logs.append,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).post("/api/update/do")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["error"], updater.status()["message"])
        self.assertEqual(payload["errorCode"], "network_interrupted")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["remediation"], updater.status()["remediation"])
        self.assertEqual(payload["outcome"], "failed")
        self.assertEqual(logs, ["网络连接中断", "网络恢复后重试"])

    def test_failed_update_uses_request_progress_instead_of_shared_status(self) -> None:
        app = FastAPI()

        class BusyUpdater(_FailedUpdater):
            def install_latest(self, progress_callback=None):
                if progress_callback:
                    progress_callback(
                        {
                            "phase": "failed",
                            "message": "已有 LOOM 更新任务正在进行",
                            "errorCode": "update_in_progress",
                            "retryable": True,
                            "remediation": ["等待当前更新完成后再试。"],
                        }
                    )
                return False, "2.1.89", ["已有 LOOM 更新任务正在进行"]

            def status(self) -> dict:
                return {
                    "phase": "downloading",
                    "message": "正在下载更新包",
                    "errorCode": "",
                    "retryable": False,
                    "remediation": [],
                }

        updater = BusyUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).post("/api/update/do")

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload["errorCode"], "update_in_progress")
        self.assertEqual(payload["error"], "已有 LOOM 更新任务正在进行")
        self.assertEqual(payload["remediation"], ["等待当前更新完成后再试。"])

    def test_current_version_response_is_not_reported_as_ready_to_install(self) -> None:
        app = FastAPI()

        class CurrentUpdater(_FailedUpdater):
            def install_latest(self, progress_callback=None):
                status = {
                    "phase": "current",
                    "message": "当前已经是最新版本",
                    "errorCode": "",
                    "retryable": False,
                    "remediation": [],
                }
                if progress_callback:
                    progress_callback(status)
                return True, "2.1.89", ["当前已经是最新版本"]

            def status(self) -> dict:
                return {"phase": "current"}

        updater = CurrentUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)

        response = TestClient(app).post("/api/update/do")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["outcome"], "already_current")
        self.assertEqual(payload["installer_path"], "")


class UpdateCheckAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_route_does_not_block_the_event_loop(self) -> None:
        app = FastAPI()
        release = threading.Event()
        worker_started = threading.Event()
        heartbeat = asyncio.Event()
        loop = asyncio.get_running_loop()

        class BlockingUpdater(_FailedUpdater):
            def latest_release(self):
                worker_started.set()
                loop.call_soon_threadsafe(heartbeat.set)
                release.wait(timeout=1)
                return super().latest_release()

        updater = BlockingUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)
        timer = threading.Timer(1, release.set)
        timer.start()
        try:
            endpoint = next(
                route.endpoint
                for route in app.routes
                if getattr(route, "path", "") == "/api/update/check"
            )
            request = asyncio.create_task(endpoint(SimpleNamespace()))
            await asyncio.wait_for(heartbeat.wait(), timeout=1.5)
            self.assertTrue(worker_started.is_set())
            self.assertFalse(release.is_set(), "update check blocked the event loop until the worker finished")
            release.set()
            response = await request
        finally:
            release.set()
            timer.cancel()

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
