from __future__ import annotations

import importlib
import datetime
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON_ROOT = os.path.join(REPO_ROOT, "python")
if PYTHON_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_ROOT)

REGISTRY_FILE = os.path.join(REPO_ROOT, "src", "features", "registry.ts")
PAGES_FILE = os.path.join(REPO_ROOT, "src", "features", "pages.tsx")
API_FILE = os.path.join(REPO_ROOT, "src", "services", "api.ts")
SIDEBAR_FILE = os.path.join(REPO_ROOT, "src", "components", "sidebar", "Sidebar.tsx")
CREATIVE_PAGE = os.path.join(REPO_ROOT, "src", "components", "creative", "CreativeMediaPage.tsx")
MEDIA_LIBRARY_PANEL = os.path.join(REPO_ROOT, "src", "components", "creative", "MediaLibraryPanel.tsx")
BRIDGE_FILE = os.path.join(REPO_ROOT, "python", "bridge.py")
TAURI_CONFIG = os.path.join(REPO_ROOT, "src-tauri", "tauri.conf.json")
TAURI_LIB = os.path.join(REPO_ROOT, "src-tauri", "src", "lib.rs")
AGENT_BUILTIN_CAPABILITIES = os.path.join(
    REPO_ROOT,
    "python",
    "services",
    "agent_builtin_capabilities.py",
)


