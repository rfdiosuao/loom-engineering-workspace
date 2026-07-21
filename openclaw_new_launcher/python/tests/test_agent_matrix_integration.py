from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.paths import AppPaths
from core.agent_policy import AgentPolicyEngine
from core.phone_matrix import MatrixControlPlane
from services.agent_service import AgentService


class MatrixDispatchRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def status(self, profile_id=None):
        return {"available": True, "profileId": profile_id or "default", "runtime": "integration-test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "toolCalls": [{
                    "toolCallId": "matrix-call-1",
                    "name": "loom.matrix.dispatch",
                    "input": {
                        "prompt": "Read the current screen",
                        "mode": "observe",
                        "targets": {"deviceIds": ["phone-a", "phone-b"]},
                    },
                }]
            }
        return {"final": {"text": "The Matrix campaign was created."}}


class EscapingPhoneRuntime:
    def status(self, profile_id=None):
        return {"available": True, "profileId": profile_id or "default", "runtime": "integration-test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        return {
            "toolCalls": [{
                "toolCallId": "phone-scope-escape",
                "name": "loom.mcp.loom.loom_phone_quick_task",
                "input": {"deviceId": "phone-attacker", "prompt": "Open settings"},
            }]
        }


class AgentMatrixIntegrationTests(unittest.TestCase):
    def test_agent_dispatch_creates_real_campaign_and_replayable_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            matrix = MatrixControlPlane(paths)
            matrix.register_device({"deviceId": "phone-a", "online": True, "group": "recruiting"})
            matrix.register_device({"deviceId": "phone-b", "online": True, "group": "recruiting"})
            service = AgentService(
                paths,
                runtime=MatrixDispatchRuntime(),
                policy=AgentPolicyEngine(approval_mode="strong"),
            )
            try:
                session = service.create_session({"title": "Recruiting Matrix"})
                response = service.send_message(session["sessionId"], {
                    "clientMessageId": "agent-matrix-client-1",
                    "text": "Read phone-a and phone-b",
                    "scopeMode": "auto",
                })
                deadline = time.monotonic() + 3
                run = response["run"]
                while time.monotonic() < deadline:
                    run = service.get_run(run["runId"])
                    if run["status"] in {"waiting_approval", "failed"}:
                        break
                    time.sleep(0.01)

                self.assertEqual(run["status"], "waiting_approval")
                approval = service.get_trace(run["runId"])["approvals"][0]
                outcome = service.resolve_approval(
                    approval["approvalId"],
                    {"decision": "approved", "operator": "local-user"},
                )
                run = outcome["run"]

                self.assertEqual(run["status"], "completed")
                self.assertEqual(len(run["campaignIds"]), 1)
                campaign_id = run["campaignIds"][0]
                status = matrix.status()
                self.assertTrue(any(item.get("campaignId") == campaign_id for item in status["campaigns"]))

                events = service.events_after(session_id=session["sessionId"], after_seq=0)
                attachment = next(item for item in events if item["type"] == "matrix.attached")
                self.assertEqual(attachment["topic"], "matrix.campaign")
                self.assertEqual(attachment["entityId"], campaign_id)
                self.assertEqual(attachment["data"]["counts"]["total"], 2)
                self.assertTrue(any(node["kind"] == "matrix" for node in service.get_trace(run["runId"])["trace"]))
            finally:
                service.shutdown()

    def test_native_phone_tool_cannot_escape_the_agent_request_scope(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            paths = AppPaths(root)
            MatrixControlPlane(paths).register_device({"deviceId": "phone-a", "online": True})
            service = AgentService(paths, runtime=EscapingPhoneRuntime())
            try:
                session = service.create_session({"title": "Phone scope"})
                response = service.send_message(session["sessionId"], {
                    "clientMessageId": "phone-scope-client-1",
                    "text": "Open settings on phone-a",
                    "targets": {"deviceIds": ["phone-a"]},
                })
                deadline = time.monotonic() + 3
                run = response["run"]
                while time.monotonic() < deadline:
                    run = service.get_run(run["runId"])
                    if run["status"] in {"failed", "waiting_approval", "completed"}:
                        break
                    time.sleep(0.01)

                self.assertEqual(run["status"], "failed")
                self.assertEqual(run["error"]["code"], "phone_target_scope_required")
                self.assertEqual(service.get_trace(run["runId"])["approvals"], [])
            finally:
                service.shutdown()


if __name__ == "__main__":
    unittest.main()
