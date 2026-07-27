from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ScriptedRuntime:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def status(self, _profile_id=None):
        return {"available": True, "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        if cancel.is_set():
            raise AssertionError("runtime started after cancellation")
        self.requests.append(dict(request))
        return self.responses.pop(0)


class RejectingEventBus:
    def __init__(self, delegate, rejected_type: str):
        self.delegate = delegate
        self.rejected_type = rejected_type

    def publish(self, session_id, event_type, *, topic, entity_id, data=None):
        if event_type == self.rejected_type:
            raise OSError("event ledger unavailable")
        return self.delegate.publish(
            session_id,
            event_type,
            topic=topic,
            entity_id=entity_id,
            data=data,
        )


class AgentRuntimeReliabilityTests(unittest.TestCase):
    def _build(self, root: str, runtime, operation, *, event_bus_factory=None):
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_events import AgentEventBus
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        repository = AgentSessionRepository(root)
        repository.create_session("Reliability", session_id="session-1")
        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.echo": {
                    "executor": operation,
                    "permission": "read",
                    "risk": "read",
                    "inputSchema": {
                        "type": "object",
                        "required": ["prompt"],
                        "properties": {
                            "prompt": {"type": "string", "minLength": 1},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )
        base_bus = AgentEventBus(repository)
        event_bus = event_bus_factory(base_bus) if event_bus_factory else base_bus
        orchestrator = AgentOrchestrator(
            repository,
            event_bus,
            runtime,
            registry,
            AgentPolicyEngine(approval_mode="weak"),
        )
        return repository, base_bus, orchestrator

    def test_required_blank_string_is_repaired_once_before_execution(self) -> None:
        calls: list[dict] = []
        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "blank-1",
                            "name": "loom.test.echo",
                            "input": {"prompt": "   "},
                        }
                    ]
                },
                {
                    "toolCalls": [
                        {
                            "toolCallId": "repaired-1",
                            "name": "loom.test.echo",
                            "input": {"prompt": "ready"},
                        }
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, orchestrator = self._build(
                root,
                runtime,
                lambda payload: calls.append(dict(payload)) or {"ok": True},
            )
            orchestrator.queue_run("session-1", run_id="run-blank")

            completed = orchestrator.execute_run("session-1", "run-blank", {"prompt": "echo"})
            events = bus.replay("session-1")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(calls, [{"prompt": "ready"}])
        self.assertEqual(len(runtime.requests), 3)
        repair = runtime.requests[1]["toolResults"][-1]
        self.assertEqual(repair["error"]["code"], "capability_invalid_input")
        self.assertIn("input.prompt", repair["error"]["message"])
        self.assertEqual([event["type"] for event in events].count("tool.input_rejected"), 1)

    def test_runtime_without_final_cannot_complete_with_placeholder_text(self) -> None:
        runtime = ScriptedRuntime([{"toolCalls": []}])
        with tempfile.TemporaryDirectory() as root:
            repository, _bus, orchestrator = self._build(root, runtime, lambda _payload: {"ok": True})
            orchestrator.queue_run("session-1", run_id="run-no-final")

            failed = orchestrator.execute_run("session-1", "run-no-final", {"prompt": "answer"})
            messages = repository.page_messages("session-1", limit=50)["messages"]

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "agent_runtime_missing_final")
        self.assertTrue(failed["error"]["recoverable"])
        self.assertEqual(messages, [])

    def test_terminal_run_is_persisted_when_completion_event_publish_fails(self) -> None:
        runtime = ScriptedRuntime([{"final": {"text": "persist me"}}])
        with tempfile.TemporaryDirectory() as root:
            repository, _bus, orchestrator = self._build(
                root,
                runtime,
                lambda _payload: {"ok": True},
                event_bus_factory=lambda bus: RejectingEventBus(bus, "message.completed"),
            )
            orchestrator.queue_run("session-1", run_id="run-event-failure")

            completed = orchestrator.execute_run(
                "session-1",
                "run-event-failure",
                {"prompt": "answer"},
            )
            stored = repository.get_run("run-event-failure", session_id="session-1")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["executionState"]["phase"], "terminal")
        self.assertTrue(stored["executionState"]["degraded"])

    def test_execution_state_contract_tracks_planning_tool_and_terminal(self) -> None:
        observed_tool_state: list[dict] = []
        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "state-1",
                            "name": "loom.test.echo",
                            "input": {"prompt": "inspect"},
                        }
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository_holder = {}

            def operation(_payload):
                repository = repository_holder["repository"]
                observed_tool_state.append(repository.get_run("run-state")["executionState"])
                return {"ok": True}

            repository, _bus, orchestrator = self._build(root, runtime, operation)
            repository_holder["repository"] = repository
            queued = orchestrator.queue_run("session-1", run_id="run-state")

            completed = orchestrator.execute_run("session-1", "run-state", {"prompt": "inspect"})

        self.assertEqual(
            queued["executionState"],
            {"phase": "planning", "retryable": False, "degraded": False},
        )
        self.assertEqual(observed_tool_state[0]["phase"], "tool")
        self.assertEqual(
            completed["executionState"],
            {"phase": "terminal", "retryable": False, "degraded": False},
        )

        contract_root = Path(PYTHON_DIR).parents[3] / "packages" / "contracts"
        schema = json.loads((contract_root / "schemas" / "agent-run.v1.schema.json").read_text(encoding="utf-8"))
        fixture = json.loads((contract_root / "fixtures" / "agent-run.v1.json").read_text(encoding="utf-8"))
        self.assertIn("executionState", schema["required"])
        self.assertEqual(fixture["executionState"]["phase"], "planning")


if __name__ == "__main__":
    unittest.main()
