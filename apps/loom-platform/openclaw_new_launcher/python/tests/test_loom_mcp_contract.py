from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER_DIR = os.path.dirname(PYTHON_DIR)
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


def _sample_schema_value(schema) -> object:
    value_type = schema.get("type") if isinstance(schema, dict) else "string"
    if value_type == "boolean":
        return True
    if value_type == "integer":
        return max(1, int(schema.get("minimum") or 1))
    if value_type == "array":
        return ["sample"]
    if value_type == "object":
        return {"sample": "value"}
    values = schema.get("enum") if isinstance(schema, dict) else None
    return values[0] if isinstance(values, list) and values else "sample"


class LoomMcpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._audit_dir = tempfile.TemporaryDirectory()
        self._audit_patch = patch.dict(os.environ, {"LOOM_AUDIT_DIR": self._audit_dir.name})
        self._audit_patch.start()

    def tearDown(self) -> None:
        self._audit_patch.stop()
        self._audit_dir.cleanup()

    def test_mcp_tools_and_cli_catalog_are_a_one_to_one_contract(self) -> None:
        import loom_cli
        import loom_mcp

        catalog_commands = {
            item["name"]
            for domain in loom_cli._command_catalog()["domains"]
            for item in domain["commands"]
        }
        mapped_commands: dict[str, str] = {}
        for tool in loom_mcp.tool_definitions():
            schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required_names = list(schema.get("required", []))
            alternatives = schema.get("oneOf")
            if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
                required_names.extend(alternatives[0].get("required", []))
            arguments = {
                name: _sample_schema_value(properties.get(name))
                for name in dict.fromkeys(required_names)
                if name != "dryRun"
            }
            argv = loom_mcp._tool_to_cli_args(tool["name"], arguments)
            matches = [
                command
                for command in catalog_commands
                if argv[: len(command.split())] == command.split()
            ]
            self.assertTrue(matches, f"MCP tool has no catalog command: {tool['name']} -> {argv}")
            mapped_commands[tool["name"]] = max(matches, key=lambda command: len(command.split()))

        self.assertEqual(len(mapped_commands), len(set(mapped_commands.values())))
        self.assertEqual(set(mapped_commands.values()), catalog_commands)

    def test_targeted_and_scheduled_tools_publish_runtime_requirements(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}

        matrix_schema = tools["loom_matrix_dispatch"]["inputSchema"]
        self.assertEqual(
            matrix_schema["oneOf"],
            [
                {"required": ["deviceId"]},
                {"required": ["group"]},
                {"required": ["targets"]},
            ],
        )
        self.assertEqual(
            matrix_schema["properties"]["targets"]["oneOf"],
            [
                {"required": ["deviceIds"]},
                {"required": ["groups"]},
                {"required": ["allOnline"]},
            ],
        )
        self.assertIn("deviceId", tools["loom_template_run"]["inputSchema"]["required"])
        self.assertEqual(
            tools["loom_schedule_add"]["inputSchema"]["anyOf"],
            [{"required": ["at"]}, {"required": ["every"]}],
        )

    def test_diagnostics_repair_maps_to_the_cli_check_argument(self) -> None:
        import loom_mcp

        argv = loom_mcp._tool_to_cli_args("loom_diagnostics_repair", {"action": "phone-runtime"})

        self.assertEqual(argv, ["diagnostics", "repair", "--check", "phone-runtime"])

    def test_phase_one_tools_are_safe_and_explicit(self) -> None:
        import loom_mcp

        names = {tool["name"] for tool in loom_mcp.tool_definitions()}

        phase_one = {
            "loom_status",
            "loom_cli_commands",
            "loom_models",
            "loom_agent_list",
            "loom_agent_start",
            "loom_agent_install",
            "loom_phone_screenshot",
            "loom_phone_read",
            "loom_phone_quick_task",
            "loom_phone_template_task",
            "loom_phone_adb_doctor",
            "loom_schedule_list",
            "loom_schedule_add",
            "loom_schedule_run",
            "loom_schedule_cancel",
            "loom_logs_tail",
            "loom_matrix_status",
            "loom_matrix_dispatch",
            "loom_matrix_watch",
            "loom_matrix_cancel",
            "loom_matrix_retry",
            "loom_lead_list",
            "loom_lead_record",
            "loom_template_run",
            "loom_experience_report",
        }
        expanded_domains = {
            "loom_account_current",
            "loom_account_send_code",
            "loom_account_login_code",
            "loom_account_login_password",
            "loom_account_sync",
            "loom_account_subscription",
            "loom_account_select_models",
            "loom_account_logout",
            "loom_wire_current",
            "loom_wire_sync",
            "loom_wire_custom",
            "loom_wire_verify",
            "loom_wire_rollback",
            "loom_media_config",
            "loom_media_save_image_config",
            "loom_media_save_video_config",
            "loom_media_test_image",
            "loom_media_test_video",
            "loom_media_generate_image",
            "loom_media_generate_video",
            "loom_agent_detect",
            "loom_agent_uninstall",
            "loom_agent_rollback",
            "loom_agent_model_status",
            "loom_agent_model_apply",
            "loom_agent_model_rollback",
            "loom_job_list",
            "loom_job_get",
            "loom_settings_theme",
            "loom_settings_theme_list",
            "loom_settings_update_check",
            "loom_settings_update_install",
            "loom_diagnostics_run",
            "loom_diagnostics_repair",
            "loom_diagnostics_export",
            "loom_license_current",
            "loom_license_activate",
            "loom_license_authorized",
        }
        self.assertTrue(phase_one.issubset(names))
        self.assertTrue(expanded_domains.issubset(names))

    def test_tool_definitions_expose_machine_readable_permission_and_risk(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}

        self.assertEqual(tools["loom_status"]["permission"], "read")
        self.assertEqual(tools["loom_status"]["risk"], "read")
        self.assertEqual(tools["loom_matrix_dispatch"]["permission"], "control")
        self.assertEqual(tools["loom_matrix_dispatch"]["risk"], "control_safe")
        self.assertEqual(tools["loom_phone_template_task"]["permission"], "control")
        self.assertEqual(tools["loom_template_run"]["permission"], "control")
        self.assertEqual(tools["loom_template_run"]["risk"], "control_safe")
        self.assertEqual(tools["loom_agent_uninstall"]["permission"], "admin")
        self.assertEqual(tools["loom_agent_uninstall"]["risk"], "critical")
        self.assertEqual(tools["loom_schedule_add"]["permission"], "automation")
        self.assertEqual(tools["loom_schedule_add"]["risk"], "critical")
        self.assertEqual(tools["loom_media_test_image"]["permission"], "control")
        self.assertEqual(tools["loom_media_test_image"]["risk"], "control_safe")
        self.assertEqual(tools["loom_media_test_video"]["permission"], "control")
        self.assertEqual(tools["loom_media_test_video"]["risk"], "control_safe")

    def test_external_writes_publish_explicit_risk_instead_of_generic_control(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}

        self.assertEqual(tools["loom_account_send_code"]["risk"], "outbound")
        self.assertEqual(tools["loom_account_login_code"]["risk"], "critical")
        self.assertEqual(tools["loom_account_login_password"]["risk"], "critical")
        self.assertEqual(tools["loom_feishu_create_table"]["risk"], "critical")
        self.assertEqual(tools["loom_feishu_test_write"]["risk"], "outbound")
        self.assertEqual(tools["loom_feishu_retry_sync"]["risk"], "outbound")
        self.assertEqual(tools["loom_feishu_reconcile"]["risk"], "control_safe")
        self.assertEqual(tools["loom_acquisition_agent_result"]["risk"], "outbound")

    def test_state_changing_phone_event_tools_require_control_permission(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}

        self.assertEqual(tools["loom_phone_events_start"]["permission"], "control")
        self.assertEqual(tools["loom_phone_events_status"]["permission"], "read")
        self.assertEqual(tools["loom_phone_events_stop"]["permission"], "control")

    def test_account_send_code_is_pinned_to_login_purpose(self) -> None:
        import loom_mcp

        tool = next(item for item in loom_mcp.tool_definitions() if item["name"] == "loom_account_send_code")
        purpose = tool["inputSchema"]["properties"]["purpose"]

        self.assertEqual(purpose["enum"], ["login"])
        self.assertEqual(
            loom_mcp._tool_to_cli_args("loom_account_send_code", {"email": "user@example.com"}),
            ["account", "send-code", "--email", "user@example.com", "--purpose", "login"],
        )

    def test_restricted_cli_arguments_are_discoverable_in_tool_schemas(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}
        schedule_command = tools["loom_schedule_add"]["inputSchema"]["properties"]["command"]
        repair_action = tools["loom_diagnostics_repair"]["inputSchema"]["properties"]["action"]

        self.assertIn("status", schedule_command["examples"])
        self.assertIn("phone screenshot", schedule_command["description"])
        self.assertEqual(repair_action["enum"], ["prerequisites"])

    def test_phone_and_matrix_tools_expose_target_scope_contracts(self) -> None:
        import loom_mcp

        tools = {tool["name"]: tool for tool in loom_mcp.tool_definitions()}
        expected = {
            "loom_phone_status": "none",
            "loom_phone_screenshot": "single-device-read",
            "loom_phone_read": "single-device-read",
            "loom_phone_quick_task": "single-device-write",
            "loom_phone_template_task": "single-device-write",
            "loom_template_run": "single-device-write",
            "loom_matrix_dispatch": "matrix-write",
            "loom_matrix_cancel": "campaign-write",
            "loom_matrix_retry": "campaign-write",
        }

        self.assertEqual(
            {name: tools[name].get("targetScope") for name in expected},
            expected,
        )

    def test_mcp_server_version_matches_launcher_package_version(self) -> None:
        import loom_mcp

        with open(os.path.join(LAUNCHER_DIR, "package.json"), "r", encoding="utf-8") as handle:
            package_version = json.load(handle)["version"]

        response = loom_mcp._handle_rpc_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))

        self.assertEqual(response["result"]["serverInfo"]["version"], package_version)

    def test_mcp_accepts_utf8_bom_on_first_stdio_line(self) -> None:
        import loom_mcp

        response = loom_mcp._handle_rpc_line("\ufeff" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

        self.assertEqual(response["id"], 1)
        self.assertEqual(len(response["result"]["tools"]), len(loom_mcp.tool_definitions()))

    def test_mcp_accepts_windows_mojibake_bom_on_first_stdio_line(self) -> None:
        import loom_mcp

        raw = "\u9518\u7e36" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[1:]
        response = loom_mcp._handle_rpc_line(raw)

        self.assertEqual(response["id"], 1)
        self.assertEqual(len(response["result"]["tools"]), len(loom_mcp.tool_definitions()))

    def test_mcp_tool_calls_cli_dispatcher_for_phone_read_fast_path(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_phone_read",
                {"prompt": "读取屏幕", "dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        content = json.loads(result["content"][0]["text"])
        self.assertFalse(result.get("isError", False))
        self.assertEqual(content["data"]["endpoint"], "/api/phone/read")
        self.assertEqual(content["data"]["body"]["profile"], "fast")

    def test_mcp_phone_adb_doctor_maps_to_dedicated_phone_adb_recovery(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_phone_adb_doctor",
                {"dryRun": True, "serial": "emulator-5554"},
                permission="admin",
                base_path=temp_dir,
            )

        content = json.loads(result["content"][0]["text"])
        self.assertFalse(result.get("isError", False))
        self.assertEqual(content["data"]["endpoint"], "/api/phone/adb-doctor")
        self.assertEqual(content["data"]["body"]["serial"], "emulator-5554")
        self.assertTrue(content["data"]["body"]["confirmed"])

    def test_mcp_can_read_cli_command_catalog(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_cli_commands",
                {"dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        content = json.loads(result["content"][0]["text"])
        self.assertFalse(result.get("isError", False))
        self.assertEqual(content["data"]["schema"], "loom.cli.catalog.v1")
        self.assertGreaterEqual(content["data"]["commandCount"], 50)

    def test_mcp_phone_template_task_exposes_screen_summary_read_template(self) -> None:
        import loom_mcp

        tool = next(item for item in loom_mcp.tool_definitions() if item["name"] == "loom_phone_template_task")
        enum_values = tool["inputSchema"]["properties"]["template"]["enum"]
        self.assertIn("screen-summary", enum_values)
        self.assertEqual(tool["inputSchema"]["properties"]["deviceId"]["type"], "string")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_phone_template_task",
                {"template": "screen-summary", "deviceId": "phone-2", "dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        content = json.loads(result["content"][0]["text"])
        self.assertFalse(result.get("isError", False))
        self.assertEqual(content["data"]["endpoint"], "/api/phone/task")
        self.assertEqual(content["data"]["body"]["template"], "screen-summary")
        self.assertEqual(content["data"]["body"]["executionLayer"], "template")
        self.assertEqual(content["data"]["body"]["deviceId"], "phone-2")

    def test_mcp_denies_dangerous_tool_by_default(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_agent_install",
                {"component": "codex-desktop", "dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        content = json.loads(result["content"][0]["text"])
        self.assertTrue(result["isError"])
        self.assertEqual(content["error"]["code"], "permission_denied")

    def test_trusted_agent_call_keeps_policy_granted_control_permission(self) -> None:
        import loom_mcp

        dispatched = (0, {"ok": True, "data": {"status": "queued"}})
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(loom_mcp, "DEFAULT_PERMISSION", "read"), patch.object(
                loom_mcp, "dispatch", return_value=dispatched
            ) as dispatch:
                result = loom_mcp.call_tool(
                    "loom_phone_quick_task",
                    {"prompt": "Open settings", "deviceId": "phone-1"},
                    permission="control",
                    base_path=temp_dir,
                    trusted_internal=True,
                )

        self.assertFalse(result["isError"])
        argv = dispatch.call_args.args[0]
        self.assertEqual(argv[argv.index("--permission") + 1], "control")

    def test_mcp_writes_redacted_audit_log(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                result = loom_mcp.call_tool(
                    "loom_status",
                    {"dryRun": True, "apiKey": "secret-value"},
                    permission="read",
                    base_path=temp_dir,
                )
            self.assertFalse(result.get("isError", False))
            audit_path = os.path.join(temp_dir, "mcp-audit.jsonl")
            with open(audit_path, "r", encoding="utf-8") as handle:
                audit = json.loads(handle.readline())
            source_audit_path = os.path.join(temp_dir, "data", ".openclaw", "launcher", "mcp-audit.jsonl")

        self.assertEqual(audit["tool"], "loom_status")
        self.assertNotIn("secret-value", json.dumps(audit, ensure_ascii=False))
        self.assertIn("durationMs", audit)
        self.assertFalse(os.path.exists(source_audit_path))

    def test_mcp_matrix_tools_call_cli_dispatcher(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            status = loom_mcp.call_tool(
                "loom_matrix_status",
                {"dryRun": True},
                permission="read",
                base_path=temp_dir,
            )
            dispatch = loom_mcp.call_tool(
                "loom_matrix_dispatch",
                {"deviceId": "phone-a", "prompt": "打开系统设置", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )
            retry = loom_mcp.call_tool(
                "loom_matrix_retry",
                {"campaignId": "campaign_123", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )
            lead_list = loom_mcp.call_tool(
                "loom_lead_list",
                {"limit": 5, "dryRun": True},
                permission="read",
                base_path=temp_dir,
            )
            lead_record = loom_mcp.call_tool(
                "loom_lead_record",
                {"summary": "用户询问套餐", "deviceId": "phone-a", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )

        status_payload = json.loads(status["content"][0]["text"])
        dispatch_payload = json.loads(dispatch["content"][0]["text"])
        retry_payload = json.loads(retry["content"][0]["text"])
        lead_list_payload = json.loads(lead_list["content"][0]["text"])
        lead_record_payload = json.loads(lead_record["content"][0]["text"])
        self.assertFalse(status.get("isError", False))
        self.assertFalse(dispatch.get("isError", False))
        self.assertEqual(status_payload["data"]["endpoint"], "/api/matrix/status")
        self.assertEqual(dispatch_payload["data"]["endpoint"], "/api/matrix/dispatch")
        self.assertEqual(dispatch_payload["data"]["body"]["executionLayer"], "template")
        self.assertEqual(retry_payload["data"]["endpoint"], "/api/matrix/retry")
        self.assertEqual(lead_list_payload["data"]["endpoint"], "/api/matrix/leads?limit=5")
        self.assertEqual(lead_record_payload["data"]["endpoint"], "/api/matrix/leads")

    def test_mcp_matrix_dispatch_safety_gate_blocks_bulk_outreach(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_matrix_dispatch",
                {
                    "prompt": "批量评论并自动回复",
                    "targets": {"allOnline": True},
                    "dryRun": True,
                },
                permission="control",
                base_path=temp_dir,
            )

        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(result["isError"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_mcp_phone_quick_task_safety_gate_blocks_bulk_outreach(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_phone_quick_task",
                {"prompt": "批量私信所有客户", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )

        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(result["isError"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_mcp_phone_quick_task_blocks_garbled_prompt(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_phone_quick_task",
                {"prompt": "????????", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )

        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(result["isError"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_mcp_phone_quick_task_passes_prompt_to_cli(self) -> None:
        import loom_mcp

        argv = loom_mcp._tool_to_cli_args("loom_phone_quick_task", {"prompt": "读取当前页面"})

        self.assertIn("--prompt", argv)
        self.assertEqual(argv[argv.index("--prompt") + 1], "读取当前页面")

    def test_mcp_phone_and_matrix_tools_forward_bound_targets_to_cli(self) -> None:
        import loom_mcp

        quick_task = loom_mcp._tool_to_cli_args(
            "loom_phone_quick_task",
            {"prompt": "open settings", "deviceId": "P01"},
        )
        dispatch = loom_mcp._tool_to_cli_args(
            "loom_matrix_dispatch",
            {"prompt": "read screens", "targets": {"deviceIds": ["P01", "P02"]}},
        )

        self.assertEqual(quick_task[quick_task.index("--device-id") + 1], "P01")
        self.assertEqual(dispatch[dispatch.index("--device") + 1], "P01,P02")

    def test_mcp_matrix_dispatch_rejects_ambiguous_or_empty_targets(self) -> None:
        import loom_mcp

        invalid_requests = [
            {
                "prompt": "read screens",
                "deviceId": "phone-a",
                "targets": {"allOnline": True},
            },
            {
                "prompt": "read screens",
                "targets": {"allOnline": True, "deviceIds": ["phone-a"]},
            },
            {
                "prompt": "read screens",
                "targets": {"deviceIds": ["phone-a"], "groups": ["sales"]},
            },
            {
                "prompt": "read screens",
                "targets": {"allOnline": False},
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            for arguments in invalid_requests:
                result = loom_mcp.call_tool(
                    "loom_matrix_dispatch",
                    {**arguments, "dryRun": True},
                    permission="control",
                    base_path=temp_dir,
                    trusted_internal=True,
                )
                payload = json.loads(result["content"][0]["text"])
                self.assertTrue(result["isError"], arguments)
                self.assertEqual(payload["error"]["code"], "invalid_target", arguments)

    def test_mcp_expanded_capabilities_call_cli_dispatcher(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            image = loom_mcp.call_tool(
                "loom_media_generate_image",
                {"prompt": "product photo", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )
            wire = loom_mcp.call_tool(
                "loom_wire_custom",
                {
                    "baseUrl": "https://api.example.com/v1",
                    "apiKey": "secret-value",
                    "textModel": "qwen",
                    "dryRun": True,
                },
                permission="control",
                base_path=temp_dir,
            )
            agent = loom_mcp.call_tool(
                "loom_agent_model_apply",
                {"component": "codex-desktop", "model": "qwen", "dryRun": True},
                permission="control",
                base_path=temp_dir,
            )
            subscription = loom_mcp.call_tool(
                "loom_account_subscription",
                {"dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        image_payload = json.loads(image["content"][0]["text"])
        wire_payload = json.loads(wire["content"][0]["text"])
        agent_payload = json.loads(agent["content"][0]["text"])
        subscription_payload = json.loads(subscription["content"][0]["text"])
        self.assertFalse(image.get("isError", False))
        self.assertFalse(wire.get("isError", False))
        self.assertFalse(agent.get("isError", False))
        self.assertFalse(subscription.get("isError", False))
        self.assertEqual(image_payload["data"]["endpoint"], "/api/image/generate/submit")
        self.assertEqual(wire_payload["data"]["endpoint"], "/api/wire/custom")
        self.assertNotIn("secret-value", json.dumps(wire_payload, ensure_ascii=False))
        self.assertEqual(agent_payload["data"]["endpoint"], "/api/components/model-config/apply")
        self.assertEqual(subscription_payload["data"]["endpoint"], "/api/account/subscription")

    def test_mcp_admin_update_is_denied_by_default(self) -> None:
        import loom_mcp

        with tempfile.TemporaryDirectory() as temp_dir:
            result = loom_mcp.call_tool(
                "loom_settings_update_install",
                {"dryRun": True},
                permission="read",
                base_path=temp_dir,
            )

        payload = json.loads(result["content"][0]["text"])
        self.assertTrue(result["isError"])
        self.assertEqual(payload["error"]["code"], "permission_denied")

    def test_mcp_json_config_is_bundled_for_codex_and_claude(self) -> None:
        config_path = os.path.join(LAUNCHER_DIR, ".mcp.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)

        server = config["mcpServers"]["loom"]
        self.assertIn("loom_mcp.py", " ".join(server["args"]))
        self.assertEqual(server["env"]["LOOM_MCP_PERMISSION"], "read")
        self.assertEqual(server["env"]["PYTHONUTF8"], "1")
        self.assertEqual(server["env"]["PYTHONIOENCODING"], "utf-8")


if __name__ == "__main__":
    unittest.main()
