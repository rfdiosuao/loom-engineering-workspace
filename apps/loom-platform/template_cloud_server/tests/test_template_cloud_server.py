from __future__ import annotations

import json
import os
import tempfile
import unittest

from template_cloud_server.server import TemplateStore, can_write_template, create_response, decode_payload, require_bearer


class TemplateCloudServerTests(unittest.TestCase):
    def test_create_response_saves_template_and_increments_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TemplateStore(os.path.join(temp_dir, "templates.json"))
            first = create_response(
                store,
                {
                    "schema": "loom.acquisition_template.v1",
                    "templateId": "beauty-local",
                    "name": "美业本地获客模板",
                    "industry": "美业",
                    "platforms": ["douyin"],
                    "safetyPolicy": {"sendMode": "draft_only", "manualConfirm": True},
                },
                public_base="https://api-cn.heang.top",
            )
            second = create_response(
                store,
                {
                    "templateId": "beauty-local",
                    "name": "美业本地获客模板 v2",
                    "industry": "美业",
                    "platforms": ["douyin", "xiaohongshu"],
                },
                public_base="https://api-cn.heang.top",
            )

            self.assertEqual(first["templateId"], "beauty-local")
            self.assertEqual(first["version"], 1)
            self.assertEqual(first["url"], "https://api-cn.heang.top/template-admin/?templateId=beauty-local")
            self.assertEqual(second["version"], 2)
            saved = store.list_templates()["templates"]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["name"], "美业本地获客模板 v2")
            self.assertEqual(saved[0]["version"], 2)
            self.assertEqual(saved[0]["uploadCount"], 2)

    def test_create_response_redacts_sensitive_fields_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TemplateStore(os.path.join(temp_dir, "templates.json"))
            create_response(
                store,
                {
                    "templateId": "decor",
                    "name": "装修模板",
                    "token": "secret-token",
                    "nested": {"apiKey": "secret-key", "safe": "ok"},
                },
                public_base="",
            )
            raw = json.dumps(store.list_templates(), ensure_ascii=False)

            self.assertNotIn("secret-token", raw)
            self.assertNotIn("secret-key", raw)
            self.assertIn("装修模板", raw)
            self.assertIn("ok", raw)

    def test_require_bearer_accepts_exact_token_only(self) -> None:
        self.assertTrue(require_bearer("Bearer abc123", "abc123"))
        self.assertFalse(require_bearer("Bearer wrong", "abc123"))
        self.assertFalse(require_bearer("", "abc123"))
        self.assertFalse(require_bearer("abc123", "abc123"))

    def test_public_upload_allows_writes_but_not_admin_reads(self) -> None:
        self.assertTrue(can_write_template("", "admin-token", allow_public_upload=True))
        self.assertTrue(can_write_template("Bearer admin-token", "admin-token", allow_public_upload=True))
        self.assertFalse(require_bearer("", "admin-token"))

    def test_decode_payload_accepts_utf8_bom(self) -> None:
        payload = decode_payload(b'\xef\xbb\xbf{"templateId":"bom-ok","name":"BOM"}')

        self.assertEqual(payload["templateId"], "bom-ok")
        self.assertEqual(payload["name"], "BOM")


if __name__ == "__main__":
    unittest.main()
