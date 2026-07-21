from __future__ import annotations

import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADMIN_HTML = os.path.join(ROOT, "license_server", "admin_console.html")
PUBLIC_HTML = os.path.join(ROOT, "license_server", "public_home.html")


class AdminConsoleContractTests(unittest.TestCase):
    def test_admin_console_uses_luming_brand_and_cookie_session(self) -> None:
        with open(ADMIN_HTML, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("麓鸣授权与客户管理", source)
        self.assertIn('credentials: "same-origin"', source)
        self.assertNotIn('localStorage.setItem("openclawAdminSession"', source)
        self.assertNotIn('localStorage.getItem("openclawAdminSession")', source)

    def test_destructive_actions_use_custom_typed_confirmation(self) -> None:
        with open(ADMIN_HTML, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn('id="dangerConfirmDialog"', source)
        self.assertIn("function confirmDanger", source)
        self.assertIn("requiredText", source)
        self.assertIn('confirmation: "DELETE"', source)
        self.assertIn('confirmation: "CLEAR"', source)
        self.assertIn('confirmation: "UNBIND"', source)
        self.assertNotIn("confirm(", source)

    def test_public_home_is_a_real_commercial_entry(self) -> None:
        self.assertTrue(os.path.isfile(PUBLIC_HTML), PUBLIC_HTML)
        with open(PUBLIC_HTML, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("麓鸣商业授权中心", source)
        self.assertIn("{{PURCHASE_URL}}", source)
        self.assertIn("{{SUPPORT_URL}}", source)
        self.assertIn("/admin", source)
        self.assertIn("logo.ico", source)


if __name__ == "__main__":
    unittest.main()
