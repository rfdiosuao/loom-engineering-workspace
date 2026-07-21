import os
import unittest

from PIL import Image


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DASHBOARD_PAGE = os.path.join(REPO_ROOT, "src", "components", "dashboard", "DashboardPage.tsx")
HERO_ASSET = os.path.join(REPO_ROOT, "src", "assets", "overview-hero-openclaw-4k.webp")


class DashboardHeroContractTests(unittest.TestCase):
    def test_dashboard_uses_the_original_design_as_a_4k_asset(self) -> None:
        with open(DASHBOARD_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("overview-hero-openclaw-4k.webp", source)
        self.assertIn("data-dashboard-matrix-hero", source)

    def test_dashboard_reuses_the_persisted_component_snapshot_on_remount(self) -> None:
        with open(DASHBOARD_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("loadCachedComponentSnapshot", source)
        self.assertIn("components === null", source)
        self.assertNotIn("useState<ComponentSnapshot | null>(null)", source)
        self.assertIn('aria-label="开始配置"', source)
        self.assertIn('aria-label="查看可做的事"', source)
        self.assertIn("让 AI 带着手机干活", source)

        self.assertTrue(os.path.exists(HERO_ASSET))
        with Image.open(HERO_ASSET) as image:
            self.assertGreaterEqual(image.width, 3840)
            self.assertGreaterEqual(image.height, 2160)


if __name__ == "__main__":
    unittest.main()
