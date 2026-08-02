from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
ENABLED_VALUES = {"1", "true", "yes", "on", "enabled"}
ZPAY_ALLOWED_CHANNELS = frozenset({"alipay", "wxpay"})
ZPAY_REQUIRED_NAMES = (
    "LICENSE_ZPAY_ENABLED",
    "LICENSE_ZPAY_BASE_URL",
    "LICENSE_ZPAY_PID",
    "LICENSE_ZPAY_KEY",
    "LICENSE_ZPAY_CREATE_PATH",
    "LICENSE_ZPAY_CHANNELS",
    "LICENSE_ZPAY_QUERY_ENABLED",
    "LICENSE_ZPAY_QUERY_PATH",
    "LICENSE_ZPAY_NOTIFY_URL",
    "LICENSE_ZPAY_RETURN_URL",
)


def _validate_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("invalid environment variable name")
    return normalized


def _quote_value(value: str) -> str:
    text = str(value)
    if "\r" in text or "\n" in text:
        raise ValueError("environment values must be single-line")
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _value_from_lines(lines: list[str], name: str) -> str:
    prefix = f"{name}="
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip().strip('"').strip("'")
    return ""


def has_nonempty_env_value(path: Path, name: str) -> bool:
    normalized = _validate_name(name)
    return bool(_value_from_lines(_read_lines(Path(path)), normalized))


def _require_zpay_values(path: Path) -> dict[str, str]:
    lines = _read_lines(Path(path))
    values = {name: _value_from_lines(lines, name) for name in ZPAY_REQUIRED_NAMES}
    for name, value in values.items():
        if not value:
            raise ValueError(f"missing required setting: {name}")
    return values


def _enabled(value: str) -> bool:
    return str(value or "").strip().lower() in ENABLED_VALUES


def _validate_https_url(name: str, value: str, *, base_only: bool) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"invalid HTTPS setting: {name}")
    if base_only and (parsed.path not in {"", "/"} or parsed.query):
        raise ValueError(f"invalid provider base URL setting: {name}")


def _validate_provider_path(name: str, value: str) -> None:
    parsed = urlsplit(value)
    decoded_segments = unquote(parsed.path).split("/")
    if (
        not value.startswith("/")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or ".." in decoded_segments
    ):
        raise ValueError(f"invalid provider path setting: {name}")


def _validate_channels(value: str) -> None:
    raw = str(value or "").split(",")
    channels = [item.strip().lower() for item in raw]
    if (
        not channels
        or any(not item or item not in ZPAY_ALLOWED_CHANNELS for item in channels)
    ):
        raise ValueError("invalid payment channel setting: LICENSE_ZPAY_CHANNELS")


def validate_zpay_env_file(path: Path) -> None:
    """Validate production payment readiness without returning secret values."""

    values = _require_zpay_values(Path(path))
    if not _enabled(values["LICENSE_ZPAY_ENABLED"]):
        raise ValueError("payment provider must be enabled: LICENSE_ZPAY_ENABLED")
    if not _enabled(values["LICENSE_ZPAY_QUERY_ENABLED"]):
        raise ValueError(
            "payment reconciliation must be enabled: LICENSE_ZPAY_QUERY_ENABLED"
        )
    _validate_https_url(
        "LICENSE_ZPAY_BASE_URL",
        values["LICENSE_ZPAY_BASE_URL"],
        base_only=True,
    )
    _validate_provider_path(
        "LICENSE_ZPAY_CREATE_PATH", values["LICENSE_ZPAY_CREATE_PATH"]
    )
    _validate_provider_path(
        "LICENSE_ZPAY_QUERY_PATH", values["LICENSE_ZPAY_QUERY_PATH"]
    )
    _validate_channels(values["LICENSE_ZPAY_CHANNELS"])
    _validate_https_url(
        "LICENSE_ZPAY_NOTIFY_URL",
        values["LICENSE_ZPAY_NOTIFY_URL"],
        base_only=False,
    )
    _validate_https_url(
        "LICENSE_ZPAY_RETURN_URL",
        values["LICENSE_ZPAY_RETURN_URL"],
        base_only=False,
    )


def upsert_env_value(path: Path, name: str, value: str) -> None:
    target = Path(path)
    normalized = _validate_name(name)
    lines = _read_lines(target)
    prefix = f"{normalized}="
    preserved = [line for line in lines if not line.strip().startswith(prefix)]
    preserved.append(f"{normalized}={_quote_value(value)}")
    content = "\n".join(preserved) + "\n"

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=str(target.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    env_file = Path(os.environ["DEPLOY_ENV_FILE"])
    if _enabled(os.environ.get("DEPLOY_ENV_VALIDATE_ZPAY", "")):
        validate_zpay_env_file(env_file)
        return 0
    required_name = str(os.environ.get("DEPLOY_ENV_REQUIRE_NAME") or "").strip()
    if required_name:
        return 0 if has_nonempty_env_value(env_file, required_name) else 1

    name = os.environ["DEPLOY_ENV_NAME"]
    value = os.environ["DEPLOY_ENV_VALUE"]
    upsert_env_value(env_file, name, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "has_nonempty_env_value",
    "upsert_env_value",
    "validate_zpay_env_file",
]
