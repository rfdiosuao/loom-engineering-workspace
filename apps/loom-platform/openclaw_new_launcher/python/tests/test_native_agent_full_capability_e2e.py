from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class ScriptedRuntime:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def status(self, _profile_id=None):
        return {"available": True, "runtime": "full-capability-e2e"}

    def start(self, request, _emit, cancel, *, timeout_sec=None):
        if cancel.is_set():
            raise AssertionError("runtime started after cancellation")
        self.requests.append(dict(request))
        return self.responses.pop(0)


class NativeAgentFullCapabilityE2ETests(unittest.TestCase):
    def test_native_agent_executes_media_phone_and_matrix_capabilities_end_to_end(self) -> None:
        import loom_cli
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_events import AgentEventBus
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        tool_calls = [
            ("loom.matrix.status", {}),
            ("loom.media.image.generate", {"prompt": "生成招聘海报", "count": 2, "ratio": "5:2"}),
            ("loom.media.image.generate", {"prompt": "把标题改为招聘中", "editImagePath": "D:/media/reference.png"}),
            ("loom.media.video.generate", {"prompt": "让招聘海报自然动起来", "imagePath": "D:/media/reference.png", "duration": 5}),
            ("loom.cli.phone.screenshot", {"args": []}),
            ("loom.cli.phone.read", {"args": ["--prompt", "读取当前页面"]}),
            ("loom.cli.phone.quick-task", {"args": ["--prompt", "返回应用首页"]}),
            ("loom.matrix.dispatch", {"prompt": "读取屏幕"}),
        ]
        responses = [
            {
                "toolCalls": [{
                    "toolCallId": f"call-{index}",
                    "name": capability,
                    "input": tool_input,
                }]
            }
            for index, (capability, tool_input) in enumerate(tool_calls, start=1)
        ]
        responses.append({"final": {"text": "全部能力已完成"}})
        runtime = ScriptedRuntime(responses)
        executions: list[dict] = []

        def internal_executor(capability_name: str):
            def execute(payload):
                executions.append({"name": capability_name, "source": "internal", "input": dict(payload)})
                if capability_name == "loom.matrix.dispatch":
                    return {"campaignId": "campaign-full-e2e", "counts": {"total": 1, "completed": 1, "failed": 0}}
                if capability_name.startswith("loom.media"):
                    return {"jobId": f"job-{len(executions)}", "kind": "video" if "video" in capability_name else "image", "status": "queued"}
                return {"ok": True, "status": "ready"}
            return execute

        def cli_executor(command: str, payload: dict):
            executions.append({"name": f"loom.cli.{command.replace(' ', '.')}", "source": "cli", "command": command, "input": dict(payload)})
            return {"ok": True, "command": command, "status": "completed"}

        class RecordingPolicy(AgentPolicyEngine):
            def __init__(self):
                super().__init__(authorized_device_ids={"phone-1"}, approval_mode="weak")
                self.decisions: list[dict] = []

            def evaluate(self, capability, tool_input=None):
                decision = super().evaluate(capability, tool_input)
                self.decisions.append({
                    "capability": capability.name,
                    "input": dict(tool_input or {}),
                    **decision.to_dict(),
                })
                return decision

        registry = CapabilityRegistry(
            internal_operations={
                capability: {"executor": internal_executor(capability)}
                for capability in {
                    "loom.matrix.status",
                    "loom.matrix.dispatch",
                    "loom.media.image.generate",
                    "loom.media.video.generate",
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=loom_cli._command_catalog,
            cli_executor=cli_executor,
        )
        selected_names = {name for name, _tool_input in tool_calls}
        catalog = {
            item["name"]: item
            for item in registry.list_capabilities(available_only=True)
            if item["name"] in selected_names
        }

        self.assertEqual(set(catalog), selected_names)
        for name, capability in catalog.items():
            self.assertRegex(capability["displayName"], r"[\u3400-\u9fff]", name)
            self.assertTrue(capability["available"], name)
            self.assertIn(capability["source"], {"internal", "cli"})
            self.assertEqual(capability["inputSchema"].get("type"), "object")
            self.assertIn(capability["targetScope"], {
                "none",
                "optional-device-write",
                "single-device-read",
                "single-device-write",
                "matrix-write",
            })

        policy = RecordingPolicy()
        with tempfile.TemporaryDirectory() as root:
            repository = AgentSessionRepository(root)
            repository.create_session("完整能力验收", session_id="session-full-e2e")
            event_bus = AgentEventBus(repository)
            orchestrator = AgentOrchestrator(repository, event_bus, runtime, registry, policy)
            orchestrator.queue_run("session-full-e2e", run_id="run-full-e2e")
            result = orchestrator.execute_run(
                "session-full-e2e",
                "run-full-e2e",
                {
                    "prompt": "完成原生能力验收",
                    "scopeMode": "manual",
                    "targets": {"deviceIds": ["phone-1"]},
                },
            )
            events = event_bus.replay("session-full-e2e")

        self.assertEqual(result["status"], "completed")
        self.assertNotIn("error", result)
        self.assertEqual(len(executions), len(tool_calls))
        self.assertEqual([item["capability"] for item in policy.decisions], [name for name, _input in tool_calls])
        self.assertTrue(all(item["allowed"] for item in policy.decisions))
        self.assertTrue(all(not item["requiresApproval"] for item in policy.decisions))
        self.assertEqual([event["type"] for event in events].count("tool.completed"), len(tool_calls))
        self.assertNotIn("tool.failed", [event["type"] for event in events])

        screenshot = next(item for item in executions if item["name"] == "loom.cli.phone.screenshot")
        phone_read = next(item for item in executions if item["name"] == "loom.cli.phone.read")
        quick_task = next(item for item in executions if item["name"] == "loom.cli.phone.quick-task")
        matrix = next(item for item in executions if item["name"] == "loom.matrix.dispatch")
        for phone_call in (screenshot, phone_read, quick_task):
            self.assertEqual(phone_call["input"]["args"][-2:], ["--device-id", "phone-1"])
        self.assertEqual(matrix["input"]["targets"], {"deviceIds": ["phone-1"]})

        checkpoint = json.loads(result["checkpoint"])
        self.assertEqual(len(checkpoint["toolResults"]), len(tool_calls))
        self.assertEqual(runtime.requests[-1]["toolResults"][-1]["capability"], "loom.matrix.dispatch")


if __name__ == "__main__":
    unittest.main()
