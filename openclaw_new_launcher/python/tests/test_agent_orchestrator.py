from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ScriptedRuntime:
    def __init__(self, responses: list[dict], emitted: list[list[dict]] | None = None):
        self.responses = list(responses)
        self.emitted = list(emitted or [[] for _ in responses])
        self.requests: list[dict] = []

    def status(self, _profile_id=None):
        return {"available": True, "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        if cancel.is_set():
            raise AssertionError("runtime started after cancellation")
        self.requests.append(dict(request))
        for event in self.emitted[len(self.requests) - 1]:
            emit(event)
        return self.responses.pop(0)


class BlockingFinalRuntime:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def status(self, _profile_id=None):
        return {"available": True, "runtime": "test"}

    def start(self, request, emit, cancel, *, timeout_sec=None):
        self.started.set()
        if not self.release.wait(2):
            raise AssertionError("test did not release blocked runtime")
        return {"final": {"text": "late runtime completion"}}


class AgentOrchestratorTests(unittest.TestCase):
    def _dependencies(self, root: str, runtime, *, operation=None, approval_mode: str = "strong"):
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_events import AgentEventBus
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        repository = AgentSessionRepository(root)
        repository.create_session("Test", session_id="session-1")
        event_bus = AgentEventBus(repository)
        calls: list[dict] = []

        def execute(payload):
            calls.append(payload)
            if operation is not None:
                return operation(payload)
            return {"ok": True}

        registry = CapabilityRegistry(
            internal_operations={
                "loom.matrix.dispatch": {
                    "executor": execute,
                    "permission": "control",
                    "risk": "control_safe",
                    "timeoutSec": 2,
                },
                "loom.matrix.cancel": {
                    "executor": execute,
                    "permission": "control",
                    "risk": "control_safe",
                    "timeoutSec": 2,
                },
                "loom.matrix.retry": {
                    "executor": execute,
                    "permission": "control",
                    "risk": "control_safe",
                    "timeoutSec": 2,
                },
                "loom.phone.publish": {
                    "executor": execute,
                    "permission": "control",
                    "risk": "outbound",
                    "timeoutSec": 2,
                },
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )
        return repository, event_bus, registry, AgentPolicyEngine(approval_mode=approval_mode), calls

    def test_runtime_request_contains_only_connected_capabilities(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{"final": {"text": "done"}}])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-connected-catalog")

            completed = orchestrator.execute_run(
                "session-1",
                "run-connected-catalog",
                {"prompt": "inspect connected tools"},
            )

        self.assertEqual(completed["status"], "completed")
        capabilities = {item["name"]: item for item in runtime.requests[0]["capabilities"]}
        self.assertIn("loom.matrix.dispatch", capabilities)
        self.assertNotIn("loom.media.image.generate", capabilities)
        self.assertTrue(all(item["available"] for item in capabilities.values()))

    def test_invalid_outbound_tool_input_is_returned_to_model_for_one_hidden_repair(self) -> None:
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_events import AgentEventBus
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        calls: list[dict] = []
        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "publish-without-title",
                    "name": "loom.phone.publish",
                    "input": {"platform": "douyin", "mediaPaths": ["draft.png"]},
                }],
            },
            {
                "toolCalls": [{
                    "toolCallId": "publish-repaired",
                    "name": "loom.phone.publish",
                    "input": {
                        "platform": "douyin",
                        "title": "LOOM QA draft",
                        "mediaPaths": ["draft.png"],
                    },
                }],
            },
        ])
        with tempfile.TemporaryDirectory() as root:
            repository = AgentSessionRepository(root)
            repository.create_session("Test", session_id="session-1")
            registry = CapabilityRegistry(
                internal_operations={
                    "loom.phone.publish": {
                        "executor": lambda payload: calls.append(payload) or {"ok": True},
                        "permission": "control",
                        "risk": "outbound",
                        "timeoutSec": 2,
                        "inputSchema": {
                            "type": "object",
                            "required": ["platform", "title", "mediaPaths"],
                            "properties": {
                                "platform": {"type": "string"},
                                "title": {"type": "string"},
                                "mediaPaths": {"type": "array"},
                            },
                        },
                    },
                },
                skill_provider=lambda: [],
                mcp_provider=lambda: [],
                cli_catalog_provider=lambda: {"domains": []},
            )
            orchestrator = AgentOrchestrator(
                repository,
                AgentEventBus(repository),
                runtime,
                registry,
                AgentPolicyEngine(),
            )
            orchestrator.queue_run("session-1", run_id="run-invalid-outbound")

            waiting = orchestrator.execute_run(
                "session-1",
                "run-invalid-outbound",
                {"prompt": "publish"},
            )
            events = AgentEventBus(repository).replay("session-1")
            approvals = repository.list_approvals("session-1", run_id="run-invalid-outbound")

            self.assertEqual(waiting["status"], "waiting_approval")
            self.assertEqual(calls, [])
            self.assertEqual(len(runtime.requests), 2)
            self.assertEqual(
                runtime.requests[1]["toolResults"][0]["error"]["code"],
                "capability_invalid_input",
            )
            self.assertIn("input.title is required", runtime.requests[1]["toolResults"][0]["error"]["message"])
            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0]["inputSummary"]["title"], "LOOM QA draft")
            self.assertEqual([event["type"] for event in events].count("tool.failed"), 0)
            self.assertEqual([event["type"] for event in events].count("tool.input_rejected"), 1)

    def test_publish_title_explicit_in_user_prompt_is_restored_before_validation(self) -> None:
        from core.agent_capabilities import CapabilityRegistry, PHONE_PUBLISH_INPUT_SCHEMA
        from core.agent_events import AgentEventBus
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        calls: list[dict] = []
        invalid_publish = {
            "name": "loom.phone.publish",
            "input": {
                "platform": "douyin",
                "body": "LOOM draft verification",
                "mediaPaths": ["draft.png"],
                "deviceId": "phone-1",
                "draftOnly": True,
                "notes": "标题：LOOM 2.1.95 草稿实机验收。仅保存草稿，不得公开发布。",
            },
        }
        runtime = ScriptedRuntime([
            {"toolCalls": [{"toolCallId": "publish-title-in-notes-1", **invalid_publish}]},
            {"toolCalls": [{"toolCallId": "publish-title-in-notes-2", **invalid_publish}]},
        ])
        with tempfile.TemporaryDirectory() as root:
            repository = AgentSessionRepository(root)
            repository.create_session("Test", session_id="session-1")
            registry = CapabilityRegistry(
                internal_operations={
                    "loom.phone.publish": {
                        "executor": lambda payload: calls.append(payload) or {"ok": True},
                        "permission": "control",
                        "risk": "outbound",
                        "timeoutSec": 2,
                        "inputSchema": PHONE_PUBLISH_INPUT_SCHEMA,
                    },
                },
                skill_provider=lambda: [],
                mcp_provider=lambda: [],
                cli_catalog_provider=lambda: {"domains": []},
            )
            orchestrator = AgentOrchestrator(
                repository,
                AgentEventBus(repository),
                runtime,
                registry,
                AgentPolicyEngine(),
            )
            orchestrator.queue_run("session-1", run_id="run-explicit-publish-title")

            waiting = orchestrator.execute_run(
                "session-1",
                "run-explicit-publish-title",
                {
                    "prompt": "保存抖音草稿。标题：LOOM 2.1.95 草稿实机验收。不得公开发布。",
                    "targets": {"deviceIds": ["phone-1"]},
                },
            )
            approvals = repository.list_approvals(
                "session-1",
                run_id="run-explicit-publish-title",
            )
            events = AgentEventBus(repository).replay("session-1")

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(calls, [])
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["inputSummary"]["title"], "LOOM 2.1.95 草稿实机验收")
        self.assertEqual([event["type"] for event in events].count("tool.input_rejected"), 0)

    def test_publish_title_is_derived_from_body_when_model_omits_it(self) -> None:
        from core.agent_orchestrator import _restore_explicit_publish_title

        restored = _restore_explicit_publish_title(
            {
                "toolCallId": "publish-body-title",
                "name": "loom.phone.publish",
                "input": {
                    "platform": "xiaohongshu",
                    "body": "檀木手串｜沉稳温润\n适合日常佩戴与礼赠。",
                    "mediaPaths": ["bracelet.png"],
                    "deviceId": "phone-1",
                },
            },
            {"prompt": "生成檀木手串海报并发布到小红书"},
        )

        self.assertEqual(restored["input"]["title"], "檀木手串｜沉稳温润")

    def test_tool_loop_persists_checkpoint_and_matrix_partial_failure_attachment(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-1",
                            "name": "loom.matrix.dispatch",
                            "input": {
                                "prompt": "读取屏幕",
                                "targets": {"deviceIds": ["phone-1", "phone-2"]},
                            },
                        }
                    ]
                },
                {"final": {"text": "Matrix task finished with one device failure."}},
            ]
        )

        def matrix_result(_payload):
            return {
                "campaignId": "cmp-1",
                "counts": {"total": 2, "completed": 1, "failed": 1},
                "deviceTasks": [
                    {"deviceId": "phone-1", "status": "completed"},
                    {"deviceId": "phone-2", "status": "failed", "error": {"code": "device_offline"}},
                ],
            }

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(
                root,
                runtime,
                operation=matrix_result,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            queued = orchestrator.queue_run("session-1", run_id="run-1")

            completed = orchestrator.execute_run(
                "session-1",
                "run-1",
                {"prompt": "run matrix", "targets": {"deviceIds": ["phone-1", "phone-2"]}},
            )
            events = bus.replay("session-1")

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["campaignIds"], ["cmp-1"])
        checkpoint = json.loads(completed["checkpoint"])
        self.assertEqual(checkpoint["completedToolCallIds"], ["call-1"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(runtime.requests), 2)
        event_types = [event["type"] for event in events]
        expected_lifecycle = [
            "run.queued",
            "run.started",
            "tool.queued",
            "tool.started",
            "matrix.attached",
            "tool.completed",
            "message.completed",
            "run.completed",
        ]
        lifecycle_positions = [event_types.index(event_type) for event_type in expected_lifecycle]
        self.assertEqual(lifecycle_positions, sorted(lifecycle_positions))
        self.assertIn("tool.started", event_types)
        self.assertIn("tool.completed", event_types)
        self.assertIn("matrix.attached", event_types)
        self.assertIn("run.completed", event_types)
        attachment = next(event for event in events if event["type"] == "matrix.attached")
        self.assertEqual(attachment["data"]["failedDeviceIds"], ["phone-2"])
        self.assertTrue(attachment["data"]["partialFailure"])

    def test_completed_media_tool_event_exposes_preview_attachments(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([
            {
                "toolCalls": [{
                    "toolCallId": "call-media",
                    "name": "loom.matrix.dispatch",
                    "input": {"prompt": "生成媒体", "targets": {"deviceIds": ["phone-1"]}},
                }],
            },
            {"final": {"text": "Media generated."}},
        ])
        media_result = {
            "attachments": [{
                "name": "loom-image.png",
                "path": "D:/LOOM/data/generated-images/loom-image.png",
                "mime": "image/png",
                "kind": "image",
            }],
            "phoneTransfer": {
                "status": "succeeded",
                "message": "已传送到手机相册",
            },
        }

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(
                root,
                runtime,
                operation=lambda _payload: media_result,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-media")
            orchestrator.execute_run(
                "session-1",
                "run-media",
                {
                    "prompt": "generate media",
                    "targets": {"deviceIds": ["phone-1"]},
                },
            )
            completed = next(
                event for event in bus.replay("session-1")
                if event["type"] == "tool.completed"
            )

        self.assertEqual(completed["data"]["attachments"], media_result["attachments"])
        self.assertEqual(completed["data"]["phoneTransfer"], media_result["phoneTransfer"])
        self.assertIn("outputSummary", completed["data"])

    def test_tool_result_summary_preserves_nested_phone_job_outcome_for_next_model_round(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-phone-read",
                            "name": "loom.matrix.dispatch",
                            "input": {"prompt": "读取手机", "targets": {"deviceIds": ["phone-1"]}},
                        }
                    ]
                },
                {"final": {"text": "Phone screen read successfully."}},
            ]
        )

        def phone_job_result(_payload):
            return {
                "endpoint": "/api/phone/read",
                "method": "POST",
                "result": {
                    "jobId": "job-phone-read",
                    "job": {
                        "status": "succeeded",
                        "result": {
                            "success": True,
                            "summary": "读取完成：设置 / 网络和互联网 / 已连接的设备 / 应用",
                            "currentPackage": "com.android.settings",
                            "stdout": "x" * 5000,
                        },
                    },
                },
            }

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(
                root,
                runtime,
                operation=phone_job_result,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-phone-result")

            completed = orchestrator.execute_run(
                "session-1",
                "run-phone-result",
                {"prompt": "read phone", "targets": {"deviceIds": ["phone-1"]}},
            )

        self.assertEqual(completed["status"], "completed")
        summarized = runtime.requests[1]["toolResults"][0]["result"]
        self.assertEqual(runtime.requests[1]["toolResults"][0]["input"], {
            "prompt": "读取手机",
            "targets": {"deviceIds": ["phone-1"]},
        })
        phone_result = summarized["result"]["job"]["result"]
        self.assertEqual(phone_result["success"], True)
        self.assertEqual(phone_result["currentPackage"], "com.android.settings")
        self.assertIn("设置", phone_result["summary"])
        self.assertNotIn("[nested content omitted]", json.dumps(summarized, ensure_ascii=False))
        self.assertEqual(len(phone_result["stdout"]), 500)

    def test_tool_result_summary_has_a_global_budget_and_keeps_outcome_fields(self) -> None:
        from core.agent_orchestrator import _summary

        payload = {
            "result": {
                "job": {
                    "status": "succeeded",
                    "result": {
                        "success": True,
                        "summary": "目标页面已打开",
                        "currentPackage": "com.android.settings",
                        "stdout": "x" * 100000,
                        "branches": [
                            {f"field-{column}": "y" * 2000 for column in range(40)}
                            for _row in range(40)
                        ],
                    },
                },
            },
        }
        payload.update({
            f"branch-{row}": {f"field-{column}": "z" * 2000 for column in range(40)}
            for row in range(40)
        })

        summarized = _summary(payload)
        encoded = json.dumps(summarized, ensure_ascii=False)

        self.assertLess(len(encoded), 20000)
        phone_result = summarized["result"]["job"]["result"]
        self.assertEqual(phone_result["success"], True)
        self.assertEqual(phone_result["summary"], "目标页面已打开")
        self.assertEqual(phone_result["currentPackage"], "com.android.settings")

    def test_indeterminate_capability_failure_preserves_execution_flags_in_run_and_events(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-indeterminate",
                            "name": "loom.matrix.dispatch",
                            "input": {"prompt": "安全读取屏幕"},
                        }
                    ]
                }
            ]
        )

        def indeterminate_failure(_payload):
            raise CapabilityExecutionError(
                "capability_timeout_indeterminate",
                "Capability timed out and may still be running.",
                recoverable=False,
                outcome_indeterminate=True,
                execution_may_continue=True,
            )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(
                root,
                runtime,
                operation=indeterminate_failure,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-indeterminate")

            failed = orchestrator.execute_run(
                "session-1",
                "run-indeterminate",
                {"prompt": "read safely", "targets": {"deviceIds": ["phone-1"]}},
            )
            events = bus.replay("session-1")

        expected_flags = {"outcomeIndeterminate": True, "executionMayContinue": True}
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            {name: failed["error"][name] for name in expected_flags},
            expected_flags,
        )
        tool_error = next(event for event in events if event["type"] == "tool.failed")["data"]["error"]
        run_error = next(event for event in events if event["type"] == "run.failed")["data"]["error"]
        self.assertEqual({name: tool_error[name] for name in expected_flags}, expected_flags)
        self.assertEqual({name: run_error[name] for name in expected_flags}, expected_flags)

    def test_matrix_dispatch_without_tool_targets_is_bound_to_run_request(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-bound-target",
                            "name": "loom.matrix.dispatch",
                            "input": {"prompt": "读取屏幕"},
                        }
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(
                root,
                runtime,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-bind-target")

            result = orchestrator.execute_run(
                "session-1",
                "run-bind-target",
                {"prompt": "run matrix", "targets": {"deviceIds": ["phone-1"]}},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(calls[0]["targets"], {"deviceIds": ["phone-1"]})

    def test_outbound_tool_waits_for_approval_then_executes_once(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-publish",
                            "name": "loom.phone.publish",
                            "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved post"},
                        }
                    ]
                },
                {"final": {"text": "Published after approval."}},
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-approval")

            waiting = orchestrator.execute_run("session-1", "run-approval", {"prompt": "publish"})
            approvals = repository.list_approvals("session-1", run_id="run-approval")
            self.assertEqual(calls, [])
            self.assertEqual(waiting["status"], "waiting_approval")
            self.assertEqual(len(approvals), 1)

            outcome = orchestrator.resolve_approval(
                "session-1",
                approvals[0]["approvalId"],
                decision="approved",
                decided_by="user-1",
                request={"prompt": "publish"},
            )
            stored_approval = repository.get_approval(approvals[0]["approvalId"])
            events = bus.replay("session-1")

        self.assertEqual(outcome["run"]["status"], "completed")
        self.assertEqual(stored_approval["status"], "consumed")
        self.assertEqual(len(calls), 1)
        self.assertEqual([event["type"] for event in events].count("approval.required"), 1)
        self.assertEqual([event["type"] for event in events].count("run.waiting_approval"), 1)
        self.assertEqual([event["type"] for event in events].count("tool.queued"), 1)
        self.assertEqual([event["type"] for event in events].count("tool.completed"), 1)
        resolved_event = next(event for event in events if event["type"] == "approval.resolved")
        self.assertEqual(resolved_event["data"]["status"], "approved")
        self.assertEqual(resolved_event["data"]["runId"], "run-approval")

    def test_rejected_approval_finishes_the_queued_tool_row(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{
            "toolCalls": [{
                "toolCallId": "call-rejected",
                "name": "loom.phone.publish",
                "input": {
                    "target": {"deviceIds": ["phone-1"]},
                    "text": "do not execute",
                },
            }],
        }])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-rejected")
            orchestrator.execute_run("session-1", "run-rejected", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-rejected")[0]

            outcome = orchestrator.resolve_approval(
                "session-1",
                approval["approvalId"],
                decision="rejected",
                decided_by="user-1",
                request={"prompt": "publish"},
            )
            events = bus.replay("session-1")

        self.assertEqual(outcome["run"]["status"], "paused")
        self.assertEqual(calls, [])
        failed = [event for event in events if event["type"] == "tool.failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["data"]["toolCallId"], "call-rejected")
        self.assertEqual(failed[0]["data"]["error"]["code"], "approval_rejected")

    def test_approved_blocking_tool_marks_run_running_before_it_finishes(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        tool_started = threading.Event()
        release_tool = threading.Event()

        def blocking_tool(_payload):
            tool_started.set()
            if not release_tool.wait(2):
                raise AssertionError("test did not release blocked tool")
            return {"ok": True}

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-running-after-approval",
                            "name": "loom.phone.publish",
                            "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved"},
                        }
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(
                root,
                runtime,
                operation=blocking_tool,
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-running-after-approval")
            waiting = orchestrator.execute_run("session-1", "run-running-after-approval", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-running-after-approval")[0]
            outcome: dict[str, dict] = {}
            worker = threading.Thread(
                target=lambda: outcome.setdefault(
                    "result",
                    orchestrator.resolve_approval(
                        "session-1",
                        approval["approvalId"],
                        decision="approved",
                        decided_by="user-1",
                        request={"prompt": "publish"},
                    ),
                )
            )
            worker.start()
            self.assertTrue(tool_started.wait(1))
            executing = repository.get_run("run-running-after-approval", session_id="session-1")
            release_tool.set()
            worker.join(2)

            self.assertFalse(worker.is_alive())

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(executing["status"], "running")
        self.assertEqual(outcome["result"]["run"]["status"], "completed")

    def test_approved_tool_failure_finishes_run_with_the_capability_error(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError
        from core.agent_orchestrator import AgentOrchestrator

        def failing_tool(_payload):
            raise CapabilityExecutionError(
                "phone_publish_semantic_failure",
                "抖音应用当前未登录",
                recoverable=True,
            )

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-failed-after-approval",
                            "name": "loom.phone.publish",
                            "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved"},
                        }
                    ]
                }
            ]
        )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(
                root,
                runtime,
                operation=failing_tool,
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-failed-after-approval")
            waiting = orchestrator.execute_run("session-1", "run-failed-after-approval", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-failed-after-approval")[0]

            outcome = orchestrator.resolve_approval(
                "session-1",
                approval["approvalId"],
                decision="approved",
                decided_by="user-1",
                request={"prompt": "publish"},
            )
            stored = repository.get_run("run-failed-after-approval", session_id="session-1")

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(outcome["run"]["status"], "failed")
        self.assertEqual(stored["status"], "failed")
        self.assertEqual(stored["error"]["code"], "phone_publish_semantic_failure")
        self.assertIn("未登录", stored["error"]["message"])

    def test_concurrent_approval_requests_execute_protected_tool_once_and_loser_conflicts(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import PolicyViolationError

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-concurrent-approval",
                            "name": "loom.phone.publish",
                            "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved once"},
                        }
                    ]
                },
                {"final": {"text": "winner completed"}},
                {"final": {"text": "duplicate completed"}},
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-concurrent-approval")
            waiting = orchestrator.execute_run("session-1", "run-concurrent-approval", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-concurrent-approval")[0]

            pending_reads = threading.Barrier(2)
            approved_reads = threading.Barrier(2)
            original_get_approval = repository.get_approval

            def synchronize_approval_reads(approval_id, session_id=None):
                current = original_get_approval(approval_id, session_id=session_id)
                if current.get("status") == "pending":
                    pending_reads.wait(1)
                elif current.get("status") == "approved":
                    try:
                        approved_reads.wait(0.25)
                    except threading.BrokenBarrierError:
                        pass
                return current

            repository.get_approval = synchronize_approval_reads
            outcomes: list[dict] = []
            failures: list[PolicyViolationError] = []

            def approve(decided_by: str) -> None:
                try:
                    outcomes.append(
                        orchestrator.resolve_approval(
                            "session-1",
                            approval["approvalId"],
                            decision="approved",
                            decided_by=decided_by,
                            request={"prompt": "publish"},
                        )
                    )
                except PolicyViolationError as exc:
                    failures.append(exc)

            workers = [threading.Thread(target=approve, args=(f"user-{index}",)) for index in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(2)

            stored_approval = original_get_approval(approval["approvalId"], session_id="session-1")
            events = bus.replay("session-1")

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(outcomes), 1)
        self.assertEqual([failure.code for failure in failures], ["approval_conflict"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(stored_approval["status"], "consumed")
        self.assertEqual([event["type"] for event in events].count("approval.resolved"), 1)
        self.assertEqual([event["type"] for event in events].count("tool.started"), 1)

    def test_pause_resume_and_cancel_are_persisted_and_emitted(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{"final": {"text": "resumed"}}])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-pause")

            paused = orchestrator.pause_run("run-pause", session_id="session-1")
            resumed = orchestrator.resume_run("run-pause", session_id="session-1", request={"prompt": "resume"})
            orchestrator.queue_run("session-1", run_id="run-cancel")
            cancelled = orchestrator.cancel_run("run-cancel", session_id="session-1")
            events = bus.replay("session-1")

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIn("run.paused", [event["type"] for event in events])
        self.assertIn("run.cancelled", [event["type"] for event in events])

    def test_pause_and_cancel_win_race_with_late_runtime_completion(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        for action in ("pause", "cancel"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as root:
                runtime = BlockingFinalRuntime()
                repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
                orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
                orchestrator.queue_run("session-1", run_id="run-runtime-race")
                outcomes: list[dict] = []
                failures: list[BaseException] = []

                def execute():
                    try:
                        outcomes.append(orchestrator.execute_run("session-1", "run-runtime-race", {"prompt": "wait"}))
                    except BaseException as exc:
                        failures.append(exc)

                worker = threading.Thread(target=execute)
                worker.start()
                self.assertTrue(runtime.started.wait(1))
                if action == "pause":
                    orchestrator.pause_run("run-runtime-race", session_id="session-1")
                else:
                    orchestrator.cancel_run("run-runtime-race", session_id="session-1")
                runtime.release.set()
                worker.join(2)

                self.assertFalse(worker.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(outcomes[0]["status"], "paused" if action == "pause" else "cancelled")
                self.assertEqual(repository.get_run("run-runtime-race")["status"], outcomes[0]["status"])
                late_types = [event["type"] for event in bus.replay("session-1")]
                self.assertNotIn("run.completed", late_types)
                self.assertNotIn("message.completed", late_types)

    def test_pause_and_cancel_win_race_with_late_approved_tool_completion(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        for action in ("pause", "cancel"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as root:
                tool_started = threading.Event()
                release_tool = threading.Event()

                def blocking_tool(_payload):
                    tool_started.set()
                    if not release_tool.wait(2):
                        raise AssertionError("test did not release blocked tool")
                    return {"ok": True}

                runtime = ScriptedRuntime(
                    [
                        {
                            "toolCalls": [
                                {
                                    "toolCallId": "call-approved-race",
                                    "name": "loom.phone.publish",
                                    "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved"},
                                }
                            ]
                        },
                        {"final": {"text": "late final"}},
                    ]
                )
                repository, bus, registry, policy, _calls = self._dependencies(
                    root,
                    runtime,
                    operation=blocking_tool,
                )
                orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
                orchestrator.queue_run("session-1", run_id="run-tool-race")
                waiting = orchestrator.execute_run("session-1", "run-tool-race", {"prompt": "publish"})
                self.assertEqual(waiting["status"], "waiting_approval")
                approval = repository.list_approvals("session-1", run_id="run-tool-race")[0]
                status_changes: list[str] = []
                original_update_run = repository.update_run

                def track_update(run_id, changes, session_id=None):
                    if isinstance(changes.get("status"), str):
                        status_changes.append(changes["status"])
                    return original_update_run(run_id, changes, session_id=session_id)

                repository.update_run = track_update
                outcomes: list[dict] = []
                failures: list[BaseException] = []

                def approve():
                    try:
                        outcomes.append(
                            orchestrator.resolve_approval(
                                "session-1",
                                approval["approvalId"],
                                decision="approved",
                                decided_by="user-1",
                                request={"prompt": "publish"},
                            )
                        )
                    except BaseException as exc:
                        failures.append(exc)

                worker = threading.Thread(target=approve)
                worker.start()
                self.assertTrue(tool_started.wait(1))
                if action == "pause":
                    orchestrator.pause_run("run-tool-race", session_id="session-1")
                else:
                    orchestrator.cancel_run("run-tool-race", session_id="session-1")
                status_marker = len(status_changes)
                release_tool.set()
                worker.join(2)

                self.assertFalse(worker.is_alive())
                self.assertEqual(failures, [])
                expected = "paused" if action == "pause" else "cancelled"
                self.assertEqual(outcomes[0]["run"]["status"], expected)
                self.assertEqual(repository.get_run("run-tool-race")["status"], expected)
                self.assertFalse({"running", "completed"}.intersection(status_changes[status_marker:]))

    def test_restart_recovery_pauses_running_run_without_repeating_inflight_tool(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-restart")
            repository.update_run(
                "run-restart",
                {
                    "status": "running",
                    "checkpoint": json.dumps(
                        {
                            "version": 1,
                            "completedToolCallIds": [],
                            "toolResults": [],
                            "inFlightToolCall": {
                                "toolCallId": "call-unknown",
                                "name": "loom.matrix.dispatch",
                                "input": {"targets": {"deviceIds": ["phone-1"]}},
                            },
                        }
                    ),
                },
                session_id="session-1",
            )

            recovered = orchestrator.recover_unfinished_runs()
            stored = repository.get_run("run-restart")
            events = bus.replay("session-1")

        self.assertEqual(recovered[0]["status"], "paused")
        self.assertEqual(stored["error"]["code"], "agent_restart_inflight_unknown")
        self.assertTrue(stored["error"]["recoverable"])
        self.assertEqual(calls, [])
        checkpoint = json.loads(stored["checkpoint"])
        self.assertIsNone(checkpoint["inFlightToolCall"])
        self.assertIn("call-unknown", checkpoint["completedToolCallIds"])
        self.assertEqual(checkpoint["toolResults"][-1]["status"], "failed")
        lifecycle = [
            event["type"]
            for event in events
            if event["type"] in {"tool.failed", "run.paused"}
        ]
        self.assertEqual(lifecycle[-2:], ["tool.failed", "run.paused"])
        failed_event = next(event for event in events if event["type"] == "tool.failed")
        self.assertEqual(failed_event["data"]["toolCallId"], "call-unknown")
        self.assertEqual(failed_event["data"]["error"]["code"], "agent_restart_inflight_unknown")

    def test_runtime_events_are_redacted_before_persistence(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [{"final": {"text": "done"}}],
            emitted=[[{"type": "plan.updated", "data": {"token": "secret-value", "note": "Bearer abc.def"}}]],
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-secret")
            orchestrator.execute_run("session-1", "run-secret", {"prompt": "safe"})

            serialized = json.dumps(bus.replay("session-1"), ensure_ascii=False)

        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("abc.def", serialized)

    def test_message_completed_emits_the_complete_persisted_assistant_message(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{"final": {"text": "Frontend-ready answer"}}])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-message-contract")
            orchestrator.execute_run("session-1", "run-message-contract", {"prompt": "answer"})

            messages = repository.page_messages("session-1", limit=50)["messages"]
            event = next(item for item in bus.replay("session-1") if item["type"] == "message.completed")

        persisted = messages[-1]
        self.assertEqual(persisted["role"], "assistant")
        self.assertEqual(event["data"]["message"], persisted)
        self.assertEqual(event["data"]["message"]["schema"], "loom.agent.message.v1")
        self.assertEqual(event["data"]["message"]["blocks"][0]["data"]["text"], "Frontend-ready answer")

    def test_final_message_reuses_runtime_message_id_for_stream_identity(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{
            "messageId": "message_run-fixed",
            "final": {"text": "streamed final"},
        }])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-fixed")
            orchestrator.execute_run("session-1", "run-fixed", {"prompt": "answer"})

            persisted = repository.page_messages("session-1", limit=50)["messages"][-1]
            completed_event = next(item for item in bus.replay("session-1") if item["type"] == "message.completed")

        self.assertEqual(persisted["messageId"], "message_run-fixed")
        self.assertEqual(completed_event["data"]["message"]["messageId"], "message_run-fixed")

    def test_restart_with_only_redacted_pending_input_pauses_instead_of_executing(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        first_runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-secret",
                            "name": "loom.phone.publish",
                            "input": {
                                "target": {"deviceIds": ["phone-1"]},
                                "apiKey": "sk-one-use-secret",
                            },
                        }
                    ]
                }
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, first_runtime)
            first = AgentOrchestrator(repository, bus, first_runtime, registry, policy)
            first.queue_run("session-1", run_id="run-secret-approval")
            first.execute_run("session-1", "run-secret-approval", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-secret-approval")[0]

            restarted = AgentOrchestrator(repository, bus, ScriptedRuntime([]), registry, policy)
            outcome = restarted.resolve_approval(
                "session-1",
                approval["approvalId"],
                decision="approved",
                decided_by="user-1",
            )
            stored = repository.get_run("run-secret-approval")
            events = bus.replay("session-1")

        self.assertEqual(outcome["run"]["status"], "paused")
        self.assertEqual(outcome["run"]["error"]["code"], "approval_scope_mismatch")
        self.assertEqual(calls, [])
        checkpoint = json.loads(stored["checkpoint"])
        self.assertNotIn("pendingApproval", checkpoint)
        self.assertIsNone(checkpoint["inFlightToolCall"])
        self.assertIn("call-secret", checkpoint["completedToolCallIds"])
        self.assertEqual(checkpoint["toolResults"][-1]["status"], "failed")
        lifecycle = [
            event["type"]
            for event in events
            if event["type"] in {"tool.failed", "run.paused"}
        ]
        self.assertEqual(lifecycle[-2:], ["tool.failed", "run.paused"])
        failed_event = next(
            event
            for event in reversed(events)
            if event["type"] == "tool.failed"
        )
        self.assertEqual(failed_event["data"]["toolCallId"], "call-secret")
        self.assertEqual(failed_event["data"]["error"]["code"], "approval_scope_mismatch")

    def test_cancel_during_blocking_runtime_is_not_overwritten_by_late_completion(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        started = threading.Event()
        release = threading.Event()

        class BlockingRuntime:
            def status(self, _profile_id=None):
                return {"available": True, "runtime": "test"}

            def start(self, _request, _emit, _cancel, *, timeout_sec=None):
                started.set()
                release.wait(2)
                return {"final": {"text": "late runtime completion"}}

        with tempfile.TemporaryDirectory() as root:
            runtime = BlockingRuntime()
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-runtime-race")
            outcome: dict[str, dict] = {}
            worker = threading.Thread(
                target=lambda: outcome.setdefault(
                    "run",
                    orchestrator.execute_run("session-1", "run-runtime-race", {"prompt": "block"}),
                )
            )
            worker.start()
            self.assertTrue(started.wait(1))

            cancelled = orchestrator.cancel_run("run-runtime-race", session_id="session-1")
            release.set()
            worker.join(2)

            self.assertFalse(worker.is_alive())
            stored = repository.get_run("run-runtime-race", session_id="session-1")
            events = bus.replay("session-1")
            messages = repository.page_messages("session-1")["messages"]

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(outcome["run"]["status"], "cancelled")
        self.assertEqual(stored["status"], "cancelled")
        self.assertEqual(messages, [])
        self.assertNotIn("message.completed", [event["type"] for event in events])
        self.assertNotIn("run.completed", [event["type"] for event in events])

    def test_pause_during_blocking_approved_tool_is_not_overwritten_by_late_completion(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        started = threading.Event()
        release = threading.Event()
        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-blocking-publish",
                            "name": "loom.phone.publish",
                            "input": {"target": {"deviceIds": ["phone-1"]}, "text": "approved post"},
                        }
                    ]
                }
            ]
        )

        def blocking_operation(_payload):
            started.set()
            release.wait(2)
            return {"ok": True}

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime, operation=blocking_operation)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-tool-race")
            waiting = orchestrator.execute_run("session-1", "run-tool-race", {"prompt": "publish"})
            approval = repository.list_approvals("session-1", run_id="run-tool-race")[0]
            outcome: dict[str, dict] = {}
            worker = threading.Thread(
                target=lambda: outcome.setdefault(
                    "result",
                    orchestrator.resolve_approval(
                        "session-1",
                        approval["approvalId"],
                        decision="approved",
                        decided_by="user-1",
                        request={"prompt": "publish"},
                    ),
                )
            )
            worker.start()
            self.assertTrue(started.wait(1))

            paused = orchestrator.pause_run("run-tool-race", session_id="session-1")
            release.set()
            worker.join(2)

            self.assertFalse(worker.is_alive())
            stored = repository.get_run("run-tool-race", session_id="session-1")

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(outcome["result"]["run"]["status"], "paused")
        self.assertEqual(stored["status"], "paused")

    def test_matrix_dispatch_targets_are_bound_to_the_run_request(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-scoped-dispatch",
                            "name": "loom.matrix.dispatch",
                            "input": {
                                "targets": {"deviceIds": ["phone-attacker"]},
                                "prompt": "读取屏幕",
                            },
                        }
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(
                root,
                runtime,
                approval_mode="weak",
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-target-scope")

            completed = orchestrator.execute_run(
                "session-1",
                "run-target-scope",
                {"prompt": "inspect", "targets": {"deviceIds": ["phone-1"]}},
            )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(calls[0]["targets"], {"deviceIds": ["phone-1"]})

    def test_matrix_tools_cannot_invent_a_device_scope_for_an_unscoped_run(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-unscoped-dispatch",
                            "name": "loom.matrix.dispatch",
                            "input": {"targets": {"deviceIds": ["phone-attacker"]}, "prompt": "inspect"},
                        }
                    ]
                }
            ]
        )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-unscoped-target")

            failed = orchestrator.execute_run(
                "session-1",
                "run-unscoped-target",
                {"prompt": "inspect a phone"},
            )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "matrix_target_scope_required")
        self.assertEqual(calls, [])

    def test_matrix_cancel_and_retry_campaigns_are_bound_to_the_run_request(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime(
            [
                {
                    "toolCalls": [
                        {
                            "toolCallId": "call-scoped-cancel",
                            "name": "loom.matrix.cancel",
                            "input": {"campaignId": "cmp-attacker"},
                        },
                        {
                            "toolCallId": "call-scoped-retry",
                            "name": "loom.matrix.retry",
                            "input": {"id": "cmp-attacker"},
                        },
                    ]
                },
                {"final": {"text": "done"}},
            ]
        )

        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-campaign-scope")

            completed = orchestrator.execute_run(
                "session-1",
                "run-campaign-scope",
                {"prompt": "repair campaign", "campaignIds": ["cmp-allowed"]},
            )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(calls, [{"campaignId": "cmp-allowed"}, {"campaignId": "cmp-allowed"}])

    def test_single_phone_write_cannot_escape_request_scope(self) -> None:
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import PolicyViolationError

        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, _registry, policy, _calls = self._dependencies(root, runtime)
            registry = CapabilityRegistry(
                internal_operations={},
                skill_provider=lambda: [],
                mcp_provider=lambda: [{
                    "server": "loom",
                    "name": "loom_phone_quick_task",
                    "permission": "control",
                    "risk": "control_safe",
                    "targetScope": "single-device-write",
                }],
                mcp_executor=lambda _server, _tool, _payload: {"ok": True},
                cli_catalog_provider=lambda: {"domains": []},
            )
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            capability = registry.get("loom.mcp.loom.loom_phone_quick_task")

            with self.assertRaisesRegex(PolicyViolationError, "phone_target_scope_required"):
                orchestrator._bind_execution_scope(
                    "session-1",
                    "run-phone-scope",
                    {
                        "toolCallId": "phone-write",
                        "name": capability.name,
                        "input": {"deviceId": "P99", "prompt": "open app"},
                    },
                    capability,
                    {"requestScope": {"targets": {"deviceIds": ["P01"]}}},
                )

    def test_optional_device_write_inherits_selected_phone_scope(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator

        capability = Capability(
            name="loom.media.image.generate",
            source="internal",
            permission="control",
            risk="control_safe",
            timeout_sec=600,
            target_scope="optional-device-write",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            bound = orchestrator._bind_execution_scope(
                "session-1",
                "run-media-scope",
                {
                    "toolCallId": "media-image",
                    "name": capability.name,
                    "input": {"prompt": "檀木手串海报"},
                },
                capability,
                {"requestScope": {"targets": {"deviceIds": ["phone-1"]}}},
            )

        self.assertEqual(bound["input"]["deviceIds"], ["phone-1"])

    def test_optional_device_write_preserves_group_and_all_online_scope(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator

        capability = Capability(
            name="loom.media.image.generate",
            source="internal",
            permission="control",
            risk="control_safe",
            timeout_sec=600,
            target_scope="optional-device-write",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            grouped = orchestrator._bind_execution_scope(
                "session-1",
                "run-media-group",
                {
                    "toolCallId": "media-image-group",
                    "name": capability.name,
                    "input": {"prompt": "group poster", "deviceIds": ["phone-attacker"]},
                },
                capability,
                {"requestScope": {"targets": {"groups": ["招聘一组"]}}},
            )
            all_online = orchestrator._bind_execution_scope(
                "session-1",
                "run-media-online",
                {
                    "toolCallId": "media-image-online",
                    "name": capability.name,
                    "input": {"prompt": "online poster", "deviceIds": ["phone-attacker"]},
                },
                capability,
                {"requestScope": {"targets": {"allOnline": True}}},
            )

        self.assertEqual(grouped["input"].get("groups"), ["招聘一组"])
        self.assertNotIn("deviceIds", grouped["input"])
        self.assertTrue(all_online["input"].get("allOnline"))
        self.assertNotIn("deviceIds", all_online["input"])

    def test_optional_device_write_ignores_model_target_without_request_scope(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator

        capability = Capability(
            name="loom.media.image.generate",
            source="internal",
            permission="control",
            risk="control_safe",
            timeout_sec=600,
            target_scope="optional-device-write",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            bound = orchestrator._bind_execution_scope(
                "session-1",
                "run-media-no-scope",
                {
                    "toolCallId": "media-image",
                    "name": capability.name,
                    "input": {"prompt": "poster", "deviceIds": ["phone-attacker"]},
                },
                capability,
                {},
            )

        self.assertNotIn("deviceIds", bound["input"])

    def test_single_phone_write_requires_one_device_and_never_truncates_matrix_scope(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import PolicyViolationError

        capability = Capability(
            name="loom.mcp.loom.loom_phone_quick_task",
            source="mcp",
            permission="control",
            risk="control_safe",
            timeout_sec=30,
            target_scope="single-device-write",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            with self.assertRaisesRegex(PolicyViolationError, "phone_single_target_required"):
                orchestrator._bind_execution_scope(
                    "session-1",
                    "run-phone-multiple",
                    {
                        "toolCallId": "phone-write",
                        "name": capability.name,
                        "input": {"prompt": "open app"},
                    },
                    capability,
                    {"requestScope": {"targets": {"deviceIds": ["P01", "P02"]}}},
                )

    def test_single_phone_read_rejects_a_declared_device_outside_request_scope(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import PolicyViolationError

        capability = Capability(
            name="loom.cli.phone.screenshot",
            source="cli",
            permission="read",
            risk="read",
            timeout_sec=30,
            target_scope="single-device-read",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            with self.assertRaisesRegex(PolicyViolationError, "phone_target_scope_required"):
                orchestrator._bind_execution_scope(
                    "session-1",
                    "run-phone-read",
                    {
                        "toolCallId": "phone-read",
                        "name": capability.name,
                        "input": {"args": ["--device-id", "P99"]},
                    },
                    capability,
                    {"requestScope": {"targets": {"deviceIds": ["P01", "P02"]}}},
                )

    def test_cli_phone_scope_is_injected_as_authoritative_argument(self) -> None:
        from core.agent_capabilities import Capability
        from core.agent_orchestrator import AgentOrchestrator

        capability = Capability(
            name="loom.cli.phone.quick-task",
            source="cli",
            permission="control",
            risk="control_safe",
            timeout_sec=30,
            target_scope="single-device-write",
            executor=lambda _payload: {"ok": True},
        )
        with tempfile.TemporaryDirectory() as root:
            runtime = ScriptedRuntime([])
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)

            bound = orchestrator._bind_execution_scope(
                "session-1",
                "run-phone-cli",
                {
                    "toolCallId": "phone-write",
                    "name": capability.name,
                    "input": {"args": ["--prompt", "open app"]},
                },
                capability,
                {"requestScope": {"targets": {"deviceIds": ["P01"]}}},
            )

        args = bound["input"]["args"]
        self.assertEqual(args[args.index("--device-id") + 1], "P01")

    def test_message_completed_emits_the_complete_persisted_agent_message(self) -> None:
        from core.agent_orchestrator import AgentOrchestrator

        runtime = ScriptedRuntime([{"final": {"text": "Persisted answer"}}])
        with tempfile.TemporaryDirectory() as root:
            repository, bus, registry, policy, _calls = self._dependencies(root, runtime)
            orchestrator = AgentOrchestrator(repository, bus, runtime, registry, policy)
            orchestrator.queue_run("session-1", run_id="run-message-contract")

            orchestrator.execute_run("session-1", "run-message-contract", {"prompt": "answer"})
            persisted = repository.page_messages("session-1")["messages"][0]
            completed_event = next(event for event in bus.replay("session-1") if event["type"] == "message.completed")

        self.assertEqual(completed_event["data"]["message"], persisted)
        self.assertEqual(persisted["schema"], "loom.agent.message.v1")
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["blocks"], [{"type": "text", "data": {"text": "Persisted answer"}}])


if __name__ == "__main__":
    unittest.main()
