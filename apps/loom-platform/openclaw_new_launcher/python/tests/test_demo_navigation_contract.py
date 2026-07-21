from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_FILE = os.path.join(REPO_ROOT, "src", "App.tsx")


class DemoNavigationContractTests(unittest.TestCase):
    def test_phone_page_keeps_phone_nav_item_active(self) -> None:
        with open(APP_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("NAV_PARENT_BY_PAGE", source)
        self.assertIn("models: 'license'", source)
        self.assertIn("const activeNavPage = NAV_PARENT_BY_PAGE[visiblePage] || visiblePage;", source)
        self.assertNotIn("visiblePage === 'phone' ? 'capabilities'", source)


if __name__ == "__main__":
    unittest.main()
