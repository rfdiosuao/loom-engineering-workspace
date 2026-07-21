from __future__ import annotations

import http.cookiejar
import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.newapi_account_manager import DEFAULT_PHONE_MODEL, DEFAULT_TEXT_MODEL, NewApiAccountManager
from core.paths import AppPaths
from core.storage import read_json, write_json


class NewApiAccountManagerTests(unittest.TestCase):
    def test_build_session_prefers_required_defaults_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            session = manager._build_session(
                "https://api.heang.top",
                "user@example.com",
                "sk-test-token",
                {"data": {"id": "u1", "email": "user@example.com", "group": "default"}},
                {"data": {"id": "u1", "email": "user@example.com", "quota": 100, "used_quota": 10}},
                {"source": "supplied"},
                ["other-text", DEFAULT_TEXT_MODEL, "agnes-2.0-flash", "seedream-image", "agnes-video-v2.0"],
                http.cookiejar.CookieJar(),
            )

            self.assertEqual(session["gatewayDefaultModel"], DEFAULT_TEXT_MODEL)
            self.assertEqual(session["gateway"]["defaultModel"], DEFAULT_TEXT_MODEL)
            self.assertEqual(session["phoneAgent"]["model"], DEFAULT_PHONE_MODEL)
            self.assertEqual(session["newApi"]["modelClasses"]["image"], ["seedream-image"])
            self.assertEqual(session["newApi"]["modelClasses"]["video"], ["agnes-video-v2.0"])

    def test_logout_clears_only_managed_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            manager = NewApiAccountManager(paths)
            write_json(paths.member_session_file, {"source": "newapi_account"})
            write_json(paths.auth_profiles, {
                "models": {
                    "primary": "member_gateway",
                    "providers": {
                        "member_gateway": {"managedBy": "newapi_account"},
                        "heang_gateway": {"managedBy": "heang_account"},
                        "manual": {"baseUrl": "https://manual.example/v1"},
                    },
                },
            })
            write_json(paths.image_config, {"managedBy": "newapi_account", "model": "seedream-image"})
            write_json(paths.video_config, {"managedBy": "heang_account", "model": "agnes-video-v2.0"})

            self.assertTrue(manager.logout())

            profiles = read_json(paths.auth_profiles, {})
            providers = profiles["models"]["providers"]
            self.assertNotIn("member_gateway", providers)
            self.assertNotIn("heang_gateway", providers)
            self.assertIn("manual", providers)
            self.assertEqual(profiles["models"]["primary"], "manual")
            self.assertEqual(read_json(paths.image_config, {"x": 1}), {})
            self.assertEqual(read_json(paths.video_config, {"x": 1}), {})

    def test_sync_targets_writes_managed_runtime_configs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            manager = NewApiAccountManager(paths)
            session = manager._build_session(
                "https://api.heang.top",
                "user@example.com",
                "sk-test-token",
                {"data": {"id": "u1", "email": "user@example.com"}},
                {"data": {"id": "u1", "email": "user@example.com"}},
                {"source": "supplied"},
                [DEFAULT_TEXT_MODEL, "seedream-image", "agnes-video-v2.0"],
                http.cookiejar.CookieJar(),
            )

            results = manager.sync_targets(session, targets=("image", "video", "desktop", "phone"))

            self.assertTrue(all(item["ok"] for item in results))
            self.assertEqual(read_json(paths.image_config, {})["model"], "seedream-image")
            self.assertEqual(read_json(paths.video_config, {})["model"], "agnes-video-v2.0")
            desktop = read_json(os.path.join(paths.launcher_dir, "desktop-agent.json"), {})
            self.assertEqual(desktop["provider"]["model"], DEFAULT_TEXT_MODEL)
            phone = read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {})
            self.assertEqual(phone["llm"]["model"], DEFAULT_PHONE_MODEL)


if __name__ == "__main__":
    unittest.main()
