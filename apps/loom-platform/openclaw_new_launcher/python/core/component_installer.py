"""Component download, verification, extraction, and rollback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Callable, Iterator, List
from urllib.request import Request, urlopen

from core.component_state import ComponentState, ComponentStateStore
from core.official_codex import (
    CODEX_DESKTOP_APP_ID,
    CODEX_DESKTOP_PACKAGE_NAMES,
    CODEX_STORE_COMMAND_TIMEOUT_MS,
    CODEX_STORE_INSTALLER_FILENAME,
    CODEX_STORE_INSTALLER_URL,
    CODEX_STORE_PRODUCT_ID,
    is_official_codex_component,
)
from core.paths import AppPaths
from core.release_manifest import ReleaseComponent
from core.secret_store import unprotect_secret


ComponentFetcher = Callable[[str, float], bytes]
StreamFetcherProgress = Callable[[str], None]
ComponentHealthChecker = Callable[[ReleaseComponent, str], None]
ComponentLauncher = Callable[[str, str], dict]
ComponentInstallerRunner = Callable[[List[str], str, int], subprocess.CompletedProcess]
ProcessTerminator = Callable[[int], None]
OfficialCodexStopper = Callable[[], None]
OfficialCodexProbe = Callable[[], bool]
ProgressCallback = Callable[[str, str], None]
RetrySleeper = Callable[[float], None]


class ComponentInstallError(RuntimeError):
    """Raised when a component cannot be installed safely."""


WINDOWS_COMMAND_SUFFIXES = ("", ".cmd", ".exe", ".ps1", ".bat")

KNOWN_COMPONENT_COMMANDS: dict[str, tuple[str, ...]] = {
    "codex-desktop": ("Codex", "codex"),
    "claude-code": ("claude",),
    "opencode": ("opencode",),
    "openclaw-companion": ("openclaw",),
    "hermes": ("hermes",),
}

KNOWN_NPM_PACKAGE_COMMANDS: dict[str, tuple[str, ...]] = {
    "@openai/codex": ("codex",),
    "@anthropic-ai/claude-code": ("claude",),
    "opencode-ai": ("opencode",),
    "opencode-windows-x64": ("opencode",),
    "openclaw": ("openclaw",),
}

RETRY_DELAYS_SECONDS = (0.0, 0.8, 1.6)
CODEX_STARTUP_PROBE_SECONDS = 0.8
EXTERNAL_ENTRY_CACHE_TTL_SECONDS = 30.0
VERSION_DETECT_TIMEOUT_MS = 5000
APPX_PROBE_TIMEOUT_MS = 3000
NPM_PROBE_TIMEOUT_MS = 3000
DOWNLOAD_CHUNK_SIZE = 64 * 1024
DOWNLOAD_PROGRESS_PERCENT_STEP = 5
DOWNLOAD_PROGRESS_INTERVAL_SECONDS = 2.0
_EXTERNAL_ENTRY_CACHE: dict[tuple[object, ...], tuple[float, str | None]] = {}
_GUIDANCE_WRITE_LOCK = threading.Lock()
LOOM_GUIDANCE_START = "<!-- LOOM:BEGIN DEFAULT-LANGUAGE -->"
LOOM_GUIDANCE_END = "<!-- LOOM:END DEFAULT-LANGUAGE -->"
LOOM_DEFAULT_LANGUAGE_GUIDANCE = """# LOOM 默认交互语言

