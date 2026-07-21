from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_capabilities import CapabilityRegistry
from core.loom_model_client import LoomModelClient
from core.native_agent_runtime import LoomNativeRuntimeAdapter
from core.paths import AppPaths
from services.agent_service import AgentService


class FakeAccount:
    def __init__(self, session: dict) -> None:
        self.session = session

    def current(self) -> dict:
        return self.session

    def ensure_launcher_token(self, *, sync_runtime: bool = False, force_refresh: bool = False) -> dict:
        return self.session


def managed_session() -> dict:
    return {
        "source": "newapi_account",
        "gatewayBaseUrl": "https://gateway.example/v1",
        "memberToken": "fixture-native-integration-token",
        "gatewayDefaultModel": "glm-managed",
        "gateway": {
            "baseUrl": "https://gateway.example/v1",
            "accessToken": "fixture-native-integration-token",
            "defaultModel": "glm-managed",
        },
    }


class TwoRoundTransport:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def stream(self, _profile, payload, _cancel, *, timeout_sec):
        self.requests.append({"payload": dict(payload), "timeoutSec": timeout_sec})
        round_index = len(self.requests)
        if round_index == 1:
            yield {
                "choices": [{"delta": {"tool_calls": [{
                    "index": 0,
                    "id": "call_read_1",
                    "function": {"name": "loom_test_read", "arguments": "{}"},
                }]}}],
            }
            return
        if round_index == 2:
            yield {"choices": [{"delta": {"content": "\u72b6\u6001\u6b63\u5e38"}}]}
            yield {"usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}}
            return
        raise AssertionError(f"unexpected native model round: {round_index}")


def wait_for_status(service: AgentService, run_id: str, status: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if run["status"] == status:
            return run
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {status}: {service.get_run(run_id)}")


class NativeAgentIntegrationTests(unittest.TestCase):
    def test_managed_model_completes_safe_internal_tool_loop_without_external_process(self) -> None:
        executions: list[dict] = []
        transport = TwoRoundTransport()
        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.read": {
                    "description": "Read test status",
                    "permission": "read",
                    "risk": "read",
                    "executor": lambda payload: executions.append(dict(payload)) or {"status": "ok"},
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )
        client = LoomModelClient(FakeAccount(managed_session()), transport=transport)
        model_results: list[dict] = []
        complete = client.complete

        def record_complete(*args, **kwargs):
            result = complete(*args, **kwargs)
            model_results.append(result)
            return result

        client.complete = record_complete

        with tempfile.TemporaryDirectory() as root:
            with patch.object(subprocess, "Popen") as popen, patch.object(subprocess, "run") as run_process:
                service = AgentService(AppPaths(root), model_client=client, capabilities=registry)
                try:
                    self.assertIsInstance(service.runtime, LoomNativeRuntimeAdapter)
                    session = service.create_session({"title": "Native"})
                    sent = service.send_message(
                        session["sessionId"],
                        {"clientMessageId": "client_1", "text": "Read test status"},
                    )
                    completed = wait_for_status(service, sent["run"]["runId"], "completed")
                    detail = service.session_detail(session["sessionId"])
                    trace = service.get_trace(sent["run"]["runId"])
                    events = service.events_after(session_id=session["sessionId"], after_seq=0)
                    bootstrap = service.bootstrap()
                finally:
                    service.shutdown()

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(session["runtimeProfileId"], "loom-native")
        self.assertEqual(detail["session"]["runtimeProfileId"], "loom-native")
        self.assertEqual(
            detail["messages"][-1]["blocks"][0]["data"]["text"],
            "\u72b6\u6001\u6b63\u5e38",
        )
        self.assertEqual(executions, [{}])
        tool_nodes = [node for node in trace["trace"] if node["name"].startswith("tool.")]
        self.assertEqual(len(tool_nodes), 1)
        self.assertEqual(tool_nodes[0]["name"], "tool.completed")
        self.assertEqual(tool_nodes[0]["status"], "completed")
        self.assertEqual(tool_nodes[0]["eventCount"], 3)
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(transport.requests[0]["payload"]["metadata"]["idempotencyKey"].rsplit(":", 1)[1], "1")
        sent_tool_names = {
            item["function"]["name"]
            for item in transport.requests[0]["payload"]["tools"]
        }
        self.assertIn("loom_test_read", sent_tool_names)
        self.assertIn("麓鸣原生中枢智能体", transport.requests[0]["payload"]["messages"][0]["content"])
        second_payload = transport.requests[1]["payload"]
        self.assertEqual(second_payload["metadata"]["idempotencyKey"].rsplit(":", 1)[1], "2")
        assistant_tool_message = next(
            message for message in second_payload["messages"]
            if message.get("role") == "assistant" and message.get("tool_calls")
        )
        tool_call = assistant_tool_message["tool_calls"][0]
        self.assertEqual(tool_call["id"], "call_read_1")
        self.assertEqual(tool_call["function"]["name"], "loom_test_read")
        tool_result_message = next(
            message for message in second_payload["messages"]
            if message.get("role") == "tool" and message.get("tool_call_id") == "call_read_1"
        )
        self.assertEqual(json.loads(tool_result_message["content"]), {
            "status": "completed",
            "result": {"status": "ok"},
        })
        self.assertEqual(transport.requests[1]["timeoutSec"], 120.0)
        self.assertEqual(model_results[1]["usage"], {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16})
        event_types = [event["type"] for event in events]
        self.assertIn("tool.queued", event_types)
        self.assertIn("tool.started", event_types)
        self.assertIn("tool.completed", event_types)
        self.assertIn("model.tool_call.delta", event_types)
        self.assertIn("model.usage", event_types)
        self.assertIn("model.completed", event_types)
        popen.assert_not_called()
        run_process.assert_not_called()

        relevant_output = json.dumps(
            {
                "bootstrap": bootstrap,
                "session": session,
                "run": completed,
                "detail": detail,
                "trace": trace,
                "events": events,
                "transport": transport.requests,
            },
            ensure_ascii=False,
        ).lower()
        self.assertNotIn("fixture-native-integration-token", relevant_output)
        self.assertNotIn("codex", relevant_output)
        self.assertNotIn("claude", relevant_output)


if __name__ == "__main__":
    unittest.main()
