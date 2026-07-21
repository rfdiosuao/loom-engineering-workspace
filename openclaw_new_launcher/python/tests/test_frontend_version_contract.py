from __future__ import annotations

import json
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_JSON = os.path.join(REPO_ROOT, "package.json")
VERSION_FILE = os.path.join(REPO_ROOT, "src", "version.ts")
DASHBOARD_PAGE = os.path.join(REPO_ROOT, "src", "components", "dashboard", "DashboardPage.tsx")
SETTINGS_PAGE = os.path.join(REPO_ROOT, "src", "components", "settings", "SettingsPage.tsx")


class FrontendVersionContractTests(unittest.TestCase):
    def test_frontend_version_comes_from_package_json(self) -> None:
        with open(PACKAGE_JSON, "r", encoding="utf-8") as handle:
            package_version = json.load(handle)["version"]

        with open(VERSION_FILE, "r", encoding="utf-8") as handle:
            version_source = handle.read()
        with open(DASHBOARD_PAGE, "r", encoding="utf-8") as handle:
            dashboard_source = handle.read()
        with open(SETTINGS_PAGE, "r", encoding="utf-8") as handle:
            settings_source = handle.read()

        self.assertIn("import packageJson from '../package.json'", version_source)
        self.assertIn("export const APP_VERSION = packageJson.version", version_source)
        self.assertIn("APP_VERSION", dashboard_source)
        self.assertIn("APP_VERSION", settings_source)
        self.assertNotIn(f"'{package_version}'", dashboard_source)
        self.assertNotIn(f">{package_version}<", settings_source)


if __name__ == "__main__":
    unittest.main()
