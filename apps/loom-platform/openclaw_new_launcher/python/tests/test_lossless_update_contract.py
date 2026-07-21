from __future__ import annotations

import json
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TAURI_CONFIG = os.path.join(ROOT, "src-tauri", "tauri.conf.json")
TAURI_LIB = os.path.join(ROOT, "src-tauri", "src", "lib.rs")
INSTALLER_HOOKS = os.path.join(ROOT, "src-tauri", "installer", "upgrade-hooks.nsh")
HANDOFF_SCRIPT = os.path.join(ROOT, "src-tauri", "installer", "update-handoff.ps1")
INSTALLER_PROCESS_CLEANUP = os.path.join(ROOT, "src-tauri", "installer", "stop-owned-install-processes.ps1")


class LosslessUpdateContractTests(unittest.TestCase):
    def test_nsis_blocks_downgrades_and_loads_upgrade_hooks(self) -> None:
        with open(TAURI_CONFIG, "r", encoding="utf-8") as handle:
            config = json.load(handle)

        windows = config["bundle"]["windows"]
        self.assertFalse(windows["allowDowngrades"])
        self.assertEqual(windows["nsis"]["installerHooks"], "installer/upgrade-hooks.nsh")

    def test_upgrade_hooks_leave_update_recovery_to_detached_handoff(self) -> None:
        with open(INSTALLER_HOOKS, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("NSIS_HOOK_PREUNINSTALL", source)
        self.assertIn("NSIS_HOOK_POSTINSTALL", source)
        self.assertIn("detached update handoff", source)
        self.assertNotIn("update-pending", source)
        self.assertNotIn("$LOCALAPPDATA\\LOOM", source)
        self.assertNotIn("RMDir /r \"$INSTDIR\\data\"", source)

    def test_tauri_update_handoff_stops_bridge_and_uses_external_recovery_backup(self) -> None:
        with open(TAURI_LIB, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(HANDOFF_SCRIPT, "r", encoding="utf-8") as handle:
            handoff = handle.read()

        self.assertIn("prepare_update_install", source)
        self.assertIn("shutdown_backend().await", source)
        self.assertIn("upgrade-backups", source)
        self.assertIn("LOOM-Update-Recovery", source)
        self.assertIn("update-pending", source)
        self.assertIn("/D=", handoff)
        self.assertIn("LOOM_UPDATE_TEST_MODE", source)
        self.assertIn("Copy-DataTree", handoff)
        self.assertIn("Copy-ApplicationTree", handoff)
        self.assertIn("Restore-ApplicationTree", handoff)
        self.assertIn('rollbackState = "restored"', handoff)
        self.assertIn("oldVersionLaunchable", handoff)
        self.assertIn("Stop-OwnedInstallProcesses", handoff)
        self.assertNotIn("Stop-ManagedProcessTrees", handoff)
        self.assertNotIn("ManagedProcessIds", handoff)
        self.assertIn("Get-CimInstance Win32_Process", handoff)
        self.assertIn("Get-Process -Id $_.ProcessId", handoff)
        self.assertIn("Get-CommandExecutablePath", handoff)
        self.assertIn("LoomExecutablePath", handoff)
        self.assertNotIn("$commandOwned", handoff)
        self.assertIn("LOOM_UPDATE_HEALTH_MARKER", handoff)
        self.assertIn("LOOM_UPDATE_HEALTH_NONCE", handoff)
        self.assertIn("Prune-SuccessfulRecoveryBackups", handoff)
        self.assertIn("RecoveryOnly", handoff)
        self.assertIn("Register-UpdateRecoveryRunOnce", handoff)
        self.assertIn('$runOnceName = "!LOOMUpdateRecovery"', handoff)
        self.assertIn("Register-UpdateRecoveryRunOnce -Retry", handoff)
        self.assertIn('"Local\\LOOM.Update.Handoff"', handoff)
        self.assertIn("Backup-InstallerRegistryState", handoff)
        self.assertIn("Restore-InstallerRegistryState", handoff)
        self.assertIn("Restore-DataTree", handoff)
        self.assertIn("if ($dataBackupComplete)", handoff)
        self.assertIn("if ($registryBackupComplete)", handoff)
        self.assertIn("withdrew health confirmation", handoff)
        self.assertIn("ReparsePoint", handoff)
        self.assertIn("update-success.json", handoff)
        self.assertIn("update-failed.json", handoff)
        self.assertIn("acknowledge_update_health", source)
        self.assertNotIn('command.arg("-ManagedProcessIds")', source)
        self.assertIn("UPDATE_HANDOFF_STARTED", source)
        self.assertIn("compare_exchange", source)
        self.assertIn("CreateMutexW", source)
        self.assertIn("std::os::windows::io::OwnedHandle", source)
        self.assertIn("as_millis", source)
        self.assertIn("bridge did not accept connections", source)
        self.assertIn("invalidate_update_health_marker", source)
        self.assertIn("bridge health was not stable", source)
        self.assertIn('strip_prefix("LOOM-")', source)
        self.assertIn('strip_suffix("-setup.exe")', source)
        self.assertIn('command.arg("-Version").arg(&target_version)', source)

    def test_installer_hooks_never_kill_processes_by_global_image_name(self) -> None:
        with open(INSTALLER_HOOKS, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("NSIS_HOOK_PREINSTALL", source)
        self.assertIn("NSIS_HOOK_PREUNINSTALL", source)
        self.assertNotIn('/IM LOOM.exe', source)
        self.assertNotIn('/IM python.exe', source)
        self.assertNotIn('/IM node.exe', source)

    def test_direct_installer_stops_only_processes_owned_by_install_root(self) -> None:
        with open(INSTALLER_HOOKS, "r", encoding="utf-8") as handle:
            hooks = handle.read()
        with open(INSTALLER_PROCESS_CLEANUP, "r", encoding="utf-8") as handle:
            cleanup = handle.read()

        self.assertIn("stop-owned-install-processes.ps1", hooks)
        self.assertIn("ExecWait", hooks)
        self.assertIn("-InstallRoot", hooks)
        self.assertIn("Sysnative\\WindowsPowerShell", hooks)
        self.assertIn("Abort", hooks)
        self.assertNotIn("Get-CimInstance Win32_Process", cleanup)
        self.assertIn("Get-Process -ErrorAction", cleanup)
        self.assertIn("Get-Process -Id $ProcessId", cleanup)
        self.assertIn("[System.IO.Path]::GetFullPath", cleanup)
        self.assertIn("StartsWith", cleanup)
        self.assertIn("Stop-Process -Id", cleanup)
        self.assertIn("Invoke-TaskKillProcessTree", cleanup)
        self.assertIn("/T /PID", cleanup)
        self.assertIn("$emptyScans", cleanup)
        self.assertIn("$emptyScans -ge 5", cleanup)
        self.assertIn("Test-OwnedRuntimeFilesUnlocked", cleanup)
        self.assertIn("installer-process-cleanup.log", cleanup)
        self.assertNotIn("Get-Process -Name", cleanup)
        self.assertNotIn("/IM python.exe", cleanup)
        self.assertNotIn("/IM node.exe", cleanup)

    def test_installer_hooks_do_not_use_global_update_staging(self) -> None:
        with open(INSTALLER_HOOKS, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("upgrade-staging", source)
        self.assertNotIn("update-pending.json", source)

    def test_installer_hooks_do_not_clean_registry_after_maintenance_decision(self) -> None:
        with open(INSTALLER_HOOKS, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("RemoveStaleLoomRegistryEntries", source)
        self.assertNotIn("Get-ItemProperty", source)
        self.assertNotIn("-EncodedCommand", source)


if __name__ == "__main__":
    unittest.main()
