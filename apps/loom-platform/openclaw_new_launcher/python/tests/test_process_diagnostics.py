from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from unittest import mock


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.paths import AppPaths
from services.process import OpenClawProcessService


@dataclass
class FakeCompletedProcess:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class TestableProcessService(OpenClawProcessService):
    def _stop_registered_gateway(self) -> int:
        return 0

    def _kill_clawpanel_processes(self) -> int:
        return 0

    def _kill_openclaw_gateway_processes(self) -> int:
        return 0

    def _kill_port_processes(self, _port: int) -> int:
        return 0

    def _kill_port_range_processes(self, _start_port: int, _end_port: int, *, exclude_pids=None) -> int:
        return 0

    def _storage_health_check(self, *, write_test: bool = False) -> dict:
        return {
            "id": "storage",
            "label": "运行磁盘 / U盘健康",
            "status": "ok",
            "message": "写入测试通过",
            "detail": "test",
            "repairable": False,
        }

    def diagnose_environment(self) -> dict:
        return {
            "basePath": self.paths.base_path,
            "serviceRunning": False,
            "servicePid": None,
            "checks": [
                self._webview2_check(),
                {
                    "id": "node",
                    "label": "Node.js 运行时",
                    "status": "fail",
                    "message": "缺失，可能导致启动失败",
                    "detail": os.path.join(self.paths.base_path, "node", "node.exe"),
                    "repairable": False,
                },
                {
                    "id": "python_runtime",
                    "label": "Python / Bridge 运行时",
                    "status": "fail",
                    "message": "未找到 Python 运行时，Bridge 无法启动",
                    "detail": os.path.join(self.paths.base_path, "_up_", "python-runtime", "python.exe"),
                    "repairable": False,
                },
                {
                    "id": "git",
                    "label": "Git",
                    "status": "warn",
                    "message": "未找到；部分编程智能体的仓库能力会受限",
                    "detail": "Git for Windows",
                    "repairable": False,
                },
                {
                    "id": "uv",
                    "label": "uv",
                    "status": "warn",
                    "message": "未找到；Python 组件安装会使用备用流程",
                    "detail": "Python uv package manager",
                    "repairable": False,
                },
            ],
        }


