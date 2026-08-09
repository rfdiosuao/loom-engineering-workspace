from __future__ import annotations

import ipaddress
import json
import os
import ssl
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from _support import LICENSE_SERVER_ROOT  # noqa: F401 - package import path
from luming_license.domains.payments import sign_md5
from test_license_flow import load_server


SERVICE_TOKEN = "test-account-redeem-service-token"
MERCHANT_ID = "network-merchant-001"
MERCHANT_KEY = "network-merchant-secret"


def _write_test_certificates(root: Path) -> tuple[Path, Path, Path]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "LOOM local payment test CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = root / "payment-test-ca.pem"
    cert_path = root / "payment-test-server.pem"
    key_path = root / "payment-test-server-key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


class LocalZPaySandbox:
    def __init__(self, root: Path) -> None:
        self.orders: dict[str, dict[str, str]] = {}
        self.queries: list[dict[str, str]] = []
        self.errors: list[str] = []
        ca_path, cert_path, key_path = _write_test_certificates(root)
        self.ca_path = ca_path
        sandbox = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def send_json(self, status: int, payload: dict[str, object]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802 - HTTP handler contract
                if urlsplit(self.path).path != "/mapi.php":
                    self.send_json(404, {"code": 0})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "")
                message = BytesParser(policy=default).parsebytes(
                    f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode(
                        "ascii"
                    )
                    + raw
                )
                fields = {
                    str(part.get_param("name", header="content-disposition")): (
                        part.get_payload(decode=True).decode("utf-8")
                    )
                    for part in message.iter_parts()
                }
                expected = sign_md5(fields, MERCHANT_KEY)
                if fields.get("pid") != MERCHANT_ID or fields.get("sign") != expected:
                    sandbox.errors.append("invalid create signature")
                    self.send_json(400, {"code": 0})
                    return
                out_trade_no = fields["out_trade_no"]
                sandbox.orders[out_trade_no] = fields
                self.send_json(
                    200,
                    {
                        "code": 1,
                        "trade_no": f"CREATE-{out_trade_no}",
                        "qrcode": f"alipays://platformapi/startapp?order={out_trade_no}",
                        "payurl": f"https://cashier.example.invalid/{out_trade_no}",
                    },
                )

            def do_GET(self) -> None:  # noqa: N802 - HTTP handler contract
                parsed = urlsplit(self.path)
                if parsed.path != "/api.php":
                    self.send_json(404, {"code": 0})
                    return
                params = {
                    key: values[-1]
                    for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
                }
                sandbox.queries.append(params)
                order = sandbox.orders.get(params.get("out_trade_no", ""))
                if (
                    params.get("act") != "order"
                    or params.get("pid") != MERCHANT_ID
                    or params.get("key") != MERCHANT_KEY
                    or order is None
                ):
                    sandbox.errors.append("invalid query credentials")
                    self.send_json(403, {"code": 0})
                    return
                out_trade_no = order["out_trade_no"]
                self.send_json(
                    200,
                    {
                        "code": 1,
                        "trade_no": f"FINAL-QUERY-{out_trade_no}",
                        "out_trade_no": out_trade_no,
                        "type": order["type"],
                        "pid": order["pid"],
                        "name": order["name"],
                        "money": order["money"],
                        "status": 1,
                        "param": order["param"],
                    },
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"https://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class PaymentNetworkIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="loom-payment-network-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.merchant = LocalZPaySandbox(root)
        self.addCleanup(self.merchant.close)
        self.env = {
            "LICENSE_ZPAY_ENABLED": "1",
            "LICENSE_ZPAY_BASE_URL": self.merchant.base_url,
            "LICENSE_ZPAY_PID": MERCHANT_ID,
            "LICENSE_ZPAY_KEY": MERCHANT_KEY,
            "LICENSE_ZPAY_CREATE_PATH": "/mapi.php",
            "LICENSE_ZPAY_CHANNELS": "alipay",
            "LICENSE_ZPAY_PAY_URL_HOSTS": "cashier.example.invalid",
            "LICENSE_ZPAY_QUERY_ENABLED": "1",
            "LICENSE_ZPAY_QUERY_PATH": "/api.php",
            "LICENSE_ZPAY_NOTIFY_URL": "https://license.example.invalid/api/payments/zpay/notify",
            "LICENSE_ZPAY_RETURN_URL": "https://license.example.invalid/api/payments/zpay/return",
            "SSL_CERT_FILE": str(self.merchant.ca_path),
        }
        self.old_env = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        self.addCleanup(self.restore_environment)
        self.old_opener = urllib.request._opener
        urllib.request._opener = None
        self.addCleanup(self.restore_url_opener)

        license_root = root / "license"
        license_root.mkdir()
        self.app = load_server(license_root)
        self.license_logs: list[str] = []
        self.app.print = self.license_logs.append
        with self.app.connect() as connection:
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
        self.httpd = self.app.ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()
        self.addCleanup(self.stop_license_server)

    def restore_environment(self) -> None:
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def restore_url_opener(self) -> None:
        urllib.request._opener = self.old_opener

    def stop_license_server(self) -> None:
        self.httpd.shutdown()
        self.http_thread.join(timeout=5)
        self.httpd.server_close()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            method="POST",
            headers={
                "Authorization": f"Bearer {SERVICE_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        try:
            with urlopen(request, timeout=5) as response:
                raw = response.read()
        except HTTPError as error:
            self.fail(f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')}")
        return json.loads(raw.decode("utf-8"))

    def create(self, account_id: str, request_id: str) -> dict[str, object]:
        return self.post(
            "/api/service/payments/orders/create",
            {
                "accountId": account_id,
                "planKey": "monthly",
                "paymentType": "alipay",
                "requestId": request_id,
                "clientIp": "127.0.0.1",
            },
        )["order"]

    def test_real_tls_create_notify_and_query_reconciliation_issue_entitlements(self) -> None:
        callback_order = self.create("network-callback-account", "network-click-001")
        self.assertTrue(callback_order["qrcode"].startswith("alipays://"))
        self.assertTrue(callback_order["payUrl"].startswith("https://"))
        self.assertNotEqual(callback_order["qrcode"], callback_order["payUrl"])
        callback_fields = self.merchant.orders[callback_order["outTradeNo"]]
        callback = {
            "pid": MERCHANT_ID,
            "trade_no": f"FINAL-NOTIFY-{callback_order['outTradeNo']}",
            "out_trade_no": callback_order["outTradeNo"],
            "type": callback_fields["type"],
            "name": callback_fields["name"],
            "money": callback_fields["money"],
            "trade_status": "TRADE_SUCCESS",
            "param": callback_fields["param"],
            "sign_type": "MD5",
        }
        callback["sign"] = sign_md5(callback, MERCHANT_KEY)
        with urlopen(
            f"{self.base_url}/api/payments/zpay/notify?{urlencode(callback)}",
            timeout=5,
        ) as response:
            self.assertEqual(b"success", response.read())
        paid = self.post(
            "/api/service/payments/orders/status",
            {
                "accountId": "network-callback-account",
                "orderId": callback_order["orderId"],
            },
        )["order"]
        self.assertEqual("paid", paid["status"])
        self.assertTrue(callback_order["providerOrderReference"].startswith("CREATE-"))
        self.assertTrue(paid["providerTransactionId"].startswith("FINAL-NOTIFY-"))
        self.assertNotEqual(
            callback_order["providerOrderReference"], paid["providerTransactionId"]
        )
        self.assertEqual("", paid["qrcode"])
        self.assertEqual("", paid["payUrl"])
        self.assertEqual(
            "monthly",
            self.app.current_account_entitlement("network-callback-account")["plan"],
        )

        query_order = self.create("network-query-account", "network-click-002")
        reconciled = self.post(
            "/api/service/payments/orders/status",
            {
                "accountId": "network-query-account",
                "orderId": query_order["orderId"],
                "reconcile": True,
            },
        )["order"]
        self.assertEqual("paid", reconciled["status"])
        self.assertTrue(reconciled["reconciled"])
        self.assertTrue(reconciled["providerTransactionId"].startswith("FINAL-QUERY-"))
        self.assertNotEqual(
            query_order["providerOrderReference"], reconciled["providerTransactionId"]
        )
        self.assertEqual(
            "monthly",
            self.app.current_account_entitlement("network-query-account")["plan"],
        )
        self.assertEqual(query_order["outTradeNo"], self.merchant.queries[-1]["out_trade_no"])
        self.assertEqual([], self.merchant.errors)
        rendered_logs = "\n".join(self.license_logs)
        self.assertIn("/api/payments/zpay/notify", rendered_logs)
        self.assertNotIn(MERCHANT_KEY, rendered_logs)
        self.assertNotIn(callback["sign"], rendered_logs)
        self.assertNotIn(callback_fields["param"], rendered_logs)
        self.assertNotIn(callback["trade_no"], rendered_logs)


if __name__ == "__main__":
    unittest.main()
