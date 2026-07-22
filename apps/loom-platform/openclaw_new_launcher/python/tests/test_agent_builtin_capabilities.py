from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON_ROOT = os.path.join(REPO_ROOT, "python")
if PYTHON_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_ROOT)


class UnavailableRuntime:
    def status(self, profile_id=None) -> dict:
        return {"available": False, "profileId": profile_id or "default"}


class RecordingJobManager:
    def __init__(self) -> None:
        self.submissions: list[dict] = []
        self.results: dict[str, dict] = {}
        self.progress_updates: list[tuple[str, str, str, dict]] = []
        self.cancelled: list[str] = []

    def submit_progress(self, kind, label, target, initial_progress=None):
        job_id = f"job-{kind}-{len(self.submissions) + 1}"
        job = {"id": job_id, "kind": kind, "status": "queued"}
        self.submissions.append({**job, "label": label, "initialProgress": initial_progress})
        self.results[job_id] = target(job_id)
        return job

    def progress(self, job_id, message, tone="neutral", **details):
        self.progress_updates.append((job_id, message, tone, details))

    def get(self, job_id):
        result = self.results.get(job_id)
        if result is None:
            return {"id": job_id, "kind": "publish", "status": "queued", "result": None}
        failed = result.get("success") is False
        return {
            "id": job_id,
            "kind": "publish",
            "status": "failed" if failed else "succeeded",
            "result": result,
            "error": result.get("error") if failed else None,
        }

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return True


class PendingJobManager(RecordingJobManager):
    def submit_progress(self, kind, label, target, initial_progress=None):
        job_id = f"job-{kind}-pending"
        job = {"id": job_id, "kind": kind, "status": "queued"}
        self.submissions.append({**job, "label": label, "initialProgress": initial_progress})
        return job

    def get(self, job_id):
        return {"id": job_id, "status": "running", "result": None}


class ImageClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_many(
        self,
        base_url,
        api_key,
        prompt,
        size,
        *,
        count=1,
        edit_image_path=None,
        model="",
    ):
        self.calls.append({
            "baseUrl": base_url,
            "apiKey": api_key,
            "prompt": prompt,
            "size": size,
            "count": count,
            "editImagePath": edit_image_path,
            "model": model,
        })
        return [b"image-bytes"] * count


class VideoClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(
        self,
        api_key,
        prompt,
        mode,
        resolution,
        duration,
        ratio,
        image_path,
        **options,
    ):
        self.calls.append({
            "apiKey": api_key,
            "prompt": prompt,
            "mode": mode,
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
            "imagePath": image_path,
            **options,
        })
        return b"video-bytes"


class LicenseManager:
    def current_gateway_profile(self) -> dict:
        return {
            "baseUrl": "https://gateway.example/v1",
            "apiKey": "test-secret",
            "imageModel": "image-model",
            "videoDraftModel": "video-model",
        }

    def gateway_diagnosis(self) -> dict:
        return {"ok": True}


