from __future__ import annotations

import importlib
import json
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

from core.paths import AppPaths
from core.phone_matrix import MatrixControlPlane


routes_media = importlib.import_module("api.routes_media")


class ImmediateJobManager:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {}

    def submit_progress(self, kind, _label, target, initial_progress=None):
        job_id = f"job-{kind}"
        self.results[job_id] = target(job_id)
        return {"id": job_id, "status": "succeeded", "result": self.results[job_id]}

    def progress(self, *_args, **_kwargs) -> None:
        return None


class MediaPhoneTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.paths = AppPaths(base_path=self.temp_dir.name)
        os.makedirs(self.paths.scripts_dir, exist_ok=True)
        Path(self.paths.scripts_dir, "openclaw-media-phone.mjs").write_text("", encoding="utf-8")
        self.ctx = SimpleNamespace(paths=self.paths)
        self.image_path = str(Path(self.paths.data_dir, "generated-images", "result.png"))
        self.video_path = str(Path(self.paths.data_dir, "videos", "result.mp4"))
        Path(self.image_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.video_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.image_path).write_bytes(b"image")
        Path(self.video_path).write_bytes(b"video")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def transfer(self, kind: str, files: list[dict]) -> dict:
        transfer = getattr(routes_media, "_transfer_generated_media_to_phone", None)
        self.assertTrue(callable(transfer), "media phone transfer helper is missing")
        return transfer(self.ctx, kind, files)

    @staticmethod
    def store(selected: str = "phone-a") -> dict:
        return {
            "selectedDeviceId": selected,
            "devices": [
                {
                    "id": "phone-a",
                    "name": "Selected Phone",
                    "baseUrl": "http://127.0.0.1:9527",
                    "token": "TOP_SECRET_PHONE_TOKEN",
                    "album": "LOOM",
                },
                {
                    "id": "phone-b",
                    "name": "Other Phone",
                    "baseUrl": "http://127.0.0.1:9528",
                    "token": "OTHER_SECRET_PHONE_TOKEN",
                    "album": "Other",
                },
            ],
        }

    def test_selected_online_phone_uses_upload_only_script_without_secret_args(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "image", "filename": "result.png"}],
            }),
            stderr="",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = self.transfer("image", [{"path": self.image_path, "mime": "image/png"}])

        command = run.call_args.args[0]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["deviceId"], "phone-a")
        self.assertEqual(result["uploadedCount"], 1)
        self.assertIn("openclaw-media-phone.mjs", " ".join(command))
        self.assertEqual(command[command.index("--device-id") + 1], "phone-a")
        self.assertEqual(command[command.index("--image") + 1], self.image_path)
        self.assertNotIn("phone-b", command)
        self.assertNotIn("TOP_SECRET_PHONE_TOKEN", repr(command))
        self.assertNotIn("TOP_SECRET_PHONE_TOKEN", json.dumps(result))

    def test_multi_phone_transfer_attempts_every_configured_device_and_reports_each_result(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "image", "filename": "result.png"}],
            }),
            stderr="",
        )

        transfer_many = getattr(routes_media, "_transfer_generated_media_to_phones", None)
        self.assertTrue(callable(transfer_many), "multi-phone media transfer helper is missing")
        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = transfer_many(self.ctx, "image", [{"path": self.image_path, "mime": "image/png"}])

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertCountEqual(
            [command[command.index("--device-id") + 1] for command in commands],
            ["phone-a", "phone-b"],
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["succeededDeviceCount"], 2)
        self.assertEqual(result["failedDeviceCount"], 0)
        self.assertEqual(
            [item["deviceId"] for item in result["deviceResults"]],
            ["phone-a", "phone-b"],
        )
        self.assertNotIn("TOP_SECRET_PHONE_TOKEN", json.dumps(result))

    def test_sync_and_async_http_generation_without_target_stays_local(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-b", "online": True})
        selected = {"value": "phone-a"}
        jobs = ImmediateJobManager()

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
        )
        routes_media.register_media_routes(app, ctx)

        def store_now(*_args):
            return self.store(selected=selected["value"])

        def generate_image(_ctx, _body):
            selected["value"] = "phone-b"
            return {
                "images": ["base64"],
                "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
                "count": 1,
            }

        def generate_video(_ctx, _body, on_status=None, *, request_key=""):
            selected["value"] = "phone-b"
            return {
                "video": "base64",
                "path": self.video_path,
                "filename": "result.mp4",
                "mime": "video/mp4",
            }

        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "image", "filename": "result.png"}],
            }),
            stderr="",
        )
        with mock.patch("api.routes_phone._load_store", side_effect=store_now), mock.patch(
            "api.routes_phone.node_executable",
            return_value="node",
        ), mock.patch("api.routes_phone.phone_process_env", return_value={}), mock.patch.object(
            routes_media,
            "_image_generate_payload",
            side_effect=generate_image,
        ), mock.patch.object(
            routes_media,
            "_video_generate_payload",
            side_effect=generate_video,
        ), mock.patch.object(routes_media.subprocess, "run", return_value=completed) as run:
            client = TestClient(app)
            for endpoint, kind in (
                ("/api/image/generate", "image"),
                ("/api/image/generate/submit", "image"),
                ("/api/video/generate", "video"),
                ("/api/video/generate/submit", "video"),
            ):
                with self.subTest(endpoint=endpoint):
                    run.reset_mock()
                    selected["value"] = "phone-a"
                    response = client.post(endpoint, json={"prompt": "snapshot target"})
                    self.assertEqual(response.status_code, 200)
                    if endpoint.endswith("/submit"):
                        payload = jobs.results[f"job-{kind}"]
                    else:
                        payload = response.json()
                        self.assertIn("images" if kind == "image" else "video", payload)
                    self.assertEqual(payload["phoneTransfer"]["status"], "skipped")
                    self.assertEqual(payload["phoneTransfer"]["reason"], "local_only")
                    run.assert_not_called()

    def test_http_generation_transfers_only_to_explicit_phone(self) -> None:
        jobs = ImmediateJobManager()

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
        )
        routes_media.register_media_routes(app, ctx)
        generated = {
            "images": ["base64"],
            "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
            "count": 1,
        }
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "image", "filename": "result.png"}],
            }),
            stderr="",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch(
            "api.routes_phone.node_executable",
            return_value="node",
        ), mock.patch("api.routes_phone.phone_process_env", return_value={}), mock.patch.object(
            routes_media,
            "_image_generate_payload",
            return_value=generated,
        ), mock.patch.object(routes_media.subprocess, "run", return_value=completed) as run:
            response = TestClient(app).post(
                "/api/image/generate",
                json={"prompt": "send to one phone", "deviceIds": ["phone-b"]},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["phoneTransfer"]["status"], "succeeded")
        self.assertEqual(payload["phoneTransfer"]["deviceId"], "phone-b")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--device-id") + 1], "phone-b")

    def test_http_generation_rejects_unknown_phone_before_sync_or_submit(self) -> None:
        jobs = ImmediateJobManager()

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
        )
        routes_media.register_media_routes(app, ctx)

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media,
            "_image_generate_payload",
        ) as generate, mock.patch.object(
            routes_media,
            "_transfer_generated_media_to_phones",
            return_value={"status": "succeeded"},
        ):
            client = TestClient(app)
            for endpoint in ("/api/image/generate", "/api/image/generate/submit"):
                with self.subTest(endpoint=endpoint):
                    response = client.post(
                        endpoint,
                        json={"prompt": "unknown target", "deviceIds": ["phone-404"]},
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()["errorCode"], "phone_target_not_found")

        generate.assert_not_called()
        self.assertEqual(jobs.results, {})

    def test_library_transfer_endpoint_targets_only_requested_phone(self) -> None:
        jobs = ImmediateJobManager()

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
        )
        routes_media._record_media(ctx, self.image_path, {
            "kind": "image",
            "mime": "image/png",
            "source": "ui",
        })
        asset = routes_media._media_library(ctx).list_assets("image", "", 20)["items"][0]
        routes_media.register_media_routes(app, ctx)
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "image", "filename": "result.png"}],
            }),
            stderr="",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch(
            "api.routes_phone.node_executable",
            return_value="node",
        ), mock.patch("api.routes_phone.phone_process_env", return_value={}), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ) as run:
            response = TestClient(app).post(
                f"/api/media/assets/{asset['id']}/transfer",
                json={"deviceIds": ["phone-b"]},
            )

        self.assertEqual(response.status_code, 200)
        result = jobs.results["job-media.transfer"]
        self.assertEqual(result["succeededDeviceCount"], 1)
        self.assertEqual(result["deviceResults"][0]["deviceId"], "phone-b")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--device-id") + 1], "phone-b")

    def test_async_image_failure_returns_safe_structured_result(self) -> None:
        jobs = ImmediateJobManager()

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
        )
        routes_media.register_media_routes(app, ctx)

        with mock.patch.object(
            routes_media,
            "_selected_phone_snapshot",
            return_value=None,
        ), mock.patch.object(
            routes_media,
            "_image_generate_payload",
            side_effect=routes_media.ImageApiError("HTTP 401 api_key=TOP_SECRET"),
        ):
            response = TestClient(app).post(
                "/api/image/generate/submit",
                json={"prompt": "generate a poster"},
            )

        self.assertEqual(response.status_code, 200)
        result = jobs.results["job-image"]
        self.assertFalse(result["success"])
        self.assertEqual(result["errorCode"], "image_provider_auth_failed")
        self.assertFalse(result["retryable"])
        self.assertNotIn("TOP_SECRET", json.dumps(result))

    def test_zero_exit_with_invalid_json_is_not_reported_as_uploaded(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        completed = SimpleNamespace(returncode=0, stdout="not-json", stderr="")

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ):
            result = self.transfer("image", [{"path": self.image_path}])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "phone_upload_invalid_response")
        self.assertEqual(result["uploadedCount"], 0)

    def test_ok_response_requires_exact_uploaded_count(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 2,
                "uploaded": [{"kind": "image", "filename": "one.png"}],
            }),
            stderr="",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ):
            result = self.transfer("image", [
                {"path": self.image_path},
                {"path": self.image_path},
            ])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "phone_upload_incomplete")
        self.assertEqual(result["uploadedCount"], 1)
        self.assertEqual(result["totalCount"], 2)
        self.assertEqual(result["uploadedFiles"], ["one.png"])

    def test_partial_upload_failure_returns_only_safe_filename_summary(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        completed = SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "ok": False,
                "errorCode": "media_upload_partial_failure",
                "uploadedCount": 1,
                "totalCount": 2,
                "uploaded": [{"kind": "image", "filename": "first.png"}],
                "failed": [{"kind": "image", "filename": "second.png"}],
                "message": "TOP_SECRET_PHONE_TOKEN",
            }),
            stderr="TOP_SECRET_PHONE_TOKEN",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ):
            result = self.transfer("image", [
                {"path": self.image_path},
                {"path": self.image_path},
            ])

        serialized = json.dumps(result)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["uploadedCount"], 1)
        self.assertEqual(result["totalCount"], 2)
        self.assertEqual(result["uploadedFiles"], ["first.png"])
        self.assertNotIn(self.image_path, serialized)
        self.assertNotIn("TOP_SECRET_PHONE_TOKEN", serialized)

    def test_no_selected_phone_is_a_structured_skip(self) -> None:
        with mock.patch("api.routes_phone._load_store", return_value=self.store(selected="")), mock.patch.object(
            routes_media.subprocess,
            "run",
        ) as run:
            result = self.transfer("image", [{"path": self.image_path}])

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_selected_phone")
        self.assertFalse(result["attempted"])
        run.assert_not_called()

    def test_stale_offline_matrix_presence_does_not_block_real_upload(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": False})
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "ok": True,
                "uploadedCount": 1,
                "totalCount": 1,
                "uploaded": [{"kind": "video", "filename": "result.mp4"}],
            }),
            stderr="",
        )

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = self.transfer("video", [{"path": self.video_path, "mime": "video/mp4"}])

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["deviceId"], "phone-a")
        self.assertTrue(result["attempted"])
        run.assert_called_once()

    def test_upload_failure_is_nonfatal_and_secret_safe(self) -> None:
        MatrixControlPlane(self.paths).register_device({"deviceId": "phone-a", "online": True})
        completed = SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "ok": False,
                "errorCode": "phone_request_failed",
                "message": "rejected TOP_SECRET_PHONE_TOKEN",
            }),
            stderr="",
        )
        generated = {
            "images": ["large-base64"],
            "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
            "count": 1,
        }
        async_result = getattr(routes_media, "_async_media_job_result", None)
        self.assertTrue(callable(async_result), "async media result helper is missing")

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
            return_value=completed,
        ):
            result = async_result(
                self.ctx,
                "image",
                generated,
                phone_snapshot={
                    "devices": [{"id": "phone-a", "name": "Selected Phone"}],
                    "reason": "",
                    "missingDeviceIds": [],
                },
            )

        self.assertEqual(result["files"][0]["path"], self.image_path)
        self.assertNotIn("images", result)
        self.assertEqual(result["phoneTransfer"]["status"], "failed")
        self.assertEqual(result["phoneTransfer"]["reason"], "phone_request_failed")
        self.assertNotIn("TOP_SECRET_PHONE_TOKEN", json.dumps(result))

    def test_async_media_result_without_target_cannot_expand_to_configured_phones(self) -> None:
        generated = {
            "images": ["large-base64"],
            "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
            "count": 1,
        }

        with mock.patch("api.routes_phone._load_store", return_value=self.store()), mock.patch.object(
            routes_media.subprocess,
            "run",
        ) as run:
            result = routes_media._async_media_job_result(self.ctx, "image", generated)

        self.assertEqual(result["phoneTransfer"]["status"], "skipped")
        self.assertEqual(result["phoneTransfer"]["reason"], "local_only")
        self.assertEqual(result["files"][0]["path"], self.image_path)
        run.assert_not_called()

    def test_generated_media_upload_failures_preserve_local_result_and_block_regeneration(self) -> None:
        generated = {
            "images": ["large-base64"],
            "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
            "count": 1,
        }
        phone_snapshot = {
            "devices": [{"id": "phone-a", "name": "Selected Phone"}],
            "reason": "",
            "missingDeviceIds": [],
        }
        cases = (
            (
                "all-failed",
                {
                    "status": "failed",
                    "reason": "phone_request_failed",
                    "attempted": True,
                    "deviceCount": 1,
                    "succeededDeviceCount": 0,
                    "failedDeviceCount": 1,
                },
                "partial_failure",
                False,
            ),
            (
                "partial",
                {
                    "status": "failed",
                    "reason": "phone_upload_partial_failure",
                    "attempted": True,
                    "deviceCount": 2,
                    "succeededDeviceCount": 1,
                    "failedDeviceCount": 1,
                },
                "partial_failure",
                False,
            ),
        )

        for label, transfer_result, expected_status, indeterminate in cases:
            with self.subTest(label=label), mock.patch.object(
                routes_media,
                "_transfer_generated_media_to_phones",
                return_value=transfer_result,
            ):
                result = routes_media._async_media_job_result(
                    self.ctx,
                    "image",
                    generated,
                    phone_snapshot=phone_snapshot,
                )

            self.assertEqual(result["status"], expected_status)
            self.assertFalse(result["success"])
            self.assertEqual(result["outcomeIndeterminate"], indeterminate)
            self.assertFalse(result["retryable"])
            self.assertFalse(result["regenerationAllowed"])
            self.assertEqual(result["files"][0]["path"], self.image_path)

        with mock.patch.object(
            routes_media,
            "_transfer_generated_media_to_phones",
            side_effect=RuntimeError("connection lost after upload"),
        ):
            uncertain = routes_media._async_media_job_result(
                self.ctx,
                "image",
                generated,
                phone_snapshot=phone_snapshot,
            )

        self.assertEqual(uncertain["status"], "outcome_uncertain")
        self.assertFalse(uncertain["success"])
        self.assertTrue(uncertain["outcomeIndeterminate"])
        self.assertFalse(uncertain["retryable"])
        self.assertFalse(uncertain["regenerationAllowed"])
        self.assertEqual(uncertain["files"][0]["path"], self.image_path)

    def test_upload_timeout_returns_uncertain_result_without_losing_local_file(self) -> None:
        generated = {
            "images": ["large-base64"],
            "files": [{"path": self.image_path, "filename": "result.png", "mime": "image/png"}],
            "count": 1,
        }
        phone_snapshot = {
            "devices": [{"id": "phone-a", "name": "Selected Phone"}],
            "reason": "",
            "missingDeviceIds": [],
        }

        with mock.patch(
            "api.routes_phone.node_executable",
            return_value="node",
        ), mock.patch("api.routes_phone.phone_process_env", return_value={}), mock.patch.object(
            routes_media.subprocess,
            "run",
            side_effect=routes_media.subprocess.TimeoutExpired("upload", 180),
        ):
            result = routes_media._async_media_job_result(
                self.ctx,
                "image",
                generated,
                phone_snapshot=phone_snapshot,
            )

        self.assertEqual(result["status"], "outcome_uncertain")
        self.assertFalse(result["success"])
        self.assertTrue(result["outcomeIndeterminate"])
        self.assertFalse(result["retryable"])
        self.assertFalse(result["regenerationAllowed"])
        self.assertEqual(result["files"][0]["path"], self.image_path)
        self.assertEqual(result["phoneTransfer"]["status"], "outcome_uncertain")
        self.assertEqual(result["phoneTransfer"]["reason"], "phone_upload_outcome_unknown")

    def test_async_video_generation_returns_actionable_public_failure(self) -> None:
        jobs = ImmediateJobManager()
        logs: list[str] = []

        async def body(request):
            return await request.json()

        app = FastAPI()
        ctx = SimpleNamespace(
            paths=self.paths,
            auth_error=lambda _request: None,
            protected_error=lambda _path: None,
            body=body,
            fastapi_json=lambda data, status_code=200: JSONResponse(data, status_code=status_code),
            get_job_mgr=lambda: jobs,
            append_log=logs.append,
        )
        routes_media.register_media_routes(app, ctx)

        with mock.patch.object(
            routes_media,
            "_selected_phone_snapshot",
            return_value=None,
        ), mock.patch.object(
            routes_media,
            "_video_generate_payload",
            side_effect=routes_media.VideoApiError(
                "Invalid URL (POST /v1/services/aigc/video-generation/video-synthesis)"
            ),
        ):
            response = TestClient(app).post(
                "/api/video/generate/submit",
                json={"prompt": "LOOM demo"},
            )

        self.assertEqual(response.status_code, 200)
        result = jobs.results["job-video"]
        self.assertFalse(result["success"])
        self.assertEqual(result["errorCode"], "video_provider_endpoint_mismatch")
        self.assertIn("Provider", result["error"])
        self.assertNotIn("/v1/services/aigc", result["error"])
        self.assertTrue(any("Invalid URL" in entry for entry in logs))


if __name__ == "__main__":
    unittest.main()
