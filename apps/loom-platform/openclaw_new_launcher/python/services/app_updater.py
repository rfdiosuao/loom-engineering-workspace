"""Verified, resumable LOOM desktop application update support."""

from __future__ import annotations

import base64
import copy
import errno
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.paths import AppPaths


DEFAULT_RELEASE_API_URLS = (
    "https://gitee.com/api/v5/repos/rfdiosuao/lumi/releases/latest",
    "https://github.com/rfdiosuao/loom-engineering-workspace/releases/latest/download/LOOM-stable.update.json",
    "https://api.github.com/repos/rfdiosuao/loom-engineering-workspace/releases/latest",
)
RELEASE_DISCOVERY_ATTEMPTS = 3
SETUP_NAME_RE = re.compile(r"^LOOM-(?P<version>\d+\.\d+\.\d+)-setup\.exe$", re.IGNORECASE)
SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
UPDATE_MANIFEST_SUFFIX = ".update.json"
UPDATE_PUBLIC_KEY_ENV = "LOOM_DESKTOP_UPDATE_PUBLIC_KEY"
UPDATE_PUBLIC_KEY_PATH_ENV = "LOOM_DESKTOP_UPDATE_PUBLIC_KEY_PATH"


@dataclass(frozen=True)
class UpdateDownloadPart:
    index: int
    url: str
    size: int
    sha256: str
    fallback_urls: tuple[str, ...] = ()


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
    update_manifest: dict[str, Any] | None = None
    fallback_urls: tuple[str, ...] = ()
    download_parts: tuple[UpdateDownloadPart, ...] = ()


@dataclass(frozen=True)
class UpdateBrand:
    brand_id: str = "loom"
    display_name: str = "LOOM"
    product: str = "LOOM"
    channel: str = "stable"
    channel_id: str = "loom-stable"
    file_prefix: str = "LOOM"
    manifest_url: str = ""
    cache_key: str = "LOOM"
    public_key: str = ""


class UpdateCancelled(Exception):
    """Raised after the user asks the resumable downloader to stop."""


@dataclass(frozen=True)
class UpdateFailure:
    error_code: str
    message: str
    retryable: bool
    remediation: tuple[str, ...]


