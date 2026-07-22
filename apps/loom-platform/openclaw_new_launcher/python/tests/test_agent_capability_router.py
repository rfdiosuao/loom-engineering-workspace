from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class AgentCapabilityRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capabilities = [
            {"name": "loom.media.image.generate", "domain": "media", "available": True},
            {"name": "loom.media.video.generate", "domain": "media", "available": True},
            {"name": "loom.phone.publish", "domain": "phone", "available": True},
            {"name": "loom.matrix.dispatch", "domain": "matrix", "available": True},
            {"name": "loom.cli.account.current", "domain": "account", "available": True},
            {"name": "loom.cli.logs.tail", "domain": "diagnostics", "available": True},
            {"name": "loom.settings.update.check", "domain": "settings", "available": True},
            {"name": "loom.settings.update.install", "domain": "settings", "available": True},
            {"name": "loom.license.current", "domain": "license", "available": True},
            {"name": "loom.license.activate", "domain": "license", "available": True},
            {"name": "loom.skill.resume-screener", "domain": "custom", "available": True},
        ]

    def test_media_and_phone_cross_domain_request_is_focused(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成一张海报，然后发布到 phone-1 的小红书草稿"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.media.image.generate", names)
        self.assertIn("loom.phone.publish", names)
        self.assertIn("loom.cli.logs.tail", names)
        self.assertNotIn("loom.cli.account.current", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["media", "phone"])

    def test_matrix_request_does_not_send_media_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "给招聘一组的多台手机下发矩阵任务"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")

    def test_ambiguous_or_catalog_request_uses_full_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        ambiguous, ambiguous_meta = route_capabilities({"prompt": "继续"}, self.capabilities)
        catalog, catalog_meta = route_capabilities({"prompt": "列出你的全部能力"}, self.capabilities)

        self.assertEqual(len(ambiguous), len(self.capabilities))
        self.assertEqual(ambiguous_meta["reason"], "ambiguous_intent")
        self.assertEqual(len(catalog), len(self.capabilities))
        self.assertEqual(catalog_meta["reason"], "broad_capability_intent")

    def test_selection_repair_restores_full_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成图片"},
            self.capabilities,
            {"toolSelectionRepairAttempts": 1},
        )

        self.assertEqual(len(selected), len(self.capabilities))
        self.assertEqual(metadata["mode"], "full")
        self.assertEqual(metadata["reason"], "selection_repair")

    def test_update_request_includes_settings_update_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "检查麓鸣更新，如果有新版本就安装"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.settings.update.check", names)
        self.assertIn("loom.settings.update.install", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertIn("settings", metadata["domains"])

    def test_nested_single_device_scope_focuses_phone_tools_for_short_followup(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "继续",
                "requestScope": {
                    "status": "resolved",
                    "targets": {"deviceIds": ["phone-1"]},
                },
            },
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.phone.publish", names)
        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["phone"])

    def test_nested_all_online_scope_focuses_matrix_tools_for_short_followup(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "开始执行",
                "requestScope": {
                    "status": "resolved",
                    "targets": {"allOnline": True},
                },
            },
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["matrix"])

    def test_license_request_focuses_license_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "查看商业授权状态，如果未激活就使用授权码激活"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.license.current", names)
        self.assertIn("loom.license.activate", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertIn("license", metadata["domains"])

    def test_common_mobile_app_launch_focuses_phone_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in ("打开QQ", "打开闲鱼", "启动淘宝"):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn("loom.phone.publish", names)
                self.assertNotIn("loom.media.image.generate", names)
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("phone", metadata["domains"])

    def test_explicit_capability_hint_survives_unrelated_domain_routing(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "分析这张图片",
                "capabilityHints": ["loom.skill.resume-screener", "loom.skill.not-connected"],
            },
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.skill.resume-screener", names)
        self.assertNotIn("loom.skill.not-connected", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["hinted"], ["loom.skill.resume-screener"])


if __name__ == "__main__":
    unittest.main()
