from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest


LAUNCHER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_ROOT = os.path.dirname(LAUNCHER_ROOT)
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
LAUNCHER_SCRIPTS_DIR = os.path.join(LAUNCHER_ROOT, "scripts")
PACKAGE_JSON = os.path.join(LAUNCHER_ROOT, "package.json")
TAURI_CONFIG = os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.conf.json")
TAURI_PROTECTED_CONFIG = os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.protected.conf.json")


def read_script(name: str) -> str:
    with open(os.path.join(SCRIPTS_DIR, name), "r", encoding="utf-8-sig") as handle:
        return handle.read()


def read_launcher_script(name: str) -> str:
    with open(os.path.join(LAUNCHER_SCRIPTS_DIR, name), "r", encoding="utf-8-sig") as handle:
        return handle.read()


class ReleaseScriptsContractTests(unittest.TestCase):
    def test_build_stages_complete_bundled_platform_tools_before_tauri_packaging(self) -> None:
        source = read_launcher_script("build-platform-tools.ps1")
        with open(PACKAGE_JSON, "r", encoding="utf-8-sig") as handle:
            package_source = handle.read()
        with open(TAURI_CONFIG, "r", encoding="utf-8-sig") as handle:
            tauri_source = handle.read()
        with open(TAURI_PROTECTED_CONFIG, "r", encoding="utf-8-sig") as handle:
            protected_source = handle.read()

        for marker in (
            "LOOM_ADB",
            "ANDROID_SDK_ROOT",
            "ANDROID_HOME",
            "_up_\\redist\\platform-tools",
            "adb.exe",
            "AdbWinApi.dll",
            "AdbWinUsbApi.dll",
            "NOTICE.txt",
            "Refusing to package LOOM without a complete bundled Android platform-tools directory",
        ):
            self.assertIn(marker, source)
        self.assertIn('"build:platform-tools"', package_source)
        self.assertIn("npm run build:platform-tools &&", tauri_source)
        self.assertIn("npm run build:platform-tools &&", protected_source)

    def test_dual_nsis_script_declares_validate_only_and_distinct_outputs(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("CodexPackagePath", source)
        self.assertIn("OutputRoot", source)
        self.assertIn("ValidateOnly", source)
        self.assertIn("-online-setup.exe", source)
        self.assertIn("-complete-setup.exe", source)
        self.assertIn(".sha256.txt", source)

    def test_dual_nsis_script_parses_manifest_and_validates_codex_seed(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("release-manifest.json", source)
        self.assertIn("ConvertFrom-Json", source)
        self.assertIn('component.id -eq "codex-desktop"', source)
        self.assertIn("Get-FileHash", source)
        self.assertIn("$codexComponent.size", source)
        self.assertIn("$codexComponent.sha256", source)

    def test_dual_nsis_script_builds_online_before_seed_injection_and_cleans_up_in_finally(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("try {", source)
        self.assertIn("finally {", source)
        self.assertIn("redist\\components\\codex-desktop", source)
        self.assertIn('@("run", "tauri", "--", "build", "--bundles", "nsis")', source)
        self.assertIn("--config", source)
        self.assertIn("function Initialize-MsvcBuildEnvironment", source)
        self.assertIn("VsDevCmd.bat", source)
        self.assertIn("Initialize-MsvcBuildEnvironment", source)
        self.assertLess(
            source.index('Build-InstallerVariant -VariantName "online"'),
            source.index('Copy-Item -LiteralPath $resolvedCodexPackagePath -Destination $seedPackagePath -Force'),
        )
        self.assertLess(
            source.index('Copy-Item -LiteralPath $resolvedCodexPackagePath -Destination $seedPackagePath -Force'),
            source.index('Build-InstallerVariant -VariantName "complete"'),
        )
        self.assertIn("Remove-Item -LiteralPath $seedPackagePath -Force", source)

    def test_dual_nsis_script_preserves_existing_release_outputs(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertNotIn("Remove-Item -LiteralPath $OutputRoot -Recurse", source)
        self.assertNotIn("Remove-Item -Path $OutputRoot -Recurse", source)
        self.assertIn("Installer output already exists", source)
        self.assertNotIn("Copy-Item -LiteralPath $builtInstaller.FullName -Destination $variantOutputPath -Force", source)

    def test_dual_nsis_script_rejects_unsafe_output_roots(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("function Assert-SafeOutputRoot", source)
        self.assertIn("$Root", source)
        self.assertIn("$LauncherDir", source)
        self.assertIn('"release"', source)
        self.assertIn('"openclaw_new_launcher"', source)
        self.assertIn("Refusing unsafe OutputRoot", source)

    def test_dual_nsis_validate_only_does_not_create_or_modify_outputs(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn('if ($ValidateOnly) {', source)
        self.assertIn('Write-Host "Validated Codex package and dual NSIS build inputs."', source)
        self.assertLess(
            source.index('if ($ValidateOnly) {'),
            source.index('New-Item -ItemType Directory -Path $resolvedOutputRoot -Force'),
        )

    def test_dual_nsis_checks_output_collisions_before_building(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("function Assert-OutputPathAvailable", source)
        self.assertIn("Assert-OutputPathAvailable -Path $onlineOutputPath", source)
        self.assertIn("Assert-OutputPathAvailable -Path $completeOutputPath", source)
        self.assertIn("Assert-OutputPathAvailable -Path $recommendedOutputPath", source)
        self.assertIn("Test-Path -LiteralPath $Path", source)

    def test_dual_nsis_publishes_complete_variant_as_unambiguous_recommended_setup(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn('$recommendedOutputPath = Join-Path $resolvedOutputRoot "$packagePrefix-$launcherVersion-setup.exe"', source)
        self.assertIn('Copy-Item -LiteralPath $completeOutputPath -Destination $recommendedOutputPath', source)
        self.assertIn('Write-InstallerHash -Path $recommendedOutputPath', source)

    def test_dual_nsis_can_require_a_valid_authenticode_signature(self) -> None:
        source = read_script("build-dual-nsis.ps1")

        self.assertIn("RequireCodeSignature", source)
        self.assertIn("CertificateThumbprint", source)
        self.assertIn("Get-AuthenticodeSignature", source)
        self.assertIn('signature.Status -ne "Valid"', source)

    def test_measure_installer_performance_script_reports_budgets_and_performance_gates(self) -> None:
        source = read_launcher_script("measure-installer-performance.ps1")

        self.assertIn("PrerequisiteBudgetMs", source)
        self.assertIn("CodexBudgetMs", source)
        self.assertIn("ValidateOnly", source)
        self.assertIn("Simulate", source)
        self.assertIn('"prerequisiteMs"', source)
        self.assertIn('"codexDetectMs"', source)
        self.assertIn('"appxCalls"', source)
        self.assertIn('"npmCalls"', source)
        self.assertIn('"performanceGate"', source)
        self.assertIn('"onlinePerformanceGate"', source)
        self.assertIn('"completePerformanceGate"', source)
        self.assertIn('"releaseValidation"', source)
        self.assertIn("diagnose_prerequisites()", source)
        self.assertIn("installer.detect(codex_component", source)

    def test_measure_installer_performance_script_validate_only_checks_dual_nsis_inputs_only(self) -> None:
        source = read_launcher_script("measure-installer-performance.ps1")

        self.assertIn('if ($ValidateOnly) {', source)
        self.assertIn("build-dual-nsis.ps1", source)
        self.assertIn("-ValidateOnly", source)
        self.assertIn("dual-nsis-validateonly-failed", source)
        self.assertIn("Resolve-CodexPackagePath", source)
        self.assertIn("Input validation only runs when measure-installer-performance.ps1 is called with -ValidateOnly.", source)
        self.assertIn('$result.releaseValidation = [pscustomobject]@{', source)

    def test_measure_installer_performance_script_avoids_real_release_side_effects(self) -> None:
        source = read_launcher_script("measure-installer-performance.ps1")

        self.assertNotIn("publish-gitee-release.ps1", source)
        self.assertNotIn("verify-newapi-account.ps1", source)
        self.assertNotIn("Invoke-WebRequest", source)
        self.assertNotIn("Start-BitsTransfer", source)
        self.assertNotIn("upload", source.lower())

    def test_measure_installer_performance_script_validates_tar_members_before_extracting(self) -> None:
        source = read_launcher_script("measure-installer-performance.ps1")

        self.assertIn("def _validate_archive_members", source)
        self.assertIn("pathlib.PurePosixPath", source)
        self.assertIn('if ".." in pure_member.parts:', source)
        self.assertIn("os.path.commonpath([install_root, destination_path]) != install_root", source)
        self.assertLess(
            source.index("_validate_archive_members(archive, install_path)"),
            source.index("archive.extractall(install_path)"),
        )

    def test_online_installer_requires_package_inputs_instead_of_old_defaults(self) -> None:
        source = read_script("build-online-exe-installer.ps1")

        self.assertIn("[Parameter(Mandatory = $true)]", source)
        self.assertNotIn("LOOM-Online-v2.1.21-20260629-rc3.zip", source)
        self.assertNotIn("744734BBA7542C49CF95C154D898B2B9D08596331DA8F306DAF3804D537CCB6D", source)
        self.assertRegex(source, r"if \(\$PackageRootName -notmatch \[regex\]::Escape\(\$Version\)")

    def test_online_installer_blocks_non_loom_non_empty_target_dirs(self) -> None:
        source = read_script("build-online-exe-installer.ps1")

        self.assertIn("IsRecognizedLoomInstallDirectory", source)
        self.assertIn("DirectoryContainsUserFiles", source)
        self.assertIn("\\u76ee\\u6807\\u76ee\\u5f55\\u4e0d\\u662f LOOM \\u5b89\\u88c5\\u76ee\\u5f55", source)
        self.assertIn("LOOMFiles", source)

    def test_online_package_rewrites_runtime_package_name(self) -> None:
        source = read_script("build-online-portable.ps1")

        self.assertIn("Update-LauncherRuntimePackageName", source)
        self.assertIn("launcher_runtime.json", source)
        self.assertIn("packageName", source)

    def test_verify_release_checks_online_runtime_package_name(self) -> None:
        source = read_script("verify-release.ps1")

        self.assertIn("launcher_runtime.json packageName mismatch", source)
        self.assertRegex(source, re.escape("$script:LauncherRuntimePackageName") + r"\s+-ne\s+\$packageName")

    def test_verify_release_blocks_runtime_state_and_logs(self) -> None:
        source = read_script("verify-release.ps1")

        self.assertIn("member-session\\.json", source)
        self.assertIn("wire-current\\.json", source)
        self.assertIn("agent-model-configs", source)
        self.assertIn("data/logs/.*\\.(log|jsonl)", source)

    def test_portable_build_cleans_runtime_state_after_smoke(self) -> None:
        source = read_script("build-portable.ps1")

        self.assertIn("function Remove-PortableRuntimeStateArtifacts", source)
        self.assertIn("data\\.openclaw\\launcher\\member-session.json", source)
        self.assertIn("data\\.openclaw\\launcher\\wire-current.json", source)
        self.assertIn("data\\logs", source)
        self.assertRegex(source, r"Remove-PortableRuntimeStateArtifacts\s+-PackageDir\s+\$payloadDir")

    def test_portable_smoke_rejects_runtime_state(self) -> None:
        source = read_script("verify-portable-smoke.ps1")

        self.assertIn("data\\.openclaw\\launcher\\member-session.json", source)
        self.assertIn("data\\.openclaw\\launcher\\wire-current.json", source)
        self.assertIn("data\\logs\\bridge-service.log", source)

    def test_secret_scan_ignores_generated_runtimes_but_allows_known_library_examples(self) -> None:
        source = read_script("verify-release-secrets.ps1")

        self.assertIn("openclaw_new_launcher/(?:node-runtime|python-runtime)", source)
        self.assertIn("_up_/python-runtime/Lib/site-packages/PIL/ImageFont.py", source)
        self.assertIn(
            "_up_/python-runtime/Lib/site-packages/cryptography/hazmat/primitives/serialization/ssh.py",
            source,
        )
        self.assertIn(
            "_up_/node-runtime/node_modules/npm/node_modules/@npmcli/config/lib/definitions/definitions.js",
            source,
        )

    def test_secret_scan_rejects_an_empty_target_set(self) -> None:
        source = read_script("verify-release-secrets.ps1")

        self.assertIn("No secret scan targets were selected", source)
        self.assertIn("if ($targets.Count -eq 0", source)

    def test_secret_scan_includes_explicit_text_file_targets(self) -> None:
        source = read_script("verify-release-secrets.ps1")

        self.assertIn("function Add-FileTarget", source)
        self.assertIn("Add-FileTarget -InputPath $item.FullName -Targets $targets", source)

    def test_secret_scan_redacts_detected_secret_values_from_output(self) -> None:
        fake_secret = "sk-" + ("A" * 40)
        script_path = os.path.join(SCRIPTS_DIR, "verify-release-secrets.ps1")
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = os.path.join(temp_dir, "secret.txt")
            with open(fixture, "w", encoding="utf-8") as handle:
                handle.write(fake_secret)
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script_path,
                    "-Path",
                    fixture,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        output = f"{result.stdout}\n{result.stderr}"
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(fake_secret, output)
        self.assertIn("[REDACTED]", output)

    def test_portable_package_keeps_scripts_declared_by_package_json(self) -> None:
        build_source = read_script("build-portable.ps1")
        smoke_source = read_script("verify-portable-smoke.ps1")
        verify_source = read_script("verify-release.ps1")
        legacy_match = re.search(
            r"function Remove-LegacyScriptArtifacts \{(?P<body>.*?)\n\}",
            build_source,
            flags=re.S,
        )
        self.assertIsNotNone(legacy_match)
        legacy_body = legacy_match.group("body")

        self.assertNotIn("scripts\\openclaw-publish-phone.mjs", legacy_body)
        self.assertNotIn("scripts\\openclaw-publish-relay.mjs", legacy_body)
        self.assertIn('"phone:publish"', build_source)
        self.assertIn("Assert-PackageScriptsResolve", smoke_source)
        self.assertIn("scripts\\openclaw-publish-phone.mjs", smoke_source)
        self.assertIn("scripts\\openclaw-publish-relay.mjs", smoke_source)
        self.assertNotIn("openclaw-publish-(phone|relay|relay-check|relay-smoke)", verify_source)

    def test_gitee_publish_supports_dpapi_token_file(self) -> None:
        publish_source = read_script("publish-gitee-release.ps1")
        token_source = read_script("set-gitee-token.ps1")

        self.assertIn("gitee-token.dpapi", publish_source)
        self.assertIn("Read-GiteeTokenFromFile", publish_source)
        self.assertIn("set-gitee-token.ps1", publish_source)
        self.assertIn("Read-Host", token_source)
        self.assertIn("-AsSecureString", token_source)
        self.assertIn("ConvertFrom-SecureString", token_source)
        self.assertNotRegex(token_source, r"[0-9a-f]{32,}")

    def test_gitee_publish_uses_urlencoded_post_for_release_creation(self) -> None:
        publish_source = read_script("publish-gitee-release.ps1")

        self.assertIn("function New-GiteeRelease", publish_source)
        release_function = re.search(
            r"function New-GiteeRelease \{(?P<body>.*?)\n\}",
            publish_source,
            flags=re.S,
        )
        self.assertIsNotNone(release_function)
        self.assertIn('Invoke-GiteeApi -Method "POST"', release_function.group("body"))
        self.assertNotIn("Invoke-GiteeFormPost", release_function.group("body"))
        self.assertIn("curl.exe", publish_source)
        self.assertIn("releases?page=1&per_page=100", publish_source)


if __name__ == "__main__":
    unittest.main()
