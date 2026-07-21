"""OpenClaw gateway process management."""

from __future__ import annotations

import os
import json
import hashlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, List

from core.constants import APP_PORT
from core.paths import AppPaths

UiCall = Callable[..., None]
LogCall = Callable[[str], None]
CommandRunner = Callable[[List[str], int], subprocess.CompletedProcess]
RetrySleeper = Callable[[float], None]
PREREQUISITE_RETRY_DELAYS_SECONDS = (0.0, 1.0, 3.0)


class OpenClawProcessService:
    def __init__(
        self,
        paths: AppPaths,
        append_log: LogCall,
        ui_call: UiCall,
        command_runner: CommandRunner | None = None,
        retry_sleep: RetrySleeper | None = None,
    ):
        self.paths = paths
        self.append_log = append_log
        self.ui_call = ui_call
        self.command_runner = command_runner or self._run_command
        self.retry_sleep = retry_sleep or time.sleep
        self.process: subprocess.Popen | None = None
        self.running = False
        self._output_tail: list[str] = []
        self._last_start_command: list[str] = []
        self.startup_state = "idle"
        self.startup_started_at: float | None = None
        self._startup_started_perf: float | None = None
        self._startup_timeline: list[dict] = []
        self.startup_error = ""
        self.startup_timeout_sec = int(os.environ.get("OPENCLAW_STARTUP_TIMEOUT_SEC", "420") or "420")
        self._startup_lock = threading.Lock()

    def start(self, on_exit: Callable[[int | None], None] | None = None) -> None:
        with self._startup_lock:
            self._start_locked(on_exit=on_exit)

    def start_background(self, on_exit: Callable[[int | None], None] | None = None) -> dict:
        with self._startup_lock:
            if self.running and self.process and self.process.poll() is None:
                return self.status()
            if self.startup_state == "starting":
                return self.status()
            self.startup_state = "starting"
            self.startup_started_at = time.time()
            self.startup_error = ""

        threading.Thread(target=self._background_start_worker, args=(on_exit,), daemon=True).start()
        return self.status()

    def _background_start_worker(self, on_exit: Callable[[int | None], None] | None = None) -> None:
        try:
            self.start(on_exit=on_exit)
        except Exception as error:
            self.running = False
            self.startup_state = "failed"
            self.startup_error = str(error)
            self._write_startup_snapshot(
                status="fail",
                error=str(error),
                exit_code=None,
                port_ready=self._is_port_listening(APP_PORT),
            )
            self.append_log(f"[OpenClaw] Background startup failed: {error}\n")

    def status(self) -> dict:
        process_exists = self.process is not None
        process_alive = process_exists and self.process.poll() is None
        port_ready = self._is_port_listening(APP_PORT) if process_alive else False
        if process_alive and port_ready:
            self.running = True
            self.startup_state = "running"
            self.startup_error = ""
        elif self.startup_state == "starting" and (process_alive or not process_exists):
            self.running = False
        elif process_exists and not process_alive and self.startup_state == "starting":
            self.running = False
            self.startup_state = "failed"
            if not self.startup_error:
                self.startup_error = "OpenClaw process exited before the port became ready"

        elapsed = int(time.time() - self.startup_started_at) if self.startup_started_at else 0
        return {
            "running": bool(process_alive and port_ready),
            "processAlive": bool(process_alive),
            "starting": self.startup_state == "starting" and not port_ready and (process_alive or not process_exists),
            "startupState": self.startup_state,
            "startupElapsedSec": elapsed,
            "startupTimeoutSec": self.startup_timeout_sec,
            "startupError": self.startup_error,
            "startupStage": self._startup_timeline[-1]["stage"] if self._startup_timeline else None,
            "startupDurationMs": int((time.perf_counter() - self._startup_started_perf) * 1000) if self._startup_started_perf else None,
            "pid": self.process.pid if process_alive else None,
            "portReady": bool(port_ready),
        }

    def _resolve_openclaw_start_command(self) -> list[str]:
        node_exe = self.paths.node_exe
        if not os.path.isfile(node_exe):
            raise FileNotFoundError(f"找不到 Node.js：\n{node_exe}")

        start_js = self.paths.find_file("start.js", ("back", "backup", ""))
        if os.path.isfile(start_js):
            return [node_exe, start_js]

        openclaw_mjs = self.paths.openclaw_mjs
        if os.path.isfile(openclaw_mjs):
            return [
                node_exe,
                openclaw_mjs,
                "gateway",
                "--port",
                str(APP_PORT),
                "--bind",
                "loopback",
                "--auth",
                "none",
                "--allow-unconfigured",
            ]

        raise FileNotFoundError(
            "找不到 OpenClaw 启动入口：\n"
            f"{start_js}\n"
            f"{openclaw_mjs}\n"
            "请先在安装页完成 OpenClaw 安装。"
        )

    def _openclaw_start_entry_check(self) -> dict:
        try:
            command = self._resolve_openclaw_start_command()
            return {
                "id": "start_js",
                "label": "OpenClaw 启动入口",
                "status": "ok",
                "message": "已找到可启动入口",
                "detail": command[1],
                "repairable": False,
            }
        except (FileNotFoundError, OSError) as error:
            return {
                "id": "start_js",
                "label": "OpenClaw 启动入口",
                "status": "fail",
                "message": "启动入口缺失，请先安装 OpenClaw",
                "detail": str(error),
                "repairable": False,
            }

    def _start_locked(self, on_exit: Callable[[int | None], None] | None = None) -> None:
        if self.running:
            raise RuntimeError("服务已在运行中")
        self.startup_state = "starting"
        self.startup_started_at = time.time()
        self._startup_started_perf = time.perf_counter()
        self._startup_timeline = []
        self.startup_error = ""
        command = self._resolve_openclaw_start_command()
        node_exe, start_entry = command[:2]

        self._mark_startup_stage("preflight", "检查运行环境和启动脚本")
        storage_check = self._storage_health_check(write_test=self._startup_storage_write_test_enabled())
        if storage_check["status"] == "fail":
            raise RuntimeError(
                "运行磁盘/U盘检测失败："
                f"{storage_check['message']}\n{storage_check.get('detail', '')}\n"
                "请先重新插拔U盘、备份数据，或把安装包复制到健康磁盘后再启动。"
            )
        if storage_check["status"] == "warn":
            self.append_log(
                "[OpenClaw] Storage warning: "
                f"{storage_check['message']} | {storage_check.get('detail', '')}\n"
            )
        self._mark_startup_stage("storage_check", storage_check["message"])

        killed = self._kill_port_processes(APP_PORT)
        if self._startup_deep_clean_enabled():
            killed += self._stop_registered_gateway()
            killed += self._kill_clawpanel_processes()
            killed += self._kill_openclaw_gateway_processes()
        if killed:
            self.append_log(f"[OpenClaw] Cleared {killed} stale gateway/listener process(es).\n")
        self._mark_startup_stage("cleanup", f"killed={killed}")

        config_changed, config_backup = self._ensure_openclaw_config()
        if config_changed:
            if config_backup:
                self.append_log(f"[OpenClaw] Rebuilt invalid openclaw.json, backup: {config_backup}\n")
            else:
                self.append_log("[OpenClaw] Rebuilt or normalized openclaw.json.\n")
        self._mark_startup_stage("config", "openclaw.json ready" if not config_changed else "openclaw.json repaired")

        self._ensure_openclaw_workspace()
        self._mark_startup_stage("workspace", "portable workspace ready")
        self._write_runtime_context()
        self._mark_startup_stage("runtime_context", "runtime-context.json written")

        env = self.paths.process_env()
        self._last_start_command = command
        self._output_tail = []
        self.append_log("[OpenClaw] Starting service...\n")
        self.append_log(f"[OpenClaw] Node: {node_exe}\n")
        self.append_log(f"[OpenClaw] Entry: {start_entry}\n\n")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(
            command,
            cwd=self.paths.base_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
        self.running = True
        self.append_log(f"[OpenClaw] PID: {self.process.pid}\n")
        self._mark_startup_stage("spawn", f"pid={self.process.pid}")
        threading.Thread(target=self._read_output, args=(self.process, on_exit), daemon=True).start()
        try:
            self._wait_until_ready(APP_PORT, timeout=float(self.startup_timeout_sec))
            self.append_log(f"[OpenClaw] Ready: http://127.0.0.1:{APP_PORT}\n")
            self._mark_startup_stage("ready", f"port={APP_PORT}")
            self.startup_state = "running"
            self.startup_error = ""
            self._write_startup_snapshot(
                status="ok",
                error="",
                exit_code=None,
                port_ready=True,
            )
        except Exception as startup_error:
            error_text = str(startup_error) or "OpenClaw startup failed"
            self.startup_error = error_text
            exit_code = self.process.poll() if self.process else None
            self._write_startup_snapshot(
                status="fail",
                error=error_text,
                exit_code=exit_code,
                port_ready=self._is_port_listening(APP_PORT),
            )
            if isinstance(startup_error, TimeoutError) and self.process and self.process.poll() is None:
                self.append_log("[OpenClaw] Startup is slower than expected; keeping process alive for low-end hardware.\n")
                self.startup_state = "starting"
                return
            self.append_log("[OpenClaw] Startup did not become ready; cleaning up process tree.\n")
            if self.process and self.process.poll() is None:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            self.running = False
            self.process = None
            self.startup_state = "failed"
            raise

    def stop(self) -> str:
        if self.process and self.process.poll() is None:
            pid = self.process.pid
            self.append_log("\n[OpenClaw] Stopping...\n")
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True, errors="replace")
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self.running = False
            self.startup_state = "idle"
            self.startup_error = ""
            self.append_log("[OpenClaw] Stopped.\n")
            return "服务已停止"
        if self.process:
            self.append_log("\n[OpenClaw] Cleaning up stale port listeners...\n")
            killed = self._kill_openclaw_gateway_processes()
            killed += self._kill_port_processes(APP_PORT)
            self.running = False
            self.process = None
            self.startup_state = "idle"
            self.startup_error = ""
            return f"已清理 {killed} 个端口占用进程" if killed else "没有运行中的服务"
        self.startup_state = "idle"
        self.startup_error = ""
        return "服务未启动"

    def _build_prerequisite_checks(self, with_timing: bool = False):
        checks: list[dict] = []
        checks_ms: dict[str, int] = {}

        def timed(check_id: str, check) -> None:
            started = time.perf_counter()
            check()
            if with_timing:
                checks_ms[check_id] = round((time.perf_counter() - started) * 1000)
        def file_check(check_id: str, label: str, path: str, required: bool = True, repairable: bool = False) -> None:
            exists = os.path.exists(path)
            checks.append({
                "id": check_id,
                "label": label,
                "status": "ok" if exists else ("fail" if required else "warn"),
                "message": "已找到" if exists else ("缺失，可能导致启动失败" if required else "未找到，一键修复会尝试补齐"),
                "detail": path,
                "repairable": repairable and not exists,
            })

        def tool_check(
            check_id: str,
            label: str,
            bundled_path: str,
            command_names: tuple[str, ...],
            required: bool = True,
            repairable: bool = False,
        ) -> None:
            if os.path.exists(bundled_path):
                checks.append({
                    "id": check_id,
                    "label": label,
                    "status": "ok",
                    "message": "已找到",
                    "detail": bundled_path,
                    "repairable": False,
                })
                return

            system_path = next((path for path in (shutil.which(name) for name in command_names) if path), "")
            if system_path:
                checks.append({
                    "id": check_id,
                    "label": label,
                    "status": "ok",
                    "message": "已找到系统工具",
                    "detail": f"{system_path}；随包未找到: {bundled_path}",
                    "repairable": False,
                })
                return

            checks.append({
                "id": check_id,
                "label": label,
                "status": "fail" if required else "warn",
                "message": "缺失，可能导致启动失败" if required else "未找到，一键修复会尝试补齐",
                "detail": bundled_path,
                "repairable": repairable,
            })

        def first_existing(candidates: list[str]) -> str:
            for candidate in candidates:
                if candidate and os.path.exists(candidate):
                    return candidate
            return ""

        def git_bash_candidates_from_git(git_exe: str | None) -> list[str]:
            if not git_exe:
                return []
            git_dir = os.path.dirname(os.path.abspath(git_exe))
            roots = [git_dir]
            if os.path.basename(git_dir).lower() in {"cmd", "bin"}:
                roots.insert(0, os.path.dirname(git_dir))
            candidates: list[str] = []
            for root in roots:
                candidates.extend([
                    os.path.join(root, "bin", "bash.exe"),
                    os.path.join(root, "usr", "bin", "bash.exe"),
                    os.path.join(root, "bash.exe"),
                ])
            return candidates

        timed("node", lambda: tool_check("node", "Node.js 运行时", self.paths.node_exe, ("node.exe", "node"), repairable=True))
        timed("npm", lambda: tool_check("npm", "npm 包管理器", self.paths.npm_cli, ("npm.cmd", "npm.exe", "npm"), repairable=True))
        timed("data_dir", lambda: file_check("data_dir", "数据目录", self.paths.data_dir, required=False, repairable=True))
        git_started = time.perf_counter()
        bundled_git_path = first_existing([
            os.path.join(self.paths.base_path, "Git", "cmd", "git.exe"),
            os.path.join(self.paths.base_path, "git", "cmd", "git.exe"),
            os.path.join(self.paths.base_path, "SystemData", ".core", "Git", "cmd", "git.exe"),
            os.path.join(self.paths.base_path, "SystemData", ".core", "git", "cmd", "git.exe"),
        ])
        git_path = bundled_git_path or shutil.which("git")
        checks.append({
            "id": "git",
            "label": "Git",
            "status": "ok" if git_path else "fail",
            "message": "已找到" if git_path else "未找到；一键补齐会尝试安装 Git for Windows",
            "detail": git_path or "Git for Windows",
            "repairable": not bool(git_path),
        })
        if with_timing:
            checks_ms["git"] = round((time.perf_counter() - git_started) * 1000)
        git_bash_started = time.perf_counter()
        git_bash_path = first_existing([
            *git_bash_candidates_from_git(git_path),
            os.path.join(self.paths.base_path, "Git", "bin", "bash.exe"),
            os.path.join(self.paths.base_path, "Git", "usr", "bin", "bash.exe"),
            os.path.join(self.paths.base_path, "git", "bin", "bash.exe"),
            os.path.join(self.paths.base_path, "git", "usr", "bin", "bash.exe"),
            os.path.join(self.paths.base_path, "SystemData", ".core", "Git", "bin", "bash.exe"),
            os.path.join(self.paths.base_path, "SystemData", ".core", "Git", "usr", "bin", "bash.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Git", "bin", "bash.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Git", "usr", "bin", "bash.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Git", "bin", "bash.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Git", "usr", "bin", "bash.exe"),
        ])
        if not git_bash_path:
            path_bash = shutil.which("bash")
            if path_bash and "git" in path_bash.replace("\\", "/").lower().split("/"):
                git_bash_path = path_bash
        checks.append({
            "id": "git_bash",
            "label": "Git Bash",
            "status": "ok" if git_bash_path else "fail",
            "message": "已找到" if git_bash_path else "未找到；一键补齐会尝试安装 Git Bash",
            "detail": git_bash_path or "Git for Windows bash.exe",
            "repairable": not bool(git_bash_path),
        })
        if with_timing:
            checks_ms["git_bash"] = round((time.perf_counter() - git_bash_started) * 1000)
        uv_started = time.perf_counter()
        uv_path = shutil.which("uv")
        checks.append({
            "id": "uv",
            "label": "uv",
            "status": "ok" if uv_path else "warn",
            "message": "已找到" if uv_path else "未找到；Python 组件安装会使用备用流程",
            "detail": uv_path or "Python uv package manager",
            "repairable": not bool(uv_path),
        })
        if with_timing:
            checks_ms["uv"] = round((time.perf_counter() - uv_started) * 1000)
        timed("webview2", lambda: checks.append(self._webview2_check()))
        timed("python_runtime", lambda: checks.append(self._fast_python_runtime_check()))

        checks_by_id = {check["id"]: check for check in checks}
        checks = [checks_by_id[check_id] for check_id in (
            "python_runtime", "node", "npm", "git", "git_bash", "uv", "webview2", "data_dir",
        )]
        if with_timing:
            return checks, checks_ms
        return checks

    def diagnose_prerequisites(self) -> dict:
        started = time.perf_counter()
        checks, checks_ms = self._build_prerequisite_checks(with_timing=True)
        return {
            "basePath": self.paths.base_path,
            "serviceRunning": self.status().get("running", False),
            "servicePid": self.process.pid if self.process and self.process.poll() is None else None,
            "checks": checks,
            "timing": {
                "totalMs": round((time.perf_counter() - started) * 1000),
                "checksMs": checks_ms,
                "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
        }

    def diagnose_environment(self) -> dict:
        """Return customer-facing environment checks for the launcher."""
        prerequisite_checks = {check["id"]: check for check in self._build_prerequisite_checks()}

        def file_check(check_id: str, label: str, path: str, required: bool = True, repairable: bool = False) -> dict:
            exists = os.path.exists(path)
            return {"id": check_id, "label": label, "status": "ok" if exists else ("fail" if required else "warn"), "message": "已找到" if exists else ("缺失，可能导致启动失败" if required else "未找到，一键修复会尝试补齐"), "detail": path, "repairable": repairable and not exists}

        checks = [
            file_check("base_path", "安装目录", self.paths.base_path),
            self._storage_health_check(write_test=True),
            prerequisite_checks["node"],
            prerequisite_checks["npm"],
            prerequisite_checks["data_dir"],
            prerequisite_checks["git"],
            prerequisite_checks["git_bash"],
            prerequisite_checks["uv"],
            prerequisite_checks["webview2"],
            self._python_runtime_check(),
            self._portable_integrity_check(),
            self._security_software_block_check(),
            self._runtime_context_check(),
            self._phone_agent_apk_check(),
            self._member_gateway_check(),
            self._core_service_snapshot_check(),
        ]

        port_listeners = self._port_listeners(APP_PORT)
        expected_pid = str(self.process.pid) if self.process and self.process.poll() is None else None
        unexpected = [item for item in port_listeners if str(item.get("pid")) != expected_pid]
        if port_listeners:
            checks.append({
                "id": "port_18790",
                "label": "本地端口 18790",
                "status": "ok" if expected_pid and not unexpected else "warn",
                "message": "当前服务正在监听" if expected_pid and not unexpected else "端口被其他进程占用，一键修复可释放",
                "detail": "; ".join(self._format_process(item) for item in port_listeners),
                "repairable": not expected_pid or bool(unexpected),
            })
        else:
            checks.append({
                "id": "port_18790",
                "label": "本地端口 18790",
                "status": "ok",
                "message": "端口空闲，可以启动服务",
                "detail": "127.0.0.1:18790",
                "repairable": False,
            })

        bridge_listeners = self._port_range_listeners(18791, 18950, exclude_pids={str(os.getpid())})
        checks.append({
            "id": "bridge_ports",
            "label": "Bridge 管理端口",
            "status": "warn" if bridge_listeners else "ok",
            "message": f"发现 {len(bridge_listeners)} 个旧 Bridge 占用" if bridge_listeners else "未发现旧 Bridge 占用",
            "detail": "; ".join(self._format_process(item) for item in bridge_listeners) or "127.0.0.1:18791-18950",
            "repairable": bool(bridge_listeners),
        })

        stale_gateways = self._openclaw_gateway_processes()
        clawpanels = self._clawpanel_processes()
        stale_count = len(stale_gateways) + len(clawpanels)
        checks.append({
            "id": "stale_process",
            "label": "残留 OpenClaw/ClawPanel 进程",
            "status": "warn" if stale_count else "ok",
            "message": f"发现 {stale_count} 个残留进程" if stale_count else "未发现残留进程",
            "detail": "; ".join(self._format_process(item) for item in (stale_gateways + clawpanels)) or "clean",
            "repairable": stale_count > 0,
        })

        version = self._openclaw_version()
        checks.append({
            "id": "openclaw_version",
            "label": "OpenClaw 版本",
            "status": "ok" if version != "unknown" else "warn",
            "message": version if version != "unknown" else "未能读取版本号",
            "detail": os.path.join(os.path.dirname(self.paths.openclaw_mjs), "package.json"),
            "repairable": False,
        })

        status = self.status()
        snapshot = self._read_startup_snapshot()
        startup_duration_ms = snapshot.get("startupDurationMs") if isinstance(snapshot, dict) else None
        startup_timeline = snapshot.get("startupTimeline") if isinstance(snapshot, dict) and isinstance(snapshot.get("startupTimeline"), list) else []
        startup_stage = startup_timeline[-1].get("stage") if startup_timeline and isinstance(startup_timeline[-1], dict) else None

        return {
            "basePath": self.paths.base_path,
            "serviceRunning": status.get("running", False),
            "servicePid": self.process.pid if self.process and self.process.poll() is None else None,
            "startupState": status.get("startupState"),
            "startupElapsedSec": status.get("startupElapsedSec"),
            "startupTimeoutSec": status.get("startupTimeoutSec"),
            "startupError": status.get("startupError"),
            "startupDurationMs": startup_duration_ms if isinstance(startup_duration_ms, int) else None,
            "startupStage": startup_stage,
            "startupSnapshotPath": self._startup_snapshot_path(),
            "checks": checks,
        }

    def repair_environment(self) -> dict:
        """Clear stale runtime state that commonly blocks customer startup."""
        actions: list[dict] = []

        def record(label: str, count: int) -> None:
            actions.append({
                "label": label,
                "status": "ok",
                "message": f"已处理 {count} 项" if count else "无需处理",
                "count": count,
            })

        stopped_current = 0
        if self.process and self.process.poll() is None:
            if self._kill_pid(str(self.process.pid)):
                stopped_current = 1
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self.running = False
            self.process = None
        record("停止当前 OpenClaw 服务", stopped_current)
        record("停止已注册的 OpenClaw Gateway 任务", self._stop_registered_gateway())
        record("清理 ClawPanel 残留进程", self._kill_clawpanel_processes())
        record("清理 OpenClaw Gateway 残留进程", self._kill_openclaw_gateway_processes())
        record("释放 18790 端口", self._kill_port_processes(APP_PORT))
        record("释放旧 Bridge 端口", self._kill_port_range_processes(18791, 18950, exclude_pids={str(os.getpid())}))

        created = 0
        for path in (
            self.paths.data_dir,
            self.paths.state_dir,
            os.path.dirname(self.paths.auth_profiles),
        ):
            if not os.path.isdir(path):
                os.makedirs(path, exist_ok=True)
                created += 1
        record("补齐基础数据目录", created)

        config_changed, config_backup = self._ensure_openclaw_config()
        actions.append({
            "label": "修复 OpenClaw 基础配置",
            "status": "ok",
            "message": (
                f"已备份损坏配置并重建：{config_backup}"
                if config_backup else
                ("已补齐/重建 openclaw.json" if config_changed else "无需处理")
            ),
            "count": 1 if config_changed else 0,
        })

        storage_check = self._storage_health_check(write_test=True)
        actions.append({
            "label": "检测运行磁盘 / U盘健康",
            "status": storage_check["status"],
            "message": storage_check["message"],
            "count": 0,
        })

        preflight_checks = self.diagnose_environment().get("checks", [])
        actions.append(self._install_public_prerequisites_action(preflight_checks))
        actions.append(self._repair_webview2_runtime(preflight_checks))
        actions.append(self._prerequisite_source_check_action(preflight_checks))

        return {
            "actions": actions,
            "diagnostics": self.diagnose_environment(),
        }

    def repair_prerequisites(self) -> dict:
        """Repair install prerequisites without disturbing a running service."""
        actions: list[dict] = []
        preflight_checks = self.diagnose_prerequisites().get("checks", [])
        actions.append(self._install_public_prerequisites_action(preflight_checks))
        actions.append(self._repair_webview2_runtime(preflight_checks))
        actions.append(self._prerequisite_source_check_action(preflight_checks))

        created = 0
        if not os.path.isdir(self.paths.data_dir):
            os.makedirs(self.paths.data_dir, exist_ok=True)
            created = 1
        actions.append({
            "label": "补齐基础数据目录",
            "status": "ok",
            "message": "已创建数据目录" if created else "无需处理",
            "count": created,
        })
        diagnostics = self.diagnose_prerequisites()
        blocking = [
            check for check in diagnostics.get("checks", [])
            if str(check.get("status") or "").lower() == "fail"
        ]
        if blocking:
            names = "、".join(dict.fromkeys(str(check.get("label") or check.get("id") or "未知环境") for check in blocking))
            actions.append({
                "label": "复检前置环境",
                "status": "fail",
                "message": f"安装命令已结束，但以下环境仍未就绪：{names}",
                "count": len(blocking),
            })
        else:
            actions.append({
                "label": "复检前置环境",
                "status": "ok",
                "message": "前置环境复检通过",
                "count": 0,
            })
        restart_required = any(bool(action.get("restartRequired")) for action in actions)
        return {
            "ok": not blocking,
            "restartRequired": restart_required,
            "actions": actions,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _default_openclaw_config() -> dict:
        return {
            "gateway": {
                "auth": {"mode": "none"},
                "bind": "loopback",
            },
            "agents": {
                "defaults": {
                    "workspace": "data/.openclaw/workspace",
                    "contextInjection": "always",
                    "bootstrapPromptTruncationWarning": "once",
                }
            },
        }

    def _openclaw_config_check(self) -> dict:
        path = self.paths.openclaw_config
        if not os.path.exists(path):
            return {
                "id": "openclaw_config",
                "label": "OpenClaw 基础配置",
                "status": "warn",
                "message": "配置文件缺失，一键修复或启动服务时会自动重建",
                "detail": path,
                "repairable": True,
            }
        try:
            config = self._read_openclaw_config()
            if self._normalize_openclaw_config(config):
                return {
                    "id": "openclaw_config",
                    "label": "OpenClaw 基础配置",
                    "status": "warn",
                    "message": "配置文件可读取，但缺少基础 gateway 配置",
                    "detail": path,
                    "repairable": True,
                }
            return {
                "id": "openclaw_config",
                "label": "OpenClaw 基础配置",
                "status": "ok",
                "message": "配置文件格式正常",
                "detail": path,
                "repairable": False,
            }
        except Exception as error:
            return {
                "id": "openclaw_config",
                "label": "OpenClaw 基础配置",
                "status": "fail",
                "message": "配置文件格式损坏，一键修复会备份后重建",
                "detail": f"{path} ({error})",
                "repairable": True,
            }

    def _read_openclaw_config(self) -> dict:
        with open(self.paths.openclaw_config, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("root value is not an object")
        return config

    def _normalize_openclaw_config(self, config: dict) -> bool:
        changed = False
        gateway = config.get("gateway")
        if not isinstance(gateway, dict):
            gateway = {}
            config["gateway"] = gateway
            changed = True
        auth = gateway.get("auth")
        if not isinstance(auth, dict):
            auth = {}
            gateway["auth"] = auth
            changed = True
        if not auth.get("mode"):
            auth["mode"] = "none"
            changed = True
        if not gateway.get("bind"):
            gateway["bind"] = "loopback"
            changed = True
        agents = config.get("agents")
        if not isinstance(agents, dict):
            agents = {}
            config["agents"] = agents
            changed = True
        defaults = agents.get("defaults")
        if not isinstance(defaults, dict):
            defaults = {}
            agents["defaults"] = defaults
            changed = True
        if not defaults.get("workspace"):
            defaults["workspace"] = "data/.openclaw/workspace"
            changed = True
        if not defaults.get("contextInjection"):
            defaults["contextInjection"] = "always"
            changed = True
        if not defaults.get("bootstrapPromptTruncationWarning"):
            defaults["bootstrapPromptTruncationWarning"] = "once"
            changed = True
        channels = config.get("channels")
        if isinstance(channels, dict):
            legacy_lark_config = channels.get("openclaw-lark")
            feishu_config = channels.get("feishu")
            if isinstance(legacy_lark_config, dict):
                if not isinstance(feishu_config, dict):
                    channels["feishu"] = legacy_lark_config
                    feishu_config = legacy_lark_config
                del channels["openclaw-lark"]
                changed = True
            if isinstance(feishu_config, dict):
                domain = str(feishu_config.get("domain") or "").strip()
                if not domain or domain == "openclaw-lark":
                    feishu_config["domain"] = "feishu"
                    changed = True
        return changed

    def _write_openclaw_config(self, config: dict) -> None:
        os.makedirs(os.path.dirname(self.paths.openclaw_config), exist_ok=True)
        with open(self.paths.openclaw_config, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)

    def _backup_invalid_openclaw_config(self) -> str | None:
        path = self.paths.openclaw_config
        if not os.path.exists(path):
            return None
        backup = f"{path}.bad-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(path, backup)
            return backup
        except OSError:
            return None

    def _ensure_openclaw_config(self) -> tuple[bool, str | None]:
        if not os.path.exists(self.paths.openclaw_config):
            self._write_openclaw_config(self._default_openclaw_config())
            return True, None
        try:
            config = self._read_openclaw_config()
        except Exception:
            backup = self._backup_invalid_openclaw_config()
            self._write_openclaw_config(self._default_openclaw_config())
            return True, backup
        if self._normalize_openclaw_config(config):
            self._write_openclaw_config(config)
            return True, None
        return False, None

    def _ensure_openclaw_workspace(self) -> None:
        os.makedirs(self.paths.openclaw_workspace, exist_ok=True)
        template_dir = self.paths.openclaw_workspace_template
        if os.path.isdir(template_dir):
            for name in ("AGENTS.md", "SOUL.md", "TOOLS.md", "CAPABILITIES.md", "skills"):
                source = os.path.join(template_dir, name)
                target = os.path.join(self.paths.openclaw_workspace, name)
                if os.path.exists(target) or not os.path.exists(source):
                    if not os.path.isdir(source):
                        continue
                if os.path.isdir(source):
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, target)

        fallbacks = {
            "AGENTS.md": "# AGENTS.md - LOOM Portable Launcher Workspace\n\nUse the portable launcher capabilities before asking the user to move files manually.\n",
            "SOUL.md": "# SOUL.md - LOOM Portable Launcher\n\nBe careful, practical, and aware that this workspace runs inside a portable launcher.\n",
            "TOOLS.md": "# TOOLS.md - Portable Launcher Tools\n\nRead runtime-context.json for current paths and phone Agent state.\n",
            "CAPABILITIES.md": "# LOOM Portable Launcher Capability Map\n\nRead runtime-context.json for current capability state.\n",
        }
        for filename, content in fallbacks.items():
            target = os.path.join(self.paths.openclaw_workspace, filename)
            if not os.path.exists(target):
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(content)

    def _write_runtime_context(self) -> None:
        os.makedirs(self.paths.openclaw_workspace, exist_ok=True)
        runtime_context_path = os.path.join(self.paths.openclaw_workspace, "runtime-context.json")
        existing_context = self._read_json_if_exists(runtime_context_path)
        existing_capabilities = existing_context.get("capabilities") if isinstance(existing_context.get("capabilities"), dict) else {}
        existing_phone_agent = existing_capabilities.get("phoneAgent") if isinstance(existing_capabilities.get("phoneAgent"), dict) else {}
        package_json_path = os.path.join(self.paths.base_path, "package.json")
        launcher_runtime = self._read_json_if_exists(os.path.join(self.paths.data_dir, "launcher_runtime.json"))
        image_config = self._read_json_if_exists(self.paths.image_config)
        video_config = self._read_json_if_exists(self.paths.video_config)
        member_license = self._read_json_if_exists(self.paths.license_file)
        member_session = self._read_json_if_exists(self.paths.member_session_file)
        member_gateway_configured = False
        member_gateway_base = ""
        member_gateway_token = ""
        member_gateway_models: list[str] = []
        member_gateway_default_model = ""
        member_gateway_image_model = ""
        member_gateway_video_draft_model = ""
        for gateway_source in (member_license, member_session):
            if not isinstance(gateway_source, dict):
                continue
            gateway = gateway_source.get("gateway") if isinstance(gateway_source.get("gateway"), dict) else {}
            member_gateway_base = str(
                gateway_source.get("gatewayBaseUrl")
                or gateway_source.get("gatewayUrl")
                or gateway_source.get("baseUrl")
                or gateway.get("baseUrl")
                or gateway.get("url")
                or ""
            ).strip()
            member_gateway_token = str(
                gateway_source.get("gatewayAccessToken")
                or gateway_source.get("gatewayToken")
                or gateway_source.get("memberToken")
                or gateway_source.get("apiKey")
                or gateway.get("apiKey")
                or gateway.get("token")
                or ""
            ).strip()
            raw_models = (
                gateway_source.get("gatewayModels")
                if isinstance(gateway_source.get("gatewayModels"), list)
                else gateway_source.get("models")
            )
            if not isinstance(raw_models, list):
                raw_models = gateway.get("models") if isinstance(gateway.get("models"), list) else []
            member_gateway_models = []
            for item in raw_models:
                model_id = item.get("id") if isinstance(item, dict) else item
                if isinstance(model_id, str):
                    clean = model_id.strip()
                    if clean and clean not in member_gateway_models:
                        member_gateway_models.append(clean)
            member_gateway_default_model = str(
                gateway_source.get("gatewayDefaultModel")
                or gateway_source.get("defaultModel")
                or gateway_source.get("model")
                or gateway.get("defaultModel")
                or gateway.get("model")
                or ""
            ).strip()
            member_gateway_image_base = str(
                gateway_source.get("gatewayImageBaseUrl")
                or gateway_source.get("imageBaseUrl")
                or gateway.get("imageBaseUrl")
                or member_gateway_base
            ).strip()
            member_gateway_video_base = str(
                gateway_source.get("gatewayVideoBaseUrl")
                or gateway_source.get("videoBaseUrl")
                or gateway.get("videoBaseUrl")
                or member_gateway_base
            ).strip()
            member_gateway_image_model = str(
                gateway_source.get("gatewayImageModel")
                or gateway_source.get("imageModel")
                or gateway.get("imageModel")
                or ""
            ).strip()
            member_gateway_video_draft_model = str(
                gateway_source.get("gatewayVideoDraftModel")
                or gateway_source.get("videoDraftModel")
                or gateway_source.get("gatewayVideoModel")
                or gateway_source.get("videoModel")
                or gateway.get("videoDraftModel")
                or gateway.get("videoModel")
                or ""
            ).strip()
            member_gateway_configured = bool(member_gateway_base and member_gateway_token)
            if member_gateway_configured:
                break
        phone_store = self._read_json_if_exists(os.path.join(self.paths.launcher_dir, "phone-agents.json"))
        phone_config = self._read_json_if_exists(os.path.join(self.paths.launcher_dir, "phone-agent.json"))
        desktop_config = self._read_json_if_exists(os.path.join(self.paths.launcher_dir, "desktop-agent.json"))
        launcher_version = "unknown"
        if launcher_runtime.get("version"):
            launcher_version = str(launcher_runtime.get("version"))
        else:
            package_data = self._read_json_if_exists(package_json_path)
            if package_data.get("name") == "openclaw-new-launcher":
                launcher_version = str(package_data.get("version") or "unknown")
        phone_devices: list[dict] = []
        selected_device_id = ""
        phone_config_path = "data/.openclaw/launcher/phone-agent.json"
        selected_phone_config = phone_config if isinstance(phone_config, dict) else {}
        if isinstance(phone_store, dict) and isinstance(phone_store.get("devices"), list) and phone_store.get("devices"):
            phone_config_path = "data/.openclaw/launcher/phone-agents.json"
            selected_device_id = str(phone_store.get("selectedDeviceId") or "").strip()
            raw_devices = [device for device in phone_store.get("devices", []) if isinstance(device, dict)]
            selected_phone_config = next(
                (device for device in raw_devices if str(device.get("id") or "").strip() == selected_device_id),
                raw_devices[0] if raw_devices else {},
            )
            phone_devices = [
                {
                    "id": str(device.get("id") or "").strip() or None,
                    "name": str(device.get("name") or "").strip() or None,
                    "tokenAvailable": bool(str(device.get("token") or "").strip()),
                    "baseUrl": None,
                    "tags": device.get("tags") if isinstance(device.get("tags"), list) else [],
                    "lastSeenAt": str(device.get("lastSeenAt") or "").strip() or None,
                }
                for device in raw_devices
            ]
        elif isinstance(phone_config, dict) and (str(phone_config.get("baseUrl") or "").strip() or str(phone_config.get("token") or "").strip()):
            selected_device_id = str(phone_config.get("id") or "").strip()
            phone_devices = [{
                "id": selected_device_id or None,
                "name": str(phone_config.get("name") or "Android Phone").strip() or "Android Phone",
                "tokenAvailable": bool(str(phone_config.get("token") or "").strip()),
                "baseUrl": None,
                "tags": [],
                "lastSeenAt": None,
            }]
        phone_album = str(selected_phone_config.get("album") or os.environ.get("OPENCLAW_PHONE_ALBUM") or "LOOM") if isinstance(selected_phone_config, dict) else "LOOM"
        phone_url = str(selected_phone_config.get("baseUrl") or "").rstrip("/") if isinstance(selected_phone_config, dict) else ""
        token_available = bool(str(selected_phone_config.get("token") or "").strip()) if isinstance(selected_phone_config, dict) else False
        desktop_port = int(desktop_config.get("port") or 21900) if isinstance(desktop_config, dict) else 21900
        desktop_agent_dir = str(desktop_config.get("agentDir") or "").strip() if isinstance(desktop_config, dict) else ""
        desktop_token_available = bool(str(desktop_config.get("token") or "").strip()) if isinstance(desktop_config, dict) else False
        verified_phone_version = str(existing_phone_agent.get("verifiedVersion") or "").strip()
        try:
            verified_phone_version_code = int(existing_phone_agent.get("verifiedVersionCode") or 0)
        except Exception:
            verified_phone_version_code = 0
        if not verified_phone_version:
            verified_phone_version = "unknown"
        if verified_phone_version_code <= 0:
            verified_phone_version_code = None
        context = {
            "schema": "openclaw.launcher.runtime-context.v1",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "launcher": {
                "name": "LOOM Portable Launcher",
                "version": launcher_version,
                "mode": "usb-portable",
                "root": self.paths.base_path,
            },
            "openclaw": {
                "version": self._openclaw_version(),
                "configPath": self.paths.openclaw_config,
                "workspacePath": self.paths.openclaw_workspace,
                "memberGateway": {
                    "configured": member_gateway_configured,
                    "baseUrl": member_gateway_base or None,
                    "imageBaseUrl": member_gateway_image_base or member_gateway_base or None,
                    "videoBaseUrl": member_gateway_video_base or member_gateway_base or None,
                    "defaultModel": member_gateway_default_model or None,
                    "imageModel": member_gateway_image_model or None,
                    "videoDraftModel": member_gateway_video_draft_model or None,
                    "models": member_gateway_models,
                },
            },
            "workspace": {
                "path": self.paths.openclaw_workspace,
                "bootstrapFiles": ["AGENTS.md", "SOUL.md", "TOOLS.md", "CAPABILITIES.md"],
                "skillsPath": os.path.join(self.paths.openclaw_workspace, "skills"),
            },
            "paths": {
                "generatedImages": self.paths.generated_images_dir,
                "scripts": self.paths.scripts_dir,
                "imageToPhoneCli": os.path.join(self.paths.scripts_dir, "openclaw-image-phone.mjs"),
                "phoneVerifier": os.path.join(self.paths.scripts_dir, "verify-phone-agent.ps1"),
                "phoneFleetCli": os.path.join(self.paths.scripts_dir, "openclaw-phone-fleet.mjs"),
                "desktopAgentCli": os.path.join(self.paths.scripts_dir, "openclaw-desktop-agent.mjs"),
            },
            "capabilities": {
                "imageGeneration": {
                    "available": True,
                    "configured": self._has_config_values(image_config) or member_gateway_configured,
                    "localOutputDir": self.paths.generated_images_dir,
                    "cli": "npm run phone:image",
                    "editCli": 'npm run phone:image:edit -- --reference-image <path> --prompt "<edit instruction>"',
                    "model": image_config.get("model") if isinstance(image_config, dict) else None,
                    "memberModel": member_gateway_image_model or None,
                },
                "videoGeneration": {
                    "available": True,
                    "configured": self._has_config_values(video_config) or member_gateway_configured,
                    "model": video_config.get("model") if isinstance(video_config, dict) else None,
                    "memberModel": member_gateway_video_draft_model or None,
                },
                "phoneAgent": {
                    "available": True,
                    "configured": bool(phone_url and token_available),
                    "endpoint": "launcher-cli-wrapper",
                    "defaultAlbum": phone_album,
                    "galleryPath": f"Pictures/{phone_album}",
                    "verifiedVersion": verified_phone_version,
                    "verifiedVersionCode": verified_phone_version_code,
                    "maxRoundsPerTask": 60,
                    "agentCli": "npm run phone:agent --",
                    "fleetCli": "npm run phone:fleet --",
                    "secureCli": "npm run phone:secure --",
                    "visionCli": "npm run phone:vision --",
                    "imageCli": "npm run phone:image --",
                    "imageEditCli": 'npm run phone:image:edit -- --reference-image <path> --prompt "<edit instruction>"',
                    "videoCli": "npm run phone:video --",
                    "multiDevice": len(phone_devices) > 1,
                    "defaultDeviceId": selected_device_id or None,
                    "deviceCliArg": "--device-id <id>",
                    "fleetTargets": "--target <id|id,id|all>",
                    "controlPolicy": "wrapper-only",
                    "tokenPolicy": "never expose token; never call APKClaw HTTP APIs directly; use launcher CLI wrappers only",
                },
                "desktopAgent": {
                    "available": True,
                    "configured": bool(desktop_agent_dir or desktop_token_available),
                    "endpoint": "launcher-bridge",
                    "localPort": desktop_port,
                    "configPath": "data/.openclaw/launcher/desktop-agent.json",
                    "tokenAvailable": desktop_token_available,
                    "agentCli": "npm run desktop:agent --",
                    "replyCli": "npm run desktop:reply --",
                    "replyPolicy": "observe first; send only with explicit --confirmed user approval",
                    "tokenPolicy": "never expose token; call through launcher Bridge /api/desktop-agent/*",
                    "tools": [
                        "desktop.status",
                        "desktop.health",
                        "desktop.start",
                        "desktop.stop",
                        "desktop.screenshot",
                        "desktop.click",
                        "desktop.type",
                        "wechat.send",
                        "wechat.unread",
                        "desktop.reply.observe",
                        "desktop.reply.once",
                    ],
                },
                "portableRuntime": {
                    "available": True,
                    "preferRelativePaths": True,
                },
            },
            "phone": {
                "configured": bool(phone_url and token_available),
                "connected": False,
                "endpoint": "launcher-cli-wrapper",
                "baseUrl": None,
                "tokenAvailable": token_available,
                "configPath": phone_config_path,
                "defaultDeviceId": selected_device_id or None,
                "devices": phone_devices,
                "lastStatus": None,
            },
            "desktop": {
                "configured": bool(desktop_agent_dir or desktop_token_available),
                "endpoint": "launcher-bridge",
                "localPort": desktop_port,
                "agentDir": desktop_agent_dir or None,
                "tokenAvailable": desktop_token_available,
                "configPath": "data/.openclaw/launcher/desktop-agent.json",
            },
            "policies": {
                "autoSendGeneratedImagesToPhone": "enabled_when_phone_configured",
                "autoUploadPersonalFiles": False,
                "neverExposeSecrets": True,
            },
        }
        with open(runtime_context_path, "w", encoding="utf-8") as handle:
            json.dump(context, handle, ensure_ascii=False, indent=2)

    def _read_json_if_exists(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _has_config_values(self, value: dict) -> bool:
        return any(isinstance(item, str) and bool(item.strip()) for item in value.values())

    def _member_gateway_check(self) -> dict:
        license_data = self._read_json_if_exists(self.paths.license_file)
        if not isinstance(license_data, dict):
            license_data = {}
        base_url = str(license_data.get("gatewayBaseUrl") or license_data.get("gatewayUrl") or "").strip()
        token = str(license_data.get("gatewayAccessToken") or license_data.get("gatewayToken") or "").strip()
        plan = str(license_data.get("plan") or license_data.get("edition") or "").strip()
        if base_url and token:
            return {
                "id": "member_gateway",
                "label": "会员托管网关",
                "status": "ok",
                "message": f"已配置 {plan or 'member'} 网关",
                "detail": f"{base_url} | token=present",
                "repairable": False,
            }
        if base_url or token:
            return {
                "id": "member_gateway",
                "label": "会员托管网关",
                "status": "warn",
                "message": "会员网关字段不完整，启动器会回退到本地 API 配置",
                "detail": f"baseUrl={bool(base_url)} token={bool(token)}",
                "repairable": False,
            }
        return {
            "id": "member_gateway",
            "label": "会员托管网关",
            "status": "warn",
            "message": "未配置会员托管网关",
            "detail": self.paths.license_file,
            "repairable": False,
        }

    def _logs_dir(self) -> str:
        return os.path.join(self.paths.data_dir, "logs")

    def _startup_snapshot_path(self) -> str:
        return os.path.join(self._logs_dir(), "openclaw-startup-snapshot.json")

    def _append_output_tail(self, line: str) -> None:
        self._output_tail.append(line.rstrip("\r\n"))
        if len(self._output_tail) > 120:
            self._output_tail = self._output_tail[-120:]

    def _mark_startup_stage(self, stage: str, detail: str = "") -> None:
        if self._startup_started_perf is None:
            return
        elapsed_ms = int((time.perf_counter() - self._startup_started_perf) * 1000)
        entry = {
            "stage": stage,
            "elapsedMs": elapsed_ms,
        }
        if detail:
            entry["detail"] = detail
        self._startup_timeline.append(entry)
        if len(self._startup_timeline) > 24:
            self._startup_timeline = self._startup_timeline[-24:]
        detail_text = f" {detail}" if detail else ""
        self.append_log(f"[OpenClaw] startup stage={stage} elapsed={elapsed_ms}ms{detail_text}\n")

    def _write_startup_snapshot(self, status: str, error: str, exit_code: int | None, port_ready: bool) -> None:
        elapsed_ms = int((time.perf_counter() - self._startup_started_perf) * 1000) if self._startup_started_perf else None
        snapshot = {
            "schema": "openclaw.launcher.core-startup-snapshot.v1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": status,
            "error": error,
            "exitCode": exit_code,
            "pid": self.process.pid if self.process else None,
            "command": self._last_start_command,
            "cwd": self.paths.base_path,
            "port": APP_PORT,
            "portReady": port_ready,
            "node": self.paths.node_exe,
            "startJs": self.paths.find_file("start.js", ("back", "backup", "")),
            "startupDurationMs": elapsed_ms,
            "startupTimeline": self._startup_timeline[-16:],
            "outputTail": self._output_tail[-80:],
        }
        try:
            os.makedirs(self._logs_dir(), exist_ok=True)
            with open(self._startup_snapshot_path(), "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        except Exception as write_error:
            self.append_log(f"[OpenClaw] Failed to write startup snapshot: {write_error}\n")

    def _read_startup_snapshot(self) -> dict:
        return self._read_json_if_exists(self._startup_snapshot_path())

    def _core_service_snapshot_check(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        port_ready = self._is_port_listening(APP_PORT)
        snapshot = self._read_startup_snapshot()
        if running and port_ready:
            duration_ms = snapshot.get("startupDurationMs")
            duration_text = f"；startup={duration_ms}ms" if isinstance(duration_ms, int) else ""
            return {
                "id": "core_service_snapshot",
                "label": "OpenClaw 核心服务状态",
                "status": "ok",
                "message": f"核心服务正在运行，端口 {APP_PORT} 可访问{duration_text}",
                "detail": f"pid={self.process.pid if self.process else '-'}；snapshot={self._startup_snapshot_path()}",
                "repairable": False,
            }

        if running and self.startup_state == "starting":
            elapsed = int(time.time() - self.startup_started_at) if self.startup_started_at else 0
            timeline = snapshot.get("startupTimeline") if isinstance(snapshot.get("startupTimeline"), list) else []
            last_stage = timeline[-1].get("stage") if timeline and isinstance(timeline[-1], dict) else "starting"
            return {
                "id": "core_service_snapshot",
                "label": "OpenClaw 核心服务状态",
                "status": "warn",
                "message": f"核心服务仍在启动中，已等待 {elapsed}s，当前阶段：{last_stage}，端口 {APP_PORT} 尚未就绪",
                "detail": (
                    f"pid={self.process.pid if self.process else '-'}；"
                    f"timeout={self.startup_timeout_sec}s；"
                    f"snapshot={self._startup_snapshot_path()}"
                ),
                "repairable": False,
            }

        if snapshot.get("status") == "fail":
            output_tail = snapshot.get("outputTail") if isinstance(snapshot.get("outputTail"), list) else []
            output_text = "\n".join(str(line) for line in output_tail[-12:])
            duration_ms = snapshot.get("startupDurationMs")
            duration_text = f"startup={duration_ms}ms；" if isinstance(duration_ms, int) else ""
            detail = (
                f"error={snapshot.get('error') or '-'}；"
                f"exitCode={snapshot.get('exitCode')}; "
                f"pid={snapshot.get('pid')}; "
                f"portReady={snapshot.get('portReady')}; "
                f"{duration_text}"
                f"command={' '.join(str(item) for item in snapshot.get('command', []))}; "
                f"snapshot={self._startup_snapshot_path()}"
            )
            if output_text:
                detail = f"{detail}\n--- output tail ---\n{output_text}"
            return {
                "id": "core_service_snapshot",
                "label": "OpenClaw 核心服务状态",
                "status": "fail",
                "message": "最近一次核心服务启动失败，已捕获启动快照",
                "detail": detail,
                "repairable": True,
            }

        if self.startup_state == "failed" or self.startup_error:
            error_text = self.startup_error or "OpenClaw startup failed"
            return {
                "id": "core_service_snapshot",
                "label": "OpenClaw 核心服务状态",
                "status": "fail",
                "message": "核心服务启动失败，但没有读取到完整启动快照",
                "detail": (
                    f"error={error_text}; "
                    f"portReady={port_ready}; "
                    f"snapshot={self._startup_snapshot_path()}"
                ),
                "repairable": True,
            }

        if port_ready:
            listeners = self._port_listeners(APP_PORT)
            return {
                "id": "core_service_snapshot",
                "label": "OpenClaw 核心服务状态",
                "status": "warn",
                "message": f"端口 {APP_PORT} 有监听，但不是当前 Bridge 管理的核心进程",
                "detail": "; ".join(self._format_process(item) for item in listeners) or f"127.0.0.1:{APP_PORT}",
                "repairable": True,
            }

        return {
            "id": "core_service_snapshot",
            "label": "OpenClaw 核心服务状态",
            "status": "warn",
            "message": "核心服务当前未运行；如果刚点击过启动失败，请再次诊断查看失败快照",
            "detail": f"port={APP_PORT}；snapshot={self._startup_snapshot_path()}",
            "repairable": False,
        }

    def _run_command(self, command: list[str], timeout_sec: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_sec,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def phone_adb_doctor(
        self,
        *,
        serial: str | None = None,
        wake: bool = True,
        launch: bool = True,
        restart_server: bool = True,
    ) -> dict:
        """Repair the host-side ADB path without bypassing APKClaw permissions."""
        adb_path = self._find_adb_path()
        result = {
            "schema": "loom.phone.adb_doctor.v1",
            "ok": False,
            "status": "unknown",
            "adbPath": adb_path,
            "selectedDevice": "",
            "devices": [],
            "actions": [],
            "instructions": [],
            "message": "",
        }
        if not adb_path:
            result.update({
                "status": "missing_adb",
                "message": "未找到 ADB，无法通过 USB 调试唤醒或拉起手机端。",
                "instructions": [
                    "把 Android platform-tools 放到 LOOMFiles/platform-tools/adb.exe 或安装到系统 PATH。",
                    "安装后重新运行 phone adb-doctor，再打开 APKClaw -> Settings -> LAN Config。",
                ],
            })
            return result

        devices = self._adb_devices(adb_path)
        result["devices"] = devices
        if not devices and restart_server:
            result["actions"].append(self._run_adb(adb_path, ["kill-server"], timeout_sec=10, label="restart.kill_server"))
            result["actions"].append(self._run_adb(adb_path, ["start-server"], timeout_sec=10, label="restart.start_server"))
            devices = self._adb_devices(adb_path)
            result["devices"] = devices

        if not devices:
            result.update({
                "status": "no_device",
                "message": "ADB 已找到，但没有检测到手机。",
                "instructions": [
                    "请用 USB 连接手机，开启开发者选项和 USB 调试。",
                    "手机弹出 RSA 授权时点允许；然后打开 APKClaw -> Settings -> LAN Config。",
                    "如果是多台手机，请确认每台手机都授权本电脑。",
                ],
            })
            return result

        requested_serial = (serial or "").strip()
        if requested_serial and not any(str(device.get("serial") or "") == requested_serial for device in devices):
            result.update({
                "status": "device_not_found",
                "message": f"没有找到指定手机：{requested_serial}。",
                "instructions": [
                    "请运行 adb devices -l 或 phone adb-doctor 不带 serial 查看当前设备列表。",
                    "确认要修复的手机 serial 后再重试，避免误操作其他手机。",
                ],
            })
            return result
        if not requested_serial and len(devices) > 1:
            result.update({
                "status": "multiple_devices",
                "message": "检测到多台手机，请先选择要修复的设备。",
                "instructions": [
                    "运行 phone adb-doctor --serial <设备 serial>，避免误唤醒或误拉起其他手机。",
                    "设备 serial 可从当前返回的 devices 列表，或 adb devices -l 中查看。",
                ],
            })
            return result

        selected = self._select_adb_device(devices, serial)
        result["selectedDevice"] = selected.get("serial", "")
        state = str(selected.get("state") or "").lower()
        if state == "unauthorized":
            result.update({
                "status": "unauthorized",
                "message": "手机已连接，但还没有授权本电脑的 USB 调试。",
                "instructions": [
                    "请解锁手机，在 USB 调试授权弹窗里选择允许。",
                    "如果没看到弹窗，拔插 USB 或在开发者选项里撤销 USB 调试授权后重试。",
                ],
            })
            return result
        if state == "offline":
            if restart_server:
                serial_arg = ["-s", selected["serial"]]
                result["actions"].append(self._run_adb(adb_path, [*serial_arg, "reconnect"], timeout_sec=20, label="device.reconnect"))
                devices = self._adb_devices(adb_path)
                result["devices"] = devices
                selected = self._select_adb_device(devices, selected["serial"])
                result["selectedDevice"] = selected.get("serial", "")
                state = str(selected.get("state") or "").lower()
            if state != "device":
                result.update({
                    "status": "offline",
                    "message": "手机处于 offline 状态，ADB 暂时无法控制。",
                    "instructions": [
                        "请拔插 USB，重新授权 USB 调试，必要时重启手机端 APKClaw。",
                        "恢复后打开 APKClaw -> Settings -> LAN Config，再重新检测连接。",
                    ],
                })
                return result
        if state != "device":
            result.update({
                "status": "bad_state",
                "message": f"手机 ADB 状态异常：{state or 'unknown'}。",
                "instructions": [
                    "请确认手机已解锁、USB 调试已开启，并允许本电脑调试。",
                    "打开 APKClaw -> Settings -> LAN Config 后再试。",
                ],
            })
            return result

        serial_arg = ["-s", selected["serial"]]
        if wake:
            result["actions"].append(self._run_adb(adb_path, [*serial_arg, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout_sec=10, label="device.wake"))
            result["actions"].append(self._run_adb(adb_path, [*serial_arg, "shell", "wm", "dismiss-keyguard"], timeout_sec=10, label="device.dismiss_keyguard"))
            result["actions"].append(self._run_adb(adb_path, [*serial_arg, "shell", "input", "keyevent", "KEYCODE_HOME"], timeout_sec=10, label="device.home"))
        launched_package = ""
        if launch:
            for package_name in self._apkclaw_package_candidates():
                action = self._run_adb(
                    adb_path,
                    [*serial_arg, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
                    timeout_sec=15,
                    label=f"apkclaw.launch:{package_name}",
                )
                result["actions"].append(action)
                combined = f"{action.get('stdout', '')}\n{action.get('stderr', '')}".lower()
                if action.get("ok") and "no activities found" not in combined and "monkey aborted" not in combined:
                    launched_package = package_name
                    break

        result.update({
            "ok": True,
            "status": "ready",
            "launchedPackage": launched_package,
            "message": (
                f"ADB 已连接并尝试拉起 APKClaw（{launched_package}）。"
                if launched_package else
                "ADB 已连接并已唤醒手机；未确认 APKClaw 已自动拉起，请在手机端手动打开一次。"
            ),
            "instructions": [
                "接下来运行 phone status 或 phone screenshot 验证 LAN Config 是否可用。",
                "如果仍连不上，请打开 APKClaw -> Settings -> LAN Config，并确认手机与电脑在同一网络。",
            ],
        })
        return result

    def _find_adb_path(self) -> str:
        return self.paths.adb_exe

    def _adb_devices(self, adb_path: str) -> list[dict]:
        action = self._run_adb(adb_path, ["devices", "-l"], timeout_sec=15, label="devices")
        devices: list[dict] = []
        for line in str(action.get("stdout") or "").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("list of devices"):
                continue
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            devices.append({
                "serial": parts[0],
                "state": parts[1],
                "detail": parts[2] if len(parts) > 2 else "",
            })
        return devices

    def _select_adb_device(self, devices: list[dict], serial: str | None) -> dict:
        serial = (serial or "").strip()
        if serial:
            for device in devices:
                if str(device.get("serial") or "") == serial:
                    return device
        for device in devices:
            if str(device.get("state") or "").lower() == "device":
                return device
        return devices[0] if devices else {}

    def _run_adb(self, adb_path: str, args: list[str], *, timeout_sec: int, label: str) -> dict:
        command = [adb_path, *args]
        started = time.perf_counter()
        try:
            completed = self.command_runner(command, timeout_sec)
            stdout = self._limit_text(getattr(completed, "stdout", "") or "")
            stderr = self._limit_text(getattr(completed, "stderr", "") or "")
            code = int(getattr(completed, "returncode", 1))
            return {
                "label": label,
                "command": self._public_command(command),
                "ok": code == 0,
                "code": code,
                "stdout": stdout,
                "stderr": stderr,
                "durationMs": int((time.perf_counter() - started) * 1000),
            }
        except subprocess.TimeoutExpired as error:
            return {
                "label": label,
                "command": self._public_command(command),
                "ok": False,
                "code": "timeout",
                "stdout": self._limit_text(getattr(error, "stdout", "") or ""),
                "stderr": self._limit_text(getattr(error, "stderr", "") or "ADB command timed out"),
                "durationMs": int((time.perf_counter() - started) * 1000),
            }
        except Exception as error:
            return {
                "label": label,
                "command": self._public_command(command),
                "ok": False,
                "code": "error",
                "stdout": "",
                "stderr": self._limit_text(str(error)),
                "durationMs": int((time.perf_counter() - started) * 1000),
            }

    @staticmethod
    def _public_command(command: list[str]) -> list[str]:
        return [os.path.basename(command[0]) if command else "", *command[1:]]

    @staticmethod
    def _limit_text(value: object, limit: int = 1200) -> str:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _apkclaw_package_candidates() -> tuple[str, ...]:
        return (
            "com.apk.claw.android",
            "com.openclaw.agentphone",
            "ai.openclaw.agentphone",
            "com.lumi.apkclaw",
            "com.lumi.openclaw",
            "com.hermes.agentphone",
        )

    def _install_public_prerequisites_action(self, checks: list[dict]) -> dict:
        package_rules = (
            (("git", "git_bash"), "Git", "Git.Git"),
            (("node", "npm"), "Node.js", "OpenJS.NodeJS.LTS"),
            (("python_runtime",), "Python", "Python.Python.3.11"),
            (("uv",), "uv", "astral-sh.uv"),
        )
        missing_packages: list[tuple[str, str]] = []
        seen_package_ids: set[str] = set()
        for check_ids, label, package_id in package_rules:
            if package_id in seen_package_ids:
                continue
            missing = any(
                str(check.get("id") or "") in check_ids and str(check.get("status") or "") in {"fail", "warn"}
                for check in checks
            )
            if missing:
                missing_packages.append((label, package_id))
                seen_package_ids.add(package_id)

        if not missing_packages:
            return {
                "label": "安装公共前置环境",
                "status": "ok",
                "message": "Git、Node.js、Python 和 uv 已就绪，无需安装",
                "count": 0,
            }

        failures: list[str] = []
        installed: list[str] = []
        restart_required = False
        if missing_packages:
            try:
                winget_check = self.command_runner(["winget", "--version"], 20)
                winget_code = int(getattr(winget_check, "returncode", 0) or 0)
                if winget_code != 0:
                    winget_output = (
                        (getattr(winget_check, "stdout", "") or "")
                        + "\n"
                        + (getattr(winget_check, "stderr", "") or "")
                    ).strip()
                    failures.append(
                        f"winget 不可用，退出码 {winget_code}："
                        f"{self._limit_text(winget_output, 180) or '请安装或修复 Windows 应用安装程序后重试'}"
                    )
            except Exception as error:
                winget_code = 1
                failures.append(f"winget 不可用：{error}")
            if winget_code == 0:
                for label, package_id in missing_packages:
                    command = [
                        "winget",
                        "install",
                        "--id",
                        package_id,
                        "--exact",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                        "--disable-interactivity",
                        "--source",
                        "winget",
                        "--silent",
                    ]
                    package_installed = False
                    last_failure = ""
                    for attempt_index, delay in enumerate(PREREQUISITE_RETRY_DELAYS_SECONDS, start=1):
                        if delay > 0:
                            self.retry_sleep(delay)
                        try:
                            result = self.command_runner(command, 1800)
                            code = int(getattr(result, "returncode", 0) or 0)
                            output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
                        except Exception as error:
                            code = -1
                            output = str(error)
                        if code in (0, 3010):
                            installed.append(label)
                            restart_required = True
                            package_installed = True
                            break
                        last_failure = f"{label} 安装失败，退出码 {code}：{self._limit_text(output, 180) or '请手动运行 winget 后重试'}"
                        can_retry = attempt_index < len(PREREQUISITE_RETRY_DELAYS_SECONDS) and _is_transient_winget_failure(output)
                        if not can_retry:
                            break
                        self.append_log(f"[Diagnostics] {label} winget install failed transiently; retrying attempt {attempt_index + 1}\n")
                    if not package_installed:
                        failures.append(last_failure or f"{label} 安装命令失败")

        if installed:
            _refresh_process_path_from_windows_registry()

        if failures:
            return {
                "label": "安装公共前置环境",
                "status": "fail" if not installed else "warn",
                "message": "；".join(failures),
                "count": len(installed),
            }
        return {
            "label": "安装公共前置环境",
            "status": "ok",
            "message": f"已执行公共前置安装：{'、'.join(installed)}。安装完成后可能需要重启 LOOM 或重新打开终端。",
            "count": len(installed),
            "restartRequired": restart_required,
        }


    def _webview2_redist_path(self) -> str:
        redist_candidates = [
            os.path.join(self.paths.base_path, "redist", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
            os.path.join(self.paths.base_path, "_up_", "redist", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
        ]
        return next((path for path in redist_candidates if os.path.isfile(path)), "")

    def _repair_webview2_runtime(self, checks: list[dict]) -> dict:
        webview2 = next((check for check in checks if check.get("id") == "webview2"), None)
        if not isinstance(webview2, dict):
            webview2 = self._webview2_check()
        if webview2.get("status") == "ok":
            return {
                "label": "安装 WebView2 Runtime",
                "status": "ok",
                "message": "已检测到 WebView2 Runtime，无需处理",
                "count": 0,
            }
        if not webview2.get("repairable"):
            return {
                "label": "安装 WebView2 Runtime",
                "status": "warn",
                "message": "未检测到 WebView2 Runtime，且包内缺少离线安装器。请使用完整 LOOM 离线包或先安装 Microsoft Edge WebView2 Runtime。",
                "count": 0,
            }

        installer = self._webview2_redist_path()
        if not installer:
            return {
                "label": "安装 WebView2 Runtime",
                "status": "warn",
                "message": "WebView2 可修复，但未找到随包离线安装器。请使用完整 LOOM 离线包。",
                "count": 0,
            }

        command = [installer, "/silent", "/install"]
        self.append_log(f"[Diagnostics] Installing WebView2 Runtime from bundled offline installer: {installer}\n")
        try:
            result = self.command_runner(command, 180)
        except subprocess.TimeoutExpired:
            return {
                "label": "安装 WebView2 Runtime",
                "status": "fail",
                "message": "WebView2 离线安装器执行超时，请稍后重试或手动运行 redist 目录中的安装器。",
                "count": 0,
            }
        except Exception as error:
            return {
                "label": "安装 WebView2 Runtime",
                "status": "fail",
                "message": f"WebView2 离线安装器启动失败：{error}",
                "count": 0,
            }

        code = int(getattr(result, "returncode", 0) or 0)
        if code in (0, 3010):
            return {
                "label": "安装 WebView2 Runtime",
                "status": "ok",
                "message": "已执行 WebView2 离线安装器；如窗口仍异常，请重启 LOOM 后重新检测。",
                "count": 1,
            }
        output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
        if len(output) > 240:
            output = output[:240] + "..."
        return {
            "label": "安装 WebView2 Runtime",
            "status": "fail",
            "message": f"WebView2 离线安装器返回 {code}。{output or '请以管理员身份重试，或手动运行 redist 目录中的安装器。'}",
            "count": 0,
        }

    def _prerequisite_source_check_action(self, checks: list[dict]) -> dict:
        required_labels = {
            "node": "Node.js",
            "npm": "npm",
            "python_runtime": "Python",
            "git": "Git",
            "git_bash": "Git Bash",
        }
        missing: list[str] = []
        for check in checks:
            check_id = str(check.get("id") or "")
            if check_id not in required_labels:
                continue
            status = str(check.get("status") or "")
            if status not in ("fail", "warn"):
                continue
            label = required_labels[check_id]
            if label not in missing:
                missing.append(label)

        if not missing:
            return {
                "label": "前置环境离线源检查",
                "status": "ok",
                "message": "关键前置环境已就绪或已有随包修复源。",
                "count": 0,
            }
        names = "、".join(missing)
        return {
            "label": "前置环境离线源检查",
            "status": "warn",
            "message": f"检测到 {names} 缺失或不可用。当前包内没有对应离线安装源；请使用完整 LOOM 离线包，或先安装官方运行时后重新检测。",
            "count": len(missing),
        }

    def _webview2_check(self) -> dict:
        if os.name != "nt":
            return {
                "id": "webview2",
                "label": "WebView2 Runtime",
                "status": "warn",
                "message": "当前不是 Windows 环境，跳过 WebView2 检查",
                "detail": os.name,
                "repairable": False,
            }

        version = ""
        detail_parts: list[str] = []
        registry_paths = [
            (r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "HKCU"),
            (r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "HKLM"),
            (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "HKLM"),
        ]
        try:
            import winreg
            roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
            for path, root_name in registry_paths:
                try:
                    with winreg.OpenKey(roots[root_name], path) as key:
                        value, _ = winreg.QueryValueEx(key, "pv")
                        if value:
                            version = str(value)
                            detail_parts.append(f"{root_name}\\{path} pv={version}")
                            break
                except OSError:
                    continue
        except Exception as error:
            detail_parts.append(f"registry read failed: {error}")

        fixed_paths = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "EdgeWebView", "Application"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "EdgeWebView", "Application"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "EdgeWebView", "Application"),
        ]
        existing_dirs = [path for path in fixed_paths if path and self._webview2_dir_is_valid(path)]
        if existing_dirs:
            detail_parts.extend(existing_dirs)

        installed = bool(version or existing_dirs)
        redist = self._webview2_redist_path()
        if redist:
            detail_parts.append(f"offline installer: {redist}")
        return {
            "id": "webview2",
            "label": "WebView2 Runtime",
            "status": "ok" if installed else "fail",
            "message": f"已检测到 WebView2 Runtime {version}".strip() if installed else "未检测到 WebView2 Runtime，启动器窗口可能白屏或无法渲染",
            "detail": "；".join(detail_parts) or "Microsoft Edge WebView2 Runtime",
            "repairable": bool(redist and not installed),
        }

    @staticmethod
    def _webview2_dir_is_valid(application_dir: str) -> bool:
        if not application_dir or not os.path.isdir(application_dir):
            return False
        try:
            with os.scandir(application_dir) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if os.path.isfile(os.path.join(entry.path, "msedgewebview2.exe")):
                        return True
        except OSError:
            return False
        return False

    def _fast_python_runtime_check(self) -> dict:
        candidates = [
            os.path.join(self.paths.base_path, "_up_", "python-runtime", "python.exe"),
            os.path.join(self.paths.base_path, "python-runtime", "python.exe"),
            sys.executable,
        ]
        python_exe = next((path for path in candidates if path and os.path.exists(path)), "")
        return {
            "id": "python_runtime",
            "label": "Python / Bridge 运行时",
            "status": "ok" if python_exe else "fail",
            "message": "已找到 Python 运行时" if python_exe else "未找到 Python 运行时，Bridge 无法启动",
            "detail": python_exe or "；".join(candidates),
            "repairable": False,
        }

    def _python_runtime_check(self) -> dict:
        candidates = [
            os.path.join(self.paths.base_path, "_up_", "python-runtime", "python.exe"),
            os.path.join(self.paths.base_path, "python-runtime", "python.exe"),
            sys.executable,
        ]
        python_exe = next((path for path in candidates if path and os.path.exists(path)), "")
        if not python_exe:
            return {
                "id": "python_runtime",
                "label": "Python / Bridge 运行时",
                "status": "fail",
                "message": "未找到 Python 运行时，Bridge 无法启动",
                "detail": "；".join(candidates),
                "repairable": False,
            }
        try:
            env = os.environ.copy()
            bridge_deps = os.path.join(self.paths.base_path, "_up_", "python")
            if os.path.isdir(bridge_deps):
                env["PYTHONPATH"] = bridge_deps + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            result = subprocess.run(
                [python_exe, "-c", "import fastapi, uvicorn; print('ok')"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=12,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ok = result.returncode == 0
            detail = (result.stdout or result.stderr or "").strip()
            return {
                "id": "python_runtime",
                "label": "Python / Bridge 运行时",
                "status": "ok" if ok else "fail",
                "message": "Python 运行时和 FastAPI 依赖正常" if ok else "Python 可执行文件存在，但 Bridge 依赖缺失或损坏",
                "detail": f"{python_exe}；{detail}",
                "repairable": False,
            }
        except Exception as error:
            return {
                "id": "python_runtime",
                "label": "Python / Bridge 运行时",
                "status": "fail",
                "message": "Python 运行时检查失败",
                "detail": f"{python_exe}；{error}",
                "repairable": False,
            }

    def _portable_integrity_check(self) -> dict:
        def first_existing(candidates: list[str]) -> str:
            return next((path for path in candidates if os.path.exists(path)), candidates[0])

        workspace_template_roots = [
            self.paths.openclaw_workspace,
            self.paths.openclaw_workspace_template,
            os.path.join(self.paths.base_path, "_up_", "openclaw-workspace"),
            os.path.join(self.paths.base_path, "_up_", "data", ".openclaw", "workspace"),
        ]

        required = [
            ("bridge.py", os.path.join(self.paths.python_dir, "bridge.py")),
            ("openclaw-image-phone.mjs", os.path.join(self.paths.scripts_dir, "openclaw-image-phone.mjs")),
            ("openclaw-phone-video.mjs", os.path.join(self.paths.scripts_dir, "openclaw-phone-video.mjs")),
            ("openclaw-phone-vision.mjs", os.path.join(self.paths.scripts_dir, "openclaw-phone-vision.mjs")),
            ("verify-phone-agent.ps1", os.path.join(self.paths.scripts_dir, "verify-phone-agent.ps1")),
            ("AGENTS.md", first_existing([os.path.join(root, "AGENTS.md") for root in workspace_template_roots])),
            ("SOUL.md", first_existing([os.path.join(root, "SOUL.md") for root in workspace_template_roots])),
        ]
        node_exists = os.path.exists(self.paths.node_exe)
        missing = [label for label, path in required if not os.path.exists(path)]
        if not node_exists:
            missing.append(os.path.join("node", "node.exe"))

        is_dev_tree = os.path.isdir(os.path.join(self.paths.base_path, "src")) and os.path.exists(os.path.join(self.paths.base_path, "package.json"))
        if missing and is_dev_tree:
            status = "warn"
            message = "当前像开发目录，便携包专用文件未完全具备；正式交付包仍应通过 verify-release.ps1"
        elif missing:
            status = "fail"
            message = "便携包关键文件缺失，可能导致启动、手机 Agent 或离线运行失败"
        else:
            status = "ok"
            message = "便携包关键文件完整"

        return {
            "id": "portable_integrity",
            "label": "便携包完整性",
            "status": status,
            "message": message,
            "detail": "缺失: " + "；".join(missing) if missing else self.paths.base_path,
            "repairable": False,
        }

    def _security_software_block_check(self) -> dict:
        """Detect common Windows security software blocks that look like startup failures."""
        if os.name != "nt":
            return {
                "id": "security_software_block",
                "label": "杀毒 / 安全软件拦截",
                "status": "ok",
                "message": "非 Windows 环境，跳过安全软件拦截检查",
                "detail": os.name,
                "repairable": False,
            }

        explicit_keywords = (
            "operation did not complete successfully because the file contains a virus",
            "virus or potentially unwanted software",
            "microsoft defender",
            "windows defender",
            "controlled folder access",
            "unauthorized changes blocked",
            "blocked by antivirus",
            "quarantine",
            "quarantined",
            "smartscreen",
            "病毒",
            "威胁",
            "隔离",
            "已阻止",
            "安全中心",
            "杀毒",
            "恶意软件",
            "潜在不需要",
            "受控文件夹访问",
            "勒索软件防护",
        )
        weak_keywords = (
            "access is denied",
            "permission denied",
            "拒绝访问",
            "eacces",
            "eperm",
            "winerror 5",
            "winerror 225",
        )

        text_parts: list[str] = []
        snapshot = self._read_startup_snapshot()
        if isinstance(snapshot, dict):
            for key in ("error", "status", "command", "cwd"):
                value = snapshot.get(key)
                if isinstance(value, list):
                    text_parts.append(" ".join(str(item) for item in value))
                elif value:
                    text_parts.append(str(value))
            output_tail = snapshot.get("outputTail")
            if isinstance(output_tail, list):
                text_parts.extend(str(line) for line in output_tail[-80:])

        for log_name in ("bridge-service.log", "openclaw-service.log"):
            log_path = os.path.join(self._logs_dir(), log_name)
            if not os.path.exists(log_path):
                continue
            try:
                with open(log_path, "rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    size = handle.tell()
                    handle.seek(max(0, size - 120_000), os.SEEK_SET)
                    text_parts.append(handle.read().decode("utf-8", errors="replace"))
            except Exception as error:
                text_parts.append(str(error))

        start_js = self.paths.find_file("start.js", ("back", "backup", ""))
        start_entry = start_js if os.path.isfile(start_js) else self.paths.openclaw_mjs
        critical_files = [
            ("Node.js", self.paths.node_exe),
            ("OpenClaw start entry", start_entry),
            ("OpenClaw core", self.paths.openclaw_mjs),
            ("Bridge", os.path.join(self.paths.base_path, "_up_", "python", "bridge.py")),
            ("Phone Agent CLI", os.path.join(self.paths.scripts_dir, "openclaw-phone-agent.mjs")),
        ]
        missing: list[str] = []
        unreadable: list[str] = []
        access_errors: list[str] = []
        for label, path in critical_files:
            if not path:
                continue
            if not os.path.exists(path):
                missing.append(f"{label}: {path}")
                continue
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as handle:
                    handle.read(1)
            except PermissionError as error:
                unreadable.append(f"{label}: {path}")
                access_errors.append(str(error))
            except OSError as error:
                unreadable.append(f"{label}: {path}")
                access_errors.append(str(error))

        text_parts.extend(access_errors)
        combined = "\n".join(text_parts)
        lowered = combined.lower()
        explicit_hits = [keyword for keyword in explicit_keywords if keyword.lower() in lowered]
        weak_hits = [keyword for keyword in weak_keywords if keyword.lower() in lowered]
        is_dev_tree = os.path.isdir(os.path.join(self.paths.base_path, "src")) and os.path.exists(os.path.join(self.paths.base_path, "package.json"))

        detail_parts: list[str] = []
        if explicit_hits:
            detail_parts.append("匹配信号: " + "；".join(dict.fromkeys(explicit_hits)))
        if weak_hits:
            detail_parts.append("权限信号: " + "；".join(dict.fromkeys(weak_hits)))
        if unreadable:
            detail_parts.append("不可读取: " + "；".join(unreadable[:6]))
        if missing and not is_dev_tree:
            detail_parts.append("关键文件缺失: " + "；".join(missing[:8]))
        if snapshot:
            detail_parts.append(f"startupSnapshot={self._startup_snapshot_path()}")

        if explicit_hits or unreadable:
            return {
                "id": "security_software_block",
                "label": "杀毒 / 安全软件拦截",
                "status": "fail",
                "message": "检测到疑似杀毒软件、Windows Defender 或受控文件夹访问拦截",
                "detail": "\n".join(detail_parts),
                "repairable": False,
            }

        if missing and not is_dev_tree:
            return {
                "id": "security_software_block",
                "label": "杀毒 / 安全软件拦截",
                "status": "warn",
                "message": "离线包关键文件缺失，可能是解压不完整或被安全软件隔离",
                "detail": "\n".join(detail_parts),
                "repairable": False,
            }

        if weak_hits:
            return {
                "id": "security_software_block",
                "label": "杀毒 / 安全软件拦截",
                "status": "warn",
                "message": "最近日志出现权限拒绝信号，若启动失败请检查安全软件拦截记录",
                "detail": "\n".join(detail_parts),
                "repairable": False,
            }

        return {
            "id": "security_software_block",
            "label": "杀毒 / 安全软件拦截",
            "status": "ok",
            "message": "未发现明显的 Defender、杀毒软件或受控文件夹访问拦截信号",
            "detail": "checked startup snapshot, bridge logs and critical files",
            "repairable": False,
        }

    def _runtime_context_check(self) -> dict:
        path = os.path.join(self.paths.openclaw_workspace, "runtime-context.json")
        if not os.path.exists(path):
            return {
                "id": "runtime_context",
                "label": "Runtime Context",
                "status": "warn",
                "message": "runtime-context.json 尚未生成；启动运行环境时会自动写入",
                "detail": path,
                "repairable": False,
            }
        try:
            data = self._read_json_if_exists(path)
            schema = str(data.get("schema") or "")
            capabilities = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
            phone_agent = capabilities.get("phoneAgent") if isinstance(capabilities.get("phoneAgent"), dict) else {}
            version = str(phone_agent.get("verifiedVersion") or "")
            version_code = phone_agent.get("verifiedVersionCode")
            problems: list[str] = []
            if schema != "openclaw.launcher.runtime-context.v1":
                problems.append("schema 不匹配")
            if not version or version == "unknown":
                problems.append("phoneAgent.verifiedVersion 为空")
            try:
                if int(version_code or 0) <= 0:
                    problems.append("phoneAgent.verifiedVersionCode 无效")
            except Exception:
                problems.append("phoneAgent.verifiedVersionCode 无效")

            return {
                "id": "runtime_context",
                "label": "Runtime Context",
                "status": "fail" if problems else "ok",
                "message": "；".join(problems) if problems else f"runtime context 正常，Phone Agent {version}/{version_code}",
                "detail": path,
                "repairable": False,
            }
        except Exception as error:
            return {
                "id": "runtime_context",
                "label": "Runtime Context",
                "status": "fail",
                "message": "runtime-context.json 无法解析",
                "detail": f"{path}；{error}",
                "repairable": False,
            }

    def _phone_agent_apk_check(self) -> dict:
        candidates = [
            os.path.join(self.paths.base_path, "releases", "agent-phone", "AgentPhone_latest.apk"),
            os.path.join(self.paths.base_path, "AgentPhone_latest.apk"),
        ]
        apk_path = next((path for path in candidates if os.path.exists(path)), "")
        if not apk_path:
            return {
                "id": "phone_agent_apk",
                "label": "AgentPhone APK 附件",
                "status": "warn",
                "message": "未找到 AgentPhone_latest.apk，手机控制需要单独安装 APK",
                "detail": "；".join(candidates),
                "repairable": False,
            }
        size_mb = os.path.getsize(apk_path) / (1024 * 1024)
        sha256 = self._file_sha256(apk_path)
        latest_hash = sha256
        matched_versions: list[str] = []
        for name in os.listdir(os.path.dirname(apk_path)):
            if not (name.startswith("AgentPhone_v") and name.endswith(".apk")):
                continue
            candidate = os.path.join(os.path.dirname(apk_path), name)
            if self._file_sha256(candidate) == latest_hash:
                matched_versions.append(name)
        status = "ok" if matched_versions or "releases" not in apk_path.replace("\\", "/") else "warn"
        message = (
            f"已找到 APK，匹配版本文件：{', '.join(matched_versions)}"
            if matched_versions else
            "已找到 AgentPhone_latest.apk，但没有匹配到同目录版本化 APK，发布追踪性不足"
        )
        return {
            "id": "phone_agent_apk",
            "label": "AgentPhone APK 附件",
            "status": status,
            "message": message,
            "detail": f"{apk_path}；{size_mb:.1f} MB；SHA256={sha256}",
            "repairable": False,
        }

    @staticmethod
    def _file_sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _storage_health_check(self, write_test: bool = False) -> dict:
        root = self._drive_root()
        detail_parts = [
            f"运行目录: {self.paths.base_path}",
            f"磁盘: {root}",
        ]
        problems: list[str] = []
        warnings: list[str] = []

        if not os.path.isdir(self.paths.base_path):
            return {
                "id": "storage_health",
                "label": "运行磁盘 / U盘健康",
                "status": "fail",
                "message": "安装目录不可访问",
                "detail": self.paths.base_path,
                "repairable": False,
            }

        drive_type = self._drive_type_label(root)
        if drive_type:
            detail_parts.append(f"类型: {drive_type}")
            if drive_type == "不可访问":
                problems.append("磁盘不可访问")

        try:
            usage = shutil.disk_usage(root if root and os.path.exists(root) else self.paths.base_path)
            free_mb = usage.free / (1024 * 1024)
            detail_parts.append(f"可用空间: {free_mb:.0f} MB")
            if free_mb < 256:
                problems.append("可用空间低于 256MB")
            elif free_mb < 1024:
                warnings.append("可用空间低于 1GB")
        except Exception as error:
            warnings.append(f"无法读取剩余空间: {error}")

        if write_test:
            probe_path = ""
            try:
                probe_dir = self.paths.launcher_dir
                os.makedirs(probe_dir, exist_ok=True)
                fd, probe_path = tempfile.mkstemp(prefix=".openclaw-disk-check-", suffix=".tmp", dir=probe_dir)
                payload = f"openclaw-disk-check:{time.time()}".encode("utf-8")
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                with open(probe_path, "rb") as handle:
                    if handle.read() != payload:
                        raise OSError("写入后读回内容不一致")
                os.remove(probe_path)
                detail_parts.append("读写测试: 通过")
            except Exception as error:
                problems.append(f"读写测试失败: {error}")
                detail_parts.append("读写测试: 失败")
            finally:
                if probe_path and os.path.exists(probe_path):
                    try:
                        os.remove(probe_path)
                    except OSError:
                        pass

        if problems:
            status = "fail"
            message = "；".join(problems)
        elif warnings:
            status = "warn"
            message = "；".join(warnings)
        else:
            status = "ok"
            message = "运行磁盘可访问，读写测试正常" if write_test else "运行磁盘可访问"

        return {
            "id": "storage_health",
            "label": "运行磁盘 / U盘健康",
            "status": status,
            "message": message,
            "detail": "；".join(detail_parts),
            "repairable": False,
        }

    def _drive_root(self) -> str:
        absolute = os.path.abspath(self.paths.base_path)
        drive, _ = os.path.splitdrive(absolute)
        if drive:
            return f"{drive}\\"
        return absolute

    @staticmethod
    def _env_truthy(name: str) -> bool:
        return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _startup_deep_clean_enabled(self) -> bool:
        return self._env_truthy("OPENCLAW_STARTUP_DEEP_CLEAN")

    def _startup_storage_write_test_enabled(self) -> bool:
        return self._env_truthy("OPENCLAW_STARTUP_STORAGE_WRITE_TEST")

    @staticmethod
    def _drive_type_label(root: str) -> str:
        if os.name != "nt":
            return "当前系统磁盘"
        try:
            import ctypes

            drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:
            return "未知"
        return {
            0: "未知",
            1: "不可访问",
            2: "可移动磁盘",
            3: "本地磁盘",
            4: "网络磁盘",
            5: "光盘",
            6: "内存盘",
        }.get(drive_type, f"类型 {drive_type}")

    def _read_output(self, process: subprocess.Popen, on_exit: Callable[[int | None], None] | None) -> None:
        try:
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    self._append_output_tail(line)
                    self.ui_call(self.append_log, line)
        except Exception as error:
            self.ui_call(self.append_log, f"[Error: {error}]\n")
        exit_code = process.poll()
        self.running = False
        if self.startup_state == "starting":
            self.startup_state = "failed"
            self.startup_error = f"OpenClaw process exited with code {exit_code}"
        self.ui_call(self.append_log, f"\n[OpenClaw] Process ended (exit: {exit_code})\n")
        if exit_code not in (0, None):
            self._write_startup_snapshot(
                status="fail",
                error=f"OpenClaw process exited with code {exit_code}",
                exit_code=exit_code,
                port_ready=self._is_port_listening(APP_PORT),
            )
        if on_exit:
            self.ui_call(on_exit, exit_code)

    def _kill_port_processes(self, port: int) -> int:
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return 0
        pids: set[str] = set()
        marker = f":{port}"
        stdout = result.stdout or ""
        for line in stdout.splitlines():
            if marker not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if parts:
                pids.add(parts[-1])
        killed = 0
        for pid in pids:
            if self._kill_pid(pid):
                killed += 1
        return killed

    def _kill_port_range_processes(self, start: int, end: int, exclude_pids: set[str] | None = None) -> int:
        exclude_pids = exclude_pids or set()
        listeners = self._port_range_listeners(start, end, exclude_pids=exclude_pids)
        pids = {str(item.get("pid")) for item in listeners if str(item.get("pid", "")).isdigit()}
        killed = 0
        for pid in pids:
            if pid in exclude_pids:
                continue
            if self._kill_pid(pid):
                killed += 1
        return killed

    def _stop_registered_gateway(self) -> int:
        completed = subprocess.run(
            ["schtasks", "/End", "/TN", "OpenClaw Gateway"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return 1 if completed.returncode == 0 else 0

    def _port_listeners(self, port: int) -> list[dict[str, str]]:
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return []
        pids: set[str] = set()
        marker = f":{port}"
        for line in (result.stdout or "").splitlines():
            if marker not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])
        return self._describe_pids(pids)

    def _port_range_listeners(self, start: int, end: int, exclude_pids: set[str] | None = None) -> list[dict[str, str]]:
        exclude_pids = exclude_pids or set()
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return []
        pids: set[str] = set()
        for line in (result.stdout or "").splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 5 or not parts[-1].isdigit():
                continue
            local = parts[1]
            if any(local.endswith(f":{port}") for port in range(start, end + 1)) and parts[-1] not in exclude_pids:
                pids.add(parts[-1])
        return self._describe_pids(pids)

    def _clawpanel_processes(self) -> list[dict[str, str]]:
        command = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -ieq 'clawpanel.exe' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return []
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        return self._describe_pids(pids)

    def _openclaw_gateway_processes(self) -> list[dict[str, str]]:
        command = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and "
            "$_.CommandLine -match 'openclaw' -and $_.CommandLine -match '\\bgateway\\b' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return []
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        if self.process:
            pids.discard(str(self.process.pid))
        return self._describe_pids(pids)

    def _describe_pids(self, pids: set[str]) -> list[dict[str, str]]:
        processes: list[dict[str, str]] = []
        for pid in sorted(pids):
            if not pid.isdigit():
                continue
            command = (
                "$ErrorActionPreference='SilentlyContinue'; "
                f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\"; "
                "if ($p) { Write-Output ($p.ProcessId.ToString() + \"`t\" + $p.Name + \"`t\" + ($p.CommandLine -replace \"`r|`n\", \" \")) }"
            )
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                continue
            for line in (result.stdout or "").splitlines():
                parts = line.split("\t", 2)
                if len(parts) >= 2:
                    processes.append({
                        "pid": parts[0],
                        "name": parts[1],
                        "command": parts[2] if len(parts) > 2 else "",
                    })
        return processes

    def _format_process(self, item: dict[str, str]) -> str:
        pid = item.get("pid", "?")
        name = item.get("name", "process")
        command = (item.get("command") or "").strip()
        if len(command) > 120:
            command = command[:117] + "..."
        return f"{name}({pid}) {command}".strip()

    def _openclaw_version(self) -> str:
        package_path = os.path.join(self.paths.base_path, "node_modules", "openclaw", "package.json")
        if not os.path.exists(package_path):
            return "unknown"
        try:
            with open(package_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return str(data.get("version") or "unknown")
        except Exception:
            return "unknown"

    def _kill_clawpanel_processes(self) -> int:
        command = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -ieq 'clawpanel.exe' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return 0
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        killed = 0
        for pid in pids:
            if self._kill_pid(pid):
                killed += 1
        return killed

    def _kill_openclaw_gateway_processes(self) -> int:
        command = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and "
            "$_.CommandLine -match 'openclaw' -and $_.CommandLine -match '\\bgateway\\b' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return 0
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        killed = 0
        for pid in pids:
            if self.process and str(self.process.pid) == pid:
                continue
            if self._kill_pid(pid):
                killed += 1
        return killed

    def _kill_pid(self, pid: str) -> bool:
        completed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0

    def _wait_until_ready(self, port: int, timeout: float) -> None:
        deadline = time.time() + timeout
        next_log_at = time.time() + 8.0
        while time.time() < deadline:
            if self.process and self.process.poll() is not None:
                self.running = False
                raise RuntimeError("OpenClaw 启动后立即退出，请查看服务日志")
            if self._is_port_listening(port):
                return
            now = time.time()
            if now >= next_log_at:
                remaining = max(0, int(deadline - now))
                elapsed = int(timeout - remaining)
                self.append_log(f"[OpenClaw] Still starting on low-end hardware... elapsed={elapsed}s remaining={remaining}s port={port}\n")
                next_log_at = now + 15.0
            time.sleep(0.5)
        raise TimeoutError(f"OpenClaw 启动较慢：端口 {port} 暂未就绪，进程仍会保留并继续等待")

    def _is_port_listening(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            pass
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return False
        marker = f":{port}"
        return any(marker in line and "LISTENING" in line.upper() for line in (result.stdout or "").splitlines())


def _is_transient_winget_failure(value: object) -> bool:
    text = str(value or "").lower()
    markers = (
        "network",
        "connection",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "source data",
        "source failed",
        "0x8a15000f",
        "0x801901f7",
        "0x80072ee2",
        "0x80072efe",
    )
    return any(marker in text for marker in markers)


def _merge_windows_path(existing: str, registry_values: list[str]) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_group in [*registry_values, existing]:
        for raw_entry in str(raw_group or "").split(";"):
            entry = os.path.expandvars(raw_entry.strip().strip('"'))
            if not entry:
                continue
            key = os.path.normpath(entry).rstrip("\\/").lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    return ";".join(merged)


def _windows_registry_path_values() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    )
    values: list[str] = []
    for root, subkey in locations:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if str(value or "").strip():
            values.append(str(value))
    return values


def _refresh_process_path_from_windows_registry() -> bool:
    registry_values = _windows_registry_path_values()
    if not registry_values:
        return False
    existing = os.environ.get("Path") or os.environ.get("PATH") or ""
    merged = _merge_windows_path(existing, registry_values)
    if not merged:
        return False
    os.environ["PATH"] = merged
    os.environ["Path"] = merged
    return True