class MinimalDiagnosticProcessService(OpenClawProcessService):
    def _storage_health_check(self, *, write_test: bool = False) -> dict:
        return {"id": "storage_health", "label": "storage", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _openclaw_config_check(self) -> dict:
        return {"id": "openclaw_config", "label": "config", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _webview2_check(self) -> dict:
        return {"id": "webview2", "label": "webview2", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _python_runtime_check(self) -> dict:
        return {"id": "python_runtime", "label": "python", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _portable_integrity_check(self) -> dict:
        return {"id": "portable_integrity", "label": "portable", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _security_software_block_check(self) -> dict:
        return {"id": "security_software_block", "label": "security", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _runtime_context_check(self) -> dict:
        return {"id": "runtime_context", "label": "runtime", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _phone_agent_apk_check(self) -> dict:
        return {"id": "phone_agent_apk", "label": "apk", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _member_gateway_check(self) -> dict:
        return {"id": "member_gateway", "label": "gateway", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _core_service_snapshot_check(self) -> dict:
        return {"id": "core_service_snapshot", "label": "core", "status": "ok", "message": "ok", "detail": "ok", "repairable": False}

    def _port_listeners(self, _port: int) -> list[dict]:
        return []

    def _port_range_listeners(self, _start_port: int, _end_port: int, *, exclude_pids=None) -> list[dict]:
        return []

    def _openclaw_gateway_processes(self) -> list[dict]:
        return []

    def _clawpanel_processes(self) -> list[dict]:
        return []

    def _detect_openclaw_version(self) -> str | None:
        return "test"


class ProcessDiagnosticsRepairTests(unittest.TestCase):
    def test_packaged_openclaw_component_is_a_valid_core_start_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            node_exe = os.path.join(temp_dir, "_up_", "node-runtime", "node.exe")
            openclaw_mjs = os.path.join(
                temp_dir,
                "data",
                ".installer",
                "npm-global",
                "node_modules",
                "openclaw",
                "openclaw.mjs",
            )
            for path in (node_exe, openclaw_mjs):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"ok")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
            )

            command = service._resolve_openclaw_start_command()

            self.assertEqual(os.path.normcase(command[0]), os.path.normcase(node_exe))
            self.assertEqual(os.path.normcase(command[1]), os.path.normcase(openclaw_mjs))
            self.assertEqual(command[2:4], ["gateway", "--port"])
            check = service._openclaw_start_entry_check()
            self.assertEqual(check["status"], "ok")
            self.assertEqual(os.path.normcase(check["detail"]), os.path.normcase(openclaw_mjs))

    def test_prerequisite_diagnostics_excludes_expensive_checks_and_reports_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            def unavailable(*_args, **_kwargs):
                raise AssertionError("full diagnostics check ran during prerequisite detection")

            service._port_range_listeners = unavailable
            service._openclaw_gateway_processes = unavailable
            service._clawpanel_processes = unavailable
            service._phone_agent_apk_check = unavailable
            service._member_gateway_check = unavailable
            service._core_service_snapshot_check = unavailable
            original_webview2_check = service._webview2_check

            def slow_webview2_check() -> dict:
                time.sleep(0.01)
                return original_webview2_check()

            service._webview2_check = slow_webview2_check

            diagnostics = service.diagnose_prerequisites()

        checks = diagnostics["checks"]
        self.assertEqual(
            [check["id"] for check in checks],
            ["python_runtime", "node", "npm", "git", "git_bash", "uv", "webview2", "data_dir"],
        )
        self.assertGreaterEqual(diagnostics["timing"]["totalMs"], 0)
        self.assertTrue(all(check["id"] in diagnostics["timing"]["checksMs"] for check in checks))
        self.assertGreaterEqual(diagnostics["timing"]["checksMs"]["webview2"], 10)

    def test_prerequisite_diagnostics_avoids_hung_deep_python_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            def hung_deep_probe() -> dict:
                time.sleep(2)
                raise AssertionError("quick diagnostics used the deep Python probe")

            service._python_runtime_check = hung_deep_probe
            started = time.perf_counter()
            diagnostics = service.diagnose_prerequisites()
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1)
        self.assertEqual(diagnostics["checks"][0]["id"], "python_runtime")

    def test_full_diagnostics_omits_obsolete_openclaw_install_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )
            checks = service.diagnose_environment()["checks"]

        self.assertEqual(
            [check["id"] for check in checks],
            [
                "base_path", "storage_health", "node", "npm", "data_dir", "git", "git_bash", "uv", "webview2",
                "python_runtime", "portable_integrity", "security_software_block", "runtime_context",
                "phone_agent_apk", "member_gateway", "core_service_snapshot", "port_18790",
                "bridge_ports", "stale_process", "openclaw_version",
            ],
        )

    def test_prerequisite_repair_avoids_runtime_cleanup_and_runs_one_final_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )
            calls: list[str] = []
            quick_snapshot = {
                "basePath": temp_dir,
                "serviceRunning": False,
                "servicePid": None,
                "checks": [{"id": "webview2", "status": "fail", "repairable": True}],
                "timing": {"totalMs": 0, "checksMs": {"webview2": 0}, "measuredAt": "2026-07-10T00:00:00+0000"},
            }

            def diagnose_prerequisites():
                calls.append("diagnose")
                return quick_snapshot

            def action(name: str):
                def run(_checks: list[dict]) -> dict:
                    calls.append(name)
                    return {"label": name, "status": "ok", "message": "ok", "count": 0}
                return run

            def unavailable(*_args, **_kwargs):
                raise AssertionError("runtime cleanup ran during prerequisite repair")

            service.diagnose_prerequisites = diagnose_prerequisites
            service._install_public_prerequisites_action = action("install")
            service._repair_webview2_runtime = action("webview2")
            service._prerequisite_source_check_action = action("source")
            service._stop_registered_gateway = unavailable
            service._kill_clawpanel_processes = unavailable
            service._kill_openclaw_gateway_processes = unavailable
            service._kill_port_processes = unavailable
            service._kill_port_range_processes = unavailable
            service._ensure_openclaw_config = unavailable

            result = service.repair_prerequisites()

            self.assertEqual(calls, ["diagnose", "install", "webview2", "source", "diagnose"])
            self.assertEqual(result["diagnostics"], quick_snapshot)
            self.assertTrue(os.path.isdir(service.paths.data_dir))

    def test_prerequisite_repair_never_reports_success_when_final_checks_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
            )
            snapshots = [
                {"checks": [{"id": "node", "label": "Node.js", "status": "fail", "repairable": True}]},
                {"checks": [{"id": "node", "label": "Node.js", "status": "fail", "repairable": True}]},
            ]
            service.diagnose_prerequisites = lambda: snapshots.pop(0)
            service._install_public_prerequisites_action = lambda _checks: {
                "label": "install",
                "status": "ok",
                "message": "winget returned zero",
                "count": 1,
                "restartRequired": True,
            }
            service._repair_webview2_runtime = lambda _checks: {"label": "webview", "status": "ok", "message": "ok", "count": 0}
            service._prerequisite_source_check_action = lambda _checks: {"label": "sources", "status": "warn", "message": "missing", "count": 1}

            result = service.repair_prerequisites()

            self.assertFalse(result["ok"])
            self.assertTrue(result["restartRequired"])
            self.assertEqual(result["actions"][-1]["status"], "fail")
            self.assertIn("Node.js", result["actions"][-1]["message"])

    def test_repairable_winget_item_is_not_misreported_as_an_offline_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
            )

            result = service._prerequisite_source_check_action([
                {"id": "git", "status": "fail", "repairable": True},
            ])

            self.assertEqual(result["status"], "warn")
            self.assertIn("Git", result["message"])

    def test_phone_adb_doctor_reports_missing_adb_with_repair_instructions(self) -> None:
        import services.process as process_module

        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            original_which = process_module.shutil.which
            process_module.shutil.which = lambda name: None if name in {"adb", "adb.exe"} else original_which(name)
            try:
                result = service.phone_adb_doctor()
            finally:
                process_module.shutil.which = original_which

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "missing_adb")
        self.assertIn("platform-tools", " ".join(result["instructions"]))

    def test_phone_adb_doctor_discovers_protected_bundle_redist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adb_dir = os.path.join(temp_dir, "_up_", "redist", "platform-tools")
            os.makedirs(adb_dir)
            adb_path = os.path.join(adb_dir, "adb.exe")
            with open(adb_path, "wb") as file:
                file.write(b"fake adb")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(
                    returncode=0,
                    stdout="List of devices attached\n",
                ),
            )

            self.assertEqual(service._find_adb_path(), adb_path)

    def test_phone_adb_doctor_wakes_and_launches_apkclaw_when_device_is_ready(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            calls.append(command)
            if command[1:] == ["devices", "-l"]:
                return FakeCompletedProcess(returncode=0, stdout="List of devices attached\nemulator-5554\tdevice product:sdk\n")
            return FakeCompletedProcess(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as temp_dir:
            adb_dir = os.path.join(temp_dir, "platform-tools")
            os.makedirs(adb_dir)
            adb_path = os.path.join(adb_dir, "adb.exe")
            with open(adb_path, "wb") as file:
                file.write(b"fake adb")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
            )

            result = service.phone_adb_doctor(serial="emulator-5554")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        flattened = [" ".join(command) for command in calls]
        self.assertTrue(any("KEYCODE_WAKEUP" in command for command in flattened))
        self.assertTrue(any("KEYCODE_HOME" in command for command in flattened))
        self.assertTrue(any("monkey -p com.apk.claw.android" in command for command in flattened))

    def test_phone_adb_doctor_does_not_fallback_to_wrong_device_when_serial_is_missing(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            calls.append(command)
            if command[1:] == ["devices", "-l"]:
                return FakeCompletedProcess(returncode=0, stdout="List of devices attached\nphone-a\tdevice product:test\n")
            return FakeCompletedProcess(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as temp_dir:
            adb_dir = os.path.join(temp_dir, "platform-tools")
            os.makedirs(adb_dir)
            with open(os.path.join(adb_dir, "adb.exe"), "wb") as file:
                file.write(b"fake adb")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
            )

            result = service.phone_adb_doctor(serial="phone-b")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "device_not_found")
        flattened = [" ".join(command) for command in calls]
        self.assertFalse(any("KEYCODE_WAKEUP" in command for command in flattened))
        self.assertFalse(any("monkey -p" in command for command in flattened))

    def test_phone_adb_doctor_requires_serial_when_multiple_devices_exist(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            calls.append(command)
            if command[1:] == ["devices", "-l"]:
                return FakeCompletedProcess(
                    returncode=0,
                    stdout="List of devices attached\nphone-a\tdevice product:test\nphone-b\tdevice product:test\n",
                )
            return FakeCompletedProcess(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as temp_dir:
            adb_dir = os.path.join(temp_dir, "platform-tools")
            os.makedirs(adb_dir)
            with open(os.path.join(adb_dir, "adb.exe"), "wb") as file:
                file.write(b"fake adb")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
            )

            result = service.phone_adb_doctor()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "multiple_devices")
        self.assertEqual([device["serial"] for device in result["devices"]], ["phone-a", "phone-b"])
        flattened = [" ".join(command) for command in calls]
        self.assertFalse(any("KEYCODE_WAKEUP" in command for command in flattened))
        self.assertFalse(any("monkey -p" in command for command in flattened))

    def test_diagnostics_use_system_node_and_npm_as_prerequisite_fallback(self) -> None:
        import services.process as process_module

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )
            fake_tools = {
                "node": os.path.join(temp_dir, "system-node", "node.exe"),
                "node.exe": os.path.join(temp_dir, "system-node", "node.exe"),
                "npm": os.path.join(temp_dir, "system-node", "npm.cmd"),
                "npm.cmd": os.path.join(temp_dir, "system-node", "npm.cmd"),
            }

            original_which = process_module.shutil.which
            process_module.shutil.which = lambda name: fake_tools.get(name) or original_which(name)
            try:
                checks = {item["id"]: item for item in service.diagnose_environment()["checks"]}
            finally:
                process_module.shutil.which = original_which

        self.assertEqual(checks["node"]["status"], "ok")
        self.assertIn("system-node", checks["node"]["detail"])
        self.assertEqual(checks["npm"]["status"], "ok")
        self.assertIn("system-node", checks["npm"]["detail"])

    def test_diagnostics_mark_node_and_npm_repairable_when_no_runtime_exists(self) -> None:
        import services.process as process_module

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            original_which = process_module.shutil.which
            process_module.shutil.which = lambda name: None if name in {"node", "node.exe", "npm", "npm.cmd", "npm.exe"} else original_which(name)
            try:
                checks = {item["id"]: item for item in service.diagnose_environment()["checks"]}
            finally:
                process_module.shutil.which = original_which

        self.assertEqual(checks["node"]["status"], "fail")
        self.assertTrue(checks["node"]["repairable"])
        self.assertEqual(checks["npm"]["status"], "fail")
        self.assertTrue(checks["npm"]["repairable"])

    def test_diagnostics_mark_git_git_bash_and_uv_repairable_for_blank_windows_user(self) -> None:
        import services.process as process_module

        with tempfile.TemporaryDirectory() as temp_dir:
            service = MinimalDiagnosticProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            original_which = process_module.shutil.which
            old_program_files = os.environ.get("ProgramFiles")
            old_program_files_x86 = os.environ.get("ProgramFiles(x86)")
            os.environ["ProgramFiles"] = os.path.join(temp_dir, "ProgramFiles")
            os.environ["ProgramFiles(x86)"] = os.path.join(temp_dir, "ProgramFilesX86")
            process_module.shutil.which = (
                lambda name: None
                if name in {"git", "git.exe", "bash", "bash.exe", "uv", "uv.exe"}
                else original_which(name)
            )
            try:
                checks = {item["id"]: item for item in service.diagnose_environment()["checks"]}
            finally:
                process_module.shutil.which = original_which
                if old_program_files is None:
                    os.environ.pop("ProgramFiles", None)
                else:
                    os.environ["ProgramFiles"] = old_program_files
                if old_program_files_x86 is None:
                    os.environ.pop("ProgramFiles(x86)", None)
                else:
                    os.environ["ProgramFiles(x86)"] = old_program_files_x86

        self.assertEqual(checks["git"]["status"], "fail")
        self.assertTrue(checks["git"]["repairable"])
        self.assertEqual(checks["git_bash"]["status"], "fail")
        self.assertTrue(checks["git_bash"]["repairable"])
        self.assertEqual(checks["uv"]["status"], "warn")
        self.assertTrue(checks["uv"]["repairable"])

    def test_diagnostics_find_git_bash_next_to_custom_git_path(self) -> None:
        import services.process as process_module

        with tempfile.TemporaryDirectory() as temp_dir:
            git_root = os.path.join(temp_dir, "CustomGit")
            git_cmd = os.path.join(git_root, "cmd")
            git_bin = os.path.join(git_root, "bin")
            os.makedirs(git_cmd)
            os.makedirs(git_bin)
            git_exe = os.path.join(git_cmd, "git.exe")
            bash_exe = os.path.join(git_bin, "bash.exe")
            with open(git_exe, "wb") as file:
                file.write(b"git")
            with open(bash_exe, "wb") as file:
                file.write(b"bash")

            service = MinimalDiagnosticProcessService(
                AppPaths(os.path.join(temp_dir, "app")),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            original_which = process_module.shutil.which
            process_module.shutil.which = (
                lambda name: git_exe
                if name in {"git", "git.exe"}
                else None if name in {"bash", "bash.exe", "uv", "uv.exe"} else original_which(name)
            )
            try:
                checks = {item["id"]: item for item in service.diagnose_environment()["checks"]}
            finally:
                process_module.shutil.which = original_which

        self.assertEqual(checks["git"]["status"], "ok")
        self.assertEqual(checks["git_bash"]["status"], "ok")
        self.assertIn("CustomGit", checks["git_bash"]["detail"])

    def test_portable_integrity_allows_online_package_without_openclaw_runtime_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            required_files = [
                os.path.join("node", "node.exe"),
                "start.js",
                os.path.join("_up_", "python", "bridge.py"),
                os.path.join("scripts", "openclaw-image-phone.mjs"),
                os.path.join("scripts", "openclaw-phone-video.mjs"),
                os.path.join("scripts", "openclaw-phone-vision.mjs"),
                os.path.join("scripts", "verify-phone-agent.ps1"),
                os.path.join("data", ".openclaw", "workspace", "AGENTS.md"),
                os.path.join("data", ".openclaw", "workspace", "SOUL.md"),
            ]
            for relative_path in required_files:
                full_path = os.path.join(temp_dir, relative_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as file:
                    file.write(b"ok")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            result = service._portable_integrity_check()

            self.assertEqual(result["status"], "ok")
            self.assertNotIn("openclaw.mjs", result["detail"])

    def test_portable_integrity_accepts_packaged_up_scripts_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            required_files = [
                os.path.join("_up_", "node-runtime", "node.exe"),
                "start.js",
                os.path.join("_up_", "python", "bridge.py"),
                os.path.join("_up_", "scripts", "openclaw-image-phone.mjs"),
                os.path.join("_up_", "scripts", "openclaw-phone-video.mjs"),
                os.path.join("_up_", "scripts", "openclaw-phone-vision.mjs"),
                os.path.join("_up_", "scripts", "verify-phone-agent.ps1"),
                os.path.join("_up_", "openclaw-workspace", "AGENTS.md"),
                os.path.join("_up_", "openclaw-workspace", "SOUL.md"),
            ]
            for relative_path in required_files:
                full_path = os.path.join(temp_dir, relative_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as file:
                    file.write(b"ok")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )

            result = service._portable_integrity_check()

            self.assertEqual(result["status"], "ok")

    def test_repair_runs_bundled_webview2_installer_when_missing(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            calls.append(command)
            return FakeCompletedProcess(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            redist_dir = os.path.join(temp_dir, "redist")
            os.makedirs(redist_dir)
            installer = os.path.join(redist_dir, "MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
            with open(installer, "wb") as file:
                file.write(b"fake webview2 installer")

            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
            )
            service._webview2_check = lambda: {
                "id": "webview2",
                "label": "WebView2 Runtime",
                "status": "fail",
                "message": "未检测到 WebView2 Runtime，启动器窗口可能白屏或无法渲染",
                "detail": f"offline installer: {installer}",
                "repairable": True,
            }

            result = service.repair_environment()

            self.assertIn([installer, "/silent", "/install"], calls)
            webview_action = next(action for action in result["actions"] if action["label"] == "安装 WebView2 Runtime")
            self.assertEqual(webview_action["status"], "ok")
            self.assertIn("离线安装器", webview_action["message"])

    def test_empty_webview_application_directory_is_not_a_valid_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(OpenClawProcessService._webview2_dir_is_valid(temp_dir))
            runtime_exe = os.path.join(temp_dir, "123.0.0.0", "msedgewebview2.exe")
            os.makedirs(os.path.dirname(runtime_exe), exist_ok=True)
            with open(runtime_exe, "wb") as handle:
                handle.write(b"runtime")
            self.assertTrue(OpenClawProcessService._webview2_dir_is_valid(temp_dir))

    def test_repair_warns_when_critical_prerequisites_need_a_complete_portable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(returncode=0),
            )
            service._webview2_check = lambda: {
                "id": "webview2",
                "label": "WebView2 Runtime",
                "status": "ok",
                "message": "已检测到 WebView2 Runtime",
                "detail": "test",
                "repairable": False,
            }

            result = service.repair_environment()

            source_action = next(action for action in result["actions"] if action["label"] == "前置环境离线源检查")
            self.assertEqual(source_action["status"], "warn")
            self.assertIn("完整 LOOM 离线包", source_action["message"])
            self.assertIn("Node.js", source_action["message"])
            self.assertIn("Python", source_action["message"])
            self.assertIn("Git", source_action["message"])

    def test_repair_installs_missing_public_prerequisites_with_winget_and_uv(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            calls.append(command)
            return FakeCompletedProcess(returncode=0, stdout="ok")

        with tempfile.TemporaryDirectory() as temp_dir:
            service = TestableProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
            )
            service._webview2_check = lambda: {
                "id": "webview2",
                "label": "WebView2 Runtime",
                "status": "ok",
                "message": "已检测到 WebView2 Runtime",
                "detail": "test",
                "repairable": False,
            }

            result = service.repair_environment()

            self.assertIn(["winget", "--version"], calls)
            self.assertIn(
                [
                    "winget",
                    "install",
                    "--id",
                    "Git.Git",
                    "--exact",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                    "--source",
                    "winget",
                    "--silent",
                ],
                calls,
            )
            self.assertIn(
                [
                    "winget",
                    "install",
                    "--id",
                    "OpenJS.NodeJS.LTS",
                    "--exact",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                    "--source",
                    "winget",
                    "--silent",
                ],
                calls,
            )
            self.assertIn(
                [
                    "winget",
                    "install",
                    "--id",
                    "Python.Python.3.11",
                    "--exact",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                    "--source",
                    "winget",
                    "--silent",
                ],
                calls,
            )
            self.assertIn(
                [
                    "winget",
                    "install",
                    "--id",
                    "astral-sh.uv",
                    "--exact",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                    "--source",
                    "winget",
                    "--silent",
                ],
                calls,
            )
            self.assertFalse(any("irm" in " ".join(command).lower() or "iex" in " ".join(command).lower() for command in calls))
            action = next(action for action in result["actions"] if action["label"] == "安装公共前置环境")
            self.assertEqual(action["status"], "ok")

    def test_public_prerequisite_install_retries_transient_winget_failure_and_refreshes_path(self) -> None:
        install_attempts = 0

        def fake_runner(command: list[str], _timeout_sec: int) -> FakeCompletedProcess:
            nonlocal install_attempts
            if command[:2] == ["winget", "--version"]:
                return FakeCompletedProcess(returncode=0, stdout="v1")
            install_attempts += 1
            if install_attempts == 1:
                return FakeCompletedProcess(returncode=1, stderr="source network connection reset")
            return FakeCompletedProcess(returncode=0, stdout="installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            service = OpenClawProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=fake_runner,
                retry_sleep=lambda _seconds: None,
            )
            checks = [{"id": "node", "status": "fail"}, {"id": "npm", "status": "fail"}]
            with mock.patch("services.process._refresh_process_path_from_windows_registry", return_value=True) as refresh:
                action = service._install_public_prerequisites_action(checks)

            self.assertEqual(action["status"], "ok")
            self.assertEqual(install_attempts, 2)
            refresh.assert_called_once_with()

    def test_public_prerequisite_install_does_not_report_success_when_winget_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OpenClawProcessService(
                AppPaths(temp_dir),
                append_log=lambda _text: None,
                ui_call=lambda *_args: None,
                command_runner=lambda _command, _timeout_sec: FakeCompletedProcess(
                    returncode=1,
                    stderr="App Installer is unavailable",
                ),
                retry_sleep=lambda _seconds: None,
            )

            action = service._install_public_prerequisites_action([{"id": "node", "status": "fail"}])

            self.assertEqual(action["status"], "fail")
            self.assertEqual(action["count"], 0)
            self.assertIn("winget 不可用", action["message"])

    def test_merge_windows_path_keeps_new_registry_entries_and_deduplicates_case_insensitively(self) -> None:
        from services.process import _merge_windows_path

        merged = _merge_windows_path(
            r"C:\\Old;C:\\Tools",
            [r"C:\\Program Files\\nodejs", r"c:\\tools", r"C:\\Users\\demo\\bin"],
        )

        self.assertEqual(
            merged.split(";"),
            [r"C:\\Program Files\\nodejs", r"c:\\tools", r"C:\\Users\\demo\\bin", r"C:\\Old"],
        )


if __name__ == "__main__":
    unittest.main()
