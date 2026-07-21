from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from api.routes_cli import _catalog, _is_read_only


class CliRoutePolicyTests(unittest.TestCase):
    def test_catalog_exposes_only_current_core_capabilities(self) -> None:
        command_ids = {item["id"] for item in _catalog()}

        self.assertIn("phone:agent", command_ids)
        self.assertIn("desktop:agent", command_ids)
        self.assertNotIn("phone:publish", command_ids)

    def test_desktop_screenshot_is_read_only(self) -> None:
        self.assertTrue(_is_read_only(["screenshot", "--json"], []))

    def test_desktop_start_requires_confirmation(self) -> None:
        self.assertFalse(_is_read_only(["start", "--json"], []))

    def test_phone_agent_observe_run_is_read_only_only_in_observe_mode(self) -> None:
        self.assertTrue(_is_read_only(["run", "--prompt", "读取屏幕", "--mode", "observe", "--json"], [], "phone:agent"))
        self.assertFalse(_is_read_only(["run", "--prompt", "点击按钮", "--mode", "safe", "--json"], [], "phone:agent"))


if __name__ == "__main__":
    unittest.main()
