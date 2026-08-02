from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs

from _support import LICENSE_SERVER_ROOT  # noqa: F401 - package import path
from luming_license.domains.payment_provider_zpay import ZPayConfig, ZPayProvider
from luming_license.domains.payments import PaymentError, sign_md5


class ZPayProviderTests(unittest.TestCase):
    def config(self, **overrides) -> ZPayConfig:
        values = {
            "enabled": True,
            "base_url": "https://merchant.example.test",
            "merchant_id": "merchant-001",
            "merchant_key": "merchant-secret",
            "create_path": "/mapi.php",
            "notify_url": "https://license.example.test/api/payments/zpay/notify",
            "return_url": "https://license.example.test/api/payments/zpay/return",
            "order_ttl_seconds": 600,
        }
        values.update(overrides)
        return ZPayConfig(**values)

    def test_create_signs_raw_values_then_form_encodes_transport(self) -> None:
        captured: dict[str, object] = {}

        def requester(url: str, data: bytes, headers: dict[str, str], timeout: int) -> bytes:
            captured.update(url=url, data=data, headers=headers, timeout=timeout)
            return json.dumps(
                {
                    "code": 1,
                    "trade_no": "CREATE-REF-123",
                    "qrcode": "alipays://platformapi/startapp?token=a&b=1",
                    "payurl": "https://merchant.example.test/cashier/order-123",
                }
            ).encode("utf-8")

        provider = ZPayProvider(
            self.config(),
            requester=requester,
            now_fn=lambda: "2026-08-02T12:00:00Z",
        )
        result = provider.create_payment(
            {
                "out_trade_no": "LM-001",
                "type": "alipay",
                "name": "麓鸣 月卡 A&B=1",
                "money": "99.00",
                "param": "nonce with space&=",
            }
        )

        self.assertEqual("https://merchant.example.test/mapi.php", captured["url"])
        form = {key: values[0] for key, values in parse_qs(captured["data"].decode("utf-8"), keep_blank_values=True).items()}
        self.assertEqual("merchant-001", form["pid"])
        self.assertEqual("麓鸣 月卡 A&B=1", form["name"])
        self.assertEqual("nonce with space&=", form["param"])
        self.assertEqual("MD5", form["sign_type"])
        self.assertEqual(sign_md5(form, "merchant-secret"), form["sign"])
        self.assertEqual("CREATE-REF-123", result["providerOrderReference"])
        self.assertEqual("alipays://platformapi/startapp?token=a&b=1", result["qrcode"])
        self.assertEqual("https://merchant.example.test/cashier/order-123", result["payUrl"])
        self.assertEqual("2026-08-02T12:10:00Z", result["expiresAt"])

    def test_provider_fails_closed_for_insecure_or_malformed_contract(self) -> None:
        for config, expected in (
            (self.config(base_url="http://merchant.example.test"), "PAYMENT_PROVIDER_INSECURE"),
            (self.config(merchant_key=""), "PAYMENT_PROVIDER_NOT_CONFIGURED"),
            (self.config(create_path="https://attacker.example/mapi.php"), "PAYMENT_PROVIDER_PATH_INVALID"),
        ):
            with self.subTest(expected=expected), self.assertRaises(PaymentError) as raised:
                ZPayProvider(config, requester=lambda *_args: b"{}").create_payment(
                    {
                        "out_trade_no": "LM-001",
                        "type": "alipay",
                        "name": "月卡",
                        "money": "99.00",
                        "param": "nonce",
                    }
                )
            self.assertEqual(expected, raised.exception.code)

        provider = ZPayProvider(
            self.config(),
            requester=lambda *_args: b'{"code":1,"trade_no":"CREATE-REF"}',
        )
        with self.assertRaises(PaymentError) as raised:
            provider.create_payment(
                {
                    "out_trade_no": "LM-001",
                    "type": "alipay",
                    "name": "月卡",
                    "money": "99.00",
                    "param": "nonce",
                }
            )
        self.assertEqual("PAYMENT_PROVIDER_INVALID_RESPONSE", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
