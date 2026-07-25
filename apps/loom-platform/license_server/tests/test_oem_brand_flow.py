from __future__ import annotations

import base64
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _support import LICENSE_SERVER_ROOT


SERVER_PATH = LICENSE_SERVER_ROOT / "server.py"


def load_server(temp_dir: Path):
    private_key = Ed25519PrivateKey.generate()
    raw_key = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = temp_dir / "private_key.b64"
    key_file.write_text(base64.b64encode(raw_key).decode("ascii"), encoding="utf-8")
    os.environ["LICENSE_DB"] = str(temp_dir / "license.db")
    os.environ["LICENSE_BACKUP_DIR"] = str(temp_dir / "backups")
    os.environ["LICENSE_PRIVATE_KEY_FILE"] = str(key_file)
    os.environ["LICENSE_ADMIN_TOKEN"] = "test-admin-token"
    os.environ["LICENSE_PUBLIC_URL"] = "https://license.example.com/"
    os.environ["LICENSE_SUPPORT_URL"] = "https://support.example.com/"
    module_name = f"oem_brand_server_test_{next(tempfile._get_candidate_names())}"
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class OemBrandServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = load_server(self.root)
        self.merchant, _ = self.server.create_account_record(
            username="northstar-owner",
            password="merchant-password-123",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        self.other, _ = self.server.create_account_record(
            username="other-owner",
            password="merchant-password-456",
            role=self.server.ACCOUNT_ROLE_MERCHANT,
        )
        self.merchant_context = {
            "accountId": self.merchant["accountId"],
            "role": "merchant",
        }
        self.other_context = {
            "accountId": self.other["accountId"],
            "role": "merchant",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _brand(self, brand_id: str = "northstar", status: str = "active") -> dict[str, object]:
        return {
            "brandId": brand_id,
            "displayName": "Northstar AI",
            "status": status,
            "purchaseUrl": f"https://{brand_id}.example.com/buy",
            "supportUrl": f"https://support.{brand_id}.example.com",
        }

    def test_database_and_crud_are_scoped_to_the_owning_merchant(self) -> None:
        saved = self.server.upsert_oem_brand(
            self._brand(),
            self.merchant_context,
        )
        self.assertEqual(saved["ownerAccountId"], self.merchant["accountId"])
        self.assertEqual(
            [item["brandId"] for item in self.server.list_oem_brands(self.merchant_context)],
            ["northstar"],
        )
        self.assertEqual(self.server.list_oem_brands(self.other_context), [])
        with self.assertRaises(self.server.ActivationError):
            self.server.upsert_oem_brand(
                {**self._brand(), "supportUrl": "https://hijack.example.com"},
                self.other_context,
            )

    def test_public_config_is_brand_specific_and_global_clients_remain_compatible(self) -> None:
        self.server.upsert_oem_brand(self._brand(), self.merchant_context)
        brand = self.server.client_public_config("northstar")
        self.assertEqual(brand["brandId"], "northstar")
        self.assertEqual(brand["purchaseUrl"], "https://northstar.example.com/buy")
        self.assertEqual(
            brand["supportUrl"],
            "https://support.northstar.example.com",
        )
        global_config = self.server.client_public_config()
        self.assertNotIn("brandId", global_config)
        self.assertIn("purchaseUrl", global_config)

    def test_unknown_and_suspended_brands_fail_closed(self) -> None:
        with self.assertRaisesRegex(self.server.ActivationError, "不存在"):
            self.server.client_public_config("missing-brand")
        self.server.upsert_oem_brand(
            self._brand("paused-brand", status="suspended"),
            self.merchant_context,
        )
        with self.assertRaisesRegex(self.server.ActivationError, "停用"):
            self.server.client_public_config("paused-brand")

    def test_activation_rejects_unknown_brand_before_consuming_a_code(self) -> None:
        code = self.server.create_code_records(
            count=1,
            licensee="OEM customer",
            edition="pro",
            features=["openclaw"],
            expires="2030-01-01",
            max_activations=1,
            owner_account_id=self.merchant["accountId"],
        )[0]
        with self.assertRaisesRegex(self.server.ActivationError, "不存在"):
            self.server.activate_code(
                {
                    "code": code,
                    "brandId": "missing-brand",
                    "installId": "install-1",
                    "deviceId": "device-1",
                }
            )


if __name__ == "__main__":
    unittest.main()
