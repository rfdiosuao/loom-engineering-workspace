from __future__ import annotations

import os
import json
import re
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from typing import Any


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


def _minimal_value(schema: Mapping[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        return schema["default"]
    examples = schema.get("examples")
    if isinstance(examples, Sequence) and not isinstance(examples, (str, bytes)) and examples:
        return examples[0]
    expected = schema.get("type")
    allowed = schema.get("enum")
    if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)) and allowed:
        return allowed[0]
    if expected == "string":
        return "test-value"
    if expected == "integer":
        return max(1, int(schema.get("minimum") or 0))
    if expected == "number":
        return max(1.0, float(schema.get("minimum") or 0))
    if expected == "boolean":
        return True
    if expected == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), Mapping) else {}
        return [_minimal_value(item_schema)]
    if expected == "object" or isinstance(schema.get("properties"), Mapping):
        properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        required = [
            str(key)
            for key in schema.get("required", [])
            if isinstance(key, str)
        ] if isinstance(schema.get("required"), Sequence) else []
        any_of = schema.get("anyOf")
        if isinstance(any_of, Sequence) and not isinstance(any_of, (str, bytes)) and any_of:
            first = any_of[0] if isinstance(any_of[0], Mapping) else {}
            option_required = first.get("required") if isinstance(first.get("required"), Sequence) else []
            required.extend(str(key) for key in option_required if isinstance(key, str))
        result: dict[str, Any] = {}
        for key in dict.fromkeys(required):
            child = properties.get(key) if isinstance(properties.get(key), Mapping) else {}
            result[key] = _minimal_value(child)
        return result
    return "test-value"


class _SingleToolRuntime:
    def __init__(self, capability_name: str, payload: Mapping[str, Any]):
        self.responses = [
            {
                "toolCalls": [{
                    "toolCallId": "all-tools-call",
                    "name": capability_name,
                    "input": dict(payload),
                }],
            },
            {"final": {"text": "done"}},
        ]

    def status(self, _profile_id=None):
        return {"available": True, "runtime": "all-tools-contract"}

    def start(self, _request, _emit, cancel, *, timeout_sec=None):
        if cancel.is_set():
            raise AssertionError("runtime started after cancellation")
        return self.responses.pop(0)


