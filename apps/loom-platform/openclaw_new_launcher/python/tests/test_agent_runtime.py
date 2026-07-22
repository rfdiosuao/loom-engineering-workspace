from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class LoomCliRuntimeAdapterTests(unittest.TestCase):
    def test_status_resolves_configured_runtime_without_exposing_environment_secrets(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter

        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "codex",
                "command": [sys.executable, "--version"],
                "env": {"OPENAI_API_KEY": "sk-runtime-secret"},
            }
        )

        status = adapter.status()

        self.assertTrue(status["available"])
        self.assertEqual(status["runtime"], "codex")
        self.assertEqual(status["profileId"], "default")
        self.assertNotIn("sk-runtime-secret", json.dumps(status))
        self.assertNotIn("env", status)

    def test_start_launches_argument_array_and_emits_redacted_jsonl_events(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter

        program = (
            "import json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'type':'message.delta','data':{'text':'hello'}})); "
            "print(json.dumps({'type':'tool.completed','data':{'token':'raw-token','ok':True}})); "
            "print(json.dumps({'type':'result','data':{'requestId':request['requestId'],'authorization':'Bearer abc.def'}}))"
        )
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [sys.executable, "-c", program],
            }
        )
        events: list[dict] = []

        result = adapter.start(
            {"requestId": "req-1", "prompt": "safe"},
            events.append,
            threading.Event(),
            timeout_sec=2,
        )

        self.assertEqual([event["type"] for event in events], ["message.delta", "tool.completed"])
        self.assertEqual(events[1]["data"]["token"], "[REDACTED]")
        self.assertEqual(result["requestId"], "req-1")
        self.assertEqual(result["authorization"], "[REDACTED]")

    def test_start_accepts_one_structured_json_document(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter

        program = "print('''{\\n  \"type\": \"result\",\\n  \"data\": {\"status\": \"completed\"}\\n}''')"
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [sys.executable, "-c", program],
            }
        )

        result = adapter.start({}, lambda _event: None, threading.Event(), timeout_sec=2)

        self.assertEqual(result, {"status": "completed"})

    def test_native_claude_profile_returns_bounded_tool_calls_and_plan_events(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter

        program = (
            "import json,sys; prompt=sys.stdin.read(); "
            "assert 'loom.matrix.status' in prompt; "
            "print(json.dumps({'structured_output':{'plan':['Read matrix status'],"
            "'toolCalls':[{'toolCallId':'call-1','name':'loom.matrix.status','input':{}}],'final':None}}))"
        )
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "claude",
                "runtime": "Claude Code",
                "adapter": "claude",
                "command": [sys.executable, "-c", program],
            }
        )
        events: list[dict] = []

        result = adapter.start(
            {
                "runtimeProfileId": "claude",
                "prompt": "Check the phones",
                "capabilities": [{"name": "loom.matrix.status"}],
            },
            events.append,
            threading.Event(),
            timeout_sec=2,
        )

        self.assertEqual(events, [{"type": "plan.updated", "data": {"steps": ["Read matrix status"]}}])
        self.assertEqual(result["toolCalls"][0]["name"], "loom.matrix.status")
        self.assertNotIn("final", result)

    def test_native_codex_profile_reads_schema_constrained_result_file(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter

        program = (
            "import json,sys; sys.stdin.read(); "
            "path=sys.argv[sys.argv.index('--output-last-message')+1]; "
            "open(path,'w',encoding='utf-8').write(json.dumps({"
            "'plan':['Summarize evidence'],'toolCalls':[],'final':{'text':'All devices checked.'}}))"
        )
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "codex",
                "runtime": "Codex CLI",
                "adapter": "codex",
                "command": [sys.executable, "-c", program],
            }
        )

        result = adapter.start(
            {"runtimeProfileId": "codex", "prompt": "Summarize"},
            lambda _event: None,
            threading.Event(),
            timeout_sec=2,
        )

        self.assertEqual(result, {"toolCalls": [], "final": {"text": "All devices checked."}})

    def test_native_provider_cancellation_terminates_the_child(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        cancelled = threading.Event()
        timer = threading.Timer(0.05, cancelled.set)
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "claude",
                "runtime": "Claude Code",
                "adapter": "claude",
                "command": [sys.executable, "-c", "import time,sys; sys.stdin.read(); time.sleep(5)"],
            }
        )

        timer.start()
        try:
            with self.assertRaises(RuntimeExecutionError) as caught:
                adapter.start({}, lambda _event: None, cancelled, timeout_sec=2)
        finally:
            timer.cancel()

        self.assertEqual(caught.exception.code, "agent_runtime_cancelled")

    def test_timeout_is_recoverable_and_terminates_runtime(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [sys.executable, "-c", "import time; time.sleep(5)"],
            },
            default_timeout_sec=0.05,
        )

        with self.assertRaises(RuntimeExecutionError) as caught:
            adapter.start({}, lambda _event: None, threading.Event())

        self.assertEqual(caught.exception.code, "agent_runtime_timeout")
        self.assertTrue(caught.exception.recoverable)

    def test_pre_cancelled_run_never_launches(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        launches: list[list[str]] = []
        cancelled = threading.Event()
        cancelled.set()
        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [sys.executable, "--version"],
            },
            process_factory=lambda args, **_kwargs: launches.append(args),
        )

        with self.assertRaises(RuntimeExecutionError) as caught:
            adapter.start({}, lambda _event: None, cancelled)

        self.assertEqual(caught.exception.code, "agent_runtime_cancelled")
        self.assertEqual(launches, [])

    def test_invalid_output_error_redacts_raw_credentials(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [sys.executable, "-c", "print('Bearer super-secret-token')"],
            }
        )

        with self.assertRaises(RuntimeExecutionError) as caught:
            adapter.start({}, lambda _event: None, threading.Event(), timeout_sec=2)

        self.assertEqual(caught.exception.code, "agent_runtime_invalid_output")
        self.assertTrue(caught.exception.recoverable)
        self.assertNotIn("super-secret-token", str(caught.exception))

    def test_generic_runtime_rejects_output_larger_than_two_megabytes(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('x' * 2100000); sys.stdout.flush()",
                ],
            }
        )

        with self.assertRaises(RuntimeExecutionError) as caught:
            adapter.start({}, lambda _event: None, threading.Event(), timeout_sec=2)

        self.assertEqual(caught.exception.code, "agent_runtime_output_too_large")
        self.assertFalse(caught.exception.recoverable)

    def test_runtime_event_failure_terminates_the_child_process(self) -> None:
        from core.agent_runtime import LoomCliRuntimeAdapter, RuntimeExecutionError

        processes = []

        def process_factory(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            processes.append(process)
            return process

        adapter = LoomCliRuntimeAdapter(
            profile_resolver=lambda _profile_id: {
                "profileId": "default",
                "runtime": "test",
                "command": [
                    sys.executable,
                    "-c",
                    "import json,time; print(json.dumps({'type':'message.delta','data':{'delta':'hello'}}), flush=True); time.sleep(5)",
                ],
            },
            process_factory=process_factory,
        )

        def reject_event(_event):
            raise OSError("event ledger unavailable")

        with self.assertRaises(RuntimeExecutionError) as caught:
            adapter.start({}, reject_event, threading.Event(), timeout_sec=2)

        self.assertEqual(caught.exception.code, "agent_runtime_event_failed")
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())
        self.assertNotIn("event ledger unavailable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
