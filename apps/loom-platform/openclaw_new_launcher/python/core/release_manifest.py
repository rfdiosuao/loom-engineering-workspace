"""Release manifest parsing and validation for installable components."""

from __future__ import annotations

import base64
import copy
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
SUPPORTED_ARCHIVE_TYPES = {"zip", "tgz", "installer"}
PUBLIC_KEY_ENV = "LOOM_RELEASE_MANIFEST_PUBLIC_KEY"
PUBLIC_KEY_PATH_ENV = "LOOM_RELEASE_MANIFEST_PUBLIC_KEY_PATH"


class ManifestValidationError(ValueError):
    """Raised when a release manifest is malformed or unsafe."""


@dataclass(frozen=True)
class ManifestSignature:
    algorithm: str
    value: str


@dataclass(frozen=True)
class ComponentHealthCheck:
    kind: str
    url: str
    timeout_ms: int


@dataclass(frozen=True)
class ComponentRollback:
    keep_previous: bool
    backup_name: str | None = None


@dataclass(frozen=True)
class ReleaseComponent:
    component_id: str
    name: str
    version: str
    platform: str
    arch: str
    archive_type: str
    size: int
    sha256: str
    urls: tuple[str, ...]
    install_path: str
    entry: str | None = None
    category: str | None = None
    official_url: str | None = None
    description: str | None = None
    external_paths: tuple[str, ...] = ()
    installer_args: tuple[str, ...] = ()
    installer_timeout_ms: int = 900000
    install_command: tuple[str, ...] = ()
    uninstall_command: tuple[str, ...] = ()
    command_timeout_ms: int = 900000
    health_check: ComponentHealthCheck | None = None
    rollback: ComponentRollback | None = None


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    product: str
    channel: str
    version: str
    published_at: str
    min_launcher_version: str
    signature: ManifestSignature
    components: tuple[ReleaseComponent, ...]

    def component_by_id(self, component_id: str) -> ReleaseComponent | None:
        for component in self.components:
            if component.component_id == component_id:
                return component
        return None


def load_release_manifest_file(
    path: str,
    *,
    public_key: str | bytes | None = None,
    require_signature_verification: bool = False,
) -> ReleaseManifest:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return parse_release_manifest(
        data,
        public_key=public_key,
        require_signature_verification=require_signature_verification,
    )


