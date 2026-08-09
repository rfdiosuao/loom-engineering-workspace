"""UI-facing component catalog derived from the release manifest and local state."""

from __future__ import annotations

import os
import re
from typing import Any

from collections.abc import Iterable

from core.agent_catalog import AgentCatalog, merge_agent_components
from core.agent_definition import AgentDefinition
from core.component_state import ComponentState, ComponentStateStore
from core.official_codex import CODEX_CLI_COMPONENT_ID, CODEX_DESKTOP_COMPONENT_ID, expand_openai_components
from core.release_manifest import (
    ReleaseComponent,
    ReleaseManifest,
    default_release_manifest_public_key,
    load_release_manifest_file,
)
from core.release_manifest_client import ReleaseManifestClient, default_release_manifest_sources


INSTALLED_STATUSES = {"ready", "started", "starting", "start_failed", "upgrade_available"}


class ComponentCatalog:
    def __init__(
        self,
        *,
        manifest_path: str,
        state_store: ComponentStateStore,
        fallback_components: Iterable[ReleaseComponent] = (),
        agent_definitions: Iterable[AgentDefinition] | None = None,
    ):
        self.manifest_path = manifest_path
        self.state_store = state_store
        self.fallback_components = tuple(fallback_components)
        self.agent_definitions = tuple(agent_definitions) if agent_definitions is not None else AgentCatalog().definitions()

    def status(self, *, state_overrides: Iterable[ComponentState] = ()) -> dict[str, Any]:
        overrides = {state.component_id: state for state in state_overrides}
        try:
            manifest, manifest_warning = load_installable_manifest(self.manifest_path)
        except Exception:
            states = self.state_store.load()
            states.update(overrides)
            components = merge_agent_components(self.fallback_components, self.agent_definitions)
            return {
                "manifest": None,
                "components": [
                    _component_payload(
                        component,
                        _state_for_component(component, states),
                        definition=_definition_by_id(self.agent_definitions, component.component_id),
                        install_locked=_definition_install_locked(self.agent_definitions, component.component_id, fallback=True),
                    )
                    for component in components
                ],
                "warning": "正式组件清单未就绪。签名包组件仅支持本机查看；内置声明式 CLI 仍可按各自安全状态探测或安装。",
                "manifestErrorCode": "manifest_unavailable",
                "installLocked": True,
            }

        components = merge_agent_components(expand_openai_components(manifest.components), self.agent_definitions)
        states = self.state_store.load()
        states.update(overrides)
        return {
            "manifest": _manifest_payload(manifest),
            "components": [
                _component_payload(
                    component,
                    _state_for_component(component, states),
                    definition=_definition_by_id(self.agent_definitions, component.component_id),
                    install_locked=_definition_install_locked(self.agent_definitions, component.component_id, fallback=False),
                )
                for component in components
            ],
            "warning": manifest_warning,
            "manifestErrorCode": None,
            "installLocked": False,
        }


def default_manifest_path(base_path: str) -> str:
    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(path: str) -> None:
        normalized = os.path.normpath(path)
        key = os.path.normcase(os.path.abspath(normalized))
        if key not in seen:
            seen.add(key)
            candidates.append(normalized)

    current = os.path.abspath(base_path)
    for _depth in range(8):
        add_candidate(os.path.join(current, "release-manifest.json"))
        add_candidate(os.path.join(current, "_up_", "release-manifest.json"))
        add_candidate(os.path.join(current, "_up_", "_up_", "release-manifest.json"))
        add_candidate(os.path.join(current, "LOOMFiles", "release-manifest.json"))

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def default_component_state_path(base_path: str) -> str:
    return os.path.join(base_path, "data", ".installer", "components-state.json")


