from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TAURI_CONFIG = os.path.join(ROOT, "src-tauri", "tauri.conf.json")
TAURI_LIB = os.path.join(ROOT, "src-tauri", "src", "lib.rs")
INSTALLER_HOOKS = os.path.join(ROOT, "src-tauri", "installer", "upgrade-hooks.nsh")
HANDOFF_SCRIPT = os.path.join(ROOT, "src-tauri", "installer", "update-handoff.ps1")
INSTALLER_PROCESS_CLEANUP = os.path.join(ROOT, "src-tauri", "installer", "stop-owned-install-processes.ps1")
UPDATE_RELEASE_SCRIPT = os.path.join(ROOT, "scripts", "prepare-desktop-update-release.ps1")
UPDATE_SIGNER_SCRIPT = os.path.join(ROOT, "scripts", "sign-desktop-update.py")
UPDATE_BRAND_CONFIG_SCRIPT = os.path.join(
    ROOT, "scripts", "prepare-brand-update-config.py"
)
POWERSHELL_HOST = shutil.which("pwsh") or shutil.which("powershell")


class LosslessUpdateContractTests(unittest.TestCase):
    def test_update_release_preparation_canonicalizes_and_hashes_the_installer(self) -> None:
        self.assertTrue(os.path.isfile(UPDATE_RELEASE_SCRIPT))
        with open(UPDATE_RELEASE_SCRIPT, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn('[string]$FilePrefix = "LOOM"', source)
        self.assertIn('"$FilePrefix-$Version-setup.exe"', source)
        self.assertIn("Get-FileHash", source)
        self.assertIn("Get-AuthenticodeSignature", source)
        self.assertIn("NotSigned", source)
        self.assertIn(".sha256.txt", source)

    def test_update_release_preparation_emits_a_required_loom_signature_manifest(self) -> None:
        with open(UPDATE_RELEASE_SCRIPT, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("LOOM_DESKTOP_UPDATE_PRIVATE_KEY", source)
        self.assertIn('[string]$PublicKeyPath', source)
        self.assertIn('"--public-key"', source)
        self.assertIn(".update.json", source)
        self.assertIn("sign-desktop-update.py", source)
        self.assertIn("updateManifest", source)

    @unittest.skipUnless(
        os.name == "nt" and POWERSHELL_HOST,
        "PowerShell is required",
    )
    def test_update_release_preparation_allows_an_empty_download_url(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        private_key_value = base64.b64encode(
            private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode("ascii")
        public_key_value = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temp_dir:
            source_installer = os.path.join(temp_dir, "source-installer.exe")
            public_key_path = os.path.join(temp_dir, "desktop-update-public-key.txt")
            output_dir = os.path.join(temp_dir, "release")
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            fixture_executable = os.path.join(system_root, "System32", "where.exe")
            self.assertTrue(os.path.isfile(fixture_executable), fixture_executable)
            shutil.copyfile(fixture_executable, source_installer)
            with open(public_key_path, "w", encoding="utf-8") as handle:
                handle.write(public_key_value)
            env = os.environ.copy()
            # PowerShell 7 module paths can prevent Windows PowerShell 5.1 from
            # loading its built-in Microsoft.PowerShell.Security module.
            env.pop("PSModulePath", None)
            env["LOOM_DESKTOP_UPDATE_PRIVATE_KEY"] = private_key_value

            result = subprocess.run(
                [
                    POWERSHELL_HOST,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    UPDATE_RELEASE_SCRIPT,
                    "-InstallerPath",
                    source_installer,
                    "-Version",
                    "2.3.19",
                    "-OutputDirectory",
                    output_dir,
                    "-PublicKeyPath",
                    public_key_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            manifest_path = os.path.join(
                output_dir,
                "LOOM-2.3.19-setup.exe.update.json",
            )
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)

        self.assertNotIn("downloadUrl", manifest)

    def test_desktop_update_signer_binds_the_installer_metadata(self) -> None:
        installer = b"unsigned-but-loom-signed-installer"
        private_key = Ed25519PrivateKey.generate()
        private_key_value = base64.b64encode(
            private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode("ascii")
        public_key_value = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temp_dir:
            installer_path = os.path.join(temp_dir, "LOOM-2.3.19-setup.exe")
            manifest_path = installer_path + ".update.json"
            public_key_path = os.path.join(temp_dir, "desktop-update-public-key.txt")
            with open(installer_path, "wb") as handle:
                handle.write(installer)
            with open(public_key_path, "w", encoding="utf-8") as handle:
                handle.write(public_key_value)
            env = os.environ.copy()
            env["LOOM_DESKTOP_UPDATE_PRIVATE_KEY"] = private_key_value
            result = subprocess.run(
                [
                    sys.executable,
                    UPDATE_SIGNER_SCRIPT,
                    "--installer",
                    installer_path,
                    "--version",
                    "2.3.19",
                    "--output",
                    manifest_path,
                    "--public-key",
                    public_key_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)

        self.assertEqual(manifest["filename"], "LOOM-2.3.19-setup.exe")
        self.assertEqual(manifest["version"], "2.3.19")
        self.assertEqual(manifest["size"], len(installer))
        self.assertEqual(manifest["sha256"], hashlib.sha256(installer).hexdigest())
        signature = base64.b64decode(manifest["signature"]["value"])
        unsigned = dict(manifest)
        unsigned.pop("signature")
        payload = json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        private_key.public_key().verify(signature, payload)

    def test_desktop_update_signer_binds_domestic_download_parts(self) -> None:
        installer = b"segmented-domestic-installer"
        private_key = Ed25519PrivateKey.generate()
        private_key_value = base64.b64encode(
            private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode("ascii")
        public_key_value = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        part = {
            "index": 1,
            "url": "https://gitee.com/example/LOOM-2.3.24-setup.part001",
            "fallbackUrls": [
                "https://github.com/example/LOOM-2.3.24-setup.part001",
            ],
            "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            installer_path = os.path.join(temp_dir, "LOOM-2.3.24-setup.exe")
            manifest_path = installer_path + ".update.json"
            parts_path = os.path.join(temp_dir, "parts.json")
            public_key_path = os.path.join(temp_dir, "desktop-update-public-key.txt")
            with open(installer_path, "wb") as handle:
                handle.write(installer)
            with open(parts_path, "w", encoding="utf-8") as handle:
                json.dump([part], handle)
            with open(public_key_path, "w", encoding="utf-8") as handle:
                handle.write(public_key_value)
            env = os.environ.copy()
            env["LOOM_DESKTOP_UPDATE_PRIVATE_KEY"] = private_key_value
            result = subprocess.run(
                [
                    sys.executable,
                    UPDATE_SIGNER_SCRIPT,
                    "--installer",
                    installer_path,
                    "--version",
                    "2.3.24",
                    "--output",
                    manifest_path,
                    "--public-key",
                    public_key_path,
                    "--download-parts-json",
                    parts_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)

        self.assertEqual(manifest["downloadParts"], [part])
        signature = base64.b64decode(manifest["signature"]["value"])
        unsigned = dict(manifest)
        unsigned.pop("signature")
        private_key.public_key().verify(
            signature,
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    def test_desktop_update_signer_rejects_a_private_key_that_does_not_match_the_client_key(
        self,
    ) -> None:
        signing_key = Ed25519PrivateKey.generate()
        different_key = Ed25519PrivateKey.generate()
        private_key_value = base64.b64encode(
            signing_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode("ascii")
        different_public_key = base64.b64encode(
            different_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temp_dir:
            installer_path = os.path.join(temp_dir, "LOOM-2.3.19-setup.exe")
            manifest_path = installer_path + ".update.json"
            public_key_path = os.path.join(temp_dir, "desktop-update-public-key.txt")
            with open(installer_path, "wb") as handle:
                handle.write(b"installer")
            with open(public_key_path, "w", encoding="utf-8") as handle:
                handle.write(different_public_key)
            env = os.environ.copy()
            env["LOOM_DESKTOP_UPDATE_PRIVATE_KEY"] = private_key_value
            result = subprocess.run(
                [
                    sys.executable,
                    UPDATE_SIGNER_SCRIPT,
                    "--installer",
                    installer_path,
                    "--version",
                    "2.3.19",
                    "--output",
                    manifest_path,
                    "--public-key",
                    public_key_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match", result.stderr)
            self.assertFalse(os.path.exists(manifest_path))

    def test_oem_update_config_contains_only_the_derived_public_key(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        private_key_value = base64.b64encode(
            private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ).decode("ascii")
        expected_public_key = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "desktop-update-brand.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "brandId": "northstar"}, handle)
            env = os.environ.copy()
            env["LOOM_DESKTOP_UPDATE_PRIVATE_KEY"] = private_key_value
            result = subprocess.run(
                [
                    sys.executable,
                    UPDATE_BRAND_CONFIG_SCRIPT,
                    "--config",
                    config_path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            serialized = json.dumps(config, sort_keys=True)

        self.assertEqual(config["publicKey"], expected_public_key)
        self.assertNotIn(private_key_value, serialized)

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
        self.assertIn('post_bridge_shutdown("/api/agent/shutdown").await;', source)
        self.assertLess(
            source.index('post_bridge_shutdown("/api/agent/shutdown").await;'),
            source.index('post_bridge_shutdown("/api/process/stop").await;'),
        )
        self.assertIn("upgrade-backups", source)
        self.assertIn('None => "LOOM"', source)
        self.assertIn("update_recovery_dir_name()", source)
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
        self.assertIn('$runOnceName = "!${safeBrandId}UpdateRecovery"', handoff)
        self.assertIn("Register-UpdateRecoveryRunOnce -Retry", handoff)
        self.assertIn('"Local\\$safeBrandId.Update.Handoff"', handoff)
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
        self.assertIn('format!("{UPDATE_FILE_PREFIX}-")', source)
        self.assertIn("strip_prefix(&expected_prefix)", source)
        self.assertIn('strip_suffix("-setup.exe")', source)
        self.assertIn('command.arg("-Version").arg(&target_version)', source)
        self.assertIn('command.arg("-ReadyPath").arg(&ready_path)', source)
        self.assertIn(
            "command.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)",
            source,
        )
        self.assertIn("if ready_path.is_file()", source)
        self.assertIn("handoff_process.try_wait()", source)
        self.assertIn("app_handle.exit(0)", source)
        self.assertNotIn("Duration::from_millis(1200)", source)
        self.assertIn(
            "shutdown_backend().await;\n                app_handle.exit(0);",
            source,
        )
        self.assertLess(
            source.index("if ready_path.is_file()"),
            source.index("shutdown_backend().await"),
        )
        self.assertIn("Publish-HandoffReady", handoff)
        self.assertIn("$installDirectoryArgument", handoff)
        self.assertIn("-PassThru", handoff)
        self.assertIn("$setupProcess.WaitForExit()", handoff)
        self.assertIn("$setupProcess.ExitCode", handoff)

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
        self.assertNotIn("@(Get-ChildItem", cleanup)
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
