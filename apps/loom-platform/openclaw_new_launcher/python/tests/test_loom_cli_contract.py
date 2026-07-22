from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER_DIR = os.path.dirname(PYTHON_DIR)
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class LoomCliContractTests(unittest.TestCase):
    def test_nested_command_help_returns_matching_command_contract(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["matrix", "dispatch", "--help", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["command"], "matrix dispatch")
        self.assertEqual(payload["data"]["permission"], "control")
        self.assertIn("--target", payload["data"]["usage"])

    def test_status_command_returns_structured_json_payload(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            code, payload = dispatch(["status", "--json"], base_path=temp_dir)

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "status")
        self.assertIn("data", payload)

    def test_commands_catalog_is_machine_readable(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["commands", "--json"])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        catalog = payload["data"]
        self.assertEqual(catalog["schema"], "loom.cli.catalog.v1")
        self.assertGreaterEqual(catalog["commandCount"], 50)
        domains = {item["domain"] for item in catalog["domains"]}
        self.assertIn("account", domains)
        self.assertIn("media", domains)
        self.assertIn("matrix", domains)
        self.assertIn("doctor", domains)
        command_names = [command["name"] for domain in catalog["domains"] for command in domain["commands"]]
        self.assertEqual(len(command_names), len(set(command_names)))
        self.assertEqual(catalog["commandCount"], len(command_names))
        self.assertIn("--dry-run", json.dumps(catalog, ensure_ascii=False))

    def test_phone_and_matrix_commands_expose_target_scope_contracts(self) -> None:
        from loom_cli import _command_catalog

        catalog = _command_catalog()
        commands = {
            command["name"]: command
            for domain in catalog["domains"]
            for command in domain["commands"]
        }
        expected = {
            "phone screenshot": "single-device-read",
            "phone read": "single-device-read",
            "phone quick-task": "single-device-write",
            "phone template-task": "single-device-write",
            "template run": "single-device-write",
            "acquisition agent-run": "single-device-write",
            "matrix dispatch": "matrix-write",
            "matrix cancel": "campaign-write",
            "matrix retry": "campaign-write",
        }

        self.assertEqual(
            {name: commands[name].get("targetScope") for name in expected},
            expected,
        )
        self.assertEqual(commands["phone status"].get("targetScope", "none"), "none")

    def test_commands_catalog_exposes_runtime_paths_for_packaged_layouts(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "LOOMFiles", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "_up_", "python"), exist_ok=True)
            for rel, text in (
                (os.path.join("LOOMFiles", "package.json"), '{"scripts":{"phone:publish":"node scripts/openclaw-publish-phone.mjs"}}'),
                (os.path.join("LOOMFiles", "scripts", "openclaw-publish-phone.mjs"), "// publish"),
            ):
                with open(os.path.join(temp_dir, rel), "w", encoding="utf-8") as handle:
                    handle.write(text)

            code, payload = dispatch(["commands", "--json"], base_path=temp_dir)

        self.assertEqual(code, 0)
        runtime = payload["data"]["runtime"]
        self.assertEqual(runtime["schema"], "loom.runtime_paths.v1")
        self.assertTrue(runtime["npmRoot"].endswith("LOOMFiles"))
        self.assertTrue(runtime["scriptsRoot"].endswith(os.path.join("LOOMFiles", "scripts")))
        self.assertTrue(runtime["helpers"]["phone:publish"]["exists"])

    def test_doctor_reports_paths_python_and_script_health_without_guessing(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "LOOMFiles", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "_up_", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, "LOOMFiles", "_up_", "python-runtime"), exist_ok=True)
            adb_dir = os.path.join(temp_dir, "_up_", "redist", "platform-tools")
            os.makedirs(adb_dir, exist_ok=True)
            adb_path = os.path.join(adb_dir, "adb.exe")
            with open(adb_path, "wb") as handle:
                handle.write(b"adb")
            with open(os.path.join(temp_dir, "LOOMFiles", "package.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "scripts": {
                        "phone:publish": "node scripts/openclaw-publish-phone.mjs",
                        "phone:video": "node scripts/openclaw-phone-video.mjs",
                    }
                }, handle)
            with open(os.path.join(temp_dir, "LOOMFiles", "scripts", "openclaw-publish-phone.mjs"), "w", encoding="utf-8") as handle:
                handle.write("// publish")
            with open(os.path.join(temp_dir, "_up_", "scripts", "openclaw-phone-video.mjs"), "w", encoding="utf-8") as handle:
                handle.write("// video fallback")

            code, payload = dispatch(["doctor", "--json"], base_path=temp_dir)

        self.assertEqual(code, 0)
        data = payload["data"]
        self.assertEqual(data["schema"], "loom.doctor.v1")
        self.assertTrue(data["paths"]["npmRoot"].endswith("LOOMFiles"))
        self.assertTrue(data["scripts"]["phone:publish"]["exists"])
        self.assertFalse(data["scripts"]["phone:video"]["exists"])
        self.assertTrue(data["scripts"]["phone:video"]["fallbackExists"])
        self.assertIn(os.path.join("_up_", "scripts", "openclaw-phone-video.mjs"), data["scripts"]["phone:video"]["fallbackPath"])
        self.assertEqual(data["issues"][0]["helper"], "phone:video")
        self.assertIn("executable", data["python"])
        self.assertFalse(data["python"]["bundledRuntimeExists"])
        self.assertIn("bridgeConfigured", data["phone"])
        self.assertEqual(data["paths"]["adbPath"], adb_path)
        self.assertEqual(data["phone"]["adbPath"], adb_path)
        self.assertTrue(data["phone"]["adbBundled"])

    def test_doctor_redacts_secret_like_bridge_url_parts(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch([
            "doctor",
            "--json",
            "--bridge-url",
            "http://user:secret-password@127.0.0.1:18888?token=secret-token&api_key=secret-key&plain=ok",
        ])

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(code, 0)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-password", serialized)
        self.assertIn("plain=ok", payload["data"]["phone"]["bridgeUrl"])

    def test_python_runtime_aliases_are_compatible_with_python_38(self) -> None:
        runtime_files = [
            os.path.join(PYTHON_DIR, "loom_cli.py"),
            os.path.join(PYTHON_DIR, "loom_mcp.py"),
            os.path.join(PYTHON_DIR, "core", "phone_matrix.py"),
            os.path.join(PYTHON_DIR, "core", "reliability.py"),
        ]

        for path in runtime_files:
            with self.subTest(path=path):
                with open(path, "r", encoding="utf-8") as handle:
                    source = handle.read()
                ast.parse(source, filename=path, feature_version=(3, 8))
                self.assertNotRegex(source, r"^\s*\w+\s*=\s*(dict|list|tuple|set)\[", path)

    def test_commands_catalog_teaches_codex_command_brain_workflow(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["commands", "--json"])

        self.assertEqual(code, 0)
        brain = payload["data"]["codexCommandBrain"]
        self.assertEqual(brain["schema"], "loom.codex_command_brain.v1")
        self.assertEqual(brain["roles"]["codex"], "Command Brain")
        self.assertEqual(brain["roles"]["singlePhone"], "Phone Worker")
        self.assertIn("matrix status", brain["workflows"]["matrixDispatch"])
        self.assertIn("matrix watch", brain["workflows"]["matrixDispatch"])
        self.assertIn("logs ledger", brain["workflows"]["matrixDispatch"])
        self.assertIn("phone adb-doctor", brain["recovery"]["adb"])
        self.assertIn("experience report", brain["experienceLoop"])

    def test_unknown_command_returns_structured_error(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["does-not-exist", "--json"])

        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unknown_command")
        self.assertIn("message", payload["error"])

    def test_schedule_run_and_cancel_dry_runs_do_not_require_saved_state(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            for action in ("run", "cancel"):
                with self.subTest(action=action):
                    code, payload = dispatch(
                        [
                            "schedule",
                            action,
                            "--id",
                            "task-preview",
                            "--permission",
                            "automation",
                            "--dry-run",
                            "--json",
                        ],
                        base_path=temp_dir,
                    )

                    self.assertEqual(code, 0)
                    self.assertTrue(payload["data"]["dryRun"])
                    self.assertEqual(payload["data"]["task"]["id"], "task-preview")
                    self.assertEqual(payload["data"]["action"], action)

    def test_schedule_run_propagates_child_failure_exit_code(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            add_code, add_payload = dispatch(
                [
                    "schedule",
                    "add",
                    "--command",
                    "logs unsupported-action",
                    "--every",
                    "hourly",
                    "--permission",
                    "automation",
                    "--json",
                ],
                base_path=temp_dir,
            )
            task_id = add_payload["data"]["task"]["id"]

            code, payload = dispatch(
                ["schedule", "run", "--id", task_id, "--permission", "automation", "--json"],
                base_path=temp_dir,
            )

            self.assertEqual(add_code, 0)
            self.assertEqual(code, 2)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["command"], "schedule run")
            self.assertEqual(payload["error"]["code"], "unknown_command")

    def test_diagnostics_repair_targets_prerequisite_scope(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "diagnostics",
                "repair",
                "--check",
                "prerequisites",
                "--permission",
                "admin",
                "--dry-run",
                "--json",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            payload["data"]["body"],
            {"scope": "prerequisites", "confirmed": True},
        )

    def test_diagnostics_repair_rejects_unsupported_target(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "diagnostics",
                "repair",
                "--check",
                "node",
                "--permission",
                "admin",
                "--dry-run",
                "--json",
            ]
        )

        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unsupported_repair_target")

    def test_admin_agent_install_is_denied_without_permission(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["agents", "install", "--component", "codex-desktop", "--json", "--dry-run"])

        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "permission_denied")

    def test_phone_read_dry_run_uses_fast_direct_read_path(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "read", "--prompt", "读取当前屏幕", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/read")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")
        self.assertNotIn("deep", json.dumps(payload, ensure_ascii=False).lower())

    def test_phone_read_screen_alias_uses_read_path(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "read-screen", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/read")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")

    def test_phone_adb_doctor_uses_dedicated_phone_adb_recovery(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch([
            "phone",
            "adb-doctor",
            "--serial",
            "emulator-5554",
            "--json",
            "--dry-run",
            "--permission",
            "admin",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["method"], "POST")
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/adb-doctor")
        self.assertEqual(payload["data"]["body"]["serial"], "emulator-5554")
        self.assertTrue(payload["data"]["body"]["confirmed"])

    def test_phone_adb_doctor_requires_admin_permission(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["phone", "adb-doctor", "--json", "--dry-run"])

        self.assertEqual(code, 3)
        self.assertEqual(payload["error"]["code"], "permission_denied")

    def test_phone_event_stream_wrappers_are_read_permission_dry_runs(self) -> None:
        from loom_cli import dispatch

        cases = [
            (
                ["phone", "events-start", "--device-id", "phone-1", "--max-sec", "3600", "--max-events", "0", "--json", "--dry-run"],
                "POST",
                "/api/phone/events/start",
            ),
            (
                ["phone", "events-status", "--device-id", "phone-1", "--json", "--dry-run"],
                "GET",
                "/api/phone/events/status?deviceId=phone-1",
            ),
            (
                ["phone", "events-stop", "--device-id", "phone-1", "--json", "--dry-run"],
                "POST",
                "/api/phone/events/stop",
            ),
        ]

        for argv, method, endpoint in cases:
            with self.subTest(argv=argv):
                code, payload = dispatch(argv)

                self.assertEqual(code, 0)
                self.assertEqual(payload["data"]["method"], method)
                self.assertEqual(payload["data"]["endpoint"], endpoint)

    def test_phone_quick_task_maps_simple_back_to_fast_action_path(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "quick-task",
                "--prompt",
                "返回上一页",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/task")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")
        self.assertEqual(payload["data"]["body"]["action"], "back")

    def test_phone_quick_task_preserves_explicit_device_target(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "quick-task",
                "--device",
                "phone-2",
                "--prompt",
                "读取当前屏幕",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["body"]["deviceId"], "phone-2")

    def test_phone_status_preserves_explicit_device_target(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            ["phone", "status", "--device-id", "phone-2", "--json", "--dry-run"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["body"]["deviceId"], "phone-2")

    def test_phone_read_screenshot_and_template_preserve_explicit_device_target(self) -> None:
        from loom_cli import dispatch

        commands = [
            ["phone", "read", "--device-id", "phone-2", "--json", "--dry-run"],
            ["phone", "screenshot", "--device-id", "phone-2", "--json", "--dry-run"],
            ["phone", "template-task", "back", "--device-id", "phone-2", "--permission", "control", "--json", "--dry-run"],
        ]

        payloads = [dispatch(command)[1] for command in commands]

        self.assertEqual(payloads[0]["data"]["body"]["deviceId"], "phone-2")
        self.assertEqual(payloads[1]["data"]["body"]["deviceId"], "phone-2")
        self.assertEqual(payloads[2]["data"]["body"]["deviceId"], "phone-2")

    def test_phone_run_task_alias_submits_phone_task(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "run-task",
                "--prompt",
                "read current page",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/task")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")

    def test_phone_run_task_blocks_bulk_outreach_without_confirmation(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "run-task",
                "--prompt",
                "批量私信所有客户",
                "--device",
                "phone-a",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_phone_quick_task_blocks_garbled_control_prompt(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "quick-task",
                "--prompt",
                "????????",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_phone_template_task_passes_template_layer_to_bridge(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "template-task",
                "--template",
                "screen-summary",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/phone/task")
        self.assertEqual(payload["data"]["body"]["template"], "screen-summary")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")
        self.assertEqual(payload["data"]["body"]["executionLayer"], "template")
        self.assertNotIn("action", payload["data"]["body"])

    def test_phone_mutating_template_task_still_requires_control(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "phone",
                "template-task",
                "--template",
                "back",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 3)
        self.assertEqual(payload["error"]["code"], "permission_denied")

    def test_cli_stdout_is_single_json_document(self) -> None:
        completed = subprocess.run(
            [sys.executable, os.path.join("python", "loom_cli.py"), "status", "--json"],
            cwd=LAUNCHER_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )

        self.assertEqual(completed.stderr.strip(), "")
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(payload["ok"])

    def test_cli_stdout_json_with_chinese_is_utf8(self) -> None:
        env = os.environ.copy()
        env.pop("PYTHONUTF8", None)
        env.pop("PYTHONIOENCODING", None)
        completed = subprocess.run(
            [
                sys.executable,
                os.path.join("python", "loom_cli.py"),
                "phone",
                "read-screen",
                "--json",
                "--dry-run",
            ],
            cwd=LAUNCHER_DIR,
            capture_output=True,
            env=env,
            timeout=10,
        )

        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(completed.returncode, 0)
        self.assertIn("读取当前手机屏幕", payload["data"]["body"]["prompt"])

    def test_cli_writes_audit_to_user_data_not_source_tree(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                code, payload = dispatch(["status", "--json", "--bridge-token", "secret-token"])
                audit_path = os.path.join(temp_dir, "loom-cli-audit.jsonl")
                with open(audit_path, "r", encoding="utf-8") as handle:
                    audit = json.loads(handle.readline())

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(audit["tool"], "cli:status")
        self.assertNotIn("secret-token", json.dumps(audit, ensure_ascii=False))

    def test_logs_tail_reads_user_audit_log(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOOM_AUDIT_DIR": temp_dir}):
                dispatch(["status", "--json"])
                code, payload = dispatch(["logs", "tail", "--limit", "5", "--json"])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["path"].endswith("loom-cli-audit.jsonl"))
        self.assertGreaterEqual(len(payload["data"]["lines"]), 1)

    def test_matrix_status_dry_run_uses_matrix_endpoint(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["matrix", "status", "--json", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/status")
        self.assertEqual(payload["data"]["method"], "GET")

    def test_matrix_status_reads_local_bridge_session_when_available(self) -> None:
        import loom_cli

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self) -> bytes:
                return b'{"devices":[],"tasks":[]}'

        captured: dict[str, str] = {}

        def fake_urlopen(request, timeout):
            headers = {key.lower(): value for key, value in request.header_items()}
            captured["url"] = request.full_url
            captured["token"] = headers.get("x-bridge-token", "")
            captured["timeout"] = str(timeout)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = os.path.join(temp_dir, "session")
            os.makedirs(session_dir, exist_ok=True)
            with open(os.path.join(session_dir, "bridge-session.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "loom.bridge_session.v1",
                        "url": "http://127.0.0.1:18888",
                        "token": "local-session-token",
                    },
                    handle,
                )
            with patch.dict(os.environ, {"LOOM_BRIDGE_SESSION_DIR": session_dir}):
                with patch.object(loom_cli, "DEFAULT_BRIDGE_URL", ""), patch.object(loom_cli, "DEFAULT_BRIDGE_TOKEN", ""):
                    with patch("urllib.request.urlopen", fake_urlopen):
                        code, payload = loom_cli.dispatch(["matrix", "status", "--json"], base_path=temp_dir)

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(captured["url"], "http://127.0.0.1:18888/api/matrix/status")
        self.assertEqual(captured["token"], "local-session-token")
        self.assertEqual(payload["data"]["result"]["devices"], [])

    def test_matrix_dispatch_requires_confirmation_for_bulk_outreach(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "dispatch",
                "--prompt",
                "批量私信所有客户",
                "--device",
                "phone-a",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "safety_confirmation_required")

    def test_matrix_dispatch_dry_run_preserves_layered_execution_fields(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "dispatch",
                "--device",
                "phone-a",
                "--prompt",
                "打开系统设置",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/dispatch")
        self.assertEqual(payload["data"]["body"]["executionLayer"], "template")
        self.assertEqual(payload["data"]["body"]["profile"], "fast")

    def test_matrix_dispatch_target_alias_never_degrades_to_broadcast(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "dispatch",
                "--target",
                "phone-1,phone-2",
                "--prompt",
                "读取当前屏幕",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            payload["data"]["body"]["target"]["deviceIds"],
            ["phone-1", "phone-2"],
        )

    def test_matrix_watch_limit_option_value_is_not_treated_as_campaign_id(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            ["matrix", "watch", "--limit", "5", "--json", "--dry-run"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/watch?limit=5")

    def test_matrix_dispatch_target_option_value_is_not_treated_as_prompt(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "dispatch",
                "--target",
                "phone-a",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "missing_prompt")

    def test_matrix_dispatch_rejects_mixed_device_and_group_targets(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "dispatch",
                "--target",
                "phone-a",
                "--group",
                "lab",
                "--prompt",
                "read screen",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_target")

    def test_matrix_dispatch_and_template_require_an_explicit_target(self) -> None:
        from loom_cli import dispatch

        dispatch_code, dispatch_payload = dispatch(
            ["matrix", "dispatch", "--prompt", "read screen", "--permission", "control", "--json", "--dry-run"]
        )
        template_code, template_payload = dispatch(
            ["template", "run", "--template", "read-screen", "--json", "--dry-run"]
        )

        self.assertEqual(dispatch_code, 2)
        self.assertEqual(dispatch_payload["error"]["code"], "missing_target")
        self.assertEqual(template_code, 2)
        self.assertEqual(template_payload["error"]["code"], "missing_target")

    def test_matrix_watch_cancel_template_and_experience_commands_are_structured(self) -> None:
        from loom_cli import dispatch

        with tempfile.TemporaryDirectory() as temp_dir:
            commands = [
                ["matrix", "watch", "--campaign", "campaign_123", "--limit", "17", "--json", "--dry-run"],
                ["matrix", "cancel", "--campaign", "campaign_123", "--permission", "control", "--json", "--dry-run"],
                ["matrix", "retry", "--campaign", "campaign_123", "--permission", "control", "--json", "--dry-run"],
                ["matrix", "leads", "--limit", "5", "--json", "--dry-run"],
                [
                    "matrix",
                    "record-lead",
                    "--summary",
                    "用户询问套餐",
                    "--device",
                    "phone-a",
                    "--permission",
                    "control",
                    "--json",
                    "--dry-run",
                ],
                ["template", "run", "--template", "read-screen", "--device", "phone-a", "--json", "--dry-run"],
                ["experience", "report", "--json", "--dry-run"],
            ]
            payloads = [dispatch(command, base_path=temp_dir)[1] for command in commands]

        self.assertEqual(payloads[0]["data"]["endpoint"], "/api/matrix/watch?campaignId=campaign_123&limit=17")
        self.assertEqual(payloads[1]["data"]["endpoint"], "/api/matrix/cancel")
        self.assertEqual(payloads[2]["data"]["endpoint"], "/api/matrix/retry")
        self.assertEqual(payloads[3]["data"]["endpoint"], "/api/matrix/leads?limit=5")
        self.assertEqual(payloads[4]["data"]["endpoint"], "/api/matrix/leads")
        self.assertEqual(payloads[4]["data"]["body"]["deviceId"], "phone-a")
        self.assertEqual(payloads[5]["data"]["endpoint"], "/api/matrix/template/run")
        self.assertEqual(payloads[6]["data"]["endpoint"], "/api/matrix/experience")

    def test_matrix_cancel_all_uses_explicit_bulk_cancel_contract(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "cancel",
                "--all",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/cancel")
        self.assertEqual(payload["data"]["body"], {"all": True})

    def test_matrix_record_lead_dry_run_redacts_contact_like_values(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "matrix",
                "record-lead",
                "--summary",
                "用户询问套餐 13800000000 user@example.com Bearer secret-token",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(code, 0)
        self.assertNotIn("13800000000", serialized)
        self.assertNotIn("user@example.com", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_expanded_cli_domains_are_structured_and_redacted(self) -> None:
        from loom_cli import dispatch

        commands = [
            ["media", "image", "--prompt", "product photo", "--permission", "control", "--json", "--dry-run"],
            [
                "wire",
                "custom",
                "--base-url",
                "https://api.example.com/v1",
                "--api-key",
                "secret-value",
                "--text-model",
                "qwen",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ],
            [
                "agents",
                "model-apply",
                "--component",
                "codex-desktop",
                "--model",
                "qwen",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ],
            ["account", "subscription", "--json", "--dry-run"],
        ]
        payloads = [dispatch(command)[1] for command in commands]

        self.assertEqual(payloads[0]["data"]["endpoint"], "/api/image/generate/submit")
        self.assertEqual(payloads[1]["data"]["endpoint"], "/api/wire/custom")
        self.assertNotIn("secret-value", json.dumps(payloads[1], ensure_ascii=False))
        self.assertEqual(payloads[2]["data"]["endpoint"], "/api/components/model-config/apply")
        self.assertEqual(payloads[3]["data"]["endpoint"], "/api/account/subscription")

    def test_media_generation_cli_commands_mark_shared_library_source(self) -> None:
        from loom_cli import dispatch

        commands = [
            ["media", "image", "--prompt", "product photo", "--permission", "control", "--json", "--dry-run"],
            ["media", "video", "--prompt", "product video", "--permission", "control", "--json", "--dry-run"],
        ]
        payloads = [dispatch(command)[1] for command in commands]

        self.assertEqual(payloads[0]["data"]["body"]["source"], "cli")
        self.assertEqual(payloads[1]["data"]["body"]["source"], "cli")

    def test_media_image_cli_maps_common_ratio_to_provider_size(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch([
            "media",
            "image",
            "--prompt",
            "wide product banner",
            "--ratio",
            "5:2",
            "--permission",
            "control",
            "--json",
            "--dry-run",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["body"]["ratio"], "5:2")
        self.assertEqual(payload["data"]["body"]["size"], "2560x1024")

    def test_expanded_cli_admin_update_requires_admin_permission(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(["settings", "update-do", "--permission", "read", "--json", "--dry-run"])

        self.assertEqual(code, 3)
        self.assertEqual(payload["error"]["code"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
