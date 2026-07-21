"""OpenClaw gateway process management."""

from __future__ import annotations

import os
import json
import hashlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable

from core.constants import APP_PORT
from core.paths import AppPaths

UiCall = Callable[..., None]
LogCall = Callable[[str], None]


class OpenClawProcessService:
    def __init__(self, paths: AppPaths, append_log: LogCall, ui_call: UiCall):
        self.paths = paths
        self.append_log = append_log
        self.ui_call = ui_call
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

    def _start_locked(self, on_exit: Callable[[int | None], None] | None = None) -> None:
        if self.running:
            raise RuntimeError("服务已在运行中")
        self.startup_state = "starting"
        self.startup_started_at = time.time()
        self._startup_started_perf = time.perf_counter()
        self._startup_timeline = []
        self.startup_error = ""
        node_exe = self.paths.node_exe
        if not os.path.exists(node_exe):
            raise FileNotFoundError(f"找不到 Node.js：\n{node_exe}")
        start_js = self.paths.find_file("start.js", ("back", "backup", ""))
        if not os.path.exists(start_js):
            raise FileNotFoundError(f"找不到启动脚本：\n{start_js}")

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
        command = [node_exe, start_js]
        self._last_start_command = command
        self._output_tail = []
        self.append_log("[OpenClaw] Starting service...\n")
        self.append_log(f"[OpenClaw] Node: {node_exe}\n")
        self.append_log(f"[OpenClaw] Script: {start_js}\n\n")
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
                self._kill_pid(str(self.process.pid))
            self.running = False
            self.process = None
            self.startup_state = "failed"
            raise

    def stop(self) -> str:
        if self.process and self.process.poll() is None:
            pid = self.process.pid
            self.append_log("\n[OpenClaw] Stopping...\n")
            self._kill_pid(str(pid))
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

    def diagnose_environment(self) -> dict:
        """Return customer-facing environment checks for the launcher."""
        checks: list[dict] = []

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

        file_check("base_path", "安装目录", self.paths.base_path)
        checks.append(self._storage_health_check(write_test=True))
        file_check("node", "Node.js 运行时", self.paths.node_exe)
        file_check("start_js", "OpenClaw 启动脚本", self.paths.find_file("start.js", ("back", "backup", "")))
        file_check("openclaw_core", "OpenClaw 本体", self.paths.openclaw_mjs)
        file_check("data_dir", "数据目录", self.paths.data_dir, required=False, repairable=True)
        checks.append(self._openclaw_config_check())
        checks.append(self._webview2_check())
        checks.append(self._python_runtime_check())
        checks.append(self._portable_integrity_check())
        checks.append(self._security_software_block_check())
        checks.append(self._runtime_context_check())
        # APKClaw is distributed via QR link now and no longer bundled, so the
        # "APK missing" diagnostic would always warn — drop it.
        checks.append(self._member_gateway_check())
        checks.append(self._core_service_snapshot_check())

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

        return {
            "actions": actions,
            "diagnostics": self.diagnose_environment(),
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
        # utf-8-sig tolerates a leading BOM (some editors/tools add one), which
        # plain utf-8 + json.load rejects with "Unexpected UTF-8 BOM".
        with open(self.paths.openclaw_config, "r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("root value is not an object")
        return config

    def _normalize_openclaw_config(self, config: dict) -> bool:
        changed = False
        if "launcherPreview" in config:
            del config["launcherPreview"]
            changed = True
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
            "AGENTS.md": "# AGENTS.md - OpenClaw Portable Launcher Workspace\n\nUse the portable launcher capabilities before asking the user to move files manually.\n",
            "SOUL.md": "# SOUL.md - OpenClaw Portable Launcher\n\nBe careful, practical, and aware that this workspace runs inside a portable launcher.\n",
            "TOOLS.md": "# TOOLS.md - Portable Launcher Tools\n\nRead runtime-context.json for current paths and phone Agent state.\n",
            "CAPABILITIES.md": "# OpenClaw Portable Launcher Capability Map\n\nRead runtime-context.json for current capability state.\n",
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
        video_config = self._merge_config(
            self._read_json_if_exists(self.paths.video_config),
            self._read_json_if_exists(self.paths.videoapi_config),
        )
        member_license = self._read_json_if_exists(self.paths.license_file)
        member_session = self._read_json_if_exists(self.paths.member_session_file)
        member_gateway_configured = False
        member_gateway_base = ""
        member_gateway_token = ""
        member_gateway_models: list[str] = []
        member_gateway_default_model = ""
        member_gateway_image_model = ""
        member_gateway_video_model = ""
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
            member_gateway_video_model = str(
                gateway_source.get("gatewayVideoModel")
                or gateway_source.get("videoModel")
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
        phone_album = str(selected_phone_config.get("album") or os.environ.get("OPENCLAW_PHONE_ALBUM") or "OpenClaw") if isinstance(selected_phone_config, dict) else "OpenClaw"
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
                "name": "OpenClaw Portable Launcher",
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
                    "videoModel": member_gateway_video_model or None,
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
                "scripts": os.path.join(self.paths.base_path, "scripts"),
                "imageToPhoneCli": os.path.join(self.paths.base_path, "scripts", "openclaw-image-phone.mjs"),
                "phoneVerifier": os.path.join(self.paths.base_path, "scripts", "verify-phone-agent.ps1"),
                "phoneFleetCli": os.path.join(self.paths.base_path, "scripts", "openclaw-phone-fleet.mjs"),
                "desktopAgentCli": os.path.join(self.paths.base_path, "scripts", "openclaw-desktop-agent.mjs"),
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
                    "memberModel": member_gateway_video_model or None,
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
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _has_config_values(self, value: dict) -> bool:
        return any(isinstance(item, str) and bool(item.strip()) for item in value.values())

    def _merge_config(self, base: dict, updates: dict) -> dict:
        merged = dict(base) if isinstance(base, dict) else {}
        if isinstance(updates, dict):
            merged.update({key: value for key, value in updates.items() if value not in (None, "")})
        return merged

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
        existing_dirs = [path for path in fixed_paths if path and os.path.isdir(path)]
        if existing_dirs:
            detail_parts.extend(existing_dirs)

        installed = bool(version or existing_dirs)
        redist_candidates = [
            os.path.join(self.paths.base_path, "redist", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
            os.path.join(self.paths.base_path, "_up_", "redist", "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
        ]
        redist = next((path for path in redist_candidates if os.path.isfile(path)), "")
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

    def _python_runtime_check(self) -> dict:
        exe = "python.exe" if os.name == "nt" else "bin/python3"
        alt_exe = "python.exe" if os.name == "nt" else "bin/python"
        candidates = [
            os.path.join(self.paths.base_path, "_up_", "python-runtime", exe),
            os.path.join(self.paths.base_path, "_up_", "python-runtime", alt_exe),
            os.path.join(self.paths.base_path, "python-runtime", exe),
            os.path.join(self.paths.base_path, "python-runtime", alt_exe),
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
        required = [
            "start.js",
            os.path.join("node_modules", "openclaw", "openclaw.mjs"),
            os.path.join("_up_", "python", "bridge.py"),
            os.path.join("scripts", "openclaw-image-phone.mjs"),
            os.path.join("scripts", "openclaw-phone-video.mjs"),
            os.path.join("scripts", "openclaw-phone-vision.mjs"),
            os.path.join("scripts", "verify-phone-agent.ps1"),
            os.path.join("data", ".openclaw", "workspace", "AGENTS.md"),
            os.path.join("data", ".openclaw", "workspace", "SOUL.md"),
        ]
        node_exists = any(os.path.exists(os.path.join(self.paths.base_path, "node", name)) for name in self.paths.node_binary_names())
        missing = [item for item in required if not os.path.exists(os.path.join(self.paths.base_path, item))]
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

        critical_files = [
            ("Node.js", self.paths.node_exe),
            ("OpenClaw start.js", self.paths.find_file("start.js", ("back", "backup", ""))),
            ("OpenClaw core", self.paths.openclaw_mjs),
            ("Bridge", os.path.join(self.paths.base_path, "_up_", "python", "bridge.py")),
            ("Phone Agent CLI", os.path.join(self.paths.base_path, "scripts", "openclaw-phone-agent.mjs")),
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
                "message": "runtime-context.json 尚未生成；启动核心服务时会自动写入",
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
            phone_verified = bool(version and version != "unknown")
            try:
                phone_verified = phone_verified and int(version_code or 0) > 0
            except Exception:
                phone_verified = False
            schema_ok = schema == "openclaw.launcher.runtime-context.v1"

            # This file is informational and self-healing: the core service
            # rewrites it on start, and phoneAgent.verifiedVersion only fills in
            # after the phone agent is verified. So an empty/older value is a
            # normal "not set up yet" state, not a red failure that alarms users.
            if schema_ok and phone_verified:
                return {
                    "id": "runtime_context",
                    "label": "Runtime Context",
                    "status": "ok",
                    "message": f"运行时上下文正常，Phone Agent {version}/{version_code}",
                    "detail": path,
                    "repairable": False,
                }
            if not phone_verified:
                message = "Phone Agent 尚未验证（首次连接手机或启动核心服务后自动写入）"
            else:
                message = "运行时上下文为旧版本，启动核心服务时会自动升级"
            return {
                "id": "runtime_context",
                "label": "Runtime Context",
                "status": "warn",
                "message": message,
                "detail": path,
                "repairable": False,
            }
        except Exception:
            return {
                "id": "runtime_context",
                "label": "Runtime Context",
                "status": "warn",
                "message": "runtime-context.json 暂时无法解析，启动核心服务时会自动重写",
                "detail": path,
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
        # For the end user the only thing that matters is that the APK ships; the
        # "matching versioned filename" bit is release-hygiene noise, so keep it
        # in detail rather than raising a scary warning.
        version_note = f"，匹配版本文件 {', '.join(matched_versions)}" if matched_versions else ""
        return {
            "id": "phone_agent_apk",
            "label": "AgentPhone APK 附件",
            "status": "ok",
            "message": f"已找到 AgentPhone APK（{size_mb:.1f} MB）{version_note}",
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
        pids = self._port_pids(port)
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
        if os.name != "nt":
            return 0
        completed = subprocess.run(
            ["schtasks", "/End", "/TN", "OpenClaw Gateway"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return 1 if completed.returncode == 0 else 0

    def _port_listeners(self, port: int) -> list[dict[str, str]]:
        return self._describe_pids(self._port_pids(port))

    def _port_range_listeners(self, start: int, end: int, exclude_pids: set[str] | None = None) -> list[dict[str, str]]:
        exclude_pids = exclude_pids or set()
        if os.name != "nt":
            pids: set[str] = set()
            for port in range(start, end + 1):
                pids.update(self._port_pids(port))
            return self._describe_pids({pid for pid in pids if pid not in exclude_pids})
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
        if os.name != "nt":
            return []
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return []
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        return self._describe_pids(pids)

    def _openclaw_gateway_processes(self) -> list[dict[str, str]]:
        if os.name != "nt":
            return []
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return []
        pids = {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        if self.process:
            pids.discard(str(self.process.pid))
        return self._describe_pids(pids)

    def _describe_pids(self, pids: set[str]) -> list[dict[str, str]]:
        if os.name != "nt":
            return [{"pid": pid, "name": "process", "command": ""} for pid in sorted(pids) if pid.isdigit()]
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
        if os.name != "nt":
            return 0
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
        if os.name != "nt":
            return 0
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
        if os.name != "nt":
            try:
                os.kill(int(pid), signal.SIGTERM)
                return True
            except ProcessLookupError:
                return True
            except Exception:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    return True
                except Exception:
                    return False
        completed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0

    def _port_pids(self, port: int) -> set[str]:
        if os.name != "nt":
            try:
                result = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=3)
            except Exception:
                return set()
            return {line.strip() for line in (result.stdout or "").splitlines() if line.strip().isdigit()}
        try:
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return set()
        pids: set[str] = set()
        marker = f":{port}"
        for line in (result.stdout or "").splitlines():
            if marker not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])
        return pids

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
            if os.name != "nt":
                return False
            result = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return False
        marker = f":{port}"
        return any(marker in line and "LISTENING" in line.upper() for line in (result.stdout or "").splitlines())
