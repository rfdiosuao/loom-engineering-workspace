from __future__ import annotations

import os
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PYTHON_DIR)
GATE_FILE = os.path.join(REPO_ROOT, "src", "components", "license", "licenseGate.ts")
STORE_FILE = os.path.join(REPO_ROOT, "src", "stores", "appStore.ts")
API_FILE = os.path.join(REPO_ROOT, "src", "services", "api.ts")
TYPES_FILE = os.path.join(REPO_ROOT, "src", "types", "index.ts")
PAYWALL_FILE = os.path.join(REPO_ROOT, "src", "components", "license", "LicensePaywall.tsx")
VISUAL_FIXTURE_FILE = os.path.join(REPO_ROOT, "src", "components", "license", "licenseVisualFixture.ts")
APP_FILE = os.path.join(REPO_ROOT, "src", "App.tsx")
PAGES_FILE = os.path.join(REPO_ROOT, "src", "features", "pages.tsx")
MATRIX_ACCESS_GATE_FILE = os.path.join(
    REPO_ROOT,
    "src",
    "components",
    "license",
    "PhoneMatrixAccessGate.tsx",
)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class CommercialLicenseGateStateContractTests(unittest.TestCase):
    def test_gate_has_finite_explicit_states_and_normalizer(self) -> None:
        self.assertTrue(os.path.exists(GATE_FILE), "license gate state module is missing")
        source = read_text(GATE_FILE)

        for status in (
            "checking",
            "authorized",
            "unauthorized",
            "expired",
            "disabled",
            "device_mismatch",
            "offline_grace",
            "service_error",
        ):
            self.assertIn(f"'{status}'", source)

        self.assertIn("export function normalizeLicenseGate", source)
        self.assertIn("LICENSE_CHECK_TIMEOUT_MS", source)
        self.assertIn("LICENSE_EXPIRED", source)
        self.assertIn("DEVICE_MISMATCH", source)
        self.assertIn("LICENSE_DISABLED", source)

    def test_store_uses_signed_license_gate_without_gateway_profile_bypass(self) -> None:
        source = read_text(STORE_FILE)
        gate_source = read_text(GATE_FILE)

        self.assertIn("licenseGate", source)
        self.assertIn("normalizeLicenseGate", source)
        self.assertIn("withLicenseCheckTimeout", source)
        self.assertIn("license?.signature", gate_source)
        self.assertNotIn("setAuthorized:", source)
        self.assertNotIn("setLicenseInfo:", source)
        self.assertNotIn("else if (gatewayProfile", source)
        self.assertNotIn("gatewayProfile as License", source)

    def test_license_checks_ignore_stale_out_of_order_results(self) -> None:
        source = read_text(STORE_FILE)

        self.assertIn("let licenseCheckGeneration = 0", source)
        self.assertIn("const checkGeneration = ++licenseCheckGeneration", source)
        self.assertGreaterEqual(
            source.count("if (checkGeneration !== licenseCheckGeneration) return"),
            2,
        )

    def test_api_and_types_expose_typed_commercial_license_fields(self) -> None:
        api_source = read_text(API_FILE)
        types_source = read_text(TYPES_FILE)

        self.assertIn("LicenseCurrentResponse", api_source)
        self.assertIn("LicenseClientConfig", api_source)
        self.assertIn("LicenseAuthorizationResponse", api_source)
        self.assertIn("LicenseActivationResponse", api_source)
        self.assertIn("expiresAt?: string | null", types_source)
        self.assertIn("deviceLimit?: number", types_source)
        self.assertIn("status?: string", types_source)
        self.assertIn("code?: string", types_source)


class CommercialLicensePaywallUiContractTests(unittest.TestCase):
    def test_visual_state_fixture_is_strictly_development_only(self) -> None:
        self.assertTrue(os.path.exists(VISUAL_FIXTURE_FILE), "license visual fixture is missing")
        source = read_text(VISUAL_FIXTURE_FILE)
        store_source = read_text(STORE_FILE)

        self.assertIn("import.meta.env.DEV", source)
        self.assertIn("licenseState", source)
        self.assertIn("getDevLicenseFixture", source)
        self.assertIn("getDevLicenseFixture", store_source)

    def test_paywall_exposes_activation_identity_diagnostics_and_commercial_links(self) -> None:
        self.assertTrue(os.path.exists(PAYWALL_FILE), "commercial paywall component is missing")
        source = read_text(PAYWALL_FILE)

        for marker in (
            "data-license-paywall",
            "data-license-status",
            "data-license-code-input",
            "data-license-activate",
            "data-license-install-id",
            "data-license-copy-install-id",
            "data-license-diagnostics-export",
            "data-license-purchase-link",
            "data-license-support-link",
        ):
            self.assertIn(marker, source)

        self.assertIn('type="password"', source)
        self.assertIn("licenseApi.activate", source)
        self.assertIn("diagnosticsApi.export", source)
        self.assertIn("navigator.clipboard.writeText", source)
        self.assertIn("safeCommercialUrl", source)
        self.assertNotIn("gatewayAccessToken", source)
        self.assertNotIn("gatewayToken", source)

    def test_app_shell_stays_available_and_phone_matrix_owns_the_paywall(self) -> None:
        source = read_text(APP_FILE)
        pages = read_text(PAGES_FILE)
        matrix_gate = read_text(MATRIX_ACCESS_GATE_FILE)

        self.assertIn("data-commercial-app-shell", source)
        self.assertIn("const visiblePage = currentPage", source)
        self.assertNotIn("commercialAccessGranted", source)
        self.assertNotIn("LicensePaywall", source)
        self.assertIn("PhoneMatrixAccessGate", pages)
        self.assertIn("phone: PhoneConnectionPage", pages)
        self.assertIn("workbench: GuardedMatrixWorkbenchPage", pages)
        self.assertIn("licenseApi.authorized('matrix.devices')", matrix_gate)
        self.assertIn("matrixApi.emergencyStop({ all: true })", matrix_gate)
        self.assertIn('scope="phone-matrix"', matrix_gate)
        self.assertIn("data-license-offline-banner", matrix_gate)
        self.assertIn("data-license-emergency-stop", read_text(PAYWALL_FILE))


if __name__ == "__main__":
    unittest.main()
