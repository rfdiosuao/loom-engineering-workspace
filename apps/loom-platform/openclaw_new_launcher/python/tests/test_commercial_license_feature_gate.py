from __future__ import annotations

import os
import sys
import unittest
from importlib import import_module


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


FEATURE_MODULE = os.path.join(PYTHON_DIR, "core", "feature_access.py")
BRIDGE_FILE = os.path.join(PYTHON_DIR, "bridge.py")
FASTAPI_ROUTES_FILE = os.path.join(PYTHON_DIR, "api", "fastapi_routes.py")
CLI_ROUTES_FILE = os.path.join(PYTHON_DIR, "api", "routes_cli.py")
DESKTOP_ROUTES_FILE = os.path.join(PYTHON_DIR, "api", "routes_desktop_agent.py")
RUST_LIB_FILE = os.path.join(os.path.dirname(PYTHON_DIR), "src-tauri", "src", "lib.rs")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def feature_module():
    return import_module("core.feature_access")


class CommercialFeaturePathContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(os.path.exists(FEATURE_MODULE), "commercial feature policy module is missing")

    def test_longest_prefix_wins_for_commercial_routes(self) -> None:
        feature_for_path = feature_module().feature_for_path
        cases = {
            "/api/matrix/acquisition/feishu/status": "acquisition.feishu",
            "/api/matrix/acquisition/feishu/create-table?confirmed=1": "acquisition.feishu",
            "/api/matrix/acquisition/templates": "templates.cloud",
            "/api/matrix/acquisition/templates/upload": "templates.cloud",
            "/api/matrix/acquisition": "acquisition.workbench",
            "/api/matrix/acquisition/agent/result": "acquisition.workbench",
            "/api/matrix/status": "matrix.devices",
            "/api/phone/task": "matrix.devices",
        }

        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(feature_for_path(path), expected)

    def test_public_and_path_lookalike_routes_are_not_protected(self) -> None:
        feature_for_path = feature_module().feature_for_path
        for path in (
            "/api/license/current",
            "/api/license/client-config",
            "/api/license/activate",
            "/api/system/info",
            "/api/diagnostics/run",
            "/api/diagnostics/export",
            "/api/agent/bootstrap",
            "/api/agent/runs/run_1/trace",
            "/api/publishing/draft",
            "/api/process/start",
            "/api/image/generate/submit",
            "/api/video/generate",
            "/api/matrixevil/status",
            "/api/phonebook/task",
        ):
            with self.subTest(path=path):
                self.assertIsNone(feature_for_path(path))
        for path in (
            "/api/matrix/cancel",
            "/api/matrix/emergency-stop",
            "/api/phone/daemon/stop",
            "/api/phone/events/stop",
        ):
            with self.subTest(path=path):
                self.assertIsNone(feature_for_path(path, method="POST"))
        self.assertEqual(feature_for_path("/api/matrix/acquisitionevil"), "matrix.devices")

    def test_method_scoped_cleanup_routes_remain_available_without_entitlement(self) -> None:
        feature_for_path = feature_module().feature_for_path
        cleanup_requests = (
            ("DELETE", "/api/phone/config/device/phone-a"),
            ("POST", "/api/phone/usb/disconnect"),
            ("POST", "/api/phone/daemon/stop"),
            ("POST", "/api/phone/events/stop"),
            ("DELETE", "/api/matrix/devices/phone-a/lease"),
            ("POST", "/api/matrix/tasks/task-a/pause"),
        )

        for method, path in cleanup_requests:
            with self.subTest(method=method, path=path):
                self.assertIsNone(feature_for_path(path, method=method))

        protected_requests = (
            ("GET", "/api/phone/config/device/phone-a"),
            ("POST", "/api/phone/usb/connect"),
            ("POST", "/api/phone/daemon/start"),
            ("POST", "/api/phone/events/start"),
            ("POST", "/api/matrix/devices/phone-a/lease"),
            ("POST", "/api/matrix/tasks/task-a/resume"),
        )
        for method, path in protected_requests:
            with self.subTest(method=method, path=path):
                self.assertEqual(feature_for_path(path, method=method), "matrix.devices")

    def test_only_explicit_phone_video_stop_cleanup_bypasses_the_phone_matrix_feature_gate(self) -> None:
        feature_for_cli_command = feature_module().feature_for_cli_command
        self.assertEqual(feature_for_cli_command("phone:publish"), "matrix.devices")
        self.assertEqual(feature_for_cli_command("loom:phone:publish"), "matrix.devices")
        self.assertEqual(feature_for_cli_command("phone:read"), "matrix.devices")
        self.assertEqual(feature_for_cli_command("openclaw:phone:status"), "matrix.devices")
        self.assertIsNone(
            feature_for_cli_command(
                "phone:video",
                ["stop", "--device-id", "phone-a", "--json"],
            )
        )
        self.assertIsNone(
            feature_for_cli_command(
                "phone:video",
                ["--device-id=phone-a", "stop"],
            )
        )
        for args in (
            ["stop"],
            ["stop", "--device-id", ""],
            ["stop", "--device-id", "phone-a", "--phone-url", "http://127.0.0.1:9527"],
            ["start", "--device-id", "phone-a"],
            ["status", "--device-id", "phone-a"],
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    feature_for_cli_command("phone:video", args),
                    "matrix.devices",
                )
        self.assertEqual(
            feature_for_cli_command(
                "loom:phone:video",
                ["stop", "--device-id", "phone-a"],
            ),
            "matrix.devices",
        )
        self.assertIsNone(feature_for_cli_command("desktop:agent"))
        self.assertIsNone(feature_for_cli_command(""))

    def test_native_preflight_mirrors_the_phone_matrix_policy(self) -> None:
        source = read_text(RUST_LIB_FILE)

        for path in (
            "api/matrix",
            "api/phone",
            "api/matrix/emergency-stop",
            "api/phone/daemon/stop",
        ):
            self.assertIn(f'"{path}"', source)
        for old_rule in (
            '("api/publishing", "publishing.draft")',
            '("api/image/generate", "image")',
            '("api/video/generate", "video")',
            '("api/process/start", "openclaw")',
        ):
            self.assertNotIn(old_rule, source)
        self.assertIn('command.starts_with("phone:")', source)
        self.assertIn('return Some("matrix.devices")', source)


class CommercialFeatureDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(os.path.exists(FEATURE_MODULE), "commercial feature policy module is missing")

    def test_denial_uses_the_exact_feature_and_stable_public_code(self) -> None:
        commercial_feature_denial = feature_module().commercial_feature_denial
        manager = RecordingLicenseManager(authorized_features=set())

        denial = commercial_feature_denial("/api/matrix/acquisition/feishu/status", manager)

        self.assertEqual(manager.requested, ["acquisition.feishu"])
        self.assertEqual(denial["code"], "LICENSE_FEATURE_REQUIRED")
        self.assertEqual(denial["feature"], "acquisition.feishu")
        self.assertNotIn("token", repr(denial).lower())

    def test_authorized_feature_and_public_routes_have_no_denial(self) -> None:
        commercial_feature_denial = feature_module().commercial_feature_denial
        manager = RecordingLicenseManager(authorized_features={"matrix.devices"})

        self.assertIsNone(commercial_feature_denial("/api/matrix/status", manager))
        self.assertIsNone(commercial_feature_denial("/api/diagnostics/export", manager))
        self.assertEqual(manager.requested, ["matrix.devices"])

    def test_denial_preserves_actionable_account_entitlement_state(self) -> None:
        commercial_feature_denial = feature_module().commercial_feature_denial
        manager = StateAwareLicenseManager(
            {
                "authorized": False,
                "source": "account_entitlement",
                "code": "authorization_required",
                "message": "当前账号尚未激活手机矩阵，请输入授权码绑定当前账号。",
                "action": "bind_authorization_code",
                "details": {
                    "accountId": "account-safe",
                    "accessToken": "must-not-leak",
                },
            }
        )

        denial = commercial_feature_denial("/api/matrix/status", manager)

        self.assertEqual("authorization_required", denial["code"])
        self.assertEqual("bind_authorization_code", denial["action"])
        self.assertEqual("account_entitlement", denial["source"])
        self.assertEqual({"accountId": "account-safe"}, denial["details"])
        self.assertNotIn("must-not-leak", repr(denial))
        self.assertEqual(["matrix.devices"], manager.requested)

    def test_gateway_account_profile_cannot_replace_a_signed_commercial_license(self) -> None:
        from core.license_manager import LicenseManager

        manager = object.__new__(LicenseManager)
        manager.current_license = lambda: None
        manager.current_gateway_profile = lambda: {
            "memberId": "account-only",
            "features": ["acquisition.workbench", "matrix.devices"],
        }

        self.assertFalse(manager.is_authorized())
        self.assertFalse(manager.is_authorized("acquisition.workbench"))

    def test_bridge_middleware_and_publish_cli_use_the_shared_policy(self) -> None:
        bridge_source = read_text(BRIDGE_FILE)
        route_source = read_text(FASTAPI_ROUTES_FILE)
        cli_source = read_text(CLI_ROUTES_FILE)
        desktop_source = read_text(DESKTOP_ROUTES_FILE)

        self.assertIn("commercial_feature_denial", bridge_source)
        self.assertIn("commercial_feature_guard", route_source)
        self.assertIn(
            "ctx.protected_error(request.url.path, method=request.method)",
            route_source,
        )
        self.assertIn("feature_for_cli_command", cli_source)
        self.assertIn("ctx.protected_error(\"/api/phone\")", cli_source)
        self.assertNotIn("get_license_mgr().is_authorized()", cli_source)
        self.assertNotIn("get_license_mgr().is_authorized()", desktop_source)
        self.assertIn("_needs_risky_policy_confirmation", desktop_source)


class RecordingLicenseManager:
    def __init__(self, authorized_features: set[str]) -> None:
        self.authorized_features = authorized_features
        self.requested: list[str] = []

    def is_authorized(self, feature: str | None = None) -> bool:
        if feature:
            self.requested.append(feature)
        return bool(feature and feature in self.authorized_features)


class StateAwareLicenseManager:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.requested: list[str] = []

    def current_state(self, feature: str | None = None) -> dict[str, object]:
        if feature:
            self.requested.append(feature)
        return dict(self.state)

    def is_authorized(self, feature: str | None = None) -> bool:
        raise AssertionError("state-aware managers must be evaluated through current_state")


if __name__ == "__main__":
    unittest.main()