- 默认使用简体中文回答，包括分析、计划、进度、结果说明和错误解释。
- 命令、路径、代码和日志保持原文；配置键也不翻译，必要时在后面补充中文说明。
- 用户明确指定其他语言时，遵循用户当次要求。
- 执行真实发布、评论、私信、加好友或其他对外动作前，遵循 LOOM 当前的确认、白名单、频控和审计规则。
""".strip()
PYTHON_SOURCE_CONFLICT_BOUNDARIES = ("<<<<<<<", ">>>>>>>")
PHONE_MODEL_IDS = {"agnes-2.0-flash"}
NON_TEXT_MODEL_MARKERS = (
    "image",
    "dall-e",
    "gpt-image",
    "flux",
    "midjourney",
    "sd-",
    "imagen",
    "seedream",
    "video",
    "veo",
    "sora",
    "seedance",
    "kling",
    "wan",
    "hailuo",
    "runway",
    "pika",
    "luma",
)
MODEL_ENV_SCRUB_COMPONENTS = {"codex-desktop", "claude-code", "opencode", "openclaw-companion"}
AGENT_MODEL_ENV_KEYS = (
    "LOOM_CODEX_API_KEY",
    "LOOM_CLAUDE_API_KEY",
    "LOOM_OPENCODE_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_API_TYPE",
    "OPENAI_API_VERSION",
    "OPENAI_MODEL",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_API_KEY",
    "CLAUDE_CODE_API_KEY",
    "CLAUDE_CODE_MODEL",
    "OPENCODE_API_KEY",
    "OPENCODE_BASE_URL",
    "OPENCODE_MODEL",
    "OPENCODE_PROVIDER",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENROUTER_API_KEY",
    "SILICONFLOW_API_KEY",
    "VOLCENGINE_ARK_API_KEY",
    "XAI_API_KEY",
    "ZHIPUAI_API_KEY",
)


@dataclass(frozen=True)
class PreviousInstall:
    path: str
    version: str | None


class ComponentInstaller:
    def __init__(
        self,
        *,
        base_path: str,
        state_store: ComponentStateStore,
        fetcher: ComponentFetcher | None = None,
        health_checker: ComponentHealthChecker | None = None,
        launcher: ComponentLauncher | None = None,
        process_terminator: ProcessTerminator | None = None,
        official_codex_stopper: OfficialCodexStopper | None = None,
        official_codex_probe: OfficialCodexProbe | None = None,
        installer_runner: ComponentInstallerRunner | None = None,
        retry_sleep: RetrySleeper | None = None,
        sync_user_experience: bool = False,
        timeout: float = 30.0,
    ):
        self.base_path = os.path.abspath(base_path)
        self.state_store = state_store
        self.fetcher = fetcher or _default_fetcher
        self._uses_default_fetcher = fetcher is None
        self.health_checker = health_checker or _default_health_checker
        self.launcher = launcher or self._default_launcher
        self._custom_launcher = launcher is not None
        self.process_terminator = process_terminator or _terminate_process_tree
        self.official_codex_stopper = official_codex_stopper or _stop_official_codex_desktop
        self.official_codex_probe = official_codex_probe or _official_codex_desktop_running
        self.installer_runner = installer_runner or _default_installer_runner
        self.retry_sleep = retry_sleep or time.sleep
        self.sync_user_experience = bool(sync_user_experience)
        self.timeout = timeout
        self.cache_dir = os.path.join(self.base_path, "data", ".installer", "cache")
        self.staging_dir = os.path.join(self.base_path, "data", ".installer", "staging")
        self.rollback_dir = os.path.join(self.base_path, "data", ".installer", "rollback")

    def _configure_component_experience(
        self,
        component_id: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[str, ...]:
        try:
            paths = _ensure_component_language_guidance(
                self.base_path,
                component_id,
                include_user_home=self.sync_user_experience,
            )
        except Exception as exc:
            if on_progress:
                on_progress(f"组件已安装，但简体中文默认规则写入失败：{_short_error(exc)}", "warning")
            return ()
        if paths and on_progress:
            on_progress("已同步简体中文默认规则，原有个人配置已保留", "ok")
        return paths

    def install(
        self,
        component: ReleaseComponent,
        *,
        simulate: bool = False,
        job_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ComponentState:
        existing_state = self.state_store.load().get(component.component_id)
        existing_version = existing_state.version if existing_state else None
        if simulate:
            return self._simulate_install(component, job_id=job_id, on_progress=on_progress)
        if is_official_codex_component(component):
            return self._install_official_codex(component, job_id=job_id, on_progress=on_progress)
        self._mark(component, "downloading", job_id=job_id, on_progress=on_progress, message=f"下载 {component.name}")
        try:
            package_path = self._download_to_cache(component, on_progress=on_progress)
        except Exception as exc:
            self.state_store.mark(component.component_id, "download_failed", version=component.version, job_id=job_id, error_message=str(exc))
            if on_progress:
                on_progress(f"下载失败：{exc}", "danger")
            raise ComponentInstallError(f"download failed for {component.component_id}: {exc}") from exc

        self._mark(component, "verifying", job_id=job_id, on_progress=on_progress, message=f"校验 {component.name}")
        digest = _sha256_file(package_path)
        if digest.lower() != component.sha256.lower():
            self.state_store.mark(
                component.component_id,
                "verify_failed",
                version=component.version,
                job_id=job_id,
                error_code="sha256_mismatch",
                error_message=f"sha256 mismatch: expected {component.sha256}, got {digest}",
            )
            if on_progress:
                on_progress("校验失败：sha256 不匹配", "danger")
            raise ComponentInstallError(f"sha256 mismatch for {component.component_id}")

        self._mark(component, "extracting", job_id=job_id, on_progress=on_progress, message=f"安装 {component.name}")
        install_path = self._safe_install_path(component.install_path)
        staging_path = self._component_staging_path(component)
        self._remove_path(staging_path)
        os.makedirs(staging_path, exist_ok=True)

        try:
            self._extract(component, package_path, staging_path)
            self._assert_entry_exists(component, staging_path)
            previous = self._swap(component, staging_path, install_path, previous_version=existing_version)
        except Exception as exc:
            self._remove_path(staging_path)
            self.state_store.mark(component.component_id, "extract_failed", version=component.version, job_id=job_id, error_message=str(exc))
            if on_progress:
                on_progress(f"安装失败：{exc}", "danger")
            raise ComponentInstallError(f"extract failed for {component.component_id}: {exc}") from exc

        self._mark(component, "configuring", job_id=job_id, on_progress=on_progress, message=f"配置 {component.name}")
        silent_installer_ran = False
        managed_codex_entry = None
        managed_codex_version = None
        verified_bundled_entry = self._verified_bundled_entry(component, install_path)
        if component.component_id == "codex-desktop":
            managed_codex_entry = self._managed_codex_entry(install_path)
            if managed_codex_entry:
                managed_codex_version = self._detect_installed_version(component, install_path, entry_path=managed_codex_entry)
                if not managed_codex_version:
                    self._restore_previous_after_failed_health(install_path, previous)
                    self.state_store.mark(
                        component.component_id,
                        "health_failed",
                        version=component.version,
                        job_id=job_id,
                        previous_version=previous.version if previous else None,
                        error_message="managed Codex version check failed",
                    )
                    if on_progress:
                        on_progress("检测失败：managed Codex version check failed", "danger")
                    raise ComponentInstallError(f"health check failed for {component.component_id}: managed Codex version check failed")
        if component.archive_type == "installer" and getattr(component, "installer_args", ()):
            try:
                if on_progress:
                    on_progress(f"运行 {component.name} 静默安装器", "neutral")
                self._run_silent_installer(component, install_path)
                silent_installer_ran = True
                self._assert_external_install_available(component, force_refresh=True)
            except Exception as exc:
                self.state_store.mark(
                    component.component_id,
                    "config_failed",
                    version=component.version,
                    job_id=job_id,
                    previous_version=previous.version if previous else None,
                    error_message=str(exc),
                )
                if on_progress:
                    on_progress(f"配置失败：{exc}", "danger")
                raise ComponentInstallError(f"installer failed for {component.component_id}: {exc}") from exc
        if getattr(component, "install_command", ()) and not managed_codex_version and not verified_bundled_entry:
            try:
                if on_progress:
                    on_progress(f"执行 {component.name} 安装命令", "neutral")
                self._run_install_command(component, install_path, package_path=package_path, on_progress=on_progress)
                self._assert_external_install_available(component, force_refresh=True)
            except Exception as exc:
                self._restore_previous_after_failed_health(install_path, previous)
                self.state_store.mark(
                    component.component_id,
                    "config_failed",
                    version=component.version,
                    job_id=job_id,
                    previous_version=previous.version if previous else None,
                    error_message=str(exc),
                )
                if on_progress:
                    on_progress(f"配置失败：{exc}", "danger")
                raise ComponentInstallError(f"install command failed for {component.component_id}: {exc}") from exc
        if component.health_check is not None:
            self._mark(component, "health_checking", job_id=job_id, on_progress=on_progress, message=f"检测 {component.name}")
            try:
                self.health_checker(component, install_path)
            except Exception as exc:
                self._restore_previous_after_failed_health(install_path, previous)
                self.state_store.mark(
                    component.component_id,
                    "health_failed",
                    version=component.version,
                    job_id=job_id,
                    previous_version=previous.version if previous else None,
                    error_message=str(exc),
                )
                if on_progress:
                    on_progress(f"检测失败：{exc}", "danger")
                raise ComponentInstallError(f"health check failed for {component.component_id}: {exc}") from exc
        elif component.archive_type == "installer" and not silent_installer_ran:
            state = self.state_store.mark(
                component.component_id,
                "manual_install_required",
                version=component.version,
                job_id=job_id,
                previous_version=previous.version if previous else None,
            )
            if on_progress:
                on_progress(f"{component.name} 安装器已保存，等待手动安装和检测", "warning")
            return state

        state = self.state_store.mark(
            component.component_id,
            "ready",
            version=component.version,
            job_id=job_id,
            previous_version=previous.version if previous else None,
        )
        self._configure_component_experience(component.component_id, on_progress=on_progress)
        if on_progress:
            on_progress(f"{component.name} 已就绪", "ok")
        return state

    def _install_official_codex(
        self,
        component: ReleaseComponent,
        *,
        job_id: str | None,
        on_progress: ProgressCallback | None,
    ) -> ComponentState:
        existing_entry = self._official_codex_entry(refresh=True)
        if existing_entry:
            version = _codex_desktop_version_from_path(existing_entry) or component.version
            state = self.state_store.mark(component.component_id, "ready", version=version, job_id=job_id)
            self._configure_component_experience(component.component_id, on_progress=on_progress)
            if on_progress:
                on_progress("ChatGPT Codex 原版已安装", "ok")
            return state

        self._mark(
            component,
            "configuring",
            job_id=job_id,
            on_progress=on_progress,
            message="正在通过 Microsoft Store 安装 ChatGPT Codex 原版",
        )
        winget_error = ""
        winget_command = [
            "winget",
            "install",
            "--id",
            CODEX_STORE_PRODUCT_ID,
            "--source",
            "msstore",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
        try:
            result = self.installer_runner(winget_command, self.base_path, CODEX_STORE_COMMAND_TIMEOUT_MS)
            code = int(getattr(result, "returncode", 0) or 0)
            winget_succeeded = code in (0, 3010)
            if code not in (0, 3010):
                output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
                winget_error = f"winget 返回 {code}：{_short_error(output)}"
        except Exception as exc:
            winget_succeeded = False
            winget_error = str(exc) or "winget 不可用"

        installed_entry = self._wait_for_official_codex_entry() if winget_succeeded else self._official_codex_entry(refresh=True)
        if installed_entry:
            version = _codex_desktop_version_from_path(installed_entry) or component.version
            state = self.state_store.mark(component.component_id, "ready", version=version, job_id=job_id)
            self._configure_component_experience(component.component_id, on_progress=on_progress)
            if on_progress:
                on_progress("ChatGPT Codex 原版已安装", "ok")
            return state

        if on_progress:
            detail = f"（{winget_error}）" if winget_error else ""
            on_progress(f"Microsoft Store 自动安装尚未完成，正在打开官方安装器{detail}", "warning")
        bootstrapper_error = ""
        try:
            installer_path = self._download_official_codex_store_installer()
            self._verify_microsoft_store_installer(installer_path)
            self._launch_official_codex_store_installer(installer_path)
        except Exception as exc:
            bootstrapper_error = str(exc) or "微软安装器不可用"
            try:
                self._open_official_codex_store_page()
            except Exception as store_exc:
                message = f"ChatGPT Codex 原版安装入口均不可用：{bootstrapper_error}；{store_exc}"
                self.state_store.mark(
                    component.component_id,
                    "config_failed",
                    version=component.version,
                    job_id=job_id,
                    error_code="official_store_install_failed",
                    error_message=message,
                )
                raise ComponentInstallError(message) from store_exc

        state = self.state_store.mark(
            component.component_id,
            "manual_install_required",
            version=component.version,
            job_id=job_id,
            error_code="waiting_for_microsoft_store",
            error_message=(
                "请在已打开的 Microsoft Store 中完成 ChatGPT 安装，然后点击重新检测"
                + (f"；官方引导器未执行：{bootstrapper_error}" if bootstrapper_error else "")
            ),
        )
        if on_progress:
            on_progress("官方安装器已打开；完成安装后点击重新检测", "warning")
        return state

    def _wait_for_official_codex_entry(self) -> str | None:
        for delay in (0.0, 0.5, 1.0, 2.0, 3.0):
            if delay:
                self.retry_sleep(delay)
            entry = self._official_codex_entry(refresh=True)
            if entry:
                return entry
        return None

    def _download_official_codex_store_installer(self) -> str:
        os.makedirs(self.cache_dir, exist_ok=True)
        target = os.path.join(self.cache_dir, CODEX_STORE_INSTALLER_FILENAME)
        payload = self.fetcher(CODEX_STORE_INSTALLER_URL, self.timeout)
        if not payload:
            raise ComponentInstallError("微软官方安装器下载为空")
        temporary = target + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target

    def _verify_microsoft_store_installer(self, installer_path: str) -> None:
        escaped = installer_path.replace("'", "''")
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
                "[pscustomobject]@{Status=[string]$s.Status;Subject=[string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress"
            ),
        ]
        result = self.installer_runner(command, self.base_path, 30000)
        if int(getattr(result, "returncode", 0) or 0) != 0:
            raise ComponentInstallError("无法验证微软官方安装器签名")
        try:
            signature = json.loads(str(getattr(result, "stdout", "") or "{}"))
        except json.JSONDecodeError as exc:
            raise ComponentInstallError("微软官方安装器签名结果无法解析") from exc
        status = str(signature.get("Status") or "").strip().lower()
        subject = str(signature.get("Subject") or "").strip().lower()
        if status != "valid" or "microsoft corporation" not in subject:
            raise ComponentInstallError("安装器不是有效的 Microsoft 签名文件")

    def _launch_official_codex_store_installer(self, installer_path: str) -> None:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        subprocess.Popen(
            [installer_path],
            cwd=os.path.dirname(installer_path),
            close_fds=True,
            creationflags=creationflags,
        )

    def _open_official_codex_store_page(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        subprocess.Popen(
            ["explorer.exe", f"ms-windows-store://pdp/?ProductId={CODEX_STORE_PRODUCT_ID}"],
            cwd=self.base_path,
            close_fds=True,
            creationflags=creationflags,
        )

    def detect(
        self,
        component: ReleaseComponent,
        *,
        job_id: str | None = None,
        on_progress: ProgressCallback | None = None,
        force_external_probe: bool = False,
    ) -> ComponentState:
        install_path = self._safe_install_path(component.install_path)
        self._mark(component, "health_checking", job_id=job_id, on_progress=on_progress, message=f"检测 {component.name}")
        if is_official_codex_component(component):
            official_entry = self._official_codex_entry(refresh=force_external_probe)
            if not official_entry:
                state = self.state_store.mark(
                    component.component_id,
                    "not_installed",
                    version=component.version,
                    job_id=job_id,
                )
                if on_progress:
                    on_progress("未检测到 ChatGPT Codex 原版", "neutral")
                return state
        if not os.path.exists(install_path):
            external_entry = self._first_existing_external_entry(component, refresh=force_external_probe)
            if not external_entry:
                state = self.state_store.mark(
                    component.component_id,
                    "not_installed",
                    version=component.version,
                    job_id=job_id,
                )
                if on_progress:
                    on_progress(f"{component.name} 未安装", "neutral")
                return state
        try:
            entry_path = self._resolve_component_entry(
                component,
                install_path,
                force_external_probe=force_external_probe,
            )
            self._assert_component_available(component, install_path, entry_path)
            if component.health_check is not None:
                self.health_checker(component, install_path)
        except Exception as exc:
            message = str(exc) or "组件检测失败"
            self.state_store.mark(
                component.component_id,
                "health_failed",
                version=component.version,
                job_id=job_id,
                error_code="detect_failed",
                error_message=message,
            )
            if on_progress:
                on_progress(f"检测失败：{message}", "danger")
            raise ComponentInstallError(f"detect failed for {component.component_id}: {message}") from exc

        installed_version = self._detect_installed_version(component, install_path, entry_path=entry_path)
        is_managed_codex = component.component_id == "codex-desktop" and entry_path == self._managed_codex_entry(install_path)
        if is_managed_codex and not installed_version:
            message = "managed Codex version check failed"
            self.state_store.mark(
                component.component_id,
                "health_failed",
                version=component.version,
                job_id=job_id,
                error_code="detect_failed",
                error_message=message,
            )
            if on_progress:
                on_progress(f"检测失败：{message}", "danger")
            raise ComponentInstallError(f"detect failed for {component.component_id}: {message}")
        is_codex_desktop_app = component.component_id == "codex-desktop" and _is_codex_desktop_executable(entry_path)
        if installed_version and not is_codex_desktop_app and not _versions_match(component.version, installed_version):
            state = self.state_store.mark(component.component_id, "upgrade_available", version=installed_version, job_id=job_id)
            if on_progress:
                on_progress(f"{component.name} 已检测到旧版本 {installed_version}，建议升级到 {component.version}", "warning")
            return state

        state = self.state_store.mark(component.component_id, "ready", version=installed_version or component.version, job_id=job_id)
        self._configure_component_experience(component.component_id, on_progress=on_progress)
        if on_progress:
            on_progress(f"{component.name} 已就绪", "ok")
        return state

    def launch(self, component: ReleaseComponent, *, job_id: str | None = None) -> dict:
        state = self.state_store.load().get(component.component_id)
        if state is not None and state.status == "starting":
            state = self.detect(component, job_id=job_id, force_external_probe=True)
        if state is None or state.status not in {"ready", "started"}:
            raise ComponentInstallError("组件尚未就绪，请先检测或安装")
        install_path = self._safe_install_path(component.install_path)
        entry_path = self._component_entry_path(component, install_path)
        self._assert_component_sources_clean(component, install_path, entry_path)
        self._configure_component_experience(component.component_id)
        launch_version = state.version or component.version
        if is_official_codex_component(component):
            launch_version = _codex_desktop_version_from_path(entry_path) or launch_version
        elif not self._custom_launcher and component.component_id in {
            "claude-code",
            "opencode",
            "openclaw-companion",
            "hermes",
        }:
            detected_version = self._detect_installed_version(component, install_path, entry_path=entry_path)
            if not detected_version:
                message = "启动前自检失败：组件入口无法正常执行，请重新安装后再启动"
                self.state_store.mark(
                    component.component_id,
                    "start_failed",
                    version=launch_version,
                    job_id=job_id,
                    error_code="launch_preflight_failed",
                    error_message=message,
                )
                raise ComponentInstallError(message)
            launch_version = detected_version
        self.state_store.mark(component.component_id, "starting", version=launch_version, job_id=job_id)
        try:
            cwd = self._component_cwd(install_path)
            if self._custom_launcher:
                result = self.launcher(entry_path, cwd)
            else:
                result = self._default_component_launcher(component, entry_path, cwd)
        except Exception as exc:
            message = str(exc) or "组件启动失败"
            self.state_store.mark(
                component.component_id,
                "start_failed",
                version=launch_version,
                job_id=job_id,
                error_code="start_failed",
                error_message=f"启动失败：{message}",
            )
            raise ComponentInstallError(f"启动失败：{message}") from exc
        try:
            self.state_store.mark(component.component_id, "started", version=launch_version, job_id=job_id)
        except Exception as exc:
            pid = int(result.get("pid") or 0) if isinstance(result, dict) else 0
            termination_error = ""
            if pid > 0:
                try:
                    self.process_terminator(pid)
                except Exception as terminate_exc:
                    termination_error = f"；终止进程失败：{terminate_exc}"
            message = f"启动状态保存失败：{exc}{termination_error}"
            try:
                self.state_store.mark(
                    component.component_id,
                    "start_failed",
                    version=launch_version,
                    job_id=job_id,
                    error_code="start_state_persist_failed",
                    error_message=message,
                )
            except Exception:
                pass
            raise ComponentInstallError(message) from exc
        return {
            "success": True,
            "componentId": component.component_id,
            "status": "started",
            **(result if isinstance(result, dict) else {}),
        }

    def restart(self, component: ReleaseComponent, *, job_id: str | None = None) -> dict:
        if not is_official_codex_component(component):
            raise ComponentInstallError("当前仅支持重启 OpenAI 官方 ChatGPT Codex")
        state = self.state_store.load().get(component.component_id)
        if state is None or state.status not in {"ready", "started"}:
            raise ComponentInstallError("Codex 尚未就绪，请先重新检测")
        try:
            self.official_codex_stopper()
        except Exception as exc:
            message = f"停止 OpenAI 官方 Codex 失败：{exc}"
            self.state_store.mark(
                component.component_id,
                "start_failed",
                version=state.version,
                job_id=job_id,
                error_code="restart_stop_failed",
                error_message=message,
            )
            raise ComponentInstallError(message) from exc
        self.state_store.mark(component.component_id, "ready", version=state.version, job_id=job_id)
        self.retry_sleep(0.25)
        result = self.launch(component, job_id=job_id)
        for _attempt in range(10):
            if self.official_codex_probe():
                return result
            self.retry_sleep(0.4)
        message = "OpenAI 官方 Codex 未在预期时间内启动"
        self.state_store.mark(
            component.component_id,
            "start_failed",
            version=state.version,
            job_id=job_id,
            error_code="restart_launch_unverified",
            error_message=message,
        )
        raise ComponentInstallError(message)

    def _simulate_install(
        self,
        component: ReleaseComponent,
        *,
        job_id: str | None,
        on_progress: ProgressCallback | None,
    ) -> ComponentState:
        stages = (
            ("resolving_manifest", f"准备 {component.name}"),
            ("downloading", f"下载 {component.name}"),
            ("verifying", f"校验 {component.name}"),
            ("extracting", f"安装 {component.name}"),
            ("configuring", f"配置 {component.name}"),
            ("health_checking", f"检测 {component.name}"),
        )
        for status, message in stages:
            if on_progress:
                on_progress(message, "neutral")
        state = ComponentState(component.component_id, "simulation_ready", version=component.version, job_id=job_id)
        if on_progress:
            on_progress(f"{component.name} 流程预检已完成", "ok")
        return state

    def rollback(self, component_id: str) -> ComponentState:
        states = self.state_store.load()
        state = states.get(component_id)
        previous_version = state.previous_version if state else None
        previous_path = self._rollback_path(component_id)
        if not os.path.isdir(previous_path):
            raise ComponentInstallError(f"rollback is not available for {component_id}")

        install_path = self._find_active_component_path(component_id)
        if install_path and os.path.exists(install_path):
            self._remove_path(install_path)
        elif install_path:
            os.makedirs(os.path.dirname(install_path), exist_ok=True)

        if not install_path:
            install_path = os.path.join(self.base_path, "agents", component_id)
        os.makedirs(os.path.dirname(install_path), exist_ok=True)
        self._replace_path(previous_path, install_path)

        return self.state_store.mark(component_id, "ready", version=previous_version, previous_version=None)

    def uninstall(
        self,
        component: ReleaseComponent,
        *,
        job_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ComponentState:
        existing_state = self.state_store.load().get(component.component_id)
        version = (existing_state.version if existing_state else None) or component.version
        self._mark(component, "uninstalling", job_id=job_id, on_progress=on_progress, message=f"卸载 {component.name}")
        try:
            install_path = self._safe_install_path(component.install_path)
            managed_codex = component.component_id == "codex-desktop" and os.path.exists(install_path)
            if component.component_id == "codex-desktop" and not managed_codex:
                raise ComponentInstallError("检测到的是外部 Codex 安装，请从原安装来源卸载")
            if not managed_codex:
                self._run_uninstall_command(component)
            self._invalidate_external_entry_cache(component)
            self._remove_path(install_path)
            self._remove_path(self._rollback_path(component.component_id))
            self._remove_path(self._component_staging_path(component))
        except Exception as exc:
            self.state_store.mark(
                component.component_id,
                "uninstall_failed",
                version=version,
                job_id=job_id,
                error_code="uninstall_failed",
                error_message=str(exc),
            )
            if on_progress:
                on_progress(f"卸载失败：{exc}", "danger")
            raise ComponentInstallError(f"uninstall failed for {component.component_id}: {exc}") from exc
        state = self.state_store.mark(component.component_id, "not_installed", version=component.version, job_id=job_id)
        if on_progress:
            on_progress(f"{component.name} 已卸载", "ok")
        return state

    def _verified_cache_path(self, component: ReleaseComponent) -> str:
        safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", component.version)
        extension = {
            "tgz": ".tgz",
            "zip": ".zip",
            "installer": ".exe" if os.name == "nt" else ".installer",
        }.get(str(component.archive_type or "").strip().lower(), ".pkg")
        name = f"{component.component_id}-{safe_version}-{component.sha256}{extension}"
        return os.path.join(self.cache_dir, name)

    def _download_to_cache(self, component: ReleaseComponent, on_progress: ProgressCallback | None = None) -> str:
        verified_path = self._verified_cache_path(component)
        partial_path = verified_path + ".part"
        os.makedirs(self.cache_dir, exist_ok=True)
        if os.path.isfile(verified_path):
            if _sha256_file(verified_path).lower() == component.sha256.lower():
                if on_progress:
                    on_progress(f"使用已验证本地缓存：{component.name}", "neutral")
                return verified_path
            self._remove_path(verified_path)
        seeded_path = self._copy_verified_local_seed_to_cache(component, verified_path, on_progress=on_progress)
        if seeded_path:
            return seeded_path

        errors = []
        for url_index, url in enumerate(component.urls):
            if url_index > 0 and os.path.exists(partial_path):
                self._remove_path(partial_path)
            for attempt_index, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
                if delay > 0:
                    self.retry_sleep(delay)
                try:
                    if self._uses_default_fetcher:
                        offset = os.path.getsize(partial_path) if os.path.exists(partial_path) else 0
                        progress = self._stream_progress(component, on_progress)
                        _default_stream_fetcher(url, self.timeout, partial_path, offset, progress)
                    else:
                        payload = self.fetcher(url, self.timeout)
                        with open(partial_path, "wb") as handle:
                            handle.write(payload)
                        if on_progress:
                            on_progress(
                                f"下载 {component.name}，100%，{_format_megabytes(len(payload))} / {_format_megabytes(len(payload))}",
                                "neutral",
                            )
                    digest = _sha256_file(partial_path)
                    if digest.lower() != component.sha256.lower():
                        self._remove_path(partial_path)
                        raise ComponentInstallError(
                            f"sha256 mismatch: expected {component.sha256}, got {digest}"
                        )
                    os.replace(partial_path, verified_path)
                    return verified_path
                except Exception as exc:
                    is_last_attempt = attempt_index >= len(RETRY_DELAYS_SECONDS)
                    if not is_last_attempt:
                        if on_progress:
                            on_progress(f"下载失败，正在重试第 {attempt_index + 1} 次：{_short_error(exc)}", "warning")
                        continue
                    errors.append(f"{url}: {exc}")
        raise ComponentInstallError("; ".join(errors) if errors else "no component urls configured")

    def _mark(
        self,
        component: ReleaseComponent,
        status: str,
        *,
        job_id: str | None,
        on_progress: ProgressCallback | None,
        message: str,
    ) -> ComponentState:
        state = self.state_store.mark(component.component_id, status, version=component.version, job_id=job_id)
        if on_progress:
            on_progress(message, "neutral")
        return state

    def _stream_progress(self, component: ReleaseComponent, on_progress: ProgressCallback | None) -> StreamFetcherProgress | None:
        if on_progress is None:
            return None
        return lambda detail: on_progress(f"下载 {component.name}，{detail}", "neutral")

    def _copy_verified_local_seed_to_cache(
        self,
        component: ReleaseComponent,
        verified_path: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> str | None:
        for seed_path in self._local_seed_candidates(component):
            try:
                if os.path.getsize(seed_path) != component.size:
                    if on_progress:
                        on_progress(f"忽略未通过校验的本地预置包：{seed_path}", "warning")
                    continue
                digest = _sha256_file(seed_path)
            except OSError:
                continue
            if digest.lower() != component.sha256.lower():
                if on_progress:
                    on_progress(f"忽略未通过校验的本地预置包：{seed_path}", "warning")
                continue
            shutil.copy2(seed_path, verified_path)
            if on_progress:
                on_progress(f"使用已验证本地预置包：{component.name}", "neutral")
            return verified_path
        return None

    def _local_seed_candidates(self, component: ReleaseComponent) -> list[str]:
        candidates: list[str] = []
        expected_names: list[str] = []
        for url in component.urls:
            basename = os.path.basename(str(url).split("?", 1)[0].rstrip("/"))
            if basename:
                expected_names.append(basename)
        for seed_dir in self._local_seed_directories(component):
            if not os.path.isdir(seed_dir):
                continue
            for name in expected_names:
                path = os.path.join(seed_dir, name)
                if os.path.isfile(path):
                    _append_unique(candidates, path)
            try:
                entries = sorted(os.listdir(seed_dir))
            except OSError:
                continue
            for entry in entries:
                path = os.path.join(seed_dir, entry)
                if os.path.isfile(path):
                    _append_unique(candidates, path)
        return candidates

    def _local_seed_directories(self, component: ReleaseComponent) -> list[str]:
        component_dir = component.component_id
        directories: list[str] = []
        bases = (
            os.path.join(self.base_path, "redist", "components"),
            os.path.join(self.base_path, "_up_", "redist", "components"),
            os.path.join(os.path.dirname(self.base_path), "redist", "components"),
            os.path.join(self.base_path, "LOOMFiles", "redist", "components"),
            os.path.join(self.base_path, "LOOMFiles", "_up_", "redist", "components"),
            os.path.join(self.base_path, "OpenClawFiles", "redist", "components"),
            os.path.join(self.base_path, "OpenClawFiles", "_up_", "redist", "components"),
        )
        for base in bases:
            _append_unique(directories, os.path.join(base, component_dir))
        return directories

    def _extract(self, component: ReleaseComponent, package_path: str, staging_path: str) -> None:
        if component.archive_type == "tgz":
            self._extract_tgz(package_path, staging_path)
            return

        if component.archive_type != "zip":
            os.makedirs(staging_path, exist_ok=True)
            filename = component.entry or f"{component.component_id}.bin"
            target = self._safe_join(staging_path, filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(package_path, target)
            return

        with zipfile.ZipFile(package_path, "r") as archive:
            for info in archive.infolist():
                self._safe_join(staging_path, info.filename)
            archive.extractall(staging_path)

    def _extract_tgz(self, package_path: str, staging_path: str) -> None:
        os.makedirs(staging_path, exist_ok=True)
        with tarfile.open(package_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                target = self._safe_join(staging_path, member.name)
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ComponentInstallError("tgz contains an unsupported entry type")
                source = archive.extractfile(member)
                if source is None:
                    raise ComponentInstallError("tgz entry could not be read")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)

    def _assert_entry_exists(self, component: ReleaseComponent, staging_path: str) -> None:
        if not component.entry:
            return
        target = self._safe_join(staging_path, component.entry)
        if not os.path.isfile(target):
            raise ComponentInstallError(f"component entry is missing: {component.entry}")

    def _assert_component_available(self, component: ReleaseComponent, install_path: str, entry_path: str = "") -> None:
        has_internal_install = os.path.exists(install_path)
        if not entry_path:
            entry_path = self._resolve_component_entry(component, install_path)
        if not has_internal_install and not entry_path:
            raise ComponentInstallError("未找到组件目录，请先安装或重新安装")
        self._assert_component_sources_clean(component, install_path, entry_path)

    def _component_entry_path(self, component: ReleaseComponent, install_path: str) -> str:
        return self._resolve_component_entry(component, install_path)

    def _verified_bundled_entry(self, component: ReleaseComponent, install_path: str) -> str | None:
        relative_by_component = {
            "claude-code": os.path.join("package", "bin", "claude.exe"),
            "opencode": os.path.join("package", "bin", "opencode.exe"),
        }
        relative = relative_by_component.get(component.component_id)
        if not relative:
            return None
        candidate = os.path.abspath(os.path.join(install_path, relative))
        if _is_path_inside(candidate, install_path) and os.path.isfile(candidate):
            return candidate
        return None

    def _managed_codex_entry(self, install_path: str) -> str | None:
        candidate = os.path.abspath(
            os.path.join(
                install_path,
                "package",
                "vendor",
                "x86_64-pc-windows-msvc",
                "bin",
                "codex.exe",
            )
        )
        return candidate if _is_path_inside(candidate, install_path) and os.path.isfile(candidate) else None

    def _resolve_component_entry(
        self,
        component: ReleaseComponent,
        install_path: str,
        allow_expensive: bool = True,
        force_external_probe: bool = False,
    ) -> str:
        if is_official_codex_component(component):
            official_entry = self._official_codex_entry(refresh=force_external_probe)
            if official_entry:
                return official_entry
            raise ComponentInstallError("未检测到 ChatGPT Codex 原版，请先通过 Microsoft Store 安装")
        if component.component_id == "codex-desktop":
            managed_entry = self._managed_codex_entry(install_path)
            if managed_entry:
                return managed_entry
        verified_bundled_entry = self._verified_bundled_entry(component, install_path)
        if verified_bundled_entry:
            return verified_bundled_entry
        if component.entry:
            target = self._safe_join(install_path, component.entry)
            if os.path.isfile(target):
                return target
        external_entry = (
            self._first_existing_external_entry(component, refresh=force_external_probe)
            if allow_expensive
            else self._cached_existing_external_entry(component)
        )
        if external_entry:
            return external_entry
        if component.entry:
            raise ComponentInstallError("未找到组件文件，请先安装或重新安装")
        raise ComponentInstallError("组件缺少启动入口")

    def _cached_existing_external_entry(self, component: ReleaseComponent) -> str | None:
        cache_key = self._external_entry_cache_key(component)
        cached = _EXTERNAL_ENTRY_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, entry_path = cached
        if entry_path:
            if os.path.isfile(entry_path):
                return entry_path
            _EXTERNAL_ENTRY_CACHE.pop(cache_key, None)
            return None
        if time.monotonic() - created_at > EXTERNAL_ENTRY_CACHE_TTL_SECONDS:
            _EXTERNAL_ENTRY_CACHE.pop(cache_key, None)
            return None
        return None

    def _first_existing_external_entry(self, component: ReleaseComponent, *, refresh: bool = False) -> str | None:
        cache_key = self._external_entry_cache_key(component)
        if not refresh:
            cached_entry = self._cached_existing_external_entry(component)
            if cached_entry is not None or cache_key in _EXTERNAL_ENTRY_CACHE:
                return cached_entry
        for candidate in self._external_entry_candidates(component):
            if os.path.isfile(candidate):
                _EXTERNAL_ENTRY_CACHE[cache_key] = (time.monotonic(), candidate)
                return candidate
        _EXTERNAL_ENTRY_CACHE[cache_key] = (time.monotonic(), None)
        return None

    def _external_entry_cache_key(self, component: ReleaseComponent) -> tuple[object, ...]:
        return (
            os.path.normcase(os.path.abspath(self.base_path)),
            component.component_id,
            component.install_path,
            component.entry or "",
            component.archive_type,
            component.platform,
            component.arch,
            component.version,
            tuple(str(path) for path in getattr(component, "external_paths", ())),
            tuple(str(part) for part in getattr(component, "install_command", ())),
        )

    def _invalidate_external_entry_cache(self, component: ReleaseComponent) -> None:
        _EXTERNAL_ENTRY_CACHE.pop(self._external_entry_cache_key(component), None)

    def _assert_component_sources_clean(self, component: ReleaseComponent, install_path: str, entry_path: str = "") -> None:
        if component.component_id != "hermes":
            return
        for root in _hermes_source_roots(install_path, entry_path):
            conflict = _first_python_conflict_marker(root)
            if conflict:
                raise ComponentInstallError(
                    f"Hermes 运行时包损坏：{conflict} 含有 Git 冲突标记，请重新安装 Hermes。"
                )

    def _external_entry_candidates(self, component: ReleaseComponent) -> Iterator[str]:
        seen: set[str] = set()
        for candidate in self._fast_external_entry_candidates(component):
            key = os.path.normcase(os.path.abspath(candidate))
            if key not in seen:
                seen.add(key)
                yield candidate
        for candidate in self._expensive_external_entry_candidates(component):
            key = os.path.normcase(os.path.abspath(candidate))
            if key not in seen:
                seen.add(key)
                yield candidate

    def _fast_external_entry_candidates(self, component: ReleaseComponent) -> list[str]:
        candidates: list[str] = []
        if component.component_id == "codex-desktop":
            for candidate in self._codex_desktop_local_entry_candidates():
                _append_unique(candidates, candidate)

        command_names = self._external_command_names(component)
        if self._npm_package_names_from_command(component):
            private_prefix = self._npm_private_prefix()
            for name in command_names:
                _append_unique(candidates, os.path.join(private_prefix, name))
                _append_unique(candidates, os.path.join(private_prefix, "bin", name))

        for raw_path in getattr(component, "external_paths", ()):
            candidate = self._expand_external_path(raw_path)
            self._append_external_path_variants(candidates, candidate)

        for candidate in self._default_external_entry_candidates(command_names):
            _append_unique(candidates, candidate)

        for name in command_names:
            found = shutil.which(name)
            if found:
                _append_unique(candidates, found)

        return candidates

    def _expensive_external_entry_candidates(self, component: ReleaseComponent) -> list[str]:
        candidates: list[str] = []
        if component.component_id == "codex-desktop":
            for candidate in self._codex_desktop_appx_entry_candidates():
                _append_unique(candidates, candidate)

        npm_package_names = self._npm_package_names_from_command(component)
        for directory in self._npm_global_bin_dirs() if npm_package_names else ():
            command_names = self._external_command_names(component)
            for name in command_names:
                _append_unique(candidates, os.path.join(directory, name))

        for package_name in npm_package_names:
            command_names = self._external_command_names(component)
            package_entry = self._npm_package_bin_entry(package_name, command_names)
            if package_entry:
                _append_unique(candidates, package_entry)
        return candidates

    def _codex_desktop_entry_candidates(self) -> tuple[str, ...]:
        candidates = list(self._codex_desktop_local_entry_candidates())
        for candidate in self._codex_desktop_appx_entry_candidates():
            _append_unique(candidates, candidate)
        return tuple(candidates)

    def _codex_desktop_local_entry_candidates(self) -> tuple[str, ...]:
        candidates: list[str] = []
        localappdata = os.environ.get("LOCALAPPDATA", "").strip()
        program_files = os.environ.get("ProgramFiles", "").strip()
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "").strip()
        for root, suffixes in (
            (localappdata, ("Programs/Codex/Codex.exe", "Programs/OpenAI Codex/Codex.exe", "OpenAI/Codex/Codex.exe")),
            (program_files, ("Codex/Codex.exe", "OpenAI Codex/Codex.exe")),
            (program_files_x86, ("Codex/Codex.exe", "OpenAI Codex/Codex.exe")),
        ):
            if not root:
                continue
            for suffix in suffixes:
                _append_unique(candidates, os.path.abspath(os.path.join(root, *suffix.split("/"))))
        return tuple(candidates)

    def _codex_desktop_appx_entry_candidates(self) -> tuple[str, ...]:
        candidates: list[str] = []
        for install_location in self._codex_desktop_appx_locations():
            for relative in ("app/ChatGPT.exe", "app/Codex.exe", "ChatGPT.exe", "Codex.exe"):
                _append_unique(candidates, os.path.join(install_location, *relative.split("/")))
        return tuple(candidates)

    def _official_codex_entry(self, *, refresh: bool = False) -> str | None:
        cache_key = (os.path.normcase(os.path.abspath(self.base_path)), "official-chatgpt-codex")
        if not refresh:
            cached = _EXTERNAL_ENTRY_CACHE.get(cache_key)
            if cached is not None:
                created_at, entry_path = cached
                if entry_path and os.path.isfile(entry_path):
                    return entry_path
                if not entry_path and time.monotonic() - created_at <= EXTERNAL_ENTRY_CACHE_TTL_SECONDS:
                    return None
        for candidate in self._codex_desktop_appx_entry_candidates():
            if os.path.isfile(candidate):
                _EXTERNAL_ENTRY_CACHE[cache_key] = (time.monotonic(), candidate)
                return candidate
        _EXTERNAL_ENTRY_CACHE[cache_key] = (time.monotonic(), None)
        return None

    def _codex_desktop_appx_locations(self) -> tuple[str, ...]:
        package_names = ",".join(f"'{name}'" for name in CODEX_DESKTOP_PACKAGE_NAMES)
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                f"$names=@({package_names}); Get-AppxPackage | "
                "Where-Object { $names -contains $_.Name } | "
                "Sort-Object Version -Descending | Select-Object -ExpandProperty InstallLocation"
            ),
        ]
        try:
            result = self.installer_runner(command, self.base_path, APPX_PROBE_TIMEOUT_MS)
        except Exception:
            return ()
        if int(getattr(result, "returncode", 0) or 0) != 0:
            return ()
        locations: list[str] = []
        for line in str(getattr(result, "stdout", "") or "").splitlines():
            value = line.strip()
            if value:
                _append_unique(locations, self._expand_external_path(value))
        return tuple(locations)

    def _external_command_names(self, component: ReleaseComponent) -> tuple[str, ...]:
        names: list[str] = []
        for raw_path in getattr(component, "external_paths", ()):
            base_name = os.path.basename(raw_path.replace("\\", "/")).strip()
            if not base_name:
                continue
            self._append_command_name_variants(names, base_name)
        for command_name in KNOWN_COMPONENT_COMMANDS.get(component.component_id, ()):
            self._append_command_name_variants(names, command_name)
        for package_name in self._npm_package_names_from_command(component):
            for command_name in KNOWN_NPM_PACKAGE_COMMANDS.get(package_name, ()):
                self._append_command_name_variants(names, command_name)
        return tuple(names)

    def _append_external_path_variants(self, candidates: list[str], path: str) -> None:
        _append_unique(candidates, path)
        directory = os.path.dirname(path)
        filename = os.path.basename(path)
        stem, _ext = os.path.splitext(filename)
        if not directory or not stem:
            return
        for name in self._command_file_names(stem):
            _append_unique(candidates, os.path.join(directory, name))

    def _append_command_name_variants(self, names: list[str], name: str) -> None:
        for candidate in self._command_file_names(name):
            _append_unique(names, candidate)

    def _command_file_names(self, name: str) -> tuple[str, ...]:
        clean = str(name or "").strip()
        if not clean:
            return ()
        stem, ext = os.path.splitext(clean)
        base = stem or clean
        names: list[str] = []
        _append_unique(names, clean)
        if base and base != clean:
            _append_unique(names, base)
        if base:
            for suffix in WINDOWS_COMMAND_SUFFIXES:
                _append_unique(names, f"{base}{suffix}")
        return tuple(names)

    def _default_external_entry_candidates(self, command_names: tuple[str, ...]) -> tuple[str, ...]:
        stems = self._command_stems(command_names)
        if not stems:
            return ()
        directories = self._common_command_directories()
        candidates: list[str] = []
        for directory in directories:
            for stem in stems:
                for name in self._command_file_names(stem):
                    _append_unique(candidates, os.path.join(directory, name))
        return tuple(candidates)

    def _command_stems(self, command_names: tuple[str, ...]) -> tuple[str, ...]:
        stems: list[str] = []
        for name in command_names:
            base = os.path.basename(str(name or "").replace("\\", "/")).strip()
            if not base:
                continue
            stem, _ext = os.path.splitext(base)
            _append_unique(stems, stem or base)
        return tuple(stems)

    def _common_command_directories(self) -> tuple[str, ...]:
        directories: list[str] = []
        private_prefix = self._npm_private_prefix()
        _append_unique(directories, private_prefix)
        _append_unique(directories, os.path.join(private_prefix, "bin"))
        appdata = os.environ.get("APPDATA", "").strip()
        localappdata = os.environ.get("LOCALAPPDATA", "").strip()
        userprofile = os.environ.get("USERPROFILE", "").strip() or os.path.expanduser("~")
        program_files = os.environ.get("ProgramFiles", "").strip()
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "").strip()

        for root, suffixes in (
            (appdata, ("npm",)),
            (localappdata, ("pnpm", "npm")),
            (userprofile, (".local/bin", "scoop/shims", "AppData/Roaming/npm", "AppData/Local/pnpm")),
            (program_files, ("nodejs",)),
            (program_files_x86, ("nodejs",)),
        ):
            if not root:
                continue
            for suffix in suffixes:
                _append_unique(directories, os.path.abspath(os.path.join(root, *suffix.split("/"))))
        return tuple(directories)

    def _npm_global_bin_dirs(self) -> tuple[str, ...]:
        directories: list[str] = []
        private_prefix = self._npm_private_prefix()
        _append_unique(directories, private_prefix)
        _append_unique(directories, os.path.join(private_prefix, "bin"))
        for command in (("npm", "prefix", "-g"),):
            try:
                result = self.installer_runner(self._resolve_command(list(command)), self.base_path, NPM_PROBE_TIMEOUT_MS)
            except Exception:
                continue
            if int(getattr(result, "returncode", 0) or 0) != 0:
                continue
            for line in str(getattr(result, "stdout", "") or "").splitlines():
                value = line.strip()
                if not value or value.lower().startswith("unknown command"):
                    continue
                _append_unique(directories, self._expand_external_path(value))
                _append_unique(directories, os.path.join(self._expand_external_path(value), "bin"))
        return tuple(directories)

    def _npm_package_names_from_command(self, component: ReleaseComponent) -> tuple[str, ...]:
        command = tuple(getattr(component, "install_command", ()) or ())
        if len(command) < 3:
            return ()
        if os.path.basename(command[0]).lower() not in {"npm", "npm.cmd", "npm.ps1"}:
            return ()

        packages: list[str] = []
        saw_install = False
        skip_next = False
        options_with_value = {"--prefix", "--cache", "--registry", "--userconfig", "--globalconfig", "--tag"}
        for raw_part in command[1:]:
            part = str(raw_part or "").strip()
            if not part:
                continue
            lowered = part.lower()
            if skip_next:
                skip_next = False
                continue
            if not saw_install:
                if lowered in {"install", "i", "add"}:
                    saw_install = True
                continue
            if lowered in options_with_value:
                skip_next = True
                continue
            if lowered.startswith("-"):
                continue
            _append_unique(packages, _strip_npm_package_version(part))
        return tuple(packages)

    def _npm_package_bin_entry(self, package_name: str, command_names: tuple[str, ...]) -> str | None:
        root = self._npm_global_root()
        if not root:
            return None
        package_dir = os.path.join(root, *package_name.split("/"))
        package_json_path = os.path.join(package_dir, "package.json")
        if not os.path.isfile(package_json_path):
            return None
        try:
            import json

            with open(package_json_path, "r", encoding="utf-8-sig") as handle:
                package_json = json.load(handle)
        except Exception:
            return None
        bin_value = package_json.get("bin") if isinstance(package_json, dict) else None
        entries: list[str] = []
        if isinstance(bin_value, str):
            entries.append(bin_value)
        elif isinstance(bin_value, dict):
            preferred_stems = {os.path.splitext(name)[0].lower() for name in command_names}
            for key, value in bin_value.items():
                if not isinstance(value, str):
                    continue
                if not preferred_stems or str(key).lower() in preferred_stems:
                    entries.append(value)
            if not entries:
                entries.extend(value for value in bin_value.values() if isinstance(value, str))
        for relative in entries:
            candidate = os.path.abspath(os.path.join(package_dir, *relative.replace("\\", "/").split("/")))
            if _is_path_inside(candidate, package_dir) and os.path.isfile(candidate):
                return candidate
        return None

    def _npm_global_root(self) -> str:
        private_root = os.path.join(self._npm_private_prefix(), "node_modules")
        if os.path.isdir(private_root):
            return private_root
        try:
            result = self.installer_runner(
                self._resolve_command(["npm", "root", "-g"]),
                self.base_path,
                NPM_PROBE_TIMEOUT_MS,
            )
        except Exception:
            return ""
        if int(getattr(result, "returncode", 0) or 0) != 0:
            return ""
        for line in str(getattr(result, "stdout", "") or "").splitlines():
            value = line.strip()
            if value:
                return self._expand_external_path(value)
        return ""

    def _npm_private_prefix(self) -> str:
        return os.path.join(self.base_path, "data", ".installer", "npm-global")

    def _assert_external_install_available(self, component: ReleaseComponent, *, force_refresh: bool = False) -> None:
        if not getattr(component, "external_paths", ()):
            return
        if self._first_existing_external_entry(component, refresh=force_refresh):
            return
        raise ComponentInstallError("静默安装已执行，但未检测到组件入口，请打开诊断或手动重试")

    def _expand_external_path(self, path: str) -> str:
        expanded = os.path.expandvars(os.path.expanduser(path))
        return os.path.abspath(expanded)

    def _default_launcher(self, executable: str, cwd: str) -> dict:
        return _default_launcher(executable, cwd, base_path=self.base_path)

    def _default_component_launcher(self, component: ReleaseComponent, executable: str, cwd: str) -> dict:
        return _default_launcher(executable, cwd, base_path=self.base_path, component_id=component.component_id)

    def _run_silent_installer(self, component: ReleaseComponent, install_path: str) -> None:
        entry_path = self._component_entry_path(component, install_path)
        command = [entry_path, *getattr(component, "installer_args", ())]
        result = self.installer_runner(
            command,
            install_path,
            int(getattr(component, "installer_timeout_ms", 900000) or 900000),
        )
        code = int(getattr(result, "returncode", 0) or 0)
        if code in (0, 3010):
            return
        output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
        if len(output) > 240:
            output = output[:240] + "..."
        raise ComponentInstallError(f"安装器返回 {code}：{output or '没有输出'}")

    def _run_uninstall_command(self, component: ReleaseComponent) -> None:
        command = [self._expand_command_part(part) for part in getattr(component, "uninstall_command", ())]
        if not command:
            return
        result = self.installer_runner(
            self._resolve_command(self._with_private_npm_prefix(command)),
            self.base_path,
            int(getattr(component, "command_timeout_ms", 900000) or 900000),
        )
        code = int(getattr(result, "returncode", 0) or 0)
        if code in (0, 3010):
            return
        output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
        if len(output) > 240:
            output = output[:240] + "..."
        raise ComponentInstallError(f"卸载命令返回 {code}：{output or '没有输出'}")

    def _run_install_command(
        self,
        component: ReleaseComponent,
        install_path: str,
        *,
        package_path: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        command = [self._expand_command_part(part) for part in getattr(component, "install_command", ())]
        if not command:
            return
        if component.component_id == "openclaw-companion" and package_path and os.path.isfile(package_path):
            command = [command[0], "install", "-g", os.path.abspath(package_path)]
        timeout_ms = int(getattr(component, "command_timeout_ms", 900000) or 900000)
        resolved = self._resolve_command(self._with_private_npm_prefix(command))
        last_error = ""
        for attempt_index, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
            if delay > 0:
                self.retry_sleep(delay)
            result = self.installer_runner(resolved, install_path, timeout_ms)
            code = int(getattr(result, "returncode", 0) or 0)
            if code in (0, 3010):
                return
            output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
            last_error = f"安装命令返回 {code}：{_short_error(output)}"
            is_last_attempt = attempt_index >= len(RETRY_DELAYS_SECONDS)
            if not is_last_attempt and on_progress:
                on_progress(f"安装命令失败，正在重试第 {attempt_index + 1} 次：{_short_error(output)}", "warning")
        raise ComponentInstallError(last_error or "安装命令失败")

    def _with_private_npm_prefix(self, command: list[str]) -> list[str]:
        if not command:
            return command
        executable = os.path.basename(command[0]).lower()
        if executable not in {"npm", "npm.cmd", "npm.ps1"}:
            return command
        lowered = [part.lower() for part in command[1:]]
        if not any(part in {"install", "i", "add", "uninstall", "remove", "rm"} for part in lowered):
            return command
        if "--prefix" in lowered:
            return command
        prefix = self._npm_private_prefix()
        os.makedirs(prefix, exist_ok=True)
        return [command[0], "--prefix", prefix, *command[1:]]

    def _detect_installed_version(
        self,
        component: ReleaseComponent,
        install_path: str,
        entry_path: str | None = None,
    ) -> str | None:
        try:
            entry_path = entry_path or self._resolve_component_entry(component, install_path)
            managed_codex_version = self._managed_codex_metadata_version(component, install_path, entry_path)
            if managed_codex_version:
                return managed_codex_version
            if component.component_id == "codex-desktop" and _is_codex_desktop_executable(entry_path):
                return _codex_desktop_version_from_path(entry_path)
            cwd = self._component_cwd(install_path)
            command = [*build_launcher_command(entry_path, cwd, base_path=self.base_path), "--version"]
            result = self.installer_runner(command, cwd, VERSION_DETECT_TIMEOUT_MS)
        except Exception:
            return None
        if int(getattr(result, "returncode", 0) or 0) != 0:
            return None
        output = ((getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")).strip()
        if not output:
            return None
        match = re.search(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)\b", output, re.IGNORECASE)
        return match.group(1) if match else None

    def _managed_codex_metadata_version(
        self,
        component: ReleaseComponent,
        install_path: str,
        entry_path: str,
    ) -> str | None:
        if component.component_id != "codex-desktop":
            return None
        managed_entry = self._managed_codex_entry(install_path)
        if not managed_entry:
            return None
        if os.path.normcase(os.path.abspath(entry_path)) != os.path.normcase(os.path.abspath(managed_entry)):
            return None
        for resolver in (
            self._managed_codex_version_from_package_json,
            self._managed_codex_version_from_vendor_metadata,
        ):
            version = resolver(install_path, managed_entry)
            if version:
                return version
        return None

    def _managed_codex_version_from_package_json(self, install_path: str, managed_entry: str) -> str | None:
        package_dir = self._safe_join(install_path, "package")
        package_json_path = self._safe_join(package_dir, "package.json")
        package_json = self._read_json_dict(package_json_path)
        if not package_json:
            return None
        if str(package_json.get("name") or "").strip() != "@openai/codex":
            return None
        if not self._json_list_contains(package_json.get("os"), "win32"):
            return None
        if not self._json_list_contains(package_json.get("cpu"), "x64"):
            return None
        files_value = package_json.get("files")
        if isinstance(files_value, list) and "vendor" not in {str(value).strip() for value in files_value}:
            return None
        vendor_dir = os.path.dirname(os.path.dirname(os.path.dirname(managed_entry)))
        if not _is_path_inside(vendor_dir, package_dir):
            return None
        return _normalize_version_core(str(package_json.get("version") or ""))

    def _managed_codex_version_from_vendor_metadata(self, install_path: str, managed_entry: str) -> str | None:
        vendor_dir = os.path.dirname(os.path.dirname(managed_entry))
        metadata_path = self._safe_join(vendor_dir, "codex-package.json")
        metadata = self._read_json_dict(metadata_path)
        if not metadata:
            return None
        if str(metadata.get("variant") or "").strip() != "codex":
            return None
        if str(metadata.get("target") or "").strip() != "x86_64-pc-windows-msvc":
            return None
        entrypoint = str(metadata.get("entrypoint") or "").strip()
        if not entrypoint:
            return None
        try:
            metadata_entry = self._safe_join(vendor_dir, entrypoint)
        except ComponentInstallError:
            return None
        if os.path.normcase(os.path.abspath(metadata_entry)) != os.path.normcase(os.path.abspath(managed_entry)):
            return None
        return _normalize_version_core(str(metadata.get("version") or ""))

    def _read_json_dict(self, path: str) -> dict[str, object] | None:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                value = json.load(handle)
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _json_list_contains(self, value: object, expected: str) -> bool:
        if value is None:
            return True
        if not isinstance(value, list):
            return False
        normalized_expected = expected.strip().lower()
        return any(str(item).strip().lower() == normalized_expected for item in value)

    def _resolve_command(self, command: list[str]) -> list[str]:
        if not command:
            return command
        executable = os.path.basename(command[0]).lower()
        app_paths = AppPaths(self.base_path)
        if executable in {"node", "node.exe"}:
            node = app_paths.node_exe if os.path.isfile(app_paths.node_exe) else self._first_existing_tool(
                ("node.exe", "node"),
                extra_dirs=("node", "node-runtime", "SystemData/.core/node", "_up_/node", "_up_/node-runtime"),
            )
            if node:
                return [node, *command[1:]]
        if executable in {"npm", "npm.cmd", "npm.ps1"}:
            node = app_paths.node_exe if os.path.isfile(app_paths.node_exe) else self._first_existing_tool(
                ("node.exe", "node"),
                extra_dirs=("node", "node-runtime", "SystemData/.core/node", "_up_/node", "_up_/node-runtime"),
            )
            npm_cli = app_paths.npm_cli if os.path.isfile(app_paths.npm_cli) else self._first_existing_path(
                (
                    "node/node_modules/npm/bin/npm-cli.js",
                    "node-runtime/node_modules/npm/bin/npm-cli.js",
                    "node_modules/npm/bin/npm-cli.js",
                    "SystemData/.core/node/node_modules/npm/bin/npm-cli.js",
                    "SystemData/.core/node_modules/npm/bin/npm-cli.js",
                    "_up_/node/node_modules/npm/bin/npm-cli.js",
                    "_up_/node-runtime/node_modules/npm/bin/npm-cli.js",
                )
            )
            if node and npm_cli:
                return [node, npm_cli, *command[1:]]
            npm_shim = self._first_existing_tool(
                ("npm.cmd", "npm.exe", "npm"),
                extra_dirs=("node", "node-runtime", "SystemData/.core/node", "_up_/node", "_up_/node-runtime"),
            )
            if npm_shim:
                return [*build_launcher_command(npm_shim, self.base_path, base_path=self.base_path), *command[1:]]
        if executable in {"python", "python.exe", "py"}:
            python = app_paths.python_exe if os.path.isfile(app_paths.python_exe) else self._first_existing_tool(
                ("python.exe", "python"),
                extra_dirs=(
                    "python",
                    "python-runtime",
                    "runtime/python",
                    "SystemData/.core/python",
                    "_up_/python-runtime",
                ),
            )
            if python:
                return [python, *command[1:]]
        if executable in {"git", "git.exe"}:
            git = self._first_existing_path(
                (
                    "Git/cmd/git.exe",
                    "git/cmd/git.exe",
                    "SystemData/.core/Git/cmd/git.exe",
                    "SystemData/.core/git/cmd/git.exe",
                )
            )
            if git:
                return [git, *command[1:]]
        return command

    def _first_existing_tool(self, names: tuple[str, ...], *, extra_dirs: tuple[str, ...]) -> str:
        for directory in extra_dirs:
            for name in names:
                path = os.path.join(self.base_path, *directory.replace("\\", "/").split("/"), name)
                if os.path.isfile(path):
                    return path
        for name in names:
            path = shutil.which(name)
            if path:
                return path
        return ""

    def _first_existing_path(self, relatives: tuple[str, ...]) -> str:
        for relative in relatives:
            path = os.path.join(self.base_path, *relative.replace("\\", "/").split("/"))
            if os.path.isfile(path):
                return path
        return ""

    def _expand_command_part(self, value: str) -> str:
        return os.path.expandvars(os.path.expanduser(value))

    def _component_cwd(self, install_path: str) -> str:
        return install_path if os.path.isdir(install_path) else self.base_path

    def _swap(
        self,
        component: ReleaseComponent,
        staging_path: str,
        install_path: str,
        *,
        previous_version: str | None,
    ) -> PreviousInstall | None:
        previous = None
        if os.path.exists(install_path):
            previous = PreviousInstall(path=self._rollback_path(component.component_id), version=previous_version)
            self._remove_path(previous.path)
            os.makedirs(os.path.dirname(previous.path), exist_ok=True)
            self._replace_path(install_path, previous.path)

        os.makedirs(os.path.dirname(install_path), exist_ok=True)
        self._replace_path(staging_path, install_path)
        return previous

    def _replace_path(self, source: str, target: str) -> None:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not os.path.isdir(source):
                raise
            self._remove_path(target)
            shutil.copytree(source, target)
            self._remove_path(source)

    def _restore_previous_after_failed_health(self, install_path: str, previous: PreviousInstall | None) -> None:
        self._remove_path(install_path)
        if previous is None or not os.path.exists(previous.path):
            return
        os.makedirs(os.path.dirname(install_path), exist_ok=True)
        if os.path.isdir(previous.path):
            shutil.copytree(previous.path, install_path)
            return
        shutil.copy2(previous.path, install_path)

    def _safe_install_path(self, install_path: str) -> str:
        normalized = self._normalize_install_path(install_path)
        target = os.path.abspath(os.path.join(self.base_path, normalized))
        if not _is_path_inside(target, self.base_path):
            raise ComponentInstallError("install path escapes base directory")
        return target

    def _normalize_install_path(self, install_path: str) -> str:
        normalized = install_path.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        payload_root = os.path.basename(self.base_path).lower()
        legacy_root = parts[0].lower() if parts else ""
        if parts and legacy_root == payload_root and legacy_root in ("loomfiles", "openclawfiles"):
            parts = parts[1:]
        return os.path.join(*parts) if parts else ""

    def _component_staging_path(self, component: ReleaseComponent) -> str:
        return os.path.join(self.staging_dir, component.component_id)

    def _rollback_path(self, component_id: str) -> str:
        return os.path.join(self.rollback_dir, component_id)

    def _find_active_component_path(self, component_id: str) -> str | None:
        candidates = [
            os.path.join(self.base_path, "agents", component_id),
            os.path.join(self.base_path, component_id),
            os.path.join(self.base_path, "LOOMFiles", "agents", component_id),
            os.path.join(self.base_path, "LOOMFiles", component_id),
            os.path.join(self.base_path, "OpenClawFiles", "agents", component_id),
            os.path.join(self.base_path, "OpenClawFiles", component_id),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[0]

    def _safe_join(self, root: str, name: str) -> str:
        normalized = name.replace("\\", "/")
        if normalized.startswith("/") or any(part == ".." for part in normalized.split("/")):
            raise ComponentInstallError("archive path traversal is not allowed")
        target = os.path.abspath(os.path.join(root, *[part for part in normalized.split("/") if part]))
        if not _is_path_inside(target, root):
            raise ComponentInstallError("archive path traversal is not allowed")
        return target

    @staticmethod
    def _remove_path(path: str) -> None:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.unlink(path)


def _default_fetcher(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "LOOM-Launcher/component-installer"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _default_stream_fetcher(
    url: str,
    timeout: float,
    target_path: str,
    offset: int,
    on_progress: StreamFetcherProgress | None,
) -> None:
    headers = {"User-Agent": "LOOM-Launcher/component-installer"}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200) or 200)
        content_length = _header_int(getattr(response, "headers", {}), "Content-Length")
        total_bytes = _response_total_bytes(getattr(response, "headers", {}), status, offset, content_length)
        current_bytes = offset
        file_mode = "ab"
        if offset > 0 and status != 206:
            current_bytes = 0
            file_mode = "wb"
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if on_progress:
            on_progress("已连接")
        last_percent = -DOWNLOAD_PROGRESS_PERCENT_STEP
        last_report_at = time.monotonic()
        with open(target_path, file_mode) as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                current_bytes += len(chunk)
                if not on_progress:
                    continue
                now = time.monotonic()
                should_report = now - last_report_at >= DOWNLOAD_PROGRESS_INTERVAL_SECONDS
                if total_bytes:
                    percent = min(100, int((current_bytes * 100) / total_bytes))
                    should_report = should_report or percent >= last_percent + DOWNLOAD_PROGRESS_PERCENT_STEP or percent >= 100
                    if should_report:
                        last_percent = percent
                        last_report_at = now
                        on_progress(
                            f"{percent}%，{_format_megabytes(current_bytes)} / {_format_megabytes(total_bytes)}"
                        )
                elif should_report:
                    last_report_at = now
                    on_progress(f"{_format_megabytes(current_bytes)}")
        if on_progress and total_bytes:
            on_progress(f"100%，{_format_megabytes(current_bytes)} / {_format_megabytes(total_bytes)}")


def _default_health_checker(component: ReleaseComponent, _install_path: str) -> None:
    health_check = component.health_check
    if health_check is None:
        return
    if health_check.kind != "http":
        raise ComponentInstallError(f"unsupported health check kind: {health_check.kind}")
    timeout = max(0.1, health_check.timeout_ms / 1000)
    request = Request(health_check.url, headers={"User-Agent": "LOOM-Launcher/component-health"})
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status < 200 or status >= 300:
            raise ComponentInstallError(f"health check returned HTTP {status}")


def _hermes_source_roots(install_path: str, entry_path: str = "") -> tuple[str, ...]:
    roots: list[str] = []
    for candidate in (install_path, entry_path):
        current = os.path.abspath(candidate) if candidate else ""
        if not current:
            continue
        if os.path.isfile(current):
            current = os.path.dirname(current)
        for _ in range(6):
            if not current or current == os.path.dirname(current):
                break
            if os.path.isdir(os.path.join(current, "hermes_cli")) or os.path.isfile(os.path.join(current, "utils.py")):
                _append_unique(roots, current)
            current = os.path.dirname(current)
    return tuple(roots)


def _first_python_conflict_marker(root: str) -> str:
    if not root or not os.path.isdir(root):
        return ""
    ignored_dirs = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "Lib",
        "Scripts",
        "bin",
        "Include",
        "site-packages",
        "node_modules",
    }
    checked = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ignored_dirs and not name.endswith(".dist-info")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            checked += 1
            if checked > 1000:
                return ""
            path = os.path.join(dirpath, filename)
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    for line in handle:
                        if _is_python_conflict_marker(line):
                            return path
            except UnicodeDecodeError:
                try:
                    with open(path, "r", encoding="gb18030") as handle:
                        for line in handle:
                            if _is_python_conflict_marker(line):
                                return path
                except Exception:
                    continue
            except OSError:
                continue
    return ""


def _is_python_conflict_marker(line: str) -> bool:
    stripped = line.strip()
    return any(
        stripped == marker
        or (stripped.startswith(marker) and stripped[len(marker) : len(marker) + 1].isspace())
        for marker in PYTHON_SOURCE_CONFLICT_BOUNDARIES
    )


def _default_installer_runner(command: list[str], cwd: str, timeout_ms: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=max(1, timeout_ms / 1000),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _is_codex_desktop_executable(executable: str) -> bool:
    path = os.path.abspath(str(executable or ""))
    filename = os.path.basename(path)
    if filename.lower() not in {"codex.exe", "chatgpt.exe"}:
        return False
    lowered_parts = {part.lower() for part in path.replace("\\", "/").split("/")}
    return not lowered_parts.intersection({"resources", "node_modules", "vendor", "bin", "npm"})


def _codex_desktop_version_from_path(executable: str) -> str | None:
    match = re.search(r"OpenAI\.(?:Codex|ChatGPT)_(\d+(?:\.\d+){1,3})_", str(executable or ""), re.IGNORECASE)
    return match.group(1) if match else None


def _codex_desktop_app_uri(executable: str) -> str | None:
    match = re.search(
        r"WindowsApps[\\/](OpenAI\.(?:Codex|ChatGPT))_[^\\/]+__([0-9a-z]+)[\\/]",
        str(executable or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    package_family = f"{match.group(1)}_{match.group(2)}"
    return f"shell:AppsFolder\\{package_family}!{CODEX_DESKTOP_APP_ID}"


def build_launcher_command(executable: str, cwd: str, *, base_path: str | None = None) -> list[str]:
    extension = os.path.splitext(executable)[1].lower()
    if extension in {".js", ".mjs", ".cjs"}:
        node_candidates = []
        if base_path:
            app_paths = AppPaths(os.path.abspath(base_path))
            node_candidates.extend([
                app_paths.node_exe,
                os.path.join(base_path, "node", "node.exe"),
                os.path.join(base_path, "node-runtime", "node.exe"),
                os.path.join(base_path, "_up_", "node-runtime", "node.exe"),
                os.path.join(base_path, "_up_", "node", "node.exe"),
                os.path.join(base_path, "SystemData", ".core", "node", "node.exe"),
                os.path.join(base_path, "runtime", "node", "node.exe"),
            ])
        node_from_path = shutil.which("node")
        if node_from_path:
            node_candidates.append(node_from_path)
        node = next((candidate for candidate in node_candidates if os.path.isfile(candidate)), "")
        if not node:
            raise ComponentInstallError("未找到 Node.js，无法启动 JavaScript 组件")
        return [node, executable]
    if extension == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", executable]
    if extension in {".cmd", ".bat"}:
        return ["cmd", "/c", executable]
    return [executable]


def build_agent_launcher_command(
    component_id: str | None,
    executable: str,
    cwd: str,
    *,
    base_path: str | None = None,
) -> list[str]:
    if component_id == "codex-desktop" and _is_codex_desktop_executable(executable):
        app_uri = _codex_desktop_app_uri(executable)
        if app_uri and os.name == "nt":
            return ["explorer.exe", app_uri]
        return [executable]

    command = build_launcher_command(executable, cwd, base_path=base_path)
    if component_id == "opencode":
        model = _require_opencode_default_model(base_path)
        return [*command, "--pure", "-m", model]
    if component_id == "openclaw-companion":
        return [*command, "chat", "--local"]
    if component_id == "hermes":
        return [*command, "chat"]
    return command


def build_visible_launcher_command(
    executable: str,
    cwd: str,
    *,
    base_path: str | None = None,
    component_id: str | None = None,
    force_windows: bool | None = None,
) -> list[str]:
    command = build_agent_launcher_command(component_id, executable, cwd, base_path=base_path)
    use_windows_terminal = os.name == "nt" if force_windows is None else force_windows
    if component_id == "codex-desktop" and _is_codex_desktop_executable(executable):
        return command
    if not use_windows_terminal:
        return command

    command_line = subprocess.list2cmdline(command)
    title = f"LOOM Agent - {_launcher_title(component_id, executable)}"
    shell_mode = "/c" if component_id == "codex-desktop" else "/k"
    return ["cmd.exe", shell_mode, f"title {title} && {command_line}"]


def _default_launcher(executable: str, cwd: str, *, base_path: str | None = None, component_id: str | None = None) -> dict:
    command = build_visible_launcher_command(executable, cwd, base_path=base_path, component_id=component_id)
    use_windows_terminal = os.name == "nt"
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if use_windows_terminal else 0
    env = build_agent_launcher_environment(base_path, component_id)
    stream_target = None if use_windows_terminal else subprocess.DEVNULL
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=stream_target,
        stderr=stream_target,
        stdin=stream_target,
        close_fds=True,
        creationflags=creationflags,
    )
    if component_id == "codex-desktop" and not _is_codex_desktop_executable(executable):
        time.sleep(CODEX_STARTUP_PROBE_SECONDS)
        return_code = process.poll()
        if return_code is not None:
            raise ComponentInstallError(f"Codex 启动后立即退出：exit={return_code}")
    return {"pid": process.pid, "visible": use_windows_terminal, "command": subprocess.list2cmdline(command)}


def _terminate_process_tree(pid: int) -> None:
    if int(pid or 0) <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return
    os.kill(pid, signal.SIGTERM)


def _stop_official_codex_desktop() -> None:
    if os.name != "nt":
        raise ComponentInstallError("OpenAI 官方 Codex 重启仅支持 Windows")
    script = """
