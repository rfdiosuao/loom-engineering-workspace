from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from _support import LICENSE_SERVER_ROOT  # noqa: F401 - package import path
from luming_license.domains import payments
from test_license_flow import load_server


class FakeZPayProvider:
    name = "zpay"

    def __init__(self, connect_fn) -> None:
        self.connect_fn = connect_fn
        self.calls: list[dict[str, object]] = []
        self.query_calls: list[dict[str, object]] = []
        self.query_response: dict[str, object] | None = None

    def create_payment(self, request: dict[str, object]) -> dict[str, object]:
        with self.connect_fn() as connection:
            persisted = connection.execute(
                "select status from payment_orders where out_trade_no = ?",
                (request["out_trade_no"],),
            ).fetchone()
        if persisted is None or persisted["status"] != "pending":
            raise AssertionError("order must be committed before provider I/O")
        self.calls.append(dict(request))
        return {
            "providerOrderReference": "CREATE-REFERENCE-001",
            "qrcode": "https://pay.example.test/qr/token-001",
            "payUrl": "https://pay.example.test/jump/order-001",
            "expiresAt": "2026-08-02T13:00:00Z",
        }

    def query_payment(self, request: dict[str, object]) -> dict[str, object]:
        self.query_calls.append(dict(request))
        if self.query_response is None:
            return {"status": "pending", "outTradeNo": request["out_trade_no"]}
        return dict(self.query_response)


class PaymentDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = load_server(Path(self.temp.name))
        with self.server.connect() as connection:
            connection.execute(
                """
                update plans
                set payment_enabled = 1, price_minor = 9900, currency = 'CNY',
                    payment_description = '手机矩阵与共享模板',
                    payment_benefits_json = ?, duration_days = 31,
                    features_json = ?, quotas_json = ?
                where plan_key = 'monthly'
                """,
                (
                    json.dumps(["手机矩阵", "共享模板", "Skill 中心"], ensure_ascii=False),
                    json.dumps(["matrix.devices", "matrix.tasks"], ensure_ascii=False),
                    json.dumps({"concurrentTasks": 3}, ensure_ascii=False),
                ),
            )
            connection.commit()

    def test_md5_signing_uses_raw_utf8_values_and_keeps_zero(self) -> None:
        fields = {
            "pid": "1001",
            "type": "alipay",
            "out_trade_no": "ORDER 001",
            "name": "测试 A&B=1",
            "money": "0",
            "empty": "",
            "sign": "ignored",
            "sign_type": "MD5",
        }

        canonical = payments.canonical_signing_text(fields, "s3cr et&=")

        self.assertEqual(
            "money=0&name=测试 A&B=1&out_trade_no=ORDER 001&pid=1001&type=alipays3cr et&=",
            canonical,
        )
        self.assertEqual(
            "bad6cdd8efa426b30a168e2f0b8cf003",
            payments.sign_md5(fields, "s3cr et&="),
        )

    def test_create_order_is_persisted_before_provider_and_is_idempotent(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        body = {
            "accountId": "account-paid",
            "planKey": "monthly",
            "paymentType": "alipay",
            "requestId": "desktop-click-001",
        }

        created = payments.create_payment_order(
            body,
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:00Z",
            token_fn=lambda _size=0: "token-fixed-001",
        )
        retried = payments.create_payment_order(
            body,
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:01Z",
            token_fn=lambda _size=0: "must-not-be-used",
        )

        self.assertEqual(1, len(provider.calls))
        self.assertEqual(created["orderId"], retried["orderId"])
        self.assertEqual("pending", created["status"])
        self.assertEqual("CREATE-REFERENCE-001", created["providerOrderReference"])
        self.assertEqual("https://pay.example.test/qr/token-001", created["qrcode"])
        self.assertEqual("https://pay.example.test/jump/order-001", created["payUrl"])
        self.assertNotEqual(created["qrcode"], created["payUrl"])
        self.assertNotIn("nonce", json.dumps(created).lower())
        with self.server.connect() as connection:
            row = connection.execute(
                "select amount_minor, currency, provider_order_reference, provider_transaction_id from payment_orders"
            ).fetchone()
        self.assertEqual((9900, "CNY", "CREATE-REFERENCE-001", None), tuple(row))

    def test_status_expires_stale_qr_without_granting_entitlement(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        created = payments.create_payment_order(
            {
                "accountId": "account-expired",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "desktop-expired-001",
            },
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:00Z",
            token_fn=lambda _size=0: "expired-token-001",
        )
        with self.server.connect() as connection:
            connection.execute(
                "update payment_orders set expires_at = '2000-01-01T00:00:00Z' where order_id = ?",
                (created["orderId"],),
            )
            connection.commit()

        status = payments.payment_order_status(
            {"accountId": "account-expired", "orderId": created["orderId"]},
            connect_fn=self.server.connect,
        )

        self.assertEqual("expired", status["status"])
        self.assertEqual("", status["qrcode"])
        self.assertEqual("", status["payUrl"])
        with self.server.connect() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "select count(*) from account_entitlement_redemptions where account_id = ?",
                    ("account-expired",),
                ).fetchone()[0],
            )

    def test_late_verified_callback_can_fulfil_an_expired_qr_order(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        created = payments.create_payment_order(
            {
                "accountId": "account-late-callback",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "desktop-expired-002",
            },
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:00Z",
            token_fn=lambda _size=0: "expired-token-002",
        )
        request = provider.calls[0]
        with self.server.connect() as connection:
            connection.execute(
                "update payment_orders set status = 'expired' where order_id = ?",
                (created["orderId"],),
            )
            connection.commit()
        callback = {
            "pid": "merchant-001",
            "trade_no": "FINAL-LATE-TRANSACTION-002",
            "out_trade_no": request["out_trade_no"],
            "type": "alipay",
            "name": request["name"],
            "money": "99.00",
            "trade_status": "TRADE_SUCCESS",
            "param": request["param"],
            "sign_type": "MD5",
        }
        callback["sign"] = payments.sign_md5(callback, "merchant-secret")

        try:
            paid = payments.process_zpay_notification(
                callback,
                connect_fn=self.server.connect,
                merchant_id="merchant-001",
                merchant_key="merchant-secret",
                now_fn=lambda: "2026-08-02T13:01:00Z",
            )
        except payments.PaymentError as error:
            self.fail(f"late verified callback was rejected: {error.code}")

        self.assertEqual("paid", paid["status"])
        self.assertEqual(
            "monthly",
            self.server.current_account_entitlement("account-late-callback")["plan"],
        )

    def test_verified_notification_fulfils_once_and_rejects_tampering(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        created = payments.create_payment_order(
            {
                "accountId": "account-paid",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "desktop-click-002",
            },
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:00Z",
            token_fn=lambda _size=0: "callback-nonce-002",
        )
        request = provider.calls[0]
        callback = {
            "pid": "merchant-001",
            "trade_no": "FINAL-TRANSACTION-999",
            "out_trade_no": request["out_trade_no"],
            "type": "alipay",
            "name": request["name"],
            "money": "99.00",
            "trade_status": "TRADE_SUCCESS",
            "param": request["param"],
            "sign_type": "MD5",
        }
        callback["sign"] = payments.sign_md5(callback, "merchant-secret")

        paid = payments.process_zpay_notification(
            callback,
            connect_fn=self.server.connect,
            merchant_id="merchant-001",
            merchant_key="merchant-secret",
            now_fn=lambda: "2026-08-02T12:02:00Z",
        )
        duplicate = payments.process_zpay_notification(
            callback,
            connect_fn=self.server.connect,
            merchant_id="merchant-001",
            merchant_key="merchant-secret",
            now_fn=lambda: "2026-08-02T12:03:00Z",
        )

        self.assertEqual("paid", paid["status"])
        self.assertFalse(paid["duplicate"])
        self.assertEqual("", paid["qrcode"])
        self.assertEqual("", paid["payUrl"])
        self.assertEqual("", duplicate["qrcode"])
        self.assertEqual("", duplicate["payUrl"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual("CREATE-REFERENCE-001", created["providerOrderReference"])
        self.assertEqual("FINAL-TRANSACTION-999", paid["providerTransactionId"])
        entitlement = self.server.current_account_entitlement("account-paid")
        self.assertEqual("monthly", entitlement["plan"])
        self.assertIn("matrix.devices", entitlement["features"])
        self.assertEqual(3, entitlement["limits"]["concurrentTasks"])
        self.assertGreaterEqual(
            date.fromisoformat(entitlement["expiresAt"]),
            date.today() + timedelta(days=30),
        )
        with self.server.connect() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "select count(*) from account_entitlement_redemptions where account_id = 'account-paid'"
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    "select count(*) from audit_logs where action = 'payment.order.paid'"
                ).fetchone()[0],
            )

        for field, bad_value, code in (
            ("pid", "wrong-merchant", "PAYMENT_MERCHANT_MISMATCH"),
            ("money", "98.99", "PAYMENT_AMOUNT_MISMATCH"),
            ("type", "wxpay", "PAYMENT_CHANNEL_MISMATCH"),
            ("trade_status", "WAIT_BUYER_PAY", "PAYMENT_NOT_SUCCESSFUL"),
            ("param", "wrong-nonce", "PAYMENT_NONCE_MISMATCH"),
        ):
            tampered = {**callback, field: bad_value}
            tampered["sign"] = payments.sign_md5(tampered, "merchant-secret")
            with self.subTest(field=field), self.assertRaises(payments.PaymentError) as raised:
                payments.process_zpay_notification(
                    tampered,
                    connect_fn=self.server.connect,
                    merchant_id="merchant-001",
                    merchant_key="merchant-secret",
                )
            self.assertEqual(code, raised.exception.code)

        wrong_signature = {**callback, "sign": hashlib.md5(b"wrong").hexdigest()}
        with self.assertRaises(payments.PaymentError) as raised:
            payments.process_zpay_notification(
                wrong_signature,
                connect_fn=self.server.connect,
                merchant_id="merchant-001",
                merchant_key="merchant-secret",
            )
        self.assertEqual("PAYMENT_SIGNATURE_INVALID", raised.exception.code)

    def test_reconcile_recovers_a_paid_order_after_callback_loss(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        created = payments.create_payment_order(
            {
                "accountId": "account-reconcile",
                "planKey": "monthly",
                "paymentType": "wxpay",
                "requestId": "desktop-reconcile-001",
            },
            connect_fn=self.server.connect,
            provider=provider,
            now_fn=lambda: "2026-08-02T12:00:00Z",
            token_fn=lambda _size=0: "reconcile-nonce-001",
        )
        request = provider.calls[0]
        provider.query_response = {
            "status": "paid",
            "merchantId": "merchant-001",
            "providerTransactionId": "FINAL-RECONCILED-001",
            "outTradeNo": request["out_trade_no"],
            "paymentType": "wxpay",
            "productName": request["name"],
            "money": "99.00",
            "param": request["param"],
        }

        paid = payments.reconcile_payment_order(
            {"accountId": "account-reconcile", "orderId": created["orderId"]},
            connect_fn=self.server.connect,
            provider=provider,
            merchant_id="merchant-001",
            now_fn=lambda: "2026-08-02T12:05:00Z",
        )
        duplicate = payments.reconcile_payment_order(
            {"accountId": "account-reconcile", "orderId": created["orderId"]},
            connect_fn=self.server.connect,
            provider=provider,
            merchant_id="merchant-001",
            now_fn=lambda: "2026-08-02T12:06:00Z",
        )

        self.assertEqual("paid", paid["status"])
        self.assertFalse(paid["duplicate"])
        self.assertEqual("paid", duplicate["status"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(1, len(provider.query_calls))
        self.assertEqual(
            "monthly",
            self.server.current_account_entitlement("account-reconcile")["plan"],
        )

    def test_reconcile_rejects_mismatched_provider_result_without_fulfilment(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        created = payments.create_payment_order(
            {
                "accountId": "account-reconcile-tamper",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "desktop-reconcile-002",
            },
            connect_fn=self.server.connect,
            provider=provider,
            token_fn=lambda _size=0: "reconcile-nonce-002",
        )
        request = provider.calls[0]
        provider.query_response = {
            "status": "paid",
            "merchantId": "merchant-001",
            "providerTransactionId": "FINAL-RECONCILED-002",
            "outTradeNo": request["out_trade_no"],
            "paymentType": "alipay",
            "productName": request["name"],
            "money": "98.99",
            "param": request["param"],
        }

        with self.assertRaises(payments.PaymentError) as raised:
            payments.reconcile_payment_order(
                {
                    "accountId": "account-reconcile-tamper",
                    "orderId": created["orderId"],
                },
                connect_fn=self.server.connect,
                provider=provider,
                merchant_id="merchant-001",
            )

        self.assertEqual("PAYMENT_AMOUNT_MISMATCH", raised.exception.code)
        with self.server.connect() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "select count(*) from account_entitlement_redemptions where account_id = ?",
                    ("account-reconcile-tamper",),
                ).fetchone()[0],
            )

    def test_concurrent_duplicate_callbacks_fulfil_exactly_once(self) -> None:
        provider = FakeZPayProvider(self.server.connect)
        payments.create_payment_order(
            {
                "accountId": "account-concurrent-callback",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "desktop-concurrent-001",
            },
            connect_fn=self.server.connect,
            provider=provider,
            token_fn=lambda _size=0: "concurrent-nonce-001",
        )
        request = provider.calls[0]
        callback = {
            "pid": "merchant-001",
            "trade_no": "FINAL-CONCURRENT-001",
            "out_trade_no": request["out_trade_no"],
            "type": "alipay",
            "name": request["name"],
            "money": "99.00",
            "trade_status": "TRADE_SUCCESS",
            "param": request["param"],
            "sign_type": "MD5",
        }
        callback["sign"] = payments.sign_md5(callback, "merchant-secret")

        def fulfil_once() -> dict[str, object]:
            return payments.process_zpay_notification(
                callback,
                connect_fn=self.server.connect,
                merchant_id="merchant-001",
                merchant_key="merchant-secret",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: fulfil_once(), range(2)))

        self.assertEqual([False, True], sorted(result["duplicate"] for result in results))
        with self.server.connect() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "select count(*) from account_entitlement_redemptions where account_id = ?",
                    ("account-concurrent-callback",),
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    "select count(*) from audit_logs where action = 'payment.order.paid'",
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
