from __future__ import annotations

import os
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PythonRuntimeCompatibilityTests(unittest.TestCase):
    def test_bridge_startup_modules_do_not_use_collections_abc_callable_aliases(self) -> None:
        startup_modules = [
            os.path.join(PYTHON_DIR, "bridge.py"),
            os.path.join(PYTHON_DIR, "services", "process.py"),
            os.path.join(PYTHON_DIR, "services", "updater.py"),
            os.path.join(PYTHON_DIR, "services", "jobs.py"),
            os.path.join(PYTHON_DIR, "services", "desktop_agent.py"),
            os.path.join(PYTHON_DIR, "services", "video_api.py"),
        ]

        offenders = []
        for path in startup_modules:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            if "from collections.abc import Callable" in source:
                offenders.append(os.path.relpath(path, PYTHON_DIR))

        self.assertEqual(
            offenders,
            [],
            "collections.abc.Callable is not subscriptable on older target Python runtimes",
        )

    def test_runtime_type_aliases_do_not_use_pep585_builtin_generics(self) -> None:
        alias_modules = [
            os.path.join(PYTHON_DIR, "services", "process.py"),
            os.path.join(PYTHON_DIR, "core", "component_installer.py"),
        ]

        offenders = []
        for path in alias_modules:
            with open(path, "r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    stripped = line.strip()
                    if stripped.startswith(("CommandRunner =", "ComponentInstallerRunner =")) and "list[" in stripped:
                        offenders.append(f"{os.path.relpath(path, PYTHON_DIR)}:{line_number}")

        self.assertEqual(
            offenders,
            [],
            "module-level Callable aliases must avoid list[str] on older target Python runtimes",
        )


if __name__ == "__main__":
    unittest.main()
