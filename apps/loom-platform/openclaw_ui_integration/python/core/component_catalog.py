"""UI-facing component catalog derived from the release manifest and local state."""

from __future__ import annotations

import os
from typing import Any

from core.component_state import ComponentStateStore
from core.release_manifest import ReleaseComponent, ReleaseManifest, load_release_manifest_file


class ComponentCatalog:
    def __init__(self, *, manifest_path: str, state_store: ComponentStateStore):
        self.manifest_path = manifest_path
        self.state_store = state_store

    def status(self) -> dict[str, Any]:
        try:
            manifest = load_release_manifest_file(self.manifest_path)
        except Exception as exc:
            return {
                "manifest": None,
                "components": [],
                "error": f"manifest unavailable: {exc}",
            }

        states = {state.component_id: state for state in self.state_store.snapshot_for_manifest(manifest)}
        return {
            "manifest": _manifest_payload(manifest),
            "components": [_component_payload(component, states[component.component_id]) for component in manifest.components],
            "error": None,
        }


def default_manifest_path(base_path: str) -> str:
    candidates = [
        os.path.join(base_path, "release-manifest.json"),
        os.path.join(base_path, "_up_", "release-manifest.json"),
        os.path.join(base_path, "examples", "openclaw-release-manifest.example.json"),
        os.path.join(os.path.dirname(base_path), "examples", "openclaw-release-manifest.example.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def default_component_state_path(base_path: str) -> str:
    return os.path.join(base_path, "data", ".installer", "components-state.json")


def _manifest_payload(manifest: ReleaseManifest) -> dict[str, Any]:
    return {
        "schemaVersion": manifest.schema_version,
        "product": manifest.product,
        "channel": manifest.channel,
        "version": manifest.version,
        "publishedAt": manifest.published_at,
        "minLauncherVersion": manifest.min_launcher_version,
    }


def _component_payload(component: ReleaseComponent, state) -> dict[str, Any]:
    return {
        "id": component.component_id,
        "name": component.name,
        "version": component.version,
        "installedVersion": state.version if state.status == "ready" else None,
        "previousVersion": state.previous_version,
        "status": state.status,
        "jobId": state.job_id,
        "platform": component.platform,
        "arch": component.arch,
        "type": component.archive_type,
        "size": component.size,
        "entry": component.entry,
        "installPath": component.install_path,
        "category": component.category or "component",
        "officialUrl": component.official_url,
        "description": component.description,
        "urls": list(component.urls),
        "updatedAt": state.updated_at,
        "errorCode": state.error_code,
        "errorMessage": state.error_message,
    }
