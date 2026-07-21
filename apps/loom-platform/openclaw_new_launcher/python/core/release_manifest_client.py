"""Fetch and cache release manifests with ordered source fallback."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

from core.release_manifest import (
    ReleaseManifest,
    default_release_manifest_public_key,
    load_release_manifest_file,
    parse_release_manifest,
)


ManifestFetcher = Callable[[str, float], bytes]
SOURCE_URLS_ENV = "LOOM_RELEASE_MANIFEST_URLS"
SOURCE_URL_ENV = "LOOM_RELEASE_MANIFEST_URL"
DISABLE_DEFAULT_SOURCES_ENV = "LOOM_RELEASE_MANIFEST_DISABLE_DEFAULTS"
DEFAULT_RELEASE_MANIFEST_SOURCES = (
    "https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/stable/release-manifest.json",
    "https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/rc/release-manifest.json",
)


class ManifestFetchError(RuntimeError):
    """Raised when no remote or cached manifest can be loaded."""


@dataclass(frozen=True)
class ManifestLoadResult:
    manifest: ReleaseManifest
    source_url: str | None
    from_cache: bool
    warnings: tuple[str, ...] = ()


class ReleaseManifestClient:
    def __init__(
        self,
        *,
        cache_path: str,
        public_key: str | bytes | None = None,
        fetcher: ManifestFetcher | None = None,
        timeout: float = 10.0,
    ):
        self.cache_path = cache_path
        self.public_key = public_key
        self.fetcher = fetcher or _default_fetcher
        self.timeout = timeout

    def fetch(self, sources: list[str] | tuple[str, ...]) -> ManifestLoadResult:
        warnings: list[str] = []
        if not sources:
            cached = self._load_cache()
            if cached is not None:
                return ManifestLoadResult(manifest=cached, source_url=None, from_cache=True, warnings=("No manifest source configured",))
            raise ManifestFetchError("No manifest source configured and no cached manifest is available")

        for source_url in sources:
            try:
                body = self.fetcher(source_url, self.timeout)
                data = json.loads(body.decode("utf-8-sig"))
                manifest = parse_release_manifest(
                    data,
                    public_key=self._public_key(),
                    require_signature_verification=True,
                )
            except Exception as exc:
                warnings.append(f"{source_url}: {exc}")
                continue
            self._write_cache(data)
            return ManifestLoadResult(manifest=manifest, source_url=source_url, from_cache=False, warnings=tuple(warnings))

        cached = self._load_cache()
        if cached is not None:
            return ManifestLoadResult(manifest=cached, source_url=None, from_cache=True, warnings=tuple(warnings))

        raise ManifestFetchError("All manifest sources failed and no cached manifest is available")

    def _load_cache(self) -> ReleaseManifest | None:
        if not os.path.exists(self.cache_path):
            return None
        try:
            return load_release_manifest_file(
                self.cache_path,
                public_key=self._public_key(),
                require_signature_verification=True,
            )
        except Exception:
            return None

    def _public_key(self) -> str | bytes | None:
        if self.public_key is not None:
            return self.public_key
        return default_release_manifest_public_key(self.cache_path)

    def _write_cache(self, data: object) -> None:
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".release-manifest-", suffix=".tmp", dir=os.path.dirname(self.cache_path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp_path, self.cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _default_fetcher(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "LOOM-Launcher/installer-manifest"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def default_release_manifest_sources() -> list[str]:
    """Return ordered release manifest sources for component installation."""
    env_sources: list[str] = []
    for value in (os.environ.get(SOURCE_URLS_ENV), os.environ.get(SOURCE_URL_ENV)):
        env_sources.extend(_split_sources(value or ""))
    if env_sources:
        return _dedupe_sources(env_sources)
    if _truthy(os.environ.get(DISABLE_DEFAULT_SOURCES_ENV)):
        return []
    return list(DEFAULT_RELEASE_MANIFEST_SOURCES)


def _split_sources(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\r", "\n").replace(";", "\n").replace(",", "\n").split("\n") if item.strip()]


def _dedupe_sources(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