def load_installable_manifest(manifest_path: str) -> tuple[ReleaseManifest, str | None]:
    public_key = default_release_manifest_public_key(manifest_path)
    local_error: Exception | None = None
    if os.path.exists(manifest_path):
        try:
            return (
                load_release_manifest_file(
                    manifest_path,
                    public_key=public_key,
                    require_signature_verification=True,
                ),
                None,
            )
        except Exception as exc:
            local_error = exc

    client = ReleaseManifestClient(cache_path=manifest_path, public_key=public_key, timeout=5.0)
    result = client.fetch(default_release_manifest_sources())
    warning_parts = list(result.warnings)
    if local_error is not None:
        warning_parts.insert(0, f"local manifest failed: {local_error}")
    if result.from_cache:
        warning_parts.append("使用本机缓存的 release manifest")
    elif result.source_url:
        warning_parts.append(f"release manifest 来自 {result.source_url}")
    return result.manifest, "；".join(warning_parts) if warning_parts else None


def _manifest_payload(manifest: ReleaseManifest) -> dict[str, Any]:
    return {
        "schemaVersion": manifest.schema_version,
        "product": manifest.product,
        "channel": manifest.channel,
        "version": manifest.version,
        "publishedAt": manifest.published_at,
        "minLauncherVersion": manifest.min_launcher_version,
    }


def _default_state(component: ReleaseComponent) -> ComponentState:
    return ComponentState(
        component_id=component.component_id,
        status="not_installed",
        version=component.version,
        updated_at=None,
    )


def _state_for_component(component: ReleaseComponent, states: dict[str, ComponentState]) -> ComponentState:
    state = states.get(component.component_id)
    legacy = states.get(CODEX_DESKTOP_COMPONENT_ID)
    legacy_version = str(legacy.version or "") if legacy else ""
    legacy_is_cli = bool(re.search(r"(?:win32|x86_64-pc-windows|codex-cli)", legacy_version, re.IGNORECASE))
    if component.component_id == CODEX_DESKTOP_COMPONENT_ID and state is not None and legacy_is_cli:
        return ComponentState(
            component_id=CODEX_DESKTOP_COMPONENT_ID,
            status="not_installed",
            version=component.version,
            error_code="legacy_codex_cli_state",
            error_message="检测到旧版 Codex CLI 状态；桌面应用需要单独检测",
        )
    if component.component_id == CODEX_CLI_COMPONENT_ID and state is None and legacy is not None and legacy_is_cli:
        return ComponentState(
            component_id=CODEX_CLI_COMPONENT_ID,
            status=legacy.status,
            version=legacy.version,
            previous_version=legacy.previous_version,
            job_id=legacy.job_id,
            error_code="legacy_codex_cli_state",
            error_message="已从旧版混合 Codex 状态迁移；请重新检测 Codex CLI",
            detection=legacy.detection,
            updated_at=legacy.updated_at,
        )
    return state or _default_state(component)


def _component_payload(
    component: ReleaseComponent,
    state,
    *,
    definition: AgentDefinition | None = None,
    install_locked: bool = False,
) -> dict[str, Any]:
    payload = {
        "id": component.component_id,
        "name": component.name,
        "version": component.version,
        "installedVersion": state.version if state.status in INSTALLED_STATUSES else None,
        "previousVersion": state.previous_version,
        "status": state.status,
        "jobId": state.job_id,
        "platform": component.platform,
        "arch": component.arch,
        "type": component.archive_type,
        "size": component.size,
        "entry": component.entry,
        "installPath": component.install_path,
        "installCommand": list(component.install_command),
        "uninstallCommand": list(component.uninstall_command),
        "commandTimeoutMs": component.command_timeout_ms,
        "category": component.category or "component",
        "officialUrl": component.official_url,
        "description": component.description,
        "urls": list(component.urls),
        "updatedAt": state.updated_at,
        "errorCode": state.error_code,
        "errorMessage": state.error_message,
        "detection": state.detection,
        "installLocked": bool(install_locked),
    }
    if definition is not None:
        payload.update(definition.payload())
    return payload


def _definition_by_id(definitions: Iterable[AgentDefinition], component_id: str) -> AgentDefinition | None:
    return next((item for item in definitions if item.component_id == component_id), None)


def _definition_install_locked(
    definitions: Iterable[AgentDefinition],
    component_id: str,
    *,
    fallback: bool,
) -> bool:
    definition = _definition_by_id(definitions, component_id)
    return definition.install_locked if definition is not None else bool(fallback)
