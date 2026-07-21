"""Luminode desktop agent sidecar management."""

from __future__ import annotations

import glob
import json
import os
import signal
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from core.paths import AppPaths

LogCall = Callable[[str], None]


class DesktopAgentService:
    """Manage Luminode as an optional local desktop execution sidecar."""

    DEFAULT_PORT = 21900
    ALLOWED_PROXY_PATHS = {
        "/health",
        "/screenshot",
        "/click",
        "/type",
        "/wechat/send",
        "/wechat/unread",
        "/wechat/contact_unread",
        "/measure_layout",
        "/wechat/chat_diff",
        "/engine/status",
    }

    def __init__(self, paths: AppPaths, append_log: LogCall):
        self.paths = paths
        self.append_log = append_log
        self.process: subprocess.Popen | None = None
        self._output_thread: threading.Thread | None = None

    @property
    def config_path(self) -> str:
        return os.path.join(self.paths.launcher_dir, "desktop-agent.json")

    def default_config(self) -> dict:
        return {
            "enabled": False,
            "agentDir": "",
            "port": self.DEFAULT_PORT,
            "token": secrets.token_urlsafe(24),
            "appType": "weixin",
            "provider": {
                "apiKey": "",
                "baseUrl": "",
                "baseURL": "",
                "model": "",
            },
            "llm": {
                "apiKey": "",
                "baseUrl": "",
                "baseURL": "",
                "model": "",
            },
            "chatProvider": {
                "config": {
                    "apiKey": "",
                    "baseUrl": "",
                    "baseURL": "",
                    "model": "",
                },
            },
            "autoStartHttpApi": True,
            "policy": {
                "allowScreenshot": True,
                "allowClick": False,
                "allowType": False,
                "allowWechatSend": False,
                "requireConfirmForClick": True,
                "requireConfirmForType": True,
                "requireConfirmForSend": True,
                "blockedWindowKeywords": ["支付", "付款", "密码", "授权", "登录"],
            },
            "capture": {
                "format": "jpeg",
                "quality": 82,
                "maxWidth": 1600,
            },
            "action": {
                "clickDelayMs": 120,
                "typeDelayMs": 20,
                "timeoutMs": 30000,
            },
            "wechat": {
                "sendMode": "draft_only",
                "detectUnreadMode": "hybrid",
            },
        }

    def read_config(self) -> dict:
        config = self.default_config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                config = self._deep_merge(config, data)
        except FileNotFoundError:
            self.write_config(config)
        except Exception as error:
            self.append_log(f"[DesktopAgent] Failed to read config: {error}\n")
        if not str(config.get("token") or "").strip():
            config["token"] = secrets.token_urlsafe(24)
            self.write_config(config)
        return config

    def write_config(self, updates: dict) -> dict:
        config = self.default_config()
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as handle:
                    existing = json.load(handle)
                if isinstance(existing, dict):
                    config = self._deep_merge(config, existing)
        except Exception:
            pass
        config = self._deep_merge(config, {key: value for key, value in updates.items() if key != "tokenPreview"})
        if not str(config.get("token") or "").strip():
            config["token"] = secrets.token_urlsafe(24)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
        return self.public_config(config)

    def public_config(self, config: dict | None = None) -> dict:
        config = config or self.read_config()
        token = str(config.get("token") or "")
        return {
            "enabled": bool(config.get("enabled")),
            "agentDir": str(config.get("agentDir") or ""),
            "resolvedAgentDir": self.resolve_agent_dir(config),
            "port": int(config.get("port") or self.DEFAULT_PORT),
            "tokenAvailable": bool(token),
            "tokenPreview": f"****{token[-4:]}" if token else "",
            "appType": str(config.get("appType") or "weixin"),
            "autoStartHttpApi": bool(config.get("autoStartHttpApi", True)),
            "provider": self._public_provider(config),
            "policy": self._public_policy(config),
            "capture": self._public_capture(config),
            "action": self._public_action(config),
            "wechat": self._public_wechat(config),
            "configPath": self.config_path,
        }

    def status(self) -> dict:
        config = self.read_config()
        process_alive = self.process is not None and self.process.poll() is None
        health = self.health(config=config, quiet=True)
        agent_dir = self.resolve_agent_dir(config)
        command = self.resolve_command(agent_dir) if agent_dir else []
        return {
            "configured": bool(agent_dir),
            "present": bool(agent_dir and os.path.isdir(agent_dir)),
            "running": bool(process_alive),
            "pid": self.process.pid if process_alive else None,
            "apiReady": bool(health.get("ok")),
            "health": health,
            "command": command,
            "config": self.public_config(config),
        }

    def _quick_status(self, config: dict, message: str, running: bool | None = None) -> dict:
        agent_dir = self.resolve_agent_dir(config)
        command = self.resolve_command(agent_dir) if agent_dir else []
        process_alive = self.process is not None and self.process.poll() is None
        if running is not None:
            process_alive = running
        health = {
            "ok": False,
            "success": False,
            "message": message,
            "port": int(config.get("port") or self.DEFAULT_PORT),
        }
        return {
            "configured": bool(agent_dir),
            "present": bool(agent_dir and os.path.isdir(agent_dir)),
            "running": bool(process_alive),
            "pid": self.process.pid if process_alive and self.process else None,
            "apiReady": False,
            "health": health,
            "command": command,
            "config": self.public_config(config),
        }

    def start(self) -> dict:
        config = self.read_config()
        if self.process and self.process.poll() is None:
            return self._quick_status(config, "already running", running=True)

        agent_dir = self.resolve_agent_dir(config)
        if not agent_dir:
            raise FileNotFoundError("未找到 Luminode Desktop Agent 目录，请在桌面控制页设置 agentDir")

        command = self.resolve_command(agent_dir)
        if not command:
            raise FileNotFoundError(f"未找到 Luminode 可启动入口：{agent_dir}")

        # 显式以 sidecar 模式启动并传参,让 agent 自动开启 token 保护的本地 HTTP API。
        # agent 读 --luminode-sidecar / --port / --token / --app-type / --api-key(arg 优先于 env)。
        # 此前启动器只设 LUMINODE_* env,而 agent 读 SIGHTFLOW_* env,前缀对不上 → API 起不来、
        # 桌面控制无法自主启动。用显式 arg 绕开前缀问题,最可靠。
        sidecar_port = int(config.get("port") or self.DEFAULT_PORT)
        sidecar_token = str(config.get("token") or "")
        sidecar_app_type = str(config.get("appType") or "weixin")
        command = [
            *command,
            "--luminode-sidecar",
            "--port", str(sidecar_port),
            "--token", sidecar_token,
            "--app-type", sidecar_app_type,
        ]
        # 视觉模型:从统一配置(auth-profiles 主 provider)读出 网关地址+模型+key 一起传给 agent。
        # 否则 agent 的视觉客户端会回退默认火山地址,拿网关 token 直连 → 401「key 格式不对」,
        # 布局测量失败导致引擎无法启动。
        sidecar_provider = self._primary_provider(config)
        if sidecar_provider.get("apiKey"):
            command += ["--api-key", sidecar_provider["apiKey"]]
        if sidecar_provider.get("baseUrl"):
            command += ["--base-url", sidecar_provider["baseUrl"]]
        if sidecar_provider.get("model"):
            command += ["--model", sidecar_provider["model"]]

        env = os.environ.copy()
        env.update({
            "LUMINODE_HTTP_API_AUTOSTART": "1" if config.get("autoStartHttpApi", True) else "0",
            "LUMINODE_HTTP_API_PORT": str(int(config.get("port") or self.DEFAULT_PORT)),
            "LUMINODE_AGENT_TOKEN": str(config.get("token") or ""),
            "LUMINODE_APP_TYPE": str(config.get("appType") or "weixin"),
            "LUMINODE_POLICY_JSON": json.dumps(self.public_config(config), ensure_ascii=False),
            "SIGHTFLOW_HTTP_API_AUTOSTART": "1" if config.get("autoStartHttpApi", True) else "0",
            "SIGHTFLOW_HTTP_API_PORT": str(sidecar_port),
            "SIGHTFLOW_AGENT_TOKEN": sidecar_token,
            "SIGHTFLOW_APP_TYPE": sidecar_app_type,
        })
        api_key = sidecar_provider.get("apiKey") or self._primary_api_key()
        if api_key:
            env["LUMINODE_API_KEY"] = api_key
        if sidecar_provider.get("apiKey"):
            env["SIGHTFLOW_API_KEY"] = sidecar_provider["apiKey"]
        if sidecar_provider.get("baseUrl"):
            env["SIGHTFLOW_BASE_URL"] = sidecar_provider["baseUrl"]
        if sidecar_provider.get("model"):
            env["SIGHTFLOW_MODEL"] = sidecar_provider["model"]

        self.append_log(f"[DesktopAgent] Starting Luminode: {' '.join(self._redact_command(command))}\n")
        popen_kwargs = self._popen_platform_kwargs()
        self.process = subprocess.Popen(
            command,
            cwd=agent_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **popen_kwargs,
        )
        self.append_log(f"[DesktopAgent] PID: {self.process.pid}\n")
        self._output_thread = threading.Thread(target=self._read_output, args=(self.process,), daemon=True)
        self._output_thread.start()
        return self._quick_status(config, "starting", running=True)

    def stop(self) -> dict:
        config = self.read_config()
        stopped = False
        if self.process and self.process.poll() is None:
            pid = self.process.pid
            self.append_log(f"[DesktopAgent] Stopping PID {pid}\n")
            self._terminate_process_tree(pid)
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._kill_process_tree(pid)
                pass
            stopped = True
        if not stopped:
            stopped = self._stop_process_on_port(int(config.get("port") or self.DEFAULT_PORT))
        self.process = None
        return self._quick_status(config, "stopped" if stopped else "not running", running=False)

    def health(self, config: dict | None = None, quiet: bool = False) -> dict:
        config = config or self.read_config()
        try:
            return self.proxy("/health", {}, method="GET", config=config)
        except Exception as error:
            if not quiet:
                self.append_log(f"[DesktopAgent] Health check failed: {error}\n")
            return {"ok": False, "success": False, "error": str(error), "port": int(config.get("port") or self.DEFAULT_PORT)}

    def proxy(self, path: str, body: dict | None = None, method: str = "POST", config: dict | None = None) -> dict:
        config = config or self.read_config()
        path = "/" + path.strip("/")
        if path not in self.ALLOWED_PROXY_PATHS:
            raise ValueError(f"desktop agent path not allowed: {path}")
        body = body or {}
        self._enforce_policy(path, body, config)

        port = int(config.get("port") or self.DEFAULT_PORT)
        url = f"http://127.0.0.1:{port}{path}"
        payload = json.dumps(self._augment_body(path, body, config), ensure_ascii=False).encode("utf-8")
        # 按路径分级超时:健康检查要快返回;动作/微信操作要扫 UI、点按、抓未读,耗时长,
        # 对齐 agent 自身 ~30s 动作超时,避免启动器这边 8s 就误判"动作失败"(agent 还在干)。
        timeout = 2 if path == "/health" else 35
        request = urllib.request.Request(
            url,
            data=None if method.upper() == "GET" else payload,
            method=method.upper(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "X-Desktop-Agent-Token": str(config.get("token") or ""),
                "Authorization": f"Bearer {config.get('token') or ''}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code}: {text}") from error
        data = json.loads(text) if text else {}
        if isinstance(data, dict):
            data.setdefault("ok", bool(data.get("success", True)))
            return data
        return {"ok": True, "data": data}

    def resolve_agent_dir(self, config: dict | None = None) -> str:
        config = config or self.read_config()
        candidates = [
            str(config.get("agentDir") or "").strip(),
            os.environ.get("OPENCLAW_DESKTOP_AGENT_DIR", ""),
            os.path.join(self.paths.base_path, "agents", "luminode-desktop"),
            os.path.join(self.paths.base_path, "agents", "luminode-desktop", "Luminode.app"),
            os.path.join(self.paths.base_path, "agents", "luminode-desktop", "LumiNode.app"),
            os.path.join(self.paths.base_path, "agents", "sightflow-desktop"),
            os.path.join(self.paths.base_path, "sightflow-desktop-agent"),
            os.path.join(
                os.path.dirname(self.paths.base_path),
                "sightflow-desktop-agent-main",
                "sightflow-desktop-agent-main",
            ),
            os.path.join(os.path.dirname(self.paths.base_path), "sightflow-desktop-agent-main"),
        ]
        for candidate in candidates:
            if candidate and os.path.isdir(candidate):
                return os.path.normpath(candidate)
        return ""

    def resolve_command(self, agent_dir: str) -> list[str]:
        if not agent_dir:
            return []
        app_command = self._mac_app_command(agent_dir)
        if app_command:
            return app_command

        electron = os.path.join(agent_dir, "electron-dist", "electron.exe")
        package_json = os.path.join(agent_dir, "package.json")
        out_main = os.path.join(agent_dir, "out", "main", "index.js")
        if os.path.exists(electron) and os.path.exists(package_json) and os.path.exists(out_main):
            return [electron, "."]

        exe_candidates = [
            os.path.join(agent_dir, "Luminode.exe"),
            os.path.join(agent_dir, "LumiNode.exe"),
            os.path.join(agent_dir, "sightflow-desktop-agent.exe"),
        ]
        exe_candidates.extend(glob.glob(os.path.join(agent_dir, "dist", "win-unpacked", "*.exe")))
        for exe in exe_candidates:
            if os.path.exists(exe):
                return [exe]

        app_candidates = [
            os.path.join(agent_dir, "Luminode.app"),
            os.path.join(agent_dir, "LumiNode.app"),
            os.path.join(agent_dir, "SightFlow.app"),
        ]
        app_candidates.extend(glob.glob(os.path.join(agent_dir, "dist", "mac*", "*.app")))
        for app_path in app_candidates:
            app_command = self._mac_app_command(app_path)
            if app_command:
                return app_command

        dev_launch = os.path.join(agent_dir, "scripts", "dev-launch.mjs")
        if os.path.exists(dev_launch) and os.path.exists(self.paths.node_exe):
            return [self.paths.node_exe, dev_launch]
        return []

    def _mac_app_command(self, app_path: str) -> list[str]:
        if not app_path.endswith(".app") or not os.path.isdir(app_path):
            return []
        macos_dir = os.path.join(app_path, "Contents", "MacOS")
        executable_names = ["Luminode", "LumiNode", "SightFlow", "sightflow-desktop-agent"]
        executable_names.extend(os.path.basename(path) for path in glob.glob(os.path.join(macos_dir, "*")))
        for name in executable_names:
            executable = os.path.join(macos_dir, name)
            if os.path.isfile(executable) and os.access(executable, os.X_OK):
                return [executable]
        return []

    def _popen_platform_kwargs(self) -> dict:
        if os.name == "nt":
            return {
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            }
        return {"start_new_session": True}

    def _terminate_process_tree(self, pid: int) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    def _kill_process_tree(self, pid: int) -> None:
        if os.name == "nt":
            return
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    def _redact_command(self, command: list[str]) -> list[str]:
        redacted: list[str] = []
        hide_next = False
        sensitive_flags = {"--token", "--api-key"}
        for part in command:
            if hide_next:
                redacted.append("[redacted]")
                hide_next = False
                continue
            redacted.append(part)
            if part in sensitive_flags:
                hide_next = True
        return redacted

    def _stop_process_on_port(self, port: int) -> bool:
        if port <= 0:
            return False
        pids = self._listening_pids_for_port(port)
        stopped = False
        for pid in pids:
            if not pid or pid == str(os.getpid()):
                continue
            self.append_log(f"[DesktopAgent] Stopping listener on port {port}: PID {pid}\n")
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                stopped = stopped or result.returncode == 0
            else:
                result = subprocess.run(["kill", "-TERM", pid], capture_output=True, text=True)
                stopped = stopped or result.returncode == 0
        return stopped

    def _listening_pids_for_port(self, port: int) -> set[str]:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "tcp"],
                    capture_output=True,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                return set()
            pids: set[str] = set()
            suffix = f":{port}"
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(suffix) and parts[3].upper() == "LISTENING":
                    pids.add(parts[-1])
            return pids
        try:
            result = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
        except Exception:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _deep_merge(self, base: dict, updates: dict) -> dict:
        merged = dict(base)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _public_policy(self, config: dict) -> dict:
        policy = self._deep_merge(self.default_config()["policy"], config.get("policy") or {})
        return {
            "allowScreenshot": bool(policy.get("allowScreenshot", True)),
            "allowClick": bool(policy.get("allowClick", False)),
            "allowType": bool(policy.get("allowType", False)),
            "allowWechatSend": bool(policy.get("allowWechatSend", False)),
            "requireConfirmForClick": bool(policy.get("requireConfirmForClick", True)),
            "requireConfirmForType": bool(policy.get("requireConfirmForType", True)),
            "requireConfirmForSend": bool(policy.get("requireConfirmForSend", True)),
            "blockedWindowKeywords": [str(item) for item in (policy.get("blockedWindowKeywords") or []) if str(item).strip()],
        }

    def _public_capture(self, config: dict) -> dict:
        capture = self._deep_merge(self.default_config()["capture"], config.get("capture") or {})
        return {
            "format": str(capture.get("format") or "jpeg"),
            "quality": int(capture.get("quality") or 82),
            "maxWidth": int(capture.get("maxWidth") or 1600),
        }

    def _public_action(self, config: dict) -> dict:
        action = self._deep_merge(self.default_config()["action"], config.get("action") or {})
        return {
            "clickDelayMs": int(action.get("clickDelayMs") or 120),
            "typeDelayMs": int(action.get("typeDelayMs") or 20),
            "timeoutMs": int(action.get("timeoutMs") or 30000),
        }

    def _public_provider(self, config: dict) -> dict:
        provider = self._primary_provider(config)
        api_key = str(provider.get("apiKey") or "")
        return {
            "baseUrl": str(provider.get("baseUrl") or ""),
            "baseURL": str(provider.get("baseUrl") or ""),
            "model": str(provider.get("model") or ""),
            "apiKeyAvailable": bool(api_key),
            "apiKeyPreview": f"****{api_key[-4:]}" if api_key else "",
        }

    def _public_wechat(self, config: dict) -> dict:
        wechat = self._deep_merge(self.default_config()["wechat"], config.get("wechat") or {})
        return {
            "sendMode": str(wechat.get("sendMode") or "draft_only"),
            "detectUnreadMode": str(wechat.get("detectUnreadMode") or "hybrid"),
        }

    def _enforce_policy(self, path: str, body: dict, config: dict) -> None:
        policy = self._public_policy(config)
        wechat = self._public_wechat(config)

        if path == "/screenshot" and not policy["allowScreenshot"]:
            raise PermissionError("desktop screenshot is disabled by launcher policy")

        if path == "/click":
            if not policy["allowClick"]:
                raise PermissionError("desktop click is disabled by launcher policy")
            if policy["requireConfirmForClick"] and not bool(body.get("confirmed")):
                raise PermissionError("desktop click requires confirmed=true")

        if path == "/type":
            if not policy["allowType"]:
                raise PermissionError("desktop typing is disabled by launcher policy")
            if policy["requireConfirmForType"] and not bool(body.get("confirmed")):
                raise PermissionError("desktop typing requires confirmed=true")
            self._block_sensitive_text(str(body.get("text") or ""), policy)

        if path == "/wechat/send":
            if not policy["allowWechatSend"]:
                raise PermissionError("wechat send is disabled by launcher policy")
            if wechat["sendMode"] != "auto_enter":
                raise PermissionError(f"wechat sendMode={wechat['sendMode']} blocks automatic sending")
            if policy["requireConfirmForSend"] and not bool(body.get("confirmed")):
                raise PermissionError("wechat send requires confirmed=true")
            self._block_sensitive_text(str(body.get("text") or ""), policy)

    def _block_sensitive_text(self, text: str, policy: dict) -> None:
        lowered = text.lower()
        for keyword in policy.get("blockedWindowKeywords") or []:
            if keyword and keyword.lower() in lowered:
                raise PermissionError(f"desktop action blocked by sensitive keyword: {keyword}")

    def _augment_body(self, path: str, body: dict, config: dict) -> dict:
        enriched = dict(body)
        if path == "/screenshot":
            enriched.setdefault("capture", self._public_capture(config))
        elif path in {"/click", "/type", "/wechat/send"}:
            enriched.setdefault("action", self._public_action(config))
        return enriched

    def _primary_provider(self, config: dict | None = None) -> dict:
        """返回统一配置主 provider 的 {apiKey, baseUrl, model},供桌面 agent 的视觉客户端使用。

        agent 的 VLM(布局测量/识别)默认直连火山地址,只换 key 会 401;必须把网关
        baseUrl + model 一起带过去,让 agent 走网关。
        """
        result = {"apiKey": "", "baseUrl": "", "model": ""}
        config = config or {}
        self._merge_provider_candidate(result, config.get("provider"))
        self._merge_provider_candidate(result, config.get("llm"))
        chat_provider = config.get("chatProvider")
        if isinstance(chat_provider, dict):
            self._merge_provider_candidate(result, chat_provider.get("config"))
        try:
            with open(self.paths.auth_profiles, "r", encoding="utf-8") as handle:
                profiles = json.load(handle)
            models = profiles.get("models") if isinstance(profiles, dict) else {}
            providers = models.get("providers") if isinstance(models, dict) else {}
            primary = models.get("primary") if isinstance(models, dict) else ""
            provider = providers.get(primary) if primary else None
            if not isinstance(provider, dict) and isinstance(providers, dict):
                provider = next((item for item in providers.values() if isinstance(item, dict)), None)
            provider = provider if isinstance(provider, dict) else {}
            if not result["apiKey"]:
                result["apiKey"] = str(provider.get("apiKey") or "").strip()
            if not result["baseUrl"]:
                result["baseUrl"] = str(provider.get("baseUrl") or provider.get("baseURL") or provider.get("url") or "").strip()
            model_list = provider.get("models")
            if not result["model"] and isinstance(model_list, list) and model_list:
                result["model"] = str(model_list[0] or "").strip()
            elif not result["model"] and isinstance(provider.get("model"), str):
                result["model"] = str(provider.get("model")).strip()
        except Exception:
            pass
        if not result["apiKey"]:
            result["apiKey"] = self._primary_api_key()
        return result

    def _merge_provider_candidate(self, result: dict, candidate: object) -> None:
        if not isinstance(candidate, dict):
            return
        api_key = str(candidate.get("apiKey") or candidate.get("apikey") or candidate.get("key") or "").strip()
        base_url = str(candidate.get("baseUrl") or candidate.get("baseURL") or candidate.get("url") or "").strip()
        model = str(candidate.get("model") or "").strip()
        if api_key:
            result["apiKey"] = api_key
        if base_url:
            result["baseUrl"] = base_url
        if model:
            result["model"] = model

    def _primary_api_key(self) -> str:
        try:
            with open(self.paths.auth_profiles, "r", encoding="utf-8") as handle:
                profiles = json.load(handle)
            models = profiles.get("models") if isinstance(profiles, dict) else {}
            providers = models.get("providers") if isinstance(models, dict) else {}
            primary = models.get("primary") if isinstance(models, dict) else ""
            provider = providers.get(primary) if primary else None
            if not isinstance(provider, dict) and isinstance(providers, dict):
                provider = next((item for item in providers.values() if isinstance(item, dict)), None)
            api_key = str((provider or {}).get("apiKey") or "").strip()
            if api_key:
                return api_key
            try:
                with open(self.paths.license_file, "r", encoding="utf-8") as handle:
                    license_data = json.load(handle)
                if isinstance(license_data, dict):
                    gateway_key = str(license_data.get("gatewayAccessToken") or license_data.get("gatewayToken") or "").strip()
                    if gateway_key:
                        return gateway_key
            except Exception:
                pass
            return ""
        except Exception:
            return ""

    def _read_output(self, process: subprocess.Popen) -> None:
        try:
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    self.append_log(f"[DesktopAgent] {line}")
        except Exception as error:
            self.append_log(f"[DesktopAgent] output read failed: {error}\n")
        exit_code = process.poll()
        self.append_log(f"[DesktopAgent] Process ended (exit: {exit_code})\n")
