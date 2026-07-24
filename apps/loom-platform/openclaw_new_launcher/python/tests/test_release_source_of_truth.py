from __future__ import annotations

import base64
import json
import os
import re
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER_ROOT = os.path.dirname(PYTHON_DIR)
PLATFORM_ROOT = os.path.dirname(LAUNCHER_ROOT)
MONOREPO_ROOT = os.path.dirname(os.path.dirname(PLATFORM_ROOT))
CI_WORKFLOW = os.path.join(MONOREPO_ROOT, ".github", "workflows", "platform-ci.yml")
RELEASE_WORKFLOW = os.path.join(MONOREPO_ROOT, ".github", "workflows", "platform-release.yml")
CI_SCRIPT = os.path.join(PLATFORM_ROOT, "scripts", "ci-check.ps1")
SMOKE_SCRIPT = os.path.join(PLATFORM_ROOT, "scripts", "smoke-test-tauri-nsis.ps1")
PROTECTED_TAURI_CONFIG = os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.protected.conf.json")
TAURI_CONFIG = os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.conf.json")
DESKTOP_UPDATE_PUBLIC_KEY = os.path.join(LAUNCHER_ROOT, "desktop-update-public-key.txt")
MAC_ONLINE_PACKAGER = os.path.join(LAUNCHER_ROOT, "scripts", "package-mac-online.mjs")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class ReleaseSourceOfTruthTests(unittest.TestCase):
    def test_desktop_updaters_and_packagers_use_the_public_monorepo(self) -> None:
        updater = read_text(os.path.join(PYTHON_DIR, "services", "app_updater.py"))
        mac_packager = read_text(MAC_ONLINE_PACKAGER)

        canonical_repo = "rfdiosuao/loom-engineering-workspace"
        self.assertIn(f"api.github.com/repos/{canonical_repo}/releases/latest", updater)
        self.assertIn(f'return "{canonical_repo}";', mac_packager)
        self.assertNotIn("rfdiosuao/lumi/releases/latest", updater)

    def test_current_ci_and_release_only_build_new_launcher(self) -> None:
        for path in (CI_WORKFLOW, RELEASE_WORKFLOW):
            source = read_text(path)
            self.assertNotIn("openclaw_ui_integration", source, path)
            self.assertIn("openclaw_new_launcher", source, path)

        release = read_text(RELEASE_WORKFLOW)
        self.assertIn(r"scripts\build-portable.ps1", release)
        self.assertIn("openclaw_new_launcher/src-tauri/target/release/bundle", release.replace("\\", "/"))
        self.assertIn('Join-Path $_.FullName "LOOM.exe"', release)
        self.assertIn('Join-Path $_.FullName "LOOMFiles"', release)

    def test_windows_release_builds_and_publishes_only_the_complete_setup(self) -> None:
        release = read_text(RELEASE_WORKFLOW)

        self.assertIn("npm run package:protected:nsis", release)
        self.assertIn("Set-AuthenticodeSignature", release)
        self.assertIn('LOOM-$version-setup.exe', release)
        self.assertIn(r"verify-release-secrets.ps1 -Source", release)
        self.assertNotIn("Download verified Codex seed", release)
        self.assertNotIn("CODEX_PACKAGE_PATH", release)
        self.assertNotIn("CodexPackagePath", release)
        self.assertNotIn("Get-ChildItem -LiteralPath $bundleDir -Recurse -File", release)

    def test_windows_release_uses_loom_signatures_when_authenticode_secrets_are_absent(self) -> None:
        release = read_text(RELEASE_WORKFLOW)

        self.assertIn("LOOM_DESKTOP_UPDATE_PRIVATE_KEY", release)
        self.assertIn(r"scripts\prepare-desktop-update-release.ps1", release)
        self.assertIn("*.update.json", release)
        self.assertNotIn("-AllowUnsigned", release)
        self.assertNotIn(
            "Stable Windows releases require WINDOWS_PFX_BASE64 and WINDOWS_PFX_PASSWORD.",
            release,
        )

    def test_windows_release_exposes_update_private_key_only_to_manifest_signing(self) -> None:
        release = read_text(RELEASE_WORKFLOW)
        build_step = release.split("- name: Build protected NSIS", 1)[1].split("- name:", 1)[0]
        signing_step = release.split("- name: Sign desktop update manifest", 1)[1].split("- name:", 1)[0]

        self.assertNotIn("LOOM_DESKTOP_UPDATE_PRIVATE_KEY", build_step)
        self.assertIn("LOOM_DESKTOP_UPDATE_PRIVATE_KEY", signing_step)

    def test_release_smoke_preserves_ascii_and_chinese_path_array(self) -> None:
        release = read_text(RELEASE_WORKFLOW)

        self.assertIn(r"& .\scripts\smoke-test-tauri-nsis.ps1", release)
        self.assertIn("-InstallPaths $paths", release)
        self.assertIn("$chineseUser", release)
        self.assertIn("$luming", release)
        self.assertNotIn(r"powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke-test-tauri-nsis.ps1", release)

    def test_release_smoke_uses_repository_artifacts_root_accepted_by_safety_guard(self) -> None:
        release = read_text(RELEASE_WORKFLOW)

        self.assertIn('$smokeRoot = Join-Path $PWD "artifacts\\ci-nsis-smoke"', release)
        self.assertNotIn('$smokeRoot = Join-Path $env:RUNNER_TEMP "loom-nsis-smoke"', release)

    def test_release_smoke_waits_for_owned_processes_to_release_runtime_files(self) -> None:
        smoke = read_text(SMOKE_SCRIPT)

        self.assertIn("$process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue", smoke)
        self.assertIn("Stop-Process -InputObject $process -Force -ErrorAction Stop", smoke)
        self.assertIn("$process.WaitForExit(15000)", smoke)
        self.assertIn("$process.Dispose()", smoke)
        self.assertIn("did not exit after Stop-Process", smoke)
        self.assertIn("function Stop-OwnedProcessesUnderRoot", smoke)
        self.assertIn("Stop-OwnedProcessesUnderRoot -ExpectedRoot $installPath", smoke)
        self.assertNotIn('if ([string]::IsNullOrWhiteSpace($executablePath)) {\n        return', smoke)

    def test_windows_bundle_uses_offline_webview2_installer(self) -> None:
        with open(os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.conf.json"), "r", encoding="utf-8") as handle:
            tauri = json.load(handle)

        self.assertEqual(
            tauri["bundle"]["windows"]["webviewInstallMode"]["type"],
            "offlineInstaller",
        )

    def test_protected_bundle_resources_keep_tauri_runtime_under_up_directory(self) -> None:
        with open(PROTECTED_TAURI_CONFIG, "r", encoding="utf-8") as handle:
            protected = json.load(handle)

        resources = protected["bundle"]["resources"]
        self.assertEqual(resources["../build/protected-resources/python/"], "_up_/python/")
        self.assertEqual(resources["../python-runtime/"], "_up_/python-runtime/")
        self.assertEqual(resources["../node-runtime/"], "_up_/node-runtime/")
        self.assertEqual(resources["../build/protected-resources/scripts/"], "_up_/scripts/")

    def test_desktop_update_public_key_is_bundled_in_standard_and_protected_installers(self) -> None:
        with open(DESKTOP_UPDATE_PUBLIC_KEY, "r", encoding="utf-8") as handle:
            public_key = handle.read().strip()
        self.assertEqual(len(base64.b64decode(public_key, validate=True)), 32)

        with open(TAURI_CONFIG, "r", encoding="utf-8") as handle:
            standard = json.load(handle)
        with open(PROTECTED_TAURI_CONFIG, "r", encoding="utf-8") as handle:
            protected = json.load(handle)

        self.assertIn("../desktop-update-public-key.txt", standard["bundle"]["resources"])
        self.assertEqual(
            protected["bundle"]["resources"]["../desktop-update-public-key.txt"],
            "_up_/desktop-update-public-key.txt",
        )

    def test_ci_script_runs_complete_launcher_python_tests(self) -> None:
        source = read_text(CI_SCRIPT)
        self.assertIn("Python launcher unit tests", source)
        self.assertIn("-m unittest discover", source)
        self.assertIn('python\\tests', source)
        self.assertIn('test_*.py', source)

    def test_ci_builds_and_tests_the_bundled_python_runtime(self) -> None:
        source = read_text(CI_SCRIPT)
        self.assertIn("Bundled Python runtime build", source)
        self.assertIn(r"scripts\build-python-runtime.ps1", source)
        self.assertIn("Bundled Python runtime unit tests", source)
        self.assertIn(r'python-runtime\python.exe', source)
        self.assertIn("Bundled Node runtime build", source)
        self.assertIn(r"scripts\build-node-runtime.ps1", source)
        self.assertLess(source.index("Bundled Python runtime build"), source.index("Rust cargo check"))
        self.assertLess(source.index("Bundled Node runtime build"), source.index("Rust cargo check"))

    def test_ci_passes_powershell_file_arguments_without_parameter_abbreviation(self) -> None:
        source = read_text(CI_SCRIPT)
        self.assertNotIn("Invoke-Native powershell -NoProfile", source)
        self.assertGreaterEqual(source.count("Invoke-Native -FilePath powershell -Arguments"), 3)

    def test_ci_runs_for_every_pull_request_target(self) -> None:
        source = read_text(CI_WORKFLOW)
        self.assertRegex(source, r"(?m)^\s{2}pull_request:\s*$")
        pull_request_block = source.split("  pull_request:", 1)[1].split("  workflow_dispatch:", 1)[0]
        self.assertNotIn("branches:", pull_request_block)

    def test_ci_runs_frontend_node_and_rust_behavior_tests(self) -> None:
        source = read_text(CI_SCRIPT)
        self.assertIn("npm run test:platform-contracts", source)
        self.assertIn("npm run test:node-contracts", source)
        self.assertIn("cargo test", source)

    def test_ci_uses_node_24_compatible_official_actions(self) -> None:
        source = read_text(CI_WORKFLOW)
        self.assertIn("actions/checkout@v5", source)
        self.assertIn("actions/setup-node@v5", source)
        self.assertIn("actions/setup-python@v6", source)
        self.assertIn("actions/cache@v5", source)
        self.assertNotIn("actions/checkout@v4", source)
        self.assertNotIn("actions/setup-node@v4", source)
        self.assertNotIn("actions/setup-python@v5", source)
        self.assertNotIn("actions/cache@v4", source)

    def test_ci_artifact_guard_rejects_new_files_without_deleting_release_history(self) -> None:
        source = read_text(CI_WORKFLOW)
        self.assertIn("git diff --name-only --diff-filter=A", source)
        self.assertIn('"$base...HEAD"', source)
        self.assertNotIn("git ls-files release", source)

    def test_all_authoritative_version_files_are_consistent(self) -> None:
        with open(os.path.join(LAUNCHER_ROOT, "package.json"), "r", encoding="utf-8") as handle:
            package = json.load(handle)
        with open(os.path.join(LAUNCHER_ROOT, "package-lock.json"), "r", encoding="utf-8") as handle:
            package_lock = json.load(handle)
        with open(os.path.join(LAUNCHER_ROOT, "src-tauri", "tauri.conf.json"), "r", encoding="utf-8") as handle:
            tauri = json.load(handle)
        cargo_toml = read_text(os.path.join(LAUNCHER_ROOT, "src-tauri", "Cargo.toml"))
        cargo_lock = read_text(os.path.join(LAUNCHER_ROOT, "src-tauri", "Cargo.lock"))

        version = package["version"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(package_lock["version"], version)
        self.assertEqual(package_lock["packages"][""]["version"], version)
        self.assertEqual(tauri["version"], version)
        escaped_version = re.escape(version)
        self.assertRegex(cargo_toml, rf'(?ms)^\[package\].*?^version\s*=\s*"{escaped_version}"')
        self.assertRegex(
            cargo_lock,
            rf'(?s)\[\[package\]\]\s*name\s*=\s*"app"\s*version\s*=\s*"{escaped_version}"',
        )

    def test_release_body_uses_the_versioned_product_notes_when_available(self) -> None:
        release = read_text(RELEASE_WORKFLOW)

        self.assertIn('RELEASE_NOTES_$version.md', release)
        self.assertIn('Get-Content -LiteralPath $notesPath -Raw', release)
        self.assertIn('body_path: apps/loom-platform/ci_artifacts/RELEASE_BODY.md', release)


if __name__ == "__main__":
    unittest.main()