class AgentAllToolsContractTests(unittest.TestCase):
    def test_every_mcp_tool_matches_cli_permission_and_target_scope(self) -> None:
        import loom_cli
        import loom_mcp

        catalog = {
            command["name"]: command
            for domain in loom_cli._command_catalog()["domains"]
            for command in domain["commands"]
        }
        for tool in loom_mcp.tool_definitions():
            payload = _minimal_value(tool["inputSchema"])
            argv = loom_mcp._tool_to_cli_args(str(tool["name"]), payload)
            matches = [
                (name, command)
                for name, command in catalog.items()
                if argv[: len(name.split())] == name.split()
            ]
            self.assertTrue(matches, tool["name"])
            cli_name, cli_command = max(matches, key=lambda item: len(item[0].split()))
            self.assertIn(
                tool["permission"],
                str(cli_command["permission"]).split("/"),
                f"{tool['name']} -> {cli_name}",
            )
            self.assertEqual(
                tool.get("targetScope", "none"),
                cli_command.get("targetScope", "none"),
                f"{tool['name']} -> {cli_name}",
            )

    def test_every_builtin_mcp_tool_reaches_real_cli_dry_run(self) -> None:
        import loom_mcp

        failures: dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            for tool in loom_mcp.tool_definitions():
                name = str(tool["name"])
                payload = _minimal_value(tool["inputSchema"])
                payload["dryRun"] = True
                result = loom_mcp.call_tool(
                    name,
                    payload,
                    permission=str(tool["permission"]),
                    base_path=temp_dir,
                    trusted_internal=True,
                )
                content = json.loads(result["content"][0]["text"])
                if result.get("isError") or not content.get("ok"):
                    failures[name] = content.get("error") or content

        self.assertEqual(failures, {})

    def test_every_single_device_tool_schema_accepts_bound_device_id(self) -> None:
        import loom_mcp

        for tool in loom_mcp.tool_definitions():
            if tool.get("targetScope") not in {"single-device-read", "single-device-write"}:
                continue
            properties = tool["inputSchema"].get("properties", {})
            self.assertIn("deviceId", properties, tool["name"])
            self.assertEqual(properties["deviceId"].get("type"), "string", tool["name"])

    def test_every_builtin_mcp_tool_rejects_undeclared_input_fields(self) -> None:
        import loom_mcp
        from core.agent_capabilities import CapabilityInputError, CapabilityRegistry

        definitions = loom_mcp.tool_definitions()
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{"server": "loom", **tool} for tool in definitions],
            mcp_executor=lambda _server, _tool, _payload: {"ok": True},
            cli_catalog_provider=lambda: {"domains": []},
        )

        for tool in definitions:
            name = f"loom.mcp.loom.{tool['name']}"
            payload = _minimal_value(tool["inputSchema"])
            payload["undeclaredTargetOverride"] = "phone-attacker"
            with self.assertRaises(CapabilityInputError, msg=name):
                registry.validate_input(name, payload)

    def test_every_builtin_mcp_tool_has_localized_agent_metadata(self) -> None:
        import loom_mcp
        from core.agent_capabilities import CapabilityRegistry

        definitions = loom_mcp.tool_definitions()
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{"server": "loom", **tool} for tool in definitions],
            mcp_executor=lambda _server, _tool, _payload: {"ok": True},
            cli_catalog_provider=lambda: {"domains": []},
        )

        capabilities = registry.list_capabilities(available_only=True)
        self.assertEqual(len(capabilities), len(definitions))
        for capability in capabilities:
            self.assertRegex(capability["displayName"], r"[\u3400-\u9fff]", capability["name"])
            self.assertRegex(capability["description"], r"[\u3400-\u9fff]", capability["name"])
            self.assertNotEqual(capability["domain"], "general", capability["name"])

    def test_every_builtin_mcp_tool_is_reachable_by_its_agent_metadata(self) -> None:
        import loom_mcp
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_capability_router import route_capabilities

        definitions = loom_mcp.tool_definitions()
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{"server": "loom", **tool} for tool in definitions],
            mcp_executor=lambda _server, _tool, _payload: {"ok": True},
            cli_catalog_provider=lambda: {"domains": []},
        )
        capabilities = registry.list_capabilities(available_only=True)

        for capability in capabilities:
            for metadata_field in ("displayName", "description"):
                selected, metadata = route_capabilities(
                    {"prompt": capability[metadata_field]},
                    capabilities,
                )
                selected_names = {item["name"] for item in selected}
                self.assertIn(
                    capability["name"],
                    selected_names,
                    f"{metadata_field}: {capability['name']} -> {metadata}",
                )

    def test_every_builtin_mcp_tool_round_trips_through_agent_registry(self) -> None:
        import loom_mcp
        from core.agent_capabilities import CapabilityRegistry
        from core.loom_model_client import _model_tool_alias_maps

        definitions = loom_mcp.tool_definitions()
        calls: list[tuple[str, dict[str, Any]]] = []
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{"server": "loom", **tool} for tool in definitions],
            mcp_executor=lambda _server, tool, payload: calls.append((tool, dict(payload))) or {"ok": True},
            cli_catalog_provider=lambda: {"domains": []},
        )

        capabilities = registry.list_capabilities(available_only=True)
        self.assertEqual(len(capabilities), len(definitions))
        canonical_to_alias, alias_to_canonical = _model_tool_alias_maps(capabilities)
        self.assertEqual(len(canonical_to_alias), len(capabilities))
        self.assertEqual(len(alias_to_canonical), len(capabilities))

        for capability in capabilities:
            name = str(capability["name"])
            alias = canonical_to_alias[name]
            self.assertLessEqual(len(alias), 64, name)
            self.assertRegex(alias, re.compile(r"^[A-Za-z0-9_-]+$"), name)
            self.assertEqual(alias_to_canonical[alias], name)
            payload = _minimal_value(capability["inputSchema"])
            resolved, validated = registry.validate_input(name, payload)
            self.assertEqual(resolved.source, "mcp", name)
            self.assertEqual(validated, payload, name)
            self.assertTrue(registry.execute(name, payload)["ok"], name)

        self.assertEqual(
            {tool for tool, _payload in calls},
            {str(tool["name"]) for tool in definitions},
        )
        self.assertEqual(len(calls), len(definitions))

    def test_every_builtin_mcp_tool_completes_the_real_agent_orchestration_path(self) -> None:
        import loom_mcp
        from core.agent_capabilities import CapabilityRegistry
        from core.agent_events import AgentEventBus
        from core.agent_orchestrator import AgentOrchestrator
        from core.agent_policy import AgentPolicyEngine
        from core.agent_sessions import AgentSessionRepository

        definitions = loom_mcp.tool_definitions()
        calls: list[dict[str, Any]] = []

        def execute(_server, tool, payload, *, permission=None):
            calls.append({"tool": tool, "payload": dict(payload), "permission": permission})
            return {"ok": True, "tool": tool}

        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{"server": "loom", **tool} for tool in definitions],
            mcp_executor=execute,
            cli_catalog_provider=lambda: {"domains": []},
        )
        capabilities = registry.list_capabilities(available_only=True)
        expected_approvals = sum(capability["risk"] == "critical" for capability in capabilities)
        approval_count = 0

        with tempfile.TemporaryDirectory() as root:
            repository = AgentSessionRepository(root)
            event_bus = AgentEventBus(repository)
            for index, capability in enumerate(capabilities):
                session_id = f"all-tools-session-{index}"
                run_id = f"all-tools-run-{index}"
                repository.create_session(capability["displayName"], session_id=session_id)
                payload = _minimal_value(capability["inputSchema"])
                target_scope = capability["targetScope"]
                request: dict[str, Any] = {
                    "prompt": capability["displayName"],
                    "capabilityHints": [capability["name"]],
                }
                if target_scope in {
                    "single-device-read",
                    "single-device-write",
                    "optional-device-write",
                }:
                    for key in ("deviceId", "device", "target"):
                        payload.pop(key, None)
                    request["targets"] = {"deviceIds": ["phone-1"]}
                elif target_scope == "matrix-write":
                    request["targets"] = {"allOnline": True}
                elif target_scope == "campaign-write":
                    request["campaignIds"] = ["campaign-1"]

                before_calls = len(calls)
                orchestrator = AgentOrchestrator(
                    repository,
                    event_bus,
                    _SingleToolRuntime(capability["name"], payload),
                    registry,
                    AgentPolicyEngine(approval_mode="strong"),
                )
                orchestrator.queue_run(session_id, run_id=run_id)
                result = orchestrator.execute_run(session_id, run_id, request)
                if result["status"] == "waiting_approval":
                    approval_count += 1
                    approvals = repository.list_approvals(session_id, run_id=run_id)
                    self.assertEqual(len(approvals), 1, capability["name"])
                    result = orchestrator.resolve_approval(
                        session_id,
                        approvals[0]["approvalId"],
                        decision="approved",
                        decided_by="contract-test",
                        request=request,
                    )["run"]

                self.assertEqual(result["status"], "completed", capability["name"])
                self.assertEqual(len(calls), before_calls + 1, capability["name"])
                if target_scope in {"single-device-read", "single-device-write"}:
                    self.assertEqual(calls[-1]["payload"]["deviceId"], "phone-1", capability["name"])

        self.assertEqual(len(calls), len(capabilities))
        self.assertEqual(approval_count, expected_approvals)


if __name__ == "__main__":
    unittest.main()
