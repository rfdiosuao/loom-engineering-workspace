"""Verified, resumable LOOM desktop application update support."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from core.paths import AppPaths


DEFAULT_RELEASE_API_URLS = (
    "https://gitee.com/api/v5/repos/rfdiosuao/lumi/releases/latest",
    "https://api.github.com/repos/rfdiosuao/lumi/releases/latest",
)
SETUP_NAME_RE = re.compile(r"^LOOM-(?P<version>\d+\.\d+\.\d+)-setup\.exe$", re.IGNORECASE)
SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


@dataclass(frozen=True)
class LoomRelease:
    version: str
    filename: str
    url: str
    size: int
    sha256: str
    source: str
    notes: str = ""
    published_at: str = ""
    release_url: str = ""


class UpdateCancelled(Exception):
    """Raised after the user asks the resumable downloader to stop."""


@dataclass(frozen=True)
class UpdateFailure:
    error_code: str
    message: str
    retryable: bool
    remediation: tuple[str, ...]


def _classify_update_failure(error: Exception) -> UpdateFailure:
    raw = str(error or "").strip()
    lowered = raw.casefold()
    error_number = getattr(error, "errno", None)
    win_error = getattr(error, "winerror", None)

    if isinstance(error, urllib.error.HTTPError):
        status_code = int(getattr(error, "code", 0) or 0)
        if status_code in {408, 429} or status_code >= 500:
            return UpdateFailure(
                "network_interrupted",
                f"更新服务器暂时不可用（HTTP {status_code}），已保留下载进度。",
                True,
                ("稍后重试，LOOM 会继续使用已下载的有效内容。",),
            )
        return UpdateFailure(
            "release_http_error",
            f"更新服务器拒绝了下载请求（HTTP {status_code or '未知'}）。",
            False,
            ("请重新检查更新；若持续出现，请联系发布管理员检查下载权限。",),
        )

    if win_error in {32, 33} or any(
        marker in lowered
        for marker in ("used by another process", "being used by another process", "sharing violation", "文件被占用")
    ):
        return UpdateFailure(
            "file_locked",
            "更新文件正被其他程序占用，已保留下载进度。",
            True,
            ("关闭其他 LOOM、安装器或正在扫描该文件的安全软件后重试。",),
        )
    if error_number == errno.ENOSPC or win_error == 112 or "no space left" in lowered:
        return UpdateFailure(
            "disk_full",
            "磁盘空间不足，更新未安装，当前版本保持不变。",
            False,
            ("释放系统盘和更新缓存所在磁盘的空间后重新更新。",),
        )
    if isinstance(error, PermissionError) or error_number in {errno.EACCES, errno.EPERM} or win_error == 5:
        return UpdateFailure(
            "permission_denied",
            "没有权限写入更新缓存，更新未安装，当前版本保持不变。",
            False,
            ("确认当前账户可写入 LOOM 更新目录，并检查安全软件是否拦截。",),
        )
    if isinstance(error, (ConnectionError, TimeoutError, urllib.error.URLError)) or any(
        marker in lowered
        for marker in ("connection reset", "connection aborted", "timed out", "network is unreachable")
    ):
        return UpdateFailure(
            "network_interrupted",
            "网络连接中断，已保留下载进度。",
            True,
            ("网络恢复后点击重试，LOOM 会从已下载的位置继续。",),
        )
    if "windows 签名验证失败" in lowered:
        return UpdateFailure(
            "signature_invalid",
            "更新包发布者签名无效，已拒绝安装。",
            False,
            ("请只使用 LOOM 官方发布的签名安装包。",),
        )
    if "sha256" in lowered or "安装包大小不一致" in lowered:
        return UpdateFailure(
            "integrity_failed",
            "更新包完整性校验失败，已拒绝安装。",
            True,
            ("请重新下载；若重复失败，请检查网络代理或安全软件。",),
        )
    return UpdateFailure(
        "update_failed",
        raw or "更新失败，当前版本保持不变。",
        True,
        ("请重试；若仍失败，请导出诊断日志。",),
    )


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(item) for item in match.groups())


def _safe_https_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("更新地址必须使用 HTTPS")
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("更新地址不能指向本机")
    return text


def _default_update_cache_dir() -> str:
    explicit = str(os.environ.get("LOOM_UPDATE_CACHE_DIR") or "").strip()
    if explicit:
        return os.path.abspath(explicit)
    root = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not root:
        root = tempfile.gettempdir()
    return os.path.join(root, "LOOM-Update-Recovery", "updates")


def _verify_windows_signature(path: str) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Windows Authenticode verification is unavailable on this platform"

    powershell = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    app_exe = str(os.environ.get("LOOM_APP_EXE") or "").strip()
    trusted_publisher = str(os.environ.get("LOOM_UPDATE_PUBLISHER") or "").strip()
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$candidate = Get-AuthenticodeSignature -LiteralPath $env:LOOM_UPDATE_SIGNATURE_PATH
$current = $null
if ($env:LOOM_CURRENT_SIGNED_EXE -and (Test-Path -LiteralPath $env:LOOM_CURRENT_SIGNED_EXE)) {
  $current = Get-AuthenticodeSignature -LiteralPath $env:LOOM_CURRENT_SIGNED_EXE
}
[pscustomobject]@{
  status = [string]$candidate.Status
  subject = if ($candidate.SignerCertificate) { [string]$candidate.SignerCertificate.Subject } else { '' }
  thumbprint = if ($candidate.SignerCertificate) { [string]$candidate.SignerCertificate.Thumbprint } else { '' }
  currentStatus = if ($current) { [string]$current.Status } else { '' }
  currentSubject = if ($current -and $current.SignerCertificate) { [string]$current.SignerCertificate.Subject } else { '' }
  currentThumbprint = if ($current -and $current.SignerCertificate) { [string]$current.SignerCertificate.Thumbprint } else { '' }
} | ConvertTo-Json -Compress
"""
    env = os.environ.copy()
    env["LOOM_UPDATE_SIGNATURE_PATH"] = os.path.abspath(path)
    env["LOOM_CURRENT_SIGNED_EXE"] = app_exe
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
            check=False,
        )
    except Exception as error:
        return False, f"签名验证执行失败: {error}"
    if result.returncode != 0:
        return False, f"签名验证执行失败: {result.stderr.strip() or result.stdout.strip()}"
    try:
        payload = json.loads(result.stdout.strip())
    except (TypeError, ValueError) as error:
        return False, f"签名验证结果无效: {error}"
    if str(payload.get("status") or "").lower() != "valid":
        return False, f"安装包签名状态不是 Valid: {payload.get('status') or 'Unknown'}"

    subject = str(payload.get("subject") or "").strip()
    thumbprint = str(payload.get("thumbprint") or "").strip().lower()
    if trusted_publisher:
        if trusted_publisher.lower() not in subject.lower():
            return False, f"安装包发布者不匹配: {subject or 'Unknown'}"
        return True, subject

    current_valid = str(payload.get("currentStatus") or "").lower() == "valid"
    current_thumbprint = str(payload.get("currentThumbprint") or "").strip().lower()
    current_subject = str(payload.get("currentSubject") or "").strip()
    if not current_valid or not current_thumbprint:
        return False, "无法从当前 LOOM 获取可信发布者；请配置 LOOM_UPDATE_PUBLISHER"
    if thumbprint != current_thumbprint and subject.casefold() != current_subject.casefold():
        return False, f"安装包发布者与当前 LOOM 不一致: {subject or 'Unknown'}"
    return True, subject


