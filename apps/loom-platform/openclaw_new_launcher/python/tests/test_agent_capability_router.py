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


if __name__ == "__main__":
    unittest.main()
