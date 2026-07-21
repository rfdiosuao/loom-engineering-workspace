"""Release manifest parsing and validation for installable components."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse


SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


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


def load_release_manifest_file(path: str) -> ReleaseManifest:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return parse_release_manifest(data)


def parse_release_manifest(data: Mapping[str, Any]) -> ReleaseManifest:
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


def _parse_signature(data: Any) -> ManifestSignature:
    if not isinstance(data, Mapping):
        raise ManifestValidationError("manifest.signature must be an object")
    _require_fields(data, ("algorithm", "value"), "manifest.signature")
    algorithm = _require_str(data, "algorithm", "manifest.signature")
    if algorithm != "ed25519":
        raise ManifestValidationError("manifest.signature.algorithm must be ed25519")
    return ManifestSignature(
        algorithm=algorithm,
        value=_require_str(data, "value", "manifest.signature"),
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

    return ReleaseComponent(
        component_id=_require_str(data, "id", context),
        name=_require_str(data, "name", context),
        version=_require_str(data, "version", context),
        platform=_require_str(data, "platform", context),
        arch=_require_str(data, "arch", context),
        archive_type=_require_str(data, "type", context),
        size=size,
        sha256=sha256.lower(),
        urls=urls,
        install_path=install_path.replace("\\", "/"),
        entry=entry,
        category=category,
        official_url=official_url,
        description=description,
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
