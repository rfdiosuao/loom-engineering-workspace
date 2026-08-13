from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest


WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT_PATH = os.path.join(WORKSPACE_ROOT, "scripts", "verify-version-consistency.ps1")
PACKAGE_JSON_PATH = os.path.join(WORKSPACE_ROOT, "openclaw_new_launcher", "package.json")
FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "version_consistency")


def _run_script_path(script_path: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    return _run_script_path(SCRIPT_PATH, *arguments)


def _current_version() -> str:
    with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as handle:
        return str(json.load(handle)["version"])


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _create_mini_platform(temp_dir: str) -> tuple[str, str]:
    scripts_dir = os.path.join(temp_dir, "scripts")
    launcher_dir = os.path.join(temp_dir, "openclaw_new_launcher")
    tauri_dir = os.path.join(launcher_dir, "src-tauri")
    os.makedirs(scripts_dir)
    os.makedirs(tauri_dir)

    copied_script = os.path.join(scripts_dir, "verify-version-consistency.ps1")
    shutil.copy2(SCRIPT_PATH, copied_script)
    _write(
        os.path.join(launcher_dir, "package.json"),
        json.dumps({"name": "loom-launcher", "version": "2.4.11"}, indent=2),
    )
    _write(
        os.path.join(launcher_dir, "package-lock.json"),
        json.dumps(
            {
                "name": "loom-launcher",
                "version": "2.4.11",
                "lockfileVersion": 3,
                "packages": {"": {"name": "loom-launcher", "version": "2.4.11"}},
            },
            indent=2,
        ),
    )
    _write(os.path.join(tauri_dir, "tauri.conf.json"), json.dumps({"version": "2.4.11"}, indent=2))
    _write(os.path.join(tauri_dir, "Cargo.toml"), '[package]\nname = "app"\nversion = "2.4.11"\n')
    _write(os.path.join(tauri_dir, "Cargo.lock"), '[[package]]\nname = "app"\nversion = "2.4.11"\n')
    return copied_script, launcher_dir


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell is required")
class VerifyVersionConsistencyScriptTests(unittest.TestCase):
    def test_invalid_json_with_nested_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path, launcher_dir = _create_mini_platform(temp_dir)
            shutil.copy2(
                os.path.join(FIXTURE_ROOT, "invalid_json_with_nested_version.json"),
                os.path.join(launcher_dir, "package.json"),
            )

            result = _run_script_path(script_path)

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Unable to parse JSON", output)

    def test_package_lock_nested_versions_cannot_replace_root_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path, launcher_dir = _create_mini_platform(temp_dir)
            shutil.copy2(
                os.path.join(FIXTURE_ROOT, "package_lock_nested_versions_only.json"),
                os.path.join(launcher_dir, "package-lock.json"),
            )

            result = _run_script_path(script_path)

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Missing JSON property 'version'", output)

    def test_cargo_lock_rejects_duplicate_target_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path, launcher_dir = _create_mini_platform(temp_dir)
            shutil.copy2(
                os.path.join(FIXTURE_ROOT, "cargo_lock_duplicate_app.lock"),
                os.path.join(launcher_dir, "src-tauri", "Cargo.lock"),
            )

            result = _run_script_path(script_path)

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("found 2", output)

    def test_no_arguments_accepts_consistent_sources(self) -> None:
        version = _current_version()
        result = _run_script()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(f"Version consistency check passed: {version}", output)

    def test_expected_version_accepts_release_contract_literal(self) -> None:
        result = _run_script("-ExpectedVersion", "2.4.14")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Version consistency check passed: 2.4.14", output)

    def test_expected_version_rejects_non_exact_values(self) -> None:
        version = _current_version()
        for value in ("", "   ", f"v{version}", "0.0.0"):
            with self.subTest(value=value):
                result = _run_script("-ExpectedVersion", value)

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(f"expected-version={value}", output)

    def test_unknown_named_parameter_fails_closed(self) -> None:
        result = _run_script("-UnexpectedOption", "value")

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("UnexpectedOption", output)

    def test_tag_name_accepts_current_release_tag(self) -> None:
        version = _current_version()
        result = _run_script("-TagName", f"v{version}")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)

    def test_tag_name_rejects_non_exact_values(self) -> None:
        version = _current_version()
        for value in ("", "   ", version, f"V{version}", "v0.0.0"):
            with self.subTest(value=value):
                result = _run_script("-TagName", value)

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(f"tag={value}", output)

    def test_expected_version_and_tag_name_accept_exact_values(self) -> None:
        version = _current_version()
        result = _run_script("-ExpectedVersion", version, "-TagName", f"v{version}")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)

    def test_expected_version_and_tag_name_reject_any_invalid_value(self) -> None:
        version = _current_version()
        cases = (
            ("0.0.0", f"v{version}"),
            (version, "v0.0.0"),
            ("", f"v{version}"),
            (version, ""),
            ("   ", f"v{version}"),
            (version, "   "),
        )
        for expected_version, tag_name in cases:
            with self.subTest(expected_version=expected_version, tag_name=tag_name):
                result = _run_script(
                    "-ExpectedVersion",
                    expected_version,
                    "-TagName",
                    tag_name,
                )

                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
