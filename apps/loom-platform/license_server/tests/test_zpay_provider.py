from __future__ import annotations

import json
import os
import unittest
from email.parser import BytesParser
from email.policy import default
from unittest.mock import patch

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
            "channels": ("alipay", "wxpay"),
            "order_ttl_seconds": 600,
        }
        values.update(overrides)
        return ZPayConfig(**values)

    def test_create_signs_raw_values_then_uses_multipart_transport(self) -> None:
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
                "clientip": "203.0.113.42",
            }
        )

        self.assertEqual("https://merchant.example.test/mapi.php", captured["url"])
        content_type = captured["headers"]["Content-Type"]
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
            + captured["data"]
        )
        form = {
            str(part.get_param("name", header="content-disposition")): part.get_payload(
                decode=True
            ).decode("utf-8")
            for part in message.iter_parts()
        }
        self.assertEqual("merchant-001", form["pid"])
        self.assertEqual("麓鸣 月卡 A&B=1", form["name"])
        self.assertEqual("nonce with space&=", form["param"])
        self.assertEqual("203.0.113.42", form["clientip"])
        self.assertEqual("pc", form["device"])
        self.assertEqual("MD5", form["sign_type"])
        self.assertEqual(sign_md5(form, "merchant-secret"), form["sign"])
        self.assertEqual("CREATE-REF-123", result["providerOrderReference"])
        self.assertEqual("alipays://platformapi/startapp?token=a&b=1", result["qrcode"])
        self.assertEqual("https://merchant.example.test/cashier/order-123", result["payUrl"])
        self.assertEqual("2026-08-02T12:10:00Z", result["expiresAt"])

    def test_configured_channels_are_required_and_enforced(self) -> None:
        environment = {
            "LICENSE_ZPAY_ENABLED": "1",
            "LICENSE_ZPAY_BASE_URL": "https://merchant.example.test",
            "LICENSE_ZPAY_PID": "merchant-001",
            "LICENSE_ZPAY_KEY": "merchant-secret",
            "LICENSE_ZPAY_CREATE_PATH": "/mapi.php",
            "LICENSE_ZPAY_CHANNELS": "alipay",
            "LICENSE_ZPAY_NOTIFY_URL": "https://license.example.test/api/payments/zpay/notify",
            "LICENSE_ZPAY_RETURN_URL": "https://license.example.test/api/payments/zpay/return",
        }
        with patch.dict(os.environ, environment, clear=False):
            config = ZPayConfig.from_env()
        self.assertEqual(("alipay",), config.channels)
        provider = ZPayProvider(
            config,
            requester=lambda *_args: self.fail("disabled channel reached provider transport"),
        )
        with self.assertRaises(PaymentError) as raised:
            provider.create_payment(
                {
                    "out_trade_no": "LM-UNSUPPORTED",
                    "type": "wxpay",
                    "name": "月卡",
                    "money": "99.00",
                    "param": "nonce",
                    "clientip": "203.0.113.42",
                }
            )
        self.assertEqual("PAYMENT_CHANNEL_UNSUPPORTED", raised.exception.code)

    def test_callback_urls_reject_query_parameters_and_fragments(self) -> None:
        invalid_callbacks = (
            {"notify_url": "https://license.example.test/api/payments/zpay/notify?tenant=1"},
            {"return_url": "https://license.example.test/api/payments/zpay/return#paid"},
        )
        for override in invalid_callbacks:
            with self.subTest(override=override):
                with self.assertRaises(PaymentError) as raised:
                    ZPayProvider(
                        self.config(**override),
                        requester=lambda *_args: self.fail("invalid callback reached provider transport"),
                    ).create_payment(
                        {
                            "out_trade_no": "LM-001",
                            "type": "alipay",
                            "name": "月卡",
                            "money": "99.00",
                            "param": "nonce",
                            "clientip": "203.0.113.42",
                        }
                    )
                self.assertEqual("PAYMENT_CALLBACK_INVALID", raised.exception.code)

    def test_create_filters_untrusted_payurl_when_qrcode_is_available(self) -> None:
        request = {
            "out_trade_no": "LM-001",
            "type": "alipay",
            "name": "月卡",
            "money": "99.00",
            "param": "nonce",
            "clientip": "203.0.113.42",
        }
        for pay_url in (
            "javascript:alert(1)",
            "http://merchant.example.test/cashier/order-123",
            "https://attacker.example/cashier/order-123",
            "https://user:password@merchant.example.test/cashier/order-123",
            "https://merchant.example.test/" + "x" * 2050,
        ):
            with self.subTest(pay_url=pay_url[:80]):
                provider = ZPayProvider(
                    self.config(),
                    requester=lambda *_args, candidate=pay_url: json.dumps(
                        {
                            "code": 1,
                            "trade_no": "CREATE-REF",
                            "qrcode": "alipays://platformapi/startapp?token=safe",
                            "payurl": candidate,
                        }
                    ).encode("utf-8"),
                )
                result = provider.create_payment(request)
                self.assertEqual("", result["payUrl"])
                self.assertTrue(result["qrcode"].startswith("alipays://"))

    def test_create_rejects_order_with_only_untrusted_payurl(self) -> None:
        provider = ZPayProvider(
            self.config(),
            requester=lambda *_args: json.dumps(
                {
                    "code": 1,
                    "trade_no": "CREATE-REF",
                    "payurl": "https://attacker.example/cashier/order-123",
                }
            ).encode("utf-8"),
        )
        with self.assertRaises(PaymentError) as raised:
            provider.create_payment(
                {
                    "out_trade_no": "LM-001",
                    "type": "alipay",
                    "name": "月卡",
                    "money": "99.00",
                    "param": "nonce",
                    "clientip": "203.0.113.42",
                }
            )
        self.assertEqual("PAYMENT_PROVIDER_INVALID_RESPONSE", raised.exception.code)

    def test_out_trade_no_respects_official_32_character_limit(self) -> None:
        oversized = "L" * 33
        provider = ZPayProvider(
            self.config(query_enabled=True),
            requester=lambda *_args: self.fail("oversized create order reached transport"),
            query_requester=lambda *_args: self.fail("oversized query reached transport"),
        )

        with self.assertRaises(PaymentError) as create_error:
            provider.create_payment(
                {
                    "out_trade_no": oversized,
                    "type": "alipay",
                    "name": "月卡",
                    "money": "99.00",
                    "param": "nonce",
                    "clientip": "203.0.113.42",
                }
            )
        self.assertEqual("PAYMENT_PROVIDER_REQUEST_INVALID", create_error.exception.code)

        with self.assertRaises(PaymentError) as query_error:
            provider.query_payment({"out_trade_no": oversized})
        self.assertEqual(
            "PAYMENT_RECONCILIATION_REQUEST_INVALID",
            query_error.exception.code,
        )

    def test_create_keeps_https_payurl_on_provider_subdomain(self) -> None:
        provider = ZPayProvider(
            self.config(),
            requester=lambda *_args: json.dumps(
                {
                    "code": 1,
                    "trade_no": "CREATE-REF",
                    "payurl": "https://cashier.merchant.example.test/order/123",
                }
            ).encode("utf-8"),
        )
        result = provider.create_payment(
            {
                "out_trade_no": "LM-001",
                "type": "alipay",
                "name": "月卡",
                "money": "99.00",
                "param": "nonce",
                "clientip": "203.0.113.42",
            }
        )
        self.assertEqual(
            "https://cashier.merchant.example.test/order/123", result["payUrl"]
        )

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
                        "clientip": "203.0.113.42",
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
                    "clientip": "203.0.113.42",
                }
            )
        self.assertEqual("PAYMENT_PROVIDER_INVALID_RESPONSE", raised.exception.code)

    def test_query_uses_explicit_server_side_contract_and_normalizes_paid_result(self) -> None:
        captured: dict[str, object] = {}

        def query_requester(
            url: str,
            params: dict[str, str],
            headers: dict[str, str],
            timeout: int,
        ) -> bytes:
            captured.update(url=url, params=dict(params), headers=headers, timeout=timeout)
            return json.dumps(
                {
                    "code": 1,
                    "trade_no": "FINAL-QUERY-001",
                    "out_trade_no": "LM-001",
                    "type": "alipay",
                    "pid": "merchant-001",
                    "name": "麓鸣月卡",
                    "money": "99.00",
                    "status": 1,
                    "param": "nonce-001",
                }
            ).encode("utf-8")

        provider = ZPayProvider(
            self.config(query_enabled=True, query_path="/api.php"),
            query_requester=query_requester,
        )
        result = provider.query_payment({"out_trade_no": "LM-001"})

        self.assertEqual("https://merchant.example.test/api.php", captured["url"])
        self.assertEqual(
            {
                "act": "order",
                "pid": "merchant-001",
                "key": "merchant-secret",
                "out_trade_no": "LM-001",
            },
            captured["params"],
        )
        self.assertNotIn("merchant-secret", str(captured["url"]))
        self.assertEqual("paid", result["status"])
        self.assertEqual("FINAL-QUERY-001", result["providerTransactionId"])
        self.assertEqual("nonce-001", result["param"])

    def test_query_is_disabled_until_the_merchant_contract_is_explicitly_enabled(self) -> None:
        provider = ZPayProvider(self.config(query_enabled=False))
        with self.assertRaises(PaymentError) as raised:
            provider.query_payment({"out_trade_no": "LM-001"})
        self.assertEqual("PAYMENT_RECONCILIATION_NOT_CONFIGURED", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
