from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from _support import LICENSE_SERVER_ROOT  # noqa: F401 - ensures the package is importable
from luming_license.http import handler as http_handler
from luming_license.http import responses as http_responses
from luming_license.http.handler import ROUTE_INVENTORY
from luming_license.http.responses import ResponseMixin
from luming_license.http import routes_admin, routes_auth, routes_public, routes_relay
from test_license_flow import load_server

EXPECTED_ROUTE_MARKERS = {
    "/",
    "/activate",
    "/admin",
    "/admin/",
    "/admin/api/account-gateway",
    "/admin/api/accounts",
    "/admin/api/accounts/toggle",
    "/admin/api/activations",
    "/admin/api/activations/delete",
    "/admin/api/audit-logs",
    "/admin/api/auth/bootstrap",
    "/admin/api/auth/login",
    "/admin/api/auth/logout",
    "/admin/api/auth/register",
    "/admin/api/auth/status",
    "/admin/api/beta/config",
    "/admin/api/codes",
    "/admin/api/codes/activations",
    "/admin/api/codes/bulk-update",
    "/admin/api/codes/clear",
    "/admin/api/codes/delete",
    "/admin/api/codes/export",
    "/admin/api/codes/hash",
    "/admin/api/codes/reveal",
    "/admin/api/codes/toggle",
    "/admin/api/codes/update",
    "/admin/api/invites",
    "/admin/api/invites/toggle",
    "/admin/api/me",
    "/admin/api/plans",
    "/admin/api/plans/delete",
    "/admin/api/plans/update",
    "/admin/api/public-settings",
    "/admin/api/templates",
    "/admin/api/templates/delete",
    "/admin/logo.ico",
    "/api/beta/claim",
    "/api/beta/status",
    "/api/client/config",
    "/api/lumi/publish/complete",
    "/api/lumi/publish/health",
    "/api/lumi/publish/packet",
    "/api/lumi/publish/poll",
    "/api/lumi/publish/status",
    "/api/lumi/relay/complete",
    "/api/lumi/relay/health",
    "/api/lumi/relay/packet",
    "/api/lumi/relay/poll",
    "/api/lumi/relay/status",
    "/api/member/activate",
    "/api/member/current",
    "/api/member/refresh",
    "/api/member/usage",
    "/api/public/config",
    "/api/templates",
    "/api/v1/member/activate",
    "/api/v1/member/current",
    "/api/v1/member/refresh",
    "/api/v1/member/usage",
    "/client/config",
    "/health",
    "/logo.ico",
    "/member/activate",
    "/member/current",
    "/member/refresh",
    "/member/usage",
    "/public-key",
}

EXPECTED_ADMIN_ROUTE_CALLABLES = {
    "GET": {
        "/admin/api/beta/config": "get_admin_api_beta_config",
        "/admin/api/templates": "get_admin_api_templates",
        "/admin/api/accounts": "get_admin_api_accounts",
        "/admin/api/invites": "get_admin_api_invites",
        "/admin/api/codes": "get_admin_api_codes",
        "/admin/api/activations": "get_admin_api_activations",
        "/admin/api/plans": "get_admin_api_plans",
        "/admin/api/account-gateway": "get_admin_api_account_gateway",
        "/admin/api/codes/activations": "get_admin_api_codes_activations",
        "/admin/api/audit-logs": "get_admin_api_audit_logs",
        "/admin/api/public-settings": "get_admin_api_public_settings",
    },
    "POST": {
        "/admin/api/beta/config": "post_admin_api_beta_config",
        "/admin/api/templates": "post_admin_api_templates",
        "/admin/api/templates/delete": "post_admin_api_templates_delete",
        "/admin/api/accounts": "post_admin_api_accounts",
        "/admin/api/accounts/toggle": "post_admin_api_accounts_toggle",
        "/admin/api/invites": "post_admin_api_invites",
        "/admin/api/invites/toggle": "post_admin_api_invites_toggle",
        "/admin/api/account-gateway": "post_admin_api_account_gateway",
        "/admin/api/codes/reveal": "post_admin_api_codes_reveal",
        "/admin/api/codes/export": "post_admin_api_codes_export",
        "/admin/api/codes": "post_admin_api_codes",
        "/admin/api/codes/update": "post_admin_api_codes_update",
        "/admin/api/codes/bulk-update": "post_admin_api_codes_bulk_update",
        "/admin/api/plans/update": "post_admin_api_plans_update",
        "/admin/api/plans/delete": "post_admin_api_plans_delete",
        "/admin/api/codes/toggle": "post_admin_api_codes_toggle",
        "/admin/api/codes/clear": "post_admin_api_codes_clear",
        "/admin/api/codes/hash": "post_admin_api_codes_hash",
        "/admin/api/codes/delete": "post_admin_api_codes_delete",
        "/admin/api/activations/delete": "post_admin_api_activations_delete",
        "/admin/api/public-settings": "post_admin_api_public_settings",
    },
}


