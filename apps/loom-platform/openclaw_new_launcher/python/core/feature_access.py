"""Commercial license feature policy shared by Bridge route guards."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlsplit


class LicenseAuthorizer(Protocol):
    def is_authorized(self, feature: str | None = None) -> bool: ...


COMMERCIAL_FEATURES = frozenset(
    {
        "acquisition.workbench",
        "acquisition.feishu",
        "matrix.devices",
        "templates.cloud",
    }
)

# Phone Matrix is the single commercial capability for its acquisition,
# template, and Feishu execution surfaces. Feishu OAuth/scopes remain runtime
# prerequisites, but are not a second paid entitlement.
# A route matches only the exact prefix or a slash-delimited child, never a
# lookalike such as /api/matrixevil.
FEATURE_PATH_RULES: tuple[tuple[str, str], ...] = (
    ("/api/skills", "matrix.devices"),
    ("/api/matrix", "matrix.devices"),
    ("/api/phone-stream", "matrix.devices"),
    ("/api/phone", "matrix.devices"),
    ("/api/storyboard/generate", "matrix.devices"),
)

PHONE_CLI_PREFIXES = ("phone:", "loom:phone:", "openclaw:phone:")


def _normalized_path(value: str) -> str:
    path = urlsplit(str(value or "").replace("\\", "/")).path
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _is_safety_cleanup_request(path: str, method: str | None) -> bool:
    normalized_method = str(method or "").strip().upper()
    if normalized_method == "POST" and path in {
        "/api/matrix/cancel",
        "/api/matrix/emergency-stop",
        "/api/phone/usb/disconnect",
        "/api/phone/daemon/stop",
        "/api/phone/events/stop",
    }:
        return True
    if normalized_method == "POST":
        parts = path.strip("/").split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["api", "matrix", "tasks"]
            and bool(parts[3])
            and parts[4] == "pause"
        ):
            return True
    if normalized_method != "DELETE":
        return False
    parts = path.strip("/").split("/")
    if (
        len(parts) == 5
        and parts[:3] == ["api", "phone-stream", "devices"]
        and bool(parts[3])
        and parts[4] == "session"
    ):
        return True
    if parts[:4] == ["api", "phone", "config", "device"]:
        return len(parts) == 5 and bool(parts[4])
    return (
        len(parts) == 5
        and parts[:3] == ["api", "matrix", "devices"]
        and bool(parts[3])
        and parts[4] == "lease"
    )


def feature_for_path(value: str, *, method: str | None = None) -> str | None:
    path = _normalized_path(value)
    if _is_safety_cleanup_request(path, method):
        return None
    for prefix, feature in FEATURE_PATH_RULES:
        if _matches(path, prefix):
            return feature
    return None


def _is_phone_video_stop_cleanup(command_id: str, args: object) -> bool:
    command = str(command_id or "").strip().lower()
    if command != "phone:video" or not isinstance(args, (list, tuple)):
        return False

    saw_stop = False
    device_id = ""
    index = 0
    while index < len(args):
        raw = str(args[index] or "").strip()
        normalized = raw.lower()
        if normalized == "stop":
            if saw_stop:
                return False
            saw_stop = True
        elif normalized == "--json":
            pass
        elif normalized == "--device-id":
            if device_id or index + 1 >= len(args):
                return False
            candidate = str(args[index + 1] or "").strip()
            if not candidate or candidate.startswith("-"):
                return False
            device_id = candidate
            index += 1
        elif normalized.startswith("--device-id="):
            if device_id:
                return False
            candidate = raw.split("=", 1)[1].strip()
            if not candidate or candidate.startswith("-"):
                return False
            device_id = candidate
        else:
            return False
        index += 1

    return saw_stop and bool(device_id)


def feature_for_cli_command(command_id: str, args: object = None) -> str | None:
    command = str(command_id or "").strip().lower()
    if _is_phone_video_stop_cleanup(command, args):
        return None
    return "matrix.devices" if command.startswith(PHONE_CLI_PREFIXES) else None


def _public_entitlement_details(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked_fragments = (
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
    )
    return {
        str(key): item
        for key, item in value.items()
        if not any(
            fragment in str(key).strip().lower()
            for fragment in blocked_fragments
        )
        and isinstance(item, (bool, int, float, str, type(None)))
    }


def commercial_feature_denial(
    path: str,
    license_manager: LicenseAuthorizer,
    *,
    feature: str | None = None,
    method: str | None = None,
) -> dict[str, Any] | None:
    required = feature or feature_for_path(path, method=method)
    if not required:
        return None
    state_reader = getattr(license_manager, "current_state", None)
    if callable(state_reader):
        state = state_reader(required)
        if isinstance(state, dict):
            if bool(state.get("authorized")):
                return None
            return {
                "error": str(
                    state.get("message")
                    or "当前商业授权未开通此功能"
                ),
                "code": str(state.get("code") or "LICENSE_FEATURE_REQUIRED"),
                "feature": required,
                "source": str(state.get("source") or ""),
                "action": str(state.get("action") or ""),
                "details": _public_entitlement_details(state.get("details")),
            }
    if license_manager.is_authorized(required):
        return None
    return {
        "error": "当前商业授权未开通此功能",
        "code": "LICENSE_FEATURE_REQUIRED",
        "feature": required,
    }