$packageNames = @('OpenAI.Codex', 'OpenAI.ChatGPT')
$roots = @(
  foreach ($packageName in $packageNames) {
    Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue |
      ForEach-Object { $_.InstallLocation }
  }
) | Where-Object { $_ }
if ($roots.Count -eq 0) { exit 0 }
$targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $path = $_.ExecutablePath
  if (-not $path) { return $false }
  foreach ($root in $roots) {
    if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}
foreach ($target in $targets) {
  Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 150
$remaining = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $path = $_.ExecutablePath
  if (-not $path) { return $false }
  foreach ($root in $roots) {
    if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}
if ($remaining) { Write-Error 'OpenAI package processes are still running'; exit 1 }
""".strip()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "process stop failed").strip()
        raise ComponentInstallError(detail)


def _official_codex_desktop_running() -> bool:
    if os.name != "nt":
        return False
    script = """
$packageNames = @('OpenAI.Codex', 'OpenAI.ChatGPT')
$roots = @(
  foreach ($packageName in $packageNames) {
    Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue |
      ForEach-Object { $_.InstallLocation }
  }
) | Where-Object { $_ }
if ($roots.Count -eq 0) { Write-Output '0'; exit 0 }
$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $path = $_.ExecutablePath
  if (-not $path) { return $false }
  foreach ($root in $roots) {
    if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
} | Select-Object -First 1
if ($running) { Write-Output '1' } else { Write-Output '0' }
""".strip()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().splitlines()[-1:] == ["1"]


def build_agent_launcher_environment(base_path: str | None, component_id: str | None) -> dict[str, str] | None:
    if not base_path:
        return None
    root = os.path.abspath(base_path)
    runtime_paths = AppPaths(root)
    env = os.environ.copy()
    if component_id in MODEL_ENV_SCRUB_COMPONENTS:
        _scrub_agent_model_environment(env)
    path_entries = [
        os.path.dirname(runtime_paths.adb_exe) if runtime_paths.adb_exe else "",
        os.path.join(root, "data", ".installer", "npm-global"),
        os.path.join(root, "data", ".installer", "npm-global", "bin"),
        runtime_paths.node_dir,
        os.path.join(runtime_paths.node_dir, "node_modules", ".bin"),
        os.path.join(root, "node"),
        os.path.join(root, "_up_", "node"),
        os.path.join(root, "SystemData", ".core", "node"),
        os.path.join(root, "node_modules", ".bin"),
        os.path.join(root, "_up_", "node_modules", ".bin"),
        os.path.join(root, "SystemData", ".core", "node_modules", ".bin"),
    ]
    existing_path = env.get("Path") or env.get("PATH") or ""
    prefix = os.pathsep.join(entry for entry in path_entries if os.path.isdir(entry))
    if prefix:
        merged_path = prefix if not existing_path else f"{prefix}{os.pathsep}{existing_path}"
        env["PATH"] = merged_path
        env["Path"] = merged_path
    if runtime_paths.adb_exe:
        env["LOOM_ADB"] = runtime_paths.adb_exe

    if component_id == "openclaw-companion":
        data_dir = os.path.join(root, "data")
        state_dir = os.path.join(data_dir, ".openclaw")
        env["OPENCLAW_HOME"] = data_dir
        env["OPENCLAW_STATE_DIR"] = state_dir
        env["OPENCLAW_CONFIG_PATH"] = os.path.join(state_dir, "openclaw.json")
    elif component_id == "opencode":
        config_dir = os.path.join(root, "data", ".opencode")
        config_file = os.path.join(config_dir, "opencode.json")
        env["OPENCODE_CONFIG_DIR"] = config_dir
        env["OPENCODE_CONFIG"] = config_file
        api_key = _opencode_api_key_from_wire(root)
        if api_key:
            env["LOOM_OPENCODE_API_KEY"] = api_key
    elif component_id == "codex-desktop":
        wire = _agent_wire_from_root(root)
        _inject_openai_compatible_env(env, wire, key_name="LOOM_CODEX_API_KEY")
    elif component_id == "claude-code":
        wire = _agent_wire_from_root(root)
        api_key = _wire_api_key(wire)
        base_url = _wire_anthropic_base_url(wire)
        model = _wire_text_model(wire)
        if api_key:
            env["LOOM_CLAUDE_API_KEY"] = api_key
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
            env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
        if model:
            env["ANTHROPIC_MODEL"] = model
    return env


def _ensure_managed_codex_global_guidance(codex_home: str) -> None:
    _ensure_guidance_in_directory(codex_home, "AGENTS.md", override_name="AGENTS.override.md")


def _ensure_component_language_guidance(
    base_path: str,
    component_id: str,
    *,
    include_user_home: bool,
) -> tuple[str, ...]:
    root = os.path.abspath(base_path)
    targets: list[tuple[str, str, str | None]] = []
    user_home = _user_home_directory()
    if component_id == "codex-desktop":
        targets.append((os.path.join(root, "data", ".codex"), "AGENTS.md", "AGENTS.override.md"))
        if include_user_home:
            configured_home = str(os.environ.get("CODEX_HOME") or "").strip()
            if configured_home:
                targets.append((configured_home, "AGENTS.md", "AGENTS.override.md"))
            if user_home:
                targets.append((os.path.join(user_home, ".codex"), "AGENTS.md", "AGENTS.override.md"))
    elif component_id == "claude-code" and include_user_home and user_home:
        targets.append((os.path.join(user_home, ".claude"), "CLAUDE.md", None))
    elif component_id == "openclaw-companion":
        targets.append((os.path.join(root, "data", ".openclaw", "workspace"), "AGENTS.md", None))
    else:
        return ()

    written: list[str] = []
    seen: set[str] = set()
    for directory, default_name, override_name in targets:
        normalized = os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(directory))))
        if normalized in seen:
            continue
        seen.add(normalized)
        written.append(_ensure_guidance_in_directory(normalized, default_name, override_name=override_name))
    return tuple(written)


def _user_home_directory() -> str:
    candidate = str(os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~") or "").strip()
    if not candidate or candidate == "~":
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(candidate)))


def _ensure_guidance_in_directory(directory: str, default_name: str, *, override_name: str | None) -> str:
    os.makedirs(directory, exist_ok=True)
    override_path = os.path.join(directory, override_name) if override_name else ""
    path = override_path if override_path and os.path.isfile(override_path) else os.path.join(directory, default_name)
    _upsert_managed_markdown_block(path, LOOM_DEFAULT_LANGUAGE_GUIDANCE)
    return path


def _upsert_managed_markdown_block(path: str, content: str) -> None:
    managed_block = f"{LOOM_GUIDANCE_START}\n{content.strip()}\n{LOOM_GUIDANCE_END}"
    with _GUIDANCE_WRITE_LOCK:
        existing = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    existing = handle.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="gb18030") as handle:
                    existing = handle.read()
        start = existing.find(LOOM_GUIDANCE_START)
        end = existing.find(LOOM_GUIDANCE_END, start + len(LOOM_GUIDANCE_START)) if start >= 0 else -1
        if start >= 0 and end >= 0:
            end += len(LOOM_GUIDANCE_END)
            updated = f"{existing[:start]}{managed_block}{existing[end:]}"
        elif start >= 0:
            updated = f"{existing[:start].rstrip()}\n\n{managed_block}\n"
        else:
            prefix = existing.rstrip()
            updated = f"{prefix}\n\n{managed_block}\n" if prefix else f"{managed_block}\n"
        if updated == existing:
            return
        directory = os.path.dirname(path) or "."
        fd, temporary = tempfile.mkstemp(prefix=".loom-guidance-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)


def _scrub_agent_model_environment(env: dict[str, str]) -> None:
    stale_keys = {key.upper() for key in AGENT_MODEL_ENV_KEYS}
    for key in list(env):
        if key.upper() in stale_keys:
            env.pop(key, None)


def _require_opencode_default_model(base_path: str | None) -> str:
    if not base_path:
        raise ComponentInstallError("opencode 缺少 LOOM 安装根目录，无法加载模型配置")
    config_path = os.path.join(os.path.abspath(base_path), "data", ".opencode", "opencode.json")
    if not os.path.isfile(config_path):
        raise ComponentInstallError("opencode 模型配置缺失，请先登录模型账号并同步模型")
    try:
        with open(config_path, encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except Exception as exc:
        raise ComponentInstallError(f"opencode 模型配置无法读取：{exc}") from exc
    model = str(config.get("model") or "").strip() if isinstance(config, dict) else ""
    if "/" not in model:
        raise ComponentInstallError("opencode 默认模型缺失，请先在模型账号页同步模型")
    provider_id = model.split("/", 1)[0]
    model_id = model.split("/", 1)[1]
    if _looks_like_non_text_model(model_id):
        raise ComponentInstallError("opencode 默认模型不能使用手机/图像/视频模型，请重新同步文本模型")
    providers = config.get("provider") if isinstance(config, dict) else {}
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ComponentInstallError(f"opencode Provider {provider_id} 缺失，请重新同步模型")
    return model


def _opencode_api_key_from_wire(base_path: str) -> str:
    wire = _agent_wire_from_root(os.path.abspath(base_path))
    return _wire_api_key(wire)


def _agent_wire_from_root(root: str) -> dict:
    wire_path = os.path.join(os.path.abspath(root), "data", ".openclaw", "launcher", "wire-current.json")
    try:
        with open(wire_path, encoding="utf-8-sig") as handle:
            wire = json.load(handle)
    except Exception:
        return {}
    return wire if isinstance(wire, dict) else {}


def _wire_api_key(wire: dict) -> str:
    if not isinstance(wire, dict):
        return ""
    return unprotect_secret(wire.get("apiKey"))


def _wire_base_url(wire: dict) -> str:
    if not isinstance(wire, dict):
        return ""
    value = str(wire.get("baseUrl") or "").strip().rstrip("/")
    return value


def _wire_anthropic_base_url(wire: dict) -> str:
    value = _wire_base_url(wire)
    if value.endswith("/v1"):
        return value[:-3].rstrip("/")
    return value


def _wire_text_model(wire: dict) -> str:
    models = wire.get("models") if isinstance(wire.get("models"), dict) else {}
    model = str(models.get("text") or "").strip()
    return "" if _looks_like_non_text_model(model) else model


def _looks_like_non_text_model(model_id: object) -> bool:
    text = str(model_id or "").strip().lower()
    if not text:
        return False
    if text in PHONE_MODEL_IDS:
        return True
    return any(marker in text for marker in NON_TEXT_MODEL_MARKERS)


def _inject_openai_compatible_env(env: dict[str, str], wire: dict, *, key_name: str) -> None:
    api_key = _wire_api_key(wire)
    base_url = _wire_base_url(wire)
    model = _wire_text_model(wire)
    if api_key:
        env[key_name] = api_key
        env["OPENAI_API_KEY"] = api_key
    if base_url:
        env["OPENAI_BASE_URL"] = base_url
        env["OPENAI_API_BASE"] = base_url
    if model:
        env["OPENAI_MODEL"] = model


def _launcher_title(component_id: str | None, executable: str) -> str:
    titles = {
        "codex-desktop": "Codex",
        "claude-code": "Claude Code",
        "opencode": "opencode",
        "openclaw-companion": "OpenClaw",
        "hermes": "Hermes",
    }
    return titles.get(str(component_id or ""), os.path.basename(executable) or "runtime")


def _is_path_inside(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
    except ValueError:
        return False
    return common == os.path.abspath(root)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _strip_npm_package_version(package: str) -> str:
    text = str(package or "").strip()
    if not text:
        return ""
    if text.startswith("@"):
        first = text.find("@", 1)
        return text[:first] if first > 0 else text
    return text.split("@", 1)[0]


def _short_error(error: object, *, limit: int = 160) -> str:
    text = str(error or "").strip()
    if not text:
        return "没有错误输出"
    return text if len(text) <= limit else text[:limit] + "..."


def _normalize_version_core(version: object) -> str | None:
    text = str(version or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})(?:[-+][0-9A-Za-z.-]+)?", text, re.IGNORECASE)
    return match.group(1) if match else None


def _versions_match(expected: str | None, detected: str | None) -> bool:
    expected_text = str(expected or "").strip().lower()
    detected_text = str(detected or "").strip().lower()
    if not expected_text or not detected_text:
        return True
    return expected_text == detected_text or expected_text.startswith(f"{detected_text}-") or detected_text.startswith(f"{expected_text}-")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _header_int(headers: object, name: str) -> int | None:
    value = ""
    if hasattr(headers, "get"):
        value = str(headers.get(name, "") or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _response_total_bytes(headers: object, status: int, offset: int, content_length: int | None) -> int | None:
    if status == 206:
        content_range = ""
        if hasattr(headers, "get"):
            content_range = str(headers.get("Content-Range", "") or "").strip()
        match = re.search(r"/(\d+)$", content_range)
        if match:
            return int(match.group(1))
        if content_length is not None:
            return offset + content_length
        return None
    return content_length


def _format_megabytes(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"
