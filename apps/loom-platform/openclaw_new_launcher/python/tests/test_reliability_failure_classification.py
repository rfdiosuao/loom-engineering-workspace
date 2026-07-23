from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ReliabilityFailureClassificationTests(unittest.TestCase):
    def test_managed_account_login_is_actionable_and_not_retryable(self) -> None:
        from core.reliability import classify_failure

        failure = classify_failure({"error": {"code": "AGENT_ACCOUNT_LOGIN_REQUIRED"}})

        self.assertEqual(failure["class"], "account_login_required")
        self.assertFalse(failure["retryable"])

    def test_provider_http_failures_have_distinct_classes(self) -> None:
        from core.reliability import classify_failure

        cases = (
            ("ImageApiError: HTTP 429", "provider_rate_limited"),
            ("ImageApiError: HTTP 524", "provider_timeout"),
            ("model provider HTTP 503", "provider_unavailable"),
            ("model gateway HTTP 401", "provider_auth_failed"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(classify_failure({"error": message})["class"], expected)

    def test_device_signature_error_keeps_device_auth_class(self) -> None:
        from core.reliability import classify_failure

        failure = classify_failure({"error": "invalid lumi signature HTTP 401"})

        self.assertEqual(failure["class"], "auth_signature")

    def test_provider_auth_code_does_not_require_http_text(self) -> None:
        from core.reliability import classify_failure

        failure = classify_failure({"code": "PROVIDER_AUTH_FAILED", "message": "credential rejected"})

        self.assertEqual(failure["class"], "provider_auth_failed")
        self.assertFalse(failure["retryable"])


if __name__ == "__main__":
    unittest.main()
