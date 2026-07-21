import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "smoke-test-tauri-nsis.ps1")
UPGRADE_HOOK_PATH = os.path.join(REPO_ROOT, "openclaw_new_launcher", "src-tauri", "installer", "upgrade-hooks.nsh")


class NsisSmokeScriptContractTests(unittest.TestCase):
    def test_preinstall_cleans_managed_code_without_deleting_customer_data(self) -> None:
        with open(UPGRADE_HOOK_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        preinstall = source.split("!macro NSIS_HOOK_PREINSTALL", 1)[1].split("!macroend", 1)[0]
        for managed_path in (
            'RMDir /r "$INSTDIR\\_up_\\python"',
            'RMDir /r "$INSTDIR\\_up_\\scripts"',
            'RMDir /r "$INSTDIR\\python"',
            'RMDir /r "$INSTDIR\\scripts"',
        ):
            self.assertIn(managed_path, preinstall)
        self.assertNotIn('RMDir /r "$INSTDIR\\data"', preinstall)

    def test_smoke_script_is_transactional_and_checks_packaged_bridge(self) -> None:
        self.assertTrue(os.path.exists(SCRIPT_PATH), "NSIS smoke script is missing")
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        for marker in (
            "Assert-ChildPath",
            "try {",
            "finally {",
            "Rename-Item -LiteralPath $legacyKey",
            "Rename-Item -LiteralPath $backupKey",
            "_up_\\python-runtime\\python.exe",
            "_up_\\node-runtime\\node.exe",
            "nodeRuntime = \"packaged\"",
            'componentIds = @("codex-desktop", "claude-code", "opencode", "openclaw-companion", "hermes")',
            "/api/components/status",
            'session.impl -ne "fastapi"',
            "/api/license/current",
            "/api/matrix/status",
            "/api/matrix/acquisition",
            "matrixStatus -ne 403",
            "acquisitionStatus -ne 403",
            "verify-release-secrets.ps1",
            "-SecretScanPath $resolvedSecretScanScript",
            "Remove-Item -LiteralPath $sessionPath -Force",
            "LicenseCodeFile",
            "Test-OnlineLicensePersistence",
            "ConvertTo-CommandLineArgument",
            "$quotedArguments",
            "/api/license/activate",
            'status -ne "authorized"',
            "commercialFeatures",
            "authorizedMatrixEndpoint",
            "build_agent_launcher_environment",
            'environment["CODEX_HOME"]',
            'expected_language = "\\u9ed8\\u8ba4',
            'codexDefaultLanguage = "zh-CN"',
            "Initialize-LegacyManagedPayload",
            "legacy-fastapi-route-shadow",
            "api.fastapi_routes.__file__",
            "/api/agent/bootstrap",
            "from services.agent_service import AgentService",
            "agent_service.bootstrap()",
            'agent_bootstrap.get("defaultRuntimeProfileId") != "loom-native"',
            'len(agent_bootstrap.get("capabilities", [])) <= 0',
            "/api/matrix/devices/{device_id}/screen",
            'packagedRouteModules = "protected"',
            "upgradeDataPreserved",
        ):
            self.assertIn(marker, source)

    def test_smoke_script_does_not_print_bridge_token(self) -> None:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("ConvertTo-Json $session", source)
        self.assertNotIn("Write-Output $session.token", source)

    def test_smoke_script_quotes_process_arguments_for_space_paths(self) -> None:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("function ConvertTo-CommandLineArgument", source)
        self.assertIn('$quotedArguments = ($Arguments | ForEach-Object', source)
        self.assertIn('$startParameters["ArgumentList"] = $quotedArguments', source)
        self.assertIn('[string]$RawArguments = ""', source)
        self.assertIn('-RawArguments "/S /D=$installPath"', source)

    def test_smoke_script_falls_back_when_cim_process_lookup_is_unavailable(self) -> None:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("function Get-ProcessExecutablePath", source)
        self.assertIn("Get-Process -Id $ProcessId -ErrorAction Stop", source)
        self.assertIn("Get-ProcessExecutablePath -ProcessId $bridgePid", source)
        self.assertIn("Get-Process -Name LOOM -ErrorAction SilentlyContinue", source)

    def test_smoke_script_hides_legacy_uninstall_keys_before_install(self) -> None:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("$legacyProductNames", source)
        self.assertIn("$legacyChineseProductName", source)
        self.assertIn("0x9e93", source)
        self.assertIn('"LOOM"', source)
        self.assertIn("foreach ($legacyProductName in $legacyProductNames)", source)
        self.assertIn(".__codex_release_smoke_$PID", source)
        self.assertIn("Rename-Item -LiteralPath $legacyKey", source)
        self.assertIn("Rename-Item -LiteralPath $backupKey", source)

    def test_smoke_script_resolves_default_secret_scan_after_param_binding(self) -> None:
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn('[string]$SecretScanScript = ""', source)
        self.assertIn('Join-Path $PSScriptRoot "verify-release-secrets.ps1"', source)
        param_end = source.index("$ErrorActionPreference")
        self.assertNotIn("Join-Path $PSScriptRoot", source[:param_end])


if __name__ == "__main__":
    unittest.main()
