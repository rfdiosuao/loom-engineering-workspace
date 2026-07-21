"""Persistent component install state for the launcher installer."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from core.release_manifest import ReleaseManifest


_STATE_LOCK = threading.RLock()

COMPONENT_STATUSES = {
    "not_installed",
    "resolving_manifest",
    "downloading",
    "verifying",
    "extracting",
    "configuring",
    "health_checking",
    "starting",
    "uninstalling",
    "rolling_back",
    "upgrade_available",
    "manual_install_required",
    "simulation_ready",
    "ready",
    "started",
    "download_failed",
    "verify_failed",
    "extract_failed",
    "config_failed",
    "health_failed",
    "start_failed",
    "uninstall_failed",
    "rollback_failed",
    "rollback_available",
}


class ComponentStateError(ValueError):
    """Raised when component state cannot be represented safely."""


@dataclass(frozen=True)
class ComponentState:
    component_id: str
    status: str
    version: str | None = None
    previous_version: str | None = None
    job_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ComponentState":
        component_id = data.get("componentId")
        status = data.get("status")
        if not isinstance(component_id, str) or not component_id.strip():
            raise ComponentStateError("componentId must be a non-empty string")
        if not isinstance(status, str) or status not in COMPONENT_STATUSES:
            raise ComponentStateError("status is invalid")
        return cls(
            component_id=component_id,
            status=status,
            version=_optional_str(data.get("version")),
            previous_version=_optional_str(data.get("previousVersion")),
            job_id=_optional_str(data.get("jobId")),
            error_code=_optional_str(data.get("errorCode")),
            error_message=_optional_str(data.get("errorMessage")),
            updated_at=_optional_str(data.get("updatedAt")),
        )

    def to_json(self) -> dict[str, Any]:
        payload = {
            "componentId": self.component_id,
            "status": self.status,
            "version": self.version,
            "previousVersion": self.previous_version,
            "jobId": self.job_id,
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
            "updatedAt": self.updated_at,
        }
        return {key: value for key, value in payload.items() if value is not None}


class ComponentStateStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict[str, ComponentState]:
        data = self._read_raw()
        raw_components = data.get("components")
        if not isinstance(raw_components, Mapping):
            return {}

        states: dict[str, ComponentState] = {}
        for component_id, raw_state in raw_components.items():
            if not isinstance(raw_state, Mapping):
                continue
            try:
                state = ComponentState.from_mapping(raw_state)
            except ComponentStateError:
                continue
            if state.component_id == component_id:
                states[component_id] = state
        return states

    def mark(
        self,
        component_id: str,
        status: str,
        *,
        version: str | None = None,
        previous_version: str | None = None,
        job_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ComponentState:
        if not component_id or not component_id.strip():
            raise ComponentStateError("component_id must be a non-empty string")
        if status not in COMPONENT_STATUSES:
            raise ComponentStateError(f"status is invalid: {status}")

        with _STATE_LOCK:
            states = self.load()
            existing = states.get(component_id)
            state = ComponentState(
                component_id=component_id,
                status=status,
                version=version if version is not None else (existing.version if existing else None),
                previous_version=previous_version if previous_version is not None else (existing.previous_version if existing else None),
                job_id=job_id if job_id is not None else (existing.job_id if existing else None),
                error_code=error_code,
                error_message=error_message,
                updated_at=_utc_now(),
            )
            states[component_id] = state
            self._write(states)
            return state

    def snapshot_for_manifest(self, manifest: ReleaseManifest) -> tuple[ComponentState, ...]:
        states = self.load()
        snapshot = []
        for component in manifest.components:
            state = states.get(component.component_id)
            if state is None:
                state = ComponentState(
                    component_id=component.component_id,
                    status="not_installed",
                    version=component.version,
                    updated_at=None,
                )
            snapshot.append(state)
        return tuple(snapshot)

    def _read_raw(self) -> dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write(self, states: Mapping[str, ComponentState]) -> None:
        payload = {
            "schemaVersion": 1,
            "updatedAt": _utc_now(),
            "components": {component_id: state.to_json() for component_id, state in sorted(states.items())},
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".components-state-", suffix=".tmp", dir=os.path.dirname(self.path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                self._write_payload(handle, payload)
            try:
                os.replace(tmp_path, self.path)
            except PermissionError:
                self._write_direct(payload)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _write_payload(handle, payload: Mapping[str, Any]) -> None:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    def _write_direct(self, payload: Mapping[str, Any]) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            self._write_payload(handle, payload)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ComponentStateError("optional state field must be a string")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
