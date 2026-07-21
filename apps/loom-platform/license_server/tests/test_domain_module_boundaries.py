from __future__ import annotations

import unittest

from _support import LICENSE_SERVER_ROOT
from luming_license import audit
from luming_license.domains import accounts, sessions


class DomainModuleBoundaryTests(unittest.TestCase):
    def test_identity_and_audit_functions_have_single_owners(self) -> None:
        self.assertEqual("luming_license.domains.accounts", accounts.create_account_record.__module__)
        self.assertEqual("luming_license.domains.sessions", sessions.create_admin_session.__module__)
        self.assertEqual("luming_license.audit", audit.add_audit_log.__module__)

    def test_audit_masks_nested_secret_keys(self) -> None:
        masked = audit.audit_public_value({"gatewayToken": "secret", "nested": {"apiKey": "secret-2"}})
        self.assertNotIn("secret", str(masked))
        self.assertNotIn("secret-2", str(masked))

    def test_audit_redacts_invite_keys_and_credentials_inside_values(self) -> None:
        invite = "INV-ABCD-EFGH-JKLM-NPQR"

        masked = audit.audit_public_value(
            {
                "inviteCode": invite,
                "rawInviteCode": invite,
                "note": f"sales handoff invite:{invite} retained",
                "nested": [f"credential={invite}", "public context"],
            }
        )

        serialized = str(masked)
        self.assertNotIn(invite, serialized)
        self.assertEqual("[REDACTED]", masked["inviteCode"])
        self.assertEqual("[REDACTED]", masked["rawInviteCode"])
        self.assertIn("sales handoff", masked["note"])
        self.assertIn("retained", masked["note"])
        self.assertIn("public context", serialized)
