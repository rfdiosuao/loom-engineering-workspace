from __future__ import annotations

import json
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class CapabilityRegistryTests(unittest.TestCase):
    def _registry(self):
        from core.agent_capabilities import CapabilityRegistry

        return CapabilityRegistry(
            internal_operations={
                "loom.matrix.dispatch": {
                    "executor": lambda payload: {"campaignId": "cmp-1", "request": payload},
                    "permission": "control",
                    "risk": "control_safe",
                    "timeoutSec": 3,
                    "inputSchema": {
                        "type": "object",
                        "required": ["targets"],
                        "properties": {"targets": {"type": "object"}},
                    },
                }
            },
            skill_provider=lambda: {
                "skills": [
                    {"id": "screen-reader", "enabled": True, "installed": True, "description": "Read a screen", "permission": "read", "risk": "read"},
                    {"id": "disabled-skill", "enabled": False, "installed": True},
                ]
            },
            skill_executor=lambda skill_id, payload: {"skill": skill_id, "payload": payload},
            mcp_provider=lambda: [
                {
                    "server": "local",
                    "name": "search_logs",
                    "description": "Search logs",
                    "inputSchema": {"type": "object"},
                    "permission": "read",
                    "risk": "read",
                }
            ],
            mcp_executor=lambda server, tool, payload: {"server": server, "tool": tool, "payload": payload},
            cli_catalog_provider=lambda: {
                "domains": [
                    {
                        "commands": [
                            {"name": "phone status", "permission": "read", "risk": "read"},
                            {"name": "matrix dispatch", "permission": "control", "risk": "control_safe"},
                            {"name": "settings update-do", "permission": "admin"},
                        ]
                    }
                ]
            },
            cli_executor=lambda command, payload: {"command": command, "payload": payload},
        )

    def test_registry_exposes_all_sources_with_complete_metadata(self) -> None:
        registry = self._registry()

        capabilities = {item["name"]: item for item in registry.list_capabilities()}

        self.assertIn("loom.matrix.dispatch", capabilities)
        self.assertEqual(capabilities["loom.matrix.dispatch"]["displayName"], "下发矩阵任务")
        self.assertEqual(capabilities["loom.matrix.dispatch"]["domain"], "matrix")
        self.assertEqual(capabilities["loom.matrix.dispatch"]["targetScope"], "matrix-write")
        self.assertTrue(capabilities["loom.matrix.dispatch"]["available"])
        self.assertIn("loom.skill.screen-reader", capabilities)
        self.assertEqual(capabilities["loom.skill.screen-reader"]["permission"], "read")
        self.assertEqual(capabilities["loom.skill.screen-reader"]["risk"], "read")
        self.assertIn("loom.mcp.local.search_logs", capabilities)
        self.assertIn("loom.cli.phone.status", capabilities)
        self.assertNotIn("loom.skill.disabled-skill", capabilities)
        self.assertNotIn("loom.cli.settings.update-do", capabilities)
        for capability in capabilities.values():
            self.assertIn(capability["source"], {"internal", "skill", "mcp", "cli"})
            self.assertIn("permission", capability)
            self.assertIn("risk", capability)
            self.assertGreater(capability["timeoutSec"], 0)
            self.assertIsInstance(capability["inputSchema"], dict)
            self.assertIsInstance(capability["outputSchema"], dict)

    def test_model_catalog_contains_only_connected_capabilities(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={"loom.connected": {"executor": lambda _payload: {"ok": True}}},
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        full_catalog = {item["name"]: item for item in registry.list_capabilities()}
        model_catalog = {item["name"]: item for item in registry.list_capabilities(available_only=True)}

        self.assertIn("loom.media.image.generate", full_catalog)
        self.assertFalse(full_catalog["loom.media.image.generate"]["available"])
        self.assertNotIn("loom.media.image.generate", model_catalog)
        self.assertIn("loom.connected", model_catalog)
        self.assertTrue(model_catalog["loom.connected"]["available"])

    def test_builtin_capabilities_have_chinese_display_metadata(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        internal_capabilities = [
            item
            for item in CapabilityRegistry(
                mcp_provider=lambda: [],
                cli_catalog_provider=lambda: {"domains": []},
            ).list_capabilities()
            if item["source"] == "internal"
        ]

        self.assertTrue(internal_capabilities)
        for item in internal_capabilities:
            self.assertTrue(item["displayName"])
            self.assertTrue(item["description"])
            self.assertTrue(item["domain"])
            self.assertTrue(item["targetScope"])

        matrix_dispatch = next(
            item for item in internal_capabilities if item["name"] == "loom.matrix.dispatch"
        )
        self.assertEqual(matrix_dispatch["displayName"], "下发矩阵任务")
        self.assertEqual(matrix_dispatch["domain"], "matrix")
        self.assertEqual(matrix_dispatch["targetScope"], "matrix-write")

        expected_scopes = {
            "loom.capabilities.list": "none",
            "loom.matrix.status": "none",
            "loom.matrix.dispatch": "matrix-write",
            "loom.matrix.screenshot": "single-device-read",
            "loom.matrix.cancel": "campaign-write",
            "loom.matrix.retry": "campaign-write",
            "loom.media.image.generate": "optional-device-write",
            "loom.media.video.generate": "optional-device-write",
            "loom.logs.tail": "none",
        }
        actual_scopes = {item["name"]: item["targetScope"] for item in internal_capabilities}
        self.assertEqual(actual_scopes, expected_scopes)
        self.assertTrue(
            set(actual_scopes.values()).issubset({
                "none",
                "optional-device-write",
                "single-device-read",
                "single-device-write",
                "matrix-write",
                "campaign-write",
            })
        )

    def test_loom_mcp_and_cli_capabilities_have_chinese_model_metadata(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        capabilities = [
            item
            for item in CapabilityRegistry(skill_provider=lambda: []).list_capabilities(available_only=True)
            if item["source"] in {"mcp", "cli"}
        ]

        self.assertTrue(capabilities)
        for item in capabilities:
            self.assertRegex(item["displayName"], r"[\u3400-\u9fff]", item["name"])
            self.assertRegex(item["description"], r"[\u3400-\u9fff]", item["name"])
            self.assertNotEqual(item["domain"], "general", item["name"])

    def test_mcp_tools_without_security_metadata_fail_closed(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [
                {"server": "remote", "name": "unclassified"},
                {"server": "remote", "name": "missing_permission", "risk": "read"},
                {"server": "remote", "name": "missing_risk", "permission": "read"},
            ],
            cli_catalog_provider=lambda: {"domains": []},
        )

        capabilities = {item["name"]: item for item in registry.list_capabilities()}

        self.assertEqual(capabilities["loom.mcp.remote.unclassified"]["permission"], "admin")
        self.assertEqual(capabilities["loom.mcp.remote.unclassified"]["risk"], "critical")
        self.assertEqual(capabilities["loom.mcp.remote.missing_permission"]["permission"], "admin")
        self.assertEqual(capabilities["loom.mcp.remote.missing_permission"]["risk"], "critical")
        self.assertEqual(capabilities["loom.mcp.remote.missing_risk"]["permission"], "read")
        self.assertEqual(capabilities["loom.mcp.remote.missing_risk"]["risk"], "critical")

    def test_default_mcp_executor_connects_only_builtin_loom_server(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [
                {
                    "server": "loom",
                    "name": "loom_status",
                    "permission": "read",
                    "risk": "read",
                },
                {
                    "server": "custom",
                    "name": "remote_search",
                    "permission": "read",
                    "risk": "read",
                },
            ],
            cli_catalog_provider=lambda: {"domains": []},
        )

        full_catalog = {item["name"]: item for item in registry.list_capabilities()}
        executable_catalog = {
            item["name"]: item for item in registry.list_capabilities(available_only=True)
        }

        self.assertTrue(full_catalog["loom.mcp.loom.loom_status"]["available"])
        self.assertFalse(full_catalog["loom.mcp.custom.remote_search"]["available"])
        self.assertIn("loom.mcp.loom.loom_status", executable_catalog)
        self.assertNotIn("loom.mcp.custom.remote_search", executable_catalog)

    def test_invalid_target_scopes_fail_closed_for_every_capability_source(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={
                "loom.custom.invalid-scope": {
                    "executor": lambda _payload: {"ok": True},
                    "targetScope": "device_group",
                },
                "loom.custom.valid-scope": {
                    "executor": lambda _payload: {"ok": True},
                    "targetScope": "single-device-write",
                },
            },
            skill_provider=lambda: [{
                "id": "invalid-scope",
                "installed": True,
                "enabled": True,
                "permission": "read",
                "risk": "read",
                "targetScope": "device",
            }],
            mcp_provider=lambda: [{
                "server": "custom",
                "name": "invalid_scope",
                "permission": "read",
                "risk": "read",
                "targetScope": "campaign",
            }],
            cli_catalog_provider=lambda: {
                "domains": [{"commands": [{
                    "name": "status",
                    "permission": "read",
                    "risk": "read",
                    "targetScope": "all-devices",
                }]}],
            },
        )

        capabilities = {item["name"]: item for item in registry.list_capabilities()}

        self.assertEqual(capabilities["loom.custom.invalid-scope"]["targetScope"], "none")
        self.assertEqual(
            capabilities["loom.custom.valid-scope"]["targetScope"],
            "single-device-write",
        )
        self.assertEqual(capabilities["loom.skill.invalid-scope"]["targetScope"], "none")
        self.assertEqual(capabilities["loom.mcp.custom.invalid_scope"]["targetScope"], "none")
        self.assertEqual(capabilities["loom.cli.status"]["targetScope"], "none")

    def test_skill_and_cli_missing_permission_metadata_fail_closed(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [{"id": "unclassified", "enabled": True, "installed": True}],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {
                "domains": [{"commands": [
                    {"name": "phone status"},
                    {"name": "matrix watch", "permission": "read"},
                ]}],
            },
        )

        capabilities = {item["name"]: item for item in registry.list_capabilities()}

        self.assertEqual(capabilities["loom.skill.unclassified"]["permission"], "admin")
        self.assertEqual(capabilities["loom.skill.unclassified"]["risk"], "critical")
        self.assertEqual(capabilities["loom.cli.phone.status"]["permission"], "admin")
        self.assertEqual(capabilities["loom.cli.phone.status"]["risk"], "critical")
        self.assertEqual(capabilities["loom.cli.matrix.watch"]["permission"], "read")
        self.assertEqual(capabilities["loom.cli.matrix.watch"]["risk"], "read")

    def test_default_internal_catalog_includes_matrix_media_and_logs(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        names = {
            item["name"]
            for item in CapabilityRegistry(
                mcp_provider=lambda: [],
                cli_catalog_provider=lambda: {"domains": []},
            ).list_capabilities()
        }

        self.assertTrue(
            {
                "loom.matrix.status",
                "loom.matrix.dispatch",
                "loom.matrix.screenshot",
                "loom.matrix.cancel",
                "loom.matrix.retry",
                "loom.media.image.generate",
                "loom.media.video.generate",
                "loom.logs.tail",
            }.issubset(names)
        )

    def test_default_catalog_exposes_each_loom_operation_once(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(skill_provider=lambda: [])
        full_names = {item["name"] for item in registry.list_capabilities()}
        connected_names = {
            item["name"] for item in registry.list_capabilities(available_only=True)
        }

        self.assertEqual(len(full_names), 79)
        self.assertEqual(len(connected_names), 79)
        self.assertIn("loom.matrix.status", full_names)
        self.assertNotIn("loom.cli.matrix.status", full_names)
        self.assertNotIn("loom.mcp.loom.loom_matrix_status", full_names)
        self.assertNotIn("loom.mcp.loom.loom_status", connected_names)
        self.assertIn("loom.cli.status", connected_names)

    def test_native_capability_catalog_deduplicates_the_legacy_mcp_catalog(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls: list[str] = []
        registry = CapabilityRegistry(
            internal_operations={
                "loom.capabilities.list": {
                    "executor": lambda _payload: calls.append("internal") or {"count": 1},
                },
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "loom",
                "name": "loom_cli_commands",
                "permission": "read",
                "risk": "read",
            }],
            mcp_executor=lambda _server, _tool, _payload: calls.append("mcp") or {"count": 2},
            cli_catalog_provider=lambda: {"domains": []},
        )

        names = {item["name"] for item in registry.list_capabilities(available_only=True)}
        self.assertIn("loom.capabilities.list", names)
        self.assertNotIn("loom.mcp.loom.loom_cli_commands", names)
        self.assertEqual(registry.execute("loom.mcp.loom.loom_cli_commands", {}), {"count": 1})
        self.assertEqual(calls, ["internal"])

    def test_semantic_aliases_execute_the_preferred_connected_implementation(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls: list[tuple[str, str]] = []
        registry = CapabilityRegistry(
            internal_operations={
                "loom.matrix.status": {
                    "executor": lambda _payload: calls.append(("internal", "matrix status")) or {"source": "internal"},
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [
                {"server": "loom", "name": "loom_matrix_status", "permission": "read", "risk": "read"},
                {"server": "loom", "name": "loom_status", "permission": "read", "risk": "read"},
            ],
            mcp_executor=lambda _server, tool, _payload: calls.append(("mcp", tool)) or {"source": "mcp"},
            cli_catalog_provider=lambda: {
                "domains": [{"domain": "system", "commands": [
                    {"name": "status", "permission": "read", "risk": "read"},
                    {"name": "matrix status", "permission": "read", "risk": "read"},
                ]}],
            },
            cli_executor=lambda command, _payload: calls.append(("cli", command)) or {"source": "cli"},
        )

        names = {item["name"] for item in registry.list_capabilities(available_only=True)}
        self.assertIn("loom.matrix.status", names)
        self.assertIn("loom.cli.status", names)
        self.assertNotIn("loom.cli.matrix.status", names)
        self.assertNotIn("loom.mcp.loom.loom_matrix_status", names)
        self.assertNotIn("loom.mcp.loom.loom_status", names)

        self.assertEqual(registry.execute("loom.cli.matrix.status", {})["source"], "internal")
        self.assertEqual(registry.execute("loom.mcp.loom.loom_matrix_status", {})["source"], "internal")
        self.assertEqual(registry.execute("loom.mcp.loom.loom_status", {})["source"], "cli")
        self.assertEqual(calls, [
            ("internal", "matrix status"),
            ("internal", "matrix status"),
            ("cli", "status"),
        ])

    def test_internal_matrix_capabilities_expose_their_required_model_inputs(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        capabilities = {
            item["name"]: item
            for item in CapabilityRegistry(
                internal_operations={
                    name: {"executor": lambda _payload: {"ok": True}}
                    for name in {
                        "loom.matrix.dispatch",
                        "loom.matrix.screenshot",
                        "loom.matrix.cancel",
                        "loom.matrix.retry",
                    }
                },
                skill_provider=lambda: [],
            ).list_capabilities(available_only=True)
        }

        dispatch = capabilities["loom.matrix.dispatch"]["inputSchema"]
        self.assertIn("prompt", dispatch["required"])
        self.assertIn("targets", dispatch["properties"])
        self.assertEqual(
            dispatch["anyOf"],
            [{"required": ["deviceId"]}, {"required": ["group"]}, {"required": ["targets"]}],
        )
        self.assertIn("deviceId", capabilities["loom.matrix.screenshot"]["inputSchema"]["required"])
        self.assertIn("campaignId", capabilities["loom.matrix.cancel"]["inputSchema"]["required"])
        self.assertIn("campaignId", capabilities["loom.matrix.retry"]["inputSchema"]["required"])

    def test_phone_quick_task_semantic_alias_keeps_structured_mcp_contract(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls: list[tuple[str, dict]] = []
        payload = {"prompt": "Open settings", "deviceId": "phone-a", "mode": "safe"}
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "loom",
                "name": "loom_phone_quick_task",
                "inputSchema": {
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "deviceId": {"type": "string"},
                        "mode": {"type": "string"},
                    },
                },
                "permission": "control",
                "risk": "control_safe",
            }],
            mcp_executor=lambda _server, tool, data: calls.append((tool, data)) or {"ok": True},
            cli_catalog_provider=lambda: {"domains": [{"commands": [{"name": "phone quick-task"}]}]},
            cli_executor=lambda _command, _payload: self.fail("must preserve the structured executor"),
        )

        capabilities = {item["name"]: item for item in registry.list_capabilities(available_only=True)}
        quick_task = capabilities["loom.cli.phone.quick-task"]
        self.assertIn("prompt", quick_task["inputSchema"]["properties"])
        self.assertIn("deviceId", quick_task["inputSchema"]["properties"])
        self.assertTrue(registry.execute("loom.cli.phone.quick-task", payload)["ok"])
        self.assertTrue(registry.execute("loom.mcp.loom.loom_phone_quick_task", payload)["ok"])
        self.assertEqual(calls, [("loom_phone_quick_task", payload), ("loom_phone_quick_task", payload)])

    def test_phone_status_semantic_alias_is_single_read_only_operation(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls: list[tuple[str, dict]] = []
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "loom",
                "name": "loom_phone_status",
                "displayName": "查看手机状态",
                "description": "查看全部手机状态；deviceId 可选。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"deviceId": {"type": "string"}},
                },
                "permission": "read",
                "risk": "read",
                "targetScope": "none",
            }],
            mcp_executor=lambda _server, tool, data: calls.append((tool, data)) or {"ok": True},
            cli_catalog_provider=lambda: {
                "domains": [{
                    "domain": "phone",
                    "commands": [{
                        "name": "phone status",
                        "displayName": "查看手机状态",
                        "permission": "read",
                        "risk": "read",
                    }],
                }],
            },
            cli_executor=lambda _command, _payload: self.fail("must preserve the structured executor"),
        )

        capabilities = registry.list_capabilities(available_only=True)
        phone_status = [item for item in capabilities if item["displayName"] == "查看手机状态"]
        self.assertEqual(len(phone_status), 1)
        self.assertEqual(phone_status[0]["name"], "loom.cli.phone.status")
        self.assertEqual(phone_status[0]["targetScope"], "none")
        self.assertIn("deviceId", phone_status[0]["inputSchema"]["properties"])
        self.assertTrue(registry.execute("loom.cli.phone.status", {})["ok"])
        self.assertTrue(registry.execute("loom.mcp.loom.loom_phone_status", {"deviceId": "phone-a"})["ok"])
        self.assertEqual(calls, [("loom_phone_status", {}), ("loom_phone_status", {"deviceId": "phone-a"})])

    def test_semantic_aliases_prefer_structured_mcp_contracts_over_empty_cli_contracts(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls: list[tuple[str, dict]] = []
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "loom",
                "name": "loom_job_get",
                "inputSchema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
                "permission": "read",
                "risk": "read",
            }],
            mcp_executor=lambda _server, tool, data: calls.append((tool, data)) or {"ok": True},
            cli_catalog_provider=lambda: {"domains": [{"commands": [{"name": "jobs get"}]}]},
            cli_executor=lambda _command, _payload: self.fail("must preserve the structured executor"),
        )

        capabilities = {item["name"]: item for item in registry.list_capabilities(available_only=True)}
        job_get = capabilities["loom.cli.jobs.get"]
        self.assertEqual(job_get["inputSchema"]["required"], ["id"])
        self.assertIn("id", job_get["inputSchema"]["properties"])
        self.assertTrue(registry.execute("loom.cli.jobs.get", {"id": "job-1"})["ok"])
        self.assertTrue(registry.execute("loom.mcp.loom.loom_job_get", {"id": "job-2"})["ok"])
        self.assertEqual(calls, [("loom_job_get", {"id": "job-1"}), ("loom_job_get", {"id": "job-2"})])

    def test_unavailable_internal_alias_does_not_change_the_model_selected_executor(self) -> None:
        from core.agent_capabilities import CapabilityInputError, CapabilityRegistry

        calls: list[tuple[str, dict]] = []
        registry = CapabilityRegistry(
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "loom",
                "name": "loom_matrix_dispatch",
                "inputSchema": {
                    "type": "object",
                    "required": ["prompt", "targets"],
                    "properties": {
                        "prompt": {"type": "string", "minLength": 1},
                        "targets": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                "permission": "control",
                "risk": "control_safe",
            }],
            mcp_executor=lambda _server, tool, data: calls.append((tool, data)) or {"ok": True},
            cli_catalog_provider=lambda: {
                "domains": [{"domain": "matrix", "commands": [{"name": "matrix dispatch"}]}],
            },
            cli_executor=lambda _command, _payload: self.fail(
                "execution must use the same structured implementation exposed to the model"
            ),
        )

        catalog = registry.list_capabilities(available_only=True)
        self.assertEqual(len(catalog), 1)
        exposed_name = catalog[0]["name"]
        self.assertEqual(catalog[0]["source"], "mcp")
        with self.assertRaises(CapabilityInputError):
            registry.validate_input(exposed_name, {"prompt": "读取屏幕"})

        result = registry.execute(
            exposed_name,
            {"prompt": "读取屏幕", "targets": {"deviceIds": ["phone-1"]}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [(
            "loom_matrix_dispatch",
            {"prompt": "读取屏幕", "targets": {"deviceIds": ["phone-1"]}},
        )])

    def test_execute_validates_input_schema_and_dispatches_by_source(self) -> None:
        from core.agent_capabilities import CapabilityInputError

        registry = self._registry()

        with self.assertRaises(CapabilityInputError):
            registry.execute("loom.matrix.dispatch", {})
        result = registry.execute("loom.matrix.dispatch", {"targets": {"deviceIds": ["phone-1"]}})
        skill = registry.execute("loom.skill.screen-reader", {"deviceId": "phone-1"})
        mcp = registry.execute("loom.mcp.local.search_logs", {"query": "timeout"})
        cli = registry.execute("loom.cli.phone.status", {})

        self.assertEqual(result["campaignId"], "cmp-1")
        self.assertEqual(skill["skill"], "screen-reader")
        self.assertEqual(mcp["tool"], "search_logs")
        self.assertEqual(cli["command"], "phone status")

    def test_discovery_is_reused_across_list_resolve_validate_and_read_execution(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        calls = {"skills": 0, "mcp": 0, "cli": 0}

        def skills():
            calls["skills"] += 1
            return []

        def mcp():
            calls["mcp"] += 1
            return [{
                "server": "local",
                "name": "ping",
                "inputSchema": {"type": "object", "additionalProperties": False},
                "permission": "read",
                "risk": "read",
            }]

        def cli():
            calls["cli"] += 1
            return {"domains": []}

        registry = CapabilityRegistry(
            skill_provider=skills,
            mcp_provider=mcp,
            mcp_executor=lambda _server, _tool, _payload: {"ok": True},
            cli_catalog_provider=cli,
        )

        registry.list_capabilities(available_only=True)
        registry.get("loom.mcp.local.ping")
        registry.validate_input("loom.mcp.local.ping", {})
        registry.execute("loom.mcp.local.ping", {})

        self.assertEqual(calls, {"skills": 1, "mcp": 1, "cli": 1})

    def test_validate_input_enforces_json_schema_value_constraints(self) -> None:
        from core.agent_capabilities import CapabilityInputError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.constrained": {
                    "executor": lambda payload: {"ok": True, "payload": payload},
                    "inputSchema": {
                        "type": "object",
                        "required": ["title", "platform", "mediaPaths"],
                        "properties": {
                            "title": {"type": "string", "minLength": 1},
                            "platform": {"type": "string", "enum": ["douyin"]},
                            "mediaPaths": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        invalid_payloads = [
            {"title": "", "platform": "douyin", "mediaPaths": ["video.mp4"]},
            {"title": "title", "platform": "other", "mediaPaths": ["video.mp4"]},
            {"title": "title", "platform": "douyin", "mediaPaths": []},
            {"title": "title", "platform": "douyin", "mediaPaths": [""]},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(CapabilityInputError):
                registry.validate_input("loom.test.constrained", payload)

        _, valid = registry.validate_input(
            "loom.test.constrained",
            {"title": "title", "platform": "douyin", "mediaPaths": ["video.mp4"]},
        )
        self.assertEqual(valid["title"], "title")

    def test_validate_input_enforces_any_of_and_rejects_unknown_properties(self) -> None:
        from core.agent_capabilities import CapabilityInputError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.schedule": {
                    "executor": lambda payload: {"ok": True, "payload": payload},
                    "inputSchema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "at": {"type": "string", "minLength": 1},
                            "every": {"type": "string", "minLength": 1},
                        },
                        "anyOf": [
                            {"required": ["at"]},
                            {"required": ["every"]},
                        ],
                        "additionalProperties": False,
                    },
                },
                "loom.test.matrix": {
                    "executor": lambda payload: {"ok": True, "payload": payload},
                    "inputSchema": {
                        "type": "object",
                        "required": ["targets"],
                        "properties": {
                            "targets": {
                                "type": "object",
                                "properties": {
                                    "deviceIds": {"type": "array", "minItems": 1},
                                    "allOnline": {"type": "boolean"},
                                },
                                "anyOf": [
                                    {"required": ["deviceIds"]},
                                    {"required": ["allOnline"]},
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        invalid_cases = [
            ("loom.test.schedule", {"name": "nightly"}),
            ("loom.test.schedule", {"name": "nightly", "at": "21:00", "timezone": "Asia/Shanghai"}),
            ("loom.test.matrix", {"targets": {}}),
            ("loom.test.matrix", {"targets": {"allOnline": True, "unknown": True}}),
        ]
        for capability, payload in invalid_cases:
            with self.subTest(capability=capability, payload=payload), self.assertRaises(CapabilityInputError):
                registry.validate_input(capability, payload)

        _, scheduled = registry.validate_input(
            "loom.test.schedule",
            {"name": "nightly", "every": "1h"},
        )
        _, matrix = registry.validate_input(
            "loom.test.matrix",
            {"targets": {"deviceIds": ["phone-1"]}},
        )
        self.assertEqual(scheduled["every"], "1h")
        self.assertEqual(matrix["targets"]["deviceIds"], ["phone-1"])

    def test_execute_redacts_secrets_from_results(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={
                "loom.logs.tail": {
                    "executor": lambda _payload: {"token": "secret-token", "line": "Bearer abc.def"},
                    "permission": "read",
                    "risk": "read",
                }
            }
        )

        result = registry.execute("loom.logs.tail", {})

        self.assertEqual(result["token"], "[REDACTED]")
        self.assertNotIn("abc.def", json.dumps(result))

    def test_execute_treats_invalid_output_as_indeterminate_nonrecoverable_failure(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        executions = []
        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.side-effect": {
                    "executor": lambda payload: executions.append(dict(payload)) or {"ok": True},
                    "permission": "control",
                    "risk": "control_safe",
                    "outputSchema": {
                        "type": "object",
                        "required": ["receiptId"],
                        "properties": {"receiptId": {"type": "string"}},
                        "additionalProperties": False,
                    },
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.test.side-effect", {})

        self.assertEqual(executions, [{}])
        self.assertEqual(caught.exception.code, "capability_invalid_output")
        self.assertFalse(caught.exception.recoverable)
        self.assertTrue(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)
        self.assertIn("output.receiptId is required", str(caught.exception))

    def test_execute_treats_unknown_control_exception_as_indeterminate_nonrecoverable_failure(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        executions = []

        def send_then_disconnect(payload):
            executions.append(dict(payload))
            raise ConnectionResetError("connection reset after request was sent")

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.side-effect": {
                    "executor": send_then_disconnect,
                    "permission": "control",
                    "risk": "outbound",
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.test.side-effect", {"target": "phone-1"})

        self.assertEqual(executions, [{"target": "phone-1"}])
        self.assertEqual(caught.exception.code, "capability_execution_unknown")
        self.assertFalse(caught.exception.recoverable)
        self.assertTrue(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)

    def test_execute_keeps_unknown_read_exception_recoverable(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.read": {
                    "executor": lambda _payload: (_ for _ in ()).throw(ConnectionError("temporary read failure")),
                    "permission": "read",
                    "risk": "read",
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.test.read", {})

        self.assertEqual(caught.exception.code, "capability_failed")
        self.assertTrue(caught.exception.recoverable)
        self.assertFalse(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)

    def test_execute_returns_promptly_when_timed_out_work_keeps_running(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        started = threading.Event()
        release = threading.Event()
        settled = threading.Event()
        received_tokens = []

        def hanging_side_effect(_payload, *, cancellation_token):
            received_tokens.append(cancellation_token)
            started.set()
            release.wait()
            settled.set()

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.hanging": {
                    "executor": hanging_side_effect,
                    "permission": "read",
                    "risk": "read",
                    "timeoutSec": 0.02,
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        guard_release = threading.Timer(0.5, release.set)
        guard_release.start()
        before = time.monotonic()
        try:
            with self.assertRaises(CapabilityExecutionError) as caught:
                registry.execute("loom.test.hanging", {})
            elapsed = time.monotonic() - before

            self.assertTrue(started.is_set())
            self.assertFalse(settled.is_set())
            self.assertLess(elapsed, 0.25)
            self.assertEqual(caught.exception.code, "capability_timeout_indeterminate")
            self.assertFalse(caught.exception.recoverable)
            self.assertTrue(caught.exception.outcome_indeterminate)
            self.assertTrue(caught.exception.execution_may_continue)
            self.assertEqual(len(received_tokens), 1)
            self.assertTrue(received_tokens[0].cancelled)
            self.assertIn("may still complete", str(caught.exception))
        finally:
            release.set()
            guard_release.cancel()
            guard_release.join(timeout=1)

        self.assertTrue(settled.wait(timeout=1))

    def test_execute_signals_cooperative_cancellation_but_keeps_timeout_indeterminate(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        cancellation_observed = threading.Event()

        def cooperative_side_effect(_payload, *, cancellation_token):
            cancellation_token.wait()
            cancellation_observed.set()
            return {"cancelled": cancellation_token.cancelled}

        registry = CapabilityRegistry(
            internal_operations={
                "loom.test.cooperative": {
                    "executor": cooperative_side_effect,
                    "permission": "control",
                    "risk": "control_safe",
                    "timeoutSec": 0.02,
                }
            },
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {"domains": []},
        )

        before = time.monotonic()
        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.test.cooperative", {})

        self.assertLess(time.monotonic() - before, 0.25)
        self.assertTrue(cancellation_observed.wait(timeout=1))
        self.assertEqual(caught.exception.code, "capability_timeout_indeterminate")
        self.assertTrue(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)
        self.assertIn("acknowledged cancellation", str(caught.exception))

    def test_execute_propagates_cancellation_token_through_mcp_adapter(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        cancellation_observed = threading.Event()

        def cooperative_mcp(_server, _tool, _payload, *, cancellation_token):
            cancellation_token.wait()
            cancellation_observed.set()
            return {"cancelled": cancellation_token.cancelled}

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "local",
                "name": "cooperative",
                "permission": "control",
                "risk": "control_safe",
                "timeoutSec": 0.02,
            }],
            mcp_executor=cooperative_mcp,
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.mcp.local.cooperative", {})

        self.assertTrue(cancellation_observed.wait(timeout=1))
        self.assertEqual(caught.exception.code, "capability_timeout_indeterminate")
        self.assertFalse(caught.exception.execution_may_continue)

    def test_execute_propagates_mcp_error_result_as_capability_failure(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "local",
                "name": "denied",
                "permission": "read",
                "risk": "read",
            }],
            mcp_executor=lambda _server, _tool, _payload: {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "ok": False,
                        "error": {
                            "code": "permission_denied",
                            "message": "Admin permission is required.",
                        },
                    }),
                }],
                "isError": True,
            },
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.mcp.local.denied", {})

        self.assertEqual(caught.exception.code, "permission_denied")
        self.assertEqual(str(caught.exception), "Admin permission is required.")

    def test_mcp_control_error_without_no_effect_proof_is_indeterminate(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "local",
                "name": "publish",
                "permission": "control",
                "risk": "outbound",
            }],
            mcp_executor=lambda _server, _tool, _payload: {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "ok": False,
                        "error": {
                            "code": "bridge_http_error",
                            "message": "Connection closed before a receipt was returned.",
                        },
                    }),
                }],
                "isError": True,
            },
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.mcp.local.publish", {"body": "hello"})

        self.assertEqual(caught.exception.code, "capability_execution_unknown")
        self.assertFalse(caught.exception.recoverable)
        self.assertTrue(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)

    def test_mcp_control_preflight_denial_remains_recoverable(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, CapabilityRegistry

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "local",
                "name": "publish",
                "permission": "control",
                "risk": "outbound",
            }],
            mcp_executor=lambda _server, _tool, _payload: {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "ok": False,
                        "error": {
                            "code": "permission_denied",
                            "message": "Control permission is required.",
                        },
                    }),
                }],
                "isError": True,
            },
            cli_catalog_provider=lambda: {"domains": []},
        )

        with self.assertRaises(CapabilityExecutionError) as caught:
            registry.execute("loom.mcp.local.publish", {"body": "hello"})

        self.assertEqual(caught.exception.code, "permission_denied")
        self.assertTrue(caught.exception.recoverable)
        self.assertFalse(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)

    def test_registry_forwards_declared_permission_to_mcp_executor(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        granted: list[str | None] = []

        def execute_mcp(_server, _tool, _payload, *, permission=None):
            granted.append(permission)
            return {"ok": True}

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [{
                "server": "local",
                "name": "control_phone",
                "permission": "control",
                "risk": "control_safe",
            }],
            mcp_executor=execute_mcp,
            cli_catalog_provider=lambda: {"domains": []},
        )

        self.assertTrue(registry.execute("loom.mcp.local.control_phone", {})["ok"])
        self.assertEqual(granted, ["control"])

    def test_registry_forwards_declared_permission_to_cli_executor(self) -> None:
        from core.agent_capabilities import CapabilityRegistry

        granted: list[str | None] = []

        def execute_cli(_command, _payload, *, permission=None):
            granted.append(permission)
            return {"ok": True}

        registry = CapabilityRegistry(
            internal_operations={},
            skill_provider=lambda: [],
            mcp_provider=lambda: [],
            cli_catalog_provider=lambda: {
                "domains": [{
                    "domain": "phone",
                    "commands": [{"name": "phone status", "permission": "control", "risk": "control_safe"}],
                }],
            },
            cli_executor=execute_cli,
        )

        self.assertTrue(registry.execute("loom.cli.phone.status", {})["ok"])
        self.assertEqual(granted, ["control"])

    def test_default_cli_executor_rejects_model_controlled_global_options(self) -> None:
        from core.agent_capabilities import CapabilityInputError, _default_cli_executor

        dispatch = mock.Mock(return_value=(0, {"data": {"ok": True}}))
        fake_loom_cli = types.SimpleNamespace(dispatch=dispatch)
        attacks = [
            ["--permission", "admin"],
            ["--permission=admin"],
            ["--bridge-url", "https://attacker.invalid"],
            ["--bridge-url=https://attacker.invalid"],
            ["--bridge-token", "attacker-token"],
            ["--bridge-token=attacker-token"],
            ["--json"],
            ["--dry-run"],
        ]

        with mock.patch.dict(sys.modules, {"loom_cli": fake_loom_cli}):
            for args in attacks:
                with self.subTest(args=args), self.assertRaises(CapabilityInputError):
                    _default_cli_executor("matrix dispatch", {"args": args})

        dispatch.assert_not_called()

    def test_default_cli_executor_keeps_command_options_and_appends_trusted_json_flag(self) -> None:
        from core.agent_capabilities import _default_cli_executor

        dispatch = mock.Mock(return_value=(0, {"data": {"ok": True}}))
        fake_loom_cli = types.SimpleNamespace(dispatch=dispatch)

        with mock.patch.dict(sys.modules, {"loom_cli": fake_loom_cli}):
            result = _default_cli_executor(
                "matrix dispatch",
                {"args": ["--target", "phone-1", "--prompt", "inspect"]},
            )

        self.assertEqual(result, {"ok": True})
        dispatch.assert_called_once_with(
            ["matrix", "dispatch", "--target", "phone-1", "--prompt", "inspect", "--json"],
            source="agent",
        )

    def test_default_cli_control_error_without_no_effect_proof_is_indeterminate(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, _default_cli_executor

        dispatch = mock.Mock(return_value=(
            4,
            {
                "ok": False,
                "error": {
                    "code": "bridge_http_error",
                    "message": "Connection closed before a receipt was returned.",
                },
            },
        ))
        fake_loom_cli = types.SimpleNamespace(dispatch=dispatch)

        with mock.patch.dict(sys.modules, {"loom_cli": fake_loom_cli}):
            with self.assertRaises(CapabilityExecutionError) as caught:
                _default_cli_executor(
                    "matrix dispatch",
                    {"args": ["--target", "phone-1", "--prompt", "inspect"]},
                    permission="control",
                )

        self.assertEqual(caught.exception.code, "capability_execution_unknown")
        self.assertFalse(caught.exception.recoverable)
        self.assertTrue(caught.exception.outcome_indeterminate)
        self.assertFalse(caught.exception.execution_may_continue)

    def test_default_cli_control_preflight_denial_remains_recoverable(self) -> None:
        from core.agent_capabilities import CapabilityExecutionError, _default_cli_executor

        dispatch = mock.Mock(return_value=(
            3,
            {
                "ok": False,
                "error": {
                    "code": "permission_denied",
                    "message": "Control permission is required.",
                },
            },
        ))
        fake_loom_cli = types.SimpleNamespace(dispatch=dispatch)

        with mock.patch.dict(sys.modules, {"loom_cli": fake_loom_cli}):
            with self.assertRaises(CapabilityExecutionError) as caught:
                _default_cli_executor(
                    "matrix dispatch",
                    {"args": ["--target", "phone-1", "--prompt", "inspect"]},
                    permission="control",
                )

        self.assertEqual(caught.exception.code, "permission_denied")
        self.assertTrue(caught.exception.recoverable)
        self.assertFalse(caught.exception.outcome_indeterminate)

    def test_default_cli_executor_maps_phone_quick_task_structured_payload_to_flags(self) -> None:
        from core.agent_capabilities import _default_cli_executor

        dispatch = mock.Mock(return_value=(0, {"data": {"ok": True}}))
        with mock.patch.dict(sys.modules, {"loom_cli": types.SimpleNamespace(dispatch=dispatch)}):
            result = _default_cli_executor(
                "phone quick-task",
                {"prompt": "Open settings", "deviceId": "phone-a", "mode": "safe"},
                permission="control",
            )

        self.assertTrue(result["ok"])
        argv = dispatch.call_args.args[0]
        self.assertEqual(argv[argv.index("--prompt") + 1], "Open settings")
        self.assertEqual(argv[argv.index("--device-id") + 1], "phone-a")
        self.assertEqual(argv[argv.index("--mode") + 1], "safe")
        self.assertEqual(argv[argv.index("--permission") + 1], "control")

    def test_default_mcp_executor_forwards_policy_permission(self) -> None:
        from core.agent_capabilities import _default_mcp_executor

        call_tool = mock.Mock(return_value={"content": [], "isError": False})
        with mock.patch.dict(sys.modules, {"loom_mcp": types.SimpleNamespace(call_tool=call_tool)}):
            result = _default_mcp_executor("loom", "loom_phone_quick_task", {"prompt": "Open settings"}, permission="control")

        self.assertFalse(result["isError"])
        call_tool.assert_called_once_with(
            "loom_phone_quick_task",
            {"prompt": "Open settings"},
            permission="control",
            trusted_internal=True,
        )


if __name__ == "__main__":
    unittest.main()
