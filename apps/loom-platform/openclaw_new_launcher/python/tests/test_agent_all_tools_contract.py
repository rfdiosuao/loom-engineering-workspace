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


if __name__ == "__main__":
    unittest.main()
