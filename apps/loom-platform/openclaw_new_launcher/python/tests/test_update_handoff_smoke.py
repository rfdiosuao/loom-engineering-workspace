from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HANDOFF = os.path.join(ROOT, "src-tauri", "installer", "update-handoff.ps1")


@unittest.skipUnless(os.name == "nt", "Windows update handoff smoke")
class UpdateHandoffSmokeTests(unittest.TestCase):
    def _run_handoff(
        self,
        *,
        fail: bool,
        spawn_owned_process: bool = False,
        spawn_up_runtime_processes: bool = False,
        spawn_installer_owned_process: bool = False,
        disable_cim_process_scan: bool = False,
        fail_cim_process_scan: bool = False,
        inject_taskkill_failure: bool = False,
        inject_direct_stop_failure: bool = False,
        health_fail: bool = False,
        health_late_fail: bool = False,
    ) -> tuple[str, str, str]:
        temp_dir = tempfile.mkdtemp(prefix="loom-update-中文-")
        self.addCleanup(shutil.rmtree, temp_dir, True)
        install_root = os.path.join(temp_dir, "旧版本 LOOM")
        recovery_root = os.path.join(temp_dir, "外部恢复")
        marker_path = os.path.join(temp_dir, "state", "update-pending.json")
        previous_success = os.path.join(temp_dir, "previous-success")
        other_install_success = os.path.join(temp_dir, "other-install-success")
        os.makedirs(os.path.join(install_root, "data", "nested"), exist_ok=True)
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        os.makedirs(previous_success, exist_ok=True)
        os.makedirs(other_install_success, exist_ok=True)
        with open(os.path.join(previous_success, "update-success.json"), "w", encoding="utf-8") as handle:
            json.dump({"state": "healthy", "installRoot": install_root}, handle)
        with open(os.path.join(other_install_success, "update-success.json"), "w", encoding="utf-8") as handle:
            json.dump({"state": "healthy", "installRoot": os.path.join(temp_dir, "other-app")}, handle)
        with open(os.path.join(install_root, "data", "nested", "lead.json"), "w", encoding="utf-8") as handle:
            handle.write('{"lead":"preserve-me"}')
        app_exe = os.path.join(install_root, "LOOM.exe")
        with open(app_exe, "wb") as handle:
            handle.write(b"old")
        old_runtime = os.path.join(install_root, "old-runtime.txt")
        with open(old_runtime, "wb") as handle:
            handle.write(b"old-runtime")
        installer_process_pid_file = os.path.join(temp_dir, "installer-owned.pid")

        lingering_processes: list[subprocess.Popen[bytes]] = []
        owned_runtime_paths: list[str] = []
        if spawn_owned_process:
            owned_runtime_paths.append(os.path.join("runtime", "python.exe"))
        if spawn_up_runtime_processes:
            owned_runtime_paths.extend([
                os.path.join("_up_", "python-runtime", "python.exe"),
                os.path.join("_up_", "node-runtime", "node.exe"),
            ])
        for relative_runtime_path in owned_runtime_paths:
            owned_executable = os.path.join(install_root, relative_runtime_path)
            os.makedirs(os.path.dirname(owned_executable), exist_ok=True)
            shutil.copy2(os.path.join(os.environ["WINDIR"], "System32", "ping.exe"), owned_executable)
            lingering_processes.append(subprocess.Popen(
                [owned_executable, "-n", "120", "127.0.0.1"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ))
        lingering_pids = [process.pid for process in lingering_processes]

        installer = os.path.join(temp_dir, "fake setup.cmd")
        exit_code = 7 if fail else 0
        script = "\r\n".join(
            [
                "@echo off",
                *[
                    line
                    for lingering_pid in lingering_pids
                    for line in [
                        f'powershell.exe -NoProfile -NonInteractive -Command "if (Get-Process -Id {lingering_pid} -ErrorAction SilentlyContinue) {{ exit 9 }}"',
                        "if errorlevel 1 exit /b 9",
                    ]
                ],
                'set "target=%~2"',
                'set "target=%target:~3%"',
                'rmdir /s /q "%target%\\data" 2>nul',
                'mkdir "%target%" 2>nul',
                'mkdir "%target%\\data" 2>nul',
                'echo incompatible>"%target%\\data\\vnext-schema.json"',
                'echo new-binary>"%target%\\LOOM.exe"',
                'del /q "%target%\\old-runtime.txt" 2>nul',
                'echo partial-new-file>"%target%\\new-only.txt"',
                'echo new>"%target%\\installed-version.txt"',
                *(
                    [
                        'mkdir "%target%\\runtime" 2>nul',
                        'copy /y "%WINDIR%\\System32\\ping.exe" "%target%\\runtime\\python.exe" >nul',
                        (
                            'powershell.exe -NoProfile -NonInteractive -Command '
                            '"$p = Start-Process -FilePath \'%target%\\runtime\\python.exe\' '
                            "-ArgumentList \'-n\',\'120\',\'127.0.0.1\' -WindowStyle Hidden -PassThru; "
                            "[System.IO.File]::WriteAllText(\'%~dp0installer-owned.pid\', [string]$p.Id)\""
                        ),
                        "if errorlevel 1 exit /b 8",
                    ]
                    if spawn_installer_owned_process
                    else []
                ),
                'if defined LOOM_UPDATE_TEST_PRODUCT_KEY reg.exe add "%LOOM_UPDATE_TEST_PRODUCT_KEY%" /v DisplayVersion /t REG_SZ /d 9.9.9 /f >nul',
                f"exit /b {exit_code}",
            ]
        )
        with open(installer, "w", encoding="ascii", newline="") as handle:
            handle.write(script)

        handoff_arguments = [
            "-Installer",
            installer,
            "-InstallRoot",
            install_root,
            "-AppExe",
            app_exe,
            "-RecoveryRoot",
            recovery_root,
            "-MarkerPath",
            marker_path,
            "-ParentPid",
            "2147483647",
            "-Version",
            "2.1.62",
        ]
        handoff_arguments.append("-TestMode")
        if disable_cim_process_scan or fail_cim_process_scan:
            wrapper_path = os.path.join(temp_dir, "handoff-without-cim.ps1")
            rendered_arguments = []
            for argument in handoff_arguments:
                if argument.startswith("-"):
                    rendered_arguments.append(argument)
                else:
                    rendered_arguments.append("'" + argument.replace("'", "''") + "'")
            wrapper = "\r\n".join(
                [
                    "function Get-CimInstance {",
                    "    [CmdletBinding()]",
                    "    param([Parameter(Position = 0)][string]$ClassName)",
                    *(
                        ["    throw 'The paging file is too small for this operation to complete.'"]
                        if fail_cim_process_scan
                        else ["    return @()"]
                    ),
                    "}",
                    "& '" + HANDOFF.replace("'", "''") + "' " + " ".join(rendered_arguments),
                    "$handoffSucceeded = $?",
                    "if ($handoffSucceeded) { exit 0 }",
                    "exit 1",
                ]
            )
            with open(wrapper_path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write(wrapper)
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                wrapper_path,
            ]
        else:
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                HANDOFF,
                *handoff_arguments,
            ]
        environment = os.environ.copy()
        registry_root = rf"HKCU\Software\LOOMUpdateTests\{uuid.uuid4().hex}"
        product_key = registry_root + r"\Product"
        self.addCleanup(
            subprocess.run,
            ["reg.exe", "delete", registry_root, "/f"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            ["reg.exe", "add", product_key, "/v", "InstallLocation", "/t", "REG_SZ", "/d", install_root, "/f"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["reg.exe", "add", product_key, "/v", "DisplayVersion", "/t", "REG_SZ", "/d", "2.1.89", "/f"],
            capture_output=True,
            check=True,
        )
        environment["LOOM_UPDATE_TEST_UNINSTALL_ROOT"] = registry_root
        environment["LOOM_UPDATE_TEST_PRODUCT_KEY"] = product_key
        if inject_taskkill_failure:
            environment["LOOM_UPDATE_TEST_TASKKILL_FAILURE"] = "1"
        else:
            environment.pop("LOOM_UPDATE_TEST_TASKKILL_FAILURE", None)
        if inject_direct_stop_failure:
            environment["LOOM_UPDATE_TEST_DIRECT_STOP_FAILURE"] = "1"
            environment["LOOM_UPDATE_TEST_PROCESS_STOP_TIMEOUT_MS"] = "750"
        else:
            environment.pop("LOOM_UPDATE_TEST_DIRECT_STOP_FAILURE", None)
            environment.pop("LOOM_UPDATE_TEST_PROCESS_STOP_TIMEOUT_MS", None)
        if health_fail:
            environment["LOOM_UPDATE_TEST_HEALTH_MODE"] = "fail"
        elif health_late_fail:
            environment["LOOM_UPDATE_TEST_HEALTH_MODE"] = "late-fail"
        else:
            environment.pop("LOOM_UPDATE_TEST_HEALTH_MODE", None)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=environment,
            )
            expected = 1 if fail or health_fail or health_late_fail else 0
            diagnostic = completed.stderr or completed.stdout
            handoff_log = os.path.join(recovery_root, "update-handoff.log")
            if completed.returncode != expected and os.path.isfile(handoff_log):
                with open(handoff_log, "r", encoding="utf-8-sig", errors="replace") as handle:
                    diagnostic = f"{diagnostic}\n{handle.read()}"
            self.assertEqual(completed.returncode, expected, diagnostic)
            if inject_taskkill_failure:
                with open(handoff_log, "r", encoding="utf-8-sig", errors="replace") as handle:
                    log_text = handle.read()
                self.assertIn("taskkill failed", log_text)
                if inject_direct_stop_failure:
                    self.assertIn("direct process termination failed", log_text)
                else:
                    self.assertIn("direct process termination verified", log_text)
            for lingering_process in lingering_processes:
                lingering_process.wait(timeout=10)
        finally:
            for lingering_process in lingering_processes:
                if lingering_process.poll() is None:
                    lingering_process.kill()
                    lingering_process.wait(timeout=5)
            if os.path.isfile(installer_process_pid_file):
                with open(installer_process_pid_file, "r", encoding="ascii") as handle:
                    installer_process_pid = handle.read().strip()
                if installer_process_pid:
                    try:
                        os.kill(int(installer_process_pid), signal.SIGTERM)
                    except (OSError, ValueError):
                        pass
        preserved = os.path.join(install_root, "data", "nested", "lead.json")
        with open(preserved, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"lead":"preserve-me"}')
        self.assertFalse(os.path.exists(os.path.join(install_root, "data", "vnext-schema.json")))
        registry_result = subprocess.run(
            ["reg.exe", "query", product_key, "/v", "DisplayVersion"],
            capture_output=True,
            text=True,
            check=True,
        )
        expected_registry_version = "2.1.89" if fail or health_fail or health_late_fail else "9.9.9"
        self.assertIn(expected_registry_version, registry_result.stdout)
        return marker_path, recovery_root, install_root

    def test_update_stops_python_process_owned_by_install_root_before_setup(self) -> None:
        self._run_handoff(fail=False, spawn_owned_process=True)

    def test_update_stops_python_and_node_processes_inside_up_runtime_before_setup(self) -> None:
        self._run_handoff(fail=False, spawn_up_runtime_processes=True)

    def test_update_stops_owned_process_when_cim_scan_is_unavailable(self) -> None:
        self._run_handoff(
            fail=False,
            spawn_owned_process=True,
            disable_cim_process_scan=True,
        )

    def test_update_stops_owned_process_when_cim_scan_hits_low_memory(self) -> None:
        self._run_handoff(
            fail=False,
            spawn_owned_process=True,
            fail_cim_process_scan=True,
        )

    def test_successful_update_uses_direct_stop_when_taskkill_hits_low_memory(self) -> None:
        self._run_handoff(
            fail=False,
            spawn_owned_process=True,
            inject_taskkill_failure=True,
        )

    def test_failed_installer_process_is_stopped_before_rollback(self) -> None:
        self._run_handoff(fail=True, spawn_installer_owned_process=True)

    def test_failed_update_restores_application_and_data_when_taskkill_fails(self) -> None:
        marker_path, _, install_root = self._run_handoff(
            fail=True,
            spawn_installer_owned_process=True,
            inject_taskkill_failure=True,
        )

        with open(os.path.join(os.path.dirname(marker_path), "update-failed.json"), "r", encoding="utf-8-sig") as handle:
            marker = json.load(handle)
        self.assertEqual(marker["rollbackState"], "restored")
        with open(os.path.join(install_root, "LOOM.exe"), "rb") as handle:
            self.assertEqual(handle.read(), b"old")

    def test_failed_update_restores_data_when_all_process_cleanup_fails(self) -> None:
        marker_path, _, install_root = self._run_handoff(
            fail=True,
            spawn_installer_owned_process=True,
            inject_taskkill_failure=True,
            inject_direct_stop_failure=True,
        )

        with open(os.path.join(os.path.dirname(marker_path), "update-failed.json"), "r", encoding="utf-8-sig") as handle:
            marker = json.load(handle)
        self.assertEqual(marker["rollbackState"], "failed")
        self.assertIn("application restore failed", marker["rollbackError"])
        with open(os.path.join(install_root, "data", "nested", "lead.json"), "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"lead":"preserve-me"}')

    def test_successful_update_restores_data_and_clears_pending_marker(self) -> None:
        marker_path, recovery_root, install_root = self._run_handoff(fail=False)

        self.assertFalse(os.path.exists(marker_path))
        self.assertTrue(os.path.isfile(os.path.join(recovery_root, "data", "nested", "lead.json")))
        self.assertTrue(os.path.isfile(os.path.join(install_root, "installed-version.txt")))
        self.assertTrue(os.path.isfile(os.path.join(recovery_root, "update-success.json")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(recovery_root), "previous-success")))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(recovery_root), "other-install-success")))

    def test_failed_update_restores_data_and_leaves_recovery_manifest(self) -> None:
        marker_path, recovery_root, install_root = self._run_handoff(fail=True)

        self.assertFalse(os.path.exists(marker_path))
        failure_marker = os.path.join(os.path.dirname(marker_path), "update-failed.json")
        self.assertTrue(os.path.isfile(failure_marker))
        with open(failure_marker, "r", encoding="utf-8-sig") as handle:
            marker = json.load(handle)
        self.assertEqual(marker["state"], "failed")
        self.assertEqual(marker["version"], "2.1.62")
        self.assertEqual(marker["rollbackState"], "restored")
        self.assertTrue(marker["oldVersionLaunchable"])
        self.assertTrue(os.path.isdir(os.path.join(recovery_root, "application")))
        with open(os.path.join(install_root, "LOOM.exe"), "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        with open(os.path.join(install_root, "old-runtime.txt"), "rb") as handle:
            self.assertEqual(handle.read(), b"old-runtime")
        self.assertFalse(os.path.exists(os.path.join(install_root, "new-only.txt")))
        self.assertFalse(os.path.exists(os.path.join(install_root, "installed-version.txt")))
        self.assertTrue(os.path.isfile(os.path.join(recovery_root, "update-handoff.log")))

    def test_new_version_health_failure_restores_old_application(self) -> None:
        marker_path, recovery_root, install_root = self._run_handoff(fail=False, health_fail=True)

        self.assertFalse(os.path.exists(marker_path))
        with open(os.path.join(install_root, "LOOM.exe"), "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        self.assertFalse(os.path.exists(os.path.join(install_root, "installed-version.txt")))
        failure_marker = os.path.join(os.path.dirname(marker_path), "update-failed.json")
        with open(failure_marker, "r", encoding="utf-8-sig") as handle:
            marker = json.load(handle)
        self.assertEqual(marker["rollbackState"], "restored")
        self.assertTrue(marker["oldVersionLaunchable"])
        self.assertFalse(os.path.exists(os.path.join(recovery_root, "update-success.json")))

    def test_new_version_late_health_failure_restores_old_application(self) -> None:
        marker_path, recovery_root, install_root = self._run_handoff(
            fail=False,
            health_late_fail=True,
        )

        self.assertFalse(os.path.exists(marker_path))
        with open(os.path.join(install_root, "LOOM.exe"), "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        self.assertFalse(os.path.exists(os.path.join(recovery_root, "update-success.json")))

    def test_recovery_only_mode_restores_an_interrupted_update(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix="loom-update-interrupted-")
        self.addCleanup(shutil.rmtree, temp_dir, True)
        install_root = os.path.join(temp_dir, "LOOM")
        recovery_root = os.path.join(temp_dir, "recovery")
        marker_path = os.path.join(temp_dir, "state", "update-pending.json")
        app_exe = os.path.join(install_root, "LOOM.exe")
        os.makedirs(os.path.join(install_root, "data"), exist_ok=True)
        os.makedirs(os.path.join(recovery_root, "application"), exist_ok=True)
        os.makedirs(os.path.join(recovery_root, "data"), exist_ok=True)
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(app_exe, "wb") as handle:
            handle.write(b"partial-new")
        with open(os.path.join(install_root, "data", "new.json"), "w", encoding="utf-8") as handle:
            handle.write("new")
        with open(os.path.join(recovery_root, "application", "LOOM.exe"), "wb") as handle:
            handle.write(b"old")
        with open(os.path.join(recovery_root, "data", "old.json"), "w", encoding="utf-8") as handle:
            handle.write("old")
        with open(marker_path, "w", encoding="utf-8") as handle:
            json.dump({"state": "installing", "installRoot": install_root}, handle)

        completed = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", HANDOFF,
                "-Installer", os.path.join(temp_dir, "unused.exe"),
                "-InstallRoot", install_root,
                "-AppExe", app_exe,
                "-RecoveryRoot", recovery_root,
                "-MarkerPath", marker_path,
                "-ParentPid", "0",
                "-Version", "2.1.90",
                "-RecoveryOnly",
                "-TestMode",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertFalse(os.path.exists(marker_path))
        with open(app_exe, "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        self.assertTrue(os.path.isfile(os.path.join(install_root, "data", "old.json")))
        self.assertFalse(os.path.exists(os.path.join(install_root, "data", "new.json")))

    def test_recovery_directory_inside_install_root_is_rejected_before_setup(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix="loom-update-path-guard-")
        self.addCleanup(shutil.rmtree, temp_dir, True)
        install_root = os.path.join(temp_dir, "LOOM")
        recovery_root = os.path.join(install_root, "unsafe-recovery")
        marker_path = os.path.join(temp_dir, "state", "update-pending.json")
        os.makedirs(install_root, exist_ok=True)
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        app_exe = os.path.join(install_root, "LOOM.exe")
        with open(app_exe, "wb") as handle:
            handle.write(b"old")
        data_dir = os.path.join(install_root, "data")
        os.makedirs(data_dir, exist_ok=True)
        data_sentinel = os.path.join(data_dir, "must-survive.json")
        with open(data_sentinel, "w", encoding="utf-8") as handle:
            handle.write("preserved")
        installer = os.path.join(temp_dir, "must-not-run.cmd")
        with open(installer, "w", encoding="ascii", newline="") as handle:
            handle.write('@echo new>"%~dp0installer-ran.txt"\r\nexit /b 0\r\n')

        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                HANDOFF,
                "-Installer",
                installer,
                "-InstallRoot",
                install_root,
                "-AppExe",
                app_exe,
                "-RecoveryRoot",
                recovery_root,
                "-MarkerPath",
                marker_path,
                "-ParentPid",
                "2147483647",
                "-Version",
                "2.1.90",
                "-TestMode",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr or completed.stdout)
        with open(app_exe, "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        with open(data_sentinel, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "preserved")
        self.assertFalse(os.path.exists(os.path.join(temp_dir, "installer-ran.txt")))
        self.assertFalse(os.path.exists(marker_path))
        failure_marker = os.path.join(os.path.dirname(marker_path), "update-failed.json")
        with open(failure_marker, "r", encoding="utf-8-sig") as handle:
            marker = json.load(handle)
        self.assertEqual(marker["state"], "failed")
        self.assertEqual(marker["rollbackState"], "not_available")
        self.assertTrue(marker["oldVersionLaunchable"])


if __name__ == "__main__":
    unittest.main()
