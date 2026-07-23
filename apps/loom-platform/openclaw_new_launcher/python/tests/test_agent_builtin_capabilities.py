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
            transferred_same_file = os.path.samefile(observed["files"][0]["path"], image_path)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["kind"], "media-transfer")
        self.assertEqual(observed["kind"], "image")
        self.assertTrue(transferred_same_file)
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
            self.assertEqual(image["result"]["phoneTransfer"]["reason"], "local_only")
            self.assertEqual(edited["result"]["phoneTransfer"]["reason"], "local_only")
            self.assertEqual(video["result"]["phoneTransfer"]["reason"], "local_only")
            self.assertEqual(len(image["attachments"]), 2)
            self.assertEqual(image["attachments"][0]["kind"], "image")
            self.assertEqual(image["attachments"][0]["mime"], "image/png")
            self.assertTrue(image["attachments"][0]["path"].endswith(".png"))
            self.assertEqual(len(video["attachments"]), 1)
            self.assertEqual(video["attachments"][0]["kind"], "video")
            self.assertEqual(video["attachments"][0]["mime"], "video/mp4")
            self.assertEqual(image["phoneTransfer"]["reason"], "local_only")
            self.assertEqual(video["phoneTransfer"]["reason"], "local_only")
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

    def test_media_generation_without_explicit_target_stays_local(self) -> None:
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
                    "status": "skipped",
                    "reason": phone_snapshot.get("reason"),
                    "message": "saved locally",
                    "attempted": False,
                    "deviceCount": 0,
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
                        "loom.media.image.generate",
                        {"prompt": "poster"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(observed["snapshot"]["devices"], [])
        self.assertEqual(observed["snapshot"]["reason"], "local_only")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["phoneTransfer"]["reason"], "local_only")

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

    def test_media_generation_rejects_unknown_phone_before_generation(self) -> None:
        import json

        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "devices": [{"id": "phone-1", "name": "Phone One"}],
                }, handle)
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )

            with patch("api.routes_media._image_generate_payload") as generate:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    provider._submit_media(
                        "image",
                        {"prompt": "poster", "deviceIds": ["phone-404"]},
                    )

        self.assertEqual(raised.exception.code, "phone_target_not_found")
        self.assertEqual(jobs.submissions, [])
        generate.assert_not_called()

    def test_media_generation_rejects_unknown_group_before_generation(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class Matrix:
            def status(self):
                return {
                    "devices": [
                        {
                            "deviceId": "phone-1",
                            "online": True,
                            "group": "招聘一组",
                        },
                    ],
                }

        with tempfile.TemporaryDirectory() as root:
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=Matrix,
            )

            with patch("api.routes_media._image_generate_payload") as generate:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    provider._submit_media(
                        "image",
                        {"prompt": "poster", "groups": ["不存在的分组"]},
                    )

        self.assertEqual(raised.exception.code, "phone_target_not_found")
        self.assertEqual(jobs.submissions, [])
        generate.assert_not_called()

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

    def test_media_group_resolution_does_not_expand_group_inputs_quadratically(self) -> None:
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        with tempfile.TemporaryDirectory() as root:
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())
            observed_groups: list[list[str]] = []
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )

            def resolve(groups, *, all_online):
                observed_groups.append(list(groups))
                self.assertFalse(all_online)
                return ["phone-1"]

            provider._resolve_media_target_device_ids = resolve
            with patch(
                "api.routes_media._image_generate_payload",
                return_value={"files": [], "count": 0},
            ), patch(
                "api.routes_media._configured_phone_snapshot",
                return_value={
                    "devices": [{"id": "phone-1"}],
                    "reason": "",
                    "missingDeviceIds": [],
                },
            ), patch(
                "api.routes_media._async_media_job_result",
                return_value={
                    "success": True,
                    "files": [],
                    "phoneTransfer": {"reason": "no_configured_phones"},
                },
            ):
                provider._submit_media(
                    "image",
                    {"prompt": "group poster", "groups": ["招聘一组", "招聘二组"]},
                )

        self.assertEqual(observed_groups, [["招聘一组", "招聘二组"]])

    def test_media_transfer_failure_preserves_attachment_and_blocks_regeneration(self) -> None:
        import json

        from core.paths import AppPaths
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        with tempfile.TemporaryDirectory() as root:
            generated_path = os.path.join(root, "generated.png")
            with open(generated_path, "wb") as handle:
                handle.write(b"generated")
            paths = AppPaths(root)
            os.makedirs(paths.launcher_dir, exist_ok=True)
            with open(os.path.join(paths.launcher_dir, "phone-agents.json"), "w", encoding="utf-8") as handle:
                json.dump({"devices": [{"id": "phone-1", "name": "Phone One"}]}, handle)
            jobs = RecordingJobManager()
            context = self._context(root, jobs, ImageClient(), VideoClient())

            def read_json(path, default):
                if not os.path.isfile(path):
                    return default
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)

            context.read_json = read_json
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: None,
            )
            with patch(
                "api.routes_media._image_generate_payload",
                return_value={"files": [{"path": generated_path}], "count": 1},
            ), patch(
                "api.routes_media._async_media_job_result",
                return_value={
                    "success": False,
                    "status": "partial_failure",
                    "errorCode": "media_transfer_failed",
                    "message": "图片已生成，但一台手机传输失败",
                    "files": [{"path": generated_path, "filename": "generated.png", "mime": "image/png"}],
                    "phoneTransfer": {
                        "status": "failed",
                        "reason": "phone_upload_partial_failure",
                        "succeededDeviceCount": 1,
                        "failedDeviceCount": 1,
                    },
                },
            ):
                result = provider._submit_media(
                    "image",
                    {"prompt": "generate once", "deviceIds": ["phone-1"]},
                )

        self.assertEqual(result["status"], "partial_failure")
        self.assertFalse(result["success"])
        self.assertFalse(result["retryable"])
        self.assertFalse(result["regenerationAllowed"])
        self.assertEqual(result["attachments"][0]["path"], generated_path)
        self.assertEqual(result["phoneTransfer"]["reason"], "phone_upload_partial_failure")

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

    def test_background_job_timeouts_are_indeterminate_and_never_auto_retry(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        cases = (
            ("image", "media_job_timeout", "_wait_for_media_job"),
            ("transfer", "media_transfer_timeout", "_wait_for_media_job"),
            ("publish", "publish_job_timeout", "_wait_for_publish_job"),
        )
        for kind, expected_code, method_name in cases:
            with self.subTest(kind=kind):
                jobs = PendingJobManager()
                provider = AgentBuiltinCapabilityProvider(
                    context_factory=lambda: object(),
                    job_manager=jobs,
                    matrix_factory=lambda: object(),
                )
                with patch(
                    "services.agent_builtin_capabilities.time.monotonic",
                    side_effect=[0.0, 10_000.0],
                ):
                    with self.assertRaises(CapabilityExecutionError) as raised:
                        if method_name == "_wait_for_media_job":
                            provider._wait_for_media_job("job-timeout", kind=kind)
                        else:
                            provider._wait_for_publish_job("job-timeout")

                self.assertEqual(raised.exception.code, expected_code)
                self.assertFalse(raised.exception.recoverable)
                self.assertTrue(raised.exception.outcome_indeterminate)
                self.assertTrue(raised.exception.execution_may_continue)
                self.assertEqual(jobs.cancelled, ["job-timeout"])

    def test_background_job_status_disconnects_preserve_may_continue_semantics(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class DisconnectedStatusJobs:
            def get(self, _job_id):
                raise ConnectionResetError("status channel closed")

        provider = AgentBuiltinCapabilityProvider(
            context_factory=lambda: object(),
            job_manager=DisconnectedStatusJobs(),
            matrix_factory=lambda: object(),
        )
        cases = (
            ("image", "media_job_status_unknown", "_wait_for_media_job"),
            ("transfer", "media_transfer_status_unknown", "_wait_for_media_job"),
            ("publish", "publish_job_status_unknown", "_wait_for_publish_job"),
        )
        for kind, expected_code, method_name in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(CapabilityExecutionError) as raised:
                    if method_name == "_wait_for_media_job":
                        provider._wait_for_media_job("job-disconnected", kind=kind)
                    else:
                        provider._wait_for_publish_job("job-disconnected")

                self.assertEqual(raised.exception.code, expected_code)
                self.assertFalse(raised.exception.recoverable)
                self.assertTrue(raised.exception.outcome_indeterminate)
                self.assertTrue(raised.exception.execution_may_continue)

    def test_background_job_submit_disconnects_are_not_treated_as_safe_to_retry(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class AcceptedThenDisconnectedJobs:
            def __init__(self) -> None:
                self.accepted: list[tuple[str, str]] = []

            def submit_progress(self, kind, label, _target, initial_progress=None):
                self.accepted.append((kind, label))
                raise ConnectionResetError("submission response lost")

        with tempfile.TemporaryDirectory() as root:
            media_path = os.path.join(root, "publish.png")
            with open(media_path, "wb") as handle:
                handle.write(b"image")
            jobs = AcceptedThenDisconnectedJobs()
            context = self._context(root, jobs, ImageClient(), VideoClient())
            provider = AgentBuiltinCapabilityProvider(
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: object(),
            )

            with self.assertRaises(CapabilityExecutionError) as media_error:
                provider._submit_media("image", {"prompt": "generate once"})
            with self.assertRaises(CapabilityExecutionError) as publish_error:
                provider._submit_phone_publish({
                    "platform": "douyin",
                    "title": "LOOM QA",
                    "body": "publish once",
                    "mediaPaths": [media_path],
                    "deviceId": "phone-1",
                })

        self.assertEqual(media_error.exception.code, "media_job_submission_unknown")
        self.assertTrue(media_error.exception.execution_may_continue)
        self.assertFalse(media_error.exception.recoverable)
        self.assertEqual(publish_error.exception.code, "publish_job_submission_unknown")
        self.assertTrue(publish_error.exception.execution_may_continue)
        self.assertFalse(publish_error.exception.recoverable)
        self.assertEqual(
            [kind for kind, _label in jobs.accepted],
            ["image", "publish"],
        )

    def test_cancel_receipt_disconnect_keeps_the_original_indeterminate_error(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        class CancelReceiptDisconnectedJobs(PendingJobManager):
            def cancel(self, _job_id):
                raise ConnectionResetError("cancel response lost")

        jobs = CancelReceiptDisconnectedJobs()
        provider = AgentBuiltinCapabilityProvider(
            context_factory=lambda: object(),
            job_manager=jobs,
            matrix_factory=lambda: object(),
        )
        token = SimpleNamespace(cancelled=True)

        with self.assertRaises(CapabilityExecutionError) as raised:
            provider._wait_for_media_job(
                "job-cancel-disconnected",
                kind="image",
                cancellation_token=token,
            )

        self.assertEqual(raised.exception.code, "capability_cancelled")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

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
            jobs = SimpleNamespace(
                submit_progress=lambda *_args, **_kwargs: {"id": "job-never"},
                cancel_matching=lambda _predicate: [],
            )
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
                matrix_factory=lambda: SimpleNamespace(
                    status=lambda: {"devices": []},
                    dispatch=lambda _payload: {"campaignId": "campaign-never"},
                    cancel=lambda campaign_id: {"campaignId": campaign_id, "cancelled": True},
                    retry_failed=lambda campaign_id, _payload: {
                        "campaignId": campaign_id,
                        "retried": True,
                    },
                ),
            )
            try:
                cases = {
                    "loom.matrix.status": {},
                    "loom.matrix.dispatch": {
                        "prompt": "inspect",
                        "targets": {"deviceIds": ["phone-1"]},
                    },
                    "loom.matrix.screenshot": {"deviceId": "phone-1"},
                    "loom.matrix.cancel": {"campaignId": "campaign-1"},
                    "loom.matrix.retry": {"campaignId": "campaign-1"},
                }
                for capability_name, payload in cases.items():
                    with self.subTest(capability=capability_name):
                        with self.assertRaises(CapabilityExecutionError) as raised:
                            service.capabilities.execute(capability_name, payload)
                        self.assertEqual(raised.exception.code, "LICENSE_FEATURE_REQUIRED")
            finally:
                service.shutdown()

            self.assertEqual(raised.exception.code, "LICENSE_FEATURE_REQUIRED")
            self.assertIn("手机连接页", str(raised.exception))

    def test_matrix_job_submit_disconnect_is_indeterminate_and_may_continue(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        class SubmitDisconnectJobManager:
            def submit_progress(self, *_args, **_kwargs):
                raise ConnectionResetError("submit response lost")

        matrix = SimpleNamespace(
            dispatch=lambda _payload: {
                "campaignId": "campaign-submitted",
                "status": "queued",
                "missions": [],
            },
        )
        with tempfile.TemporaryDirectory() as root:
            jobs = SubmitDisconnectJobManager()
            context = self._context(root, jobs)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: matrix,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.dispatch",
                        {
                            "prompt": "inspect",
                            "targets": {"deviceIds": ["phone-1"]},
                        },
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_job_submission_unknown")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

    def test_matrix_job_submit_without_job_id_is_not_reported_as_completed(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        jobs = SimpleNamespace(
            submit_progress=lambda *_args, **_kwargs: {"status": "queued"},
        )
        matrix = SimpleNamespace(
            dispatch=lambda _payload: {
                "campaignId": "campaign-missing-job-id",
                "status": "queued",
                "missions": [],
            },
        )
        with tempfile.TemporaryDirectory() as root:
            context = self._context(root, jobs)
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                context_factory=lambda: context,
                job_manager=jobs,
                matrix_factory=lambda: matrix,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.dispatch",
                        {
                            "prompt": "inspect",
                            "targets": {"deviceIds": ["phone-1"]},
                        },
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_job_submission_unknown")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

    def test_matrix_retry_without_failed_tasks_is_not_reported_as_completed(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.agent_policy import AgentPolicyEngine
        from core.paths import AppPaths
        from services.agent_service import AgentService

        matrix = SimpleNamespace(
            retry_failed=lambda campaign_id, _payload: {
                "retried": False,
                "campaignId": campaign_id,
                "reason": "没有失败设备任务",
            },
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.retry",
                        {"campaignId": "campaign-no-failures"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_retry_not_started")
        self.assertTrue(raised.exception.recoverable)
        self.assertFalse(raised.exception.outcome_indeterminate)
        self.assertFalse(raised.exception.execution_may_continue)

    def test_matrix_cancel_false_result_is_not_reported_as_completed(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        matrix = SimpleNamespace(
            status=lambda campaign_id=None: {
                "campaigns": [{
                    "campaignId": campaign_id or "campaign-running",
                    "status": "running",
                }],
            },
            cancel=lambda _campaign_id: {
                "cancelled": False,
                "campaignId": "campaign-running",
            },
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: matrix,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.cancel",
                        {"campaignId": "campaign-running"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_cancel_not_applied")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

    def test_matrix_cancel_false_result_does_not_cancel_local_jobs(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        local_cancel_calls: list[object] = []
        jobs = SimpleNamespace(
            cancel_matching=lambda predicate: local_cancel_calls.append(predicate),
        )
        matrix = SimpleNamespace(
            status=lambda campaign_id=None: {
                "campaigns": [{
                    "campaignId": campaign_id or "campaign-running",
                    "status": "running",
                }],
            },
            cancel=lambda campaign_id: {
                "cancelled": False,
                "campaignId": campaign_id,
            },
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                job_manager=jobs,
                matrix_factory=lambda: matrix,
            )
            try:
                with self.assertRaises(CapabilityExecutionError):
                    service.capabilities.execute(
                        "loom.matrix.cancel",
                        {"campaignId": "campaign-running"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(local_cancel_calls, [])

    def test_matrix_attachment_counts_succeeded_device_tasks_as_completed(self) -> None:
        from services.agent_builtin_capabilities import AgentBuiltinCapabilityProvider

        attachment = AgentBuiltinCapabilityProvider._matrix_attachment(
            {
                "campaignId": "campaign-counts",
                "status": "completed",
                "missions": [{
                    "deviceTasks": [
                        {"deviceId": "phone-1", "status": "succeeded"},
                        {"deviceId": "phone-2", "status": "completed"},
                        {"deviceId": "phone-3", "status": "needs_human"},
                    ],
                }],
            },
            {"id": "job-counts"},
        )

        self.assertEqual(attachment["counts"], {
            "total": 3,
            "completed": 2,
            "failed": 1,
            "running": 0,
        })

    def test_matrix_cancel_without_authoritative_status_is_indeterminate(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.paths import AppPaths
        from services.agent_service import AgentService

        class Matrix:
            def __init__(self) -> None:
                self.status_calls = 0

            def status(self, campaign_id=None):
                self.status_calls += 1
                if self.status_calls == 1:
                    return {
                        "campaigns": [{
                            "campaignId": campaign_id,
                            "status": "running",
                        }],
                    }
                return {"campaigns": []}

            def cancel(self, campaign_id):
                return {"cancelled": True, "campaignId": campaign_id}

        matrix = Matrix()
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: matrix,
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.cancel",
                        {"campaignId": "campaign-status-lost"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_cancel_status_unknown")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

    def test_matrix_status_queries_requested_campaign_beyond_default_window(self) -> None:
        from core.paths import AppPaths
        from services.agent_service import AgentService

        requested: list[str | None] = []

        def status(campaign_id=None):
            requested.append(campaign_id)
            return {
                "campaigns": (
                    [{"campaignId": campaign_id, "status": "failed"}]
                    if campaign_id
                    else []
                ),
            }

        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: SimpleNamespace(status=status),
            )
            try:
                result = service.capabilities.execute(
                    "loom.matrix.status",
                    {"campaignId": "campaign-old"},
                )
            finally:
                service.shutdown()

        self.assertEqual(requested, ["campaign-old"])
        self.assertEqual(result["campaigns"][0]["campaignId"], "campaign-old")

    def test_matrix_retry_indeterminate_result_is_not_immediately_retryable(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.agent_policy import AgentPolicyEngine
        from core.paths import AppPaths
        from services.agent_service import AgentService

        matrix = SimpleNamespace(
            retry_failed=lambda campaign_id, _payload: {
                "retried": False,
                "campaignId": campaign_id,
                "code": "matrix_retry_blocked_indeterminate",
                "reason": "Check the actual device task status before retrying.",
                "retryable": False,
                "outcomeIndeterminate": True,
                "executionMayContinue": True,
            },
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.retry",
                        {"campaignId": "campaign-indeterminate"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_retry_blocked_indeterminate")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

    def test_matrix_retry_missing_new_task_is_indeterminate_not_completed(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.agent_policy import AgentPolicyEngine
        from core.paths import AppPaths
        from services.agent_service import AgentService

        matrix = SimpleNamespace(
            retry_failed=lambda campaign_id, _payload: {
                "retried": True,
                "retryOf": campaign_id,
            },
        )
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(
                AppPaths(root),
                runtime=UnavailableRuntime(),
                matrix_factory=lambda: matrix,
                policy=AgentPolicyEngine(approval_mode="weak"),
            )
            try:
                with self.assertRaises(CapabilityExecutionError) as raised:
                    service.capabilities.execute(
                        "loom.matrix.retry",
                        {"campaignId": "campaign-missing-task"},
                    )
            finally:
                service.shutdown()

        self.assertEqual(raised.exception.code, "matrix_retry_result_invalid")
        self.assertFalse(raised.exception.recoverable)
        self.assertTrue(raised.exception.outcome_indeterminate)
        self.assertTrue(raised.exception.execution_may_continue)

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
            self.assertFalse(raised.exception.recoverable)
            self.assertTrue(raised.exception.outcome_indeterminate)
            self.assertFalse(raised.exception.execution_may_continue)

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
