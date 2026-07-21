from __future__ import annotations

import os
import sys
import threading
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class FakeModelClient:
    def __init__(self, *, response=None, status=None, error=None):
        self.response = response or {
            "text": "hello",
            "toolCalls": [],
            "usage": {"promptTokens": 4},
            "model": "glm-managed",
        }
        self.status_response = status or {"available": True, "model": "glm-managed"}
        self.error = error
        self.requests: list[dict] = []

    def status(self):
        return self.status_response

    def complete(self, request, emit, cancel, *, timeout_sec=None):
        self.requests.append({"request": dict(request), "timeoutSec": timeout_sec})
        if self.error is not None:
            raise self.error
        emit({"type": "model.text.delta", "data": {"delta": "hello"}})
        emit({"type": "model.usage", "data": {"promptTokens": 4, "completionTokens": 2}})
        return self.response


class LoomNativeRuntimeAdapterTests(unittest.TestCase):
    def test_native_runtime_translates_stream_and_returns_stable_message_id(self) -> None:
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        events = []
        result = LoomNativeRuntimeAdapter(FakeModelClient()).start(
            {"sessionId": "session_1", "runId": "run_1", "prompt": "hello"},
            events.append,
            threading.Event(),
        )

        self.assertEqual(events[0], {
            "type": "message.delta",
            "data": {"messageId": "message_run_1", "role": "assistant", "delta": "hello"},
        })
        self.assertEqual(events[1], {"type": "model.usage", "data": {"promptTokens": 4, "completionTokens": 2}})
        self.assertEqual(result, {
            "messageId": "message_run_1",
            "toolCalls": [],
            "model": "glm-managed",
            "usage": {"promptTokens": 4},
            "final": {"text": "hello"},
        })

    def test_native_runtime_omits_final_when_model_requests_tools(self) -> None:
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        result = LoomNativeRuntimeAdapter(FakeModelClient(response={
            "text": "I will call a tool.",
            "toolCalls": [{"toolCallId": "call_1", "name": "loom.test.read", "input": {}}],
            "usage": {"promptTokens": 4},
            "model": "glm-managed",
        })).start(
            {"runId": "run_tools"},
            lambda _event: None,
            threading.Event(),
        )

        self.assertEqual(result["messageId"], "message_run_tools")
        self.assertEqual(result["toolCalls"], [{"toolCallId": "call_1", "name": "loom.test.read", "input": {}}])
        self.assertNotIn("final", result)

    def test_native_runtime_uses_round_scoped_message_ids(self) -> None:
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        adapter = LoomNativeRuntimeAdapter(FakeModelClient())
        first_events = []
        second_events = []

        first = adapter.start(
            {"runId": "run_rounds", "round": 1},
            first_events.append,
            threading.Event(),
        )
        second = adapter.start(
            {"runId": "run_rounds", "round": 2},
            second_events.append,
            threading.Event(),
        )

        self.assertEqual(first["messageId"], "message_run_rounds_round_1")
        self.assertEqual(second["messageId"], "message_run_rounds_round_2")
        self.assertEqual(first_events[0]["data"]["messageId"], first["messageId"])
        self.assertEqual(second_events[0]["data"]["messageId"], second["messageId"])

    def test_status_normalizes_profile_and_redacts_client_data(self) -> None:
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        status = LoomNativeRuntimeAdapter(FakeModelClient(status={
            "available": True,
            "profileId": "other-profile",
            "model": "glm-managed",
            "accessToken": "secret-value",
        })).status("ignored-profile")

        self.assertEqual(status["profileId"], "loom-native")
        self.assertEqual(status["runtime"], "麓鸣原生智能体")
        self.assertEqual(status["accessToken"], "[REDACTED]")

    def test_pre_cancelled_request_returns_runtime_cancellation_without_calling_model(self) -> None:
        from core.agent_runtime import RuntimeExecutionError
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        client = FakeModelClient()
        cancel = threading.Event()
        cancel.set()

        with self.assertRaises(RuntimeExecutionError) as caught:
            LoomNativeRuntimeAdapter(client).start({"runId": "run_cancelled"}, lambda _event: None, cancel)

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CANCELLED")
        self.assertTrue(caught.exception.recoverable)
        self.assertEqual(client.requests, [])

    def test_model_gateway_error_preserves_safe_code_and_recoverability(self) -> None:
        from core.agent_runtime import RuntimeExecutionError
        from core.loom_model_client import ModelGatewayError
        from core.native_agent_runtime import LoomNativeRuntimeAdapter

        client = FakeModelClient(error=ModelGatewayError(
            "AGENT_MODEL_CONFIG_INVALID",
            "Bearer sk-secret-value",
            recoverable=False,
        ))

        with self.assertRaises(RuntimeExecutionError) as caught:
            LoomNativeRuntimeAdapter(client).start({"runId": "run_error"}, lambda _event: None, threading.Event())

        self.assertEqual(caught.exception.code, "AGENT_MODEL_CONFIG_INVALID")
        self.assertFalse(caught.exception.recoverable)
        self.assertNotIn("sk-secret-value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
