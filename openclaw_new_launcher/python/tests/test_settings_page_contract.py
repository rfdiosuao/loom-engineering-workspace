from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_PAGE = os.path.join(REPO_ROOT, "src", "components", "settings", "SettingsPage.tsx")
THEME_FILE = os.path.join(REPO_ROOT, "src", "theme", "default.ts")
APP_STORE = os.path.join(REPO_ROOT, "src", "stores", "appStore.ts")


class SettingsPageContractTests(unittest.TestCase):
    def test_settings_page_exposes_real_update_actions(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("updateApi", source)
        self.assertIn("handleCheckUpdate", source)
        self.assertIn("handleInstallUpdate", source)
        self.assertIn("updateStatus", source)

    def test_update_copy_describes_verified_launcher_app_updates(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("LOOM 应用更新", source)
        self.assertIn("当前版本", source)
        self.assertIn("最新版本", source)
        self.assertIn("SHA256", source)
        self.assertNotIn("智能体运行时更新", source)

    def test_install_update_is_locked_until_an_update_is_found(self) -> None:
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("showConfirm", source)
        self.assertIn("disabled={Boolean(updateBusy) || updateStatus?.hasUpdate !== true}", source)

    def test_theme_modes_are_not_locked_to_light(self) -> None:
        with open(THEME_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("export type BuiltinThemeMode = 'light' | 'dark' | 'system'", source)
        self.assertIn("resolveThemeMode(mode)", source)
        self.assertIn("mode === 'dark' ? DARK_THEME : LIGHT_THEME", source)

    def test_builtin_themes_use_readable_muted_text_colors(self) -> None:
        with open(THEME_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("text_subtle: '#766B5C'", source)
        self.assertIn("text_subtle: '#A89E8B'", source)
        self.assertNotIn("text_subtle: '#9D907D'", source)
        self.assertNotIn("text_subtle: '#766F61'", source)

    def test_language_selection_is_persisted_in_app_store(self) -> None:
        with open(APP_STORE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("language: AppLanguage", source)
        self.assertIn("setLanguage: (language: AppLanguage)", source)
        self.assertIn("persistAppLanguage(language)", source)


if __name__ == "__main__":
    unittest.main()