class LoomAppUpdater:
    def __init__(
        self,
        paths: AppPaths,
        *,
        current_version: str = "",
        release_api_urls: Iterable[str] = DEFAULT_RELEASE_API_URLS,
        opener: Callable[..., Any] = urllib.request.urlopen,
        launcher: Callable[[str], None] | None = None,
        signature_verifier: Callable[[str], tuple[bool, str]] = _verify_windows_signature,
        update_cache_dir: str | None = None,
    ) -> None:
        self.paths = paths
        self._current_version = str(current_version or os.environ.get("LOOM_APP_VERSION") or "0.0.0").strip()
        self.release_api_urls = tuple(str(url).strip() for url in release_api_urls if str(url).strip())
        self.opener = opener
        self.launcher = launcher or self._deferred_launcher
        self.signature_verifier = signature_verifier
        self.update_cache_dir = os.path.abspath(update_cache_dir or _default_update_cache_dir())
        self.cached_release: LoomRelease | None = None
        self.last_installer_path = ""
        self._status_lock = threading.Lock()
        self._install_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._status: dict[str, Any] = {
            "phase": "idle",
            "downloaded": 0,
            "total": 0,
            "percent": 0,
            "version": "",
            "message": "",
            "errorCode": "",
            "retryable": False,
            "remediation": [],
        }

    def current_version(self) -> str:
        return self._current_version

    def status(self) -> dict[str, Any]:
        with self._status_lock:
            return dict(self._status)

    def cancel_update(self) -> bool:
        phase = str(self.status().get("phase") or "")
        if not self._install_lock.locked() or phase not in {
            "checking",
            "downloading",
        }:
            return False
        self._cancel_event.set()
        return True

    def _pending_update_result_candidate(self) -> tuple[str, str, str, str] | None:
        recovery_root = os.path.abspath(os.path.dirname(self.update_cache_dir))
        backup_root = os.path.join(recovery_root, "upgrade-backups")
        candidates: list[tuple[int, str, str]] = []
        marker_statuses = {
            "update-success.json": "success",
            "update-failed.json": "failed",
            "update-failure.json": "failed",
            "recovery-failure.json": "failed",
        }
        search_roots = [recovery_root]
        if os.path.isdir(backup_root):
            search_roots.append(backup_root)
        for search_root in search_roots:
            if not os.path.isdir(search_root):
                continue
            for root, directories, filenames in os.walk(search_root):
                if root == recovery_root:
                    directories[:] = [item for item in directories if item != "upgrade-backups"]
                for filename in filenames:
                    status = marker_statuses.get(filename.lower())
                    if not status:
                        continue
                    path = os.path.abspath(os.path.join(root, filename))
                    if os.path.commonpath([recovery_root, path]) != recovery_root:
                        continue
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    candidates.append((stat.st_mtime_ns, path, status))
        if not candidates:
            return None

        modified_ns, marker_path, result_status = max(candidates, key=lambda item: item[0])
        try:
            marker_size = os.path.getsize(marker_path)
        except OSError:
            return None
        fingerprint = f"{marker_path}|{modified_ns}|{marker_size}"
        acknowledgement_path = os.path.join(recovery_root, "update-result-ack.json")
        try:
            with open(acknowledgement_path, "r", encoding="utf-8-sig") as handle:
                acknowledged = json.load(handle)
            if str(acknowledged.get("fingerprint") or "") == fingerprint:
                return None
        except (OSError, TypeError, ValueError):
            pass
        return fingerprint, marker_path, result_status, acknowledgement_path

    def has_pending_update_result(self) -> bool:
        return self._pending_update_result_candidate() is not None

    def consume_update_result(self) -> dict[str, Any] | None:
        candidate = self._pending_update_result_candidate()
        if candidate is None:
            return None
        fingerprint, marker_path, result_status, acknowledgement_path = candidate
        recovery_root = os.path.abspath(os.path.dirname(self.update_cache_dir))

        try:
            with open(marker_path, "r", encoding="utf-8-sig") as handle:
                marker = json.load(handle)
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(marker, dict):
            return None

        os.makedirs(recovery_root, exist_ok=True)
        temporary_ack = acknowledgement_path + ".tmp"
        with open(temporary_ack, "w", encoding="utf-8") as handle:
            json.dump({"fingerprint": fingerprint}, handle, ensure_ascii=True)
        os.replace(temporary_ack, acknowledgement_path)
        return {
            "status": result_status,
            "version": str(marker.get("version") or ""),
            "confirmedAt": str(marker.get("confirmedAt") or marker.get("failedAt") or ""),
            "message": str(marker.get("error") or marker.get("failure") or marker.get("message") or ""),
            "rollbackState": str(marker.get("rollbackState") or ""),
            "remediation": [
                str(item)
                for item in marker.get("remediation") or marker.get("recoveryActions") or []
            ],
        }

    def is_newer_version(self, version: str) -> bool:
        return _version_tuple(version) > _version_tuple(self.current_version())

    def _report(
        self,
        phase: str,
        *,
        downloaded: int = 0,
        total: int = 0,
        version: str = "",
        message: str = "",
        error_code: str = "",
        retryable: bool = False,
        remediation: Iterable[str] = (),
        callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        percent = int(downloaded * 100 / total) if total > 0 else 0
        state = {
            "phase": phase,
            "downloaded": max(0, int(downloaded)),
            "total": max(0, int(total)),
            "percent": max(0, min(100, percent)),
            "version": version,
            "message": message,
            "errorCode": error_code,
            "retryable": bool(retryable),
            "remediation": [str(item) for item in remediation if str(item).strip()],
        }
        with self._status_lock:
            self._status = state
        if callback:
            callback(dict(state))

    def _resolve_latest_release(self) -> tuple[LoomRelease | None, str | None]:
        errors: list[str] = []
        releases: list[LoomRelease] = []
        for source_url in self.release_api_urls:
            try:
                releases.append(self._fetch_release(source_url))
            except Exception as error:
                errors.append(f"{urlparse(source_url).hostname or 'release'}: {error}")
        if not releases:
            return None, "；".join(errors) or "没有可用的 LOOM 更新源"

        release = max(releases, key=lambda item: _version_tuple(item.version))
        return release, None

    def latest_version(self) -> tuple[str | None, str | None]:
        release, error = self.latest_release()
        if error or release is None:
            return None, error or "没有可用的 LOOM 更新源"
        self.cached_release = release
        if not self.is_newer_version(release.version):
            return self.current_version(), None
        return release.version, None

    def latest_release(self) -> tuple[LoomRelease | None, str | None]:
        release, error = self._resolve_latest_release()
        if release is not None:
            self.cached_release = release
        return release, error

    def install_latest(
        self,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[bool, str, list[str]]:
        if not self._install_lock.acquire(blocking=False):
            message = "已有 LOOM 更新任务正在进行"
            remediation = ["等待当前更新完成后再试。"]
            if progress_callback:
                progress_callback(
                    {
                        "phase": "failed",
                        "downloaded": 0,
                        "total": 0,
                        "percent": 0,
                        "version": "",
                        "message": message,
                        "errorCode": "update_in_progress",
                        "retryable": True,
                        "remediation": remediation,
                    }
                )
            return False, self.current_version(), [message, *remediation]
        self.last_installer_path = ""
        self._cancel_event.clear()
        try:
            self._report("checking", callback=progress_callback)
            release, error = self._resolve_latest_release()
            if error or release is None:
                message = error or "没有可用的 LOOM 更新"
                remediation = ("检查网络连接后重试；若仍失败，请导出诊断日志。",)
                self._report(
                    "failed",
                    message=message,
                    error_code="release_unavailable",
                    retryable=True,
                    remediation=remediation,
                    callback=progress_callback,
                )
                return False, self.current_version(), [message, *remediation]
            self.cached_release = release
            if _version_tuple(release.version) <= _version_tuple(self.current_version()):
                self._report(
                    "current",
                    version=self.current_version(),
                    message="当前已是最新版本",
                    callback=progress_callback,
                )
                return True, self.current_version(), ["当前已是最新版本"]

            try:
                os.makedirs(self.update_cache_dir, exist_ok=True)
                final_path = os.path.join(self.update_cache_dir, release.filename)
                partial_path = final_path + ".part"
                if os.path.isfile(final_path):
                    cached_size = os.path.getsize(final_path)
                    cached_hash = self._hash_file(final_path)
                    if (release.size > 0 and cached_size != release.size) or cached_hash != release.sha256:
                        os.remove(final_path)
                    else:
                        self._report(
                            "verifying_signature",
                            downloaded=cached_size,
                            total=release.size or cached_size,
                            version=release.version,
                            message="正在重新验证已下载的更新包",
                            callback=progress_callback,
                        )
                        signature_ok, signer = self.signature_verifier(final_path)
                        if not signature_ok:
                            os.remove(final_path)
                            raise ValueError(f"Windows 签名验证失败：{signer}")
                        self.last_installer_path = final_path
                        self.launcher(final_path)
                        self._report(
                            "ready",
                            downloaded=cached_size,
                            total=release.size or cached_size,
                            version=release.version,
                            message="已下载的更新包验证通过，等待安全交接安装",
                            callback=progress_callback,
                        )
                        return True, release.version, [
                            f"已验证 SHA256：{cached_hash}",
                            f"已验证 Windows 发布者：{signer}",
                            f"LOOM {release.version} 更新包已就绪，将在关闭当前程序后无损升级。",
                        ]
                written, digest = self._prepare_partial(partial_path, release.size)
                self._report(
                    "downloading",
                    downloaded=written,
                    total=release.size,
                    version=release.version,
                    message="正在断点续传更新包" if written else "正在下载更新包",
                    callback=progress_callback,
                )
                if release.size <= 0 or written < release.size:
                    written, digest = self._download_release(
                        release,
                        partial_path,
                        written,
                        digest,
                        progress_callback,
                    )
                if release.size > 0 and written != release.size:
                    raise ValueError(f"安装包大小不一致：应为 {release.size}，实际 {written}")
                actual_sha = digest.hexdigest().lower()
                if actual_sha != release.sha256:
                    try:
                        os.remove(partial_path)
                    except OSError:
                        pass
                    raise ValueError(f"SHA256 校验失败：应为 {release.sha256}，实际 {actual_sha}")
                os.replace(partial_path, final_path)

                self._report(
                    "verifying_signature",
                    downloaded=written,
                    total=release.size,
                    version=release.version,
                    message="正在验证 Windows 发布者签名",
                    callback=progress_callback,
                )
                signature_ok, signer = self.signature_verifier(final_path)
                if not signature_ok:
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                    raise ValueError(f"Windows 签名验证失败：{signer}")

                self.last_installer_path = final_path
                self.launcher(final_path)
                self._report(
                    "ready",
                    downloaded=written,
                    total=release.size or written,
                    version=release.version,
                    message="更新包已验证，等待安全交接安装",
                    callback=progress_callback,
                )
                return True, release.version, [
                    f"已验证 SHA256：{actual_sha}",
                    f"已验证 Windows 发布者：{signer}",
                    f"LOOM {release.version} 更新包已就绪，将在关闭当前程序后无损升级。",
                ]
            except UpdateCancelled:
                message = "已取消更新，下载进度已保留"
                remediation = ("下次更新将从已下载的位置继续。",)
                self._report(
                    "cancelled",
                    version=release.version,
                    message=message,
                    error_code="update_cancelled",
                    retryable=True,
                    remediation=remediation,
                    callback=progress_callback,
                )
                return False, self.current_version(), [message, *remediation]
            except Exception as error:
                failure = _classify_update_failure(error)
                self._report(
                    "failed",
                    version=release.version,
                    message=failure.message,
                    error_code=failure.error_code,
                    retryable=failure.retryable,
                    remediation=failure.remediation,
                    callback=progress_callback,
                )
                output = [failure.message, *failure.remediation]
                raw_error = str(error or "").strip()
                if raw_error and raw_error != failure.message:
                    output.append(f"技术信息：{raw_error}")
                return False, self.current_version(), output
        finally:
            self._install_lock.release()

    @staticmethod
    def _prepare_partial(path: str, expected_size: int) -> tuple[int, "hashlib._Hash"]:
        digest = hashlib.sha256()
        written = 0
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if expected_size > 0 and size > expected_size:
                os.remove(path)
            else:
                with open(path, "rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        written += len(chunk)
        return written, digest

    @staticmethod
    def _hash_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().lower()

    def _download_release(
        self,
        release: LoomRelease,
        partial_path: str,
        written: int,
        digest,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> tuple[int, Any]:
        headers = {"User-Agent": "LOOM-Updater/2", "Accept-Encoding": "identity"}
        if written > 0:
            headers["Range"] = f"bytes={written}-"
        request = urllib.request.Request(release.url, headers=headers)
        try:
            response_context = self.opener(request, timeout=120)
        except urllib.error.HTTPError as error:
            if int(getattr(error, "code", 0) or 0) == 416 and written > 0:
                try:
                    os.remove(partial_path)
                except FileNotFoundError:
                    pass
                raise ConnectionError("服务器拒绝断点续传（HTTP 416），已清除旧分段，请重试。") from error
            raise
        with response_context as response:
            status = int(getattr(response, "status", 200) or 200)
            if written > 0 and status == 206:
                response_headers = getattr(response, "headers", {}) or {}
                content_range = str(response_headers.get("Content-Range") or "").strip()
                range_match = re.match(r"^bytes\s+(\d+)-\d+/(?:\d+|\*)$", content_range, re.IGNORECASE)
                if not range_match or int(range_match.group(1)) != written:
                    try:
                        os.remove(partial_path)
                    except FileNotFoundError:
                        pass
                    raise ConnectionError(
                        f"断点续传响应范围无效：期望从 {written} 开始，实际为 {content_range or '缺失'}"
                    )
            if written > 0 and status != 206:
                written = 0
                digest = hashlib.sha256()
                mode = "wb"
            else:
                mode = "ab" if written > 0 else "wb"
            with open(partial_path, mode) as output:
                while True:
                    if self._cancel_event.is_set():
                        raise UpdateCancelled()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    self._report(
                        "downloading",
                        downloaded=written,
                        total=release.size,
                        version=release.version,
                        message="正在下载更新包",
                        callback=progress_callback,
                    )
                    if self._cancel_event.is_set():
                        raise UpdateCancelled()
        return written, digest

    def _fetch_release(self, source_url: str) -> LoomRelease:
        source_url = _safe_https_url(source_url)
        request = urllib.request.Request(
            source_url,
            headers={"Accept": "application/json", "User-Agent": "LOOM-Updater/2"},
        )
        with self.opener(request, timeout=15) as response:
            raw = response.read(2 * 1024 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or bool(payload.get("draft")) or bool(payload.get("prerelease")):
            raise ValueError("更新源没有正式发布版本")
        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise ValueError("更新源缺少附件列表")

        setup: dict[str, Any] | None = None
        version = ""
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or asset.get("filename") or "").strip()
            match = SETUP_NAME_RE.fullmatch(name)
            if match:
                setup = asset
                version = match.group("version")
                break
        if setup is None:
            raise ValueError("正式发布中没有唯一推荐的 LOOM 完整安装包")

        filename = str(setup.get("name") or setup.get("filename") or "").strip()
        url = _safe_https_url(setup.get("browser_download_url") or setup.get("download_url"))
        size = int(setup.get("size") or 0)
        if size < 0:
            raise ValueError("安装包大小无效")
        digest = str(setup.get("digest") or "").strip().lower()
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        if not SHA256_RE.fullmatch(sha256):
            sha256 = self._fetch_sidecar_sha(assets, filename)
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError("正式发布缺少可验证的 SHA256")
        return LoomRelease(
            version=version,
            filename=filename,
            url=url,
            size=size,
            sha256=sha256.lower(),
            source=urlparse(source_url).hostname or source_url,
            notes=str(payload.get("body") or payload.get("description") or "").strip()[:20000],
            published_at=str(payload.get("published_at") or payload.get("created_at") or "").strip(),
            release_url=str(payload.get("html_url") or payload.get("url") or "").strip(),
        )

    def _fetch_sidecar_sha(self, assets: list[Any], filename: str) -> str:
        expected_name = filename + ".sha256.txt"
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or asset.get("filename") or "").strip()
            if name.lower() != expected_name.lower():
                continue
            url = _safe_https_url(asset.get("browser_download_url") or asset.get("download_url"))
            request = urllib.request.Request(url, headers={"User-Agent": "LOOM-Updater/2"})
            with self.opener(request, timeout=15) as response:
                text = response.read(4096).decode("ascii", errors="replace")
            match = SHA256_RE.search(text)
            return match.group(1).lower() if match else ""
        return ""

    @staticmethod
    def _deferred_launcher(_path: str) -> None:
        # The frontend hands the verified path to Tauri. Tauri then stops the
        # Bridge, writes the recovery marker and starts the isolated updater.
        return None
