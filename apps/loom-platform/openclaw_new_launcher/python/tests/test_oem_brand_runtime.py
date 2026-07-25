from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from core.license_manager import LicenseManager
from core.member_manager import MemberManager
from core.oem_brand import load_oem_brand_config
from core.paths import AppPaths


def _write_bundled_config(root: Path, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "brandId": "northstar",
        "licenseServer": "https://license.northstar.example.com",
        "purchaseFallback": "https://northstar.example.com/buy",
        "supportFallback": "https://support.northstar.example.com",
    }
    value.update(overrides)
    path = root / "_up_" / "data" / "oem-brand.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


class _Response:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OemBrandRuntimeTests(unittest.TestCase):
    def test_bundled_config_is_read_only_validated_and_not_taken_from_writable_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = _write_bundled_config(root)
            writable = root / "data" / "oem-brand.json"
            writable.parent.mkdir()
            writable.write_text(
                json.dumps({**expected, "brandId": "tampered"}),
                encoding="utf-8",
            )

            loaded = load_oem_brand_config(AppPaths(str(root)))

            self.assertEqual(loaded, expected)

    def test_invalid_bundled_config_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bundled_config(root, licenseServer="http://unsafe.example.com")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                load_oem_brand_config(AppPaths(str(root)))

    def test_license_client_uses_brand_server_and_brand_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bundled_config(root)
            manager = LicenseManager(AppPaths(str(root)))
            captured: list[str] = []

            def fake_urlopen(request, timeout=0):
                captured.append(request.full_url)
                return _Response(
                    {
                        "brandId": "northstar",
                        "purchaseUrl": "https://remote.example.com/buy",
                        "supportUrl": "https://remote.example.com/support",
                    }
                )

            with patch("core.license_manager.urllib.request.urlopen", fake_urlopen):
                result = manager.client_config()

            parsed = urllib.parse.urlparse(captured[0])
            self.assertEqual(
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                "https://license.northstar.example.com/api/client/config",
            )
            self.assertEqual(
                urllib.parse.parse_qs(parsed.query),
                {"brandId": ["northstar"]},
            )
            self.assertEqual(result["purchaseUrl"], "https://remote.example.com/buy")

    def test_network_outage_falls_back_only_to_the_bundled_brand(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bundled_config(root)
            manager = LicenseManager(AppPaths(str(root)))
            with patch(
                "core.license_manager.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                result = manager.client_config()

            self.assertEqual(
                result,
                {
                    "brandId": "northstar",
                    "purchaseUrl": "https://northstar.example.com/buy",
                    "supportUrl": "https://support.northstar.example.com",
                    "source": "bundled-fallback",
                },
            )

    def test_unknown_or_suspended_brand_response_does_not_use_local_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bundled_config(root)
            manager = LicenseManager(AppPaths(str(root)))
            body = io.BytesIO(
                json.dumps(
                    {
                        "ok": False,
                        "code": "OEM_BRAND_SUSPENDED",
                        "error": "brand suspended",
                    }
                ).encode("utf-8")
            )
            error = urllib.error.HTTPError(
                "https://license.northstar.example.com/api/client/config",
                403,
                "Forbidden",
                {},
                body,
            )
            with patch(
                "core.license_manager.urllib.request.urlopen",
                side_effect=error,
            ):
                result = manager.client_config()

            self.assertEqual(result["code"], "OEM_BRAND_SUSPENDED")
            self.assertFalse(result["ok"])

    def test_member_requests_use_brand_server_and_send_brand_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bundled_config(root)
            manager = MemberManager(AppPaths(str(root)))
            captured: dict[str, object] = {}

            def fake_request(action, payload=None, **_kwargs):
                captured["action"] = action
                captured["payload"] = payload
                return {
                    "memberId": "member-1",
                    "memberName": "Northstar member",
                    "gatewayBaseUrl": "https://gateway.example.com",
                    "memberToken": "opaque-test-token",
                }

            manager._request_json = fake_request
            manager.activate("CODE-1234")

            self.assertEqual(
                manager.service_base_url,
                "https://license.northstar.example.com",
            )
            self.assertEqual(captured["action"], "activate")
            self.assertEqual(captured["payload"]["brandId"], "northstar")


if __name__ == "__main__":
    unittest.main()
