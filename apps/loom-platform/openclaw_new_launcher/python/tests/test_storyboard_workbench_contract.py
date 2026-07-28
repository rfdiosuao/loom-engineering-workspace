from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_ROOT = os.path.join(REPO_ROOT, "src")

CREATIVE_PAGE = os.path.join(SRC_ROOT, "components", "creative", "CreativeMediaPage.tsx")
SETTINGS_PAGE = os.path.join(SRC_ROOT, "components", "settings", "SettingsPage.tsx")
WORKBENCH = os.path.join(SRC_ROOT, "components", "storyboard", "StoryboardWorkbench.tsx")
STEPS = os.path.join(SRC_ROOT, "components", "storyboard", "storyboardSteps.ts")
ASSET_FILE = os.path.join(SRC_ROOT, "components", "storyboard", "StoryboardAssetPanel.tsx")
VIDEO_FILE = os.path.join(SRC_ROOT, "components", "storyboard", "StoryboardVideoPanel.tsx")
TYPES_FILE = os.path.join(SRC_ROOT, "components", "storyboard", "storyboardTypes.ts")
API_FILE = os.path.join(SRC_ROOT, "services", "storyboardApi.ts")
ROUTES_FILE = os.path.join(REPO_ROOT, "python", "api", "routes_storyboard.py")
SERVICE_FILE = os.path.join(REPO_ROOT, "python", "services", "storyboard.py")


class StoryboardContractTests(unittest.TestCase):
    def setUp(self) -> None:
        with open(CREATIVE_PAGE, "r", encoding="utf-8") as handle:
            self.creative = handle.read()
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            self.settings = handle.read()
        with open(WORKBENCH, "r", encoding="utf-8") as handle:
            self.workbench = handle.read()
        with open(STEPS, "r", encoding="utf-8") as handle:
            self.steps = handle.read()
        with open(API_FILE, "r", encoding="utf-8") as handle:
            self.api = handle.read()
        with open(ROUTES_FILE, "r", encoding="utf-8") as handle:
            self.routes = handle.read()
        with open(SERVICE_FILE, "r", encoding="utf-8") as handle:
            self.service = handle.read()
        with open(ASSET_FILE, "r", encoding="utf-8") as handle:
            self.asset_panel = handle.read()
        with open(VIDEO_FILE, "r", encoding="utf-8") as handle:
            self.video_panel = handle.read()
        with open(TYPES_FILE, "r", encoding="utf-8") as handle:
            self.types = handle.read()

    def test_creative_page_has_storyboard_tab(self) -> None:
        self.assertIn("data-creative-tab-storyboard", self.creative)
        self.assertIn("StoryboardWorkbench", self.creative)
        self.assertIn("'storyboard'", self.creative)

    def test_settings_page_has_import_row(self) -> None:
        self.assertIn("storyboardApi.importParamConfig", self.settings)
        self.assertIn("全案九步参数配置", self.settings)

    def test_workbench_has_step_bar_and_project_sidebar(self) -> None:
        self.assertIn("data-storyboard-workbench", self.workbench)
        self.assertIn("data-storyboard-step-bar", self.workbench)
        self.assertIn("data-storyboard-projects-sidebar", self.workbench)
        self.assertIn("storyboardApi.generate", self.workbench)

    def test_steps_define_all_nine_modules(self) -> None:
        for module in ("模块一", "模块二", "模块三", "模块四", "模块五", "模块六", "模块七", "模块八", "模块九"):
            self.assertIn(module, self.steps)
        self.assertIn("generateStage", self.steps)
        self.assertIn("'script'", self.steps)
        self.assertIn("'storyboard'", self.steps)
        self.assertIn("'videoPrompt'", self.steps)
        self.assertIn("category: '全案板块'", self.steps)
        self.assertNotIn("对标账号库", self.steps)

    def test_api_wrappers_match_routes(self) -> None:
        self.assertIn("/api/storyboard/param-config", self.api)
        self.assertIn("/api/storyboard/import-param-config", self.api)
        self.assertIn("/api/storyboard/generate", self.api)
        self.assertIn("/api/storyboard/param-config", self.routes)
        self.assertIn("/api/storyboard/import-param-config", self.routes)
        self.assertIn("/api/storyboard/generate", self.routes)

    def test_service_has_backfill_and_three_system_templates(self) -> None:
        self.assertIn("DEFAULT_OPTION_HINTS", self.service)
        self.assertIn("GENERIC_HINT_TEMPLATE", self.service)
        self.assertIn("SCRIPT_SYSTEM_TEMPLATE", self.service)
        self.assertIn("STORYBOARD_SYSTEM_TEMPLATE", self.service)
        self.assertIn("VIDEO_PROMPT_SYSTEM_TEMPLATE", self.service)
        self.assertIn("build_context", self.service)
        self.assertIn("extract_asset_prompts", self.service)

    def test_generated_assets_are_persisted_by_real_shot_number(self) -> None:
        self.assertIn("generatedAssets", self.workbench)
        self.assertIn("shotNumbers", self.workbench)
        self.assertIn("shotNum", self.workbench)
        self.assertIn("generatedAssets", self.types)
        self.assertIn("shotNumbers", self.asset_panel)
        self.assertIn("convertFileSrc", self.asset_panel)

    def test_storyboard_results_use_tauri_asset_urls(self) -> None:
        self.assertIn("convertFileSrc", self.video_panel)
        self.assertNotIn("asset://localhost/", self.video_panel)
        self.assertIn("generatedAssets", self.video_panel)


if __name__ == "__main__":
    unittest.main()
