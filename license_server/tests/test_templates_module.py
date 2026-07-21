from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT

from luming_license.domains import templates
from test_license_flow import load_server


class TemplatesModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = load_server(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_beta_and_template_operations_have_a_domain_owner(self) -> None:
        self.assertEqual("luming_license.domains.templates", templates.beta_claim_code.__module__)
        self.assertEqual("luming_license.domains.templates", templates.save_template.__module__)

    def test_default_templates_seed_idempotently(self) -> None:
        self.server.seed_default_templates()
        first = self.server.list_templates()
        self.server.seed_default_templates()
        self.assertEqual(first, self.server.list_templates())

    def test_beta_status_never_reports_negative_remaining(self) -> None:
        self.server.set_beta_config({"dailyQuota": 0})
        status = self.server.beta_status_snapshot()
        self.assertGreaterEqual(status["remaining"], 0)

    def test_beta_claim_uses_the_server_facade_for_nested_dependencies(self) -> None:
        self.server.set_beta_config({"dailyQuota": 1, "validDays": 2})

        claim = self.server.beta_claim_code("127.0.0.1")

        self.assertFalse(claim["repeat"])
        self.assertEqual(0, claim["remaining"])
        self.assertEqual(2, claim["validDays"])
        repeated = self.server.beta_claim_code("127.0.0.1")
        self.assertTrue(repeated["repeat"])
        self.assertEqual(claim["code"], repeated["code"])
        self.assertEqual(claim["expires"], repeated["expires"])

    def test_concurrent_same_ip_beta_claim_has_one_code_and_one_claim(self) -> None:
        self.server.set_beta_config({"dailyQuota": 2, "validDays": 2})
        original_create = self.server.create_code_records
        creators = threading.Barrier(2)

        def synchronized_create(**kwargs: object) -> list[str]:
            try:
                creators.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
            return original_create(**kwargs)

        self.server.create_code_records = synchronized_create
        self.addCleanup(setattr, self.server, "create_code_records", original_create)
        start = threading.Barrier(3)
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []
        result_lock = threading.Lock()

        def claim() -> None:
            start.wait(timeout=2)
            try:
                result = self.server.beta_claim_code("198.51.100.20")
                with result_lock:
                    results.append(result)
            except BaseException as error:
                with result_lock:
                    errors.append(error)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        start.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertEqual([False, True], sorted(result["repeat"] for result in results))
        self.assertEqual(1, len({result["code"] for result in results}))
        with self.server.connect() as conn:
            self.assertEqual(1, conn.execute("select count(*) from codes").fetchone()[0])
            self.assertEqual(1, conn.execute("select count(*) from beta_claims").fetchone()[0])

    def test_concurrent_two_ip_beta_claims_respect_quota_one(self) -> None:
        self.server.set_beta_config({"dailyQuota": 1, "validDays": 2})
        original_create = self.server.create_code_records
        creators = threading.Barrier(2)

        def synchronized_create(**kwargs: object) -> list[str]:
            try:
                creators.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
            return original_create(**kwargs)

        self.server.create_code_records = synchronized_create
        self.addCleanup(setattr, self.server, "create_code_records", original_create)
        start = threading.Barrier(3)
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []
        result_lock = threading.Lock()

        def claim(ip: str) -> None:
            start.wait(timeout=2)
            try:
                result = self.server.beta_claim_code(ip)
                with result_lock:
                    results.append(result)
            except BaseException as error:
                with result_lock:
                    errors.append(error)

        threads = [
            threading.Thread(target=claim, args=("198.51.100.21",)),
            threading.Thread(target=claim, args=("198.51.100.22",)),
        ]
        for thread in threads:
            thread.start()
        start.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(1, len(results))
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], self.server.ActivationError)
        self.assertEqual(429, errors[0].status)
        with self.server.connect() as conn:
            self.assertEqual(1, conn.execute("select count(*) from codes").fetchone()[0])
            self.assertEqual(1, conn.execute("select count(*) from beta_claims").fetchone()[0])

    def test_beta_claim_rolls_back_issued_code_when_later_step_fails(self) -> None:
        self.server.set_beta_config({"dailyQuota": 1, "validDays": 2})
        original_create = self.server.create_code_records

        def create_then_fail(**kwargs: object) -> list[str]:
            original_create(**kwargs)
            raise RuntimeError("injected beta claim failure")

        self.server.create_code_records = create_then_fail
        self.addCleanup(setattr, self.server, "create_code_records", original_create)

        with self.assertRaisesRegex(RuntimeError, "injected beta claim failure"):
            self.server.beta_claim_code("198.51.100.23")

        with self.server.connect() as conn:
            self.assertEqual(0, conn.execute("select count(*) from codes").fetchone()[0])
            self.assertEqual(0, conn.execute("select count(*) from beta_claims").fetchone()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
