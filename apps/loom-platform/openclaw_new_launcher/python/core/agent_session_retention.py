"""Non-invasive session inventory and retention checks for external agents."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping


SUPPORTED_COMPONENTS = {"codex-desktop", "claude-code"}


class SessionRetentionError(RuntimeError):
    """Raised when an agent configuration operation could hide or lose sessions."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


def resolve_agent_session_home(
    component_id: str,
    *,
    env: Mapping[str, str] | None = None,
    user_home: str | None = None,
) -> dict[str, str]:
    component_id = str(component_id or "").strip()
    if component_id not in SUPPORTED_COMPONENTS:
        raise ValueError(f"unsupported_agent_session_home: {component_id}")

    environment = os.environ if env is None else env
    if component_id == "codex-desktop":
        configured = str(environment.get("CODEX_HOME") or "").strip()
        if configured:
            return {
                "homePath": _absolute(configured),
                "homeSource": "CODEX_HOME",
            }
        directory_name = ".codex"
    else:
        configured = str(environment.get("CLAUDE_CONFIG_DIR") or "").strip()
        if configured:
            return {
                "homePath": _absolute(configured),
                "homeSource": "CLAUDE_CONFIG_DIR",
            }
        directory_name = ".claude"

    profile = user_home or os.path.expanduser("~")
    return {
        "homePath": _absolute(os.path.join(profile, directory_name)),
        "homeSource": "default",
    }


def _count_jsonl_files(root: str) -> tuple[int, list[str]]:
    if not os.path.isdir(root):
        return 0, []
    count = 0
    errors: list[str] = []
    try:
        for directory, _subdirectories, filenames in os.walk(root, followlinks=False):
            for filename in filenames:
                if filename.lower().endswith(".jsonl"):
                    count += 1
    except OSError as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    return count, errors


def capture_agent_session_inventory(
    component_id: str,
    *,
    home_path: str | None = None,
    env: Mapping[str, str] | None = None,
    user_home: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_agent_session_home(component_id, env=env, user_home=user_home)
    session_home = _absolute(home_path) if home_path else resolved["homePath"]
    home_source = "explicit" if home_path else resolved["homeSource"]
    inventory: dict[str, Any] = {
        "schemaVersion": 1,
        "componentId": component_id,
        "homePath": session_home,
        "homeSource": home_source,
        "homeExists": os.path.isdir(session_home),
        "capturedAt": _iso_now(),
        "errors": [],
    }

    if component_id == "codex-desktop":
        active, active_errors = _count_jsonl_files(os.path.join(session_home, "sessions"))
        archived, archived_errors = _count_jsonl_files(os.path.join(session_home, "archived_sessions"))
        inventory.update(
            {
                "activeThreads": active,
                "archivedThreads": archived,
                "totalThreads": active + archived,
                "indexes": {
                    "stateDatabase": os.path.isfile(os.path.join(session_home, "state_5.sqlite")),
                    "legacyStateDatabase": os.path.isfile(
                        os.path.join(session_home, "sqlite", "state_5.sqlite")
                    ),
                    "sessionIndex": os.path.isfile(os.path.join(session_home, "session_index.jsonl")),
                },
                "errors": [*active_errors, *archived_errors],
            }
        )
        return inventory

    project_threads, project_errors = _count_jsonl_files(os.path.join(session_home, "projects"))
    inventory.update(
        {
            "projectThreads": project_threads,
            "totalThreads": project_threads,
            "indexes": {},
            "errors": project_errors,
        }
    )
    return inventory


def assert_agent_sessions_preserved(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    before_home = os.path.normcase(os.path.normpath(str(before.get("homePath") or "")))
    after_home = os.path.normcase(os.path.normpath(str(after.get("homePath") or "")))
    if not before_home or before_home != after_home:
        raise SessionRetentionError("agent_session_home_changed")

    before_total = int(before.get("totalThreads") or 0)
    after_total = int(after.get("totalThreads") or 0)
    if after_total < before_total:
        raise SessionRetentionError(
            f"agent_session_count_decreased: before={before_total}; after={after_total}"
        )

    before_indexes = before.get("indexes") if isinstance(before.get("indexes"), Mapping) else {}
    after_indexes = after.get("indexes") if isinstance(after.get("indexes"), Mapping) else {}
    missing_indexes = [
        name
        for name, existed in before_indexes.items()
        if existed and not bool(after_indexes.get(name))
    ]
    if missing_indexes:
        raise SessionRetentionError(
            f"agent_session_index_missing: {','.join(sorted(missing_indexes))}"
        )
