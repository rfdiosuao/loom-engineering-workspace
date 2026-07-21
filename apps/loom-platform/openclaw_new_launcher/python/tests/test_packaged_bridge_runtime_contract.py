from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PackagedBridgeRuntimeContractTests(unittest.TestCase):
    def test_tauri_bundle_includes_python_runtime_resources(self) -> None:
        config_path = os.path.join(REPO_ROOT, "src-tauri", "tauri.conf.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)

        resources = config["bundle"]["resources"]
        self.assertIn("../python/**/*", resources)
        self.assertIn("../python-runtime/**/*", resources)
        self.assertIn("../node-runtime/**/*", resources)
        self.assertIn("../public/skills/**/*", resources)
        self.assertIn("../../release-manifest.json", resources)
        self.assertIn("../../release-public-key.txt", resources)

    def test_tauri_product_name_uses_ascii_install_path(self) -> None:
        config_path = os.path.join(REPO_ROOT, "src-tauri", "tauri.conf.json")
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)

        product_name = config["productName"]

        self.assertEqual(product_name, "Luming AI Matrix Acquisition Workbench")
        self.assertTrue(product_name.isascii())

    def test_packaged_resource_bridge_requires_bundled_runtime(self) -> None:
        source_path = os.path.join(REPO_ROOT, "src-tauri", "src", "lib.rs")
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("fn is_packaged_bridge", source)
        self.assertIn('text.eq_ignore_ascii_case("resources")', source)
        self.assertIn('text.eq_ignore_ascii_case("python")', source)
        self.assertIn("Python runtime", source)

    def test_first_run_setup_can_retry_without_restarting_the_launcher(self) -> None:
        rust_path = os.path.join(REPO_ROOT, "src-tauri", "src", "lib.rs")
        gate_path = os.path.join(REPO_ROOT, "src", "components", "SetupGate.tsx")
        with open(rust_path, "r", encoding="utf-8") as handle:
            rust_source = handle.read()
        with open(gate_path, "r", encoding="utf-8") as handle:
            gate_source = handle.read()

        self.assertIn("async fn retry_distribution_setup", rust_source)
        self.assertIn("bootstrap::ensure_layers", rust_source)
        self.assertIn("start_bridge(app).await", rust_source)
        self.assertIn("retry_distribution_setup", gate_source)
        self.assertIn("重试补全", gate_source)

    def test_embedded_python_runtime_can_import_packaged_project_modules(self) -> None:
        script_path = os.path.join(REPO_ROOT, "scripts", "build-python-runtime.ps1")
        with open(script_path, "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("../python", script)
        self.assertIn('".."', script)
        self.assertIn("from python.core.paths import AppPaths", script)
        self.assertIn("from core.paths import AppPaths", script)

        runtime_pth = os.path.join(REPO_ROOT, "python-runtime", "python311._pth")
        if os.path.exists(runtime_pth):
            with open(runtime_pth, "r", encoding="ascii") as handle:
                pth_lines = [line.strip() for line in handle.readlines()]
            self.assertIn("../python", pth_lines)
            self.assertIn("..", pth_lines)
            self.assertIn("Lib/site-packages", pth_lines)
            self.assertIn("import site", pth_lines)

    def test_embedded_python_runtime_includes_fastapi_testclient_dependencies(self) -> None:
        requirements_path = os.path.join(REPO_ROOT, "python", "requirements.txt")
        script_path = os.path.join(REPO_ROOT, "scripts", "build-python-runtime.ps1")
        with open(requirements_path, "r", encoding="utf-8") as handle:
            requirements = handle.read()
        with open(script_path, "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("httpx2", requirements)
        self.assertIn("from fastapi.testclient import TestClient", script)
        self.assertIn("Get-PythonInstaller", script)
        self.assertIn("sys.version_info", script)
        self.assertIn("No working Python $targetMajorMinor installer found", script)
        self.assertNotIn("& py -3 -m pip", script)

    def test_phone_script_path_resolves_packaged_up_scripts(self) -> None:
        from api.routes_phone import _script_path
        from core.paths import AppPaths

        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = os.path.join(temp_dir, "_up_", "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            expected = os.path.join(scripts_dir, "openclaw-phone-agent.mjs")
            with open(expected, "w", encoding="utf-8") as handle:
                handle.write("// packaged phone agent\n")

            ctx = SimpleNamespace(paths=AppPaths(base_path=temp_dir))
            actual = _script_path(ctx, "openclaw-phone-agent.mjs")

            self.assertEqual(os.path.normcase(os.path.normpath(actual)), os.path.normcase(os.path.normpath(expected)))

    def test_node_runtime_resolves_packaged_up_runtime(self) -> None:
        from core.paths import AppPaths

        with tempfile.TemporaryDirectory() as temp_dir:
            node_dir = os.path.join(temp_dir, "_up_", "node-runtime")
            os.makedirs(node_dir, exist_ok=True)
            expected = os.path.join(node_dir, "node.exe")
            with open(expected, "wb") as handle:
                handle.write(b"node")

            paths = AppPaths(base_path=temp_dir)

            self.assertEqual(os.path.normcase(os.path.normpath(paths.node_exe)), os.path.normcase(os.path.normpath(expected)))


if __name__ == "__main__":
    unittest.main()
