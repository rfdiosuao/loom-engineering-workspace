from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


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
    required_name = str(os.environ.get("DEPLOY_ENV_REQUIRE_NAME") or "").strip()
    if required_name:
        return 0 if has_nonempty_env_value(env_file, required_name) else 1

    name = os.environ["DEPLOY_ENV_NAME"]
    value = os.environ["DEPLOY_ENV_VALUE"]
    upsert_env_value(env_file, name, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["has_nonempty_env_value", "upsert_env_value"]
