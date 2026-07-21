from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class AgentPolicyEngineTests(unittest.TestCase):
    def test_classifies_all_action_levels_and_escalates_conditional_content(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine()

        self.assertEqual(policy.classify({"name": "loom.logs.tail", "permission": "read", "risk": "read"}, {}), "read")
        self.assertEqual(
            policy.classify({"name": "loom.matrix.dispatch", "permission": "control", "risk": "control_safe"}, {"action": "scroll"}),
            "control_safe",
        )
        self.assertEqual(
            policy.classify(
                {"name": "loom.matrix.dispatch", "permission": "control", "risk": "conditional"},
                {"prompt": "send_dm to this customer"},
            ),
            "outbound",
        )
        self.assertEqual(
            policy.classify(
                {"name": "loom.phone.control", "permission": "control", "risk": "conditional"},
                {"action": "delete_account"},
            ),
            "critical",
        )
        self.assertEqual(
            policy.classify(
                {"name": "loom.matrix.dispatch", "permission": "control", "risk": "control_safe"},
                {"prompt": "向候选人发送私信"},
            ),
            "outbound",
        )
        self.assertEqual(
            policy.classify(
                {"name": "loom.mcp.legacy.delete_account", "permission": "read", "risk": "read"},
                {"accountId": "account-1"},
            ),
            "critical",
        )

    def test_outbound_and_critical_require_approval(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine()

        outbound = policy.evaluate({"name": "loom.phone.publish", "permission": "control", "risk": "outbound"}, {})
        critical = policy.evaluate({"name": "loom.account.delete", "permission": "admin", "risk": "critical"}, {"target": {"accountId": "a1"}})

        self.assertTrue(outbound.requires_approval)
        self.assertTrue(critical.requires_approval)
        self.assertFalse(policy.evaluate({"name": "loom.matrix.status", "permission": "read", "risk": "read"}, {}).requires_approval)

    def test_free_form_and_full_matrix_dispatch_require_approval_despite_confirmed_input(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine()
        capability = {"name": "loom.matrix.dispatch", "permission": "control", "risk": "control_safe"}

        free_form = policy.evaluate(
            capability,
            {
                "prompt": "Read the current screen",
                "targets": {"deviceIds": ["phone-1"]},
                "confirmed": True,
            },
        )
        full_template = policy.evaluate(
            capability,
            {
                "templateId": "screen_read_v1",
                "mode": "full",
                "targets": {"deviceIds": ["phone-1"]},
                "confirmed": True,
            },
        )
        canonical_prompt_with_template = policy.evaluate(
            capability,
            {
                "mode": "safe",
                "targets": {"deviceIds": ["phone-1"]},
                "deviceAssignments": [
                    {
                        "deviceId": "phone-1",
                        "prompt": "Do anything needed to inspect the account",
                        "templateId": "screen_read_v1",
                    }
                ],
                "confirmed": True,
            },
        )
        bounded_template = policy.evaluate(
            capability,
            {
                "templateId": "screen_read_v1",
                "mode": "safe",
                "targets": {"deviceIds": ["phone-1"]},
            },
        )

        self.assertTrue(free_form.requires_approval)
        self.assertTrue(full_template.requires_approval)
        self.assertTrue(canonical_prompt_with_template.requires_approval)
        self.assertFalse(bounded_template.requires_approval)

    def test_weak_mode_only_requires_approval_for_critical_actions(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine(approval_mode="weak")

        outbound = policy.evaluate(
            {"name": "loom.phone.publish", "permission": "control", "risk": "outbound"},
            {"target": {"deviceIds": ["phone-1"]}, "text": "保存为草稿"},
        )
        free_form_matrix = policy.evaluate(
            {"name": "loom.matrix.dispatch", "permission": "control", "risk": "control_safe"},
            {"prompt": "打开抖音并保存草稿", "targets": {"deviceIds": ["phone-1"]}},
        )
        critical = policy.evaluate(
            {"name": "loom.account.delete", "permission": "admin", "risk": "critical"},
            {"target": {"accountId": "account-1"}},
        )

        self.assertFalse(outbound.requires_approval)
        self.assertFalse(free_form_matrix.requires_approval)
        self.assertTrue(critical.requires_approval)
        self.assertIn("explicit user request", outbound.reason.lower())

    def test_approval_is_redacted_and_scoped_to_one_exact_tool_call(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine()
        tool_input = {
            "target": {"deviceIds": ["phone-1"]},
            "message": "hello",
            "apiKey": "sk-approval-secret",
        }
        approval = policy.create_approval(
            session_id="session-1",
            run_id="run-1",
            tool_call_id="call-1",
            capability={"name": "loom.phone.publish", "permission": "control", "risk": "outbound"},
            tool_input=tool_input,
        )

        self.assertEqual(approval["schema"], "loom.agent.approval.v1")
        self.assertEqual(approval["status"], "pending")
        self.assertRegex(approval["inputHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(approval["targetsHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("sk-approval-secret", json.dumps(approval))
        self.assertFalse(policy.is_authorized(approval, "call-1", "loom.phone.publish", tool_input))

        approved = policy.resolve_approval(approval, decision="approved", decided_by="user-1")

        self.assertTrue(policy.is_authorized(approved, "call-1", "loom.phone.publish", tool_input))
        reordered_input = {
            "apiKey": "sk-approval-secret",
            "message": "hello",
            "target": {"deviceIds": ["phone-1"]},
        }
        self.assertTrue(policy.is_authorized(approved, "call-1", "loom.phone.publish", reordered_input))
        self.assertFalse(policy.is_authorized(approved, "call-2", "loom.phone.publish", tool_input))
        self.assertFalse(policy.is_authorized(approved, "call-1", "loom.phone.publish", {**tool_input, "message": "changed"}))
        self.assertFalse(
            policy.is_authorized(
                approved,
                "call-1",
                "loom.phone.publish",
                {**tool_input, "target": {"deviceIds": ["phone-2"]}},
            )
        )
        consumed = policy.consume_approval(approved, "call-1", "loom.phone.publish", tool_input)
        self.assertEqual(consumed["status"], "consumed")
        self.assertFalse(policy.is_authorized(consumed, "call-1", "loom.phone.publish", tool_input))

    def test_approval_action_summary_uses_localized_capability_name(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine()
        approval = policy.create_approval(
            session_id="session-1",
            run_id="run-1",
            tool_call_id="call-1",
            capability={
                "name": "loom.phone.publish",
                "displayName": "手机自动发布",
                "permission": "control",
                "risk": "outbound",
            },
            tool_input={"target": {"deviceIds": ["phone-1"]}},
        )

        self.assertEqual(approval["actionSummary"], "手机自动发布：执行操作")
        self.assertNotIn("loom.phone.publish", approval["actionSummary"])
        self.assertNotIn("execute via", approval["actionSummary"])

    def test_expired_or_rejected_approval_cannot_execute(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        now = datetime.now(timezone.utc)
        policy = AgentPolicyEngine(clock=lambda: now)
        approval = policy.create_approval(
            session_id="session-1",
            run_id="run-1",
            tool_call_id="call-1",
            capability={"name": "loom.phone.publish", "risk": "outbound"},
            tool_input={"target": {"deviceIds": ["phone-1"]}},
        )
        rejected = policy.resolve_approval(approval, decision="rejected", decided_by="user-1")
        approved = policy.resolve_approval(approval, decision="approved", decided_by="user-1")

        self.assertFalse(policy.is_authorized(rejected, "call-1", "loom.phone.publish", {"target": {"deviceIds": ["phone-1"]}}))
        later = AgentPolicyEngine(clock=lambda: now + timedelta(hours=1))
        self.assertFalse(later.is_authorized(approved, "call-1", "loom.phone.publish", {"target": {"deviceIds": ["phone-1"]}}))

    def test_critical_approval_requires_an_explicit_target(self) -> None:
        from core.agent_policy import AgentPolicyEngine, PolicyViolationError

        policy = AgentPolicyEngine()

        with self.assertRaises(PolicyViolationError) as caught:
            policy.create_approval(
                session_id="session-1",
                run_id="run-1",
                tool_call_id="call-1",
                capability={"name": "loom.account.delete", "risk": "critical"},
                tool_input={},
            )

        self.assertEqual(caught.exception.code, "critical_target_required")

    def test_global_critical_capability_uses_an_explicit_action_scope(self) -> None:
        from core.agent_policy import AgentPolicyEngine

        policy = AgentPolicyEngine(approval_mode="weak")
        approval = policy.create_approval(
            session_id="session-1",
            run_id="run-1",
            tool_call_id="call-1",
            capability={
                "name": "loom.settings.update.install",
                "displayName": "安装麓鸣更新",
                "risk": "critical",
                "targetScope": "none",
            },
            tool_input={},
        )

        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["targets"], {"scope": "explicit-user-action"})


if __name__ == "__main__":
    unittest.main()
