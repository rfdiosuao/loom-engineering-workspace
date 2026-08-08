from __future__ import annotations

import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT


DEPLOY_SCRIPT = LICENSE_SERVER_ROOT / "deploy.sh"


class DeployScriptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_deploys_and_rolls_back_server_and_modular_package_together(self) -> None:
        self.assertIn("LICENSE_PACKAGE_UPLOAD", self.source)
        self.assertIn('test -d "$PACKAGE_UPLOAD"', self.source)
        self.assertIn('find "$PACKAGE_UPLOAD" -type f -name \'*.py\'', self.source)
        self.assertIn('cp -a "$PACKAGE_UPLOAD"', self.source)
        self.assertIn('systemctl stop "$SERVICE_NAME"', self.source)
        self.assertIn('mv "$REMOTE_DIR/luming_license"', self.source)
        self.assertIn('mv "$REMOTE_DIR/.luming_license.pre-deploy"', self.source)

    def test_relay_token_update_preserves_existing_entitlement_configuration(self) -> None:
        self.assertIn("luming_license/deploy_env.py", self.source)
        self.assertIn("DEPLOY_ENV_FILE", self.source)
        self.assertNotIn(
            'with open(os.environ["RELAY_ENV_FILE"], "w"',
            self.source,
        )

    def test_post_switch_smoke_requires_entitlement_route_to_exist(self) -> None:
        self.assertIn("/api/service/account-entitlements/current", self.source)
        self.assertIn("entitlement_route=ready", self.source)

    def test_payment_route_is_required_before_switch_and_smoked_after_switch(self) -> None:
        self.assertIn(
            'test -f "$PACKAGE_UPLOAD/http/routes_payments.py"',
            self.source,
        )
        payment_module_check = self.source.index(
            'test -f "$PACKAGE_UPLOAD/http/routes_payments.py"'
        )
        switch_section = self.source.index('echo "[5/8] Guarded atomic program switch"')
        program_stop = self.source.index(
            'systemctl stop "$SERVICE_NAME"', switch_section
        )
        self.assertLess(payment_module_check, program_stop)
        self.assertIn("/api/service/payments/plans", self.source)
        self.assertIn("payment_route=ready", self.source)

    def test_zpay_readiness_is_opt_in_and_validated_before_program_stop(self) -> None:
        self.assertIn("LICENSE_REQUIRE_ZPAY_READY", self.source)
        self.assertIn("DEPLOY_ENV_VALIDATE_ZPAY", self.source)
        zpay_validation = self.source.index("DEPLOY_ENV_VALIDATE_ZPAY")
        switch_section = self.source.index('echo "[5/8] Guarded atomic program switch"')
        program_stop = self.source.index(
            'systemctl stop "$SERVICE_NAME"', switch_section
        )
        self.assertLess(zpay_validation, program_stop)
        self.assertNotIn('source "$RELAY_ENV_FILE"', self.source)
        self.assertNotIn('cat "$RELAY_ENV_FILE"', self.source)

    def test_systemd_dropin_path_is_overrideable_for_isolated_rehearsal(self) -> None:
        self.assertIn("LICENSE_SYSTEMD_DROPIN_DIR", self.source)
        self.assertIn(
            'dropin_dir="${LICENSE_SYSTEMD_DROPIN_DIR:-/etc/systemd/system/${SERVICE_NAME}.service.d}"',
            self.source,
        )

    def test_post_switch_smoke_waits_for_service_readiness(self) -> None:
        self.assertIn("LICENSE_HEALTH_RETRY_ATTEMPTS", self.source)
        self.assertIn("LICENSE_HEALTH_RETRY_DELAY_SEC", self.source)
        self.assertIn("wait_for_health", self.source)
        self.assertIn('sleep "$HEALTH_RETRY_DELAY_SEC"', self.source)

    def test_environment_change_is_rolled_back_even_before_program_switch(self) -> None:
        self.assertIn(
            'if [ "$status" -ne 0 ] && [ "$relay_updated" -eq 1 ]',
            self.source,
        )
        relay_restore = self.source.index(
            'if [ "$status" -ne 0 ] && [ "$relay_updated" -eq 1 ]'
        )
        program_restore = self.source.index(
            'if [ "$status" -ne 0 ] && [ "$switched" -eq 1 ]'
        )
        self.assertLess(relay_restore, program_restore)
