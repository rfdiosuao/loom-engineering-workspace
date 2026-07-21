from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest


WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT_PATH = os.path.join(WORKSPACE_ROOT, "scripts", "ci-check.ps1")


def _write(path: str, content: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell is required")
class CiCheckScriptTests(unittest.TestCase):
    def test_child_powershell_failure_fails_the_ci_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = os.path.join(temp_dir, "scripts")
            launcher_dir = os.path.join(temp_dir, "openclaw_new_launcher")
            os.makedirs(scripts_dir)
            os.makedirs(os.path.join(launcher_dir, "src-tauri"))
            _write(os.path.join(launcher_dir, "package.json"), "{}")
            shutil.copy2(SCRIPT_PATH, os.path.join(scripts_dir, "ci-check.ps1"))
            _write(os.path.join(scripts_dir, "verify-repository-governance.ps1"), "exit 0\n")
            _write(os.path.join(scripts_dir, "build-luming-skills-library.ps1"), "exit 0\n")
            _write(os.path.join(scripts_dir, "verify-release-secrets.ps1"), "exit 17\n")
            _write(os.path.join(scripts_dir, "verify-version-consistency.ps1"), "exit 0\n")

            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    os.path.join(scripts_dir, "ci-check.ps1"),
                    "-SkipSourceText",
                    "-SkipFrontend",
                    "-SkipRust",
                    "-SkipPython",
                    "-SkipBundledPythonRuntime",
                    "-SkipLicenseServer",
                    "-SkipWorkspaceHygiene",
                    "-SkipDistSelftest",
                    "-SkipInstallerManifest",
                    "-SkipAdminConsole",
                    "-SkipLicenseFlowTests",
                ],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Source secret scan", output)
            self.assertNotIn("Version consistency", output)
            self.assertNotIn("All CI checks passed.", output)


if __name__ == "__main__":
    unittest.main()
