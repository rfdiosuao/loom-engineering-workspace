from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT

from luming_license.domains import plans
from test_license_flow import load_server


class PlansModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plan_and_gateway_operations_have_a_domain_owner(self) -> None:
        self.assertEqual("luming_license.domains.plans", plans.get_plan_rows.__module__)
        self.assertEqual("luming_license.domains.plans", plans.upsert_plan_record.__module__)
        self.assertEqual("luming_license.domains.plans", plans.upsert_account_gateway_settings.__module__)

    def test_purchase_url_remains_dynamically_configurable(self) -> None:
        self.server.update_public_settings({
            "cardSiteEnabled": True,
            "cardSiteLabel": "Buy license",
            "cardSiteUrl": "https://shop.example.com/luming",
            "supportUrl": "https://support.example.com/luming",
        })
        config = self.server.client_public_config()
        self.assertEqual("https://shop.example.com/luming", config["purchaseUrl"])
        self.assertEqual("https://support.example.com/luming", config["supportUrl"])

    def test_plan_application_does_not_expose_gateway_secret(self) -> None:
        rows = self.server.get_plan_rows(include_disabled=True)
        self.assertTrue(rows)
        self.assertNotIn("gatewayToken", rows[0])

    def test_payment_catalog_fields_are_admin_configured_and_preserved(self) -> None:
        first = self.server.upsert_plan_record({
            "planKey": "monthly",
            "displayName": "矩阵月卡",
            "durationDays": 31,
            "features": "matrix.devices,matrix.tasks,matrix.diagnostics",
            "paymentEnabled": True,
            "priceMinor": 12900,
            "currency": "cny",
            "paymentDescription": "手机矩阵、云模板与 Skill 共用授权",
            "paymentBenefits": ["不限手机数量", "共享云模板", "Skill 中心"],
            "paymentSort": 7,
        })
        self.assertTrue(first["paymentEnabled"])
        self.assertEqual(12900, first["priceMinor"])
        self.assertEqual("CNY", first["currency"])
        self.assertEqual(
            ["不限手机数量", "共享云模板", "Skill 中心"],
            first["paymentBenefits"],
        )

        preserved = self.server.upsert_plan_record({
            "planKey": "monthly",
            "displayName": "矩阵月卡（更新）",
            "durationDays": 31,
            "features": "matrix.devices,matrix.tasks,matrix.diagnostics",
        })
        self.assertTrue(preserved["paymentEnabled"])
        self.assertEqual(12900, preserved["priceMinor"])
        self.assertEqual(7, preserved["paymentSort"])

    def test_payment_catalog_rejects_enabled_zero_price(self) -> None:
        with self.assertRaises(self.server.ActivationError):
            self.server.upsert_plan_record({
                "planKey": "invalid_payment",
                "displayName": "无效套餐",
                "durationDays": 31,
                "features": "matrix.devices",
                "paymentEnabled": True,
                "priceMinor": 0,
                "currency": "CNY",
            })