class ResponseProbe(ResponseMixin):
    def __init__(
        self,
        path: str,
        *,
        origin: str = "",
        transaction: object | None = None,
        facade: object | None = None,
    ) -> None:
        self.path = path
        self.headers = {"Origin": origin} if origin else {}
        self.wfile = BytesIO()
        self.status = 0
        self.response_headers: list[tuple[str, str]] = []
        self.ended = False
        self.facade = (
            facade
            if facade is not None
            else SimpleNamespace(
                _active_audit_transaction=lambda: transaction,
                admin_cors_origin_allowed=lambda value: (
                    value == "https://admin.example"
                ),
                is_admin_request_path=lambda value: urlparse(value).path.startswith(
                    "/admin"
                ),
                json=json,
                open=open,
                urlparse=urlparse,
            )
        )

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers.append((name, value))

    def end_headers(self) -> None:
        self.ended = True

    def header(self, name: str) -> str | None:
        return next(
            (value for key, value in self.response_headers if key == name), None
        )


class HttpRouteInventoryTests(unittest.TestCase):
    def test_router_registry_contains_every_external_route(self) -> None:
        self.assertEqual(set(), EXPECTED_ROUTE_MARKERS - set(ROUTE_INVENTORY))

    def test_router_registry_is_exact_union_of_exact_path_tables(self) -> None:
        modules = (routes_public, routes_auth, routes_admin, routes_relay)
        registered: set[str] = set()
        for module in modules:
            for attribute in ("GET_ROUTES", "POST_ROUTES"):
                routes = getattr(module, attribute, {})
                self.assertIsInstance(routes, dict)
                self.assertTrue(
                    all(path.startswith("/") and "*" not in path for path in routes)
                )
                self.assertTrue(all(callable(route) for route in routes.values()))
                registered.update(routes)
        self.assertEqual(EXPECTED_ROUTE_MARKERS, registered)
        self.assertEqual(EXPECTED_ROUTE_MARKERS, set(ROUTE_INVENTORY))

    def test_admin_route_registry_keeps_method_path_callable_contract(self) -> None:
        actual = {
            "GET": {
                path: route.__name__ for path, route in routes_admin.GET_ROUTES.items()
            },
            "POST": {
                path: route.__name__ for path, route in routes_admin.POST_ROUTES.items()
            },
        }
        self.assertEqual(EXPECTED_ADMIN_ROUTE_CALLABLES, actual)

    def test_auth_status_post_keeps_explicit_method_not_allowed_response(self) -> None:
        sent: list[tuple[int, dict[str, str]]] = []
        handler = SimpleNamespace(
            send_json=lambda status, payload: sent.append((status, payload))
        )

        routes_auth.POST_ROUTES["/admin/api/auth/status"](
            handler,
            urlparse("/admin/api/auth/status"),
        )

        self.assertEqual([(405, {"error": "method not allowed"})], sent)

    def test_json_head_preserves_utf8_length_headers_and_empty_body(self) -> None:
        probe = ResponseProbe("/health")
        payload = {"name": "\u9e93\u9e23"}
        expected = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        probe.send_json(200, payload, write_body=False)

        self.assertEqual(200, probe.status)
        self.assertTrue(probe.ended)
        self.assertEqual(b"", probe.wfile.getvalue())
        self.assertEqual(
            "application/json; charset=utf-8", probe.header("Content-Type")
        )
        self.assertEqual(str(len(expected)), probe.header("Content-Length"))
        self.assertEqual("*", probe.header("Access-Control-Allow-Origin"))
        self.assertEqual("no-cache", probe.header("Cache-Control"))
        self.assertEqual(
            "max-age=31536000; includeSubDomains",
            probe.header("Strict-Transport-Security"),
        )

    def test_admin_response_keeps_origin_security_cache_and_audit_marker(self) -> None:
        transaction = SimpleNamespace(audit_written=True, response_sent=False)
        probe = ResponseProbe(
            "/admin/api/codes",
            origin="https://admin.example",
            transaction=transaction,
        )

        probe.send_json(200, {"ok": True}, headers={"Set-Cookie": "session=value"})

        self.assertEqual(
            json.dumps({"ok": True}).encode("utf-8"), probe.wfile.getvalue()
        )
        self.assertEqual(
            "https://admin.example", probe.header("Access-Control-Allow-Origin")
        )
        self.assertEqual("Origin", probe.header("Vary"))
        self.assertEqual("no-store", probe.header("Cache-Control"))
        self.assertEqual("session=value", probe.header("Set-Cookie"))
        self.assertTrue(transaction.response_sent)

    def test_missing_file_head_keeps_error_content_length_without_body(self) -> None:
        probe = ResponseProbe("/logo.ico")
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.ico"
            expected = json.dumps(
                {"error": "file not found"}, ensure_ascii=False
            ).encode("utf-8")

            probe.send_file(200, str(missing), "image/x-icon", write_body=False)

        self.assertEqual(404, probe.status)
        self.assertEqual(str(len(expected)), probe.header("Content-Length"))
        self.assertEqual(b"", probe.wfile.getvalue())

    def test_loaded_servers_bind_isolated_patchable_handler_facades(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))

            self.assertIsNot(first.Handler, second.Handler)
            self.assertIs(first, first.Handler.facade)
            self.assertIs(second, second.Handler.facade)

            first.utc_now = lambda: "first-clock"
            second.utc_now = lambda: "second-clock"
            first_sent: list[dict[str, object]] = []
            second_sent: list[dict[str, object]] = []
            first_handler = SimpleNamespace(
                facade=first.Handler.facade,
                send_json=lambda _status, payload: first_sent.append(payload),
            )
            second_handler = SimpleNamespace(
                facade=second.Handler.facade,
                send_json=lambda _status, payload: second_sent.append(payload),
            )

            routes_public.GET_ROUTES["/health"](first_handler, urlparse("/health"))
            routes_public.GET_ROUTES["/health"](second_handler, urlparse("/health"))

            self.assertEqual("first-clock", first_sent[0]["time"])
            self.assertEqual("second-clock", second_sent[0]["time"])

    def test_log_message_print_override_is_isolated_between_server_facades(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))
            first.utc_now = lambda: "first-clock"
            second.utc_now = lambda: "second-clock"
            first_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def first_print(*args: object, **kwargs: object) -> None:
                first_calls.append((args, kwargs))

            first.print = first_print
            first_handler = SimpleNamespace(
                facade=first,
                address_string=lambda: "first-client",
            )
            second_handler = SimpleNamespace(
                facade=second,
                address_string=lambda: "second-client",
            )

            with patch("builtins.print") as builtin_print:
                http_handler.Handler.log_message(first_handler, "%s=%s", "route", 7)
                http_handler.Handler.log_message(second_handler, "%s=%s", "route", 8)

            self.assertEqual(
                [(("[first-clock] first-client route=7",), {})], first_calls
            )
            builtin_print.assert_called_once_with(
                "[second-clock] second-client route=8"
            )
            self.assertNotIn("print", second.__dict__)
            self.assertNotIn("print", http_handler.__dict__)

    def test_file_exception_override_is_isolated_between_server_facades(
        self,
    ) -> None:
        class FirstFileError(Exception):
            pass

        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))

            def first_open(_path: str, _mode: str) -> object:
                raise FirstFileError("first facade file failure")

            def second_open(_path: str, _mode: str) -> object:
                raise OSError("second facade file failure")

            first.open = first_open
            first.OSError = FirstFileError
            second.open = second_open
            expected = json.dumps(
                {"error": "file not found"}, ensure_ascii=False
            ).encode("utf-8")

            first_probe = ResponseProbe("/logo.ico", facade=first)
            first_probe.send_file(200, "first.ico", "image/x-icon", write_body=False)
            second_probe = ResponseProbe("/logo.ico", facade=second)
            second_probe.send_file(200, "second.ico", "image/x-icon")

            self.assertEqual(404, first_probe.status)
            self.assertEqual(str(len(expected)), first_probe.header("Content-Length"))
            self.assertEqual(b"", first_probe.wfile.getvalue())
            self.assertEqual(404, second_probe.status)
            self.assertEqual(expected, second_probe.wfile.getvalue())
            self.assertNotIn("OSError", second.__dict__)
            self.assertNotIn("OSError", http_responses.__dict__)

    def test_json_transport_dependency_is_isolated_between_server_facades(self) -> None:
        class FirstJson:
            def __init__(self) -> None:
                self.loads_calls: list[str] = []
                self.dumps_calls: list[tuple[dict[str, object], bool]] = []

            def loads(self, value: str) -> dict[str, str]:
                self.loads_calls.append(value)
                return {"decodedBy": "first"}

            def dumps(self, payload: dict[str, object], *, ensure_ascii: bool) -> str:
                self.dumps_calls.append((payload, ensure_ascii))
                return '{"encodedBy":"first"}'

        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))
            first_json = FirstJson()
            first.json = first_json

            first_probe = ResponseProbe("/health", facade=first)
            request_bytes = b'{"ignored":true}'
            first_probe.headers["Content-Length"] = str(len(request_bytes))
            first_probe.rfile = BytesIO(request_bytes)
            self.assertEqual({"decodedBy": "first"}, first_probe.read_json())
            first_probe.send_json(200, {"source": "first"})

            second_probe = ResponseProbe("/health", facade=second)
            second_probe.send_json(200, {"source": "second"})

            self.assertEqual(request_bytes.decode("utf-8"), first_json.loads_calls[0])
            self.assertEqual([({"source": "first"}, False)], first_json.dumps_calls)
            self.assertEqual(b'{"encodedBy":"first"}', first_probe.wfile.getvalue())
            self.assertEqual(
                json.dumps({"source": "second"}).encode("utf-8"),
                second_probe.wfile.getvalue(),
            )
            self.assertIs(json, second.json)
            self.assertNotIn("json", http_responses.__dict__)

    def test_dispatch_urlparse_fault_is_isolated_between_server_facades(self) -> None:
        class UrlparseFault(RuntimeError):
            pass

        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))

            def fail_urlparse(_value: str) -> object:
                raise UrlparseFault("first facade urlparse")

            first.urlparse = fail_urlparse
            first_handler = SimpleNamespace(
                path="/health",
                facade=first,
                send_json=lambda _status, _payload: None,
            )
            second.utc_now = lambda: "second-clock"
            second_sent: list[tuple[int, dict[str, object]]] = []
            second_handler = SimpleNamespace(
                path="/health",
                facade=second,
                send_json=lambda status, payload: second_sent.append((status, payload)),
            )

            with self.assertRaisesRegex(UrlparseFault, "first facade urlparse"):
                http_handler.dispatch(first_handler, "GET")
            http_handler.dispatch(second_handler, "GET")

            self.assertEqual([(200, {"ok": True, "time": "second-clock"})], second_sent)
            self.assertIs(urlparse, second.urlparse)
            self.assertNotIn("urlparse", http_handler.__dict__)

    def test_security_urlparse_rebinding_is_isolated_between_server_facades(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))
            first.urlparse = lambda _value: SimpleNamespace(path="/admin/injected")

            first_probe = ResponseProbe("/health", facade=first)
            second_probe = ResponseProbe("/health", facade=second)
            first_probe.send_security_headers()
            second_probe.send_security_headers()

            self.assertEqual("no-store", first_probe.header("Cache-Control"))
            self.assertEqual("no-cache", second_probe.header("Cache-Control"))
            self.assertIs(urlparse, second.urlparse)
            self.assertNotIn("urlparse", http_responses.__dict__)

    def test_file_open_dependency_is_isolated_and_preserves_head_semantics(
        self,
    ) -> None:
        class FirstFile:
            def __enter__(self) -> FirstFile:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"first-file-bytes"

        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = load_server(Path(first_dir))
            second = load_server(Path(second_dir))
            open_calls: list[tuple[str, str]] = []

            def first_open(path: str, mode: str) -> FirstFile:
                open_calls.append((path, mode))
                return FirstFile()

            first.open = first_open
            first_probe = ResponseProbe("/logo.ico", facade=first)
            first_probe.send_file(
                200, "facade-only.ico", "image/x-icon", write_body=False
            )

            real_file = Path(second_dir) / "real.ico"
            real_file.write_bytes(b"second-file-bytes")
            second_probe = ResponseProbe("/logo.ico", facade=second)
            second_probe.send_file(200, str(real_file), "image/x-icon")

            self.assertEqual([("facade-only.ico", "rb")], open_calls)
            self.assertEqual(200, first_probe.status)
            self.assertEqual(
                str(len(b"first-file-bytes")), first_probe.header("Content-Length")
            )
            self.assertEqual(b"", first_probe.wfile.getvalue())
            self.assertEqual(b"second-file-bytes", second_probe.wfile.getvalue())
            self.assertNotIn("open", second.__dict__)
            self.assertNotIn("Path", http_responses.__dict__)

    def test_normal_get_head_and_post_transport_bytes_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = load_server(Path(temp_dir))
            server.utc_now = lambda: "fixed-time"
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

            def request(method: str, path: str) -> tuple[int, bytes, object]:
                http_request = Request(base_url + path, method=method)
                try:
                    response = urlopen(http_request, timeout=5)
                    return response.status, response.read(), response.headers
                except HTTPError as error:
                    return error.code, error.read(), error.headers

            try:
                get_status, get_body, get_headers = request("GET", "/health")
                head_status, head_body, head_headers = request("HEAD", "/health")
                post_status, post_body, post_headers = request(
                    "POST", "/admin/api/auth/status"
                )
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)

        expected_get = json.dumps(
            {"ok": True, "time": "fixed-time"}, ensure_ascii=False
        ).encode("utf-8")
        expected_post = json.dumps(
            {"error": "method not allowed"}, ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual((200, expected_get), (get_status, get_body))
        self.assertEqual(str(len(expected_get)), get_headers.get("Content-Length"))
        self.assertEqual((200, b""), (head_status, head_body))
        self.assertEqual(str(len(expected_get)), head_headers.get("Content-Length"))
        self.assertEqual((405, expected_post), (post_status, post_body))
        self.assertEqual(str(len(expected_post)), post_headers.get("Content-Length"))