def default_release_manifest_public_key(manifest_path: str) -> str | None:
    env_key = os.environ.get(PUBLIC_KEY_ENV)
    if env_key and env_key.strip():
        return env_key.strip()

    env_key_path = os.environ.get(PUBLIC_KEY_PATH_ENV)
    if env_key_path and env_key_path.strip() and os.path.exists(env_key_path):
        return _read_text(env_key_path)

    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    candidates = [os.path.join(manifest_dir, "release-public-key.txt")]
    if os.path.basename(manifest_dir).lower() == "_up_":
        candidates.append(os.path.join(os.path.dirname(manifest_dir), "release-public-key.txt"))
    else:
        candidates.append(os.path.join(manifest_dir, "_up_", "release-public-key.txt"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return _read_text(candidate)
    return None


def parse_release_manifest(
    data: Mapping[str, Any],
    *,
    public_key: str | bytes | None = None,
    require_signature_verification: bool = False,
) -> ReleaseManifest:
    if not isinstance(data, Mapping):
        raise ManifestValidationError("manifest must be a JSON object")

    _require_fields(
        data,
        (
            "schemaVersion",
            "product",
            "channel",
            "version",
            "publishedAt",
            "minLauncherVersion",
            "signature",
            "components",
        ),
        "manifest",
    )

    schema_version = _require_int(data, "schemaVersion", "manifest")
    if schema_version != 1:
        raise ManifestValidationError(f"manifest.schemaVersion must be 1, got {schema_version}")

    published_at = _require_str(data, "publishedAt", "manifest")
    _validate_iso_datetime(published_at, "manifest.publishedAt")

    signature = _parse_signature(data["signature"])
    if public_key is not None or require_signature_verification:
        _verify_manifest_signature(data, signature, public_key)

    raw_components = data["components"]
    if not isinstance(raw_components, list) or not raw_components:
        raise ManifestValidationError("manifest.components must be a non-empty array")

    components = tuple(_parse_component(item, index) for index, item in enumerate(raw_components))
    _validate_unique_component_ids(components)

    return ReleaseManifest(
        schema_version=schema_version,
        product=_require_str(data, "product", "manifest"),
        channel=_require_str(data, "channel", "manifest"),
        version=_require_str(data, "version", "manifest"),
        published_at=published_at,
        min_launcher_version=_require_str(data, "minLauncherVersion", "manifest"),
        signature=signature,
        components=components,
    )


def canonical_manifest_payload(data: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(data))
    payload.pop("signature", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_manifest_signature(
    data: Mapping[str, Any],
    signature: ManifestSignature,
    public_key: str | bytes | None,
) -> None:
    if not public_key:
        raise ManifestValidationError("manifest signature verification requires a public key")
    public_key_obj = _load_ed25519_public_key(public_key)
    try:
        signature_bytes = base64.b64decode(signature.value, validate=True)
        public_key_obj.verify(signature_bytes, canonical_manifest_payload(data))
    except InvalidSignature as exc:
        raise ManifestValidationError("manifest.signature verification failed") from exc


def _load_ed25519_public_key(value: str | bytes) -> Ed25519PublicKey:
    if isinstance(value, bytes):
        raw = value
    else:
        text = value.strip()
        if not text:
            raise ManifestValidationError("manifest public key must not be empty")
        if text.startswith("-----BEGIN"):
            try:
                loaded = serialization.load_pem_public_key(text.encode("utf-8"))
            except Exception as exc:
                raise ManifestValidationError("manifest public key PEM is invalid") from exc
            if not isinstance(loaded, Ed25519PublicKey):
                raise ManifestValidationError("manifest public key must be Ed25519")
            return loaded
        if text.lower().startswith("ed25519:"):
            text = text.split(":", 1)[1].strip()
        try:
            raw = base64.b64decode(text, validate=True)
        except Exception as exc:
            raise ManifestValidationError("manifest public key must be base64 raw Ed25519") from exc
    if len(raw) != 32:
        raise ManifestValidationError("manifest public key must be 32 raw Ed25519 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read().strip()


def _parse_signature(data: Any) -> ManifestSignature:
    if not isinstance(data, Mapping):
        raise ManifestValidationError("manifest.signature must be an object")
    _require_fields(data, ("algorithm", "value"), "manifest.signature")
    algorithm = _require_str(data, "algorithm", "manifest.signature")
    if algorithm != "ed25519":
        raise ManifestValidationError("manifest.signature.algorithm must be ed25519")
    value = _require_str(data, "value", "manifest.signature")
    if "replace" in value.lower() or "placeholder" in value.lower():
        raise ManifestValidationError("manifest.signature.value must not be a placeholder")
    try:
        signature_bytes = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ManifestValidationError("manifest.signature.value must be base64") from exc
    if len(signature_bytes) != 64:
        raise ManifestValidationError("manifest.signature.value must be a 64-byte Ed25519 signature")
    return ManifestSignature(
        algorithm=algorithm,
        value=value,
    )


def _parse_component(data: Any, index: int) -> ReleaseComponent:
    context = f"components[{index}]"
    if not isinstance(data, Mapping):
        raise ManifestValidationError(f"{context} must be an object")

    _require_fields(
        data,
        (
            "id",
            "name",
            "version",
            "platform",
            "arch",
            "type",
            "size",
            "sha256",
            "urls",
            "installPath",
        ),
        context,
    )

    sha256 = _require_str(data, "sha256", context)
    if not SHA256_RE.match(sha256):
        raise ManifestValidationError(f"{context}.sha256 must be a 64-character hex digest")
    sha256_lower = sha256.lower()
    if _is_placeholder_sha256(sha256_lower):
        raise ManifestValidationError(f"{context}.sha256 must not be a placeholder digest")

    size = _require_int(data, "size", context)
    if size <= 0:
        raise ManifestValidationError(f"{context}.size must be greater than 0")

    urls = _parse_urls(data["urls"], context)
    install_path = _require_str(data, "installPath", context)
    _validate_relative_install_path(install_path, f"{context}.installPath")

    health_check = None
    if "healthCheck" in data and data["healthCheck"] is not None:
        health_check = _parse_health_check(data["healthCheck"], context)

    rollback = None
    if "rollback" in data and data["rollback"] is not None:
        rollback = _parse_rollback(data["rollback"], context)

    entry = None
    if data.get("entry") is not None:
        entry = _require_str(data, "entry", context)

    category = None
    if data.get("category") is not None:
        category = _require_str(data, "category", context)

    official_url = None
    if data.get("officialUrl") is not None:
        official_url = _require_str(data, "officialUrl", context)

    description = None
    if data.get("description") is not None:
        description = _require_str(data, "description", context)

    external_paths = _parse_optional_string_list(data.get("externalPaths"), f"{context}.externalPaths")
    installer_args = _parse_optional_string_list(data.get("installerArgs"), f"{context}.installerArgs")
    install_command = _parse_optional_string_list(data.get("installCommand"), f"{context}.installCommand")
    _validate_install_command(install_command, f"{context}.installCommand")
    uninstall_command = _parse_optional_string_list(data.get("uninstallCommand"), f"{context}.uninstallCommand")
    installer_timeout_ms = 900000
    if data.get("installerTimeoutMs") is not None:
        installer_timeout_ms = _require_int(data, "installerTimeoutMs", context)
        if installer_timeout_ms <= 0:
            raise ManifestValidationError(f"{context}.installerTimeoutMs must be greater than 0")
    command_timeout_ms = 900000
    if data.get("commandTimeoutMs") is not None:
        command_timeout_ms = _require_int(data, "commandTimeoutMs", context)
        if command_timeout_ms <= 0:
            raise ManifestValidationError(f"{context}.commandTimeoutMs must be greater than 0")

    archive_type = _require_str(data, "type", context)
    if archive_type not in SUPPORTED_ARCHIVE_TYPES:
        raise ManifestValidationError(f"{context}.type must be one of: installer, tgz, zip")

    return ReleaseComponent(
        component_id=_require_str(data, "id", context),
        name=_require_str(data, "name", context),
        version=_require_str(data, "version", context),
        platform=_require_str(data, "platform", context),
        arch=_require_str(data, "arch", context),
        archive_type=archive_type,
        size=size,
        sha256=sha256_lower,
        urls=urls,
        install_path=install_path.replace("\\", "/"),
        entry=entry,
        category=category,
        official_url=official_url,
        description=description,
        external_paths=external_paths,
        installer_args=installer_args,
        installer_timeout_ms=installer_timeout_ms,
        install_command=install_command,
        uninstall_command=uninstall_command,
        command_timeout_ms=command_timeout_ms,
        health_check=health_check,
        rollback=rollback,
    )


def _parse_health_check(data: Any, component_context: str) -> ComponentHealthCheck:
    context = f"{component_context}.healthCheck"
    if not isinstance(data, Mapping):
        raise ManifestValidationError(f"{context} must be an object")
    _require_fields(data, ("kind", "url", "timeoutMs"), context)
    timeout_ms = _require_int(data, "timeoutMs", context)
    if timeout_ms <= 0:
        raise ManifestValidationError(f"{context}.timeoutMs must be greater than 0")
    return ComponentHealthCheck(
        kind=_require_str(data, "kind", context),
        url=_require_str(data, "url", context),
        timeout_ms=timeout_ms,
    )


def _validate_install_command(command: tuple[str, ...], context: str) -> None:
    if not command:
        return
    lowered_parts = [part.strip().lower() for part in command if str(part or "").strip()]
    joined = " ".join(lowered_parts)
    if "@latest" in joined or re.search(r"(^|[\s@])latest($|\s)", joined):
        raise ManifestValidationError(f"{context} must pin versions and must not use latest")
    if ("|" in joined or "invoke-expression" in joined or re.search(r"\biex\b", joined)) and re.search(
        r"\b(irm|iwr|invoke-restmethod|invoke-webrequest)\b",
        joined,
    ):
        raise ManifestValidationError(f"{context} must not pipe downloaded scripts into a shell")
    if lowered_parts[:2] == ["npm", "install"]:
        _validate_npm_install_command(command, context)


def _validate_npm_install_command(command: tuple[str, ...], context: str) -> None:
    saw_install = False
    packages: list[str] = []
    skip_next = False
    options_with_value = {"--prefix", "--cache", "--registry", "--userconfig", "--globalconfig", "--tag"}
    for raw_part in command[1:]:
        part = str(raw_part or "").strip()
        if not part:
            continue
        if skip_next:
            skip_next = False
            continue
        lowered = part.lower()
        if not saw_install:
            if lowered in {"install", "i", "add"}:
                saw_install = True
            continue
        if lowered in options_with_value:
            skip_next = True
            continue
        if lowered.startswith("-"):
            continue
        packages.append(part)
    for package in packages:
        if not _npm_package_has_pinned_version(package):
            raise ManifestValidationError(f"{context} npm packages must use pinned versions")


def _npm_package_has_pinned_version(package: str) -> bool:
    if package.startswith(("file:", "http://", "https:")):
        return True
    if package.startswith("@"):
        return package.count("@") >= 2 and not package.lower().endswith("@latest")
    return "@" in package and not package.lower().endswith("@latest")


def _is_placeholder_sha256(value: str) -> bool:
    if len(set(value)) == 1:
        return True
    hex_cycle = "0123456789abcdef"
    if value in (hex_cycle * 8):
        return True
    common_chunks = {"deadbeef", "cafebabe", "feedface"}
    return len(value) == 64 and value[:8] in common_chunks and value == value[:8] * 8


def _parse_rollback(data: Any, component_context: str) -> ComponentRollback:
    context = f"{component_context}.rollback"
    if not isinstance(data, Mapping):
        raise ManifestValidationError(f"{context} must be an object")
    keep_previous = data.get("keepPrevious")
    if not isinstance(keep_previous, bool):
        raise ManifestValidationError(f"{context}.keepPrevious must be a boolean")
    backup_name = data.get("backupName")
    if backup_name is not None and not isinstance(backup_name, str):
        raise ManifestValidationError(f"{context}.backupName must be a string")
    return ComponentRollback(keep_previous=keep_previous, backup_name=backup_name)


def _parse_urls(data: Any, context: str) -> tuple[str, ...]:
    if not isinstance(data, list) or not data:
        raise ManifestValidationError(f"{context}.urls must be a non-empty array")
    urls = []
    for index, url in enumerate(data):
        if not isinstance(url, str) or not url.strip():
            raise ManifestValidationError(f"{context}.urls[{index}] must be a non-empty string")
        _validate_download_url(url, f"{context}.urls[{index}]")
        urls.append(url)
    return tuple(urls)


def _parse_optional_string_list(data: Any, context: str) -> tuple[str, ...]:
    if data is None:
        return ()
    if not isinstance(data, list):
        raise ManifestValidationError(f"{context} must be an array")
    values: list[str] = []
    for index, value in enumerate(data):
        if not isinstance(value, str) or not value.strip():
            raise ManifestValidationError(f"{context}[{index}] must be a non-empty string")
        values.append(value.strip())
    return tuple(values)


def _validate_download_url(url: str, context: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ManifestValidationError(f"{context} must use http or https")
    hostname = (parsed.hostname or "").lower()
    if hostname in LOCAL_HOSTNAMES:
        raise ManifestValidationError(f"{context} must not point to localhost or {hostname}")
    if hostname.endswith(".local"):
        raise ManifestValidationError(f"{context} must not point to a .local host")


def _validate_relative_install_path(path: str, context: str) -> None:
    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        raise ManifestValidationError(f"{context} must be a relative path")
    if os.path.isabs(path):
        raise ManifestValidationError(f"{context} must be a relative path")
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        raise ManifestValidationError(f"{context} must not contain path traversal")


def _validate_unique_component_ids(components: tuple[ReleaseComponent, ...]) -> None:
    seen = set()
    for component in components:
        if component.component_id in seen:
            raise ManifestValidationError(f"duplicate component id: {component.component_id}")
        seen.add(component.component_id)


def _validate_iso_datetime(value: str, context: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{context} must be an ISO-8601 datetime") from exc


def _require_fields(data: Mapping[str, Any], fields: tuple[str, ...], context: str) -> None:
    for field in fields:
        if field not in data:
            raise ManifestValidationError(f"{context}.{field} is required")


def _require_str(data: Mapping[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{context}.{field} must be a non-empty string")
    return value


def _require_int(data: Mapping[str, Any], field: str, context: str) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestValidationError(f"{context}.{field} must be an integer")
    return value
