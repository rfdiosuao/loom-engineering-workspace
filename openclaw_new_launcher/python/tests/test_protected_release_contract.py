from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest


LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ProtectedReleaseContractTests(unittest.TestCase):
    def test_protected_tauri_config_uses_staged_resource_map(self) -> None:
        config_path = os.path.join(LAUNCHER_DIR, "src-tauri", "tauri.protected.conf.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)

        resources = config["bundle"]["resources"]
        self.assertIsInstance(resources, dict)
        self.assertEqual(resources["../build/protected-resources/python/"], "_up_/python/")
        self.assertEqual(resources["../build/protected-resources/scripts/"], "_up_/scripts/")
        self.assertNotIn("../python/**/*", resources)
        self.assertNotIn("../scripts/**/*", resources)

    def test_protected_package_scripts_use_standard_tauri_nsis_lane(self) -> None:
        package_path = os.path.join(LAUNCHER_DIR, "package.json")
        with open(package_path, "r", encoding="utf-8") as handle:
            package = json.load(handle)

        scripts = package["scripts"]
        self.assertIn("stage:protected", scripts)
        self.assertIn("verify:protected", scripts)
        self.assertIn("package:protected:nsis", scripts)
        self.assertIn("tauri -- build --bundles nsis", scripts["package:protected:nsis"])
        self.assertNotIn("build-nsis-online-installer", scripts["package:protected:nsis"])

    def test_python_staging_keeps_cli_executable_without_business_sources(self) -> None:
        source = os.path.join(LAUNCHER_DIR, "python")
        script = os.path.join(LAUNCHER_DIR, "scripts", "stage-protected-python.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "python")
            subprocess.run(
                [sys.executable, script, "--source", source, "--target", target],
                cwd=LAUNCHER_DIR,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            business_sources = []
            for root, _dirs, files in os.walk(target):
                for name in files:
                    if name.endswith(".py") and name not in {"bridge.py", "loom_cli.py", "loom_mcp.py", "__init__.py"}:
                        business_sources.append(os.path.relpath(os.path.join(root, name), target))

            completed = subprocess.run(
                [sys.executable, os.path.join(target, "loom_cli.py"), "status", "--json"],
                cwd=LAUNCHER_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )

        self.assertEqual(business_sources, [])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])

    def test_python_staging_keeps_cli_importable_without_running_main(self) -> None:
        source = os.path.join(LAUNCHER_DIR, "python")
        script = os.path.join(LAUNCHER_DIR, "scripts", "stage-protected-python.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "python")
            subprocess.run(
                [sys.executable, script, "--source", source, "--target", target],
                cwd=LAUNCHER_DIR,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json, sys; "
                        "sys.path.insert(0, sys.argv[1]); "
                        "import loom_cli; "
                        "catalog = loom_cli._command_catalog(); "
                        "print(json.dumps({'domains': len(catalog.get('domains', []))}))"
                    ),
                    target,
                ],
                cwd=LAUNCHER_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertGreater(json.loads(completed.stdout)["domains"], 0)

    def test_python_staging_bootstraps_native_agent_capabilities(self) -> None:
        source = os.path.join(LAUNCHER_DIR, "python")
        script = os.path.join(LAUNCHER_DIR, "scripts", "stage-protected-python.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "python")
            state_root = os.path.join(temp_dir, "state")
            subprocess.run(
                [sys.executable, script, "--source", source, "--target", target],
                cwd=LAUNCHER_DIR,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json, sys; "
                        "sys.path.insert(0, sys.argv[1]); "
                        "from core.paths import AppPaths; "
                        "from services.agent_service import AgentService; "
                        "service = AgentService(AppPaths(sys.argv[2])); "
                        "payload = service.bootstrap(); "
                        "service.shutdown(); "
                        "print(json.dumps(payload))"
                    ),
                    target,
                    state_root,
                ],
                cwd=LAUNCHER_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertIn("loom-native", [item["runtimeProfileId"] for item in payload["runtimeProfiles"]])
        self.assertGreater(len(payload["capabilities"]), 0)


if __name__ == "__main__":
    unittest.main()
