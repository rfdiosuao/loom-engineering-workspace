from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from _support import LICENSE_SERVER_ROOT  # noqa: F401 - package import path
from luming_license.domains import payments
from test_license_flow import load_server


SERVICE_TOKEN = "test-account-redeem-service-token"


class PaymentHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._old_env = {key: os.environ.get(key) for key in self.payment_env()}
        os.environ.update(self.payment_env())
        self.addCleanup(self.restore_env)
        self.server = load_server(Path(self.temp.name))
        self._httpd = None
        with self.server.connect() as connection:
            connection.execute(
                """
                update plans
                set payment_enabled = 1, price_minor = 9900, currency = 'CNY',
                    features_json = ?, quotas_json = ?, duration_days = 31
                where plan_key = 'monthly'
                """,
                (
                    json.dumps(["matrix.devices", "matrix.tasks"]),
                    json.dumps({"concurrentTasks": 2}),
                ),
            )
            connection.commit()

    @staticmethod
    def payment_env() -> dict[str, str]:
        return {
            "LICENSE_ZPAY_ENABLED": "1",
            "LICENSE_ZPAY_BASE_URL": "https://merchant.example.test",
            "LICENSE_ZPAY_PID": "merchant-001",
            "LICENSE_ZPAY_KEY": "merchant-secret",
            "LICENSE_ZPAY_CREATE_PATH": "/mapi.php",
            "LICENSE_ZPAY_NOTIFY_URL": "https://license.example.test/api/payments/zpay/notify",
            "LICENSE_ZPAY_RETURN_URL": "https://license.example.test/api/payments/zpay/return",
        }

    def restore_env(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def base_url(self) -> str:
        if self._httpd is not None:
            return f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._httpd = self.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self.server.Handler
        )
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()

        def cleanup() -> None:
            self._httpd.shutdown()
            thread.join(timeout=5)
            self._httpd.server_close()

        self.addCleanup(cleanup)
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def post(self, path: str, body: dict, *, token: str | None = SERVICE_TOKEN, expected: int = 200):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base_url()}{path}",
            method="POST",
            headers=headers,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        try:
            response = urlopen(request, timeout=5)
            status = response.status
            raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        self.assertEqual(expected, status, raw.decode("utf-8", errors="replace"))
        return json.loads(raw.decode("utf-8"))

    def test_service_routes_require_auth_and_keep_secrets_server_side(self) -> None:
        unauthorized = self.post(
            "/api/service/payments/plans", {}, token=None, expected=401
        )
        plans = self.post("/api/service/payments/plans", {})
        self.assertEqual("SERVICE_AUTH_REQUIRED", unauthorized["code"])
        self.assertEqual("monthly", plans["plans"][0]["planKey"])
        self.assertNotIn("merchant-secret", json.dumps(plans))
        self.assertNotIn("merchant-001", json.dumps(plans))

        with patch(
            "luming_license.http.routes_payments.ZPayProvider.create_payment",
            return_value={
                "providerOrderReference": "CREATE-REF-HTTP",
                "qrcode": "https://pay.example.test/qr/http",
                "payUrl": "https://pay.example.test/jump/http",
                "expiresAt": "2026-08-02T13:00:00Z",
            },
        ):
            created = self.post(
                "/api/service/payments/orders/create",
                {
                    "accountId": "http-account",
                    "planKey": "monthly",
                    "paymentType": "alipay",
                    "requestId": "http-click-001",
                },
            )
        order = created["order"]
        status = self.post(
            "/api/service/payments/orders/status",
            {"accountId": "http-account", "orderId": order["orderId"]},
        )
        self.assertEqual(order["orderId"], status["order"]["orderId"])
        self.assertEqual("pending", status["order"]["status"])
        self.assertNotIn("nonce", json.dumps(created).lower())

    def test_notify_returns_exact_ack_only_after_verified_transaction(self) -> None:
        access_logs: list[str] = []
        self.server.print = access_logs.append

        class Provider:
            name = "zpay"

            def __init__(self) -> None:
                self.request = None

            def create_payment(inner, request):
                inner.request = request
                return {
                    "providerOrderReference": "CREATE-REF-CALLBACK",
                    "qrcode": "https://pay.example.test/qr/callback",
                    "payUrl": "",
                    "expiresAt": "2026-08-02T13:00:00Z",
                }

        provider = Provider()
        payments.create_payment_order(
            {
                "accountId": "callback-account",
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": "callback-click-001",
            },
            connect_fn=self.server.connect,
            provider=provider,
            token_fn=lambda _size=0: "http-callback-token",
        )
        callback = {
            "pid": "merchant-001",
            "trade_no": "FINAL-HTTP-TRANSACTION",
            "out_trade_no": provider.request["out_trade_no"],
            "type": "alipay",
            "name": provider.request["name"],
            "money": "99.00",
            "trade_status": "TRADE_SUCCESS",
            "param": provider.request["param"],
            "sign_type": "MD5",
        }
        callback["sign"] = payments.sign_md5(callback, "merchant-secret")
        response = urlopen(
            f"{self.base_url()}/api/payments/zpay/notify?{urlencode(callback)}",
            timeout=5,
        )
        self.assertEqual(b"success", response.read())
        rendered_logs = "\n".join(access_logs)
        self.assertNotIn(callback["sign"], rendered_logs)
        self.assertNotIn(callback["param"], rendered_logs)
        self.assertNotIn("FINAL-HTTP-TRANSACTION", rendered_logs)
        self.assertIn("/api/payments/zpay/notify", rendered_logs)
        duplicate = urlopen(
            f"{self.base_url()}/api/payments/zpay/notify?{urlencode(callback)}",
            timeout=5,
        )
        self.assertEqual(b"success", duplicate.read())
        self.assertEqual(
            "monthly",
            self.server.current_account_entitlement("callback-account")["plan"],
        )

        bad = {**callback, "money": "98.00"}
        bad["sign"] = payments.sign_md5(bad, "merchant-secret")
        with self.assertRaises(HTTPError) as raised:
            urlopen(
                f"{self.base_url()}/api/payments/zpay/notify?{urlencode(bad)}",
                timeout=5,
            )
        self.assertEqual(400, raised.exception.code)
        self.assertEqual(b"fail", raised.exception.read())

        returned = urlopen(
            f"{self.base_url()}/api/payments/zpay/return?out_trade_no={provider.request['out_trade_no']}",
            timeout=5,
        ).read().decode("utf-8")
        self.assertIn("请回到麓鸣查看订单状态", returned)
        self.assertNotIn("FINAL-HTTP-TRANSACTION", returned)


if __name__ == "__main__":
    unittest.main()