def _classify_update_failure(
    error: Exception,
    display_name: str = "LOOM",
) -> UpdateFailure:
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
            (f"确认当前账户可写入 {display_name} 更新目录，并检查安全软件是否拦截。",),
        )
    if isinstance(error, (ConnectionError, TimeoutError, urllib.error.URLError)) or any(
        marker in lowered
        for marker in ("connection reset", "connection aborted", "timed out", "network is unreachable")
    ):
        return UpdateFailure(
            "network_interrupted",
            "网络连接中断，已保留下载进度。",
            True,
            (f"网络恢复后点击重试，{display_name} 会从已下载的位置继续。",),
        )
    if "签名验证失败" in lowered or "signature verification failed" in lowered:
        return UpdateFailure(
            "signature_invalid",
            "更新包官方发布签名无效，已拒绝安装。",
            False,
            (
                f"当前版本可能尚未内置最新更新公钥，请从 {display_name} 官方发布页手动安装一次最新版；之后可继续自动更新。",
                f"请只使用 {display_name} 官方发布的更新包。",
            ),
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


def _is_github_asset_api_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return (
        parsed.scheme == "https"
        and str(parsed.hostname or "").casefold() == "api.github.com"
        and re.search(r"/releases/assets/\d+/?$", parsed.path, re.IGNORECASE) is not None
    )


def _is_transient_release_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        status_code = int(getattr(error, "code", 0) or 0)
        return status_code in {408, 429} or status_code >= 500
    return isinstance(
        error,
        (ConnectionError, TimeoutError, urllib.error.URLError),
    )


def _asset_download_candidates(asset: dict[str, Any]) -> tuple[str, ...]:
    candidates: list[str] = []
    api_url = str(asset.get("url") or "").strip()
    if _is_github_asset_api_url(api_url):
        candidates.append(_safe_https_url(api_url))
    for key in ("browser_download_url", "download_url"):
        raw_url = str(asset.get(key) or "").strip()
        if not raw_url:
            continue
        url = _safe_https_url(raw_url)
        if url not in candidates:
            candidates.append(url)
    if not candidates:
        raise ValueError("更新附件缺少 HTTPS 下载地址")
    return tuple(candidates)


def _parse_download_parts(
    payload: dict[str, Any],
    expected_size: int,
) -> tuple[UpdateDownloadPart, ...]:
    raw_parts = payload.get("downloadParts")
    if raw_parts is None:
        return ()
    if not isinstance(raw_parts, list) or not 1 <= len(raw_parts) <= 32:
        raise ValueError("更新清单 downloadParts 必须包含 1 到 32 个分片")

    parts: list[UpdateDownloadPart] = []
    seen_urls: set[str] = set()
    for expected_index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            raise ValueError("更新清单 downloadParts 项必须是对象")
        index = int(raw_part.get("index") or 0)
        if index != expected_index:
            raise ValueError("更新清单 downloadParts index 必须从 1 连续递增")
        url = _safe_https_url(raw_part.get("url"))
        if url in seen_urls:
            raise ValueError("更新清单 downloadParts URL 不能重复")
        seen_urls.add(url)
        raw_fallback_urls = raw_part.get("fallbackUrls") or []
        if not isinstance(raw_fallback_urls, list) or len(raw_fallback_urls) > 3:
            raise ValueError("更新清单分片 fallbackUrls 必须是最多包含 3 项的数组")
        fallback_urls: list[str] = []
        for raw_fallback_url in raw_fallback_urls:
            fallback_url = _safe_https_url(raw_fallback_url)
            if fallback_url in seen_urls:
                raise ValueError("更新清单 downloadParts URL 不能重复")
            seen_urls.add(fallback_url)
            fallback_urls.append(fallback_url)
        size = int(raw_part.get("size") or 0)
        if size <= 0 or size > 100 * 1024 * 1024:
            raise ValueError("更新清单分片大小必须大于 0 且不超过 100 MiB")
        sha256 = str(raw_part.get("sha256") or "").strip().lower()
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError("更新清单分片 sha256 无效")
        parts.append(
            UpdateDownloadPart(
                index=index,
                url=url,
                size=size,
                sha256=sha256,
                fallback_urls=tuple(fallback_urls),
            )
        )

    if expected_size <= 0 or sum(part.size for part in parts) != expected_size:
        raise ValueError("更新清单分片总大小与完整安装包不一致")
    return tuple(parts)


def _load_update_brand(paths: AppPaths) -> UpdateBrand:
    config_path = getattr(paths, "desktop_update_brand", "")
    if not config_path or not os.path.isfile(config_path):
        return UpdateBrand()
    try:
        with open(config_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"OEM update configuration is invalid: {error}") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("OEM update configuration must use schemaVersion 1")

    def required(key: str) -> str:
        value = str(payload.get(key) or "").strip()
        if not value:
            raise ValueError(f"OEM update configuration is missing {key}")
        return value

    manifest_url = _safe_https_url(required("manifestUrl"))
    file_prefix = required("filePrefix")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{2,63}", file_prefix):
        raise ValueError("OEM update filePrefix is invalid")
    cache_key = required("cacheKey")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{2,127}", cache_key):
        raise ValueError("OEM update cacheKey is invalid")
    return UpdateBrand(
        brand_id=required("brandId"),
        display_name=required("displayName"),
        product=required("product"),
        channel=required("channel"),
        channel_id=required("channelId"),
        file_prefix=file_prefix,
        manifest_url=manifest_url,
        cache_key=cache_key,
        public_key=str(payload.get("publicKey") or "").strip(),
    )


def _default_update_cache_dir(cache_key: str = "LOOM") -> str:
    explicit = str(os.environ.get("LOOM_UPDATE_CACHE_DIR") or "").strip()
    if explicit:
        return os.path.abspath(explicit)
    root = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not root:
        root = tempfile.gettempdir()
    safe_key = re.sub(r"[^A-Za-z0-9.-]+", "-", str(cache_key or "LOOM")).strip(".-") or "LOOM"
    return os.path.join(root, f"{safe_key}-Update-Recovery", "updates")


def _canonical_update_manifest_payload(data: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(data)
    payload.pop("signature", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_update_public_key(value: str) -> Ed25519PublicKey:
    text = str(value or "").strip()
    if not text:
        raise ValueError("更新公钥为空")
    if text.startswith("-----BEGIN"):
        loaded = serialization.load_pem_public_key(text.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("更新公钥必须使用 Ed25519")
        return loaded
    if text.lower().startswith("ed25519:"):
        text = text.split(":", 1)[1].strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as error:
        raise ValueError("更新公钥不是有效的 Base64") from error
    if len(raw) != 32:
        raise ValueError("更新公钥必须是 32 字节 Ed25519 公钥")
    return Ed25519PublicKey.from_public_bytes(raw)


def _default_update_public_key(paths: AppPaths, brand: UpdateBrand | None = None) -> str:
    inline_key = str(os.environ.get(UPDATE_PUBLIC_KEY_ENV) or "").strip()
    if inline_key:
        return inline_key
    if brand is not None and brand.public_key:
        return brand.public_key
    configured_path = str(os.environ.get(UPDATE_PUBLIC_KEY_PATH_ENV) or "").strip()
    candidates = [
        configured_path,
        os.path.join(paths.base_path, "desktop-update-public-key.txt"),
        os.path.join(paths.base_path, "_up_", "desktop-update-public-key.txt"),
        os.path.join(paths.base_path, "resources", "desktop-update-public-key.txt"),
    ]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        with open(candidate, "r", encoding="utf-8-sig") as handle:
            return handle.read().strip()
    return ""


def _verify_loom_update_signature(
    release: LoomRelease,
    public_key: str,
    brand: UpdateBrand | None = None,
) -> tuple[bool, str]:
    expected_brand = brand or UpdateBrand()
    manifest = release.update_manifest
    if not isinstance(manifest, dict):
        return False, f"发布页缺少 {expected_brand.display_name} 官方更新签名"
    try:
        if manifest.get("schemaVersion") != 1:
            raise ValueError("schemaVersion 必须为 1")
        if manifest.get("product") != expected_brand.product:
            raise ValueError(f"product 必须为 {expected_brand.product}")
        if manifest.get("channel") != expected_brand.channel:
            raise ValueError(f"channel 必须为 {expected_brand.channel}")
        manifest_channel_id = str(manifest.get("channelId") or "").strip()
        if manifest_channel_id and manifest_channel_id != expected_brand.channel_id:
            raise ValueError(f"channelId 必须为 {expected_brand.channel_id}")
        signature = manifest.get("signature")
        if not isinstance(signature, dict) or signature.get("algorithm") != "ed25519":
            raise ValueError("signature.algorithm 必须为 ed25519")
        signature_bytes = base64.b64decode(str(signature.get("value") or ""), validate=True)
        if len(signature_bytes) != 64:
            raise ValueError("signature.value 必须是 64 字节 Ed25519 签名")
        _load_update_public_key(public_key).verify(
            signature_bytes,
            _canonical_update_manifest_payload(manifest),
        )
        expected = {
            "version": release.version,
            "filename": release.filename,
            "size": release.size,
            "sha256": release.sha256,
        }
        for field, value in expected.items():
            actual = manifest.get(field)
            if field == "sha256":
                actual = str(actual or "").lower()
            if actual != value:
                raise ValueError(f"{field} 与发布资产不一致")
    except InvalidSignature:
        return False, f"{expected_brand.display_name} 官方更新签名无效"
    except Exception as error:
        return False, f"{expected_brand.display_name} 官方更新签名验证失败：{error}"
    return True, f"{expected_brand.display_name} 官方发布签名（Ed25519）"


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
        update_public_key: str | None = None,
        update_cache_dir: str | None = None,
    ) -> None:
        self.paths = paths
        self.brand = _load_update_brand(paths)
        self._current_version = str(current_version or os.environ.get("LOOM_APP_VERSION") or "0.0.0").strip()
        configured_urls = tuple(str(url).strip() for url in release_api_urls if str(url).strip())
        if self.brand.manifest_url and configured_urls == DEFAULT_RELEASE_API_URLS:
            configured_urls = (self.brand.manifest_url,)
        self.release_api_urls = configured_urls
        self.opener = opener
        self.launcher = launcher or self._deferred_launcher
        self.signature_verifier = signature_verifier
        self.update_public_key = (
            str(update_public_key).strip()
            if update_public_key is not None
            else _default_update_public_key(paths, self.brand)
        )
        self.update_cache_dir = os.path.abspath(
            update_cache_dir or _default_update_cache_dir(self.brand.cache_key)
        )
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

    def _verify_release_authenticity(self, path: str, release: LoomRelease) -> tuple[bool, str]:
        windows_ok, windows_signer = self.signature_verifier(path)
        if windows_ok:
            return True, f"Windows 发布者：{windows_signer}"
        loom_ok, loom_signer = _verify_loom_update_signature(
            release,
            self.update_public_key,
            self.brand,
        )
        if loom_ok:
            return True, loom_signer
        return False, f"Windows Authenticode：{windows_signer}；{loom_signer}"

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
        def fetch_source(
            source_index: int,
            source_url: str,
        ) -> tuple[int, LoomRelease | None, str | None]:
            source_error: Exception | None = None
            for attempt in range(1, RELEASE_DISCOVERY_ATTEMPTS + 1):
                try:
                    return source_index, self._fetch_release(source_url), None
                except Exception as error:
                    source_error = error
                    if (
                        attempt >= RELEASE_DISCOVERY_ATTEMPTS
                        or not _is_transient_release_error(error)
                    ):
                        break
                    time.sleep(float(attempt))
            return (
                source_index,
                None,
                f"{urlparse(source_url).hostname or 'release'}: {source_error}",
            )

        sources = tuple(enumerate(self.release_api_urls))
        if not sources:
            return None, "没有可用的 LOOM 更新源"

        results: dict[int, LoomRelease] = {}
        errors: dict[int, str] = {}
        with ThreadPoolExecutor(
            max_workers=min(3, len(sources)),
            thread_name_prefix="loom-update-source",
        ) as executor:
            futures = {
                executor.submit(fetch_source, source_index, source_url): source_index
                for source_index, source_url in sources
            }
            for future in as_completed(futures):
                source_index, release, error = future.result()
                if release is not None:
                    results[source_index] = release
                elif error:
                    errors[source_index] = error
        if not results:
            return (
                None,
                "；".join(errors[index] for index, _url in sources if index in errors)
                or "没有可用的 LOOM 更新源",
            )

        selected_index, release = max(
            results.items(),
            key=lambda item: (_version_tuple(item[1].version), -item[0]),
        )
        del selected_index
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
                        signature_ok, signer = self._verify_release_authenticity(final_path, release)
                        if not signature_ok:
                            os.remove(final_path)
                            raise ValueError(f"{self.brand.display_name} 官方签名验证失败：{signer}")
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
                            f"已验证 {signer}",
                            f"{self.brand.display_name} {release.version} 更新包已就绪，将在关闭当前程序后无损升级。",
                        ]
                if release.download_parts:
                    try:
                        written, digest = self._download_segmented_release(
                            release,
                            partial_path,
                            progress_callback,
                        )
                    except UpdateCancelled:
                        raise
                    except Exception as mirror_error:
                        written, digest = self._prepare_partial(partial_path, release.size)
                        self._report(
                            "downloading",
                            downloaded=written,
                            total=release.size,
                            version=release.version,
                            message=f"国内镜像不可用，正在切换官方源：{mirror_error}",
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
                else:
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
                    message=f"正在验证 {self.brand.display_name} 官方发布签名",
                    callback=progress_callback,
                )
                signature_ok, signer = self._verify_release_authenticity(final_path, release)
                if not signature_ok:
                    try:
                        os.remove(final_path)
                    except OSError:
                        pass
                    raise ValueError(f"{self.brand.display_name} 官方签名验证失败：{signer}")

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
                    f"已验证 {signer}",
                    f"{self.brand.display_name} {release.version} 更新包已就绪，将在关闭当前程序后无损升级。",
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
                failure = _classify_update_failure(error, self.brand.display_name)
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
        response_context = None
        connection_errors: list[str] = []
        download_urls = (release.url, *release.fallback_urls)
        for index, download_url in enumerate(download_urls):
            headers = {
                "User-Agent": f"{self.brand.brand_id}-Updater/2",
                "Accept-Encoding": "identity",
            }
            if _is_github_asset_api_url(download_url):
                headers["Accept"] = "application/octet-stream"
            if written > 0:
                headers["Range"] = f"bytes={written}-"
            request = urllib.request.Request(download_url, headers=headers)
            try:
                response_context = self.opener(request, timeout=120)
                break
            except urllib.error.HTTPError as error:
                if int(getattr(error, "code", 0) or 0) == 416 and written > 0:
                    try:
                        os.remove(partial_path)
                    except FileNotFoundError:
                        pass
                    raise ConnectionError(
                        "服务器拒绝断点续传（HTTP 416），已清除旧分段，请重试。"
                    ) from error
                connection_errors.append(f"{urlparse(download_url).hostname}: HTTP {error.code}")
                if index + 1 >= len(download_urls):
                    raise
            except (ConnectionError, TimeoutError, urllib.error.URLError) as error:
                connection_errors.append(f"{urlparse(download_url).hostname}: {error}")
                if index + 1 >= len(download_urls):
                    raise ConnectionError("；".join(connection_errors)) from error
        if response_context is None:
            raise ConnectionError("；".join(connection_errors) or "更新包下载连接失败")
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

    def _download_segmented_release(
        self,
        release: LoomRelease,
        partial_path: str,
        progress_callback: Callable[[dict[str, Any]], None] | None,
    ) -> tuple[int, Any]:
        parts_root = partial_path + ".parts"
        os.makedirs(parts_root, exist_ok=True)
        progress_lock = threading.Lock()
        part_downloaded = {part.index: 0 for part in release.download_parts}

        def report_part_progress(part_index: int, downloaded: int) -> None:
            with progress_lock:
                part_downloaded[part_index] = max(
                    part_downloaded[part_index],
                    int(downloaded),
                )
                self._report(
                    "downloading",
                    downloaded=sum(part_downloaded.values()),
                    total=release.size,
                    version=release.version,
                    message=f"正在并行下载更新分片（最多 4 路）",
                    callback=progress_callback,
                )

        def download_part(part: UpdateDownloadPart) -> tuple[int, str, int]:
            part_path = os.path.join(
                parts_root,
                f"{release.filename}.part{part.index:03d}",
            )
            written, digest = self._prepare_partial(part_path, part.size)
            if written == part.size and digest.hexdigest().lower() != part.sha256:
                os.remove(part_path)
                written, digest = 0, hashlib.sha256()

            report_part_progress(part.index, written)
            if written < part.size:
                part_release = LoomRelease(
                    version=release.version,
                    filename=os.path.basename(part_path),
                    url=part.url,
                    size=part.size,
                    sha256=part.sha256,
                    source=urlparse(part.url).hostname or part.url,
                    fallback_urls=part.fallback_urls,
                )

                def report_current_part(state: dict[str, Any]) -> None:
                    report_part_progress(
                        part.index,
                        int(state.get("downloaded") or 0),
                    )

                written, digest = self._download_release(
                    part_release,
                    part_path,
                    written,
                    digest,
                    report_current_part,
                )
            actual_sha = digest.hexdigest().lower()
            if written != part.size or actual_sha != part.sha256:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                raise ValueError(
                    f"国内镜像分片 {part.index} 校验失败"
                )
            report_part_progress(part.index, written)
            return part.index, part_path, written

        part_results: dict[int, tuple[str, int]] = {}
        with ThreadPoolExecutor(
            max_workers=min(4, len(release.download_parts)),
            thread_name_prefix="loom-update-part",
        ) as executor:
            futures = {
                executor.submit(download_part, part): part.index
                for part in release.download_parts
            }
            for future in as_completed(futures):
                part_index, part_path, written = future.result()
                part_results[part_index] = (part_path, written)

        part_paths = [
            part_results[part.index][0]
            for part in release.download_parts
        ]

        combined_digest = hashlib.sha256()
        combined_size = 0
        try:
            with open(partial_path, "wb") as output:
                for part_path in part_paths:
                    with open(part_path, "rb") as source:
                        while True:
                            if self._cancel_event.is_set():
                                raise UpdateCancelled()
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            combined_digest.update(chunk)
                            combined_size += len(chunk)
        except Exception:
            try:
                os.remove(partial_path)
            except OSError:
                pass
            raise

        if combined_size != release.size or combined_digest.hexdigest().lower() != release.sha256:
            try:
                os.remove(partial_path)
            except OSError:
                pass
            raise ValueError("国内镜像合并后的完整安装包校验失败")

        for part_path in part_paths:
            try:
                os.remove(part_path)
            except OSError:
                pass
        try:
            os.rmdir(parts_root)
        except OSError:
            pass
        return combined_size, combined_digest

    def _fetch_release(self, source_url: str) -> LoomRelease:
        source_url = _safe_https_url(source_url)
        request = urllib.request.Request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"{self.brand.brand_id}-Updater/2",
            },
        )
        with self.opener(request, timeout=15) as response:
            raw = response.read(2 * 1024 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        if (
            isinstance(payload, dict)
            and payload.get("schemaVersion") == 1
            and isinstance(payload.get("signature"), dict)
            and payload.get("filename")
        ):
            return self._release_from_direct_manifest(payload, source_url)
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
            setup_name_re = re.compile(
                rf"^{re.escape(self.brand.file_prefix)}-(?P<version>\d+\.\d+\.\d+)-setup\.exe$",
                re.IGNORECASE,
            )
            match = setup_name_re.fullmatch(name)
            if match:
                setup = asset
                version = match.group("version")
                break
        if setup is None:
            direct_manifest_names = []
            manifest_name_re = re.compile(
                rf"^{re.escape(self.brand.file_prefix)}-(?P<version>\d+\.\d+\.\d+)-setup\.exe"
                rf"{re.escape(UPDATE_MANIFEST_SUFFIX)}$",
                re.IGNORECASE,
            )
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name") or asset.get("filename") or "").strip()
                match = manifest_name_re.fullmatch(name)
                if match:
                    direct_manifest_names.append(
                        (name[: -len(UPDATE_MANIFEST_SUFFIX)], match.group("version"))
                    )
            if len(direct_manifest_names) == 1:
                manifest_installer_name, manifest_version = direct_manifest_names[0]
                update_manifest = self._fetch_update_manifest(
                    assets,
                    manifest_installer_name,
                )
                if update_manifest is None:
                    raise ValueError("国内更新源缺少可读取的签名清单")
                release = self._release_from_direct_manifest(
                    update_manifest,
                    source_url,
                )
                if release.version != manifest_version:
                    raise ValueError("国内更新清单版本与附件名称不一致")
                return release
            raise ValueError(
                f"正式发布中没有唯一推荐的 {self.brand.display_name} 完整安装包"
            )

        filename = str(setup.get("name") or setup.get("filename") or "").strip()
        download_urls = _asset_download_candidates(setup)
        url = download_urls[0]
        size = int(setup.get("size") or 0)
        if size < 0:
            raise ValueError("安装包大小无效")
        update_manifest = self._fetch_update_manifest(assets, filename)
        if update_manifest is not None:
            manifest_size = int(update_manifest.get("size") or 0)
            if size <= 0:
                size = manifest_size
            elif manifest_size > 0 and manifest_size != size:
                raise ValueError("更新签名文件大小与发布资产不一致")
        digest = str(setup.get("digest") or "").strip().lower()
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        if not SHA256_RE.fullmatch(sha256) and update_manifest is not None:
            sha256 = str(update_manifest.get("sha256") or "").strip().lower()
        if not SHA256_RE.fullmatch(sha256):
            sha256 = self._fetch_sidecar_sha(assets, filename)
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError("正式发布缺少可验证的 SHA256")
        download_parts = (
            _parse_download_parts(update_manifest, size)
            if update_manifest is not None
            else ()
        )
        release = LoomRelease(
            version=version,
            filename=filename,
            url=url,
            size=size,
            sha256=sha256.lower(),
            source=urlparse(source_url).hostname or source_url,
            notes=str(payload.get("body") or payload.get("description") or "").strip()[:20000],
            published_at=str(payload.get("published_at") or payload.get("created_at") or "").strip(),
            release_url=str(payload.get("html_url") or payload.get("url") or "").strip(),
            update_manifest=update_manifest,
            fallback_urls=download_urls[1:],
            download_parts=download_parts,
        )
        if release.update_manifest is not None and self.update_public_key:
            signature_ok, signature_detail = _verify_loom_update_signature(
                release,
                self.update_public_key,
                self.brand,
            )
            if not signature_ok:
                raise ValueError(signature_detail)
        return release

    def _release_from_direct_manifest(
        self,
        payload: dict[str, Any],
        source_url: str,
    ) -> LoomRelease:
        filename = str(payload.get("filename") or "").strip()
        setup_name_re = re.compile(
            rf"^{re.escape(self.brand.file_prefix)}-(?P<version>\d+\.\d+\.\d+)-setup\.exe$",
            re.IGNORECASE,
        )
        match = setup_name_re.fullmatch(filename)
        if not match:
            raise ValueError(
                f"更新清单 filename 必须匹配 {self.brand.file_prefix}-<version>-setup.exe"
            )
        size = int(payload.get("size") or 0)
        sha256 = str(payload.get("sha256") or "").strip().lower()
        if size <= 0:
            raise ValueError("更新清单 size 必须大于 0")
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError("更新清单 sha256 无效")
        download_parts = _parse_download_parts(payload, size)
        download_url = _safe_https_url(payload.get("downloadUrl"))
        raw_fallback_urls = payload.get("fallbackUrls") or []
        if not isinstance(raw_fallback_urls, list) or len(raw_fallback_urls) > 3:
            raise ValueError("更新清单 fallbackUrls 必须是最多包含 3 项的数组")
        fallback_urls = tuple(_safe_https_url(url) for url in raw_fallback_urls)
        release = LoomRelease(
            version=match.group("version"),
            filename=filename,
            url=download_url,
            size=size,
            sha256=sha256,
            source=urlparse(source_url).hostname or source_url,
            notes=str(payload.get("notes") or "").strip()[:20000],
            published_at=str(payload.get("publishedAt") or "").strip(),
            release_url=source_url,
            update_manifest=payload,
            fallback_urls=fallback_urls,
            download_parts=download_parts,
        )
        if not self.update_public_key:
            raise ValueError(f"{self.brand.display_name} 更新公钥缺失")
        signature_ok, signature_detail = _verify_loom_update_signature(
            release,
            self.update_public_key,
            self.brand,
        )
        if not signature_ok:
            raise ValueError(signature_detail)
        return release

    def _fetch_sidecar_sha(self, assets: list[Any], filename: str) -> str:
        expected_name = filename + ".sha256.txt"
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or asset.get("filename") or "").strip()
            if name.lower() != expected_name.lower():
                continue
            last_error: Exception | None = None
            for url in _asset_download_candidates(asset):
                headers = {"User-Agent": f"{self.brand.brand_id}-Updater/2"}
                if _is_github_asset_api_url(url):
                    headers["Accept"] = "application/octet-stream"
                request = urllib.request.Request(url, headers=headers)
                try:
                    with self.opener(request, timeout=15) as response:
                        text = response.read(4096).decode("ascii", errors="replace")
                    match = SHA256_RE.search(text)
                    if match:
                        return match.group(1).lower()
                    last_error = ValueError("SHA256 旁车文件内容无效")
                except Exception as error:
                    last_error = error
            if last_error is not None:
                raise last_error
        return ""

    def _fetch_update_manifest(self, assets: list[Any], filename: str) -> dict[str, Any] | None:
        expected_name = filename + UPDATE_MANIFEST_SUFFIX
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or asset.get("filename") or "").strip()
            if name.lower() != expected_name.lower():
                continue
            last_error: Exception | None = None
            for url in _asset_download_candidates(asset):
                request = urllib.request.Request(
                    url,
                    headers={
                        "Accept": (
                            "application/octet-stream"
                            if _is_github_asset_api_url(url)
                            else "application/json"
                        ),
                        "User-Agent": f"{self.brand.brand_id}-Updater/2",
                    },
                )
                try:
                    with self.opener(request, timeout=15) as response:
                        raw = response.read(64 * 1024)
                    payload = json.loads(raw.decode("utf-8"))
                    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
                        raise ValueError("LOOM 更新签名文件必须是 schemaVersion 1 的 JSON 对象")
                    return payload
                except Exception as error:
                    last_error = error
            if last_error is not None:
                raise last_error
        return None

    @staticmethod
    def _deferred_launcher(_path: str) -> None:
        # The frontend hands the verified path to Tauri. Tauri then stops the
        # Bridge, writes the recovery marker and starts the isolated updater.
        return None
