from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE_ROOT = os.path.dirname(REPO_ROOT)


class CanonicalNewApiDefaultsContractTests(unittest.TestCase):
    def _read(self, *parts: str) -> str:
        path = os.path.join(REPO_ROOT, *parts)
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_all_launcher_defaults_use_canonical_cloudflare_domain(self) -> None:
        sources = {
            "account": self._read("src", "components", "license", "LicensePage.tsx"),
            "api_config": self._read("src", "components", "dialogs", "ApiConfigDialog.tsx"),
            "creative": self._read("src", "components", "creative", "CreativeMediaPage.tsx"),
            "agent_prompt": self._read("src", "components", "agentAccess", "agentPrompt.ts"),
            "providers": self._read("python", "core", "constants.py"),
            "phone_wire": self._read("python", "core", "wire_config.py"),
            "templates": self._read("python", "core", "acquisition_templates.py"),
        }

        for name, source in sources.items():
            with self.subTest(source=name):
                self.assertIn("api.heang.top", source)

        for name in ("api_config", "creative", "agent_prompt", "providers", "phone_wire", "templates"):
            with self.subTest(no_redirecting_default=name):
                self.assertNotIn("https://api-cn.heang.top", sources[name])

    def test_newapi_bridge_default_uses_canonical_cloudflare_domain(self) -> None:
        bridge_path = os.path.join(WORKSPACE_ROOT, "server", "openclaw_newapi_bridge.py")
        with open(bridge_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn('"https://api.heang.top/v1"', source)
        self.assertNotIn('"https://api-cn.heang.top/v1"', source)


if __name__ == "__main__":
    unittest.main()
