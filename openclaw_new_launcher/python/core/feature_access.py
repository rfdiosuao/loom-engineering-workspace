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

# Rules are intentionally longest-prefix-first. A route matches only the exact
# prefix or a slash-delimited child, never a lookalike such as /api/matrixevil.
FEATURE_PATH_RULES: tuple[tuple[str, str], ...] = (
    ("/api/matrix/acquisition/feishu", "acquisition.feishu"),
    ("/api/matrix/acquisition/templates", "templates.cloud"),
    ("/api/matrix/acquisition", "acquisition.workbench"),
    ("/api/matrix", "matrix.devices"),
    ("/api/phone", "matrix.devices"),
    ("/api/storyboard/generate", "matrix.devices"),
)

# These commands reduce risk or preserve recovery access. They stay available
# after a matrix license expires so an operator can stop running phone work.
PUBLIC_SAFETY_PATHS = frozenset(
    {
        "/api/matrix/cancel",
        "/api/matrix/emergency-stop",
        "/api/phone/daemon/stop",
        "/api/phone/events/stop",
    }
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


def feature_for_path(value: str) -> str | None:
    path = _normalized_path(value)
    if path in PUBLIC_SAFETY_PATHS:
        return None
    for prefix, feature in FEATURE_PATH_RULES:
        if _matches(path, prefix):
            return feature
    return None


def feature_for_cli_command(command_id: str) -> str | None:
    command = str(command_id or "").strip().lower()
    return "matrix.devices" if command.startswith(PHONE_CLI_PREFIXES) else None


def commercial_feature_denial(
    path: str,
    license_manager: LicenseAuthorizer,
    *,
    feature: str | None = None,
) -> dict[str, Any] | None:
    required = feature or feature_for_path(path)
    if not required or license_manager.is_authorized(required):
        return None
    return {
        "error": "当前商业授权未开通此功能",
        "code": "LICENSE_FEATURE_REQUIRED",
        "feature": required,
    }