class CreativeMediaUiContractTests(unittest.TestCase):
    def test_creative_page_is_first_class_nav_entry_and_phone_is_hidden(self) -> None:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(PAGES_FILE, "r", encoding="utf-8") as handle:
            pages = handle.read()
        with open(SIDEBAR_FILE, "r", encoding="utf-8") as handle:
            sidebar = handle.read()

        definition = next(line for line in registry.splitlines() if "key: 'creative'" in line)
        self.assertNotIn("requiresLicense", definition)
        self.assertRegex(registry, r"key:\s*'phone'[\s\S]+?visible:\s*HIDDEN")
        self.assertIn("CreativeMediaPage", pages)
        self.assertIn("creative: CreativeMediaPage", pages)
        self.assertIn("'creative'", sidebar)

    def test_creative_page_exposes_image_video_config_and_running_feedback(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        for marker in (
            "data-creative-media-page",
            "data-creative-tab-image",
            "data-creative-tab-video",
            "mediaApi.config",
            "mediaApi.saveConfig",
            "mediaApi.testConfig",
            "imageApi.submit",
            "videoApi.submit",
            "jobApi.get",
            "activeJob",
            "generationPulse",
            "生成中",
            "自定义 API",
        ):
            self.assertIn(marker, source)

        self.assertIn("type=\"password\"", source)
        self.assertNotIn("console.log(customApiKey", source)
        self.assertNotIn("console.log(videoApiKey", source)
        self.assertIn('<option value="agnes">', source)
        self.assertIn('Agnes / OpenAI', source)

    def test_creative_page_keeps_image_and_video_jobs_independent(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("activeJobs", source)
        self.assertIn("imageRunning", source)
        self.assertIn("videoRunning", source)
        self.assertIn("pollRefs", source)
        self.assertIn("rememberedCreativeJobs", source)
        self.assertNotIn("const generationRunning = Boolean(activeJob", source)
        self.assertIn("disabled={imageRunning}", source)
        self.assertIn("disabled={videoRunning}", source)

    def test_creative_page_exposes_reference_modes_ratios_and_persistent_library(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()
        for component_name in ("ReferenceImagePicker.tsx", "MediaLibraryPanel.tsx"):
            component_file = os.path.join(REPO_ROOT, "src", "components", "creative", component_name)
            with open(component_file, "r", encoding="utf-8") as handle:
                source += handle.read()
        presets_file = os.path.join(REPO_ROOT, "src", "components", "creative", "mediaPresets.ts")
        with open(presets_file, "r", encoding="utf-8") as handle:
            presets = handle.read()

        for marker in (
            "data-creative-mode-t2i",
            "data-creative-mode-i2i",
            "data-creative-mode-t2v",
            "data-creative-mode-i2v",
            "data-reference-image-picker",
            "data-current-generation-results",
            "data-local-media-library",
            "mediaApi.assets",
            "mediaApi.reveal",
            "mediaApi.deleteAsset",
            "用作图生图",
            "用作图生视频",
        ):
            self.assertIn(marker, source)

        for ratio in ("1:1", "3:4", "4:3", "9:16", "16:9", "5:2"):
            self.assertIn(f"ratio: '{ratio}'", presets)
        self.assertNotIn("自定义宽高", source)

    def test_creative_image_results_preserve_selected_ratio_in_preview(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("cssAspectRatio", source)
        self.assertIn("style={{ aspectRatio: cssAspectRatio(", source)
        self.assertIn("object-contain", source)
        self.assertIn("data-media-preview-error", source)
        self.assertIn("预览加载失败，文件仍保存在本地", source)
        self.assertNotIn("aspect-square w-full object-cover", source)

    def test_creative_page_defaults_image_generation_to_gpt_image_2(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("const DEFAULT_IMAGE_MODEL = 'gpt-image-2'", source)
        self.assertIn("React.useState(DEFAULT_IMAGE_MODEL)", source)
        self.assertIn("snapshot.image?.model || DEFAULT_IMAGE_MODEL", source)
        self.assertIn('placeholder="gpt-image-2"', source)
        self.assertIn("留空使用 provider 默认模型", source)
        self.assertNotIn("React.useState('wanx2.1-t2v-turbo')", source)

    def test_creative_api_key_config_is_compact_collapsible(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-creative-config-details", source)
        self.assertIn("<summary", source)
        self.assertIn("展开配置", source)
        self.assertIn('<div className="mt-4 grid gap-3">', source)
        self.assertLess(source.count("<Input type=\"password\""), 3)

    def test_api_client_has_media_config_contract(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("export interface MediaConfigSnapshot", source)
        self.assertIn("export const mediaApi", source)
        self.assertIn("api('/api/media/config')", source)
        self.assertIn("api('/api/media/config', 'POST'", source)
        self.assertIn("api('/api/media/test', 'POST'", source)
        self.assertIn("assets:", source)
        self.assertIn("reveal:", source)
        self.assertIn("deleteAsset:", source)

    def test_packaged_media_previews_enable_a_narrow_runtime_asset_protocol_scope(self) -> None:
        with open(TAURI_CONFIG, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        with open(TAURI_LIB, "r", encoding="utf-8") as handle:
            tauri_source = handle.read()

        asset_protocol = config["app"]["security"]["assetProtocol"]
        self.assertTrue(asset_protocol["enable"])
        self.assertEqual(asset_protocol["scope"], [])
        self.assertIn("configure_media_asset_scope(app)?", tauri_source)
        self.assertIn("app.asset_protocol_scope()", tauri_source)
        self.assertIn('root.join("data").join("generated-images")', tauri_source)
        self.assertIn('root.join("data").join("videos")', tauri_source)
        self.assertIn("scope.allow_directory(&directory, false)", tauri_source)
        self.assertNotIn("scope.allow_directory(&root", tauri_source)
        cargo_path = os.path.join(REPO_ROOT, "src-tauri", "Cargo.toml")
        with open(cargo_path, "r", encoding="utf-8") as handle:
            cargo_source = handle.read()
        self.assertIn('features = ["protocol-asset"]', cargo_source)

    def test_local_library_exposes_real_image_and_video_filters(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()
        with open(MEDIA_LIBRARY_PANEL, "r", encoding="utf-8") as handle:
            panel_source = handle.read()

        self.assertIn("const [assetKind, setAssetKind]", page_source)
        self.assertIn("mediaApi.assets(assetKind === 'all' ? undefined : assetKind", page_source)
        self.assertIn("data-media-library-filter", panel_source)
        for label in ("全部", "图片", "视频"):
            self.assertIn(label, panel_source)

    def test_creative_results_surface_phone_transfer_state(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("phoneTransfer?: PhoneTransferState", source)
        self.assertIn("data-phone-transfer-state", source)
        self.assertIn("activePhoneTransfer", source)


class CreativeMediaBackendContractTests(unittest.TestCase):
    def test_image_gateway_524_is_reported_as_retryable_upstream_timeout(self) -> None:
        from api.routes_media import _image_generation_failure

        failure = _image_generation_failure(RuntimeError("HTTP 524"))

        self.assertEqual(failure["errorCode"], "image_provider_gateway_timeout")
        self.assertTrue(failure["retryable"])
        self.assertIn("素材库", failure["error"])

    def test_empty_image_config_exposes_gpt_image_2_as_the_real_default(self) -> None:
        routes_media = importlib.import_module("api.routes_media")
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = SimpleNamespace(paths=SimpleNamespace(
                image_config=os.path.join(temp_dir, "image.json"),
                video_config=os.path.join(temp_dir, "video.json"),
                data_dir=temp_dir,
            ))

            snapshot = routes_media._media_config_snapshot(ctx)

        self.assertEqual(snapshot["image"]["model"], "gpt-image-2")

    def test_native_agent_media_capabilities_reuse_shared_generation_pipeline(self) -> None:
        with open(AGENT_BUILTIN_CAPABILITIES, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("_image_generate_payload", source)
        self.assertIn("_video_generate_payload", source)
        self.assertIn("_async_media_job_result", source)
        self.assertIn("_configured_phone_snapshot", source)
        self.assertNotIn("_selected_phone_snapshot(context)", source)
        self.assertIn('"source": str(payload.get("source") or "agent")', source)

    def test_generation_never_overwrites_assets_created_in_the_same_second(self) -> None:
        routes_media = importlib.import_module("api.routes_media")

        class FrozenDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                value = cls(2026, 7, 16, 12, 0, 0)
                return value.replace(tzinfo=tz) if tz else value

        payloads = [b"first-image", b"second-image"]

        class ImageClient:
            def generate_many(self, *_args, **_kwargs):
                return [payloads.pop(0)]

        license_mgr = SimpleNamespace(current_gateway_profile=lambda: {})
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = SimpleNamespace(
                paths=SimpleNamespace(
                    image_config=os.path.join(temp_dir, "image.json"),
                    video_config=os.path.join(temp_dir, "video.json"),
                    data_dir=temp_dir,
                ),
                get_image_client=lambda: ImageClient(),
                get_license_mgr=lambda: license_mgr,
            )
            body = {
                "baseUrl": "https://example.com/v1",
                "apiKey": "test-key",
                "prompt": "same second",
                "source": "ui",
            }
            with mock.patch.object(routes_media.datetime, "datetime", FrozenDatetime):
                first = routes_media._image_generate_payload(ctx, body)
                second = routes_media._image_generate_payload(ctx, body)

            first_path = first["files"][0]["path"]
            second_path = second["files"][0]["path"]
            self.assertNotEqual(first_path, second_path)
            with open(first_path, "rb") as handle:
                self.assertEqual(handle.read(), b"first-image")
            with open(second_path, "rb") as handle:
                self.assertEqual(handle.read(), b"second-image")

    def test_async_media_job_result_keeps_paths_without_embedding_large_base64(self) -> None:
        routes_media = importlib.import_module("api.routes_media")
        oversized = "A" * (9 * 1024 * 1024)

        image_result = routes_media._compact_media_job_result({
            "images": [oversized],
            "files": [{"path": "D:/LOOM/data/generated-images/example.png"}],
            "count": 1,
            "ratio": "5:2",
        })
        video_result = routes_media._compact_media_job_result({
            "video": oversized,
            "path": "D:/LOOM/data/videos/example.mp4",
            "size": 7 * 1024 * 1024,
            "mime": "video/mp4",
        })

        self.assertNotIn("images", image_result)
        self.assertNotIn("video", video_result)
        self.assertEqual(image_result["files"][0]["path"], "D:/LOOM/data/generated-images/example.png")
        self.assertEqual(video_result["path"], "D:/LOOM/data/videos/example.mp4")
        self.assertLess(len(json.dumps(image_result)), 100_000)
        self.assertLess(len(json.dumps(video_result)), 100_000)

    def test_generation_records_persistent_mode_ratio_model_and_source(self) -> None:
        routes_media = importlib.import_module("api.routes_media")

        class ImageClient:
            def generate_many(self, *_args, **_kwargs):
                return [b"image-bytes"]

        class VideoClient:
            def generate(self, *_args, **_kwargs):
                return b"video-bytes"

        license_mgr = SimpleNamespace(current_gateway_profile=lambda: {})
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = SimpleNamespace(
                image_config=os.path.join(temp_dir, "image.json"),
                video_config=os.path.join(temp_dir, "video.json"),
                data_dir=temp_dir,
            )
            ctx = SimpleNamespace(
                paths=paths,
                get_image_client=lambda: ImageClient(),
                get_video_client=lambda: VideoClient(),
                get_license_mgr=lambda: license_mgr,
            )

            image = routes_media._image_generate_payload(ctx, {
                "baseUrl": "https://example.com/v1",
                "apiKey": "test-key",
                "prompt": "生成海报",
                "model": "image-model",
                "ratio": "5:2",
                "size": "2560x1024",
                "source": "ui",
            })
            video = routes_media._video_generate_payload(ctx, {
                "apiKey": "test-key",
                "prompt": "让画面动起来",
                "model": "video-model",
                "mode": "i2v",
                "ratio": "9:16",
                "imagePath": os.path.join(temp_dir, "reference.png"),
                "source": "cli",
            })

            with open(f"{image['files'][0]['path']}.json", "r", encoding="utf-8") as handle:
                image_meta = json.load(handle)
            with open(f"{video['path']}.json", "r", encoding="utf-8") as handle:
                video_meta = json.load(handle)

            self.assertEqual(image_meta["ratio"], "5:2")
            self.assertEqual(image_meta["mode"], "t2i")
            self.assertEqual(image_meta["model"], "image-model")
            self.assertEqual(image_meta["source"], "ui")
            self.assertEqual(video_meta["ratio"], "9:16")
            self.assertEqual(video_meta["mode"], "i2v")
            self.assertEqual(video_meta["model"], "video-model")
            self.assertEqual(video_meta["source"], "cli")

    def test_agnes_video_model_overrides_stale_dashscope_provider(self) -> None:
        routes_media = importlib.import_module("api.routes_media")
        calls: list[dict] = []

        class VideoClient:
            def generate(self, *_args, **kwargs):
                calls.append(kwargs)
                return b"video-bytes"

        license_mgr = SimpleNamespace(current_gateway_profile=lambda: {})
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = SimpleNamespace(
                image_config=os.path.join(temp_dir, "image.json"),
                video_config=os.path.join(temp_dir, "video.json"),
                data_dir=temp_dir,
            )
            ctx = SimpleNamespace(
                paths=paths,
                get_video_client=lambda: VideoClient(),
                get_license_mgr=lambda: license_mgr,
            )

            result = routes_media._video_generate_payload(ctx, {
                "apiBase": "https://api.example.com/v1",
                "apiKey": "test-key",
                "providerId": "dashscope",
                "prompt": "LOOM demo",
                "model": "agnes-video-v2.0",
            })

            self.assertEqual(calls[0]["provider_id"], "agnes")
            with open(f"{result['path']}.json", "r", encoding="utf-8") as handle:
                video_meta = json.load(handle)
            self.assertEqual(video_meta["providerId"], "agnes")

    def test_image_generation_maps_ratio_to_size_before_saved_fallback(self) -> None:
        routes_media = importlib.import_module("api.routes_media")

        calls: list[str] = []

        class ImageClient:
            def generate_many(self, _base_url, _api_key, _prompt, size, **_kwargs):
                calls.append(size)
                return [b"image-bytes"]

        license_mgr = SimpleNamespace(current_gateway_profile=lambda: {})
        with tempfile.TemporaryDirectory() as temp_dir:
            image_config = os.path.join(temp_dir, "image.json")
            with open(image_config, "w", encoding="utf-8") as handle:
                json.dump({
                    "baseUrl": "https://example.com/v1",
                    "apiKey": "test-key",
                    "model": "image-model",
                    "size": "1024x1024",
                }, handle)
            paths = SimpleNamespace(
                image_config=image_config,
                video_config=os.path.join(temp_dir, "video.json"),
                data_dir=temp_dir,
            )
            ctx = SimpleNamespace(
                paths=paths,
                get_image_client=lambda: ImageClient(),
                get_license_mgr=lambda: license_mgr,
            )

            image = routes_media._image_generate_payload(ctx, {
                "prompt": "wide banner",
                "ratio": "5:2",
                "size": "1024x1024",
                "source": "ui",
            })

            self.assertEqual(calls, ["2560x1024"])
            with open(f"{image['files'][0]['path']}.json", "r", encoding="utf-8") as handle:
                image_meta = json.load(handle)
            self.assertEqual(image_meta["ratio"], "5:2")
            self.assertEqual(image_meta["generationSize"], "2560x1024")
            self.assertNotIn("size", image_meta)

    def test_media_config_is_sanitized_and_generation_uses_saved_fallback(self) -> None:
        routes_media = importlib.import_module("api.routes_media")
        with tempfile.TemporaryDirectory() as temp_dir:
            image_config = os.path.join(temp_dir, "imgapi_config.json")
            video_config = os.path.join(temp_dir, "video_config.json")
            paths = SimpleNamespace(
                image_config=image_config,
                video_config=video_config,
                data_dir=temp_dir,
            )
            ctx = SimpleNamespace(paths=paths)

            snapshot = routes_media._save_media_config(ctx, {
                "image": {
                    "baseUrl": "https://example.com/v1",
                    "apiKey": "TEST_IMAGE_SECRET",
                    "model": "gpt-image-1",
                },
                "video": {
                    "providerId": "custom",
                    "apiBase": "https://video.example.com",
                    "apiKey": "TEST_VIDEO_SECRET",
                    "model": "video-model",
                },
            })

            self.assertTrue(snapshot["image"]["hasApiKey"])
            self.assertTrue(snapshot["video"]["hasApiKey"])
            public_snapshot = json.dumps(snapshot)
            self.assertNotIn("TEST_IMAGE_SECRET", public_snapshot)
            self.assertNotIn("TEST_VIDEO_SECRET", public_snapshot)

            with open(image_config, "r", encoding="utf-8") as handle:
                saved_image = json.load(handle)
            with open(video_config, "r", encoding="utf-8") as handle:
                saved_video = json.load(handle)
            self.assertEqual(saved_image["apiKey"], "TEST_IMAGE_SECRET")
            self.assertEqual(saved_video["apiKey"], "TEST_VIDEO_SECRET")

            self.assertEqual(
                routes_media._image_config_fallback(ctx)["apiKey"],
                "TEST_IMAGE_SECRET",
            )
            self.assertEqual(
                routes_media._video_config_fallback(ctx)["apiKey"],
                "TEST_VIDEO_SECRET",
            )

    def test_bridge_does_not_clear_video_config_on_startup(self) -> None:
        with open(BRIDGE_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("_reset_transient_video_config()", source)
        self.assertNotIn("write_json(paths.video_config, {})", source)

    def test_image_client_accepts_base_url_with_or_without_v1(self) -> None:
        image_api = importlib.import_module("services.image_api")

        self.assertEqual(
            image_api._openai_endpoint("https://api.heang.top", "/v1/images/generations"),
            "https://api.heang.top/v1/images/generations",
        )
        self.assertEqual(
            image_api._openai_endpoint("https://api.heang.top/v1", "/v1/images/generations"),
            "https://api.heang.top/v1/images/generations",
        )


if __name__ == "__main__":
    unittest.main()
