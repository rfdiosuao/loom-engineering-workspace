from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from _support import LICENSE_SERVER_ROOT  # noqa: F401
from luming_license.domains import activations, licenses
from test_license_flow import load_server


class LicenseDomainModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_license_and_activation_functions_have_single_owners(self) -> None:
        self.assertEqual("luming_license.domains.licenses", licenses.create_code_records.__module__)
        self.assertEqual("luming_license.domains.licenses", licenses.get_code_secret_rows.__module__)
        self.assertEqual("luming_license.domains.activations", activations.activate_code.__module__)
        self.assertEqual("luming_license.domains.activations", activations.member_response.__module__)

    def test_created_code_activates_with_same_public_fields(self) -> None:
        expires = (date.today() + timedelta(days=30)).isoformat()
        code = self.server.create_code_records(
            count=1,
            licensee="Module Customer",
            edition="pro",
            features=["openclaw", "acquisition.workbench"],
            expires=expires,
            max_activations=1,
        )[0]

        result = self.server.activate_code(
            {"code": code, "installId": "module-install", "deviceId": "module-device"}
        )

        self.assertEqual("Module Customer", result["licensee"])
        self.assertEqual(expires, result["expires"])
        self.assertNotIn("privateKey", str(result))

    def test_loaded_server_feature_lists_are_isolated_from_each_other_and_domain_defaults(self) -> None:
        expected_commercial = list(licenses.COMMERCIAL_FEATURES)
        expected_default = list(licenses.DEFAULT_FEATURES)
        expected_vip = list(licenses.VIP_DEFAULT_FEATURES)
        with tempfile.TemporaryDirectory() as second_directory:
            second_server = load_server(Path(second_directory))

            self.server.COMMERCIAL_FEATURES.append("first-only-commercial")
            self.server.DEFAULT_FEATURES.append("first-only-default")
            self.server.VIP_DEFAULT_FEATURES.append("first-only-vip")

            self.assertEqual(expected_commercial, second_server.COMMERCIAL_FEATURES)
            self.assertEqual(expected_default, second_server.DEFAULT_FEATURES)
            self.assertEqual(expected_vip, second_server.VIP_DEFAULT_FEATURES)
            self.assertEqual(expected_commercial, licenses.COMMERCIAL_FEATURES)
            self.assertEqual(expected_default, licenses.DEFAULT_FEATURES)
            self.assertEqual(expected_vip, licenses.VIP_DEFAULT_FEATURES)
            self.assertIsInstance(second_server.COMMERCIAL_FEATURES, list)
            self.assertIsInstance(second_server.DEFAULT_FEATURES, list)
            self.assertIsInstance(second_server.VIP_DEFAULT_FEATURES, list)

            code = second_server.create_code_records(
                count=1,
                licensee="Isolated Defaults",
                edition="pro",
                features=second_server.parse_features(""),
                expires=(date.today() + timedelta(days=30)).isoformat(),
                max_activations=1,
            )[0]
            row = next(item for item in second_server.get_code_rows() if item["codeHash"] == second_server.code_hash(code))
            self.assertEqual(expected_default, row["features"])

    def test_simultaneous_activations_never_exceed_the_code_limit(self) -> None:
        max_activations = 3
        attempt_count = 16
        code = self.server.create_code_records(
            count=1,
            licensee="Concurrent Customer",
            edition="pro",
            features=["openclaw"],
            expires=(date.today() + timedelta(days=30)).isoformat(),
            max_activations=max_activations,
        )[0]
        start = threading.Barrier(attempt_count)

        def activate(index: int) -> tuple[str, object]:
            start.wait(timeout=10)
            try:
                return (
                    "ok",
                    self.server.activate_code(
                        {
                            "code": code,
                            "installId": f"concurrent-install-{index}",
                            "deviceId": f"concurrent-device-{index}",
                        }
                    ),
                )
            except self.server.ActivationError as error:
                return ("error", (error.status, error.code, str(error)))

        with ThreadPoolExecutor(max_workers=attempt_count) as executor:
            futures = [executor.submit(activate, index) for index in range(attempt_count)]
            results = [future.result(timeout=20) for future in futures]

        successful = [value for status, value in results if status == "ok"]
        failures = [value for status, value in results if status == "error"]
        self.assertLessEqual(len(successful), max_activations)
        self.assertEqual(max_activations, len(successful))
        self.assertEqual(
            [(403, "DEVICE_MISMATCH", "授权码已被其他设备激活")] * (attempt_count - max_activations),
            failures,
        )
        self.assertTrue(all(isinstance(item, dict) and "payload" not in item for item in successful))
        self.assertTrue(all(item["licensee"] == "Concurrent Customer" for item in successful))
        self.assertTrue(all("signature" in item for item in successful))
        with self.server.connect() as connection:
            row_count = connection.execute(
                "select count(*) from activations where code_hash = ?",
                (self.server.code_hash(code),),
            ).fetchone()[0]
        self.assertEqual(max_activations, row_count)
