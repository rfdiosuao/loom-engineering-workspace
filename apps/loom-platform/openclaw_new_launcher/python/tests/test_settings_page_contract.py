from __future__ import annotations

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_PAGE = os.path.join(REPO_ROOT, "src", "components", "settings", "SettingsPage.tsx")
UPDATE_CENTER = os.path.join(REPO_ROOT, "src", "components", "update", "UpdateCenter.tsx")
THEME_FILE = os.path.join(REPO_ROOT, "src", "theme", "default.ts")
APP_STORE = os.path.join(REPO_ROOT, "src", "stores", "appStore.ts")


def _relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2])


def _contrast_ratio(foreground: str, background: str) -> float:
    foreground_luminance = _relative_luminance(foreground)
    background_luminance = _relative_luminance(background)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _theme_colors(source: str, theme_name: str) -> dict[str, str]:
    theme_start = source.index(f"export const {theme_name}")
    colors_start = source.index("colors: {", theme_start)
    colors_end = source.index("\n  },", colors_start)
    block = source[colors_start:colors_end]
    return dict(re.findall(r"^\s+(\w+):\s+'(#[0-9A-Fa-f]{6})'", block, re.MULTILINE))


class SettingsPageContractTests(unittest.TestCase):
    def test_settings_page_opens_the_single_global_update_center(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("requestUpdateCenterOpen", source)
        self.assertIn("onClick={requestUpdateCenterOpen}", source)
        self.assertIn("APP_VERSION", source)
        self.assertNotIn("handleInstallUpdate", source)

    def test_update_copy_describes_verified_launcher_app_updates(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("APP_DISPLAY_NAME", source)
        self.assertIn("应用更新", source)
        self.assertIn("当前版本", source)
        self.assertIn("最新版本", source)
        self.assertIn("SHA256", source)
        self.assertNotIn("智能体运行时更新", source)

    def test_install_action_only_appears_in_the_available_update_phase(self) -> None:
        with open(UPDATE_CENTER, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("phase === 'available'", source)
        self.assertIn("onClick={() => void startDownload()}", source)
        self.assertIn("立即更新", source)
        self.assertNotIn("showConfirm", source)

    def test_theme_modes_are_not_locked_to_light(self) -> None:
        with open(THEME_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("export type BuiltinThemeMode = 'light' | 'dark' | 'system'", source)
        self.assertIn("resolveThemeMode(mode)", source)
        self.assertIn("mode === 'dark' ? DARK_THEME : LIGHT_THEME", source)

    def test_builtin_theme_semantic_text_pairs_meet_wcag_aa(self) -> None:
        with open(THEME_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        required_pairs = (
            ("text", "surface"),
            ("text_muted", "surface"),
            ("text_subtle", "surface"),
            ("disabled_text", "disabled"),
            ("accent_ink", "accent"),
            ("info_ink", "info_soft"),
            ("success_ink", "success_soft"),
            ("warning_ink", "warning_soft"),
            ("danger_ink", "danger_soft"),
            ("selected_ink", "selected"),
        )
        for theme_name in ("LIGHT_THEME", "DARK_THEME"):
            colors = _theme_colors(source, theme_name)
            for foreground_key, background_key in required_pairs:
                self.assertIn(foreground_key, colors, f"{theme_name} missing {foreground_key}")
                self.assertIn(background_key, colors, f"{theme_name} missing {background_key}")
                ratio = _contrast_ratio(colors[foreground_key], colors[background_key])
                self.assertGreaterEqual(
                    ratio,
                    4.5,
                    f"{theme_name} {foreground_key}/{background_key} contrast is {ratio:.2f}:1",
                )

    def test_language_selection_is_persisted_in_app_store(self) -> None:
        with open(APP_STORE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("language: AppLanguage", source)
        self.assertIn("setLanguage: (language: AppLanguage)", source)
        self.assertIn("persistAppLanguage(language)", source)

    def test_about_page_describes_the_candidate_product_without_demo_copy(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("演示稳定版", source)
        self.assertNotIn("第一版演示", source)
        self.assertNotIn("demo-stable", source)
        self.assertIn("Skill 中心", source)
        self.assertIn("共享模板", source)


if __name__ == "__main__":
    unittest.main()
