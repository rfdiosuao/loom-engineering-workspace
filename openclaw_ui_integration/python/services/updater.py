"""OpenClaw package update helpers."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Callable

from core.paths import AppPaths

UiCall = Callable[..., None]
LogCall = Callable[[str], None]


class OpenClawUpdater:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._cache_lock = threading.Lock()
        self._current_version_cache: str | None = None
        self._latest_version_cache: tuple[float, str | None, str | None] | None = None

    def _clear_cache(self) -> None:
        with self._cache_lock:
            self._current_version_cache = None
            self._latest_version_cache = None

    def current_version(self) -> str:
        with self._cache_lock:
            if self._current_version_cache is not None:
                return self._current_version_cache

        package_json = os.path.join(self.paths.base_path, "node_modules", "openclaw", "package.json")
        if not os.path.exists(package_json):
            version = "unknown"
        else:
            try:
                with open(package_json, "r", encoding="utf-8") as file:
                    version = json.load(file).get("version", "unknown")
            except Exception:
                version = "unknown"

        with self._cache_lock:
            self._current_version_cache = version
        return version

    def package_manager_args(self, *args: str) -> list[str] | None:
        node_exe = self.paths.node_exe
        if not os.path.exists(node_exe):
            return None

        candidates = [self.paths.npm_cli, self.paths.pnpm_cli]
        for cli in candidates:
            if os.path.exists(cli):
                return [node_exe, cli, *args]
        return None

    def latest_version(self) -> tuple[str | None, str | None]:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._latest_version_cache
            if cached and now - cached[0] < 300:
                return cached[1], cached[2]

        command = self.package_manager_args("view", "openclaw", "version")
        if not command:
            return None, "找不到随包 Node.js 或 npm，无法检查更新"
        latest: str | None
        error_message: str | None
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=self.paths.base_path,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=30,
            )
            if result.returncode == 0:
                latest, error_message = result.stdout.strip(), None
            else:
                latest, error_message = None, result.stderr.strip() or "网络错误"
        except subprocess.TimeoutExpired:
            latest, error_message = None, "请求超时"
        except Exception as error:
            latest, error_message = None, str(error)

        with self._cache_lock:
            self._latest_version_cache = (now, latest, error_message)
        return latest, error_message

    def install_latest(self) -> tuple[bool, str, list[str]]:
        command = self.package_manager_args("install", "openclaw@latest", "--no-audit", "--no-fund")
        if not command:
            return False, self.current_version(), ["找不到随包 Node.js 或 npm，无法执行更新"]

        output: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                cwd=self.paths.base_path,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if not line and process.poll() is not None:
                        break
                    if line:
                        output.append(line)
            exit_code = process.wait()
            self._clear_cache()
            return exit_code == 0, self.current_version(), output
        except Exception as error:
            self._clear_cache()
            return False, self.current_version(), [str(error)]

    def update_async(self, append_log: LogCall, ui_call: UiCall, on_done: Callable[[bool, str], None]) -> None:
        def worker():
            success, current, output = self.install_latest()
            for line in output:
                ui_call(append_log, f"  {line}")
            ui_call(on_done, success, current if success else "\n".join(output) or "更新失败")

        threading.Thread(target=worker, daemon=True).start()
