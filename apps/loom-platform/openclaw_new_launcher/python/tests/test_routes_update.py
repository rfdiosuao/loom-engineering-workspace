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

        class BlockingUpdater(_FailedUpdater):
            def latest_version(self):
                release.wait(timeout=1)
                return "2.1.90", None

        updater = BlockingUpdater()
        ctx = SimpleNamespace(
            auth_error=lambda _request: None,
            get_app_updater=lambda: updater,
            append_log=lambda _line: None,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
        )
        register_update_routes(app, ctx)
        timer = threading.Timer(0.3, release.set)
        timer.start()
        started_at = time.monotonic()
        try:
            endpoint = next(
                route.endpoint
                for route in app.routes
                if getattr(route, "path", "") == "/api/update/check"
            )
            request = asyncio.create_task(endpoint(SimpleNamespace()))
            await asyncio.sleep(0.05)
            self.assertLess(time.monotonic() - started_at, 0.2)
            release.set()
            response = await request
        finally:
            release.set()
            timer.cancel()

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
