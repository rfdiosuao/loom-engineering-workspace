"""Path discovery helpers for portable and packaged launcher layouts."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class AppPaths:
    base_path: str

    @classmethod
    def discover(cls) -> "AppPaths":
        # Navigate up from this file (paths.py) to find the project/install root.
        # paths.py lives at <root>/python/core/paths.py
        # where <root> is either the project root (dev) or install root (production).
        # In Tauri production bundles, resources are at <install_dir>/resources/python/core/paths.py,
        # so we need an extra level up.
        core_dir = os.path.dirname(os.path.abspath(__file__))
        python_dir = os.path.dirname(core_dir)
        base_path = os.path.dirname(python_dir)

        # Handle bundled resource directories (Tauri production / portable bundles).
        # For example:
        #   <install>/resources/python/core/paths.py -> <install>
        #   <portable>/_up_/python/core/paths.py     -> <portable>
        if os.path.basename(python_dir) == "python" and os.path.basename(base_path) in ("resources", "python", "_up_"):
            base_path = os.path.dirname(base_path)

        # Handle "OpenClaw启动" edge case
        if os.path.basename(base_path) == "OpenClaw启动":
            base_path = os.path.dirname(base_path)

        # Strip Windows long path prefix (\\?\) that causes Node.js module resolution failures
        if base_path.startswith("\\\\?\\"):
            base_path = base_path[4:]
        base_path = os.path.normpath(base_path)

        return cls(base_path=base_path)

    def resource_path(self, filename: str) -> str:
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, filename)
        return os.path.join(self.base_path, filename)

    def find_node_dir(self) -> str:
        candidates = [
            os.path.join(self.base_path, "SystemData", ".core", "node"),
            os.path.join(self.base_path, "node"),
        ]
        for path in candidates:
            if any(os.path.exists(os.path.join(path, name)) for name in self.node_binary_names()):
                return path
        return candidates[-1]

    @staticmethod
    def node_binary_names() -> tuple[str, ...]:
        if os.name == "nt":
            return ("node.exe", "node")
        return ("node", "node.exe")

    def find_file(self, filename: str, search_dirs: tuple[str, ...] = ("", "back", "backup", "SystemData")) -> str:
        for directory in search_dirs:
            path = os.path.join(self.base_path, directory, filename) if directory else os.path.join(self.base_path, filename)
            if os.path.exists(path):
                return path
        return os.path.join(self.base_path, filename)

    @property
    def node_dir(self) -> str:
        return self.find_node_dir()

    @property
    def node_exe(self) -> str:
        for name in self.node_binary_names():
            path = os.path.join(self.node_dir, name)
            if os.path.exists(path):
                return path
        return os.path.join(self.node_dir, self.node_binary_names()[0])

    @property
    def pnpm_cli(self) -> str:
        candidates = [
            os.path.join(self.node_dir, "node_modules", "pnpm", "bin", "pnpm.cjs"),
            os.path.join(self.base_path, "node_modules", "pnpm", "bin", "pnpm.cjs"),
            os.path.join(self.base_path, "SystemData", ".core", "node_modules", "pnpm", "bin", "pnpm.cjs"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    @property
    def npm_cli(self) -> str:
        candidates = [
            os.path.join(self.node_dir, "node_modules", "npm", "bin", "npm-cli.js"),
            os.path.join(self.base_path, "node_modules", "npm", "bin", "npm-cli.js"),
            os.path.join(self.base_path, "SystemData", ".core", "node_modules", "npm", "bin", "npm-cli.js"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    @property
    def data_dir(self) -> str:
        return os.path.join(self.base_path, "data")

    @property
    def state_dir(self) -> str:
        return os.path.join(self.data_dir, ".openclaw")

    @property
    def openclaw_config(self) -> str:
        return os.path.join(self.state_dir, "openclaw.json")

    @property
    def auth_profiles(self) -> str:
        return os.path.join(self.state_dir, "agents", "main", "agent", "auth-profiles.json")

    @property
    def image_config(self) -> str:
        return os.path.join(self.base_path, "imgapi_config.json")

    @property
    def video_config(self) -> str:
        return os.path.join(self.base_path, "video_config.json")

    @property
    def videoapi_config(self) -> str:
        return os.path.join(self.base_path, "videoapi_config.json")

    @property
    def member_session_file(self) -> str:
        return os.path.join(self.launcher_dir, "member-session.json")

    @property
    def storyboard_dir(self) -> str:
        return os.path.join(self.data_dir, "storyboards")

    @property
    def storyboard_project(self) -> str:
        return os.path.join(self.storyboard_dir, "ad_video_project.json")

    @property
    def storyboard_assets(self) -> str:
        return os.path.join(self.storyboard_dir, "assets")

    @property
    def launcher_dir(self) -> str:
        return os.path.join(self.state_dir, "launcher")

    @property
    def skills_dir(self) -> str:
        return os.path.join(self.openclaw_workspace, "skills")

    @property
    def legacy_skills_dir(self) -> str:
        return os.path.join(self.state_dir, "skills")

    @property
    def skills_state(self) -> str:
        return os.path.join(self.launcher_dir, "skills-state.json")

    @property
    def openclaw_workspace(self) -> str:
        return os.path.join(self.state_dir, "workspace")

    @property
    def openclaw_workspace_template(self) -> str:
        return os.path.join(self.base_path, "openclaw-workspace")

    @property
    def generated_images_dir(self) -> str:
        return os.path.join(self.data_dir, "generated-images")

    @property
    def openclaw_extensions_dir(self) -> str:
        return os.path.join(self.state_dir, "extensions")

    @property
    def license_file(self) -> str:
        return os.path.join(self.data_dir, "license.json")

    @property
    def install_id_file(self) -> str:
        return os.path.join(self.data_dir, "install_id.txt")

    @property
    def themes_dir(self) -> str:
        writable_themes = os.path.join(self.data_dir, "themes")
        bundled_themes = os.path.join(self.base_path, "_up_", "data", "themes")
        if os.path.isdir(writable_themes):
            return writable_themes
        if os.path.isdir(bundled_themes):
            return bundled_themes
        return writable_themes

    def theme_file(self, merchant_id: str) -> str:
        return os.path.join(self.themes_dir, merchant_id, "theme.json")

    @property
    def theme_json(self) -> str:
        return os.path.join(self.data_dir, "theme.json")

    @property
    def brand_profile(self) -> str:
        return os.path.join(self.data_dir, "brand_profile.json")

    @property
    def openclaw_mjs(self) -> str:
        candidates = [
            os.path.join(self.base_path, "node_modules", "openclaw", "openclaw.mjs"),
            os.path.join(self.base_path, "SystemData", ".core", "node_modules", "openclaw", "openclaw.mjs"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    def process_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["OPENCLAW_HOME"] = self.data_dir
        env["OPENCLAW_STATE_DIR"] = self.state_dir
        env["OPENCLAW_CONFIG_PATH"] = self.openclaw_config
        path_entries = [
            self.node_dir,
            os.path.join(self.base_path, "node_modules", ".bin"),
            os.path.join(self.base_path, "SystemData", ".core", "node_modules", ".bin"),
            os.path.join(self.base_path, "_up_", "python-runtime", "Scripts"),
        ]
        existing_path = env.get("Path") or env.get("PATH") or ""
        portable_path = os.pathsep.join([entry for entry in path_entries if entry])
        merged_path = portable_path if not existing_path else f"{portable_path}{os.pathsep}{existing_path}"
        env["PATH"] = merged_path
        env["Path"] = merged_path
        portable_python_path = os.path.join(self.base_path, "_up_", "python")
        if os.path.isdir(portable_python_path):
            existing_python_path = env.get("PYTHONPATH") or ""
            env["PYTHONPATH"] = portable_python_path if not existing_python_path else f"{portable_python_path}{os.pathsep}{existing_python_path}"
        return env
