"""Component download, verification, extraction, and rollback."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

from core.component_state import ComponentState, ComponentStateStore
from core.release_manifest import ReleaseComponent


ComponentFetcher = Callable[[str, float], bytes]
ProgressCallback = Callable[[str, str], None]


class ComponentInstallError(RuntimeError):
    """Raised when a component cannot be installed safely."""


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
        timeout: float = 30.0,
    ):
        self.base_path = os.path.abspath(base_path)
        self.state_store = state_store
        self.fetcher = fetcher or _default_fetcher
        self.timeout = timeout
        self.cache_dir = os.path.join(self.base_path, "data", ".installer", "cache")
        self.staging_dir = os.path.join(self.base_path, "data", ".installer", "staging")
        self.rollback_dir = os.path.join(self.base_path, "data", ".installer", "rollback")

    def install(
        self,
        component: ReleaseComponent,
        *,
        job_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ComponentState:
        existing_state = self.state_store.load().get(component.component_id)
        existing_version = existing_state.version if existing_state else None
        self._mark(component, "downloading", job_id=job_id, on_progress=on_progress, message=f"Downloading {component.name}")
        try:
            package = self._download(component)
        except Exception as exc:
            self.state_store.mark(component.component_id, "download_failed", version=component.version, job_id=job_id, error_message=str(exc))
            if on_progress:
                on_progress(f"Download failed: {exc}", "danger")
            raise ComponentInstallError(f"download failed for {component.component_id}: {exc}") from exc

        self._mark(component, "verifying", job_id=job_id, on_progress=on_progress, message=f"Verifying {component.name}")
        digest = hashlib.sha256(package).hexdigest()
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
                on_progress("Verification failed: sha256 mismatch", "danger")
            raise ComponentInstallError(f"sha256 mismatch for {component.component_id}")

        self._mark(component, "extracting", job_id=job_id, on_progress=on_progress, message=f"Installing {component.name}")
        install_path = self._safe_install_path(component.install_path)
        staging_path = self._component_staging_path(component)
        self._remove_path(staging_path)
        os.makedirs(staging_path, exist_ok=True)

        try:
            self._extract(component, package, staging_path)
            previous = self._swap(component, staging_path, install_path, previous_version=existing_version)
        except Exception as exc:
            self._remove_path(staging_path)
            self.state_store.mark(component.component_id, "extract_failed", version=component.version, job_id=job_id, error_message=str(exc))
            if on_progress:
                on_progress(f"Install failed: {exc}", "danger")
            raise ComponentInstallError(f"extract failed for {component.component_id}: {exc}") from exc

        state = self.state_store.mark(
            component.component_id,
            "ready",
            version=component.version,
            job_id=job_id,
            previous_version=previous.version if previous else None,
        )
        if on_progress:
            on_progress(f"{component.name} is ready", "ok")
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
            install_path = os.path.join(self.base_path, "OpenClawFiles", "agents", component_id)
        os.makedirs(os.path.dirname(install_path), exist_ok=True)
        os.replace(previous_path, install_path)

        return self.state_store.mark(component_id, "ready", version=previous_version, previous_version=None)

    def _download(self, component: ReleaseComponent) -> bytes:
        errors = []
        for url in component.urls:
            try:
                return self.fetcher(url, self.timeout)
            except Exception as exc:
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

    def _extract(self, component: ReleaseComponent, package: bytes, staging_path: str) -> None:
        if component.archive_type != "zip":
            os.makedirs(staging_path, exist_ok=True)
            filename = component.entry or f"{component.component_id}.bin"
            target = self._safe_join(staging_path, filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(package)
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp:
            temp.write(package)
            zip_path = temp.name
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                for info in archive.infolist():
                    self._safe_join(staging_path, info.filename)
                archive.extractall(staging_path)
        finally:
            try:
                os.unlink(zip_path)
            except OSError:
                pass

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
            os.replace(install_path, previous.path)

        os.makedirs(os.path.dirname(install_path), exist_ok=True)
        os.replace(staging_path, install_path)
        return previous

    def _safe_install_path(self, install_path: str) -> str:
        normalized = install_path.replace("\\", os.sep).replace("/", os.sep)
        target = os.path.abspath(os.path.join(self.base_path, normalized))
        if not _is_path_inside(target, self.base_path):
            raise ComponentInstallError("install path escapes base directory")
        return target

    def _component_staging_path(self, component: ReleaseComponent) -> str:
        return os.path.join(self.staging_dir, component.component_id)

    def _rollback_path(self, component_id: str) -> str:
        return os.path.join(self.rollback_dir, component_id)

    def _find_active_component_path(self, component_id: str) -> str | None:
        candidates = [
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
            raise ComponentInstallError("zip path traversal is not allowed")
        target = os.path.abspath(os.path.join(root, *[part for part in normalized.split("/") if part]))
        if not _is_path_inside(target, root):
            raise ComponentInstallError("zip path traversal is not allowed")
        return target

    @staticmethod
    def _remove_path(path: str) -> None:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.unlink(path)


def _default_fetcher(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "OpenClaw-Launcher/component-installer"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _is_path_inside(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
    except ValueError:
        return False
    return common == os.path.abspath(root)
