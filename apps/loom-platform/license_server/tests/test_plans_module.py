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
