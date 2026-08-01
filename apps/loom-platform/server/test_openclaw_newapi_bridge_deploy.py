from __future__ import annotations

import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
DEPLOY_SCRIPT = SERVER_ROOT / "deploy.sh"


class BridgeDeployScriptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_uses_discovered_production_defaults_and_rejects_root(self) -> None:
        self.assertIn("/opt/openclaw-newapi-bridge", self.source)
        self.assertIn("openclaw-newapi-bridge", self.source)
        self.assertIn("http://127.0.0.1:3016", self.source)
        self.assertIn("BRIDGE_REMOTE_DIR must be absolute", self.source)
        self.assertIn("refusing to deploy into filesystem root", self.source)

    def test_required_entitlement_configuration_is_checked_before_stop(self) -> None:
        for key in (
            "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN",
            "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_BASE",
            "OPENCLAW_BIND_DB",
            "OPENCLAW_BIND_TICKET_SECRET",
            "OPENCLAW_ENTITLEMENT_KEY_ID",
        ):
            self.assertIn(key, self.source)
        self.assertIn("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_FILE", self.source)
        self.assertIn("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_B64", self.source)
        preflight = self.source.index("entitlement_config=ready")
        switch_step = self.source.index("[4/7] Guarded atomic program switch")
        service_stop = self.source.index('systemctl stop "$SERVICE_NAME"', switch_step)
        self.assertLess(preflight, service_stop)
        self.assertNotIn('source "$BRIDGE_ENV_FILE"', self.source)
        self.assertNotIn('. "$BRIDGE_ENV_FILE"', self.source)

    def test_program_switch_has_failure_rollback_and_preserves_environment(self) -> None:
        self.assertIn('cp -a "$REMOTE_DIR/openclaw_newapi_bridge.py"', self.source)
        self.assertIn('cp -a "$BRIDGE_ENV_FILE"', self.source)
        self.assertIn('mv "$REMOTE_DIR/openclaw_newapi_bridge.py"', self.source)
        self.assertIn('mv "$REMOTE_DIR/.openclaw_newapi_bridge.py.pre-deploy"', self.source)
        self.assertIn("environment_unchanged=verified", self.source)
        self.assertNotIn("> \"$BRIDGE_ENV_FILE\"", self.source)

    def test_candidate_is_compiled_before_switch(self) -> None:
        self.assertIn("BRIDGE_SERVER_UPLOAD", self.source)
        self.assertIn("python3 -m py_compile", self.source)
        compile_step = self.source.index("python3 -m py_compile")
        switch_step = self.source.index("[4/7] Guarded atomic program switch")
        service_stop = self.source.index('systemctl stop "$SERVICE_NAME"', switch_step)
        self.assertLess(compile_step, service_stop)

    def test_post_switch_smoke_requires_health_and_public_key_contract(self) -> None:
        self.assertIn("/health", self.source)
        self.assertIn("/api/openclaw/entitlements/public-key", self.source)
        self.assertIn("openclaw-newapi-bridge", self.source)
        self.assertIn("openclaw-ed25519-v1", self.source)
        self.assertIn("entitlement_public_key=ready", self.source)


if __name__ == "__main__":
    unittest.main()