class AgentBuiltinCapabilityTests(unittest.TestCase):
    @staticmethod
    def _context(root, jobs, image_client=None, video_client=None, protected_error=None):
        from core.paths import AppPaths

        return SimpleNamespace(
            paths=AppPaths(root),
            protected_error=protected_error or (lambda _path: None),
            get_image_client=lambda: image_client,
            get_video_client=lambda: video_client,
            get_license_mgr=lambda: LicenseManager(),
            get_job_mgr=lambda: jobs,
            data_url_to_temp_file=lambda value: (value, ""),
        )

    def test_default_agent_service_connects_media_capabilities(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            jobs = RecordingJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                paths,
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                capabilities = {
                    item["name"]: item for item in service.bootstrap()["capabilities"]
                }

                self.assertTrue(capabilities["loom.media.image.generate"]["available"])
                self.assertTrue(capabilities["loom.media.video.generate"]["available"])
                self.assertTrue(capabilities["loom.media.assets.list"]["available"])
                self.assertTrue(capabilities["loom.media.asset.transfer"]["available"])
                self.assertEqual(capabilities["loom.media.asset.transfer"]["targetScope"], "matrix-write")
                self.assertTrue(capabilities["loom.phone.publish"]["available"])
                self.assertEqual(capabilities["loom.phone.publish"]["risk"], "outbound")
            finally:
                service.shutdown()

    def test_agent_can_list_existing_media_without_generating_again(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService
        from services.media_library import MediaLibrary

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            image_dir = os.path.join(paths.data_dir, "generated-images")
            os.makedirs(image_dir, exist_ok=True)
            image_path = os.path.join(image_dir, "existing-poster.png")
            with open(image_path, "wb") as handle:
                handle.write(b"existing-image")
            recorded = MediaLibrary(paths.data_dir).record(image_path, {"prompt": "招聘海报"})
            jobs = RecordingJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                paths,
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                result = service.capabilities.execute(
                    "loom.media.assets.list",
                    {"kind": "image", "limit": 10},
                )
            finally:
                service.shutdown()

        self.assertEqual(result["items"][0]["id"], recorded["id"])
        self.assertEqual(result["items"][0]["filename"], "existing-poster.png")
        self.assertEqual(jobs.submissions, [])

    def test_agent_can_transfer_existing_media_to_selected_phones(self) -> None:
        import json

        from core.paths import AppPaths
        from services.agent_service import AgentService
        from services.media_library import MediaLibrary

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "selectedDeviceId": "phone-1",
                    "devices": [
                        {"id": "phone-1", "name": "Phone One"},
                        {"id": "phone-2", "name": "Phone Two"},
                    ],
                }, handle)
            image_dir = os.path.join(paths.data_dir, "generated-images")
            os.makedirs(image_dir, exist_ok=True)
            image_path = os.path.join(image_dir, "existing-poster.png")
            with open(image_path, "wb") as handle:
                handle.write(b"existing-image")
            asset = MediaLibrary(paths.data_dir).record(image_path, {"prompt": "招聘海报"})
            jobs = RecordingJobManager()
            context = self._context(root, jobs)

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            observed: dict = {}

            def transfer(_ctx, kind, files, *, phone_snapshot=None):
                observed.update({"kind": kind, "files": files, "snapshot": phone_snapshot})
                return {
                    "status": "succeeded",
                    "message": "transferred",
                    "deviceCount": len(phone_snapshot.get("devices", [])),
                    "succeededDeviceCount": len(phone_snapshot.get("devices", [])),
                    "failedDeviceCount": 0,
                }

            service = AgentService(
                paths,
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with patch("api.routes_media._transfer_generated_media_to_phones", side_effect=transfer):
                    result = service.capabilities.execute(
                        "loom.media.asset.transfer",
                        {
                            "assetId": asset["id"],
                            "targets": {"deviceIds": ["phone-2"]},
                        },
                    )
            finally:
                service.shutdown()

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["kind"], "media-transfer")
        self.assertEqual(observed["kind"], "image")
        self.assertEqual(observed["files"][0]["path"], image_path)
        self.assertEqual([item["id"] for item in observed["snapshot"]["devices"]], ["phone-2"])

    def test_disconnected_agent_service_hides_media_from_model_catalog(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=None,
                job_manager=None,
            )
            try:
                capabilities = {
                    item["name"]: item for item in service.bootstrap()["capabilities"]
                }
                model_capability_names = {
                    item["name"]
                    for item in service.capabilities.list_capabilities(available_only=True)
                }

                self.assertFalse(capabilities["loom.media.image.generate"]["available"])
                self.assertFalse(capabilities["loom.media.video.generate"]["available"])
                self.assertFalse(capabilities["loom.phone.publish"]["available"])
                self.assertNotIn("loom.media.image.generate", model_capability_names)
                self.assertNotIn("loom.media.video.generate", model_capability_names)
                self.assertNotIn("loom.phone.publish", model_capability_names)
            finally:
                service.shutdown()

    def test_media_capabilities_publish_structured_input_schemas(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        capabilities = {
            item["name"]: item for item in CapabilityRegistry().list_capabilities()
        }
        image_schema = capabilities["loom.media.image.generate"]["inputSchema"]
        video_schema = capabilities["loom.media.video.generate"]["inputSchema"]
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        publish_schema = AgentBuiltinCapabilityProvider(
            context_factory=None,
            job_manager=None,
            matrix_factory=lambda: None,
        ).operations()["loom.phone.publish"]["inputSchema"]

        self.assertEqual(image_schema["required"], ["prompt"])
        self.assertEqual(video_schema["required"], ["prompt"])
        self.assertEqual(
            set(image_schema["properties"]),
            {"prompt", "count", "ratio", "size", "model", "editImagePath", "deviceIds", "groups", "allOnline"},
        )
        self.assertEqual(image_schema["properties"]["count"]["minimum"], 1)
        self.assertEqual(image_schema["properties"]["count"]["maximum"], 9)
        self.assertEqual(
            set(video_schema["properties"]),
            {"prompt", "model", "duration", "ratio", "imagePath", "deviceIds", "groups", "allOnline"},
        )
        self.assertEqual(
            publish_schema["required"],
            ["platform", "title", "body", "mediaPaths", "deviceId"],
        )
        self.assertEqual(
            set(publish_schema["properties"]),
            {"platform", "title", "body", "hashtags", "notes", "mediaPaths", "deviceId", "draftOnly"},
        )
        self.assertIn("不得合并到 body", publish_schema["properties"]["title"]["description"])
        self.assertIn("发布正文", publish_schema["properties"]["body"]["description"])
        self.assertIn("内部备注", publish_schema["properties"]["notes"]["description"])

        publish_operation = AgentBuiltinCapabilityProvider(
            context_factory=None,
            job_manager=None,
            matrix_factory=lambda: None,
        ).operations()["loom.phone.publish"]
        self.assertIn("title", publish_operation["description"])
        self.assertIn("draftOnly", publish_operation["description"])

    def test_image_edit_and_video_use_existing_media_pipeline_and_return_jobs(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            reference_path = os.path.join(root, "reference.png")
            with open(reference_path, "wb") as handle:
                handle.write(b"reference")
            jobs = RecordingJobManager()
            image_client = ImageClient()
            video_client = VideoClient()
            context = self._context(root, jobs, image_client, video_client)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                image = service.capabilities.execute("loom.media.image.generate", {
                    "prompt": "生成招聘海报",
                    "count": 2,
                    "ratio": "5:2",
                    "model": "image-model",
                })
                edited = service.capabilities.execute("loom.media.image.generate", {
                    "prompt": "把标题改成招聘中",
                    "editImagePath": reference_path,
                })
                video = service.capabilities.execute("loom.media.video.generate", {
                    "prompt": "让招聘海报动起来",
                    "model": "video-model",
                    "duration": 5,
                    "ratio": "9:16",
                    "imagePath": reference_path,
                })
            finally:
                service.shutdown()

            self.assertEqual(
                {key: image[key] for key in ("jobId", "kind", "status")},
                {"jobId": "job-image-1", "kind": "image", "status": "succeeded"},
            )
            self.assertEqual(
                {key: edited[key] for key in ("jobId", "kind", "status")},
                {"jobId": "job-image-2", "kind": "image", "status": "succeeded"},
            )
            self.assertEqual(
                {key: video[key] for key in ("jobId", "kind", "status")},
                {"jobId": "job-video-3", "kind": "video", "status": "succeeded"},
            )
            self.assertEqual(image["result"]["phoneTransfer"]["reason"], "no_configured_phones")
            self.assertEqual(edited["result"]["phoneTransfer"]["reason"], "no_configured_phones")
            self.assertEqual(video["result"]["phoneTransfer"]["reason"], "no_configured_phones")
            self.assertEqual(len(image["attachments"]), 2)
            self.assertEqual(image["attachments"][0]["kind"], "image")
            self.assertEqual(image["attachments"][0]["mime"], "image/png")
            self.assertTrue(image["attachments"][0]["path"].endswith(".png"))
            self.assertEqual(len(video["attachments"]), 1)
            self.assertEqual(video["attachments"][0]["kind"], "video")
            self.assertEqual(video["attachments"][0]["mime"], "video/mp4")
            self.assertEqual(image["phoneTransfer"]["reason"], "no_configured_phones")
            self.assertEqual(video["phoneTransfer"]["reason"], "no_configured_phones")
            self.assertEqual(image_client.calls[0]["count"], 2)
            self.assertIsNone(image_client.calls[0]["editImagePath"])
            self.assertEqual(image_client.calls[1]["editImagePath"], reference_path)
            self.assertEqual(video_client.calls[0]["imagePath"], reference_path)
            self.assertEqual(video_client.calls[0]["duration"], 5)
            for result in jobs.results.values():
                self.assertNotIn("images", result)
                self.assertNotIn("video", result)
            self.assertTrue(all(
                item.get("path")
                for result in jobs.results.values()
                for item in result.get("files", [])
            ))
            self.assertTrue(jobs.results["job-video-3"]["path"])

    def test_media_capability_timeouts_cover_real_image_and_video_jobs(self) -> None:
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        operations = AgentBuiltinCapabilityProvider(
            context_factory=lambda: None,
            job_manager=RecordingJobManager(),
            matrix_factory=lambda: None,
        ).operations()

        self.assertGreaterEqual(operations["loom.media.image.generate"]["timeoutSec"], 300)
        self.assertGreaterEqual(operations["loom.media.video.generate"]["timeoutSec"], 900)

    def test_media_generation_passes_all_configured_phones_to_transfer_pipeline(self) -> None:
        import json

        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "selectedDeviceId": "phone-1",
                    "devices": [
                        {"id": "phone-1", "name": "Phone One"},
                        {"id": "phone-2", "name": "Phone Two"},
                    ],
                }, handle)
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            observed: dict = {}

            def transfer(_ctx, _kind, _files, *, phone_snapshot=None):
                observed["snapshot"] = phone_snapshot
                return {
                    "status": "succeeded",
                    "message": "transferred",
                    "deviceCount": len(phone_snapshot.get("devices", [])),
                }

            service = AgentService(
                paths,
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with patch("api.routes_media._transfer_generated_media_to_phones", side_effect=transfer):
                    service.capabilities.execute("loom.media.image.generate", {"prompt": "poster"})
            finally:
                service.shutdown()

        self.assertEqual(
            [item["id"] for item in observed["snapshot"]["devices"]],
            ["phone-1", "phone-2"],
        )

    def test_media_capability_transfers_only_to_requested_phone_ids(self) -> None:
        import json

        from core.paths import AppPaths
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "selectedDeviceId": "phone-1",
                    "devices": [
                        {"id": "phone-1", "name": "Phone One"},
                        {"id": "phone-2", "name": "Phone Two"},
                    ],
                }, handle)
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            observed: dict = {}

            def transfer(_ctx, _kind, _files, *, phone_snapshot=None):
                observed["snapshot"] = phone_snapshot
                return {
                    "status": "succeeded",
                    "message": "transferred",
                    "deviceCount": len(phone_snapshot.get("devices", [])),
                }

            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )
            with patch("api.routes_media._transfer_generated_media_to_phones", side_effect=transfer):
                provider._submit_media(
                    "image",
                    {"prompt": "bracelet poster", "deviceIds": ["phone-1"]},
                )

        self.assertEqual(
            [item["id"] for item in observed["snapshot"]["devices"]],
            ["phone-1"],
        )

    def test_media_transfer_resolves_selected_group_to_its_devices(self) -> None:
        import json

        from core.paths import AppPaths
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class Matrix:
            def status(self):
                return {
                    "devices": [
                        {"deviceId": "phone-1", "online": True, "group": "招聘一组"},
                        {"deviceId": "phone-2", "online": True, "group": "招聘二组"},
                    ],
                }

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "selectedDeviceId": "phone-1",
                    "devices": [
                        {"id": "phone-1", "name": "Phone One"},
                        {"id": "phone-2", "name": "Phone Two"},
                    ],
                }, handle)
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            observed: dict = {}

            def transfer(_ctx, _kind, _files, *, phone_snapshot=None):
                observed["snapshot"] = phone_snapshot
                return {
                    "status": "succeeded",
                    "message": "transferred",
                    "deviceCount": len(phone_snapshot.get("devices", [])),
                }

            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=Matrix,
            )
            with patch("api.routes_media._transfer_generated_media_to_phones", side_effect=transfer):
                provider._submit_media(
                    "image",
                    {"prompt": "group poster", "groups": ["招聘一组"]},
                )

        self.assertEqual(
            [item["id"] for item in observed["snapshot"]["devices"]],
            ["phone-1"],
        )

    def test_media_capability_cancellation_cancels_background_job(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        with tempfile.TemporaryDirectory() as root:
            jobs = PendingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )
            token = SimpleNamespace(cancelled=True)

            with self.assertRaises(CapabilityExecutionError) as raised:
                provider._submit_media(
                    "video",
                    {"prompt": "cancel this video"},
                    cancellation_token=token,
                )

        self.assertEqual(raised.exception.code, "capability_cancelled")
        self.assertEqual(jobs.cancelled, ["job-video-pending"])

    def test_cancelled_media_job_does_not_transfer_after_generation_returns(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class CancelAfterGenerationJobs(RecordingJobManager):
            def __init__(self) -> None:
                super().__init__()
                self.cancel_requested = False

            def submit_progress(self, kind, label, target, initial_progress=None):
                job_id = f"job-{kind}-cancelled"
                self.submissions.append({"id": job_id, "kind": kind, "label": label})
                try:
                    target(job_id)
                except CapabilityExecutionError:
                    pass
                return {"id": job_id, "kind": kind, "status": "cancelled"}

            def is_cancelled(self, _job_id):
                return self.cancel_requested

            def get(self, job_id):
                return {"id": job_id, "status": "cancelled", "result": None}

        with tempfile.TemporaryDirectory() as root:
            jobs = CancelAfterGenerationJobs()
            context = self._context(root, jobs, ImageClient(), VideoClient())
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )

            def generated(*_args, **_kwargs):
                jobs.cancel_requested = True
                return {"images": ["base64"], "files": [], "count": 1}

            with patch(
                "api.routes_media._image_generate_payload",
                side_effect=generated,
            ), patch("api.routes_media._transfer_generated_media_to_phone") as transfer:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    provider._submit_media("image", {"prompt": "cancel after provider response"})

        self.assertEqual(raised.exception.code, "capability_cancelled")
        transfer.assert_not_called()

    def test_protected_media_feature_returns_stable_chinese_error_before_submit(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            jobs = RecordingJobManager()
            context = self._context(
                root,
                jobs,
                ImageClient(),
                VideoClient(),
                protected_error=lambda _path: {"code": "LICENSE_FEATURE_REQUIRED"},
            )
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.media.image.generate",
                        {"prompt": "生成图片"},
                    )
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "LICENSE_FEATURE_REQUIRED")
            self.assertEqual(str(raised.exception), "当前商业授权未开通此功能")
            self.assertEqual(jobs.submissions, [])

    def test_phone_publish_is_a_first_party_outbound_job_and_defaults_to_draft(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            media_path = os.path.join(root, "qa-card.png")
            with open(media_path, "wb") as handle:
                handle.write(b"qa-image")
            jobs = RecordingJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with patch(
                    "services.agent_builtin_capabilities.run_phone_publish",
                    return_value={"success": True, "status": "success", "draftSaved": True},
                ) as execute:
                    result = service.capabilities.execute("loom.phone.publish", {
                        "platform": "douyin",
                        "title": "LOOM QA",
                        "body": "自动发布草稿验证",
                        "mediaPaths": [media_path],
                        "deviceId": "phone-1",
                    })
            finally:
                service.shutdown()

            self.assertEqual(
                result,
                {
                    "jobId": "job-publish-1",
                    "kind": "publish",
                    "status": "succeeded",
                    "result": {"success": True, "status": "success", "draftSaved": True},
                },
            )
            execute.assert_called_once()
            publish_payload = execute.call_args.args[1]
            self.assertTrue(publish_payload["draftOnly"])
            self.assertEqual(publish_payload["platform"], "douyin")
            self.assertEqual(publish_payload["mediaPaths"], [media_path])
            self.assertEqual(jobs.results["job-publish-1"]["draftSaved"], True)

    def test_phone_publish_requires_phone_matrix_authorization_before_submit(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            media_path = os.path.join(root, "qa-card.png")
            with open(media_path, "wb") as handle:
                handle.write(b"qa-image")
            jobs = RecordingJobManager()
            checked_paths: list[str] = []

            def protected_error(path: str):
                checked_paths.append(path)
                return {"code": "LICENSE_FEATURE_REQUIRED"}

            context = self._context(root, jobs, protected_error=protected_error)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute("loom.phone.publish", {
                        "platform": "douyin",
                        "title": "LOOM QA",
                        "body": "授权检查",
                        "mediaPaths": [media_path],
                        "deviceId": "phone-1",
                    })
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "LICENSE_FEATURE_REQUIRED")
            self.assertEqual(checked_paths, ["/api/phone/publish"])
            self.assertEqual(jobs.submissions, [])

    def test_native_agent_matrix_capabilities_cannot_bypass_the_shared_gate(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            jobs = RecordingJobManager()
            context = self._context(
                root,
                jobs,
                protected_error=lambda path: {"code": "LICENSE_FEATURE_REQUIRED"}
                if path == "/api/matrix/status"
                else None,
            )
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: SimpleNamespace(status=lambda: {"devices": []}),
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute("loom.matrix.status", {})
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "LICENSE_FEATURE_REQUIRED")
            self.assertIn("手机连接页", str(raised.exception))

    def test_phone_publish_terminal_job_failure_fails_the_agent_capability(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            media_path = os.path.join(root, "qa-card.png")
            with open(media_path, "wb") as handle:
                handle.write(b"qa-image")
            jobs = RecordingJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with patch(
                    "services.agent_builtin_capabilities.run_phone_publish",
                    return_value={
                        "success": False,
                        "errorCode": "phone_publish_semantic_failure",
                        "error": "抖音应用当前未登录",
                    },
                ):
                    with self.assertRaises(CapabilityExecutionError) as raised:
                        service.capabilities.execute("loom.phone.publish", {
                            "platform": "douyin",
                            "title": "LOOM QA",
                            "body": "自动发布草稿验证",
                            "mediaPaths": [media_path],
                            "deviceId": "phone-1",
                        })
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "phone_publish_semantic_failure")
            self.assertIn("未登录", str(raised.exception))

    def test_phone_publish_requires_existing_media_before_job_submit(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        with tempfile.TemporaryDirectory() as root:
            jobs = RecordingJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute("loom.phone.publish", {
                        "platform": "douyin",
                        "title": "LOOM QA",
                        "body": "自动发布草稿验证",
                        "mediaPaths": [os.path.join(root, "missing.png")],
                        "deviceId": "phone-1",
                    })
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "publish_media_missing")
            self.assertEqual(jobs.submissions, [])

    def test_phone_publish_process_omits_empty_optional_arguments(self) -> None:
        from services.agent_builtin_capabilities import run_phone_publish

        with tempfile.TemporaryDirectory() as root:
            scripts_dir = os.path.join(root, "scripts")
            os.makedirs(scripts_dir)
            script_path = os.path.join(scripts_dir, "openclaw-publish-phone.mjs")
            node_path = os.path.join(root, "node.exe")
            media_path = os.path.join(root, "qa-card.png")
            for path in (script_path, node_path, media_path):
                with open(path, "wb") as handle:
                    handle.write(b"test")
            context = SimpleNamespace(paths=SimpleNamespace(
                base_path=root,
                node_exe=node_path,
                script_roots=(scripts_dir,),
                scripts_dir=scripts_dir,
            ))

            with patch("api.routes_phone.phone_process_env", return_value={}), patch(
                "services.agent_builtin_capabilities.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout='{"status":"success","draftOnly":true}',
                    stderr="",
                ),
            ) as execute:
                result = run_phone_publish(context, {
                    "platform": "douyin",
                    "title": "LOOM QA",
                    "body": "",
                    "hashtags": "",
                    "notes": "",
                    "mediaPaths": [media_path],
                    "draftOnly": True,
                })

            args = execute.call_args.args[0]
            self.assertIn("--title", args)
            self.assertNotIn("--body", args)
            self.assertNotIn("--hashtags", args)
            self.assertNotIn("--notes", args)
            self.assertIn("--draft-only", args)
            self.assertEqual(result["success"], True)

    def test_phone_publish_process_rejects_explicit_business_failure_answer(self) -> None:
        from services.agent_builtin_capabilities import run_phone_publish

        with tempfile.TemporaryDirectory() as root:
            scripts_dir = os.path.join(root, "scripts")
            os.makedirs(scripts_dir)
            script_path = os.path.join(scripts_dir, "openclaw-publish-phone.mjs")
            node_path = os.path.join(root, "node.exe")
            media_path = os.path.join(root, "qa-card.png")
            for path in (script_path, node_path, media_path):
                with open(path, "wb") as handle:
                    handle.write(b"test")
            context = SimpleNamespace(paths=SimpleNamespace(
                base_path=root,
                node_exe=node_path,
                script_roots=(scripts_dir,),
                scripts_dir=scripts_dir,
            ))

            with patch("api.routes_phone.phone_process_env", return_value={}), patch(
                "services.agent_builtin_capabilities.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout=(
                            '{"status":"success","draftOnly":true,'
                            '"answer":"Task completed: 任务执行受阻：抖音需要登录才能进行创作/发布操作。"}'
                        ),
                        stderr="",
                    ),
            ):
                result = run_phone_publish(context, {
                    "platform": "douyin",
                    "mediaPaths": [media_path],
                    "draftOnly": True,
                })

            self.assertEqual(result["success"], False)
            self.assertEqual(result["errorCode"], "phone_publish_semantic_failure")
            self.assertIn("任务执行受阻", result["error"])

    def test_phone_publish_process_rejects_blocked_login_answer(self) -> None:
        from services.agent_builtin_capabilities import run_phone_publish

        with tempfile.TemporaryDirectory() as root:
            scripts_dir = os.path.join(root, "scripts")
            os.makedirs(scripts_dir)
            script_path = os.path.join(scripts_dir, "openclaw-publish-phone.mjs")
            node_path = os.path.join(root, "node.exe")
            media_path = os.path.join(root, "qa-card.png")
            for path in (script_path, node_path, media_path):
                with open(path, "wb") as handle:
                    handle.write(b"test")
            context = SimpleNamespace(paths=SimpleNamespace(
                base_path=root,
                node_exe=node_path,
                script_roots=(scripts_dir,),
                scripts_dir=scripts_dir,
            ))

            with patch("api.routes_phone.phone_process_env", return_value={}), patch(
                "services.agent_builtin_capabilities.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=(
                        '{"status":"success","success":true,"draftOnly":true,'
                        '"answer":"Task completed: 任务 blocked - 抖音未登录边界\\n\\n待人工处理：需要先登录抖音账号"}'
                    ),
                    stderr="",
                ),
            ):
                result = run_phone_publish(context, {
                    "platform": "douyin",
                    "mediaPaths": [media_path],
                    "draftOnly": True,
                })

            self.assertEqual(result["success"], False)
            self.assertEqual(result["errorCode"], "phone_publish_semantic_failure")
            self.assertIn("任务 blocked", result["error"])

    def test_missing_bridge_services_fail_before_media_submit(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        provider = AgentBuiltinCapabilityProvider(
            context_factory=None,
            job_manager=None,
            matrix_factory=lambda: None,
        )
        operation = provider.operations()["loom.media.video.generate"]

        self.assertIsNone(operation["executor"])

        with self.assertRaises(CapabilityExecutionError) as raised:
            provider._submit_media("video", {
                "prompt": "生成视频",
            })

        self.assertEqual(raised.exception.code, "capability_unavailable")
        self.assertEqual(str(raised.exception), "媒体生成服务尚未就绪")


if __name__ == "__main__":
    unittest.main()
